"""Deterministic chronological research simulation; no broker or order adapter."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.bars import payload_hash
from app.models import Bar, utc_now
from app.research_data import aggregate, load_dataset
from app.research_models import BacktestRequest, MarketContext
from app.risk import floor_quantity
from app.storage import atomic_json
from app.strategies import TrendPullback

D = Decimal
ZERO = D(0)
ONE = D(1)


@dataclass
class Position:
    side: int
    quantity: Decimal
    entry: Decimal
    entry_reference: Decimal
    entry_at: datetime
    stop: Decimal
    target: Decimal
    entry_fee: Decimal
    candidate_id: str
    requested_quantity: Decimal
    held: int = 0
    funding: Decimal = ZERO


def code_hash() -> str:
    directory = Path(__file__).parent
    names = [
        "backtest.py",
        "strategies.py",
        "research_data.py",
        "research_models.py",
        "risk.py",
        "models.py",
        "bars.py",
    ]
    return payload_hash(
        {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in names}
    )


def filters(spec: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    values = {row["filterType"]: row for row in spec["spec"]["filters"]}
    lot = values["LOT_SIZE"]
    minimum = values.get("MIN_NOTIONAL", {}).get("notional", "0")
    return D(lot["stepSize"]), D(lot["minQty"]), D(lot["maxQty"]), D(str(minimum))


def simulate(
    bars: list[Bar],
    funding: list[dict[str, Any]],
    spec: dict[str, Any],
    params: BacktestRequest,
    slip_factor: Decimal = ONE,
) -> dict[str, Any]:
    lower = aggregate(bars, params.timeframe)
    minute_by_time = {b.open_time_utc: b for b in bars if b.is_closed and b.quality == "VALID"}
    hourly = aggregate(bars, "1h")
    step, min_qty, max_qty, min_notional = filters(spec)
    spread_slip = (params.slippage_bps * slip_factor + params.spread_bps / 2) / D(10000)
    fee_rate = params.fee_bps / D(10000)
    multiplier = params.simulated_multiplier
    if len(lower) < 100:
        raise ValueError("闭合研究周期不足 100 根，不能划分训练、验证和 holdout")
    cut1, cut2 = len(lower) * 6 // 10, len(lower) * 8 // 10
    splits = [("train", 0, cut1), ("validation", cut1, cut2), ("holdout", cut2, len(lower))]
    outcomes: dict[str, Any] = {}
    strategy = TrendPullback()
    for label, begin, end in splits:
        cash, peak, drawdown = params.initial_equity, params.initial_equity, ZERO
        position: Position | None = None
        trades: list[dict[str, Any]] = []
        curve: list[dict[str, str]] = []
        candidates: dict[str, Any] = {}
        costs = {"fees": ZERO, "funding": ZERO, "slippage_spread": ZERO}
        rejects = 0
        funding_index = 0
        ordered_funding = sorted(funding, key=lambda f: int(f["fundingTime"]))
        for index in range(begin, end):
            bar = lower[index]
            # Entry only at the next bar open after a preceding closed-bar decision.
            if position is None and index > begin:
                prior = lower[index - 1]
                contiguous = bar.open_at - prior.close_at == timedelta(milliseconds=1)
                if contiguous:
                    decision = prior.close_at + timedelta(milliseconds=1)
                    visible_hours = [h for h in hourly if h.close_at < decision][
                        -params.slow_window :
                    ]
                    context = MarketContext(
                        decision_at=decision,
                        symbol=bar.symbol,
                        spec_version=str(spec["version"]),
                        bars=visible_hours + lower[max(0, index - 40) : index],
                    )
                    candidate = strategy.evaluate(context, params)
                    if candidate:
                        candidates[candidate.candidate_id] = candidate.model_dump(mode="json")
                        side = 1 if candidate.direction == "LONG" else -1
                        history = lower[max(0, index - params.stop_window) : index]
                        stop = (
                            min(b.low for b in history)
                            if side == 1
                            else max(b.high for b in history)
                        )
                        entry = bar.open * (1 + side * spread_slip)
                        distance = (entry - stop) * side
                        unit_loss = distance * multiplier + (entry + stop) * multiplier * (
                            fee_rate + spread_slip
                        )
                        if distance > 0 and unit_loss > 0 and cash > 0:
                            requested = floor_quantity(
                                cash * params.risk_pct / 100 / unit_loss, step
                            )
                            capacity = floor_quantity(
                                prior.volume * params.participation_pct / 100, step
                            )
                            margin_cap = floor_quantity(
                                cash
                                / (
                                    entry
                                    * multiplier
                                    * (fee_rate + ONE / params.simulated_exchange_leverage)
                                ),
                                step,
                            )
                            quantity = min(requested, capacity, max_qty, margin_cap)
                            if (
                                quantity >= min_qty
                                and quantity * entry * multiplier >= min_notional
                            ):
                                fee = quantity * entry * multiplier * fee_rate
                                cash -= fee
                                costs["fees"] += fee
                                costs["slippage_spread"] += (
                                    quantity * abs(entry - bar.open) * multiplier
                                )
                                position = Position(
                                    side,
                                    quantity,
                                    entry,
                                    bar.open,
                                    bar.open_at,
                                    stop,
                                    entry + side * distance * params.reward_risk,
                                    fee,
                                    candidate.candidate_id,
                                    requested,
                                )
                            else:
                                rejects += 1
                        else:
                            rejects += 1
            # Execute exits and settlements against archived 1m bars.
            minute_count = 5 if params.timeframe == "5m" else 15
            if position:
                position.held += 1
            for offset in range(minute_count):
                minute = minute_by_time[bar.open_at + timedelta(minutes=offset)]
                while funding_index < len(ordered_funding) and int(
                    ordered_funding[funding_index]["fundingTime"]
                ) <= int(minute.close_time_utc.timestamp() * 1000):
                    row = ordered_funding[funding_index]
                    timestamp = int(row["fundingTime"])
                    if position is not None and timestamp > int(
                        position.entry_at.timestamp() * 1000
                    ):
                        if not row.get("markPrice"):
                            raise ValueError("资金费率缺少结算标记价，不允许填零替代")
                        charge = (
                            position.side
                            * position.quantity
                            * multiplier
                            * D(str(row["markPrice"]))
                            * D(str(row["fundingRate"]))
                        )
                        cash -= charge
                        position.funding += charge
                        costs["funding"] += charge
                    funding_index += 1
                if position:
                    stop_hit = (
                        minute.low <= position.stop
                        if position.side == 1
                        else minute.high >= position.stop
                    )
                    target_hit = (
                        minute.high >= position.target
                        if position.side == 1
                        else minute.low <= position.target
                    )
                    reference: Decimal | None = None
                    reason = ""
                    if stop_hit:
                        reference = (
                            min(minute.open, position.stop)
                            if position.side == 1
                            else max(minute.open, position.stop)
                        )
                        reason = "STOP_ADVERSE_FIRST"
                    elif target_hit:
                        reference, reason = position.target, "TARGET"
                    elif offset == minute_count - 1 and (
                        position.held >= params.max_holding_bars or index == end - 1
                    ):
                        reference, reason = minute.close, "TIME_OR_SPLIT_END"
                    if reference is not None:
                        price = reference * (1 - position.side * spread_slip)
                        pnl = (
                            position.side
                            * position.quantity
                            * multiplier
                            * (price - position.entry)
                        )
                        fee = position.quantity * price * multiplier * fee_rate
                        cash += pnl - fee
                        costs["fees"] += fee
                        costs["slippage_spread"] += (
                            position.quantity * abs(price - reference) * multiplier
                        )
                        net = pnl - fee - position.entry_fee - position.funding
                        trades.append(
                            {
                                "candidate_id": position.candidate_id,
                                "direction": "LONG" if position.side == 1 else "SHORT",
                                "entry_at": position.entry_at.isoformat(),
                                "exit_at": minute.close_time_utc.isoformat(),
                                "entry": str(position.entry),
                                "exit": str(price),
                                "stop": str(position.stop),
                                "quantity": str(position.quantity),
                                "requested_quantity": str(position.requested_quantity),
                                "unfilled_cancelled": str(
                                    position.requested_quantity - position.quantity
                                ),
                                "gross_pnl_after_spread_slip": str(pnl),
                                "net_pnl": str(net),
                                "fees": str(fee + position.entry_fee),
                                "funding": str(position.funding),
                                "reason": reason,
                            }
                        )
                        position = None
                marked = cash + (
                    position.side * position.quantity * multiplier * (minute.close - position.entry)
                    if position
                    else ZERO
                )
                peak = max(peak, marked)
                drawdown = max(drawdown, (peak - marked) / peak * 100)
            curve.append({"at": bar.close_at.isoformat(), "equity": str(marked)})
        wins = [D(t["net_pnl"]) for t in trades if D(t["net_pnl"]) > 0]
        loss = -sum((D(t["net_pnl"]) for t in trades if D(t["net_pnl"]) < 0), ZERO)
        outcomes[label] = {
            "first_at": lower[begin].open_at.isoformat(),
            "last_at": lower[end - 1].close_at.isoformat(),
            "bars": end - begin,
            "trades": trades,
            "candidate_count": len(candidates),
            "candidates": list(candidates.values()),
            "rejected_entries": rejects,
            "equity_curve": curve,
            "metrics": {
                "initial_equity": str(params.initial_equity),
                "final_equity": str(cash),
                "net_pnl": str(cash - params.initial_equity),
                "return_pct": str((cash / params.initial_equity - 1) * 100),
                "max_drawdown_pct": str(drawdown),
                "trade_count": len(trades),
                "win_rate_pct": str(D(len(wins)) / len(trades) * 100) if trades else None,
                "profit_factor": str(sum(wins, ZERO) / loss) if loss else None,
                "expectancy": str((cash - params.initial_equity) / len(trades)) if trades else None,
                "costs": {k: str(v) for k, v in costs.items()},
            },
        }
    return outcomes


def run(root: Path, params: BacktestRequest) -> dict[str, Any]:
    manifest, bars, funding, spec = load_dataset(root, params.dataset_id)
    if not manifest["complete_requested_range"]:
        raise ValueError("数据范围不完整或有缺口；请重新采集完整历史后研究")
    result: dict[str, Any] = {
        "run_id": str(uuid4()),
        "created_at": utc_now().isoformat(),
        "dataset_id": params.dataset_id,
        "symbol": manifest["symbol"],
        "quote_asset": spec["spec"]["quoteAsset"],
        "status": "RESEARCH_ONLY",
        "parameters": params.model_dump(mode="json"),
        "parameter_hash": payload_hash(params.model_dump(mode="json")),
        "data_hash": manifest["data_hash"],
        "code_hash": code_hash(),
        "splits": simulate(bars, funding, spec, params),
        "stress": {
            f"slippage_{factor}x": {
                k: v["metrics"] for k, v in simulate(bars, funding, spec, params, D(factor)).items()
            }
            for factor in (2, 5)
        },
        "warnings": manifest["warnings"]
        + [
            "手续费、价差、滑点、参与率、乘数均为用户可编辑的研究假设；未核验真实账户费用。",
            "三段按时间 60/20/20 划分，分别从初始权益开始；边界强制平仓。",
            "1m OHLC 同根触及止损与止盈时先计止损；部分成交剩余数量取消；"
            "参与率上限根据前根已知成交量。",
            "模拟保证金以显式研究杠杆计算并限制在现金内；未模拟强平、真实流动性或账户资格，不形成可执行计划。",
            "资金费结算按其所在分钟计入、先于该分钟退出；入场同刻结算排除，同分钟先后顺序未核验。",
            "历史成本模拟使用观察到的结算资金费；不能证明未来成本或策略盈利。",
        ],
        "live_trading_enabled": False,
        "metadata_ledger": "FILE_STAGING_PENDING_POSTGRESQL",
    }
    result["result_hash"] = payload_hash(
        {k: result[k] for k in ["parameter_hash", "data_hash", "code_hash", "splits", "stress"]}
    )
    atomic_json(root / "reports/research" / f"{result['run_id']}.json", result)
    return result


def runs(root: Path, limit: int | None = 30) -> list[dict[str, Any]]:
    files = sorted(
        (root / "reports/research").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return [json.loads(f.read_text(encoding="utf-8")) for f in files[:limit]]
