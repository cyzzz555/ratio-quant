import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from app.models import utc_now
from app.ws_probe import probe_ws


class FakeSocket:
    def __init__(self, messages: list[str]) -> None:
        self.messages = iter(messages)

    async def __aenter__(self) -> "FakeSocket":
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass

    async def recv(self) -> str:
        try:
            return next(self.messages)
        except StopIteration as exc:
            raise TimeoutError("fixture: no data frame") from exc


def test_ack_only_does_not_verify_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(url: str, **_: Any) -> FakeSocket:
        assert url == "wss://fstream.binance.com/market/ws/nvdausdt@kline_1m"
        return FakeSocket(['{"result":null,"id":1}'])

    monkeypatch.setattr("app.ws_probe.connect", connect)
    works, evidence, bar = asyncio.run(probe_ws("NVDAUSDT", "1" * 64, tmp_path, None))
    assert works is None and bar is None and "TimeoutError" in evidence.result


def test_matching_ws_frame_verified_and_saved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    row: list[Any],
) -> None:
    payload = json.dumps(
        {
            "e": "kline",
            "s": "NVDAUSDT",
            "E": int(utc_now().timestamp() * 1000),
            "k": {
                "s": "NVDAUSDT",
                "i": "1m",
                "x": False,
                "t": row[0],
                "T": row[6],
                "o": row[1],
                "h": row[2],
                "l": row[3],
                "c": row[4],
                "v": row[5],
            },
        }
    )
    monkeypatch.setattr("app.ws_probe.connect", lambda *_args, **_kw: FakeSocket([payload]))
    works, evidence, bar = asyncio.run(probe_ws("NVDAUSDT", "1" * 64, tmp_path, None))
    assert works is True and bar is not None and bar.is_closed is False
    assert (tmp_path / str(evidence.raw_file)).read_text() == payload
