"""Offline P3 lifecycle, cost accounting, fault and persistent-risk acceptance."""

import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.main import create_app
from app.paper_engine import PaperEngine, PaperError
from app.paper_models import CreatePaper, PaperCommand
from app.paper_store import FilePaperStore, PaperConflict, PaperStoreError, restore
from app.settings import ROOT
from fastapi.testclient import TestClient

NOW = datetime(2026, 10, 12, tzinfo=UTC)


class Harness:
    def __init__(self, path: Path, **config: Any) -> None:
        self.now = NOW
        self.store = FilePaperStore(path, clock=lambda: self.now, runtime_id="offline-runtime")
        self.config = CreatePaper(command_id=str(uuid4()), name="离线验收实验", **config)
        self.sid = self.config.command_id
        self.snapshot = self.store.create(self.config)

    def command(self, action: str, key: str | None = None, **args: Any) -> dict[str, Any]:
        cmd = PaperCommand(
            session_id=self.sid, command_id=key or str(uuid4()), action=action, args=args
        )
        self.snapshot = self.store.execute(cmd)
        return self.snapshot

    def quote(self, symbol: str = "XAUUSDT", price: str = "100", **args: Any) -> dict[str, Any]:
        return self.command("QUOTE", symbol=symbol, price=price, **args)

    def prepare(self, symbol: str = "XAUUSDT", **args: Any) -> str:
        self.command(
            "PREPARE",
            **{
                **dict(symbol=symbol, stop="98", take_profit="104", assumed_liquidation="90"),
                **args,
            },
        )
        return self.snapshot["result"]["order_id"]  # type: ignore[no-any-return]

    def order(self, oid: str) -> dict[str, Any]:
        return next(o for o in self.snapshot["orders"] if o["id"] == oid)

    def approve(self, oid: str, **args: Any) -> None:
        order = self.order(oid)
        self.command(
            "APPROVE",
            order_id=oid,
            plan_hash=order["plan_hash"],
            simulation_code=order["simulation_challenge"],
            human_confirmed=True,
            **args,
        )

    def open(self, **args: Any) -> str:
        self.quote()
        oid = self.prepare(**args)
        self.approve(oid)
        self.command("SUBMIT", order_id=oid)
        self.command(
            "FILL", order_id=oid, fill_id=str(uuid4()), quantity=self.order(oid)["plan"]["quantity"]
        )
        return oid


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def test_full_lifecycle_reservations_costs_and_replay(h: Harness) -> None:
    h.quote()
    oid = h.prepare(fee_bps="0", slippage_bps="0", funding_budget_bps="0")
    assert h.order(oid)["plan"]["quantity"] == "5"
    assert D(h.snapshot["metrics"]["pending_risk"]) == 10
    assert D(h.snapshot["metrics"]["theoretical_margin"]) == 25
    h.approve(oid)
    h.command("SUBMIT", order_id=oid)
    fid = str(uuid4())
    h.command("FILL", order_id=oid, fill_id=fid, quantity="2")
    assert h.order(oid)["state"] == "PARTIALLY_FILLED"
    assert D(h.snapshot["metrics"]["pending_risk"]) == 6
    assert D(h.snapshot["metrics"]["position_risk"]) == 4
    assert D(h.snapshot["metrics"]["total_planned_risk"]) == 10
    h.command("FILL", order_id=oid, fill_id=fid, quantity="2")
    assert len(h.snapshot["fills"]) == 1
    h.command("CANCEL", order_id=oid)
    assert D(h.snapshot["metrics"]["pending_risk"]) == 0
    assert D(h.snapshot["positions"][0]["quantity"]) == 2
    h.quote(price="101")
    h.command("REDUCE", order_id=oid, quantity="1")
    assert D(h.snapshot["metrics"]["cash"]) == 1001
    h.quote(price="97")
    assert not h.snapshot["positions"]
    assert D(h.snapshot["metrics"]["cash"]) == 998
    state, records = h.store.read(h.sid)
    recovered, _, _ = restore(records)
    assert recovered and recovered.model_dump() == state.model_dump()
    assert h.snapshot["live_trading_enabled"] is False


