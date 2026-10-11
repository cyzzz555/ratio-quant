"""Versioned evidence and exact-value market contracts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


def from_ms(value: int) -> datetime:
    if type(value) is not int:
        raise ValueError("epoch milliseconds must be integer")
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=value)


def exact_decimal(value: Any) -> Decimal:
    if not isinstance(value, (str, Decimal)):
        raise ValueError("price/amount must be Decimal or decimal string, never float")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("non-finite amount")
    return result


ExactDecimal = Annotated[Decimal, BeforeValidator(exact_decimal)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="after")
    @classmethod
    def aware_utc(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("naive timestamp is forbidden")
            return value.astimezone(UTC)
        return value


class ProductFamily(StrEnum):
    USD_M_FUTURES = "USD_M_FUTURES"
    COIN_M_FUTURES = "COIN_M_FUTURES"
    SPOT = "SPOT"
    STOCKS = "STOCKS"


class CapabilityState(StrEnum):
    VERIFIED_PUBLIC = "VERIFIED_PUBLIC"
    VERIFIED_ACCOUNT = "VERIFIED_ACCOUNT"
    NEEDS_AUTHORIZED_CHECK = "NEEDS_AUTHORIZED_CHECK"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class Underlying(Model):
    id: str
    asset_class_candidate: str
    exchange_reported_type: str | None = None
    exchange_reported_base_asset: str | None = None
    name: str | None = None
    native_exchange: str | None = None
    mapping_state: Literal["UNVERIFIED"] = "UNVERIFIED"
    # baseAsset is not enough evidence to assert an exact stock / commodity contract mapping.


class Instrument(Model):
    id: str
    underlying_id: str
    venue: Literal["BINANCE"] = "BINANCE"
    symbol: str = Field(pattern=r"^[A-Z0-9_]+$")
    product_family_probed: ProductFamily
    product_family_verified: ProductFamily | None = None
    contract_type: str | None = None
    quote_asset: str | None = None
    margin_asset: str | None = None
    spec_version: str | None = None
    session_model_version: str | None = None
    price_formation_model: Literal["UNVERIFIED"] = "UNVERIFIED"


class Evidence(Model):
    source: str
    timestamp: datetime
    result: str
    request_id: str | None = None
    http_status: int | None = None
    raw_hash: str | None = None
    raw_file: str | None = None


class Capability(Model):
    schema_version: Literal["phase0.v2"] = "phase0.v2"
    venue: Literal["BINANCE"] = "BINANCE"
    product_family: str
    symbol: str
    capability_state: CapabilityState
    first_verified_at: datetime | None = None
    verified_at: datetime  # probe timestamp, NOT proof that all abilities are verified
    public_exchangeinfo_visible: bool | None = None
    account_trade_permission: Literal["UNKNOWN"] = "UNKNOWN"
    eligibility: Literal["UNVERIFIED"] = "UNVERIFIED"
    max_public_leverage: int | None = None
    max_account_leverage: int | None = None
    isolated_supported: bool | None = None
    reduce_only_supported: bool | None = None
    stop_type_supported: list[str] | None = None
    mark_price_available: bool | None = None
    funding_data_available: bool | None = None
    historical_bars_available: bool | None = None
    websocket_works: bool | None = None
    trading_status: str | None = None
    history_start_at: datetime | None = None
    history_start_scope: Literal["EARLIEST_RETURNED_BY_QUERY", "UNVERIFIED"] = "UNVERIFIED"
    instrument: Instrument
    underlying: Underlying
    evidence: list[Evidence]
    notes: list[str]


class Phase0Report(Model):
    schema_version: Literal["phase0-report.v2"] = "phase0-report.v2"
    run_id: str
    started_at: datetime
    generated_at: datetime
    live_trading_enabled: Literal[False] = False
    approval_mode: Literal["HUMAN"] = "HUMAN"
    trade_adapter: Literal["PAPER_BROKER"] = "PAPER_BROKER"
    account_check_performed: Literal[False] = False
    product_families_probed: list[ProductFamily]
    documentation_urls: list[str]
    raw_directory: str
    instruments: list[Capability]

    @model_validator(mode="after")
    def consistency(self) -> "Phase0Report":
        if self.started_at > self.generated_at or not self.instruments:
            raise ValueError("invalid report chronology or empty instruments")
        if len({x.symbol for x in self.instruments}) != len(self.instruments):
            raise ValueError("duplicate capability symbol")
        if any(x.capability_state == CapabilityState.VERIFIED_ACCOUNT for x in self.instruments):
            raise ValueError("P0 never verifies account permissions")
        return self


class Bar(Model):
    schema_version: Literal["bar.v1"] = "bar.v1"
    venue: Literal["BINANCE"] = "BINANCE"
    instrument_id: str
    product_family: ProductFamily
    timeframe: Literal["1m"] = "1m"
    open_time_utc: datetime
    close_time_utc: datetime
    open: ExactDecimal
    high: ExactDecimal
    low: ExactDecimal
    close: ExactDecimal
    volume: ExactDecimal
    is_closed: bool
    exchange_event_at: datetime | None  # REST does not provide WS event time E
    received_at: datetime
    processed_at: datetime
    available_at: datetime
    source: Literal["BINANCE_REST", "BINANCE_WS"]
    raw_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    response_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    spec_version: str
    session_type: Literal["UNVERIFIED"] = "UNVERIFIED"
    session_model_version: str | None = None
    quality: Literal["VALID", "STALE", "PARTIAL"] = "VALID"

    @model_validator(mode="after")
    def integrity(self) -> "Bar":
        if self.open_time_utc.second or self.open_time_utc.microsecond:
            raise ValueError("1m open must be minute-aligned")
        if self.close_time_utc - self.open_time_utc != timedelta(milliseconds=59999):
            raise ValueError("invalid 1m duration")
        if min(self.open, self.high, self.low, self.close) <= 0 or self.volume < 0:
            raise ValueError("invalid OHLCV signs")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("inconsistent OHLC")
        if self.received_at > self.processed_at or self.available_at != self.processed_at:
            raise ValueError("invalid processing chronology")
        return self

    @property
    def key(self) -> tuple[str, str, str, datetime, str]:
        return (self.venue, self.instrument_id, self.timeframe, self.open_time_utc, self.source)
