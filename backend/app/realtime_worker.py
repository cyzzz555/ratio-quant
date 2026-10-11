"""Single leased public market worker. Only fixed allowlisted GETs and WS receive."""

import asyncio
import fcntl
import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

from websockets.asyncio.client import connect

from app.bars import payload_hash, rest_bar, ws_bar
from app.market_catalog import display_name, visible_rows
from app.models import ProductFamily, from_ms, utc_now
from app.public_client import PublicClient, ReadResult
from app.realtime_engine import RealtimeEngine
from app.realtime_models import RealtimeEvent, StartRealtime
from app.realtime_store import ReplayJournal


def usd_m_rows(data: Any) -> dict[str, dict[str, Any]]:
    # Public directory visibility is NOT account trading permission.
    return {
        r["symbol"]: r
        for r in visible_rows(data)
        if r["quoteAsset"] == r["marginAsset"]
        and r["quoteAsset"] in {"USDT", "USDC"}
        and r.get("st", 1) == 1
        and r["contractType"] in {"PERPETUAL", "TRADIFI_PERPETUAL"}
    }


def discovery_symbols(
    rows: dict[str, dict[str, Any]], ticker: Any, watchlist: list[str]
) -> list[str]:
    if not isinstance(ticker, list):
        raise ValueError("invalid all-market ticker")
    ranked: list[tuple[Decimal, str]] = []
    for item in ticker:
        symbol = item.get("symbol")
        if symbol not in rows or symbol in watchlist or rows[symbol]["quoteAsset"] != "USDT":
            continue
        volume = Decimal(item["quoteVolume"])
        if volume.is_finite() and volume >= 0:
            ranked.append((volume, symbol))
    return [s for _, s in sorted(ranked, reverse=True)[:2]]


class RealtimeBusy(ValueError):
    pass