def test_plan_requires_hash_dummy_factor_and_human_confirmation(h: Harness) -> None:
    h.quote()
    oid = h.prepare()
    order = h.order(oid)
    for update in [
        dict(plan_hash="0" * 64),
        dict(simulation_code="000000"),
        dict(human_confirmed=False),
    ]:
        args = dict(
            order_id=oid,
            plan_hash=order["plan_hash"],
            simulation_code=order["simulation_challenge"],
            human_confirmed=True,
        )
        args.update(update)
        with pytest.raises(PaperError):
            h.command("APPROVE", **args)
    with pytest.raises(PaperError):
        h.command("SUBMIT", order_id=oid)
    h.approve(oid)
    assert h.order(oid)["state"] == "APPROVED"
    assert h.snapshot["real_2fa"] is False


def test_concurrent_approvals_and_submits_one_order(h: Harness) -> None:
    h.quote()
    oid = h.prepare()
    order = h.order(oid)

    def approve(_: int) -> Any:
        return h.store.execute(
            PaperCommand(
                session_id=h.sid,
                command_id=str(uuid4()),
                action="APPROVE",
                args=dict(
                    order_id=oid,
                    plan_hash=order["plan_hash"],
                    simulation_code=order["simulation_challenge"],
                    human_confirmed=True,
                ),
            )
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(approve, range(2)))

    def submit(_: int) -> Any:
        return h.store.execute(
            PaperCommand(
                session_id=h.sid, command_id=str(uuid4()), action="SUBMIT", args=dict(order_id=oid)
            )
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(submit, range(2)))
    state, _ = h.store.read(h.sid)
    assert len(state.orders) == len(state.venue_orders) == 1
    assert state.orders[oid].state == "ACKED"


def test_idempotency_conflict_never_changes_cash(h: Harness) -> None:
    key = str(uuid4())
    h.command("FLOW", key, amount="100")
    h.command("FLOW", key, amount="100")
    assert h.snapshot["metrics"]["cash"] == "1100"
    assert h.snapshot["duplicate_command"] is True
    with pytest.raises(PaperConflict):
        h.command("FLOW", key, amount="101")


@pytest.mark.parametrize("scenario", ["LOST_ACK_ACCEPTED", "LOST_ACK_REJECTED"])
def test_unknown_submission_query_same_id_no_new_risk(h: Harness, scenario: str) -> None:
    h.quote()
    oid = h.prepare()
    h.approve(oid)
    h.command("SUBMIT", order_id=oid, scenario=scenario, unknown_fill_pct="50")
    clientid = h.order(oid)["client_order_id"]
    assert h.order(oid)["state"] == "UNKNOWN_SUBMISSION"
    assert "UNKNOWN_SUBMISSION" in h.snapshot["blockers"]
    h.quote(symbol="BTCUSDT")
    with pytest.raises(PaperError):
        h.prepare(symbol="BTCUSDT")
    with pytest.raises(PaperError):
        h.command("CANCEL", order_id=oid)
    h.command("SUBMIT", order_id=oid)  # Query result, never a new simulated submission.
    h.command("RECONCILE", order_id=oid)
    assert h.order(oid)["client_order_id"] == clientid
    assert h.order(oid)["state"] == (
        "PARTIALLY_FILLED" if scenario == "LOST_ACK_ACCEPTED" else "REJECTED"
    )
    state, _ = h.store.read(h.sid)
    assert len(state.venue_orders) == 1
    assert "RECOVERY_REQUIRED" in h.snapshot["blockers"]
    h.command("RECOVER")
    assert not h.snapshot["blockers"]


def test_change_price_or_spec_invalidates_old_approval(h: Harness) -> None:
    h.quote()
    oid = h.prepare()
    h.approve(oid)
    h.quote(price="101")
    assert h.order(oid)["state"] == "INVALIDATED"
    assert D(h.snapshot["metrics"]["pending_risk"]) == 0
    with pytest.raises(PaperError):
        h.command("SUBMIT", order_id=oid)
    h.quote()
    oid2 = h.prepare()
    h.quote(step="0.01")
    assert h.order(oid2)["state"] == "INVALIDATED"


def test_25x_needs_extra_approval_26x_and_account_cap_rejected(tmp_path: Path) -> None:
    h = Harness(tmp_path, assumed_account_max=25)
    h.quote()
    oid = h.prepare(exchange_leverage=25)
    with pytest.raises(PaperError, match="EXTRA"):
        h.approve(oid)
    h.approve(oid, exception_code=h.order(oid)["extra_simulation_challenge"])
    assert h.order(oid)["plan"]["exchange_leverage"] == 25
    h.command("CANCEL", order_id=oid)
    with pytest.raises(PaperError, match="REJECT_USER_LEVERAGE_CAP"):
        h.prepare(exchange_leverage=26)
    low = Harness(tmp_path, assumed_account_max=20)
    low.quote()
    with pytest.raises(PaperError, match="NO_AUTOMATIC_DOWNGRADE"):
        low.prepare(exchange_leverage=25)


