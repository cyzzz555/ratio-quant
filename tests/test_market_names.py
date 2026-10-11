import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from app import market_catalog
from app.market_catalog import CatalogService, NameConflict, NameUpdateRequest
from app.models import ProductFamily
from app.public_client import PublicClient
from app.research_api import router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError


def directory(
    root: Path, monkeypatch: pytest.MonkeyPatch, symbol_row: dict[str, Any]
) -> CatalogService:
    (root / "config").mkdir()
    (root / "config/market_names.zh.json").write_text(
        '{"EQUITY:NVDA":"英伟达", "BTC":"比特币"}', encoding="utf-8"
    )
    rows = [
        symbol_row,
        {**symbol_row, "symbol": "NVDAUSDC", "quoteAsset": "USDC"},
        {**symbol_row, "symbol": "NVDATOKENUSDT", "underlyingType": "COIN"},
    ]

    def factory(family: ProductFamily, audit: Path) -> PublicClient:
        return PublicClient(
            family,
            audit,
            sleep=lambda _: None,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"symbols": rows})),
        )

    monkeypatch.setattr(market_catalog, "PublicClient", factory)
    service = CatalogService(root)
    service.get()
    return service


def edit(name: str = "英伟达（NVIDIA）", expected: str = "英伟达") -> NameUpdateRequest:
    return NameUpdateRequest(symbol="NVDAUSDT", name_zh=name, expected_name=expected)


def test_save_local_persistent_and_related_assets_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, symbol_row: dict[str, Any]
) -> None:
    service = directory(tmp_path, monkeypatch, symbol_row)
    request_count = len(list((tmp_path / "reports/market/catalog_raw").rglob("requests.jsonl")))
    saved = service.save_name(edit())
    assert set(saved.affected_symbols) == {"NVDAUSDT", "NVDAUSDC"}
    names = {i.symbol: i.name_zh for i in saved.catalog.instruments}
    assert names["NVDAUSDT"] == names["NVDAUSDC"] == "英伟达（NVIDIA）"
    assert names["NVDATOKENUSDT"] == "中文名待补充"
    assert saved.catalog.live_trading_enabled is False
    aliases = json.loads((tmp_path / "config/market_names.zh.json").read_text(encoding="utf-8"))
    assert aliases["BTC"] == "比特币" and aliases["EQUITY:NVDA"] == "英伟达（NVIDIA）"
    events = (
        (tmp_path / "reports/market/name_updates.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert json.loads(events[0])["before"] == "英伟达"
    # A new process can edit from the persisted observed directory without any network fetch.
    restarted = CatalogService(tmp_path)
    restarted.save_name(edit("英伟达", "英伟达（NVIDIA）"))
    assert service.get().instruments[0].name_zh == "中文名待补充"  # token sorts first
    assert next(i for i in service.get().instruments if i.symbol == "NVDAUSDT").name_zh == "英伟达"
    audit_files = list((tmp_path / "reports/market/catalog_raw").rglob("requests.jsonl"))
    assert len(audit_files) == request_count
    assert all(i.account_permission == "UNKNOWN" for i in saved.catalog.instruments)


def test_conflict_or_unknown_symbol_preserves_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, symbol_row: dict[str, Any]
) -> None:
    service = directory(tmp_path, monkeypatch, symbol_row)
    service.save_name(edit())
    path = tmp_path / "config/market_names.zh.json"
    before = path.read_bytes()
    with pytest.raises(NameConflict):
        CatalogService(tmp_path).save_name(edit("不应覆盖"))
    with pytest.raises(ValueError, match="不在已观测目录"):
        service.save_name(
            NameUpdateRequest(symbol="FAKEUSDT", name_zh="不存在", expected_name="中文名待补充")
        )
    assert path.read_bytes() == before


@pytest.mark.parametrize("name", ["", "   ", "NVIDIA", "中文\n换行", "中文名待补充", "字" * 81])
def test_invalid_name_is_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        edit(name)


def test_edit_api_local_origin_validation_conflict_and_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, symbol_row: dict[str, Any]
) -> None:
    directory(tmp_path, monkeypatch, symbol_row)
    app = FastAPI()
    app.include_router(router(tmp_path))
    client = TestClient(app, client=("127.0.0.1", 50000), base_url="http://127.0.0.1:8000")
    body = edit().model_dump()
    headers = {"Origin": "http://127.0.0.1:5173"}
    assert client.post("/api/v1/market/names", json=body).status_code == 403
    assert (
        client.post(
            "/api/v1/market/names", json={**body, "path": "../../secret"}, headers=headers
        ).status_code
        == 422
    )
    assert client.post("/api/v1/market/names", json=body, headers=headers).status_code == 200
    assert client.post("/api/v1/market/names", json=body, headers=headers).status_code == 409
    assert client.post("/api/v1/orders", json={}).status_code == 404