class RealtimeController:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.engine = RealtimeEngine()
        self.task: asyncio.Task[None] | None = None
        self.timer: asyncio.Task[None] | None = None
        self.stop_event = asyncio.Event()
        self.lease: TextIO | None = None
        self.journal: ReplayJournal | None = None
        self.failure: str | None = None
        self.directory: Path | None = None

    def emit(self, kind: str, **payload: Any) -> None:
        event = RealtimeEvent.model_validate(dict(kind=kind, at=utc_now(), payload=payload))
        self.engine.validate_event(event)
        if self.journal:
            self.journal.append(event)  # Archive BEFORE applying any research decision.
        self.engine.apply(event)

    def snapshot(self) -> dict[str, Any]:
        return {
            **self.engine.snapshot(),
            "failure": self.failure,
            "worker_active": self.task is not None and not self.task.done(),
            "journal": str(self.directory.relative_to(self.root) / "events.jsonl")
            if self.directory
            else None,
        }

    async def start(self, request: StartRealtime) -> dict[str, Any]:
        if self.task is not None and not self.task.done():
            raise RealtimeBusy("实时行情已运行；先停止再修改关注池")
        parent = self.root / ".runtime/realtime"
        parent.mkdir(parents=True, exist_ok=True)
        lease = (parent / "worker.lock").open("a")
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lease.close()
            raise RealtimeBusy("另一个进程正在运行实时行情") from exc
        self.lease, self.stop_event = lease, asyncio.Event()
        self.engine, self.failure = RealtimeEngine(), None
        self.engine.state = "STARTING"
        self.directory = parent / str(uuid4())
        try:
            self.journal = ReplayJournal(self.directory / "events.jsonl")
        except OSError:
            lease.close()
            self.lease = None
            self.engine.state = "FAILED"
            raise
        self.task = asyncio.create_task(self._run(request))
        return self.snapshot()

    async def stop(self) -> dict[str, Any]:
        self.stop_event.set()
        if self.task and not self.task.done():
            self.emit("STATE", state="STOPPING", message="正在停止公共行情连接")
        return self.snapshot()

    async def shutdown(self) -> None:
        await self.stop()
        if self.task:
            # No cancellation of sync HTTP mid-write; let its bounded timeout finish.
            await self.task

    async def _get(
        self, client: PublicClient, path: str, params: dict[str, str | int] | None = None
    ) -> ReadResult:
        if self.stop_event.is_set():
            raise InterruptedError("session stopped")
        result = await asyncio.to_thread(client.get, path, params)
        if self.stop_event.is_set():
            raise InterruptedError("session stopped")
        if not result.ok:
            raise ValueError("public GET unavailable: " + result.evidence.result)
        return result

    async def _backfill(self, client: PublicClient, symbol: str, warmup: bool = False) -> None:
        time_result = await self._get(client, "/fapi/v1/time")
        server = from_ms(time_result.data["serverTime"])
        if abs((utc_now() - server).total_seconds()) > 5:
            raise ValueError("local/server clock drift exceeds research bound")
        end = int(server.timestamp() // 60) * 60000 - 1
        item = self.engine.symbols[symbol]
        bars = sorted(item["bars"].values(), key=lambda b: b.open_time_utc)
        start = end + 1 - 780 * 60000
        if bars and not warmup:
            start = int(bars[-1].open_time_utc.timestamp() * 1000) - 60000
            for a, b in zip(bars, bars[1:], strict=False):
                if b.open_time_utc - a.open_time_utc > timedelta(minutes=1):
                    start = int(a.open_time_utc.timestamp() * 1000) + 60000
                    break
        if end - start > 1440 * 60000:
            raise ValueError("backfill exceeds 1440-minute bound; restart research session")
        while start <= end:
            response = await self._get(
                client,
                "/fapi/v1/klines",
                dict(
                    symbol=symbol,
                    interval="1m",
                    limit=99,
                    startTime=start,
                    endTime=min(end, start + 99 * 60000 - 1),
                ),
            )
            if not isinstance(response.data, list):
                raise ValueError("invalid backfill response")
            for row in response.data:
                bar = rest_bar(
                    row,
                    symbol=symbol,
                    spec_version=item["spec"],
                    received_at=response.evidence.timestamp,
                    server_time_before_request=server,
                    response_hash=response.evidence.raw_hash or "0" * 64,
                )
                if not start <= int(bar.open_time_utc.timestamp() * 1000) <= end:
                    raise ValueError("REST returned a bar outside the requested range")
                self.emit("BAR", bar=bar.model_dump(mode="json"), seed=True)
            start += 99 * 60000

    async def _ticker(self) -> None:
        assert self.directory is not None
        try:
            counter = 0
            while not self.stop_event.is_set():
                self.emit("TICK")
                if counter % 15 == 0 and self.journal:
                    self.journal.append(None, payload_hash(self.engine.snapshot()))
                    # Includes HTTP audit bodies: bounded disk footprint for one session.
                    size = sum(p.stat().st_size for p in self.directory.rglob("*") if p.is_file())
                    if size > 256 * 1024 * 1024:
                        raise OSError("research session disk budget exhausted")
                counter += 1
                await asyncio.sleep(2)
        except Exception as exc:
            self.failure = type(exc).__name__ + ": audit storage unavailable"
            self.engine.connected = False
            self.engine.state = "FAILED"
            self.stop_event.set()

    async def _run(self, request: StartRealtime) -> None:
        assert self.directory is not None
        try:
            with PublicClient(
                ProductFamily.USD_M_FUTURES, self.directory / "rest", attempts=1
            ) as client:
                response = await self._get(client, "/fapi/v1/exchangeInfo")
                rows = usd_m_rows(response.data)
                if not all(s in rows for s in request.watchlist):
                    raise ValueError("watchlist contains unverified or non-trading USD-M contract")
                discovery: list[str] = []
                if request.discovery:
                    ticker = await self._get(client, "/fapi/v1/ticker/24hr")
                    discovery = discovery_symbols(rows, ticker.data, request.watchlist)
                aliases = json.loads((self.root / "config/market_names.zh.json").read_text())
                self.emit(
                    "CONFIG",
                    session_id=self.directory.name,
                    timeframe=request.timeframe,
                    instruments=[
                        dict(
                            symbol=s,
                            name_zh=display_name(rows[s], aliases) or "中文名待补充",
                            spec=payload_hash(rows[s]),
                            pool="WATCHLIST" if s in request.watchlist else "DISCOVERY",
                        )
                        for s in request.watchlist + discovery
                    ],
                )
                self.timer = asyncio.create_task(self._ticker())
                for symbol in self.engine.symbols:
                    await self._backfill(client, symbol, warmup=True)
                streams = "/".join(
                    f"{s.lower()}@kline_1m/{s.lower()}@markPrice@1s" for s in self.engine.symbols
                )
                url = "wss://fstream.binance.com/market/stream?streams=" + streams
                delay = 1
                while not self.stop_event.is_set():
                    try:
                        async with connect(
                            url, open_timeout=10, close_timeout=2, max_size=262144, proxy=None
                        ) as socket:
                            self.emit(
                                "TRANSPORT",
                                connected=True,
                                message="连接已建立，等待逐品种新鲜 K 线与标记价",
                            )
                            # REST repairs are seeds, never retroactive signal triggers.
                            for symbol in self.engine.symbols:
                                await self._backfill(client, symbol)
                            self.emit("STATE", state="STREAMING", message="实时公共行情接收中")
                            last_rest, last_spec = utc_now(), utc_now()
                            samples: dict[tuple[str, str], float] = {}
                            delay = 1
                            while not self.stop_event.is_set():
                                now = utc_now()
                                if (now - last_spec).total_seconds() >= 300:
                                    result = await self._get(client, "/fapi/v1/exchangeInfo")
                                    latest = usd_m_rows(result.data)
                                    for symbol, item in self.engine.symbols.items():
                                        if (
                                            symbol not in latest
                                            or payload_hash(latest[symbol]) != (item["spec"])
                                        ):
                                            self.emit(
                                                "FAULT",
                                                symbol=symbol,
                                                code="SPEC_CHANGED",
                                                message="合约规格变化，需重新启动并核验",
                                            )
                                        else:
                                            # Journal the verified specification timestamp.
                                            self.emit("TICK", spec_symbol=symbol)
                                    last_spec = utc_now()
                                if (now - last_rest).total_seconds() >= 60:
                                    for symbol in self.engine.symbols:
                                        await self._backfill(client, symbol)
                                    last_rest = utc_now()
                                try:
                                    raw = await asyncio.wait_for(socket.recv(), timeout=2)
                                except TimeoutError:
                                    continue  # Timer marks silent stalls stale.
                                received = utc_now()
                                message = json.loads(raw)
                                data = message.get("data", message)
                                symbol, kind = data.get("s"), data.get("e")
                                if symbol not in self.engine.symbols or kind not in {
                                    "kline",
                                    "markPriceUpdate",
                                }:
                                    continue
                                if data.get("st", 1) != 1:
                                    self.emit(
                                        "FAULT",
                                        symbol=symbol,
                                        code="WRONG_PRODUCT_FAMILY",
                                        message="收到非 USD-M 事件，停止该品种信号",
                                    )
                                    continue
                                key = (symbol, kind)
                                closed = kind == "kline" and data["k"].get("x") is True
                                if not closed and received.timestamp() - samples.get(key, 0) < 5:
                                    continue
                                samples[key] = received.timestamp()
                                wire = raw.decode() if isinstance(raw, bytes) else raw
                                try:
                                    if kind == "kline":
                                        bar = ws_bar(
                                            message,
                                            symbol=symbol,
                                            spec_version=self.engine.symbols[symbol]["spec"],
                                            received_at=received,
                                            response_hash=hashlib.sha256(wire.encode()).hexdigest(),
                                        )
                                        self.emit(
                                            "BAR", bar=bar.model_dump(mode="json"), raw_text=wire
                                        )
                                    else:
                                        self.emit(
                                            "MARK",
                                            symbol=symbol,
                                            E=data["E"],
                                            p=data["p"],
                                            raw_text=wire,
                                        )
                                except (ValueError, KeyError, TypeError) as exc:
                                    self.emit(
                                        "REJECTED",
                                        symbol=symbol,
                                        raw_text=wire,
                                        message="丢弃无效或过期行情：" + type(exc).__name__,
                                    )
                                    raise
                    except InterruptedError:
                        raise
                    except Exception as exc:
                        self.emit(
                            "TRANSPORT",
                            connected=False,
                            message="断线或无效数据："
                            + type(exc).__name__
                            + "；补数后仍需新鲜 WS 证据",
                        )
                        try:
                            await asyncio.wait_for(self.stop_event.wait(), timeout=delay)
                        except TimeoutError:
                            pass
                        delay = min(delay * 2, 30)
        except InterruptedError:
            pass
        except Exception as exc:
            self.failure = type(
                exc
            ).__name__  # No raw exception that might contain environment data.
        finally:
            self.stop_event.set()
            if self.timer:
                self.timer.cancel()
                await asyncio.gather(self.timer, return_exceptions=True)
            try:
                self.emit("TRANSPORT", connected=False, message="公共行情连接已停止")
                self.emit(
                    "STATE",
                    state="FAILED" if self.failure else "STOPPED",
                    message="采集失败，请检查日志并重新启动" if self.failure else "已停止",
                )
                if self.journal:
                    self.journal.append(None, payload_hash(self.engine.snapshot()))
            except (OSError, ValueError):
                self.engine.state, self.engine.connected = "FAILED", False
                self.failure = "AUDIT_UNAVAILABLE"
            finally:
                if self.journal:
                    self.journal.close()
                    self.journal = None
                if self.lease:
                    self.lease.close()
                    self.lease = None
