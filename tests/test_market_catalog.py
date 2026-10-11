import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from app import market_catalog, research_data
from app.market_catalog import CatalogService, display_name, visible_rows
from app.models import ProductFamily, utc_now
from app.public_client import PublicClient
from app.research_api import router
from fastapi import FastAPI
from fastapi.testclient import TestClient


def install_client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    def factory(family: ProductFamily, audit: Path) -> PublicClient:
        return PublicClient(
            family, audit, transport=httpx.MockTransport(handler), sleep=lambda _: None
        )

    monkeypatch.setattr(market_catalog, "PublicClient", factory)
    monkeypatch.setattr(research_data, "PublicClient", factory)


def test_catalog_full_directory_aliases_cache_and_expired_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, symbol_row: dict[str, Any]
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/market_names.zh.json").write_text('{"BTC":"比特币"}', encoding="utf-8")
    rows = [
        {**symbol_row, "symbol": "BTCUSDT", "baseAsset": "BTC"},
        {**symbol_row, "symbol": "NEWUSDT", "baseAsset": "NEW"},
        {**symbol_row, "symbol": "OLDUSDT", "status": "SETTLING"},
        {**symbol_row, "symbol": "OTHERUSD", "status": "PENDING_TRADING"},
    ]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"symbols": rows})

    install_client(monkeypatch, handler)
    service = CatalogService(tmp_path)
    first = service.get()
    assert [i.symbol for i in first.instruments] == ["BTCUSDT", "NEWUSDT"]
    assert first.instruments[0].name_zh == "比特币"
    assert first.instruments[1].name_source == "UNAVAILABLE"
    assert first.instruments[1].name_zh == "中文名待补充"
    assert all(i.account_permission == "UNKNOWN" for i in first.instruments)
    assert first.live_trading_enabled is False
    first.instruments.clear()
    assert len(service.get().instruments) == 2 and len(calls) == 1
    snapshot = json.loads((tmp_path / "reports/market/catalog.json").read_text(encoding="utf-8"))
    assert len(snapshot["raw_hash"]) == 64
    assert list((tmp_path / "reports/market/catalog_raw").rglob("requests.jsonl"))
    service.get(refresh=True)
    assert len(calls) == 2
    snapshot = json.loads((tmp_path / "reports/market/catalog.json").read_text(encoding="utf-8"))
    service.expires_at = 0
    rows.clear()
    with pytest.raises(ValueError, match="没有当前可见"):
        service.get()
    assert (
        json.loads((tmp_path / "reports/market/catalog.json").read_text(encoding="utf-8"))
        == snapshot
    )


@pytest.mark.parametrize(
    "payload",
    [{}, {"symbols": None}, {"symbols": [None]}, {"symbols": []}],
)
def test_invalid_directory_fails_closed(payload: Any) -> None:
    with pytest.raises(ValueError):
        visible_rows(payload)


def test_duplicate_missing_and_unsafe_symbols(symbol_row: dict[str, Any]) -> None:
    assert visible_rows({"symbols": [{**symbol_row, "symbol": "币安人生USDT"}]})
    for rows in (
        [symbol_row, symbol_row],
        [{**symbol_row, "symbol": "../../secret"}],
        [{**symbol_row, "quoteAsset": None}],
    ):
        with pytest.raises(ValueError):
            visible_rows({"symbols": rows})


def test_asset_alias_does_not_confuse_token_and_equity() -> None:
    aliases = {"EQUITY:F": "福特汽车"}
    assert display_name({"underlyingType": "COIN", "baseAsset": "F"}, aliases) is None
    assert display_name({"underlyingType": "EQUITY", "baseAsset": "F"}, aliases) == "福特汽车"


