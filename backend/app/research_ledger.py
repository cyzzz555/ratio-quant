"""Explicit PostgreSQL ingestion of file-staged research artifacts; no SQLite fallback."""

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest import runs
from app.bars import payload_hash
from app.models import utc_now
from app.research_data import load_dataset, manifests
from app.research_db import (
    AuditRecord,
    DatasetRecord,
    InstrumentRecord,
    ResearchRunRecord,
    RiskLockRecord,
    SpecRecord,
    StrategyVersionRecord,
    UnderlyingRecord,
    engine,
)
from app.research_records import deleted_reports
from app.storage import atomic_json


def synchronize(root: Path) -> dict[str, Any]:
    datasets = manifests(root, None)
    with Session(engine(root)) as session, session.begin():
        for manifest in datasets:
            _, _, _, spec = load_dataset(root, manifest["id"])
            symbol = manifest["symbol"]
            underlying = "candidate:" + symbol
            instrument = "BINANCE:USD_M_FUTURES:" + symbol
            session.merge(
                UnderlyingRecord(id=underlying, metadata_json={"mapping_state": "UNVERIFIED"})
            )
            session.flush()
            session.merge(
                InstrumentRecord(
                    id=instrument, underlying_id=underlying, metadata_json=spec["spec"]
                )
            )
            session.flush()
            # Shared exchangeInfo hash includes several instruments: disambiguate version PK.
            version = symbol + ":" + manifest["spec_version"]
            session.merge(
                SpecRecord(
                    version=version,
                    instrument_id=instrument,
                    observed_at=datetime.fromisoformat(spec["observed_at"]),
                    metadata_json=spec,
                )
            )
            session.merge(
                DatasetRecord(
                    id=manifest["id"],
                    instrument_id=instrument,
                    data_sha=manifest["data_hash"],
                    created_at=datetime.fromisoformat(manifest["created_at"]),
                    manifest={**manifest, "metadata_ledger": "POSTGRESQL"},
                )
            )
        session.flush()
        for result in [*runs(root, None), *deleted_reports(root)]:
            version = result["code_hash"] + ":" + result["parameter_hash"]
            session.merge(
                StrategyVersionRecord(
                    id=version,
                    code_sha=result["code_hash"],
                    parameter_sha=result["parameter_hash"],
                    release_state="RESEARCH_ONLY",
                )
            )
            session.flush()
            session.merge(
                ResearchRunRecord(
                    id=result["run_id"],
                    dataset_id=result["dataset_id"],
                    strategy_version=version,
                    created_at=datetime.fromisoformat(result["created_at"]),
                    result={"record_state": "ACTIVE", **result, "metadata_ledger": "POSTGRESQL"},
                )
            )
        session.add(
            AuditRecord(
                id=str(uuid4()),
                action="RESEARCH_ARTIFACTS_INGESTED",
                payload_sha=payload_hash([d["data_hash"] for d in datasets]),
                created_at=utc_now(),
            )
        )
    for manifest in datasets:
        manifest["metadata_ledger"] = "POSTGRESQL"
        atomic_json(root / "data/research" / manifest["id"] / "manifest.json", manifest)
    for result in runs(root, None):
        result["metadata_ledger"] = "POSTGRESQL"
        atomic_json(root / "reports/research" / (result["run_id"] + ".json"), result)
    return {"datasets": len(datasets), "metadata_ledger": "POSTGRESQL"}


def persist_lock(root: Path, scope: str, reason: str) -> None:
    with Session(engine(root)) as session, session.begin():
        session.merge(
            RiskLockRecord(
                id=scope + ":" + reason, scope=scope, reason=reason, created_at=utc_now()
            )
        )


def is_locked(root: Path, scope: str) -> bool:
    with Session(engine(root)) as session:
        return (
            session.scalars(select(RiskLockRecord).where(RiskLockRecord.scope == scope)).first()
            is not None
        )
