"""Audited public history, immutable Parquet snapshots and closed UTC aggregation."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from app.bars import missing_minutes, payload_hash, rest_bar
from app.market_catalog import visible_rows
from app.models import Bar, ProductFamily, from_ms, utc_now
from app.public_client import PublicClient, ReadResult
from app.research_models import DatasetRequest, ResearchBar
from app.storage import atomic_json, bar_row

PERIODS = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1d": 1440}
WARNINGS = [
    "RESEARCH_ONLY：短历史不能证明长期有效性；账户权限未核验。",
    "历史发布延迟假设为闭合后 1ms；实际延迟和历史修订未核验。",
    "当前交易所规格仅在采集时核验；历史规格、合约乘数仍未核验。",
    "日线按 UTC 边界聚合，仅为研究约定；真实交易时段尚未批准。",
]


def required(result: ReadResult) -> Any:
    if not result.ok:
        raise ValueError("公共接口不可用：" + result.evidence.result)
    return result.data


def current_spec(client: PublicClient, symbol: str) -> dict[str, Any]:
    response = client.get("/fapi/v1/exchangeInfo")
    payload = required(response)
    rows = [r for r in visible_rows(payload) if r["symbol"] == symbol]
    if len(rows) != 1:
        raise ValueError("当前逐品种 USD-M 规格不可核验")
    return {
        "version": response.evidence.raw_hash,
        "observed_at": response.evidence.timestamp.isoformat(),
        "symbol": symbol,
        "spec": rows[0],
        "account_permission": "UNKNOWN",
    }


def normalize(response: ReadResult, symbol: str, spec: str, server_at: datetime) -> list[Bar]:
    rows = required(response)
    if not isinstance(rows, list):
        raise ValueError("K 线响应不是数组")
    return [
        rest_bar(
            r,
            symbol=symbol,
            spec_version=spec,
            received_at=response.evidence.timestamp,
            server_time_before_request=server_at,
            response_hash=response.evidence.raw_hash or "",
        )
        for r in rows
    ]


def aggregate(bars: list[Bar], timeframe: str) -> list[ResearchBar]:
    minutes = PERIODS[timeframe]
    # REST takes priority over WS; one economic minute, never volume summed twice.
    unique: dict[datetime, Bar] = {}
    for bar in sorted(bars, key=lambda b: b.source, reverse=True):
        if bar.is_closed and bar.quality == "VALID":
            previous = unique.get(bar.open_time_utc)
            if previous and (
                previous.open,
                previous.high,
                previous.low,
                previous.close,
                previous.volume,
            ) != (bar.open, bar.high, bar.low, bar.close, bar.volume):
                raise ValueError("同一分钟价格冲突，禁止聚合")
            unique[bar.open_time_utc] = bar
    bins: dict[int, list[Bar]] = {}
    for bar in unique.values():
        key = int(bar.open_time_utc.timestamp()) // (minutes * 60)
        bins.setdefault(key, []).append(bar)
    result = []
    for key, rows in sorted(bins.items()):
        rows.sort(key=lambda b: b.open_time_utc)
        start = datetime.fromtimestamp(key * minutes * 60, UTC)
        if len(rows) != minutes or any(
            b.open_time_utc != start + timedelta(minutes=i) for i, b in enumerate(rows)
        ):
            continue
        result.append(
            ResearchBar(
                symbol=rows[0].instrument_id.rsplit(":", 1)[1],
                timeframe=timeframe,
                open_at=start,
                close_at=rows[-1].close_time_utc,
                open=rows[0].open,
                high=max(b.high for b in rows),
                low=min(b.low for b in rows),
                close=rows[-1].close,
                volume=sum((b.volume for b in rows), Decimal(0)),
                is_closed=True,
                quality="VALID",
                raw_hashes=[b.raw_hash for b in rows],
            )
        )
    return result


def market(root: Path, symbol: str, timeframe: str) -> dict[str, Any]:
    if timeframe not in PERIODS:
        raise ValueError("不支持的周期")
    audit = root / "reports/market/raw" / str(uuid4())
    with PublicClient(ProductFamily.USD_M_FUTURES, audit) as client:
        spec = current_spec(client, symbol)
        server = from_ms(required(client.get("/fapi/v1/time"))["serverTime"])
        rows = normalize(
            client.get("/fapi/v1/klines", {"symbol": symbol, "interval": "1m", "limit": 99}),
            symbol,
            str(spec["version"]),
            server,
        )
        premium = required(client.get("/fapi/v1/premiumIndex", {"symbol": symbol}))
    archive_used = False
    chart_rows = rows
    if timeframe in {"1h", "1d"}:
        available = [m for m in manifests(root) if m["symbol"] == symbol]
        if available:
            _, archive, _, _ = load_dataset(root, available[0]["id"])
            chart_rows = archive + rows
            archive_used = True
    closed = aggregate(chart_rows, timeframe)
    forming = [b.model_dump(mode="json") for b in rows if not b.is_closed]
    result = {
        "symbol": symbol,
        "quote_asset": spec["spec"]["quoteAsset"],
        "timeframe": timeframe,
        "bars": [b.model_dump(mode="json") for b in closed],
        "forming": forming,
        "mark_price": str(premium.get("markPrice", "")),
        "funding_rate": str(premium.get("lastFundingRate", "")),
        "server_at": server.isoformat(),
        "received_at": utc_now().isoformat(),
        "spec_version": spec["version"],
        "source": "BINANCE_PUBLIC_REST",
        "archive_used": archive_used,
        "chart_gap_count": len(missing_minutes(chart_rows)),
        "account_permission": "UNKNOWN",
        "live_trading_enabled": False,
    }
    atomic_json(root / "reports/market/latest.json", result)
    return result


def collect(root: Path, request: DatasetRequest, progress: Callable[[str], None]) -> dict[str, Any]:
    identifier = str(uuid4())
    folder = root / "data/research" / identifier
    folder.mkdir(parents=True)
    rows: dict[datetime, Bar] = {}
    with PublicClient(ProductFamily.USD_M_FUTURES, folder / "raw") as client:
        spec = current_spec(client, request.symbol)
        server = from_ms(required(client.get("/fapi/v1/time"))["serverTime"])
        end_ms = int(server.timestamp() // 60) * 60000 - 1
        start_ms = end_ms + 1 - request.days * 86400000
        cursor = start_ms
        while cursor <= end_ms:
            response = client.get(
                "/fapi/v1/klines",
                {
                    "symbol": request.symbol,
                    "interval": "1m",
                    "limit": 99,
                    "startTime": cursor,
                    "endTime": end_ms,
                },
            )
            page = normalize(response, request.symbol, str(spec["version"]), server)
            if not page:
                break
            if any(int(b.open_time_utc.timestamp() * 1000) < cursor for b in page):
                raise ValueError("分页未前进")
            for b in page:
                if b.is_closed:
                    if b.open_time_utc in rows and rows[b.open_time_utc].raw_hash != b.raw_hash:
                        raise ValueError("历史修订冲突")
                    rows[b.open_time_utc] = b
            cursor = int(page[-1].open_time_utc.timestamp() * 1000) + 60000
            progress(f"已采集 {len(rows)} 根闭合 1m K 线")
        funding: list[dict[str, Any]] = []
        cursor = start_ms
        while cursor <= end_ms:
            funding_page = required(
                client.get(
                    "/fapi/v1/fundingRate",
                    {
                        "symbol": request.symbol,
                        "startTime": cursor,
                        "endTime": end_ms,
                        "limit": 1000,
                    },
                )
            )
            if not isinstance(funding_page, list):
                raise ValueError("资金费率响应不是数组")
            funding.extend(funding_page)
            if len(funding_page) < 1000:
                break
            next_cursor = int(funding_page[-1]["fundingTime"]) + 1
            if next_cursor <= cursor:
                raise ValueError("资金费率分页未前进")
            cursor = next_cursor
    ordered = sorted(rows.values(), key=lambda b: b.open_time_utc)
    if not ordered:
        raise ValueError("没有可归档的历史 K 线")
    pq.write_table(
        pa.Table.from_pylist([bar_row(b) for b in ordered]),
        folder / "bars.parquet",
        compression="zstd",
    )
    atomic_json(folder / "funding.json", funding)
    atomic_json(folder / "spec.json", spec)
    import hashlib

    hashes = {
        name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
        for name in ["bars.parquet", "funding.json", "spec.json"]
    }
    gaps = missing_minutes(ordered)
    covered = len(ordered) == request.days * 1440
    manifest = {
        "id": identifier,
        "symbol": request.symbol,
        "quote_asset": spec["spec"]["quoteAsset"],
        "account_permission": "UNKNOWN",
        "created_at": utc_now().isoformat(),
        "days_requested": request.days,
        "count": len(ordered),
        "first_at": ordered[0].open_time_utc.isoformat(),
        "last_at": ordered[-1].close_time_utc.isoformat(),
        "files": hashes,
        "data_hash": payload_hash(hashes),
        "spec_version": spec["version"],
        "gaps": gaps,
        "complete_requested_range": covered and not gaps,
        "funding_count": len(funding),
        "funding_coverage": "OBSERVED_NOT_ACCOUNT_VERIFIED",
        "status": "RESEARCH_ONLY",
        "warnings": WARNINGS,
        "metadata_ledger": "FILE_STAGING_PENDING_POSTGRESQL",
    }
    atomic_json(folder / "manifest.json", manifest)
    return manifest


def manifests(root: Path, limit: int | None = 30) -> list[dict[str, Any]]:
    paths = sorted(
        (root / "data/research").glob("*/manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths[:limit]]


def load_dataset(
    root: Path, identifier: str
) -> tuple[dict[str, Any], list[Bar], list[dict[str, Any]], dict[str, Any]]:
    if str(__import__("uuid").UUID(identifier)) != identifier:
        raise ValueError("数据集 ID 无效")
    folder = root / "data/research" / identifier
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    import hashlib

    if (
        set(manifest["files"]) != {"bars.parquet", "funding.json", "spec.json"}
        or payload_hash(manifest["files"]) != manifest["data_hash"]
    ):
        raise ValueError("数据 manifest 无效")
    if any(
        hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest
        for name, digest in manifest["files"].items()
    ):
        raise ValueError("数据哈希校验失败，禁止回测")
    # Bound immutable path; SQL identifiers/expressions are never supplied by the UI.
    with duckdb.connect(":memory:") as conn:
        table = conn.execute(
            "SELECT * FROM read_parquet(?) ORDER BY open_time_utc", [str(folder / "bars.parquet")]
        ).to_arrow_table()
    bars = [Bar.model_validate(row) for row in table.to_pylist()]
    return (
        manifest,
        bars,
        json.loads((folder / "funding.json").read_text(encoding="utf-8")),
        json.loads((folder / "spec.json").read_text(encoding="utf-8")),
    )