def test_stale_quote_expiry_and_clock_rollback(h: Harness) -> None:
    h.quote()
    oid = h.prepare()
    h.approve(oid)
    h.now += timedelta(seconds=121)
    with pytest.raises(PaperError, match="STALE"):
        h.command("SUBMIT", order_id=oid)
    h.now += timedelta(minutes=5)
    h.quote()
    assert h.order(oid)["state"] == "EXPIRED"
    h.now = NOW - timedelta(seconds=1)
    with pytest.raises(PaperError, match="CLOCK_ROLLBACK"):
        h.command("FLOW", amount="100")


def test_portfolio_pending_reservation_and_two_slots(h: Harness) -> None:
    for symbol in ["XAUUSDT", "BTCUSDT", "ETHUSDT"]:
        h.quote(symbol=symbol)
    first = h.prepare(fee_bps="0", slippage_bps="0", funding_budget_bps="0")
    h.approve(first)
    h.command("SUBMIT", order_id=first)
    h.command("FILL", order_id=first, fill_id=str(uuid4()), quantity="2")
    h.prepare(symbol="BTCUSDT", fee_bps="0", slippage_bps="0", funding_budget_bps="0")
    assert D(h.snapshot["metrics"]["total_planned_risk"]) == 20
    with pytest.raises(PaperError, match="TWO_POSITIONS"):
        h.prepare(symbol="ETHUSDT")


def test_funding_direction_dedupe_and_fees(h: Harness) -> None:
    oid = h.open(quantity="2")
    assert D(h.snapshot["metrics"]["cash"]) == D("999.9")
    eid = str(uuid4())
    h.command("FUNDING", event_id=eid, symbol="XAUUSDT", rate="0.01")
    assert D(h.snapshot["metrics"]["cash"]) == D("997.9")
    h.command("FUNDING", event_id=eid, symbol="XAUUSDT", rate="0.01")
    assert D(h.snapshot["metrics"]["cash"]) == D("997.9")
    with pytest.raises(PaperError, match="FUNDING_ID_CONFLICT"):
        h.command("FUNDING", event_id=eid, symbol="XAUUSDT", rate="0.02")
    h.command("REDUCE", order_id=oid, quantity="2")
    assert not h.snapshot["positions"]


def test_protection_failure_reduction_still_available(h: Harness) -> None:
    h.quote()
    oid = h.prepare()
    h.approve(oid)
    h.command("SUBMIT", order_id=oid, scenario="PROTECTION_FAILURE")
    h.command("FILL", order_id=oid, fill_id=str(uuid4()), quantity="1")
    assert not h.snapshot["positions"][0]["protected"]
    assert "PROTECTION_FAILURE" in h.snapshot["blockers"]
    with pytest.raises(PaperError):
        h.command("RECOVER")
    h.command("REDUCE", order_id=oid, quantity="1")
    h.command("RECOVER")
    assert not h.snapshot["positions"]


def test_kill_and_reduce_only_cannot_flip(h: Harness) -> None:
    oid = h.open(quantity="1")
    h.command("KILL")
    with pytest.raises(PaperError, match="OVERSHOOT"):
        h.command("REDUCE", order_id=oid, quantity="2")
    h.command("REDUCE", order_id=oid, quantity="1")
    h.command("RECOVER")
    assert "HUMAN_KILL_SWITCH" in h.snapshot["permanent_locks"]


@pytest.mark.parametrize("price,minimum", [("10", D("40")), ("0.01", D("50"))])
def test_40_50_lines_deposit_day_and_restart_do_not_unlock(
    tmp_path: Path, price: str, minimum: D
) -> None:
    h = Harness(tmp_path)
    h.open(
        fee_bps="10",
        slippage_bps="0",
        funding_budget_bps="0",
        risk_pct="2",
        quantity="5",
        grade="QUALIFIED",
    )
    # Explicit large adverse gap, not a promise that planned stops cap actual loss.
    h.quote(price=price)
    assert D(h.snapshot["metrics"]["principal_loss_pct"]) >= minimum
    locks = h.snapshot["permanent_locks"]
    assert locks
    h.command("FLOW", amount="1000")
    assert h.snapshot["permanent_locks"] == locks
    assert D(h.snapshot["metrics"]["adjusted_equity"]) < 600
    h.now += timedelta(days=1)
    restarted = FilePaperStore(tmp_path, clock=lambda: h.now, runtime_id="new-process")
    snap = restarted.status(h.sid)
    assert snap["permanent_locks"] == locks and snap["recovery_required"]
    restarted.execute(PaperCommand(session_id=h.sid, command_id=str(uuid4()), action="RECOVER"))
    assert restarted.status(h.sid)["permanent_locks"] == locks


