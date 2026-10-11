"""Run public-only P0 verification and generate reproducible evidence artifacts."""

import argparse
import asyncio
import csv
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from app.bars import missing_minutes, payload_hash, rest_bar
from app.capabilities import resolve_candidate
from app.models import Bar, Capability, Phase0Report, ProductFamily, exact_decimal, from_ms, utc_now
from app.probe_jobs import exclusive_probe
from app.public_client import MARKET_DOC, WS_DOC, PublicClient, ReadResult
from app.settings import ROOT, load_settings
from app.storage import BarStore, atomic_json
from app.ws_probe import probe_ws


def validated_spec(row: dict[str, Any]) -> dict[str, Any]:
    filters = {x["filterType"]: x for x in row["filters"]}
    # These fields come from actual filters, never pricePrecision / quantityPrecision.
    numbers = {
        "tick_size": filters["PRICE_FILTER"]["tickSize"],
        "quantity_step": filters["LOT_SIZE"]["stepSize"],
        "min_quantity": filters["LOT_SIZE"]["minQty"],
        "min_notional": filters["MIN_NOTIONAL"]["notional"],
    }
    for value in numbers.values():
        if exact_decimal(value) <= 0:
            raise ValueError("non-positive filter value")
    return {
        "schema_version": "spec.v1",
        **numbers,
        "raw_exchange_symbol": row,
        "contract_multiplier": None,
        "multiplier_state": "UNVERIFIED",
    }


def server_bound(result: ReadResult) -> datetime | None:
    if not result.ok or not isinstance(result.data, dict):
        return None
    try:
        timestamp = from_ms(result.data["serverTime"])
        if abs(timestamp - result.evidence.timestamp) > timedelta(seconds=5):
            return None
        return timestamp
    except (KeyError, TypeError, ValueError):
        return None


def parse_bars(
    result: ReadResult,
    cap: Capability,
    server_time: datetime | None,
) -> tuple[list[Bar], list[str]]:
    errors, bars = [], []
    if not result.ok or not isinstance(result.data, list) or not result.data:
        return [], ["UNAVAILABLE: no usable kline payload"]
    if not cap.instrument.spec_version:
        return [], ["UNVERIFIED: cannot normalize bars without a valid instrument spec"]
    if not result.evidence.raw_hash:
        return [], ["UNVERIFIED: raw response hash missing"]
    for index, row in enumerate(result.data):
        try:
            bars.append(
                rest_bar(
                    row,
                    symbol=cap.symbol,
                    spec_version=cap.instrument.spec_version,
                    received_at=result.evidence.timestamp,
                    server_time_before_request=server_time,
                    response_hash=result.evidence.raw_hash,
                    session_model_version=cap.instrument.session_model_version,
                )
            )
        except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
            errors.append(f"row {index}: {type(exc).__name__}: {exc}")
    return bars, errors


def run(root: Path = ROOT, *, with_ws: bool = True) -> dict[str, Any]:
    with exclusive_probe(root):
        return _run(root, with_ws=with_ws)


