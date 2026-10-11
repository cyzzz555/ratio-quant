"""Safety values cannot unlock live code in Phase 0."""

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_settings(root: Path = ROOT) -> dict[str, Any]:
    values: dict[str, Any] = yaml.safe_load(
        (root / "config/settings.example.yaml").read_text(encoding="utf-8")
    )
    safety, platform = values["safety"], values["platform"]
    if (
        os.environ.get("LIVE_TRADING_ENABLED", "false").lower() != "false"
        or os.environ.get("APPROVAL_MODE", "HUMAN") != "HUMAN"
        or os.environ.get("TRADE_ADAPTER", "PAPER_BROKER") != "PAPER_BROKER"
        or safety["live_trading_enabled"] is not False
        or safety["approval_mode"] != "HUMAN"
        or platform["trade_adapter"] != "PAPER_BROKER"
    ):
        raise ValueError("P0 requires LIVE_TRADING_ENABLED=false, HUMAN, PAPER_BROKER")
    return values
