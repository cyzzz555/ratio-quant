import json
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.models import ProductFamily, utc_now
from app.probe import run
from app.public_client import PublicClient
from app.settings import ROOT


def test_complete_report_pipeline_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    symbol_row: dict[str, Any],
    row: list[Any],
) -> None:
    shutil.copytree(ROOT / "config", tmp_path / "config")
    (tmp_path / "config/instruments.example.yaml").write_text(
        "watchlist_candidates:\n  stock_linked: [NVDAUSDT, MISSINGUSDT]\n", encoding="utf-8"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        path = request.url.path
        if path.endswith("exchangeInfo"):
            return httpx.Response(200, json={"symbols": [symbol_row]})
        if path.endswith("time"):
            return httpx.Response(200, json={"serverTime": int(utc_now().timestamp() * 1000)})
        if path.endswith("tradingSchedule"):
            return httpx.Response(200, json={"marketSchedules": {"EQUITY": {"sessions": []}}})
        if request.url.params.get("symbol") == "MISSINGUSDT":
            return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol"})
        if path.endswith("klines"):
            return httpx.Response(200, json=[row, row])
        if path.endswith("premiumIndex"):
            return httpx.Response(
                200,
                json={
                    "symbol": "NVDAUSDT",
                    "markPrice": "101",
                    "indexPrice": "101",
                    "time": row[0],
                },
            )
        return httpx.Response(
            200, json=[{"symbol": "NVDAUSDT", "fundingRate": "0.0001", "fundingTime": row[0]}]
        )

    def factory(family: ProductFamily, audit_dir: Path) -> PublicClient:
        return PublicClient(
            family, audit_dir, transport=httpx.MockTransport(handler), min_interval=0
        )

    monkeypatch.setattr("app.probe.PublicClient", factory)
    report = run(tmp_path, with_ws=False)
    visible, absent = report["instruments"]
    assert visible["capability_state"] == "VERIFIED_PUBLIC"
    assert visible["historical_bars_available"] is True
    assert visible["websocket_works"] is None
    assert absent["capability_state"] == "UNKNOWN"
    assert absent["historical_bars_available"] is None
    assert report["account_check_performed"] is False
    quality = json.loads((tmp_path / "reports/data_quality.json").read_text(encoding="utf-8"))
    assert quality[0]["inserted"] == 1 and quality[0]["duplicates"] == 1
    first = visible["first_verified_at"]
    assert run(tmp_path, with_ws=False)["instruments"][0]["first_verified_at"] == first
