"""Current public USD-M directory; display aliases never grant account permissions."""

import fcntl
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from app.models import ProductFamily, utc_now
from app.public_client import PublicClient
from app.storage import atomic_json


class MarketInstrument(BaseModel):
    symbol: str
    base_asset: str
    quote_asset: str
    contract_type: str
    underlying_type: str = ""
    name_zh: str
    name_source: Literal["LOCAL_DISPLAY_ALIAS", "UNAVAILABLE"]
    account_permission: Literal["UNKNOWN"] = "UNKNOWN"


class MarketCatalog(BaseModel):
    instruments: list[MarketInstrument]
    observed_at: datetime
    raw_hash: str
    source: Literal["BINANCE_PUBLIC_EXCHANGE_INFO"] = "BINANCE_PUBLIC_EXCHANGE_INFO"
    cache_ttl_seconds: int = 300
    live_trading_enabled: Literal[False] = False


class CatalogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh: StrictBool = False


class NameUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    symbol: str = Field(pattern=r"^[A-Z0-9_\u3400-\u9fff]{1,64}$")
    name_zh: str = Field(min_length=1, max_length=80)
    expected_name: str = Field(min_length=1, max_length=80)

    @field_validator("name_zh")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = value.strip()
        if not re.search(r"[\u3400-\u9fff]", value) or any(ord(c) < 32 for c in value):
            raise ValueError("请填写包含中文的名称，不能包含换行或控制字符")
        if value == "中文名待补充":
            raise ValueError("请填写实际的中文展示名称")
        return value


class NameUpdateResult(BaseModel):
    catalog: MarketCatalog
    affected_symbols: list[str]
    saved_at: datetime
    storage: Literal["LOCAL_DISPLAY_ALIAS"] = "LOCAL_DISPLAY_ALIAS"


class NameConflict(ValueError):
    pass


def visible_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
        raise ValueError("公共合约目录响应不完整")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in payload["symbols"]:
        if not isinstance(row, dict):
            raise ValueError("公共合约规格格式错误")
        if row.get("status") != "TRADING":
            continue
        if any(
            not isinstance(row.get(key), str) or not row[key]
            for key in ("symbol", "baseAsset", "quoteAsset", "marginAsset", "contractType")
        ) or not re.fullmatch(r"[A-Z0-9_\u3400-\u9fff]{1,64}", row["symbol"]):
            raise ValueError("公共合约规格缺少必要字段或代码无效")
        if row["symbol"] in seen:
            raise ValueError("公共目录包含重复合约代码")
        seen.add(row["symbol"])
        result.append(row)
    if not result:
        raise ValueError("公共目录没有当前可见的 USD-M 合约")
    return sorted(result, key=lambda row: row["symbol"])


def display_name(row: dict[str, Any], aliases: dict[str, str]) -> str | None:
    # Asset codes can collide across token/equity products (e.g. F and C).
    qualified = f"{row.get('underlyingType', '')}:{row['baseAsset']}"
    return aliases.get("SYMBOL:" + row.get("symbol", ""),
                       aliases.get(qualified, aliases.get(row["baseAsset"])))


