import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.models import ProductFamily
from app.public_client import PublicClient


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, value: float) -> None:
        self.now += value
        if value:
            self.sleeps.append(value)


@pytest.mark.parametrize(
    "family", [ProductFamily.SPOT, ProductFamily.COIN_M_FUTURES, ProductFamily.STOCKS]
)
def test_cross_family_is_rejected(tmp_path: Path, family: ProductFamily) -> None:
    with pytest.raises(ValueError, match="family"):
        PublicClient(family, tmp_path)


@pytest.mark.parametrize(
    "path,params",
    [
        ("/fapi/v1/order", {}),
        ("/api/v3/exchangeInfo", {}),
        ("/dapi/v1/klines", {}),
        ("https://evil.example/fapi/v1/time", {}),
        ("/fapi/v1/time", {"signature": "forbidden"}),
        ("/fapi/v1/time", {"apiKey": "forbidden"}),
        ("/fapi/v1/klines", {"symbol": "NVDAUSDT", "interval": "5m"}),
        ("/fapi/v1/klines", {"symbol": "NVDAUSDT", "interval": "1m", "limit": 500}),
        ("/fapi/v1/premiumIndex", {}),
    ],
)
def test_non_public_paths_and_params_blocked(
    tmp_path: Path,
    path: str,
    params: dict[str, Any],
) -> None:
    calls = []
    transport = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200, json={}))
    with PublicClient(ProductFamily.USD_M_FUTURES, tmp_path, transport=transport) as c:
        with pytest.raises(ValueError):
            c.get(path, params)
    assert calls == []


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retry_audit_and_payload_hash(tmp_path: Path, status: int) -> None:
    calls: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(r)
        assert r.method == "GET" and "x-mbx-apikey" not in r.headers
        if len(calls) < 3:
            return httpx.Response(status, json={"error": "temporary"})
        return httpx.Response(200, json={"serverTime": 1})

    clock = Clock()
    with PublicClient(
        ProductFamily.USD_M_FUTURES,
        tmp_path,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock.time,
        min_interval=0,
    ) as c:
        result = c.get("/fapi/v1/time")
    assert result.ok and len(calls) == 3 and clock.sleeps == [1, 2]
    audits = [
        json.loads(s)
        for s in (tmp_path / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(audits) == 3 and len({x["request_id"] for x in audits}) == 1
    assert result.evidence.raw_file and (tmp_path / result.evidence.raw_file).is_file()


def test_retry_after_and_min_interval(tmp_path: Path) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return (
            httpx.Response(429, headers={"Retry-After": "7"}, json={})
            if calls == 1
            else (httpx.Response(200, json={}))
        )

    clock = Clock()
    with PublicClient(
        ProductFamily.USD_M_FUTURES,
        tmp_path,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock.time,
        min_interval=0.25,
    ) as c:
        assert c.get("/fapi/v1/time").ok
        assert c.get("/fapi/v1/time").ok
    assert clock.sleeps == [7, 0.25]


@pytest.mark.parametrize("status,delay", [(429, "120"), (418, "1")])
def test_long_retry_or_ip_ban_opens_circuit(tmp_path: Path, status: int, delay: str) -> None:
    calls = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(r)
        return httpx.Response(status, headers={"retry-after": delay}, json={"msg": "blocked"})

    clock = Clock()
    with PublicClient(
        ProductFamily.USD_M_FUTURES,
        tmp_path,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock.time,
    ) as c:
        assert not c.get("/fapi/v1/time").ok
        assert "circuit" in c.get("/fapi/v1/time").evidence.result
    assert len(calls) == 1 and clock.sleeps == []


def test_timeout_is_not_success(tmp_path: Path) -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("offline fixture", request=r)

    clock = Clock()
    with PublicClient(
        ProductFamily.USD_M_FUTURES,
        tmp_path,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock.time,
    ) as c:
        result = c.get("/fapi/v1/time")
    assert not result.ok and "ReadTimeout" in result.evidence.result
    assert result.evidence.http_status is None and result.evidence.raw_hash is None


def test_invalid_json_is_preserved(tmp_path: Path) -> None:
    with PublicClient(
        ProductFamily.USD_M_FUTURES,
        tmp_path,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"not-json")),
    ) as c:
        result = c.get("/fapi/v1/time")
    assert not result.ok and "INVALID_JSON" in result.evidence.result
    assert (tmp_path / str(result.evidence.raw_file)).read_bytes() == b"not-json"


def test_exchange_reported_weight_limit_is_used(tmp_path: Path) -> None:
    clock = Clock()
    data = {
        "rateLimits": [
            {
                "rateLimitType": "REQUEST_WEIGHT",
                "interval": "MINUTE",
                "intervalNum": 1,
                "limit": 2400,
            }
        ]
    }
    with PublicClient(
        ProductFamily.USD_M_FUTURES,
        tmp_path,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=data, headers={"x-mbx-used-weight-1m": "1200"})
        ),
        clock=clock.time,
        sleep=clock.sleep,
        min_interval=0,
    ) as client:
        assert client.get("/fapi/v1/exchangeInfo").ok
        assert client.exchange_minute_weight_limit == 2400
        assert client.get("/fapi/v1/time").ok


def test_global_and_local_weight_budget(tmp_path: Path) -> None:
    clock = Clock()
    with PublicClient(
        ProductFamily.USD_M_FUTURES,
        tmp_path,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})),
        clock=clock.time,
        sleep=clock.sleep,
        min_interval=0,
    ) as client:
        for _ in range(121):
            assert client.get("/fapi/v1/time").ok
    assert clock.sleeps == [60]


def test_retry_exhaustion_preserves_cooldown(tmp_path: Path) -> None:
    clock = Clock()
    calls = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(r)
        return httpx.Response(429, json={}, headers={"retry-after": "garbage"})

    with PublicClient(
        ProductFamily.USD_M_FUTURES,
        tmp_path,
        transport=httpx.MockTransport(handler),
        clock=clock.time,
        sleep=clock.sleep,
        min_interval=0,
    ) as client:
        assert not client.get("/fapi/v1/time").ok
        assert "circuit" in client.get("/fapi/v1/time").evidence.result
    assert len(calls) == 3
