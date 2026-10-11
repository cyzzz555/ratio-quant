from datetime import timedelta
from typing import Any

import pytest
from app.bars import rest_bar
from app.models import Bar, Evidence, utc_now
from app.public_client import ReadResult


@pytest.fixture
def symbol_row() -> dict[str, Any]:
    return {
        "symbol": "NVDAUSDT",
        "contractType": "TRADIFI_PERPETUAL",
        "status": "TRADING",
        "baseAsset": "NVDA",
        "quoteAsset": "USDT",
        "marginAsset": "USDT",
        "underlyingType": "EQUITY",
        "pricePrecision": 8,
        "quantityPrecision": 9,
        "requiredMarginPercent": "5.0000",
        "maintMarginPercent": "2.5000",
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "LOT_SIZE", "stepSize": "0.01", "minQty": "0.01"},
            {"filterType": "MIN_NOTIONAL", "notional": "5"},
        ],
    }


@pytest.fixture
def info_result(symbol_row: dict[str, Any]) -> ReadResult:
    return ReadResult(
        {"symbols": [symbol_row]},
        Evidence(
            source="https://fapi.binance.com/fapi/v1/exchangeInfo",
            timestamp=utc_now(),
            result="HTTP 200",
            http_status=200,
            raw_hash="1" * 64,
        ),
        0,
    )


@pytest.fixture
def row() -> list[Any]:
    start = utc_now().replace(second=0, microsecond=0) - timedelta(minutes=3)
    epoch_ms = int(start.timestamp()) * 1000
    return [
        epoch_ms,
        "100.123456789012345678",
        "102",
        "99",
        "101",
        "3.14",
        epoch_ms + 59999,
        "300",
        2,
        "1",
        "100",
        "0",
    ]


@pytest.fixture
def bar(row: list[Any]) -> Bar:
    return rest_bar(
        row,
        symbol="NVDAUSDT",
        spec_version="1" * 64,
        received_at=utc_now(),
        server_time_before_request=utc_now(),
        response_hash="2" * 64,
    )
