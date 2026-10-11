"""Exact research risk mathematics; never grants account or live order permission."""

from decimal import ROUND_FLOOR, Decimal
from typing import Literal

from pydantic import Field

from app.bars import payload_hash
from app.models import ExactDecimal
from app.research_models import ResearchModel

ZERO = Decimal(0)
HUNDRED = Decimal(100)


def floor_quantity(quantity: Decimal, step: Decimal) -> Decimal:
    if quantity < 0 or step <= 0:
        raise ValueError("quantity/step invalid")
    return (quantity / step).to_integral_value(rounding=ROUND_FLOOR) * step


def losses(
    principal: Decimal, equity: Decimal, net_flows: Decimal, peak: Decimal
) -> tuple[Decimal, Decimal]:
    if principal <= 0 or peak <= 0:
        raise ValueError("principal/peak invalid")
    adjusted = equity - net_flows
    return max(ZERO, (principal - adjusted) / principal * HUNDRED), max(
        ZERO, (peak - adjusted) / peak * HUNDRED
    )


def risk_state(
    mode: str,
    principal_loss: Decimal,
    drawdown: Decimal,
    daily_loss: Decimal,
    portfolio_risk: Decimal,
    persisted: bool = False,
) -> dict[str, str]:
    multiplier = "1"
    if persisted:
        state = "PERSISTED_LOCK"
    elif mode == "standard":
        state = (
            "DRAWDOWN_LOCK"
            if drawdown >= 10
            else "DAILY_LOCK"
            if daily_loss >= 2
            else "PORTFOLIO_LOCK"
            if portfolio_risk > 5
            else "DAILY_WARNING"
            if daily_loss >= Decimal("1.5")
            else "NORMAL"
        )
    elif mode == "micro_capital":
        state = (
            "PRINCIPAL_BUDGET_BREACH"
            if principal_loss >= 50
            else "PRINCIPAL_LOCK"
            if principal_loss >= 40
            else "DRAWDOWN_LOCK"
            if drawdown >= 35
            else "DAILY_LOCK"
            if daily_loss >= 5
            else "PORTFOLIO_LOCK"
            if portfolio_risk > 5
            else "PRINCIPAL_REDUCE_RISK"
            if principal_loss >= 30
            else "DRAWDOWN_WARNING"
            if drawdown >= 25
            else "PRINCIPAL_WARNING"
            if principal_loss >= 20
            else "DAILY_WARNING"
            if daily_loss >= 3
            else "NORMAL"
        )
        multiplier = "0.5" if principal_loss >= 30 else "1"
    else:
        raise ValueError("unsupported risk mode")
    return {
        "state": state,
        "new_risk_multiplier": multiplier,
        "policy_state": "CONFIRMED_STANDARD" if mode == "standard" else "MICRO_RESEARCH_CANDIDATE",
    }


class RiskRequest(ResearchModel):
    mode: Literal["standard", "micro_capital"] = "micro_capital"
    direction: Literal["LONG", "SHORT"] = "LONG"
    equity: ExactDecimal = Field(default=Decimal("1000"), gt=0)
    principal: ExactDecimal = Field(default=Decimal("1000"), gt=0)
    net_flows: ExactDecimal = Decimal("0")
    peak: ExactDecimal = Field(default=Decimal("1000"), gt=0)
    daily_loss_pct: ExactDecimal = Field(default=Decimal("0"), ge=0)
    existing_notional: ExactDecimal = Field(default=Decimal("0"), ge=0)
    pending_notional: ExactDecimal = Field(default=Decimal("0"), ge=0)
    portfolio_risk_pct: ExactDecimal = Field(default=Decimal("0"), ge=0)
    entry: ExactDecimal = Field(default=Decimal("100"), gt=0)
    stop: ExactDecimal = Field(default=Decimal("98"), gt=0)
    risk_pct: ExactDecimal = Field(default=Decimal("1"), gt=0, le=2)
    multiplier: ExactDecimal = Field(default=Decimal("1"), gt=0)
    step: ExactDecimal = Field(default=Decimal("0.001"), gt=0)
    tick: ExactDecimal = Field(default=Decimal("0.01"), gt=0)
    min_qty: ExactDecimal = Field(default=Decimal("0.001"), ge=0)
    min_notional: ExactDecimal = Field(default=Decimal("5"), ge=0)
    extra_loss_per_unit: ExactDecimal = Field(default=Decimal("0"), ge=0)
    exchange_leverage: int = Field(default=20, ge=1, le=100)
    simulated_account_max: int | None = Field(default=None, ge=1, le=100)
    liquidation: ExactDecimal | None = None
    liquidation_buffer: ExactDecimal = Field(default=Decimal("0"), ge=0)
    exception_approved: bool = False
    enable_candidate_effective_cap: bool = False
    candidate_effective_cap: ExactDecimal = Field(default=Decimal("2"), gt=0)
    persisted_lock: bool = False