def test_truncated_journal_corruption_blocks_without_reset(h: Harness) -> None:
    h.quote()
    path = h.store.directory / (h.sid + ".jsonl")
    original = path.read_bytes()
    path.write_bytes(original + b"{")
    with pytest.raises(PaperStoreError):
        h.store.status(h.sid)
    with pytest.raises(PaperStoreError):
        h.command("FLOW", amount="100")
    assert path.read_bytes().startswith(original)


def test_decimal_no_round_up_and_foreign_currency_rejected(h: Harness) -> None:
    with pytest.raises(ValueError):
        h.quote(price=100.1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        h.quote(symbol="BTCUSDC")
    h.quote(step="1")
    with pytest.raises(PaperError, match="STEP"):
        h.prepare(quantity="0.9")
    with pytest.raises(PaperError, match="BUDGET"):
        h.prepare(quantity="6")


def test_api_loopback_and_no_real_order_route(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "config", tmp_path / "config")
    with TestClient(
        create_app(tmp_path), base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)
    ) as client:
        body = dict(command_id=str(uuid4()), name="UI offline experiment")
        assert client.post("/api/v1/paper/sessions", json=body).status_code == 403
        headers = {"origin": "http://127.0.0.1:5173"}
        r = client.post("/api/v1/paper/sessions", json=body, headers=headers)
        assert r.status_code == 201 and r.json()["allow_new_risk"] is False
        assert (
            client.post(
                "/api/v1/paper/commands",
                json=dict(session_id=body["command_id"], command_id=str(uuid4()), action="KILL"),
                headers={"origin": "https://evil.test"},
            ).status_code
            == 403
        )
        assert client.post("/api/v1/orders", json={}, headers=headers).status_code == 404
        assert client.get("/health/ready").json()["trading_ready"] is False
        assert (
            client.get("/api/v1/paper/sessions").json()["sessions"][0]["id"] == body["command_id"]
        )


def test_highwater_and_principal_are_independent_and_cash_flows_do_not_hide_loss(
    h: Harness,
) -> None:
    h.quote()
    oid = h.prepare(take_profit="1000", fee_bps="0", slippage_bps="0", funding_budget_bps="0")
    h.approve(oid)
    h.command("SUBMIT", order_id=oid)
    h.command("FILL", order_id=oid, fill_id=str(uuid4()), quantity="5")
    h.quote(price="160")
    assert D(h.snapshot["metrics"]["equity"]) == 1300
    h.quote(price="100")
    assert D(h.snapshot["metrics"]["principal_loss_pct"]) == 0
    assert D(h.snapshot["metrics"]["high_water_drawdown_pct"]) == D(300) / 1300 * 100
    h.quote(price="300")
    h.quote(price="100")
    assert "DRAWDOWN_LOCK" in h.snapshot["permanent_locks"]
    h.command("FLOW", amount="100")
    assert D(h.snapshot["metrics"]["adjusted_equity"]) == 1000
    assert "DRAWDOWN_LOCK" in h.snapshot["permanent_locks"]


def test_standard_five_percent_pending_risk_cap(tmp_path: Path) -> None:
    h = Harness(tmp_path, mode="standard")
    for index in range(6):
        h.quote(symbol=f"TEST{index}USDT")
    for index in range(5):
        h.prepare(
            symbol=f"TEST{index}USDT",
            grade="QUALIFIED",
            fee_bps="0",
            slippage_bps="0",
            funding_budget_bps="0",
        )
    assert D(h.snapshot["metrics"]["total_planned_risk"]) == 50
    with pytest.raises(PaperError, match="TOTAL_PLANNED_RISK_CAP"):
        h.prepare(
            symbol="TEST5USDT",
            grade="QUALIFIED",
            fee_bps="0",
            slippage_bps="0",
            funding_budget_bps="0",
        )


