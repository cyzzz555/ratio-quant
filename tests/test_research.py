from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.backtest import simulate
from app.bars import rest_bar
from app.models import Bar, utc_now
from app.research_data import aggregate
from app.research_models import BacktestRequest, HistoricalEvent, MarketContext, ResearchBar
from app.risk import RiskRequest, SimulatedApproval, losses, preview, risk_state
from app.strategies import EventDriven, MeanReversion, TrendPullback
from fastapi.testclient import TestClient


def minute_rows(count: int, start: datetime | None = None) -> list[Bar]:
    origin = start or datetime(2026, 1, 1, tzinfo=UTC)
    result = []
    for index in range(count):
        opened = origin + timedelta(minutes=index)
        stamp = int(opened.timestamp() * 1000)
        # Hourly trend with recurring pullbacks creates test candidates, not provider data.
        close = D(100) + D(index) / 100 + (D(-1) if index % 20 < 10 else D(1))
        result.append(
            rest_bar(
                [
                    stamp,
                    str(close),
                    str(close + 2),
                    str(close - 2),
                    str(close),
                    "100",
                    stamp + 59999,
                    "0",
                    1,
                    "0",
                    "0",
                    "0",
                ],
                symbol="XAUUSDT",
                spec_version="1" * 64,
                received_at=utc_now(),
                server_time_before_request=utc_now(),
                response_hash="2" * 64,
            )
        )
    return result


def params(**values: Any) -> BacktestRequest:
    return BacktestRequest.model_validate({"dataset_id": str(uuid4()), **values})


