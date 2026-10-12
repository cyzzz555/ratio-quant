"""Deterministic isolated PaperBroker. No imports of exchange HTTP/WS clients."""

from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from app.bars import payload_hash
from app.paper_models import (
    ApproveInput,
    CreatePaper,
    EmptyInput,
    Fill,
    FillInput,
    FlowInput,
    FundingInput,
    OrderInput,
    OrderPlan,
    PaperCommand,
    PaperOrder,
    PaperState,
    Position,
    PrepareInput,
    Quote,
    QuoteInput,
    ReduceInput,
    SubmitInput,
)
from app.risk import RiskRequest, floor_quantity, losses, preview, risk_state

D = Decimal
ACTIVE = {"AWAITING_APPROVAL", "APPROVED", "ACKED", "PARTIALLY_FILLED", "UNKNOWN_SUBMISSION"}
FINANCIAL_LOCKS = {"PRINCIPAL_LOCK", "PRINCIPAL_BUDGET_BREACH", "DRAWDOWN_LOCK", "DAILY_LOCK"}


class PaperError(ValueError):
    pass


def simulation_code(nonce: str, extra: bool = False) -> str:
    # Public dummy challenge, never an authentication credential or real 2FA.
    return str(
        int(payload_hash([nonce, "EXTRA" if extra else "PRIMARY"])[:12], 16) % 1000000
    ).zfill(6)


def create_state(config: CreatePaper, runtime_id: str, at: datetime) -> PaperState:
    return PaperState(
        id=config.command_id,
        config=config,
        runtime_id=runtime_id,
        created_at=at,
        updated_at=at,
        cash=config.initial_equity,
        peak_adjusted_equity=config.initial_equity,
        daily_baseline=config.initial_equity,
        risk_day=at.date().isoformat(),
    )


