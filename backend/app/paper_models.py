"""P3 isolated simulated-account contracts, never real account capabilities."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import ConfigDict, Field, StrictBool

from app.models import ExactDecimal
from app.research_models import ResearchModel

UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
SYMBOL_PATTERN = r"^[A-Z0-9_]{1,60}USDT$"


class Mutable(ResearchModel):
    model_config = ConfigDict(
        extra="forbid", frozen=False, validate_assignment=True, validate_default=True
    )


class CreatePaper(ResearchModel):
    command_id: str = Field(pattern=UUID_PATTERN)
    name: str = Field(min_length=1, max_length=60)
    initial_equity: ExactDecimal = Field(default=Decimal("1000"), gt=0)
    mode: Literal["standard", "micro_capital"] = "micro_capital"
    assumed_account_max: int = Field(default=20, ge=1, le=25)
    enable_candidate_effective_cap: StrictBool = True
    environment: Literal["OFFLINE_SCENARIO"] = "OFFLINE_SCENARIO"
    risk_day: Literal["UTC_SIMULATION_ONLY"] = "UTC_SIMULATION_ONLY"


class QuoteInput(ResearchModel):
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    price: ExactDecimal = Field(gt=0)
    step: ExactDecimal = Field(default=Decimal("0.001"), gt=0)
    tick: ExactDecimal = Field(default=Decimal("0.01"), gt=0)
    min_qty: ExactDecimal = Field(default=Decimal("0.001"), ge=0)
    min_notional: ExactDecimal = Field(default=Decimal("5"), ge=0)
    multiplier: ExactDecimal = Field(default=Decimal("1"), gt=0)
    source: Literal["MANUAL_SIMULATED_SCENARIO"] = "MANUAL_SIMULATED_SCENARIO"


class Quote(QuoteInput):
    at: datetime
    spec_version: str


class PrepareInput(ResearchModel):
    grade: Literal["NORMAL", "QUALIFIED"] = Field(
        default="NORMAL", exclude_if=lambda v: v == "NORMAL"
    )
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    direction: Literal["LONG", "SHORT"] = "LONG"
    stop: ExactDecimal = Field(gt=0)
    take_profit: ExactDecimal = Field(gt=0)
    risk_pct: ExactDecimal = Field(default=Decimal("1"), gt=0, le=2)
    exchange_leverage: int = Field(default=20, ge=1, le=100)
    assumed_liquidation: ExactDecimal = Field(gt=0)
    liquidation_buffer: ExactDecimal = Field(default=Decimal("0.01"), ge=0)
    fee_bps: ExactDecimal = Field(default=Decimal("5"), ge=0, le=100)
    slippage_bps: ExactDecimal = Field(default=Decimal("2"), ge=0, le=100)
    funding_budget_bps: ExactDecimal = Field(default=Decimal("2"), ge=0, le=100)
    quantity: ExactDecimal | None = Field(default=None, gt=0)


class OrderPlan(PrepareInput):
    entry: ExactDecimal
    quantity: ExactDecimal
    spec_version: str
    quote_at: datetime
    created_at: datetime
    expires_at: datetime
    step: ExactDecimal
    tick: ExactDecimal
    multiplier: ExactDecimal
    unit_risk: ExactDecimal
    reserved_risk: ExactDecimal
    policy_hash: str
    capability_state: Literal["SIMULATED_ASSUMPTIONS_ACCOUNT_UNKNOWN"] = (
        "SIMULATED_ASSUMPTIONS_ACCOUNT_UNKNOWN"
    )


class PaperOrder(Mutable):
    id: str
    client_order_id: str
    plan: OrderPlan
    plan_hash: str
    nonce: str
    state: Literal[
        "AWAITING_APPROVAL",
        "APPROVED",
        "SEND_PENDING",
        "RECONCILING",
        "ACKED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCELLED",
        "REJECTED",
        "INVALIDATED",
        "EXPIRED",
        "UNKNOWN_SUBMISSION",
    ]
    filled: ExactDecimal = Decimal("0")
    closed: ExactDecimal = Decimal("0")
    approved_at: datetime | None = None
    transitions: list[dict[str, str]] = Field(default_factory=list)


class Position(Mutable):
    order_id: str
    symbol: str
    direction: Literal["LONG", "SHORT"]
    quantity: ExactDecimal
    average_entry: ExactDecimal
    stop: ExactDecimal
    take_profit: ExactDecimal
    multiplier: ExactDecimal
    unit_risk: ExactDecimal
    protected: bool = True
    opened_at: datetime


class Fill(ResearchModel):
    id: str
    order_id: str
    kind: Literal["OPEN", "REDUCE", "STOP", "TAKE_PROFIT"]
    quantity: ExactDecimal
    price: ExactDecimal
    commission: ExactDecimal
    realized_pnl: ExactDecimal
    at: datetime


class PaperState(Mutable):
    schema_version: Literal["paper.v1"] = "paper.v1"
    id: str
    config: CreatePaper
    runtime_id: str
    created_at: datetime
    updated_at: datetime
    cash: ExactDecimal
    net_flows: ExactDecimal = Decimal("0")
    peak_adjusted_equity: ExactDecimal
    daily_baseline: ExactDecimal
    risk_day: str
    permanent_locks: list[str] = Field(default_factory=list)
    reduced_risk_latched: bool = Field(default=False, exclude_if=lambda v: not v)
    recovery_required: bool = False
    quotes: dict[str, Quote] = Field(default_factory=dict)
    orders: dict[str, PaperOrder] = Field(default_factory=dict)
    positions: dict[str, Position] = Field(default_factory=dict)
    fills: dict[str, Fill] = Field(default_factory=dict)
    funding: dict[str, dict[str, str]] = Field(default_factory=dict)
    ledger: list[dict[str, str]] = Field(default_factory=list)
    venue_orders: dict[str, dict[str, Any]] = Field(default_factory=dict)
    incidents: list[dict[str, str]] = Field(default_factory=list)


class PaperCommand(ResearchModel):
    session_id: str = Field(pattern=UUID_PATTERN)
    command_id: str = Field(pattern=UUID_PATTERN)
    action: Literal[
        "QUOTE",
        "PREPARE",
        "APPROVE",
        "REJECT",
        "SUBMIT",
        "FILL",
        "CANCEL",
        "RECONCILE",
        "REDUCE",
        "FUNDING",
        "FLOW",
        "KILL",
        "RECOVER",
        "RESTORE_PROTECTION",
    ]
    args: dict[str, Any] = Field(default_factory=dict)


class OrderInput(ResearchModel):
    order_id: str = Field(pattern=UUID_PATTERN)


class ApproveInput(OrderInput):
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    simulation_code: str = Field(pattern=r"^\d{6}$")
    exception_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    human_confirmed: StrictBool


class SubmitInput(OrderInput):
    scenario: Literal["NORMAL", "LOST_ACK_ACCEPTED", "LOST_ACK_REJECTED", "PROTECTION_FAILURE"] = (
        "NORMAL"
    )
    unknown_fill_pct: ExactDecimal = Field(default=Decimal("0"), ge=0, le=100)


class FillInput(OrderInput):
    fill_id: str = Field(pattern=UUID_PATTERN)
    quantity: ExactDecimal = Field(gt=0)


class ReduceInput(OrderInput):
    quantity: ExactDecimal = Field(gt=0)


class FundingInput(ResearchModel):
    event_id: str = Field(pattern=UUID_PATTERN)
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    rate: ExactDecimal = Field(ge=Decimal("-0.1"), le=Decimal("0.1"))


class FlowInput(ResearchModel):
    amount: ExactDecimal


class EmptyInput(ResearchModel):
    pass
