"""Single audited HTTP client, explicit family, public GET allowlist only."""

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.models import Evidence, ProductFamily, utc_now

MARKET_DOC = (
    "https://developers.binance.com/en/docs/catalog/"
    "core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data"
)
WS_DOC = (
    "https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/"
    "websocket-market-streams/Important-WebSocket-Change-Notice"
)
ALLOWED: dict[str, tuple[int, set[str]]] = {
    "/fapi/v1/time": (1, set()),
    "/fapi/v1/exchangeInfo": (1, set()),
    "/fapi/v1/klines": (1, {"symbol", "interval", "limit", "startTime", "endTime"}),
    "/fapi/v1/premiumIndex": (1, {"symbol"}),
    "/fapi/v1/fundingRate": (1, {"symbol", "limit", "startTime", "endTime"}),
    "/fapi/v1/tradingSchedule": (5, set()),
    "/fapi/v1/ticker/24hr": (40, set()),  # all-symbol snapshot; conservative audited weight
}


@dataclass(frozen=True)
class ReadResult:
    data: Any
    evidence: Evidence
    received_monotonic: float

    @property
    def ok(self) -> bool:
        return self.evidence.http_status == 200 and self.data is not None


class PublicClient:
    def __init__(
        self,
        family: ProductFamily,
        audit_dir: Path,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        min_interval: float = 0.25,
        attempts: int = 3,
    ) -> None:
        if family != ProductFamily.USD_M_FUTURES:
            raise ValueError("P0 adapter supports USD_M_FUTURES only; no implicit family fallback")
        if attempts < 1 or min_interval < 0:
            raise ValueError("invalid retry / rate settings")
        self.family, self.audit_dir = family, audit_dir
        self.sleep, self.clock = sleep, clock
        self.min_interval, self.attempts = min_interval, attempts
        self.last_request = float("-inf")
        self.cooldown_until = float("-inf")
        self.exchange_minute_weight_limit: int | None = None
        self.spent: list[tuple[float, int]] = []
        audit_dir.mkdir(parents=True, exist_ok=True)
        self._http = httpx.Client(
            base_url="https://fapi.binance.com",
            timeout=httpx.Timeout(10),
            follow_redirects=False,
            transport=transport,
            trust_env=False,
        )

    def __enter__(self) -> "PublicClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self._http.close()

    def _audit(self, event: dict[str, Any], payload: bytes | None) -> Evidence:
        digest = hashlib.sha256(payload).hexdigest() if payload is not None else None
        raw_file = None
        if digest:
            raw_file = f"{digest}.bin"
            path = self.audit_dir / raw_file
            if not path.exists():
                path.write_bytes(payload or b"")
        event.update(raw_hash=digest, raw_file=raw_file)
        with (self.audit_dir / "requests.jsonl").open("a") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return Evidence(
            source=event["url"],
            timestamp=event["received_at"],
            result=event["result"],
            request_id=event["request_id"],
            http_status=event["http_status"],
            raw_hash=digest,
            raw_file=raw_file,
        )

    def get(self, path: str, params: dict[str, str | int] | None = None) -> ReadResult:
        params = params or {}
        if path not in ALLOWED or not set(params) <= ALLOWED[path][1]:
            raise ValueError(
                "Only allowlisted public market GET paths and parameters are permitted"
            )
        if "symbol" in params:
            import re

            if not re.fullmatch(r"[A-Z0-9_\u3400-\u9fff]{1,64}", str(params["symbol"])):
                raise ValueError("invalid symbol")
        if path.endswith("klines") and (
            params.get("interval") != "1m" or not 1 <= int(params.get("limit", 50)) <= 99
        ):
            raise ValueError("P0 samples only 1m bars with limit 1..99 (weight=1)")
        if path.endswith(("premiumIndex", "fundingRate")) and "symbol" not in params:
            raise ValueError("symbol required to bound request weight")
        weight = ALLOWED[path][0]
        request_id = str(uuid4())
        for attempt in range(1, self.attempts + 1):
            url = str(httpx.URL("https://fapi.binance.com" + path, params=params))
            event = dict(
                request_id=request_id,
                attempt=attempt,
                method="GET",
                url=url,
                product_family=self.family.value,
                sent_at=utc_now().isoformat(),
                received_at=utc_now().isoformat(),
                http_status=None,
                result="",
                weight=weight,
            )
            if self.clock() < self.cooldown_until:
                event["result"] = "UNAVAILABLE: rate-limit circuit open; no HTTP request sent"
                return ReadResult(None, self._audit(event, None), self.clock())
            # Conservative local weighted budget: <=120 weight / rolling minute.
            self.spent = [(t, w) for t, w in self.spent if self.clock() - t < 60]
            if sum(w for _, w in self.spent) + weight > 120:
                self.sleep(max(0, 60 - (self.clock() - self.spent[0][0])))
                self.spent = [(t, w) for t, w in self.spent if self.clock() - t < 60]
            self.sleep(max(0, self.min_interval - (self.clock() - self.last_request)))
            self.last_request = self.clock()
            self.spent.append((self.last_request, weight))
            event["sent_at"] = utc_now().isoformat()
            payload, data, retry, delay = None, None, False, float(2 ** (attempt - 1))
            try:
                response = self._http.get(path, params=params)
                event["received_at"] = utc_now().isoformat()
                event["http_status"] = response.status_code
                event["response_headers"] = {
                    k: v
                    for k, v in response.headers.items()
                    if k in {"retry-after", "date", "x-mbx-used-weight-1m", "content-type"}
                }
                payload = response.content
                try:
                    # Preserve decimals even when external payload uses JSON numeric literals.
                    from decimal import Decimal

                    data = json.loads(payload, parse_float=Decimal)
                except (ValueError, UnicodeDecodeError) as exc:
                    event["result"] = f"INVALID_JSON: {type(exc).__name__}: {exc}"
                else:
                    event["result"] = f"HTTP {response.status_code}"
                retry = response.status_code == 429 or response.status_code >= 500
                if path == "/fapi/v1/exchangeInfo" and response.status_code == 200:
                    if isinstance(data, dict) and isinstance(data.get("rateLimits"), list):
                        for limit in data["rateLimits"]:
                            if (
                                isinstance(limit, dict)
                                and limit.get("rateLimitType") == "REQUEST_WEIGHT"
                                and limit.get("interval") == "MINUTE"
                                and limit.get("intervalNum") == 1
                                and type(limit.get("limit")) is int
                                and limit["limit"] > 0
                            ):
                                self.exchange_minute_weight_limit = limit["limit"]
                if response.status_code in {429, 418}:
                    header = response.headers.get("retry-after")
                    if header:
                        try:
                            delay = max(delay, float(header))
                        except ValueError:
                            try:
                                delay = max(
                                    delay,
                                    (parsedate_to_datetime(header) - utc_now()).total_seconds(),
                                )
                            except (ValueError, TypeError, OverflowError):
                                pass  # malformed header: retain exponential fallback
                    self.cooldown_until = self.clock() + delay
                    if response.status_code == 418 or delay > 60:
                        self.cooldown_until = self.clock() + max(delay, 60)
                        retry = False
                used = response.headers.get("x-mbx-used-weight-1m", "0")
                ceiling = self.exchange_minute_weight_limit or 1200
                event["exchange_minute_weight_limit"] = self.exchange_minute_weight_limit
                if used.isdigit() and int(used) >= int(ceiling * 0.9):
                    self.cooldown_until = self.clock() + 60
                    retry = False
            except httpx.RequestError as exc:
                event["received_at"] = utc_now().isoformat()
                event["result"] = f"UNAVAILABLE: {type(exc).__name__}: {exc}"
                retry = True
            evidence = self._audit(event, payload)
            if not retry or attempt == self.attempts:
                return ReadResult(data, evidence, self.clock())
            self.sleep(delay)
        raise AssertionError("unreachable")