@pytest.mark.parametrize("frame,count", [("1m", 60), ("5m", 12), ("15m", 4), ("1h", 1), ("1d", 0)])
def test_closed_aggregation_and_triple_duplicates(frame: str, count: int) -> None:
    bars = minute_rows(60)
    result = aggregate(bars * 3, frame)
    assert len(result) == count
    if result:
        assert result[0].volume == D(100) * (60 // count)


def test_unclosed_or_missing_minute_never_confirms_five_minute() -> None:
    bars = minute_rows(5)
    forming = Bar.model_validate({**bars[-1].model_dump(), "is_closed": False})
    assert not aggregate(bars[:-1] + [forming], "5m")
    assert not aggregate(bars[1:], "5m")
    assert len(aggregate(bars, "5m")) == 1
    conflicting = Bar.model_validate({**bars[-1].model_dump(), "close": "100"})
    with pytest.raises(ValueError, match="冲突"):
        aggregate(bars + [conflicting], "5m")


def test_utc_daily_boundary_stays_stable_across_dst() -> None:
    result = aggregate(minute_rows(1440, datetime(2026, 3, 8, tzinfo=UTC)), "1d")
    assert len(result) == 1 and result[0].open_at.hour == 0
    assert result[0].close_at - result[0].open_at == timedelta(days=1, milliseconds=-1)


def test_event_available_time_and_closed_bar_context() -> None:
    published = datetime(2026, 1, 1, 14, 30, tzinfo=UTC)
    event = HistoricalEvent(
        event_id="fixture",
        event_type="EARNINGS_FIXTURE",
        published_at=published,
        available_at=published + timedelta(minutes=2),
        source="OFFLINE_FIXTURE",
        revision_id="1",
        source_license="TEST_ONLY",
        payload_hash="1" * 64,
    )
    with pytest.raises(ValueError, match="not yet available"):
        MarketContext(
            decision_at=published + timedelta(minutes=1),
            symbol="XAUUSDT",
            spec_version="v1",
            bars=[],
            events=[event],
        )
    context = MarketContext(
        decision_at=event.available_at, symbol="XAUUSDT", spec_version="v1", bars=[], events=[event]
    )
    assert EventDriven().evaluate(context, params()) is None
    assert MeanReversion().evaluate(context, params()) is None
    bar = aggregate(minute_rows(5), "5m")[0]
    with pytest.raises(ValueError, match="future or unclosed"):
        MarketContext(decision_at=bar.close_at, symbol="XAUUSDT", spec_version="v1", bars=[bar])


def test_candidate_idempotent_and_no_future_sensitive_features() -> None:
    p = params(fast_window=2, slow_window=4, pullback_window=2, stop_window=2)
    origin = datetime(2026, 1, 1, tzinfo=UTC)

    def research(frame: str, index: int, price: str) -> ResearchBar:
        opened = origin + timedelta(minutes=index * (60 if frame == "1h" else 5))
        return ResearchBar(
            symbol="XAUUSDT",
            timeframe=frame,
            open_at=opened,
            close_at=opened + timedelta(minutes=60 if frame == "1h" else 5, milliseconds=-1),
            open=price,
            high=price,
            low=price,
            close=price,
            volume="100",
            is_closed=True,
            quality="VALID",
            raw_hashes=["1" * 64],
        )

    hours = [research("1h", i, str(100 + i)) for i in range(4)]
    lower = [research("5m", 45 + i, v) for i, v in enumerate(["102", "101", "103"])]
    context = MarketContext(
        decision_at=origin + timedelta(hours=4),
        symbol="XAUUSDT",
        spec_version="v1",
        bars=hours + lower,
    )
    candidates = [TrendPullback().evaluate(context, p) for _ in range(3)]
    assert candidates[0] is not None
    assert len({c.candidate_id for c in candidates if c}) == 1
    assert candidates[0].executable is False


def test_decimal_defaults_and_float_rejection() -> None:
    assert isinstance(params().fee_bps, D)
    assert isinstance(RiskRequest().net_flows, D)
    with pytest.raises(ValueError):
        params(fee_bps=0.1)


def test_backtest_reproducible_splits_partial_fills_and_costs() -> None:
    bars = minute_rows(1800)
    p = params(
        fast_window=2,
        slow_window=4,
        pullback_window=3,
        fee_bps="2",
        slippage_bps="1",
        participation_pct="0.01",
    )
    spec = {
        "version": "v1",
        "spec": {
            "filters": [
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "100"},
                {"filterType": "MIN_NOTIONAL", "notional": "0"},
            ]
        },
    }
    first = simulate(bars, [], spec, p)
    assert first == simulate(bars, [], spec, p)
    assert (
        first["train"]["last_at"] < first["validation"]["first_at"] < first["holdout"]["first_at"]
    )
    trades = [t for split in first.values() for t in split["trades"]]
    assert trades and any(D(t["unfilled_cancelled"]) > 0 for t in trades)
    assert all(D(t["fees"]) > 0 for t in trades)
    assert all(datetime.fromisoformat(t["entry_at"]).minute % 5 == 0 for t in trades)
    assert all(D(t["quantity"]) <= D("0.05") for t in trades)
    assert all(D(t["entry"]) != D(t["exit"]) for t in trades)
    # Future prices do not alter trades completed in the training range.
    cutoff = datetime.fromisoformat(first["train"]["last_at"])
    changed = [
        Bar.model_validate(
            {
                **b.model_dump(),
                **(
                    {
                        "open": str(b.open + 10),
                        "high": str(b.high + 10),
                        "low": str(b.low + 10),
                        "close": str(b.close + 10),
                    }
                    if b.open_time_utc > cutoff
                    else {}
                ),
            }
        )
        for b in bars
    ]
    assert first["train"] == simulate(changed, [], spec, p)["train"]


@pytest.mark.parametrize(
    "mode,principal,dd,daily,total,state",
    [
        ("standard", "0", "0", "1.5", "0", "DAILY_WARNING"),
        ("standard", "0", "0", "2", "0", "DAILY_LOCK"),
        ("standard", "0", "10", "0", "0", "DRAWDOWN_LOCK"),
        ("micro_capital", "20", "0", "0", "0", "PRINCIPAL_WARNING"),
        ("micro_capital", "30", "0", "0", "0", "PRINCIPAL_REDUCE_RISK"),
        ("micro_capital", "40", "40", "6", "6", "PRINCIPAL_LOCK"),
        ("micro_capital", "50", "40", "6", "6", "PRINCIPAL_BUDGET_BREACH"),
        ("micro_capital", "0", "25", "0", "0", "DRAWDOWN_WARNING"),
        ("micro_capital", "0", "35", "0", "0", "DRAWDOWN_LOCK"),
        ("micro_capital", "0", "0", "3", "0", "DAILY_WARNING"),
        ("micro_capital", "0", "0", "5", "0", "DAILY_LOCK"),
        ("micro_capital", "0", "0", "0", "5.1", "PORTFOLIO_LOCK"),
    ],
)
def test_risk_state_priority(
    mode: str, principal: str, dd: str, daily: str, total: str, state: str
) -> None:
    assert risk_state(mode, D(principal), D(dd), D(daily), D(total))["state"] == state
    assert risk_state(mode, D(0), D(0), D(0), D(0), True)["state"] == "PERSISTED_LOCK"