def preview(p: RiskRequest) -> dict[str, object]:
    reasons: list[str] = []
    principal_loss, drawdown = losses(p.principal, p.equity, p.net_flows, p.peak)
    state = risk_state(
        p.mode, principal_loss, drawdown, p.daily_loss_pct, p.portfolio_risk_pct, p.persisted_lock
    )
    if p.mode == "standard" and p.risk_pct > 1:
        reasons.append("STANDARD_SINGLE_RISK_MAX_1_PERCENT")
    if "LOCK" in state["state"] or "BREACH" in state["state"]:
        reasons.append(state["state"])
    direction_ok = p.stop < p.entry if p.direction == "LONG" else p.stop > p.entry
    if not direction_ok:
        reasons.append("INVALID_DIRECTIONAL_STOP")
    budget = p.equity * p.risk_pct / HUNDRED * Decimal(state["new_risk_multiplier"])
    unit_loss = abs(p.entry - p.stop) * p.multiplier + p.extra_loss_per_unit
    quantity = floor_quantity(budget / unit_loss, p.step) if unit_loss > 0 else ZERO
    notional = quantity * p.entry * p.multiplier
    margin = notional / p.exchange_leverage
    effective = (p.existing_notional + p.pending_notional + notional) / p.equity
    if quantity < p.min_qty or notional < p.min_notional:
        reasons.append("BELOW_EXCHANGE_MINIMUM_NO_ROUND_UP")
    if p.entry % p.tick or p.stop % p.tick:
        reasons.append("PRICE_NOT_TICK_ALIGNED")
    if p.exchange_leverage > 25:
        reasons.append("REJECT_USER_LEVERAGE_CAP")
    if p.simulated_account_max is None:
        reasons.append("ACCOUNT_LEVERAGE_UNKNOWN")
    elif p.exchange_leverage > p.simulated_account_max:
        reasons.append("REJECT_ACCOUNT_MAX_NO_AUTOMATIC_DOWNGRADE")
    if p.exchange_leverage > 20 and not p.exception_approved:
        reasons.append("SPECIAL_APPROVAL_REQUIRED_RESEARCH_ONLY")
    if p.enable_candidate_effective_cap and effective > p.candidate_effective_cap:
        reasons.append("CANDIDATE_EFFECTIVE_LEVERAGE_CAP")
    if p.liquidation is None:
        reasons.append("LIQUIDATION_UNKNOWN")
    elif not (
        p.liquidation + p.liquidation_buffer < p.stop < p.entry
        if p.direction == "LONG"
        else p.entry < p.stop < p.liquidation - p.liquidation_buffer
    ):
        reasons.append("STOP_NOT_BEFORE_LIQUIDATION_WITH_BUFFER")
    if p.mode == "micro_capital" and margin > p.equity * Decimal("0.25"):
        reasons.append("CANDIDATE_SINGLE_MARGIN_CAP")
    if unit_loss > 0 and p.extra_loss_per_unit / unit_loss > Decimal("0.2"):
        reasons.append("CANDIDATE_COST_RISK_RATIO")
    return {
        "status": "RESEARCH_ONLY",
        "plan_hash": payload_hash(p.model_dump(mode="json")),
        "risk_budget": str(budget),
        "quantity": str(quantity),
        "notional": str(notional),
        "theoretical_margin": str(margin),
        "effective_leverage": str(effective),
        "principal_loss_pct": str(principal_loss),
        "high_water_drawdown_pct": str(drawdown),
        "simulation_passed": not reasons,
        "reasons": reasons,
        "risk_state": state,
        "live_trading_enabled": False,
        "executable": False,
        "account_permission": "UNKNOWN",
    }


class SimulatedApproval:
    """One immutable simulation plan; consumes once even when zero quantity fills."""

    def __init__(self, plan_hash: str, budget: Decimal, quantity: Decimal) -> None:
        if budget < 0 or quantity <= 0:
            raise ValueError("invalid reservation")
        self.plan_hash, self.budget, self.quantity = plan_hash, budget, quantity
        self.consumed = False
        self.pending_risk, self.position_risk = budget, ZERO

    def consume(self, current_hash: str, filled: Decimal) -> None:
        if current_hash != self.plan_hash or self.consumed:
            raise ValueError("approval expired/changed/already consumed; no resubmission")
        if not ZERO <= filled <= self.quantity:
            raise ValueError("invalid fill")
        self.consumed = True
        self.position_risk = self.budget * filled / self.quantity
        self.pending_risk = ZERO  # unfilled remainder is cancelled, never retried automatically
