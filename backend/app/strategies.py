"""Point-in-time, closed-bar research plugins. Scores are not probabilities."""

from datetime import timedelta
from decimal import Decimal
from typing import Literal, Protocol

from app.bars import payload_hash
from app.research_models import BacktestRequest, CandidateSignal, MarketContext, ResearchBar


def mean(rows: list[ResearchBar]) -> Decimal:
    return sum((b.close for b in rows), Decimal(0)) / len(rows)


class Strategy(Protocol):
    identifier: str

    def evaluate(
        self, context: MarketContext, params: BacktestRequest
    ) -> CandidateSignal | None: ...


class TrendPullback:
    identifier = "TrendPullback"

    def evaluate(self, context: MarketContext, params: BacktestRequest) -> CandidateSignal | None:
        hourly = [b for b in context.bars if b.timeframe == "1h"]
        lower = [b for b in context.bars if b.timeframe == params.timeframe]
        if len(hourly) < params.slow_window or len(lower) < max(
            params.pullback_window + 1, params.stop_window
        ):
            return None
        recent = lower[-max(params.pullback_window + 1, params.stop_window) :]
        duration = timedelta(minutes=5 if params.timeframe == "5m" else 15)
        if (
            any(b.quality != "VALID" for b in recent)
            or any(
                b.open_at - a.open_at != duration for a, b in zip(recent, recent[1:], strict=False)
            )
            or any(
                b.open_at - a.open_at != timedelta(hours=1)
                for a, b in zip(
                    hourly[-params.slow_window :], hourly[-params.slow_window + 1 :], strict=False
                )
            )
        ):
            return None
        fast, slow = mean(hourly[-params.fast_window :]), mean(hourly[-params.slow_window :])
        prior_mean = mean(lower[-params.pullback_window - 1 : -1])
        current, previous = lower[-1], lower[-2]
        direction: Literal["LONG", "SHORT"] | None = (
            "LONG"
            if fast > slow and previous.close <= prior_mean < current.close
            else "SHORT"
            if fast < slow and previous.close >= prior_mean > current.close
            else None
        )
        if direction is None:
            return None
        snapshot = {
            "hourly_fast": str(fast),
            "hourly_slow": str(slow),
            "pullback_mean": str(prior_mean),
            "confirmed_close": str(current.close),
            "spec_version": context.spec_version,
            "parameters": params.model_dump(mode="json"),
        }
        identifier = payload_hash(
            [self.identifier, context.symbol, current.close_at.isoformat(), snapshot]
        )
        return CandidateSignal(
            candidate_id=identifier,
            strategy_id=self.identifier,
            strategy_version="research.1",
            instrument_id=f"BINANCE:USD_M_FUTURES:{context.symbol}",
            direction=direction,
            score=60,
            discovered_at=context.decision_at,
            expiry_at=context.decision_at + duration,
            feature_snapshot=snapshot,
            explanation=["已闭合 1h 均线趋势与低周期回拉后收盘恢复一致；研究窗口未批准"],
            confirmation_rule="CLOSED_BAR_ONLY",
            invalidation_rule="参数、规格或数据变化即失效",
        )


class MeanReversion:
    identifier = "MeanReversion"

    def evaluate(self, context: MarketContext, params: BacktestRequest) -> CandidateSignal | None:
        # Interface retained until instrument-specific mean-reversion assumptions are validated.
        return None


class EventDriven:
    identifier = "EventDriven"

    def evaluate(self, context: MarketContext, params: BacktestRequest) -> CandidateSignal | None:
        # MarketContext rejects events unavailable at decision time. No invented provider feed.
        return None


_plugins: list[Strategy] = [TrendPullback(), MeanReversion(), EventDriven()]
PLUGINS: dict[str, Strategy] = {s.identifier: s for s in _plugins}