def test_reference_position_margin_flows_and_drawdown() -> None:
    result = preview(RiskRequest())
    assert D(str(result["risk_budget"])) == 10 and D(str(result["quantity"])) == 5
    assert D(str(result["notional"])) == 500 and D(str(result["theoretical_margin"])) == 25
    assert losses(D(1000), D(650), D(100), D(1000))[0] == 45
    principal, dd = losses(D(1000), D(1000), D(0), D(1300))
    assert principal == 0 and abs(dd - D("23.076923076923")) < D("0.000000000001")
    assert result["executable"] is False


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"exchange_leverage": 26}, "REJECT_USER_LEVERAGE_CAP"),
        (
            {"exchange_leverage": 25, "simulated_account_max": 20},
            "REJECT_ACCOUNT_MAX_NO_AUTOMATIC_DOWNGRADE",
        ),
        (
            {"exchange_leverage": 25, "simulated_account_max": 25},
            "SPECIAL_APPROVAL_REQUIRED_RESEARCH_ONLY",
        ),
        ({"entry": "100.001"}, "PRICE_NOT_TICK_ALIGNED"),
        ({"min_qty": "6"}, "BELOW_EXCHANGE_MINIMUM_NO_ROUND_UP"),
        ({"liquidation": "99"}, "STOP_NOT_BEFORE_LIQUIDATION_WITH_BUFFER"),
        ({}, "LIQUIDATION_UNKNOWN"),
        (
            {"existing_notional": "2500", "enable_candidate_effective_cap": True},
            "CANDIDATE_EFFECTIVE_LEVERAGE_CAP",
        ),
        ({"extra_loss_per_unit": "1"}, "CANDIDATE_COST_RISK_RATIO"),
        ({"direction": "SHORT"}, "INVALID_DIRECTIONAL_STOP"),
    ],
)
def test_risk_rejections(changes: dict[str, Any], reason: str) -> None:
    assert reason in preview(RiskRequest.model_validate(changes))["reasons"]


def test_special_approval_and_short_liquidation() -> None:
    result = preview(
        RiskRequest.model_validate(
            {
                "direction": "SHORT",
                "stop": "102",
                "liquidation": "110",
                "exchange_leverage": 25,
                "simulated_account_max": 25,
                "exception_approved": True,
            }
        )
    )
    assert result["simulation_passed"] is True and result["executable"] is False
    result = preview(RiskRequest.model_validate({"existing_notional": "2500"}))
    assert "CANDIDATE_EFFECTIVE_LEVERAGE_CAP" not in result["reasons"]


def test_partial_and_zero_fill_approval_never_resubmits() -> None:
    approval = SimulatedApproval("hash", D(10), D(5))
    approval.consume("hash", D(2))
    assert approval.position_risk == 4 and approval.pending_risk == 0
    with pytest.raises(ValueError, match="already consumed"):
        approval.consume("hash", D(2))
    zero = SimulatedApproval("hash", D(10), D(5))
    zero.consume("hash", D(0))
    with pytest.raises(ValueError):
        zero.consume("hash", D(5))
    changed = SimulatedApproval("hash", D(10), D(5))
    with pytest.raises(ValueError):
        changed.consume("other", D(1))


def test_research_api_origin_and_no_order_route(tmp_path: Path) -> None:
    from app.research_api import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router(tmp_path))
    client = TestClient(app, client=("127.0.0.1", 50000), base_url="http://127.0.0.1:8000")
    assert client.post("/api/v1/risk/preview", json={}).status_code == 403
    good = client.post("/api/v1/risk/preview", json={}, headers={"Origin": "http://127.0.0.1:5173"})
    assert good.status_code == 200 and good.json()["executable"] is False
    assert client.post("/api/v1/orders", json={}).status_code == 404
    assert not client.get("/api/v1/research/status").json()["database"]["ready"]
    assert client.get("/api/v1/research/results/../../secret").status_code == 404


