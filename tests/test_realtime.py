"""Deterministic offline P2 failures, replay and public-only operation tests."""

import asyncio
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.bars import payload_hash
from app.main import create_app
from app.models import Bar, ProductFamily, utc_now
from app.public_client import PublicClient
from app.realtime_engine import RealtimeEngine
from app.realtime_models import RealtimeEvent, StartRealtime
from app.realtime_store import ReplayJournal, replay
from app.realtime_worker import RealtimeBusy, RealtimeController, discovery_symbols, usd_m_rows
from app.settings import ROOT
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

ORIGIN = datetime(2026, 1, 1, tzinfo=UTC)
NOW = ORIGIN + timedelta(minutes=764)
SYMBOL = "XAUUSDT"


def event(kind: str, at: datetime = NOW, **payload: Any) -> RealtimeEvent:
    return RealtimeEvent.model_validate(dict(kind=kind, at=at, payload=payload))


def bar(
    index: int,
    received: datetime,
    source: str = "BINANCE_REST",
    closed: bool = True,
    price: str | None = None,
) -> Bar:
    opened = ORIGIN + timedelta(minutes=index)
    value = price or (
        str(100 + index // 60)
        if index < 750
        else "110"
        if index < 760
        else "114"
        if index < 765
        else "115"
    )
    from decimal import Decimal

    amount = Decimal(value)
    return Bar.model_validate(
        dict(
            instrument_id=f"BINANCE:USD_M_FUTURES:{SYMBOL}",
            product_family="USD_M_FUTURES",
            open_time_utc=opened,
            close_time_utc=opened + timedelta(milliseconds=59999),
            open=value,
            high=str(amount + 2),
            low=str(amount - 2),
            close=value,
            volume="100",
            is_closed=closed,
            exchange_event_at=received if source == "BINANCE_WS" else None,
            received_at=received,
            processed_at=received,
            available_at=received,
            source=source,
            raw_hash=payload_hash([index, value]),
            response_hash="1" * 64,
            spec_version="v1",
        )
    )


def prepared(skip: int | None = None) -> tuple[RealtimeEngine, list[RealtimeEvent]]:
    inputs = [
        event(
            "CONFIG",
            session_id="test-session",
            timeframe="5m",
            instruments=[dict(symbol=SYMBOL, name_zh="黄金", spec="v1", pool="WATCHLIST")],
        )
    ]
    inputs += [
        event("BAR", bar=bar(i, NOW).model_dump(mode="json"), seed=True)
        for i in range(764)
        if i != skip
    ]
    inputs += [
        event("TRANSPORT", connected=True, message="test connected"),
        event("STATE", state="STREAMING", message="test streaming"),
    ]
    engine = RealtimeEngine()
    for entry in inputs:
        engine.apply(entry)
    return engine, inputs


def fresh(engine: RealtimeEngine, index: int, *, closed: bool = True) -> list[RealtimeEvent]:
    stamp = ORIGIN + timedelta(minutes=index + 1, milliseconds=100)
    inputs = []
    assert engine.at is not None
    cursor = engine.at + timedelta(seconds=10)
    while cursor < stamp:
        inputs.extend(
            [
                event("MARK", cursor, symbol=SYMBOL, E=int(cursor.timestamp() * 1000), p="114"),
                event(
                    "BAR",
                    cursor,
                    bar=bar(index, cursor, "BINANCE_WS", False).model_dump(mode="json"),
                ),
            ]
        )
        cursor += timedelta(seconds=10)
    if (stamp - engine.symbols[SYMBOL]["spec_checked_at"]).total_seconds() >= 300:
        inputs.append(event("TICK", stamp, spec_symbol=SYMBOL))
    inputs.extend(
        [
            event("MARK", stamp, symbol=SYMBOL, E=int(stamp.timestamp() * 1000), p="114"),
            event(
                "BAR", stamp, bar=bar(index, stamp, "BINANCE_WS", closed).model_dump(mode="json")
            ),
        ]
    )
    for entry in inputs:
        engine.apply(entry)
    return inputs


def test_real_trend_two_stage_and_economic_dedupe() -> None:
    engine, _ = prepared()
    assert not engine.signals  # REST warmup does not generate historical candidates.
    fresh(engine, 764)
    assert len(engine.signals) == 1
    signal = next(iter(engine.signals.values()))
    assert signal.state == "WATCHING" and signal.executable is False
    volume = sum(b.volume for b in engine.symbols[SYMBOL]["bars"].values())
    for _ in range(3):
        fresh(engine, 764)
    assert len(engine.signals) == 1
    assert sum(b.volume for b in engine.symbols[SYMBOL]["bars"].values()) == volume
    for index in range(765, 770):
        fresh(engine, index)
    assert engine.signals[signal.id].state == "CONFIRMED"
    assert engine.snapshot()["allow_new_risk"] is False
    assert engine.snapshot()["instruments"][0]["scores"]["MeanReversion"]["value"] is None
    assert engine.snapshot()["instruments"][0]["regime"] == "UPTREND"


def test_forming_never_generates_or_confirms() -> None:
    engine, _ = prepared()
    fresh(engine, 764, closed=False)
    assert not engine.signals and len(engine.symbols[SYMBOL]["bars"]) == 764
    fresh(engine, 764)
    original = next(iter(engine.signals.values()))
    for index in range(765, 769):
        fresh(engine, index)
    fresh(engine, 769, closed=False)
    assert engine.signals[original.id].state == "WATCHING"


def test_gap_repair_is_not_a_retroactive_signal() -> None:
    engine, _ = prepared(skip=763)
    fresh(engine, 764)
    assert engine.quality(SYMBOL) == "GAP_UNVERIFIED" and not engine.signals
    at = engine.at
    assert at is not None
    engine.apply(event("BAR", at, bar=bar(763, at).model_dump(mode="json"), seed=True))
    assert engine.quality(SYMBOL) == "HEALTHY" and not engine.signals


@pytest.mark.parametrize("failure", ["disconnect", "stale", "conflict", "spec"])
def test_bad_data_invalidates_watchers_and_fail_closed(failure: str) -> None:
    engine, _ = prepared()
    fresh(engine, 764)
    at = engine.at
    assert at is not None
    if failure == "disconnect":
        engine.apply(event("TRANSPORT", at, connected=False, message="test lost"))
    elif failure == "stale":
        engine.apply(event("TICK", at + timedelta(seconds=21)))
    elif failure == "spec":
        engine.apply(event("FAULT", at, symbol=SYMBOL, code="SPEC_CHANGED", message="test change"))
    else:
        engine.apply(event("BAR", at, bar=bar(764, at, price="115").model_dump(mode="json")))
    assert next(iter(engine.signals.values())).state == "INVALIDATED"
    assert engine.quality(SYMBOL) != "HEALTHY"
    assert engine.snapshot()["trading_ready"] is False


def test_reconnect_requires_fresh_both_streams_not_socket_ack() -> None:
    engine, _ = prepared()
    fresh(engine, 764)
    at = engine.at
    assert at is not None
    engine.apply(event("TRANSPORT", at, connected=False, message="lost"))
    engine.apply(event("TRANSPORT", at, connected=True, message="ack"))
    assert engine.quality(SYMBOL) == "KLINE_STALE"
    engine.apply(event("BAR", at, bar=bar(764, at, "BINANCE_WS").model_dump(mode="json")))
    assert engine.quality(SYMBOL) == "MARK_STALE"
    engine.apply(event("MARK", at, symbol=SYMBOL, E=int(at.timestamp() * 1000), p="114"))
    assert engine.quality(SYMBOL) == "HEALTHY"
    assert next(iter(engine.signals.values())).state == "INVALIDATED"


def test_future_available_and_stale_mark_rejected() -> None:
    engine, _ = prepared()
    with pytest.raises(ValueError, match="unavailable"):
        engine.apply(event("BAR", bar=bar(763, NOW + timedelta(seconds=1)).model_dump(mode="json")))
    with pytest.raises(ValueError, match="stale or future"):
        engine.apply(
            event(
                "MARK",
                symbol=SYMBOL,
                E=int((NOW - timedelta(seconds=11)).timestamp() * 1000),
                p="100",
            )
        )


def test_signal_expires_with_continuing_freshness() -> None:
    engine, _ = prepared()
    fresh(engine, 764)
    signal = next(iter(engine.signals.values()))
    assert engine.at is not None
    cursor = engine.at + timedelta(seconds=10)
    while cursor <= signal.expires_at:
        index = int((cursor - ORIGIN).total_seconds() // 60)
        if (cursor - engine.symbols[SYMBOL]["spec_checked_at"]).total_seconds() >= 300:
            engine.apply(event("TICK", cursor, spec_symbol=SYMBOL))
        engine.apply(
            event("MARK", cursor, symbol=SYMBOL, E=int(cursor.timestamp() * 1000), p="114")
        )
        # REST repairs maintain coverage, but do not retroactively confirm the watcher.
        engine.apply(
            event("BAR", cursor, bar=bar(index - 1, cursor).model_dump(mode="json"), seed=True)
        )
        engine.apply(
            event(
                "BAR", cursor, bar=bar(index, cursor, "BINANCE_WS", False).model_dump(mode="json")
            )
        )
        cursor += timedelta(seconds=10)
    assert engine.quality(SYMBOL) == "HEALTHY"
    assert engine.signals[signal.id].state == "EXPIRED"
    assert not engine.signals[signal.id].executable


def test_replay_exact_decisions_and_tamper_detection(tmp_path: Path) -> None:
    engine, inputs = prepared()
    inputs += fresh(engine, 764)
    for index in range(765, 770):
        inputs += fresh(engine, index)
    path = tmp_path / "events.jsonl"
    journal = ReplayJournal(path)
    for entry in inputs:
        journal.append(entry)
    journal.append(None, payload_hash(engine.snapshot()))
    journal.close()
    result = replay(path)
    assert result["snapshot"] == engine.snapshot() and result["checkpoints"] == 1
    lines = path.read_text().splitlines()
    changed = json.loads(lines[0])
    changed["event"]["payload"]["timeframe"] = "15m"
    lines[0] = json.dumps(changed)
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="corrupted"):
        replay(path)


def test_journal_budget_and_missing_checkpoint_fail(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    journal = ReplayJournal(path, max_bytes=1)
    with pytest.raises(OSError, match="budget"):
        journal.append(event("TICK"))
    journal.close()
    with pytest.raises(ValueError, match="requires events"):
        replay(path)


def row(symbol: str, **updates: Any) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "baseAsset": symbol.removesuffix("USDT"),
        "status": "TRADING",
        "quoteAsset": "USDT",
        "marginAsset": "USDT",
        "contractType": "PERPETUAL",
        **updates,
    }


def test_per_instrument_family_and_discovery_same_currency() -> None:
    rows = usd_m_rows(
        {
            "symbols": [
                row("BTCUSDT"),
                row("ETHUSDT"),
                row("MUUSDT"),
                row("CMUSDT", st=2),
                row("USDCTEST", quoteAsset="USDC", marginAsset="USDC"),
            ]
        }
    )
    assert "CMUSDT" not in rows
    selected = discovery_symbols(
        rows,
        [
            dict(symbol="BTCUSDT", quoteVolume="9000"),
            dict(symbol="MUUSDT", quoteVolume="20"),
            dict(symbol="ETHUSDT", quoteVolume="100"),
            dict(symbol="USDCTEST", quoteVolume="999999"),
        ],
        ["BTCUSDT"],
    )
    assert selected == ["ETHUSDT", "MUUSDT"]


def test_ticker_get_weight_and_no_credentials(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    with PublicClient(
        ProductFamily.USD_M_FUTURES,
        tmp_path,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    ) as client:
        result = client.get("/fapi/v1/ticker/24hr")
        assert result.ok and client.spent[-1][1] == 40
        with pytest.raises(ValueError):
            client.get("/fapi/v1/order")
    assert all(r.method == "GET" and "x-mbx-apikey" not in r.headers for r in requests)


def test_start_validation() -> None:
    for watchlist in [["BTCUSDT"] * 2, ["bad"], ["BTCUSDT"] * 5]:
        with pytest.raises(ValueError):
            StartRealtime(watchlist=watchlist)
    with pytest.raises(ValueError):
        StartRealtime.model_validate(dict(watchlist=["BTCUSDT"], api_key="PLACEHOLDER"))


def test_lease_stop_and_restart_never_autorun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_run(self: RealtimeController, _: StartRealtime) -> None:
        await self.stop_event.wait()
        self.engine.state = "STOPPED"
        assert self.lease and self.journal
        self.lease.close()
        self.lease = None
        self.journal.close()
        self.journal = None

    monkeypatch.setattr(RealtimeController, "_run", fake_run)

    async def scenario() -> None:
        first, second = RealtimeController(tmp_path), RealtimeController(tmp_path)
        assert second.snapshot()["state"] == "STOPPED"
        await first.start(StartRealtime(watchlist=["BTCUSDT"]))
        with pytest.raises(RealtimeBusy):
            await second.start(StartRealtime(watchlist=["BTCUSDT"]))
        await first.shutdown()
        await second.start(StartRealtime(watchlist=["BTCUSDT"]))
        await second.shutdown()

    asyncio.run(scenario())


def test_api_origin_readonly_stream_and_no_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copytree(ROOT / "config", tmp_path / "config")
    app = create_app(tmp_path)

    async def fake_start(self: RealtimeController, _: StartRealtime) -> dict[str, Any]:
        return self.snapshot()

    monkeypatch.setattr(RealtimeController, "start", fake_start)
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as client:
        headers = {"origin": "http://127.0.0.1:5173"}
        assert (
            client.post("/api/v1/realtime/start", json={"watchlist": ["BTCUSDT"]}).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/realtime/start", json={"watchlist": ["BTCUSDT"]}, headers=headers
            ).status_code
            == 202
        )
        assert (
            client.post(
                "/api/v1/realtime/stop", json={}, headers={"origin": "https://evil.test"}
            ).status_code
            == 403
        )
        assert client.post("/api/v1/orders", json={}, headers=headers).status_code == 404
        assert client.get("/health/ready").json()["allow_new_risk"] is False
        with client.websocket_connect(
            "ws://127.0.0.1:8000/api/v1/stream", headers=headers
        ) as stream:
            assert stream.receive_json()["live_trading_enabled"] is False
            stream.send_text("start")
            with pytest.raises(WebSocketDisconnect):
                stream.receive_json()
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "ws://127.0.0.1:8000/api/v1/stream", headers={"origin": "https://evil.test"}
            ):
                pass


