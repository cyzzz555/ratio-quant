from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
import pytest
from app.bars import missing_minutes, rest_bar, ws_bar
from app.models import Bar, from_ms, utc_now
from app.storage import BarStore


def normalize(row: list[Any], bound: datetime | None) -> Bar:
    return rest_bar(
        row,
        symbol="NVDAUSDT",
        spec_version="1" * 64,
        received_at=utc_now(),
        server_time_before_request=bound,
        response_hash="2" * 64,
    )


def test_rest_closure_and_exact_decimal(row: list[Any]) -> None:
    close = from_ms(row[6])
    assert not normalize(row, close).is_closed
    assert normalize(row, close + timedelta(milliseconds=1)).is_closed
    assert not normalize(row, None).is_closed
    assert normalize(row, None).quality == "PARTIAL"
    bar = normalize(row, utc_now())
    assert bar.open == Decimal("100.123456789012345678")
    assert bar.exchange_event_at is None and bar.open_time_utc.tzinfo is UTC


@pytest.mark.parametrize("mutation", ["short", "float", "nan", "ohlc", "negative", "duration"])
def test_bad_market_rows_rejected(row: list[Any], mutation: str) -> None:
    if mutation == "short":
        row.pop()
    elif mutation == "float":
        row[1] = 100.0
    elif mutation == "nan":
        row[1] = "NaN"
    elif mutation == "ohlc":
        row[2] = "90"
    elif mutation == "negative":
        row[5] = "-1"
    else:
        row[6] += 1
    with pytest.raises((ValueError, ArithmeticError)):
        normalize(row, utc_now())


def test_naive_and_invalid_chronology_rejected(bar: Bar) -> None:
    for update in [
        {"received_at": datetime(2026, 1, 1)},
        {"processed_at": bar.received_at - timedelta(seconds=1)},
        {"available_at": bar.received_at - timedelta(seconds=1)},
    ]:
        with pytest.raises(ValueError):
            Bar.model_validate({**bar.model_dump(), **update})


def test_duplicate_closed_bar_and_open_isolation(tmp_path: Path, bar: Bar) -> None:
    store = BarStore(tmp_path)
    forming = Bar.model_validate({**bar.model_dump(), "is_closed": False})
    assert store.save("NVDAUSDT", [forming])["open_isolated"] == 1
    result = store.save("NVDAUSDT", [bar, bar, bar])
    assert result == {"inserted": 1, "duplicates": 2, "closed_total": 1, "open_isolated": 0}
    assert store.save("NVDAUSDT", [bar, forming])["closed_total"] == 1
    rows = pq.read_table(tmp_path / "closed/NVDAUSDT.parquet").to_pylist()
    assert len(rows) == 1 and rows[0]["is_closed"] is True
    assert rows[0]["open"] == "100.123456789012345678"
    assert rows[0]["open_time_utc"].utcoffset() == timedelta(0)


def test_conflicting_bar_does_not_overwrite(tmp_path: Path, bar: Bar) -> None:
    store = BarStore(tmp_path)
    store.save("NVDAUSDT", [bar])
    changed = Bar.model_validate({**bar.model_dump(), "close": "100.5"})
    with pytest.raises(ValueError, match="conflicting"):
        store.save("NVDAUSDT", [changed])
    assert pq.read_table(tmp_path / "closed/NVDAUSDT.parquet").num_rows == 1


def test_gaps_remain_unclassified(bar: Bar) -> None:
    later = Bar.model_validate(
        {
            **bar.model_dump(),
            "open_time_utc": bar.open_time_utc + timedelta(minutes=4),
            "close_time_utc": bar.close_time_utc + timedelta(minutes=4),
        }
    )
    gaps = missing_minutes([bar, later])
    assert gaps[0]["missing_count"] == 3 and gaps[0]["classification"] == "UNVERIFIED"


@pytest.mark.parametrize(
    "date,hour_before,hour_after",
    [
        (datetime(2026, 3, 8, 6, 59, tzinfo=UTC), 1, 3),
        (datetime(2026, 11, 1, 5, 59, tzinfo=UTC), 1, 1),
    ],
)
def test_dst_does_not_change_utc_duration(
    date: datetime,
    hour_before: int,
    hour_after: int,
) -> None:
    after = date + timedelta(minutes=1)
    assert date.astimezone(ZoneInfo("America/New_York")).hour == hour_before
    assert after.astimezone(ZoneInfo("America/New_York")).hour == hour_after
    assert after - date == timedelta(minutes=1)
    assert date.astimezone(ZoneInfo("Asia/Shanghai")).astimezone(UTC) == date


def test_ws_exact_flag_and_event_time(row: list[Any]) -> None:
    now = utc_now()
    message = {
        "e": "kline",
        "s": "NVDAUSDT",
        "E": int(now.timestamp() * 1000),
        "k": {
            "s": "NVDAUSDT",
            "i": "1m",
            "x": False,
            "t": row[0],
            "T": row[6],
            "o": row[1],
            "h": row[2],
            "l": row[3],
            "c": row[4],
            "v": row[5],
        },
    }
    args = dict(symbol="NVDAUSDT", spec_version="1" * 64, received_at=now, response_hash="2" * 64)
    assert not ws_bar(message, **args).is_closed
    message["k"]["x"] = True
    assert ws_bar(message, **args).is_closed
    message["k"]["x"] = "false"
    with pytest.raises(ValueError, match="closed flag"):
        ws_bar(message, **args)
    message["k"]["x"] = True
    message["E"] -= 30000
    assert ws_bar(message, **args).quality == "STALE"