def test_funding_exact_settlement_direction_and_no_fake_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.research_models import CandidateSignal

    def forced(self: TrendPullback, context: MarketContext, p: BacktestRequest) -> CandidateSignal:
        direction = "SHORT" if p.reward_risk == D(3) else "LONG"
        return CandidateSignal(
            candidate_id=str(context.decision_at),
            strategy_id="OFFLINE_FIXTURE",
            strategy_version="test",
            instrument_id="BINANCE:USD_M_FUTURES:XAUUSDT",
            direction=direction,
            score=50,
            discovered_at=context.decision_at,
            expiry_at=context.decision_at + timedelta(minutes=5),
            feature_snapshot={},
            explanation=["OFFLINE_FIXTURE"],
            confirmation_rule="closed",
            invalidation_rule="changed",
        )

    monkeypatch.setattr(TrendPullback, "evaluate", forced)
    bars = minute_rows(600)
    stamp = int((bars[5].open_time_utc + timedelta(seconds=30)).timestamp() * 1000)
    funding = [{"fundingTime": stamp, "fundingRate": "0.001", "markPrice": "100"}]
    spec = {
        "version": "v1",
        "spec": {
            "filters": [
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "100"}
            ]
        },
    }
    p = params(fee_bps="0", slippage_bps="0", spread_bps="0")
    result = simulate(bars, funding, spec, p)
    first = result["train"]["trades"][0]
    assert D(first["funding"]) == D(first["quantity"]) * D("0.1")
    short = simulate(
        bars, funding, spec, params(fee_bps="0", slippage_bps="0", spread_bps="0", reward_risk="3")
    )
    assert D(short["train"]["trades"][0]["funding"]) < 0
    with pytest.raises(ValueError, match="结算标记价"):
        simulate(bars, [{"fundingTime": stamp, "fundingRate": "0.001"}], spec, p)


def test_dataset_hashes_and_duckdb_utc_read(tmp_path: Path) -> None:
    import hashlib
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq
    from app.bars import payload_hash
    from app.research_data import load_dataset
    from app.storage import atomic_json, bar_row

    identifier = str(uuid4())
    folder = tmp_path / "data/research" / identifier
    folder.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist([bar_row(b) for b in minute_rows(5)]), folder / "bars.parquet"
    )
    atomic_json(folder / "funding.json", [])
    atomic_json(folder / "spec.json", {"version": "v1"})
    hashes = {
        name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
        for name in ["bars.parquet", "funding.json", "spec.json"]
    }
    manifest = {"files": hashes, "data_hash": payload_hash(hashes)}
    atomic_json(folder / "manifest.json", manifest)
    _, bars, _, _ = load_dataset(tmp_path, identifier)
    assert len(bars) == 5 and bars[0].open_time_utc.tzinfo is UTC
    (folder / "funding.json").write_text("[{}]")
    with pytest.raises(ValueError, match="哈希"):
        load_dataset(tmp_path, identifier)
    (folder / "manifest.json").write_text(
        json.dumps({"files": {"../../outside": "x"}, "data_hash": "x"})
    )
    with pytest.raises(ValueError, match="manifest"):
        load_dataset(tmp_path, identifier)


def test_research_jobs_cross_runner_lock_orphan_and_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import threading

    from app import research_data
    from app.research_api import ResearchJobs
    from app.research_models import DatasetRequest
    from fastapi import HTTPException

    started = threading.Event()
    release = threading.Event()

    def collect(root: Path, p: DatasetRequest, progress: Any) -> dict[str, str]:
        progress("fixture progress")
        started.set()
        release.wait(3)
        return {"id": "offline-fixture"}

    monkeypatch.setattr(research_data, "collect", collect)
    runner = ResearchJobs(tmp_path)
    runner.start("DATASET", DatasetRequest(symbol="XAUUSDT"))
    assert started.wait(2)
    other = ResearchJobs(tmp_path)
    assert other.status()["state"] == "RUNNING"
    with pytest.raises(HTTPException) as rejected:
        other.start("DATASET", DatasetRequest(symbol="XAUUSDT"))
    assert rejected.value.status_code == 409
    release.set()
    assert runner.lock.acquire(timeout=3)
    runner.lock.release()
    assert runner.status()["state"] == "SUCCEEDED"
    audit = [
        json.loads(row)
        for row in (tmp_path / "reports/research_jobs.jsonl").read_text().splitlines()
    ]
    assert any(row["message"] == "fixture progress" for row in audit)
    (tmp_path / "reports/research_job.json").write_text(json.dumps({"state": "RUNNING"}))
    assert ResearchJobs(tmp_path).status()["state"] == "FAILED"