def test_worker_disconnect_backfill_reconnect_and_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models import Evidence, utc_now
    from app.public_client import ReadResult
    from app.realtime_worker import RealtimeController

    shutil.copytree(ROOT / "config", tmp_path / "config")
    connections: list[str] = []
    repairs: list[bool] = []
    controller = RealtimeController(tmp_path)

    async def fake_get(
        self: RealtimeController, _: PublicClient, path: str, params: Any = None
    ) -> ReadResult:
        assert path == "/fapi/v1/exchangeInfo"
        return ReadResult(
            {"symbols": [row(SYMBOL)]},
            Evidence(
                source="OFFLINE_FIXTURE",
                timestamp=utc_now(),
                result="fixture",
                http_status=200,
            ),
            0,
        )

    async def fake_fill(
        self: RealtimeController, _: PublicClient, symbol: str, warmup: bool = False
    ) -> None:
        repairs.append(warmup)

    class FakeSocket:
        def __init__(self) -> None:
            self.calls = 0

        async def __aenter__(self) -> "FakeSocket":
            return self

        async def __aexit__(self, *_: Any) -> None:
            pass

        async def recv(self) -> str:
            self.calls += 1
            if len(connections) == 1:
                raise OSError("offline fixture disconnect")
            if self.calls > 1:
                controller.stop_event.set()
                raise InterruptedError("test complete")
            return json.dumps(
                {
                    "e": "markPriceUpdate",
                    "s": SYMBOL,
                    "E": int(utc_now().timestamp() * 1000),
                    "p": "100",
                    "st": 1,
                }
            )

    def fake_connect(url: str, **kwargs: Any) -> FakeSocket:
        assert url.startswith("wss://fstream.binance.com/market/stream?streams=")
        assert kwargs["proxy"] is None
        connections.append(url)
        return FakeSocket()

    monkeypatch.setattr(RealtimeController, "_get", fake_get)
    monkeypatch.setattr(RealtimeController, "_backfill", fake_fill)
    monkeypatch.setattr("app.realtime_worker.connect", fake_connect)

    async def scenario() -> None:
        await controller.start(StartRealtime(watchlist=[SYMBOL]))
        assert controller.task
        await asyncio.wait_for(controller.task, 4)

    asyncio.run(scenario())
    assert len(connections) == 2 and repairs == [True, False, False]
    assert controller.snapshot()["state"] == "STOPPED"
    assert controller.snapshot()["live_trading_enabled"] is False
    assert controller.directory
    result = replay(controller.directory / "events.jsonl")
    assert result["snapshot"]["state"] == "STOPPED"
    assert any(n["code"] == "WS_DISCONNECTED" for n in result["snapshot"]["notifications"])


