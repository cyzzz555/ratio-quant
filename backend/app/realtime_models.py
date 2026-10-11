"""P2 public research contracts. No account credentials or executable signals."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from app.models import Model


class StartRealtime(Model):
    watchlist: list[str] = Field(min_length=1, max_length=4)
    discovery: bool = False
    timeframe: Literal["5m", "15m"] = "5m"
    mode: Literal["RESEARCH_ONLY"] = "RESEARCH_ONLY"

    @field_validator("watchlist")
    @classmethod
    def symbols(cls, value: list[str]) -> list[str]:
        import re

        if len(set(value)) != len(value) or any(
            not re.fullmatch(r"[A-Z0-9_\u3400-\u9fff]{1,64}", s) for s in value
        ):
            raise ValueError("watchlist must contain distinct exchange symbols")
        return value


class RealtimeEvent(Model):
    kind: Literal["CONFIG", "STATE", "TRANSPORT", "BAR", "MARK", "TICK", "FAULT", "REJECTED"]
    at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class ResearchSignal(Model):
    id: str
    symbol: str
    strategy: Literal["TrendPullback"] = "TrendPullback"
    direction: Literal["LONG", "SHORT"]
    score: int = Field(ge=0, le=100)
    state: Literal["WATCHING", "CONFIRMED", "INVALIDATED", "EXPIRED"] = "WATCHING"
    discovered_at: datetime
    expires_at: datetime
    source_close_at: datetime
    updated_at: datetime
    features: dict[str, Any]
    reason: str
    executable: Literal[False] = False
    mode: Literal["RESEARCH_ONLY"] = "RESEARCH_ONLY"


class Notification(Model):
    id: str
    at: datetime
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    code: str
    symbol: str | None = None
    message: str
    delivery: Literal["IN_APP_ONLY"] = "IN_APP_ONLY"