class PaperEngine:
    def __init__(
        self,
        state: PaperState,
        *,
        legacy_submit_trace: bool = False,
        persist_reduced_rule: bool = True,
    ) -> None:
        self.state = state
        self.legacy_submit_trace = legacy_submit_trace
        self.persist_reduced_rule = persist_reduced_rule
        self.at = state.updated_at
        self.result: dict[str, Any] = {}

    def transition(self, order: PaperOrder, status: str, reason: str) -> None:
        order.state = status  # type: ignore[assignment]
        order.transitions.append({"at": self.at.isoformat(), "state": status, "reason": reason})

    def incident(self, reason: str) -> None:
        self.state.incidents.append({"at": self.at.isoformat(), "reason": reason})
        self.state.recovery_required = True

    def amount(self, kind: str, amount: Decimal, reference: str) -> None:
        self.state.cash += amount
        self.state.ledger.append(
            {"at": self.at.isoformat(), "kind": kind, "amount": str(amount), "reference": reference}
        )

    def metrics(self) -> dict[str, Decimal]:
        s = self.state
        unrealized = notional = position_risk = pending_risk = margin = D(0)
        for position in s.positions.values():
            mark = s.quotes[position.symbol].price
            sign = D(1) if position.direction == "LONG" else D(-1)
            unrealized += (
                (mark - position.average_entry) * position.quantity * position.multiplier * sign
            )
            nominal = position.quantity * mark * position.multiplier
            notional += abs(nominal)
            position_risk += position.quantity * position.unit_risk
            margin += abs(nominal) / s.orders[position.order_id].plan.exchange_leverage
        pending_notional = D(0)
        for order in s.orders.values():
            if order.state in ACTIVE:
                remaining = order.plan.quantity - order.filled
                pending_risk += remaining * order.plan.unit_risk
                nominal = remaining * order.plan.entry * order.plan.multiplier
                pending_notional += nominal
                margin += nominal / order.plan.exchange_leverage
        equity = s.cash + unrealized
        adjusted = equity - s.net_flows
        principal_loss, drawdown = losses(
            s.config.initial_equity, equity, s.net_flows, s.peak_adjusted_equity
        )
        return dict(
            cash=s.cash,
            equity=equity,
            unrealized_pnl=unrealized,
            adjusted_equity=adjusted,
            net_flows=s.net_flows,
            principal_loss_pct=principal_loss,
            high_water_drawdown_pct=drawdown,
            daily_loss_pct=max(D(0), (s.daily_baseline - adjusted) / s.daily_baseline * 100),
            position_risk=position_risk,
            pending_risk=pending_risk,
            total_planned_risk=position_risk + pending_risk,
            portfolio_risk_pct=(position_risk + pending_risk) / equity * 100
            if equity > 0
            else D(100),
            position_notional=notional,
            pending_notional=pending_notional,
            effective_leverage=(notional + pending_notional) / equity
            if equity > 0
            else D("Infinity"),
            theoretical_margin=margin,
        )

    def refresh(self) -> None:
        s, m = self.state, self.metrics()
        s.peak_adjusted_equity = max(s.peak_adjusted_equity, m["adjusted_equity"])
        m = self.metrics()
        result = risk_state(
            s.config.mode,
            m["principal_loss_pct"],
            m["high_water_drawdown_pct"],
            m["daily_loss_pct"],
            m["portfolio_risk_pct"],
        )
        if (
            self.persist_reduced_rule
            and s.config.mode == "micro_capital"
            and m["principal_loss_pct"] >= 30
        ):
            s.reduced_risk_latched = True
        # Separate permanent money locks from transient portfolio/data checks.
        if result["state"] in FINANCIAL_LOCKS and result["state"] not in s.permanent_locks:
            s.permanent_locks.append(result["state"])
        if m["equity"] <= 0 and "INSOLVENT_SIMULATION" not in s.permanent_locks:
            s.permanent_locks.append("INSOLVENT_SIMULATION")

    def blockers(self) -> list[str]:
        s, m = self.state, self.metrics()
        reasons = list(s.permanent_locks)
        if s.recovery_required:
            reasons.append("RECOVERY_REQUIRED")
        if any(o.state == "UNKNOWN_SUBMISSION" for o in s.orders.values()):
            reasons.append("UNKNOWN_SUBMISSION")
        if any(not p.protected for p in s.positions.values()):
            reasons.append("PROTECTION_FAILURE")
        if m["equity"] <= 0:
            reasons.append("NON_POSITIVE_EQUITY")
        if m["portfolio_risk_pct"] > 5:
            reasons.append("PORTFOLIO_RISK_CAP")
        if (
            s.config.mode == "micro_capital"
            and s.config.enable_candidate_effective_cap
            and m["effective_leverage"] > 2
        ):
            reasons.append("CANDIDATE_EFFECTIVE_LEVERAGE_CAP")
        observed = {p.symbol for p in s.positions.values()} | {
            o.plan.symbol for o in s.orders.values() if o.state in ACTIVE
        }
        if any(
            not 0 <= (self.at - s.quotes[symbol].at).total_seconds() <= 120 for symbol in observed
        ):
            reasons.append("SIMULATED_MARKET_DATA_STALE")
        return list(dict.fromkeys(reasons))

    def quote(self, symbol: str, fresh: bool = True) -> Quote:
        if symbol not in self.state.quotes:
            raise PaperError("QUOTE_MISSING")
        quote = self.state.quotes[symbol]
        if fresh and not 0 <= (self.at - quote.at).total_seconds() <= 120:
            raise PaperError("SIMULATED_QUOTE_STALE_OR_FUTURE")
        return quote

    def order(self, identifier: str) -> PaperOrder:
        if identifier not in self.state.orders:
            raise PaperError("ORDER_NOT_FOUND")
        order = self.state.orders[identifier]
        if payload_hash(order.plan.model_dump(mode="json")) != order.plan_hash:
            raise PaperError("IMMUTABLE_PLAN_CORRUPTED")
        return order

    def _risk(self, p: PrepareInput, entry: Decimal, exclude: str | None = None) -> dict[str, Any]:
        s, m = self.state, self.metrics()
        reasons = self.blockers()
        maximum = (
            (D("0.5") if p.grade == "NORMAL" else D("1"))
            if s.config.mode == "standard"
            else (D("1") if p.grade == "NORMAL" else D("2"))
        )
        if not self.legacy_submit_trace and p.risk_pct > maximum:
            reasons.append("RISK_GRADE_BUDGET_EXCEEDED")
        quote = self.quote(p.symbol)
        cost = (
            entry
            * quote.multiplier
            * (p.fee_bps * 2 + p.slippage_bps * 2 + p.funding_budget_bps)
            / 10000
        )
        if exclude is not None:
            old = s.orders[exclude]
            m["pending_notional"] -= (
                (old.plan.quantity - old.filled) * old.plan.entry * old.plan.multiplier
            )
        calculation = preview(
            RiskRequest(
                mode=s.config.mode,
                direction=p.direction,
                equity=max(D("0.000000001"), m["equity"]),
                principal=s.config.initial_equity,
                net_flows=s.net_flows,
                peak=s.peak_adjusted_equity,
                daily_loss_pct=m["daily_loss_pct"],
                existing_notional=m["position_notional"],
                pending_notional=m["pending_notional"],
                portfolio_risk_pct=m["portfolio_risk_pct"],
                entry=entry,
                stop=p.stop,
                risk_pct=p.risk_pct,
                multiplier=quote.multiplier,
                step=quote.step,
                tick=quote.tick,
                min_qty=quote.min_qty,
                min_notional=quote.min_notional,
                extra_loss_per_unit=cost,
                exchange_leverage=p.exchange_leverage,
                simulated_account_max=s.config.assumed_account_max,
                liquidation=p.assumed_liquidation,
                liquidation_buffer=p.liquidation_buffer,
                # Precheck identifies required extra approval; it grants nothing.
                exception_approved=True,
                enable_candidate_effective_cap=s.config.mode == "micro_capital"
                and s.config.enable_candidate_effective_cap,
            )
        )
        reasons.extend(
            r
            for r in cast(list[str], calculation["reasons"])
            if r
            not in {
                "BELOW_EXCHANGE_MINIMUM_NO_ROUND_UP",
                "CANDIDATE_EFFECTIVE_LEVERAGE_CAP",
                "CANDIDATE_SINGLE_MARGIN_CAP",
            }
        )
        unit = abs(entry - p.stop) * quote.multiplier + cost
        budget = D(str(calculation["risk_budget"]))
        if s.reduced_risk_latched and m["principal_loss_pct"] < 30:
            budget *= D("0.5")
        qty = p.quantity if p.quantity is not None else floor_quantity(budget / unit, quote.step)
        if qty % quote.step:
            reasons.append("QUANTITY_NOT_STEP_ALIGNED")
        if qty * unit > budget:
            reasons.append("SINGLE_RISK_BUDGET_EXCEEDED")
        if qty < quote.min_qty or qty * entry * quote.multiplier < quote.min_notional:
            reasons.append("BELOW_EXCHANGE_MINIMUM_NO_ROUND_UP")
        existing_risk = m["total_planned_risk"]
        if exclude:
            existing_risk -= s.orders[exclude].plan.reserved_risk
        total = existing_risk + qty * unit
        if total > m["equity"] * D("0.05"):
            reasons.append("TOTAL_PLANNED_RISK_CAP")
        nominal = qty * entry * quote.multiplier
        projected_notional = m["position_notional"] + m["pending_notional"] + nominal
        projected_margin = m["theoretical_margin"] + nominal / p.exchange_leverage
        if exclude:
            projected_margin -= (
                s.orders[exclude].plan.quantity * entry / p.exchange_leverage * quote.multiplier
            )
        count = len(
            ({o.id for o in s.orders.values() if o.state in ACTIVE} | set(s.positions)) - {exclude}
        )
        if projected_margin > m["equity"]:
            reasons.append("INSUFFICIENT_SIMULATED_MARGIN")
        if s.config.mode == "micro_capital":
            if nominal / p.exchange_leverage > m["equity"] * D("0.25"):
                reasons.append("CANDIDATE_SINGLE_MARGIN_CAP")
            if count >= 2 and exclude is None:
                reasons.append("CANDIDATE_MAX_TWO_POSITIONS")
            if projected_margin > m["equity"] * D("0.5"):
                reasons.append("CANDIDATE_TOTAL_MARGIN_CAP")
            if s.config.enable_candidate_effective_cap and projected_notional > m["equity"] * 2:
                reasons.append("CANDIDATE_EFFECTIVE_LEVERAGE_CAP")
        if p.take_profit % quote.tick or not (
            p.take_profit > entry if p.direction == "LONG" else p.take_profit < entry
        ):
            reasons.append("INVALID_TAKE_PROFIT")
        return dict(
            reasons=list(dict.fromkeys(reasons)),
            quantity=qty,
            unit_risk=unit,
            reserved_risk=qty * unit,
            calculation=calculation,
        )

    def execute(self, command: PaperCommand, at: datetime, runtime_id: str) -> dict[str, Any]:
        s = self.state
        if at < s.updated_at:
            raise PaperError("CLOCK_ROLLBACK")
        self.at = at
        if s.runtime_id != runtime_id:
            self.incident("PROCESS_RESTART_REQUIRES_RECONCILIATION")
            s.runtime_id = runtime_id
        if s.risk_day != at.date().isoformat():
            s.risk_day = at.date().isoformat()
            s.daily_baseline = max(D("0.000000001"), self.metrics()["adjusted_equity"])
        # Expiry cannot infer the result of an unknown submission.
        for order in s.orders.values():
            if at >= order.plan.expires_at:
                if order.state in {"AWAITING_APPROVAL", "APPROVED"}:
                    self.transition(order, "EXPIRED", "approval expired")
                elif order.state in {"ACKED", "PARTIALLY_FILLED"}:
                    self.transition(order, "CANCELLED", "paper limit order lifetime expired")
                    s.venue_orders[order.client_order_id]["status"] = "CANCELLED"
        self.refresh()
        handler = getattr(self, "do_" + command.action.lower())
        self.result = handler(command.args, command.command_id)
        s.updated_at = at
        self.refresh()
        self.invariants()
        return self.result

    def do_quote(self, args: dict[str, Any], _: str) -> dict[str, Any]:
        p = QuoteInput.model_validate(args)
        if p.price % p.tick:
            raise PaperError("PRICE_NOT_TICK_ALIGNED")
        spec = payload_hash(p.model_dump(mode="json", exclude={"price"}))
        previous = self.state.quotes.get(p.symbol)
        quote = Quote(**p.model_dump(), at=self.at, spec_version=spec)
        self.state.quotes[p.symbol] = quote
        for order in self.state.orders.values():
            if order.plan.symbol == p.symbol and order.state in {"AWAITING_APPROVAL", "APPROVED"}:
                if order.plan.entry != p.price or order.plan.spec_version != spec:
                    self.transition(
                        order, "INVALIDATED", "price or specification changed; reapprove"
                    )
        if (
            previous
            and previous.spec_version != spec
            and any(pos.symbol == p.symbol for pos in self.state.positions.values())
        ):
            self.incident("SPECIFICATION_CHANGED_WITH_OPEN_POSITION")
        self.protect(p.symbol, _)
        return {"symbol": p.symbol, "source": p.source, "spec_version": spec}

    def protect(self, symbol: str, identifier: str) -> None:
        for position in list(self.state.positions.values()):
            if position.symbol != symbol or not position.protected:
                continue
            stop = (
                self.state.quotes[symbol].price <= position.stop
                if position.direction == "LONG"
                else self.state.quotes[symbol].price >= position.stop
            )
            profit = (
                self.state.quotes[symbol].price >= position.take_profit
                if position.direction == "LONG"
                else self.state.quotes[symbol].price <= position.take_profit
            )
            if stop or profit:
                self._close(
                    position,
                    self.state.orders[position.order_id],
                    position.quantity,
                    "STOP" if stop else "TAKE_PROFIT",
                    str(uuid5(NAMESPACE_URL, identifier + position.order_id)),
                )

    def do_prepare(self, args: dict[str, Any], identifier: str) -> dict[str, Any]:
        p = PrepareInput.model_validate(args)
        quote = self.quote(p.symbol)
        if any(pos.symbol == p.symbol for pos in self.state.positions.values()) or any(
            o.plan.symbol == p.symbol and o.state in ACTIVE for o in self.state.orders.values()
        ):
            raise PaperError("ONE_ISOLATED_PLAN_PER_SYMBOL")
        risk = self._risk(p, quote.price)
        if risk["reasons"]:
            raise PaperError(";".join(risk["reasons"]))
        plan = OrderPlan(
            **{**p.model_dump(), "quantity": risk["quantity"]},
            entry=quote.price,
            spec_version=quote.spec_version,
            quote_at=quote.at,
            created_at=self.at,
            expires_at=self.at + timedelta(minutes=5),
            step=quote.step,
            tick=quote.tick,
            multiplier=quote.multiplier,
            unit_risk=risk["unit_risk"],
            reserved_risk=risk["reserved_risk"],
            policy_hash=payload_hash(self.state.config.model_dump(mode="json")),
        )
        digest = payload_hash(plan.model_dump(mode="json"))
        order = PaperOrder(
            id=identifier,
            client_order_id="PAPER-" + payload_hash([self.state.id, identifier])[:28],
            plan=plan,
            plan_hash=digest,
            nonce=payload_hash([self.state.id, identifier, digest]),
            state="AWAITING_APPROVAL",
        )
        self.transition(order, "AWAITING_APPROVAL", "risk reserved; simulation approval required")
        self.state.orders[identifier] = order
        return {"order_id": identifier, "plan_hash": digest}

    def _current(self, order: PaperOrder) -> list[str]:
        q = self.quote(order.plan.symbol)
        if q.spec_version != order.plan.spec_version or q.price != order.plan.entry:
            return ["PRICE_OR_SPEC_CHANGED"]
        if self.at >= order.plan.expires_at:
            return ["APPROVAL_EXPIRED"]
        return self._risk(order.plan, order.plan.entry, order.id)["reasons"]  # type: ignore[no-any-return]

    def do_approve(self, args: dict[str, Any], _: str) -> dict[str, Any]:
        p = ApproveInput.model_validate(args)
        order = self.order(p.order_id)
        if p.plan_hash != order.plan_hash:
            raise PaperError("APPROVAL_HASH_MISMATCH")
        if not p.human_confirmed or p.simulation_code != simulation_code(order.nonce):
            raise PaperError("SIMULATED_SECOND_FACTOR_REQUIRED")
        if order.plan.exchange_leverage > 20 and p.exception_code != simulation_code(
            order.nonce, True
        ):
            raise PaperError("EXTRA_SIMULATED_APPROVAL_REQUIRED_21_TO_25X")
        if order.state == "APPROVED":
            return {"order_id": order.id, "state": order.state}
        if order.state != "AWAITING_APPROVAL":
            raise PaperError("ORDER_NOT_AWAITING_APPROVAL")
        reasons = self._current(order)
        if reasons:
            self.transition(order, "INVALIDATED", ";".join(reasons))
        else:
            order.approved_at = self.at
            self.transition(order, "APPROVED", "human + public dummy second-factor simulation")
        return {"order_id": order.id, "state": order.state, "reasons": reasons}

    def do_reject(self, args: dict[str, Any], _: str) -> dict[str, Any]:
        order = self.order(OrderInput.model_validate(args).order_id)
        if order.state != "AWAITING_APPROVAL":
            raise PaperError("ORDER_NOT_AWAITING_APPROVAL")
        self.transition(order, "REJECTED", "human rejected simulation plan")
        return {"state": order.state}

    def do_submit(self, args: dict[str, Any], _: str) -> dict[str, Any]:
        p = SubmitInput.model_validate(args)
        order = self.order(p.order_id)
        if order.client_order_id in self.state.venue_orders:
            return {
                "order_id": order.id,
                "client_order_id": order.client_order_id,
                "state": order.state,
            }
        if order.state != "APPROVED":
            raise PaperError("APPROVED_PLAN_REQUIRED")
        reasons = self._current(order)
        if reasons:
            self.transition(order, "INVALIDATED", ";".join(reasons))
            return {"state": order.state, "reasons": reasons}
        if self.legacy_submit_trace:
            self.transition(
                order, "APPROVED", "SEND_PENDING: final risk recheck passed; paper only"
            )
        else:
            self.transition(order, "SEND_PENDING", "final risk recheck passed; paper only")
        exists = p.scenario != "LOST_ACK_REJECTED"
        self.state.venue_orders[order.client_order_id] = dict(
            exists=exists,
            status="ACKED" if exists else "REJECTED",
            protection=p.scenario != "PROTECTION_FAILURE",
            fills={},
            pending_fill=str(
                floor_quantity(order.plan.quantity * p.unknown_fill_pct / 100, order.plan.step)
            )
            if p.scenario == "LOST_ACK_ACCEPTED"
            else "0",
        )
        if p.scenario.startswith("LOST_ACK"):
            self.transition(order, "UNKNOWN_SUBMISSION", "simulated lost ACK; query old client id")
            self.incident("UNKNOWN_SUBMISSION")
        else:
            self.transition(order, "ACKED", "in-process PaperBroker accepted; no network request")
        return {
            "order_id": order.id,
            "client_order_id": order.client_order_id,
            "state": order.state,
        }

    def _open_fill(self, order: PaperOrder, quantity: Decimal, identifier: str) -> None:
        if identifier in self.state.fills:
            fill = self.state.fills[identifier]
            if fill.order_id != order.id or fill.quantity != quantity or fill.kind != "OPEN":
                raise PaperError("FILL_ID_PAYLOAD_CONFLICT")
            return
        if (
            quantity <= 0
            or quantity % order.plan.step
            or quantity > order.plan.quantity - order.filled
        ):
            raise PaperError("INVALID_FILL_QUANTITY")
        fee = quantity * order.plan.entry * order.plan.multiplier * order.plan.fee_bps / 10000
        fill = Fill(
            id=identifier,
            order_id=order.id,
            kind="OPEN",
            quantity=quantity,
            price=order.plan.entry,
            commission=fee,
            realized_pnl=D(0),
            at=self.at,
        )
        self.state.fills[identifier] = fill
        venue = self.state.venue_orders[order.client_order_id]
        venue["fills"][identifier] = fill.model_dump(mode="json")
        self.amount("COMMISSION", -fee, identifier)
        order.filled += quantity
        if order.id in self.state.positions:
            self.state.positions[order.id].quantity += quantity
        else:
            self.state.positions[order.id] = Position(
                order_id=order.id,
                symbol=order.plan.symbol,
                direction=order.plan.direction,
                quantity=quantity,
                average_entry=order.plan.entry,
                stop=order.plan.stop,
                take_profit=order.plan.take_profit,
                multiplier=order.plan.multiplier,
                unit_risk=order.plan.unit_risk,
                protected=venue["protection"],
                opened_at=self.at,
            )
        self.transition(
            order,
            "FILLED" if order.filled == order.plan.quantity else "PARTIALLY_FILLED",
            "deduplicated simulated fill and position sync",
        )
        venue["status"] = order.state
        if not venue["protection"]:
            self.incident("PROTECTION_FAILURE")
            self.transition(
                order, "CANCELLED", "cancel unfilled remainder; reduction remains available"
            )
            venue["status"] = "CANCELLED"
        else:
            self.protect(order.plan.symbol, identifier)

    def do_fill(self, args: dict[str, Any], _: str) -> dict[str, Any]:
        p = FillInput.model_validate(args)
        order = self.order(p.order_id)
        if p.fill_id in self.state.fills:
            self._open_fill(order, p.quantity, p.fill_id)
            return {"state": order.state, "duplicate": True}
        if order.state not in {"ACKED", "PARTIALLY_FILLED"}:
            raise PaperError("ACKED_ORDER_REQUIRED")
        if self.blockers():
            raise PaperError("NO_ADDITIONAL_PAPER_FILL:" + ";".join(self.blockers()))
        quote = self.quote(order.plan.symbol)
        if not (
            quote.price <= order.plan.entry
            if order.plan.direction == "LONG"
            else quote.price >= order.plan.entry
        ):
            raise PaperError("SIMULATED_LIMIT_NOT_MARKETABLE")
        if quote.spec_version != order.plan.spec_version:
            raise PaperError("SPECIFICATION_CHANGED")
        self._open_fill(order, p.quantity, p.fill_id)
        return {"state": order.state, "filled": str(order.filled)}

    def do_cancel(self, args: dict[str, Any], _: str) -> dict[str, Any]:
        order = self.order(OrderInput.model_validate(args).order_id)
        if order.state == "UNKNOWN_SUBMISSION":
            raise PaperError("RECONCILE_OLD_CLIENT_ID_FIRST")
        if order.state not in ACTIVE:
            return {"state": order.state}
        self.transition(order, "CANCELLED", "CANCEL_REQUESTED -> CANCELLED; remainder released")
        if order.client_order_id in self.state.venue_orders:
            self.state.venue_orders[order.client_order_id]["status"] = "CANCELLED"
        return {"state": order.state, "position_quantity": str(order.filled - order.closed)}

    def do_reconcile(self, args: dict[str, Any], _: str) -> dict[str, Any]:
        order = self.order(OrderInput.model_validate(args).order_id)
        if order.state != "UNKNOWN_SUBMISSION":
            return {"state": order.state}
        venue = self.state.venue_orders[order.client_order_id]
        self.transition(order, "RECONCILING", "query SAME simulated client order id")
        if not venue["exists"]:
            self.transition(order, "REJECTED", "simulated venue confirms rejection")
        else:
            self.transition(order, "ACKED", "simulated venue confirms existing order")
            quantity = D(venue["pending_fill"])
            if quantity > 0:
                self._open_fill(
                    order, quantity, str(uuid5(NAMESPACE_URL, order.client_order_id + ":remote"))
                )
                venue["pending_fill"] = "0"
        return {
            "state": order.state,
            "client_order_id": order.client_order_id,
            "recovery_required": True,
        }

    def _close(
        self, position: Position, order: PaperOrder, quantity: Decimal, kind: str, identifier: str
    ) -> None:
        if quantity <= 0 or quantity % order.plan.step or quantity > position.quantity:
            raise PaperError("REDUCE_ONLY_MUST_NOT_OVERSHOOT")
        quote = self.quote(position.symbol)
        sign = D(1) if position.direction == "LONG" else D(-1)
        price = quote.price * (1 - sign * order.plan.slippage_bps / 10000)
        rounding = ROUND_FLOOR if sign > 0 else ROUND_CEILING
        price = max(
            order.plan.tick,
            (price / order.plan.tick).to_integral_value(rounding=rounding) * order.plan.tick,
        )
        pnl = (price - position.average_entry) * quantity * position.multiplier * sign
        fee = price * quantity * position.multiplier * order.plan.fee_bps / 10000
        fill = Fill.model_validate(
            dict(
                id=identifier,
                order_id=order.id,
                kind=kind,
                quantity=quantity,
                price=price,
                commission=fee,
                realized_pnl=pnl,
                at=self.at,
            )
        )
        self.state.fills[identifier] = fill
        self.state.venue_orders[order.client_order_id]["fills"][identifier] = fill.model_dump(
            mode="json"
        )
        self.amount("REALIZED_PNL", pnl, identifier)
        self.amount("COMMISSION", -fee, identifier)
        position.quantity -= quantity
        order.closed += quantity
        # Exit never reopens the unfilled remainder.
        if order.state in {"ACKED", "PARTIALLY_FILLED"}:
            self.transition(order, "CANCELLED", "exit cancels remaining simulated entry quantity")
            self.state.venue_orders[order.client_order_id]["status"] = "CANCELLED"
        if position.quantity == 0:
            del self.state.positions[order.id]

    def do_reduce(self, args: dict[str, Any], identifier: str) -> dict[str, Any]:
        p = ReduceInput.model_validate(args)
        order = self.order(p.order_id)
        if order.id not in self.state.positions:
            raise PaperError("NO_KNOWN_POSITION_TO_REDUCE")
        self._close(self.state.positions[order.id], order, p.quantity, "REDUCE", identifier)
        return {"remaining": str(order.filled - order.closed)}

    def do_funding(self, args: dict[str, Any], _: str) -> dict[str, Any]:
        p = FundingInput.model_validate(args)
        digest = payload_hash(p.model_dump(mode="json"))
        if p.event_id in self.state.funding:
            if self.state.funding[p.event_id]["hash"] != digest:
                raise PaperError("FUNDING_ID_CONFLICT")
            return {"duplicate": True}
        if any(
            o.state == "UNKNOWN_SUBMISSION" and o.plan.symbol == p.symbol
            for o in self.state.orders.values()
        ):
            raise PaperError("RECONCILE_BEFORE_FUNDING_SYNC")
        quote = self.quote(p.symbol)
        amount = sum(
            (
                -p.rate
                * pos.quantity
                * quote.price
                * pos.multiplier
                * (D(1) if pos.direction == "LONG" else D(-1))
                for pos in self.state.positions.values()
                if pos.symbol == p.symbol
            ),
            D(0),
        )
        self.state.funding[p.event_id] = {
            "hash": digest,
            "amount": str(amount),
            "at": self.at.isoformat(),
            "symbol": p.symbol,
            "rate": str(p.rate),
            "source": "SIMULATED_SETTLEMENT",
        }
        self.amount("FUNDING", amount, p.event_id)
        return {"amount": str(amount)}

    def do_flow(self, args: dict[str, Any], identifier: str) -> dict[str, Any]:
        p = FlowInput.model_validate(args)
        if p.amount == 0 or self.state.cash + p.amount < 0:
            raise PaperError("INVALID_EXTERNAL_SIMULATED_FLOW")
        self.amount("EXTERNAL_FLOW", p.amount, identifier)
        self.state.net_flows += p.amount
        return {"net_flows": str(self.state.net_flows)}

    def do_kill(self, args: dict[str, Any], _: str) -> dict[str, Any]:
        EmptyInput.model_validate(args)
        if "HUMAN_KILL_SWITCH" not in self.state.permanent_locks:
            self.state.permanent_locks.append("HUMAN_KILL_SWITCH")
        # PaperBroker can cancel known open remainder, not infer an unknown submission.
        for order in self.state.orders.values():
            if order.state in ACTIVE and order.state != "UNKNOWN_SUBMISSION":
                self.do_cancel({"order_id": order.id}, _)
        return {"new_paper_risk_allowed": False}

    def do_restore_protection(self, args: dict[str, Any], _: str) -> dict[str, Any]:
        order = self.order(OrderInput.model_validate(args).order_id)
        if order.id not in self.state.positions:
            raise PaperError("POSITION_NOT_FOUND")
        self.state.positions[order.id].protected = True
        self.state.venue_orders[order.client_order_id]["protection"] = True
        self.protect(order.plan.symbol, _)
        return {"protected": True, "recovery_required": True}

    def do_recover(self, args: dict[str, Any], _: str) -> dict[str, Any]:
        EmptyInput.model_validate(args)
        if any(o.state == "UNKNOWN_SUBMISSION" for o in self.state.orders.values()):
            raise PaperError("UNKNOWN_SUBMISSION_REMAINS")
        for position in self.state.positions.values():
            if not position.protected:
                raise PaperError("PROTECTION_FAILURE_REMAINS")
            self.quote(position.symbol)
        self.invariants()
        self.state.recovery_required = False
        return {
            "operational_recovery_complete": True,
            "financial_locks_unchanged": self.state.permanent_locks,
        }

    def invariants(self) -> None:
        s = self.state
        if s.cash != s.config.initial_equity + sum((D(x["amount"]) for x in s.ledger), D(0)):
            raise PaperError("CASH_LEDGER_MISMATCH")
        if s.net_flows != sum(
            (D(x["amount"]) for x in s.ledger if x["kind"] == "EXTERNAL_FLOW"), D(0)
        ):
            raise PaperError("EXTERNAL_FLOW_LEDGER_MISMATCH")
        if sum((D(f["amount"]) for f in s.funding.values()), D(0)) != sum(
            (D(row["amount"]) for row in s.ledger if row["kind"] == "FUNDING"), D(0)
        ):
            raise PaperError("FUNDING_LEDGER_MISMATCH")
        for order in s.orders.values():
            self.order(order.id)
            if not 0 <= order.closed <= order.filled <= order.plan.quantity:
                raise PaperError("ORDER_QTY_MISMATCH")
            quantity = s.positions[order.id].quantity if order.id in s.positions else D(0)
            if quantity != order.filled - order.closed:
                raise PaperError("POSITION_LEDGER_MISMATCH")
            opens = sum(
                (
                    f.quantity
                    for f in s.fills.values()
                    if f.order_id == order.id and f.kind == "OPEN"
                ),
                D(0),
            )
            closes = sum(
                (
                    f.quantity
                    for f in s.fills.values()
                    if f.order_id == order.id and f.kind != "OPEN"
                ),
                D(0),
            )
            if opens != order.filled or closes != order.closed:
                raise PaperError("FILL_LEDGER_MISMATCH")

    def snapshot(self, at: datetime, runtime_id: str) -> dict[str, Any]:
        self.at = at
        s = self.state
        reasons = self.blockers()
        if s.runtime_id != runtime_id:
            reasons.append("PROCESS_RESTART_REQUIRES_RECONCILIATION")
        m = self.metrics()
        policy = risk_state(
            s.config.mode,
            m["principal_loss_pct"],
            m["high_water_drawdown_pct"],
            m["daily_loss_pct"],
            m["portfolio_risk_pct"],
            bool(s.permanent_locks),
        )
        if s.reduced_risk_latched:
            policy["new_risk_multiplier"] = "0.5"
        orders = []
        for order in s.orders.values():
            orders.append(
                {
                    **order.model_dump(mode="json"),
                    "simulation_challenge": simulation_code(order.nonce),
                    "extra_simulation_challenge": simulation_code(order.nonce, True)
                    if order.plan.exchange_leverage > 20
                    else None,
                    "executable": False,
                }
            )
        return dict(
            id=s.id,
            name=s.config.name,
            config=s.config.model_dump(mode="json"),
            updated_at=s.updated_at.isoformat(),
            checked_at=at.isoformat(),
            metrics={k: str(v) for k, v in m.items()},
            permanent_locks=s.permanent_locks,
            reduced_risk_latched=s.reduced_risk_latched,
            risk_state=policy,
            blockers=list(dict.fromkeys(reasons)),
            recovery_required=bool(reasons),
            quotes=[
                {**q.model_dump(mode="json"), "fresh": 0 <= (at - q.at).total_seconds() <= 120}
                for q in s.quotes.values()
            ],
            orders=orders,
            positions=[p.model_dump(mode="json") for p in s.positions.values()],
            fills=[f.model_dump(mode="json") for f in s.fills.values()][-100:],
            funding=list(s.funding.values())[-100:],
            ledger=s.ledger[-100:],
            incidents=s.incidents[-30:],
            mode="OFFLINE_SCENARIO",
            phase="P3_IN_PROGRESS",
            live_trading_enabled=False,
            trading_ready=False,
            allow_new_risk=False,
            simulated_new_risk_allowed=not reasons,
            account_permission="UNKNOWN",
            policy_state="MICRO_RESEARCH_CANDIDATE"
            if s.config.mode == "micro_capital"
            else "CONFIRMED_STANDARD_DESIGN",
            real_2fa=False,
        )
