"""Public evidence does not grant account privileges."""

from typing import Any

from app.models import Capability, CapabilityState, Instrument, ProductFamily, Underlying
from app.public_client import ReadResult


def resolve_candidate(symbol: str, category: str, result: ReadResult) -> Capability:
    rows: Any = result.data.get("symbols") if result.ok and isinstance(result.data, dict) else None
    complete = (
        isinstance(rows, list)
        and bool(rows)
        and all(isinstance(x, dict) and isinstance(x.get("symbol"), str) for x in rows)
        and len({x["symbol"] for x in rows}) == len(rows)
    )
    row = next((x for x in rows if x["symbol"] == symbol), None) if complete else None
    valid = (
        row is not None
        and all(
            isinstance(row.get(k), str) and bool(row[k])
            for k in ["contractType", "status", "baseAsset", "quoteAsset", "marginAsset"]
        )
        and isinstance(row.get("filters"), list)
        and bool(row["filters"])
    )
    # A shared fapi route alone does not establish UM/CM margin family.
    valid = valid and row is not None and row["marginAsset"] in {"USDT", "USDC"}
    public_row: dict[str, Any] = row if valid and isinstance(row, dict) else {}
    if valid:
        state, visible, notes = (
            CapabilityState.VERIFIED_PUBLIC,
            True,
            [
                "Public specification only. "
                "Account/region/leverage/margin/order semantics unverified.",
                "Ignored requiredMarginPercent/maintMarginPercent: "
                "not leverage permission evidence.",
            ],
        )
    elif complete and row is None:
        state, visible, notes = (
            CapabilityState.UNKNOWN,
            False,
            [
                "Not observed in this USD_M_FUTURES response. "
                "Other families/listing status unverified."
            ],
        )
    else:
        state = CapabilityState.UNAVAILABLE if not result.ok else CapabilityState.UNKNOWN
        visible, notes = None, ["exchangeInfo unavailable/incomplete; no absence inference."]
    instrument_id = f"BINANCE:USD_M_FUTURES:{symbol}"
    underlying_id = f"candidate:{symbol}"
    underlying = Underlying(
        id=underlying_id,
        asset_class_candidate=category,
        exchange_reported_type=public_row.get("underlyingType"),
        exchange_reported_base_asset=public_row.get("baseAsset"),
    )
    instrument = Instrument(
        id=instrument_id,
        underlying_id=underlying_id,
        symbol=symbol,
        product_family_probed=ProductFamily.USD_M_FUTURES,
        product_family_verified=ProductFamily.USD_M_FUTURES if valid else None,
        contract_type=public_row.get("contractType"),
        quote_asset=public_row.get("quoteAsset"),
        margin_asset=public_row.get("marginAsset"),
    )
    return Capability(
        product_family="USD_M_FUTURES" if valid else "UNVERIFIED",
        symbol=symbol,
        capability_state=state,
        verified_at=result.evidence.timestamp,
        first_verified_at=result.evidence.timestamp if valid else None,
        public_exchangeinfo_visible=visible,
        trading_status=public_row.get("status"),
        instrument=instrument,
        underlying=underlying,
        evidence=[result.evidence],
        notes=notes,
    )