def test_rejected_frame_is_journalled_without_poisoning_replay(tmp_path: Path) -> None:
    controller = RealtimeController(tmp_path)
    at = utc_now()
    controller.journal = ReplayJournal(tmp_path / "events.jsonl")
    controller.emit(
        "CONFIG",
        session_id="fixture",
        timeframe="5m",
        instruments=[dict(symbol=SYMBOL, spec="v1", name_zh="黄金", pool="WATCHLIST")],
    )
    sequence = controller.journal.sequence
    with pytest.raises(ValueError):
        controller.emit(
            "MARK", symbol=SYMBOL, E=int((at - timedelta(seconds=30)).timestamp() * 1000), p="100"
        )
    assert controller.journal.sequence == sequence
    controller.emit("REJECTED", symbol=SYMBOL, message="offline stale frame", raw_text="fixture")
    controller.journal.append(None, payload_hash(controller.engine.snapshot()))
    controller.journal.close()
    assert replay(tmp_path / "events.jsonl")["checkpoints"] == 1


def test_confirmed_signal_invalidates_after_disconnect() -> None:
    engine, _ = prepared()
    fresh(engine, 764)
    identifier = next(iter(engine.signals))
    for index in range(765, 770):
        fresh(engine, index)
    assert engine.signals[identifier].state == "CONFIRMED"
    assert engine.at
    engine.apply(event("TRANSPORT", engine.at, connected=False, message="offline disconnect"))
    assert engine.signals[identifier].state == "INVALIDATED"
