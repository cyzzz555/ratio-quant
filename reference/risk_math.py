"""Reference-only pure risk math for offline tests, NOT a production trading/risk engine.

IMPORTANT: no exchange calls, no trade submission, no account access. This module does
NOT validate market liquidity, funding, liquidation buffers, exchange filters or fees.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN


def dec(x: str | int | Decimal) -> Decimal:
    if isinstance(x, float):
        raise TypeError("Binary float forbidden for monetary inputs")
    return Decimal(str(x))


def initial_principal_loss_pct(p0: Decimal, equity: Decimal, net_later_flows: Decimal = Decimal("0")) -> Decimal:
    """Loss as fraction of initial capital, adjusting *later* deposits and withdrawals."""
    if p0 <= 0:
        raise ValueError("Initial principal must be positive")
    adj = equity - net_later_flows
    return max(Decimal("0"), (p0 - adj) / p0 * Decimal("100"))


def high_water_drawdown_pct(high_water_adjusted_equity: Decimal, current_adjusted_equity: Decimal) -> Decimal:
    if high_water_adjusted_equity <= 0:
        raise ValueError("Historical high water mark must be positive")
    return max(Decimal("0"), (high_water_adjusted_equity - current_adjusted_equity) / high_water_adjusted_equity * Decimal("100"))


def risk_budget(equity: Decimal, risk_percent: Decimal) -> Decimal:
    if equity <= 0 or not (Decimal("0") <= risk_percent <= Decimal("100")):
        raise ValueError("Invalid equity or risk percentage")
    return equity * risk_percent / Decimal("100")


def floor_to_step(qty: Decimal, step: Decimal) -> Decimal:
    if step <= 0 or qty < 0:
        raise ValueError("Invalid quantity or step")
    return (qty / step).to_integral_value(rounding=ROUND_DOWN) * step


def linear_contract_qty(
    *,
    budget: Decimal,
    entry: Decimal,
    stop: Decimal,
    multiplier: Decimal,
    step: Decimal,
    extra_loss_per_unit: Decimal = Decimal("0"),
) -> Decimal:
    """Floor q by risk. Does not authorize the trade; outside checks mandatory."""
    if budget <= 0 or entry <= 0 or stop <= 0 or multiplier <= 0 or extra_loss_per_unit < 0:
        raise ValueError("Invalid inputs")
    unit_loss = abs(entry - stop) * multiplier + extra_loss_per_unit
    if unit_loss <= 0:
        raise ValueError("Stop loss must be nonzero")
    return floor_to_step(budget / unit_loss, step)


def linear_notional(qty: Decimal, entry: Decimal, multiplier: Decimal = Decimal("1")) -> Decimal:
    if qty < 0 or entry <= 0 or multiplier <= 0:
        raise ValueError("Invalid inputs")
    return qty * entry * multiplier


def theoretical_initial_margin(notional: Decimal, exchange_leverage: int) -> Decimal:
    if notional < 0 or exchange_leverage < 1 or exchange_leverage > 25:
        raise ValueError("Invalid notional or user leverage cap exceeded")
    return notional / Decimal(exchange_leverage)


def gross_effective_leverage(sum_abs_positions_and_pending_notional: Decimal, equity: Decimal) -> Decimal:
    if equity <= 0 or sum_abs_positions_and_pending_notional < 0:
        raise ValueError("Invalid equity or notional")
    return sum_abs_positions_and_pending_notional / equity


def leverage_preference_check(requested: int, account_instrument_max: int | None) -> str:
    """Only hard cap and known account entitlement; 10-20 is user normal preference.

    21-25 is a *proposed* special approval process and is NOT permission to trade.
    """
    if requested < 1 or requested > 25:
        return "REJECT_USER_HARD_CAP"
    if account_instrument_max is None:
        return "BLOCK_UNVERIFIED_ACCOUNT_LEVERAGE"
    if requested > account_instrument_max:
        return "REJECT_EXCHANGE_OR_ACCOUNT_MAX"
    if requested > 20:
        return "PENDING_SPECIAL_APPROVAL_RESEARCH_ONLY"
    if requested < 10:
        return "LOWER_THAN_PREFERRED_RANGE_REQUIRES_NEW_PLAN"
    return "PREFERRED_RANGE_NOT_TRADE_AUTHORIZATION"


def directional_stop_precedes_liquidation(side: str, entry: Decimal, stop: Decimal, liquidation: Decimal) -> bool:
    """Necessary condition ONLY; not sufficient safety buffer or executable order proof."""
    if side == "LONG":
        return liquidation < stop < entry
    if side == "SHORT":
        return entry < stop < liquidation
    raise ValueError("side must be LONG or SHORT")
