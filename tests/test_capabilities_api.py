import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from app.capabilities import resolve_candidate
from app.main import create_app
from app.models import Capability, CapabilityState, utc_now
from app.probe import server_bound, validated_spec
from app.public_client import ReadResult
from app.settings import ROOT, load_settings
from fastapi.testclient import TestClient


def test_public_not_account(info_result: ReadResult) -> None:
    cap = resolve_candidate("NVDAUSDT", "stock_linked", info_result)
    assert cap.capability_state == CapabilityState.VERIFIED_PUBLIC
    assert cap.account_trade_permission == "UNKNOWN"
    assert cap.max_public_leverage is None and cap.max_account_leverage is None
    assert cap.underlying.mapping_state == "UNVERIFIED"
    with pytest.raises(ValueError):
        Capability.model_validate({**cap.model_dump(), "account_trade_permission": "YES"})


@pytest.mark.parametrize(
    "data", [{}, {"symbols": []}, {"symbols": [None]}, {"symbols": [{"symbol": "NVDAUSDT"}]}]
)
def test_incomplete_exchangeinfo_never_claims_absence(
    data: Any,
    info_result: ReadResult,
) -> None:
    cap = resolve_candidate(
        "NVDAUSDT",
        "stock_linked",
        ReadResult(
            data,
            info_result.evidence,
            0,
        ),
    )
    assert cap.capability_state == CapabilityState.UNKNOWN
    assert cap.public_exchangeinfo_visible is None


def test_absent_is_not_delisted(info_result: ReadResult) -> None:
    cap = resolve_candidate("MISSINGUSDT", "metals", info_result)
    assert cap.capability_state == CapabilityState.UNKNOWN
    assert cap.public_exchangeinfo_visible is False and cap.product_family == "UNVERIFIED"


@pytest.mark.parametrize("http_status", [403, 404, 429, 500])
def test_error_is_not_absence(http_status: int, info_result: ReadResult) -> None:
    evidence = info_result.evidence.model_copy(update={"http_status": http_status})
    cap = resolve_candidate("NVDAUSDT", "stock_linked", ReadResult({}, evidence, 0))
    assert cap.capability_state == CapabilityState.UNAVAILABLE
    assert cap.public_exchangeinfo_visible is None


def test_filters_not_precision(symbol_row: dict[str, Any]) -> None:
    spec = validated_spec(symbol_row)
    assert spec["tick_size"] == "0.01" and spec["quantity_step"] == "0.01"
    assert spec["contract_multiplier"] is None


def test_shared_route_does_not_change_product_family(
    info_result: ReadResult,
    symbol_row: dict[str, Any],
) -> None:
    symbol_row.update(marginAsset="BTC", quoteAsset="USD")
    cap = resolve_candidate("NVDAUSDT", "stock_linked", info_result)
    assert cap.product_family == "UNVERIFIED"
    assert cap.instrument.product_family_verified is None


def test_server_time_missing_or_drift(info_result: ReadResult) -> None:
    assert server_bound(info_result) is None
    assert server_bound(ReadResult({"serverTime": 1}, info_result.evidence, 0)) is None


@pytest.mark.parametrize(
    "key,value",
    [("LIVE_TRADING_ENABLED", "true"), ("APPROVAL_MODE", "AUTO"), ("TRADE_ADAPTER", "BINANCE")],
)
def test_env_cannot_unlock_live(monkeypatch: pytest.MonkeyPatch, key: str, value: str) -> None:
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="P0 requires"):
        load_settings()


def test_confirmed_vs_proposed_risk_values() -> None:
    micro = load_settings()["risk"]["micro_capital"]
    confirmed = micro["user_confirmed"]
    assert confirmed["acceptable_initial_principal_loss_pct"] == "50.0"
    assert (
        confirmed["preferred_exchange_leverage_min"],
        confirmed["preferred_exchange_leverage_max"],
        confirmed["absolute_exchange_leverage_max"],
    ) == (10, 20, 25)
    assert micro["simulated_proposal"]["approval_status"] == "RESEARCH_ONLY_NOT_USER_APPROVED"


def test_read_only_api_and_unready(tmp_path: Path, info_result: ReadResult) -> None:
    shutil.copytree(ROOT / "config", tmp_path / "config")
    (tmp_path / "reports").mkdir()
    client = TestClient(create_app(tmp_path))
    assert client.get("/health/live").status_code == 200
    assert client.get("/api/v1/instruments").status_code == 503
    cap = resolve_candidate("NVDAUSDT", "stock_linked", info_result)
    (tmp_path / "reports/instrument_capabilities.json").write_text(
        json.dumps(
            {
                "run_id": "fixture",
                "started_at": utc_now().isoformat(),
                "generated_at": utc_now().isoformat(),
                "live_trading_enabled": False,
                "product_families_probed": ["USD_M_FUTURES"],
                "documentation_urls": [],
                "raw_directory": "reports/raw/fixture",
                "instruments": [cap.model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )
    assert client.get("/api/v1/instruments").status_code == 200
    ready = client.get("/health/ready")
    assert ready.status_code == 503 and ready.json()["service_ready"] is True
    assert ready.json()["trading_ready"] is False and ready.json()["allow_new_risk"] is False
    for path in ["/api/v1/instruments", "/health/live"]:
        assert client.post(path, json={}).status_code == 405
    assert client.post("/api/v1/orders", json={}).status_code == 404
    (tmp_path / "reports/instrument_capabilities.json").write_text("{}", encoding="utf-8")
    assert client.get("/health/ready").json()["service_ready"] is False