class CatalogService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = threading.Lock()
        self.cached: MarketCatalog | None = None
        self.expires_at = 0.0

    @staticmethod
    def with_names(catalog: MarketCatalog, aliases: dict[str, str]) -> MarketCatalog:
        updated = catalog.model_copy(deep=True)
        for item in updated.instruments:
            name = display_name({"symbol": item.symbol, "underlyingType": item.underlying_type,
                                 "baseAsset": item.base_asset}, aliases)
            item.name_zh = name or "中文名待补充"
            item.name_source = "LOCAL_DISPLAY_ALIAS" if name else "UNAVAILABLE"
        return updated

    def get(self, *, refresh: bool = False) -> MarketCatalog:
        with self.lock:
            if not refresh and self.cached is not None and time.monotonic() < self.expires_at:
                aliases = json.loads((self.root / "config/market_names.zh.json").read_text())
                return self.with_names(self.cached, aliases)
            audit = self.root / "reports/market/catalog_raw" / str(uuid4())
            with PublicClient(ProductFamily.USD_M_FUTURES, audit) as client:
                response = client.get("/fapi/v1/exchangeInfo")
            if not response.ok or not response.evidence.raw_hash:
                raise ValueError("公共合约目录暂不可用：" + response.evidence.result)
            rows = visible_rows(response.data)
            aliases = json.loads((self.root / "config/market_names.zh.json").read_text())
            catalog = MarketCatalog(
                observed_at=response.evidence.timestamp,
                raw_hash=response.evidence.raw_hash,
                instruments=[
                    MarketInstrument(
                        symbol=row["symbol"],
                        base_asset=row["baseAsset"],
                        quote_asset=row["quoteAsset"],
                        contract_type=row["contractType"],
                        underlying_type=str(row.get("underlyingType", "")),
                        name_zh=display_name(row, aliases) or "中文名待补充",
                        name_source=(
                            "LOCAL_DISPLAY_ALIAS" if display_name(row, aliases) else "UNAVAILABLE"
                        ),
                    )
                    for row in rows
                ],
            )
            atomic_json(self.root / "reports/market/catalog.json", catalog.model_dump(mode="json"))
            self.cached = catalog
            self.expires_at = time.monotonic() + catalog.cache_ttl_seconds
            return catalog.model_copy(deep=True)

    def save_name(self, params: NameUpdateRequest) -> NameUpdateResult:
        """Local edit using observed directory; never makes an exchange/account request."""
        with self.lock:
            catalog = self.cached or MarketCatalog.model_validate_json(
                (self.root / "reports/market/catalog.json").read_text()
            )
            target = next((i for i in catalog.instruments if i.symbol == params.symbol), None)
            if target is None:
                raise ValueError("合约不在已观测目录中，请刷新合约目录后重试")
            key = (
                f"{target.underlying_type}:{target.base_asset}" if target.underlying_type
                else "SYMBOL:" + target.symbol
            )
            affected = [
                i.symbol for i in catalog.instruments
                if i.symbol == target.symbol or (
                    target.underlying_type and i.underlying_type == target.underlying_type
                    and i.base_asset == target.base_asset
                )
            ]
            path = self.root / "config/market_names.zh.json"
            with path.with_suffix(".lock").open("a") as lease:
                fcntl.flock(lease, fcntl.LOCK_EX)
                aliases: dict[str, str] = json.loads(path.read_text())
                row = {"symbol": target.symbol, "underlyingType": target.underlying_type,
                       "baseAsset": target.base_asset}
                current = display_name(row, aliases) or "中文名待补充"
                if current != params.expected_name:
                    raise NameConflict("名称已被其他窗口修改，请刷新目录后重新编辑")
                aliases[key] = params.name_zh
                if target.underlying_type:
                    for symbol in affected:
                        aliases.pop("SYMBOL:" + symbol, None)
                saved_at = utc_now()
                audit_path = self.root / "reports/market/name_updates.jsonl"
                audit_path.parent.mkdir(parents=True, exist_ok=True)
                with audit_path.open("a") as audit:
                    atomic_json(path, aliases)
                    audit.write(json.dumps({
                        "event": "LOCAL_DISPLAY_NAME_SAVED", "saved_at": saved_at.isoformat(),
                        "key": key, "symbol": target.symbol, "before": current,
                        "after": params.name_zh, "affected_symbols": affected,
                        "directory_hash": catalog.raw_hash,
                        "account_permission": "UNKNOWN", "live_trading_enabled": False,
                    }, ensure_ascii=False) + "\n")
            updated = self.with_names(catalog, aliases)
            self.cached = updated
            atomic_json(self.root / "reports/market/catalog.json", updated.model_dump(mode="json"))
            return NameUpdateResult(
                catalog=updated.model_copy(deep=True), affected_symbols=affected, saved_at=saved_at
            )
