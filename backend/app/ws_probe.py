"""Bounded market WS receipt test; no subscribe/order messages are transmitted."""

import asyncio
import hashlib
import json
from pathlib import Path

from websockets.asyncio.client import connect

from app.bars import ws_bar
from app.models import Bar, Evidence, utc_now


async def probe_ws(
    symbol: str,
    spec_version: str,
    raw_dir: Path,
    session_version: str | None,
    timeout: float = 6,
) -> tuple[bool | None, Evidence, Bar | None]:
    url = f"wss://fstream.binance.com/market/ws/{symbol.lower()}@kline_1m"
    raw_hash = raw_file = None
    http_status = None
    try:
        async with asyncio.timeout(timeout):
            async with connect(url, open_timeout=4, close_timeout=1, max_size=262144) as ws:
                while True:
                    raw = await ws.recv()
                    received = utc_now()
                    payload = raw.encode() if isinstance(raw, str) else raw
                    raw_hash = hashlib.sha256(payload).hexdigest()
                    raw_file = f"{raw_hash}.bin"
                    (raw_dir / raw_file).write_bytes(payload)
                    message = json.loads(payload)
                    data = message.get("data", message)
                    if data.get("e") != "kline":
                        continue  # Connection / ACK is not a data-frame success.
                    bar = ws_bar(
                        message,
                        symbol=symbol,
                        spec_version=spec_version,
                        received_at=received,
                        response_hash=raw_hash,
                        session_model_version=session_version,
                    )
                    if bar.quality != "VALID":
                        raise ValueError("stale WS frame")
                    return (
                        True,
                        Evidence(
                            source=url,
                            timestamp=received,
                            result="Matching fresh 1m kline received",
                            raw_hash=raw_hash,
                            raw_file=raw_file,
                        ),
                        bar,
                    )
    except (TimeoutError, OSError, ValueError, KeyError) as exc:
        error = f"UNAVAILABLE: {type(exc).__name__}: {exc}"
    except Exception as exc:
        # websocket protocol / handshake failures must remain observable, not fake success.
        error = f"UNAVAILABLE: {type(exc).__name__}: {exc}"
        response = getattr(exc, "response", None)
        http_status = getattr(response, "status_code", None)
        body = getattr(response, "body", None)
        if isinstance(body, bytes):
            raw_hash = hashlib.sha256(body).hexdigest()
            raw_file = f"{raw_hash}.bin"
            (raw_dir / raw_file).write_bytes(body)
    return (
        None,
        Evidence(
            source=url,
            timestamp=utc_now(),
            result=error,
            http_status=http_status,
            raw_hash=raw_hash,
            raw_file=raw_file,
        ),
        None,
    )