def test_short_funding_and_directional_stop(h: Harness) -> None:
    h.quote()
    oid = h.prepare(
        direction="SHORT", stop="102", take_profit="96", assumed_liquidation="110", quantity="2"
    )
    h.approve(oid)
    h.command("SUBMIT", order_id=oid)
    h.command("FILL", order_id=oid, fill_id=str(uuid4()), quantity="2")
    h.command("FUNDING", event_id=str(uuid4()), symbol="XAUUSDT", rate="0.01")
    assert D(h.snapshot["metrics"]["cash"]) == D("1001.9")
    h.quote(price="103")
    assert not h.snapshot["positions"]
    assert h.snapshot["fills"][-1]["kind"] == "STOP"


def test_reconciled_fill_already_beyond_stop_exits_immediately(h: Harness) -> None:
    h.quote()
    oid = h.prepare()
    h.approve(oid)
    h.command("SUBMIT", order_id=oid, scenario="LOST_ACK_ACCEPTED", unknown_fill_pct="50")
    h.quote(price="90")
    h.command("RECONCILE", order_id=oid)
    assert not h.snapshot["positions"]
    assert h.snapshot["fills"][-1]["kind"] == "STOP"
    assert h.order(oid)["state"] == "CANCELLED"


def test_recovery_detects_funding_mismatch(h: Harness) -> None:
    h.open(quantity="1")
    h.command("FUNDING", event_id=str(uuid4()), symbol="XAUUSDT", rate="0.01")
    state, _ = h.store.read(h.sid)
    next(iter(state.funding.values()))["amount"] = "999"
    with pytest.raises(PaperError, match="FUNDING_LEDGER_MISMATCH"):
        PaperEngine(state).invariants()


@pytest.mark.parametrize(
    "profile,ordinary,qualified", [("standard", "0.5", "1"), ("micro_capital", "1", "2")]
)
def test_normal_qualified_budget_is_explicit(
    tmp_path: Path, profile: str, ordinary: str, qualified: str
) -> None:
    h = Harness(tmp_path, mode=profile)
    h.quote()
    with pytest.raises(PaperError, match="RISK_GRADE_BUDGET_EXCEEDED"):
        h.prepare(risk_pct=qualified)
    oid = h.prepare(risk_pct=ordinary)
    h.command("CANCEL", order_id=oid)
    oid = h.prepare(risk_pct=qualified, grade="QUALIFIED")
    assert h.order(oid)["plan"]["grade"] == "QUALIFIED"


def test_empty_journal_and_invalid_record_do_not_reset(h: Harness) -> None:
    path = h.store.directory / (h.sid + ".jsonl")
    path.write_bytes(b"")
    with pytest.raises(PaperStoreError):
        h.store.create(h.config)
    path.write_text("{}\n")
    with pytest.raises(PaperStoreError):
        h.store.status(h.sid)


def test_legacy_v1_replay_keeps_existing_experiment(h: Harness) -> None:
    from app.paper_store import record

    state, initial = record(
        None, h.config.model_dump(mode="json"), "CREATE", NOW, "old", 0, "0" * 64, "paper.engine.v1"
    )
    command = PaperCommand(
        session_id=h.sid,
        command_id=str(uuid4()),
        action="QUOTE",
        args={"symbol": "XAUUSDT", "price": "100"},
    )
    state, item = record(
        state,
        command.model_dump(mode="json"),
        "COMMAND",
        NOW,
        "old",
        1,
        initial["hash"],
        "paper.engine.v1",
    )
    replayed, _, _ = restore([initial, item])
    assert replayed and replayed.model_dump() == state.model_dump()


def test_30_percent_reduction_does_not_reset_after_profit(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    for _ in range(11):
        h.now += timedelta(days=1)
        oid = h.open(fee_bps="0", slippage_bps="0", funding_budget_bps="0")
        h.quote(price="93")
    assert D(h.snapshot["metrics"]["principal_loss_pct"]) >= 30
    assert h.snapshot["reduced_risk_latched"] and not h.snapshot["permanent_locks"]
    h.now += timedelta(days=1)
    h.open(fee_bps="0", slippage_bps="0", funding_budget_bps="0", take_profit="116")
    h.quote(price="116")
    assert D(h.snapshot["metrics"]["principal_loss_pct"]) < 30
    assert h.snapshot["reduced_risk_latched"]
    h.now += timedelta(days=1)
    h.quote()
    oid = h.prepare(fee_bps="0", slippage_bps="0", funding_budget_bps="0")
    assert D(h.order(oid)["plan"]["reserved_risk"]) <= D(h.snapshot["metrics"]["equity"]) * D(
        "0.005"
    )
