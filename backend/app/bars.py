"""Normalize REST / WS without inventing event timestamps or unobserved prices."""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from app.models import Bar, ProductFamily, from_ms, utc_now


def payload_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def rest_bar(
    row: Any,
    *,
    symbol: str,
    spec_version: str,
    received_at: datetime,
    server_time_before_request: datetime | None,
    response_hash: str,
    session_model_version: str | None = None,
) -> Bar:
    if not isinstance(row, list) or len(row) != 12:
        raise ValueError("REST kline must have exactly 12 fields")
    opened, closed = from_ms(row[0]), from_ms(row[6])
    processed = utc_now()
    # REST has no closed flag: conservative server-time lower bound, never local time alone.
    is_closed = server_time_before_request is not None and closed < server_time_before_request
    return Bar(
        instrument_id=f"BINANCE:USD_M_FUTURES:{symbol}",
        product_family=ProductFamily.USD_M_FUTURES,
        open_time_utc=opened,
        close_time_utc=closed,
        open=row[1],
        high=row[2],
        low=row[3],
        close=row[4],
        volume=row[5],
        is_closed=is_closed,
        exchange_event_at=None,
        received_at=received_at,
        processed_at=processed,
        available_at=processed,
        source="BINANCE_REST",
        raw_hash=payload_hash(row),
        response_hash=response_hash,
        spec_version=spec_version,
        quality="VALID" if server_time_before_request is not None else "PARTIAL",
        session_model_version=session_model_version,
    )


def ws_bar(
    message: Any,
    *,
    symbol: str,
    spec_version: str,
    received_at: datetime,
    response_hash: str,
    session_model_version: str | None = None,
) -> Bar:
    if not isinstance(message, dict):
        raise ValueError("WS message must be object")
    message = message.get("data", message)
    if message.get("e") != "kline" or message.get("s") != symbol:
        raise ValueError("not the requested kline event")
    k = message["k"]
    if k["s"] != symbol or k["i"] != "1m" or type(k["x"]) is not bool:
        raise ValueError("wrong symbol/interval/closed flag")
    event_at = from_ms(message["E"])
    if event_at > received_at + timedelta(seconds=5):
        raise ValueError("WS event is in the future; clock verification required")
    if k["x"] and event_at < from_ms(k["T"]):
        raise ValueError("closed flag precedes bar close time")
    processed = utc_now()
    return Bar(
        instrument_id=f"BINANCE:USD_M_FUTURES:{symbol}",
        product_family=ProductFamily.USD_M_FUTURES,
        open_time_utc=from_ms(k["t"]),
        close_time_utc=from_ms(k["T"]),
        open=k["o"],
        high=k["h"],
        low=k["l"],
        close=k["c"],
        volume=k["v"],
        is_closed=k["x"],
        exchange_event_at=event_at,
        received_at=received_at,
        processed_at=processed,
        available_at=processed,
        source="BINANCE_WS",
        raw_hash=payload_hash(message),
        response_hash=response_hash,
        spec_version=spec_version,
        session_model_version=session_model_version,
        quality="STALE" if received_at - event_at > timedelta(seconds=10) else "VALID",
    )


def missing_minutes(bars: list[Bar]) -> list[dict[str, Any]]:
    """Observe gaps only. Session closure vs outage classification remains UNVERIFIED."""
    times = sorted({b.open_time_utc for b in bars if b.is_closed})
    return [
        {
            "after": a.isoformat(),
            "before": b.isoformat(),
            "missing_count": int((b - a).total_seconds() // 60) - 1,
            "classification": "UNVERIFIED",
        }
        for a, b in zip(times, times[1:], strict=False)
        if b - a > timedelta(minutes=1)
    ]
