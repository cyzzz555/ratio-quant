"""Small P0 single-writer archive with locked atomic updates and conflicting-bar detection."""

import fcntl
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.models import Bar


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")

    def encode(item: Any) -> str:
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, Decimal):
            return str(item)
        raise TypeError(f"Unsupported JSON type: {type(item).__name__}")

    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=encode) + "\n")
    os.replace(tmp, path)


def bar_row(bar: Bar) -> dict[str, Any]:
    # Exact decimal strings in Parquet; timestamp columns retain UTC timezone.
    return {k: str(v) if isinstance(v, Decimal) else v for k, v in bar.model_dump().items()}


def economic_value(bar: Bar) -> tuple[Any, ...]:
    return (bar.open, bar.high, bar.low, bar.close, bar.volume, bar.close_time_utc)


class BarStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        for directory in ["closed", "open"]:
            (root / directory).mkdir(parents=True, exist_ok=True)

    def save(self, symbol: str, bars: list[Bar]) -> dict[str, int]:
        import re

        if not re.fullmatch(r"[A-Z0-9_]+", symbol):
            raise ValueError("invalid archive symbol")
        if any(b.instrument_id != f"BINANCE:USD_M_FUTURES:{symbol}" for b in bars):
            raise ValueError("archive instrument mismatch")
        closed_path = self.root / "closed" / f"{symbol}.parquet"
        open_path = self.root / "open" / f"{symbol}.json"
        with (self.root / f"{symbol}.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            existing = []
            if closed_path.exists():
                existing = [Bar.model_validate(x) for x in pq.read_table(closed_path).to_pylist()]
            closed = {b.key: b for b in existing}
            opened = {}
            if open_path.exists():
                opened = {
                    b.key: b for b in map(Bar.model_validate, json.loads(open_path.read_text()))
                }
            inserted = duplicate = 0
            for bar in bars:
                if bar.is_closed:
                    if bar.quality != "VALID":
                        raise ValueError("only valid confirmed bars can enter closed archive")
                    if bar.key in closed:
                        if economic_value(closed[bar.key]) != economic_value(bar):
                            raise ValueError("conflicting closed bar; requires reviewed revision")
                        duplicate += 1
                    else:
                        closed[bar.key] = bar
                        inserted += 1
                    opened.pop(bar.key, None)
                elif bar.key not in closed:
                    previous = opened.get(bar.key)
                    if previous is None or bar.received_at > previous.received_at:
                        opened[bar.key] = bar
            if closed:
                table = pa.Table.from_pylist(
                    [
                        bar_row(b)
                        for b in sorted(closed.values(), key=lambda x: (x.open_time_utc, x.source))
                    ]
                )
                tmp = closed_path.with_suffix(".parquet.tmp")
                pq.write_table(table, tmp, compression="zstd")
                os.replace(tmp, closed_path)
            # P0 open snapshot contains only the latest forming bar per source.
            latest: dict[str, Bar] = {}
            for bar in opened.values():
                if bar.source not in latest or bar.open_time_utc > latest[bar.source].open_time_utc:
                    latest[bar.source] = bar
            atomic_json(open_path, [b.model_dump(mode="json") for b in latest.values()])
            return {
                "inserted": inserted,
                "duplicates": duplicate,
                "closed_total": len(closed),
                "open_isolated": len(latest),
            }