def _run(root: Path, *, with_ws: bool) -> dict[str, Any]:
    load_settings(root)
    started = utc_now()
    run_id = str(uuid4())
    report_dir = root / "reports"
    raw_dir = report_dir / "raw" / run_id
    store = BarStore(root / "data")
    candidates = yaml.safe_load(
        (root / "config/instruments.example.yaml").read_text(encoding="utf-8")
    )
    caps, quality = [], []
    previous: dict[str, Any] = {}
    prior_path = report_dir / "instrument_capabilities.json"
    if prior_path.exists():
        try:
            previous = {
                x["symbol"]: x
                for x in json.loads(prior_path.read_text(encoding="utf-8"))["instruments"]
            }
        except (ValueError, KeyError, TypeError):
            previous = {}
    with PublicClient(ProductFamily.USD_M_FUTURES, raw_dir) as client:
        info = client.get("/fapi/v1/exchangeInfo")
        schedule = client.get("/fapi/v1/tradingSchedule")
        session_version = None
        if (
            schedule.ok
            and isinstance(schedule.data, dict)
            and isinstance(schedule.data.get("marketSchedules"), dict)
            and schedule.data["marketSchedules"]
        ):
            session_version = schedule.evidence.raw_hash
            atomic_json(
                report_dir / "sessions" / f"{session_version}.json",
                {
                    "schema_version": "session.v1",
                    "fetched_at": schedule.evidence.timestamp,
                    "raw_schedule": schedule.data,
                    "symbol_mapping_state": "UNVERIFIED",
                    "note": "Underlying sessions are not a promise of derivative trading hours.",
                },
            )
        for category, symbols in candidates["watchlist_candidates"].items():
            for symbol in symbols:
                cap = resolve_candidate(symbol, category, info)
                evidence = [info.evidence, schedule.evidence]
                notes = list(cap.notes)
                if cap.public_exchangeinfo_visible:
                    row = next(x for x in info.data["symbols"] if x["symbol"] == symbol)
                    try:
                        spec = validated_spec(row)
                        spec_version = payload_hash(spec)
                        atomic_json(
                            report_dir / "specs" / symbol / f"{spec_version}.json",
                            {
                                "version": spec_version,
                                "observed_at": info.evidence.timestamp,
                                "effective_at": None,
                                "effective_at_state": "UNVERIFIED",
                                "response_hash": info.evidence.raw_hash,
                                "spec": spec,
                            },
                        )
                        cap = cap.model_copy(
                            update={
                                "instrument": cap.instrument.model_copy(
                                    update={
                                        "spec_version": spec_version,
                                        "session_model_version": session_version,
                                    }
                                )
                            }
                        )
                    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                        notes.append(f"UNVERIFIED spec: {type(exc).__name__}: {exc}")
                clock_result = client.get("/fapi/v1/time")
                evidence.append(clock_result.evidence)
                bound = server_bound(clock_result)
                if bound is None:
                    notes.append("UNVERIFIED server time / clock drift; REST bars kept unclosed.")
                recent = client.get(
                    "/fapi/v1/klines",
                    {
                        "symbol": symbol,
                        "interval": "1m",
                        "limit": 60,
                    },
                )
                evidence.append(recent.evidence)
                bars, errors = parse_bars(recent, cap, bound)
                history_available: bool | None = True if bars and not errors else None
                first_time = None
                if cap.instrument.spec_version:
                    earliest = client.get(
                        "/fapi/v1/klines",
                        {
                            "symbol": symbol,
                            "interval": "1m",
                            "startTime": 0,
                            "limit": 1,
                        },
                    )
                    evidence.append(earliest.evidence)
                    early_bars, early_errors = parse_bars(earliest, cap, bound)
                    if early_bars and not early_errors:
                        first_time = early_bars[0].open_time_utc
                    else:
                        notes.extend(early_errors)
                mark = client.get("/fapi/v1/premiumIndex", {"symbol": symbol})
                evidence.append(mark.evidence)
                mark_available = None
                if mark.ok and isinstance(mark.data, dict) and mark.data.get("symbol") == symbol:
                    try:
                        if (
                            min(
                                exact_decimal(mark.data["markPrice"]),
                                exact_decimal(mark.data["indexPrice"]),
                            )
                            <= 0
                        ):
                            raise ValueError("non-positive mark/index")
                        from_ms(mark.data["time"])
                        mark_available = True
                    except (ValueError, KeyError, ArithmeticError) as exc:
                        notes.append(f"UNVERIFIED mark: {exc}")
                funding = client.get("/fapi/v1/fundingRate", {"symbol": symbol, "limit": 3})
                evidence.append(funding.evidence)
                funding_available = None
                if funding.ok and isinstance(funding.data, list) and funding.data:
                    try:
                        for f in funding.data:
                            if f["symbol"] != symbol:
                                raise ValueError("funding symbol mismatch")
                            exact_decimal(f["fundingRate"])
                            from_ms(f["fundingTime"])
                        funding_available = True
                    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                        notes.append(f"UNVERIFIED funding: {exc}")
                ws_works = None
                if with_ws and cap.instrument.spec_version:
                    ws_works, ws_evidence, ws_sample = asyncio.run(
                        probe_ws(
                            symbol,
                            cap.instrument.spec_version,
                            raw_dir,
                            session_version,
                        )
                    )
                    evidence.append(ws_evidence)
                    if ws_sample:
                        bars.append(ws_sample)
                    else:
                        notes.append(ws_evidence.result)
                else:
                    notes.append("WS UNVERIFIED: disabled or instrument spec unavailable.")
                try:
                    stored = store.save(symbol, bars)
                except ValueError as exc:
                    stored = {"inserted": 0, "duplicates": 0, "closed_total": 0, "open_isolated": 0}
                    errors.append(f"Archive rejected: {exc}")
                rest_closed = [b for b in bars if b.is_closed and b.source == "BINANCE_REST"]
                latest_closed = max((b.close_time_utc for b in rest_closed), default=None)
                timeliness = "UNAVAILABLE"
                if latest_closed:
                    age = utc_now() - latest_closed
                    timeliness = (
                        "FRESH" if timedelta(0) <= age <= timedelta(seconds=180) else "STALE"
                    )
                q = dict(
                    symbol=symbol,
                    sampled_bars=len(bars),
                    closed_sample=len(rest_closed),
                    unclosed_sample=sum(not b.is_closed for b in bars),
                    normalization_errors=errors,
                    gaps=missing_minutes(rest_closed),
                    gap_model_version="gap.v1",
                    gap_classification="UNVERIFIED",
                    latest_closed_at=latest_closed.isoformat() if latest_closed else None,
                    timeliness=timeliness,
                    quality="VALID" if rest_closed and not errors else "UNAVAILABLE",
                    **stored,
                )
                quality.append(q)
                notes.extend(errors)
                cap_data = cap.model_dump()
                cap_data.update(
                    historical_bars_available=history_available,
                    history_start_at=first_time,
                    history_start_scope="EARLIEST_RETURNED_BY_QUERY"
                    if first_time
                    else "UNVERIFIED",
                    mark_price_available=mark_available,
                    funding_data_available=funding_available,
                    websocket_works=ws_works,
                    evidence=evidence,
                    notes=notes,
                )
                if cap.first_verified_at and previous.get(symbol, {}).get("first_verified_at"):
                    cap_data["first_verified_at"] = previous[symbol]["first_verified_at"]
                cap = Capability.model_validate(cap_data)
                caps.append(cap)
                print(
                    f"{symbol}: {cap.capability_state}; history={history_available}; "
                    f"ws={ws_works}; closed={q['closed_sample']}",
                    flush=True,
                )
    envelope = {
        "schema_version": "phase0-report.v2",
        "run_id": run_id,
        "started_at": started,
        "generated_at": utc_now(),
        "live_trading_enabled": False,
        "approval_mode": "HUMAN",
        "trade_adapter": "PAPER_BROKER",
        "account_check_performed": False,
        "product_families_probed": ["USD_M_FUTURES"],
        "documentation_urls": [MARKET_DOC, WS_DOC],
        "raw_directory": str(raw_dir.relative_to(root)),
        "instruments": [c.model_dump(mode="json") for c in caps],
    }
    envelope = Phase0Report.model_validate(envelope).model_dump(mode="json")
    atomic_json(report_dir / "runs" / f"{run_id}.json", envelope)
    atomic_json(prior_path, envelope)
    atomic_json(report_dir / "data_quality.json", quality)
    fields = [
        "symbol",
        "product_family",
        "capability_state",
        "public_exchangeinfo_visible",
        "account_trade_permission",
        "max_public_leverage",
        "max_account_leverage",
        "isolated_supported",
        "reduce_only_supported",
        "trading_status",
        "historical_bars_available",
        "websocket_works",
        "mark_price_available",
        "funding_data_available",
        "history_start_at",
        "verified_at",
    ]
    with (report_dir / "instrument_capabilities.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for cap in caps:
            row = cap.model_dump(mode="json")
            writer.writerow({k: "UNVERIFIED" if row[k] is None else row[k] for k in fields})
    counts = Counter(c.capability_state.value for c in caps)
    lines = [
        "# P0 数据质量报告",
        "",
        f"生成时间（UTC）：{envelope['generated_at']}",
        f"运行 ID：{run_id}；能力状态：{dict(counts)}",
        "",
        "公共可见性不能证明账户或地区权限。当前工程无下单接口，LIVE=false。",
        "",
        "| 符号 | 最近 REST 闭合 bar | 未收盘样本 | 缺口段数 | 质量 |",
        "|---|---:|---:|---:|---|",
    ]
    lines += [
        f"| {q['symbol']} | {q['closed_sample']} | {q['unclosed_sample']} | "
        f"{len(q['gaps'])} | {q['quality']} |"
        for q in quality
    ]
    lines += [
        "",
        "金额使用 Decimal；Parquet 数值列保存精确十进制字符串，时间列为 UTC。",
        "REST 无事件时间字段，exchange_event_at=null；闭合判断依据请求前服务器时间。",
        "未收盘样本仅在 data/open；闭合档案在 data/closed，按源去重，冲突拒绝覆盖。",
        "当前为小样本探测，不能证明持续行情稳定性、完整长期历史或策略有效性。",
        "缺口仅为观测；时段归属、非传统资产时段定价、合约乘数尚未确认。",
        "history_start_at 是 startTime=0 查询返回的首个时间，不承诺数据完整覆盖。",
        "",
        "## 未完成的账户核验",
        "",
        "9 个品种的账户交易资格、最大杠杆、逐仓、保护单/reduceOnly、费率均 UNVERIFIED。",
        "P0 不使用凭证；待 P4 通过授权只读核验。保持本金损失容忍 50%、常规 10–20x、",
        "单仓最高 25x 的设计要求；其余微资金阈值仍是研究/模拟候选。",
        "",
        "## 异常记录",
        "",
    ]
    for cap in caps:
        lines += [f"- {cap.symbol}：{'; '.join(cap.notes)}"]
    (report_dir / "data_quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return envelope


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-ws", action="store_true", help="mark WS UNVERIFIED without probing")
    args = parser.parse_args()
    run(with_ws=not args.no_ws)


if __name__ == "__main__":
    main()
