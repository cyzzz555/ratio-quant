"""Research contracts; parameters and simulated fills never authorize trading."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from app.models import ExactDecimal, Model


class ResearchModel(Model):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class ResearchBar(ResearchModel):
    symbol: str
    timeframe: str
    open_at: datetime
    close_at: datetime
    open: ExactDecimal
    high: ExactDecimal
    low: ExactDecimal
    close: ExactDecimal
    volume: ExactDecimal
    is_closed: bool
    quality: Literal["VALID", "GAP", "UNCONFIRMED"]
    raw_hashes: list[str]

    @model_validator(mode="after")
    def integrity(self) -> "ResearchBar":
        minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1d": 1440}
        if self.timeframe not in minutes:
            raise ValueError("unknown research timeframe")
        from datetime import timedelta

        if self.close_at - self.open_at != timedelta(
            minutes=minutes[self.timeframe], milliseconds=-1
        ):
            raise ValueError("invalid research bar duration")
        if min(self.open, self.high, self.low, self.close) <= 0 or self.volume < 0:
            raise ValueError("invalid research OHLCV signs")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("inconsistent research OHLC")
        return self


class HistoricalEvent(ResearchModel):
    event_id: str
    event_type: str
    published_at: datetime
    available_at: datetime
    source: str
    revision_id: str
    source_license: str
    payload_hash: str

    @model_validator(mode="after")
    def valid_time(self) -> "HistoricalEvent":
        if self.available_at < self.published_at:
            raise ValueError("event cannot be available before publication")
        return self


class MarketContext(ResearchModel):
    decision_at: datetime
    symbol: str
    spec_version: str
    bars: list[ResearchBar]
    events: list[HistoricalEvent] = Field(default_factory=list)
    mode: Literal["RESEARCH_ONLY"] = "RESEARCH_ONLY"

    @model_validator(mode="after")
    def no_future(self) -> "MarketContext":
        if any(b.symbol != self.symbol for b in self.bars):
            raise ValueError("context symbol mismatch")
        if len({(b.timeframe, b.open_at) for b in self.bars}) != len(self.bars):
            raise ValueError("context duplicate bars")
        if any(not b.is_closed or b.close_at >= self.decision_at for b in self.bars):
            raise ValueError("context contains future or unclosed bars")
        if any(e.available_at > self.decision_at for e in self.events):
            raise ValueError("event not yet available")
        return self


class CandidateSignal(ResearchModel):
    candidate_id: str
    strategy_id: str
    strategy_version: str
    instrument_id: str
    direction: Literal["LONG", "SHORT"]
    score: int = Field(ge=0, le=100)
    discovered_at: datetime
    expiry_at: datetime
    feature_snapshot: dict[str, Any]
    explanation: list[str]
    confirmation_rule: str
    invalidation_rule: str
    status: Literal["RESEARCH_ONLY"] = "RESEARCH_ONLY"
    executable: Literal[False] = False


class DatasetRequest(ResearchModel):
    symbol: str = Field(pattern=r"^[A-Z0-9_\u3400-\u9fff]{1,64}$")
    days: int = Field(default=7, ge=1, le=14)


class BacktestRequest(ResearchModel):
    dataset_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    strategy: Literal["TrendPullback"] = "TrendPullback"
    timeframe: Literal["5m", "15m"] = "5m"
    fast_window: int = Field(default=6, ge=2, le=30)
    slow_window: int = Field(default=12, ge=4, le=60)
    pullback_window: int = Field(default=6, ge=2, le=30)
    stop_window: int = Field(default=5, ge=2, le=30)
    max_holding_bars: int = Field(default=12, ge=1, le=100)
    initial_equity: ExactDecimal = Field(default=Decimal("1000"), gt=0)
    risk_pct: ExactDecimal = Field(default=Decimal("1"), gt=0, le=2)
    fee_bps: ExactDecimal = Field(default=Decimal("5"), ge=0, le=100)
    slippage_bps: ExactDecimal = Field(default=Decimal("2"), ge=0, le=100)
    spread_bps: ExactDecimal = Field(default=Decimal("1"), ge=0, le=100)
    participation_pct: ExactDecimal = Field(default=Decimal("1"), gt=0, le=10)
    reward_risk: ExactDecimal = Field(default=Decimal("2"), ge=1, le=5)
    simulated_multiplier: ExactDecimal = Field(default=Decimal("1"), gt=0)
    simulated_exchange_leverage: int = Field(default=20, ge=1, le=20)
    status: Literal["RESEARCH_ONLY"] = "RESEARCH_ONLY"

    @model_validator(mode="after")
    def windows(self) -> "BacktestRequest":
        if self.fast_window >= self.slow_window:
            raise ValueError("fast window must be below slow window")
        return self
