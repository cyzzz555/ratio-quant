"""Deterministic closed-bar pipeline; all decisions use recorded availability time."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from app.bars import missing_minutes, payload_hash
from app.models import Bar, exact_decimal, from_ms
from app.realtime_models import Notification, RealtimeEvent, ResearchSignal
from app.research_data import aggregate
from app.research_models import MarketContext, TrendParameters
from app.strategies import TrendPullback


class RealtimeEngine:
    def __init__(self) -> None:
        self.session_id: str | None = None
        self.state = "STOPPED"
        self.at: datetime | None = None
        self.connected = False
        self.symbols: dict[str, dict[str, Any]] = {}
        self.signals: dict[str, ResearchSignal] = {}
        self.notifications: list[Notification] = []
        self.params = TrendParameters()
        self.strategy = TrendPullback()

    def notice(
        self, code: str, message: str, severity: str = "INFO", symbol: str | None = None
    ) -> None:
        assert self.at is not None
        self.notifications.append(
            Notification.model_validate(
                dict(
                    id=payload_hash(
                        [self.session_id, len(self.notifications), self.at, code, symbol]
                    ),
                    at=self.at,
                    severity=severity,
                    code=code,
                    symbol=symbol,
                    message=message,
                )
            )
        )
        self.notifications = self.notifications[-200:]

    def validate_event(self, event: RealtimeEvent) -> None:
        if self.at is not None and event.at < self.at:
            raise ValueError("non-monotonic processing time")
        p = event.payload
        if event.kind == "MARK":
            if p["symbol"] not in self.symbols:
                raise ValueError("unknown mark symbol")
            price, stamp = exact_decimal(p["p"]), from_ms(p["E"])
            if price <= 0 or not 0 <= (event.at - stamp).total_seconds() <= 10:
                raise ValueError("stale or future mark frame, or invalid price")
        elif event.kind == "BAR":
            bar = Bar.model_validate(p["bar"])
            item = self.symbols[bar.instrument_id.rsplit(":", 1)[1]]
            if bar.available_at > event.at or bar.spec_version != item["spec"]:
                raise ValueError("unavailable bar or mismatched specification")
            if bar.is_closed and bar.close_time_utc >= event.at:
                raise ValueError("closed bar is in the future")

    def apply(self, event: RealtimeEvent) -> None:
        self.validate_event(event)
        self.at = event.at
        p = event.payload
        if event.kind == "CONFIG":
            if self.session_id is not None:
                raise ValueError("session already configured")
            self.session_id = p["session_id"]
            self.params = TrendParameters(timeframe=p["timeframe"])
            for item in p["instruments"]:
                self.symbols[item["symbol"]] = dict(
                    spec=item["spec"],
                    name_zh=item["name_zh"],
                    pool=item["pool"],
                    spec_checked_at=event.at,
                    bars={},
                    ws_at=None,
                    mark_at=None,
                    mark=None,
                    latest_price=None,
                    fatal=None,
                    last_evaluated=None,
                    quality="WARMING",
                )
            self.state = "STARTING"
            self.notice("SESSION_STARTED", "公共研究行情开始预热；账户权限未核验")
        elif event.kind == "STATE":
            self.state = p["state"]
            self.notice("SESSION_STATE", p["message"])
        elif event.kind == "TRANSPORT":
            self.connected = p["connected"]
            # A new socket must receive fresh evidence of BOTH kline and mark streams.
            for item in self.symbols.values():
                item["ws_at"] = item["mark_at"] = None
            self.notice(
                "WS_CONNECTED" if self.connected else "WS_DISCONNECTED",
                p["message"],
                "INFO" if self.connected else "WARNING",
            )
        elif event.kind == "FAULT":
            targets = [p["symbol"]] if p.get("symbol") else list(self.symbols)
            for symbol in targets:
                self.symbols[symbol]["fatal"] = p["code"]
            self.notice(p["code"], p["message"], "CRITICAL", p.get("symbol"))
        elif event.kind == "REJECTED":
            self.notice("FRAME_REJECTED", p["message"], "WARNING", p.get("symbol"))
        elif event.kind == "TICK" and p.get("spec_symbol"):
            self.symbols[p["spec_symbol"]]["spec_checked_at"] = event.at
        elif event.kind == "MARK":
            item = self.symbols[p["symbol"]]
            event_at = from_ms(p["E"])
            price = Decimal(p["p"])
            if not price.is_finite() or price <= 0:
                raise ValueError("invalid mark price")
            age = (event.at - event_at).total_seconds()
            if not 0 <= age <= 10:
                raise ValueError("stale or future mark frame")
            item["mark"] = str(price)
            item["mark_at"] = event_at
        elif event.kind == "BAR":
            bar = Bar.model_validate(p["bar"])
            symbol = bar.instrument_id.rsplit(":", 1)[1]
            item = self.symbols[symbol]
            if bar.available_at > event.at or bar.spec_version != item["spec"]:
                raise ValueError("unavailable bar or mismatched specification")
            if bar.source == "BINANCE_WS" and bar.quality == "VALID":
                item["ws_at"] = bar.exchange_event_at
                item["latest_price"] = str(bar.close)
            if bar.is_closed and bar.quality == "VALID":
                if bar.close_time_utc >= event.at:
                    raise ValueError("closed bar is in the future")
                previous = item["bars"].get(bar.open_time_utc)
                if previous is not None and self.ohlcv(previous) != self.ohlcv(bar):
                    item["fatal"] = "BAR_CONFLICT"
                    self.notice(
                        "BAR_CONFLICT", "同一分钟 OHLCV 冲突，停止该品种信号", "CRITICAL", symbol
                    )
                elif previous is None:
                    item["bars"][bar.open_time_utc] = bar
                    # Bound memory, but NEVER sum REST and WS copies of one economic minute.
                    if len(item["bars"]) > 900:
                        del item["bars"][min(item["bars"])]
                    if not p.get("seed", False) and bar.source == "BINANCE_WS":
                        self._evaluate(symbol, bar)
        for symbol, item in self.symbols.items():
            quality = self.quality(symbol)
            if quality != item["quality"]:
                self.notice(
                    "QUALITY_CHANGED",
                    quality,
                    "INFO" if quality == "HEALTHY" else "WARNING",
                    symbol,
                )
                item["quality"] = quality
            if quality != "HEALTHY":
                for signal in list(self.signals.values()):
                    if signal.symbol == symbol and signal.state in {"WATCHING", "CONFIRMED"}:
                        self.transition(signal, "INVALIDATED", quality)
        for signal in list(self.signals.values()):
            if signal.state in {"WATCHING", "CONFIRMED"} and event.at >= signal.expires_at:
                self.transition(signal, "EXPIRED", "研究观察窗口已到期")

    @staticmethod
    def ohlcv(bar: Bar) -> tuple[Decimal, ...]:
        return bar.open, bar.high, bar.low, bar.close, bar.volume

    def quality(self, symbol: str) -> str:
        item = self.symbols[symbol]
        if item["fatal"]:
            return str(item["fatal"])
        if self.state != "STREAMING":
            return self.state
        if not self.connected:
            return "DISCONNECTED"
        assert self.at is not None
        if (self.at - item["spec_checked_at"]).total_seconds() > 360:
            return "SPEC_STALE"
        for key, reason in (("ws_at", "KLINE_STALE"), ("mark_at", "MARK_STALE")):
            if item[key] is None or not 0 <= (self.at - item[key]).total_seconds() <= 20:
                return reason
        bars = list(item["bars"].values())
        if missing_minutes(bars):
            return "GAP_UNVERIFIED"
        if not bars or (self.at - max(b.close_time_utc for b in bars)).total_seconds() > 90:
            return "CLOSED_BAR_STALE"
        return "HEALTHY"

    def transition(self, signal: ResearchSignal, state: str, reason: str) -> None:
        updated = ResearchSignal.model_validate(
            {**signal.model_dump(), "state": state, "updated_at": self.at, "reason": reason}
        )
        self.signals[signal.id] = updated
        self.notice("SIGNAL_" + state, reason, "INFO", signal.symbol)

    def _evaluate(self, symbol: str, bar: Bar) -> None:
        item = self.symbols[symbol]
        assert self.at is not None
        if self.quality(symbol) != "HEALTHY":
            return
        available = [b for b in item["bars"].values() if b.available_at <= self.at]
        lower = aggregate(available, self.params.timeframe)
        hourly = aggregate(available, "1h")
        if not lower or lower[-1].close_at != bar.close_time_utc:
            return
        current = lower[-1]
        if item["last_evaluated"] is not None and current.close_at <= item["last_evaluated"]:
            return
        item["last_evaluated"] = current.close_at
        duration = timedelta(minutes=5 if self.params.timeframe == "5m" else 15)
        for signal in list(self.signals.values()):
            if signal.symbol != symbol or signal.state != "WATCHING":
                continue
            if self.at >= signal.expires_at:
                self.transition(signal, "EXPIRED", "研究观察窗口已到期")
                continue
            if current.close_at == signal.source_close_at + duration:
                anchor = Decimal(signal.features["confirmed_close"])
                follows = (
                    current.close > anchor
                    if signal.direction == "LONG"
                    else (current.close < anchor)
                )
                self.transition(
                    signal,
                    "CONFIRMED" if follows else "INVALIDATED",
                    "下一根完整闭合 K 线延续方向；仅研究信号"
                    if follows
                    else "下一根完整闭合 K 线未延续方向",
                )
        candidate = self.strategy.evaluate(
            MarketContext(
                decision_at=self.at,
                symbol=symbol,
                spec_version=item["spec"],
                bars=hourly + lower,
            ),
            self.params,
        )
        if candidate is None or candidate.candidate_id in self.signals:
            return
        signal = ResearchSignal(
            id=candidate.candidate_id,
            symbol=symbol,
            direction=candidate.direction,
            score=candidate.score,
            discovered_at=self.at,
            expires_at=self.at + duration * 2,
            source_close_at=current.close_at,
            updated_at=self.at,
            features=candidate.feature_snapshot,
            reason="观察候选：等待下一根闭合 K 线；研究阈值未获实盘批准",
        )
        self.signals[signal.id] = signal
        if len(self.signals) > 200:
            del self.signals[next(iter(self.signals))]
        self.notice("SIGNAL_WATCHING", signal.reason, "INFO", symbol)

    def snapshot(self) -> dict[str, Any]:
        instruments = []
        for symbol, item in self.symbols.items():
            bars = sorted(item["bars"].values(), key=lambda b: b.open_time_utc)
            hourly = aggregate(bars, "1h")
            regime = "UNKNOWN"
            if len(hourly) >= 12:
                fast = sum((b.close for b in hourly[-6:]), Decimal(0)) / 6
                slow = sum((b.close for b in hourly[-12:]), Decimal(0)) / 12
                regime = "UPTREND" if fast > slow else "DOWNTREND" if fast < slow else "FLAT"
            latest = next(
                (s for s in reversed(list(self.signals.values())) if s.symbol == symbol), None
            )
            instruments.append(
                dict(
                    symbol=symbol,
                    name_zh=item["name_zh"],
                    pool=item["pool"],
                    quality=self.quality(symbol),
                    closed_minutes=len(bars),
                    latest_price=item["latest_price"],
                    mark_price=item["mark"],
                    last_kline_event_at=item["ws_at"],
                    last_mark_event_at=item["mark_at"],
                    latest_closed_at=bars[-1].close_time_utc if bars else None,
                    gaps=missing_minutes(bars),
                    regime=regime,
                    strategy_priority="TrendPullback"
                    if regime in {"UPTREND", "DOWNTREND"}
                    else "UNRESOLVED",
                    scores={
                        "TrendPullback": dict(
                            value=latest.score if latest else None,
                            state="CANDIDATE" if latest else "NO_CANDIDATE_OR_WARMUP",
                        ),
                        "MeanReversion": dict(value=None, state="NOT_IMPLEMENTED"),
                        "EventDriven": dict(value=None, state="NO_VERIFIED_PROVIDER"),
                    },
                )
            )
        return dict(
            phase="P2_FIRST_INCREMENT",
            state=self.state,
            session_id=self.session_id,
            checked_at=self.at,
            connected=self.connected,
            instruments=instruments,
            signals=[s.model_dump(mode="json") for s in self.signals.values()],
            notifications=[n.model_dump(mode="json") for n in self.notifications[-30:]],
            live_trading_enabled=False,
            allow_new_risk=False,
            trading_ready=False,
            account_permission="UNKNOWN",
            persistence="LOCAL_REPLAY_PENDING_POSTGRESQL",
            parameters={
                **self.params.model_dump(mode="json"),
                "freshness_seconds": 20,
                "confirmation": "NEXT_CLOSED_BAR_CONTINUATION",
                "status": "RESEARCH_ONLY_NOT_APPROVED_FOR_LIVE",
            },
            limitations=[
                "PostgreSQL 验收未完成",
                "MeanReversion 尚未实现",
                "EventDriven 无已核验事件源",
                "Discovery 为启动时 USDT 成交额快照",
                "市场时段未分类，缺口保守阻断",
                "通知仅在本机页面显示",
            ],
        )