@pytest.mark.parametrize("symbol", ["BTCUSDC", "SPCXUSD1", "币安人生USDT"])
def test_new_market_symbol_uses_current_spec_without_p0_permission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    symbol_row: dict[str, Any],
    row: list[Any],
    symbol: str,
) -> None:
    paths: list[str] = []
    quote = "USD1" if symbol.endswith("USD1") else "USDC" if symbol.endswith("USDC") else "USDT"
    spec = {
        **symbol_row,
        "symbol": symbol,
        "baseAsset": symbol.removesuffix(quote),
        "marginAsset": quote,
        "quoteAsset": quote,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.method == "GET" and request.url.host == "fapi.binance.com"
        payloads = {
            "/fapi/v1/exchangeInfo": {"symbols": [spec]},
            "/fapi/v1/time": {"serverTime": int(utc_now().timestamp() * 1000)},
            "/fapi/v1/klines": [row],
            "/fapi/v1/premiumIndex": {"markPrice": "101", "lastFundingRate": "0.001"},
        }
        return httpx.Response(200, json=payloads[request.url.path])

    install_client(monkeypatch, handler)
    result = research_data.market(tmp_path, symbol, "1m")
    assert result["symbol"] == symbol and result["quote_asset"] == quote
    assert result["bars"] and result["account_permission"] == "UNKNOWN"
    assert result["live_trading_enabled"] is False
    assert paths[0] == "/fapi/v1/exchangeInfo"
    paths.clear()
    spec["status"] = "SETTLING"
    with pytest.raises(ValueError):
        research_data.market(tmp_path, symbol, "1m")
    assert paths == ["/fapi/v1/exchangeInfo"]


def test_catalog_route_local_origin_and_unavailability(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(router(tmp_path))
    client = TestClient(app, client=("127.0.0.1", 50000), base_url="http://127.0.0.1:8000")
    assert client.post("/api/v1/market/catalog", json={}).status_code == 403
    response = client.post(
        "/api/v1/market/catalog", json={}, headers={"Origin": "http://127.0.0.1:5173"}
    )
    assert response.status_code == 503 and "目录读取失败" in response.json()["detail"]
    assert client.post("/api/v1/orders", json={}).status_code == 404


@pytest.mark.parametrize("symbol", ["MUUSDT", "SPCXUSD1", "币安人生USDT"])
def test_history_full_directory_rechecks_spec_before_pagination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    symbol_row: dict[str, Any],
    row: list[Any],
    symbol: str,
) -> None:
    from app.research_data import load_dataset
    from app.research_models import DatasetRequest

    quote = "USD1" if symbol.endswith("USD1") else "USDT"
    spec = {
        **symbol_row,
        "symbol": symbol,
        "baseAsset": symbol.removesuffix(quote),
        "quoteAsset": quote,
        "marginAsset": quote,
    }
    server_ms = 1791676800000
    start_ms = server_ms - 86400000
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.method == "GET" and request.url.host == "fapi.binance.com"
        if request.url.path == "/fapi/v1/exchangeInfo":
            return httpx.Response(200, json={"symbols": [spec]})
        if request.url.path == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": server_ms})
        if request.url.path == "/fapi/v1/fundingRate":
            return httpx.Response(
                200,
                json=[
                    {
                        "symbol": symbol,
                        "fundingTime": start_ms,
                        "fundingRate": "0.0001",
                        "markPrice": "100",
                    }
                ],
            )
        assert request.url.path == "/fapi/v1/klines"
        cursor = int(request.url.params["startTime"])
        end = int(request.url.params["endTime"])
        return httpx.Response(
            200,
            json=[
                [stamp, *row[1:6], stamp + 59999, *row[7:]]
                for stamp in range(cursor, min(cursor + 99 * 60000, end + 1), 60000)
            ],
        )

    install_client(monkeypatch, handler)
    manifest = research_data.collect(
        tmp_path, DatasetRequest(symbol=symbol, days=1), lambda _: None
    )
    assert manifest["complete_requested_range"] and manifest["count"] == 1440
    assert manifest["quote_asset"] == quote and manifest["account_permission"] == "UNKNOWN"
    assert calls[:2] == ["/fapi/v1/exchangeInfo", "/fapi/v1/time"]
    assert calls.count("/fapi/v1/klines") == 15
    _, bars, funding, observed = load_dataset(tmp_path, manifest["id"])
    assert len(bars) == 1440 and funding[0]["symbol"] == symbol
    assert observed["spec"]["symbol"] == symbol
    assert not (tmp_path / "reports/instrument_capabilities.json").exists()
    calls.clear()
    spec["status"] = "SETTLING"
    with pytest.raises(ValueError):
        research_data.collect(tmp_path, DatasetRequest(symbol=symbol, days=1), lambda _: None)
    assert calls == ["/fapi/v1/exchangeInfo"]
