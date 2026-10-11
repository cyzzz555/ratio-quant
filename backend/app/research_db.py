"""PostgreSQL metadata ledger for datasets, research versions, events and risk locks."""

import json
import os
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Numeric, String, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.models import utc_now
from app.settings import ROOT


class Base(DeclarativeBase):
    pass


class UnderlyingRecord(Base):
    __tablename__ = "underlyings"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB)


class InstrumentRecord(Base):
    __tablename__ = "instruments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    underlying_id: Mapped[str] = mapped_column(ForeignKey("underlyings.id"))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB)


class SpecRecord(Base):
    __tablename__ = "instrument_spec_versions"
    version: Mapped[str] = mapped_column(String, primary_key=True)
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB)


class DatasetRecord(Base):
    __tablename__ = "research_datasets"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"))
    data_sha: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)


class EventRecord(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB)


class StrategyVersionRecord(Base):
    __tablename__ = "strategy_versions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    code_sha: Mapped[str] = mapped_column(String)
    parameter_sha: Mapped[str] = mapped_column(String)
    release_state: Mapped[str] = mapped_column(String, default="RESEARCH_ONLY")


class ResearchRunRecord(Base):
    __tablename__ = "research_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("research_datasets.id"))
    strategy_version: Mapped[str] = mapped_column(ForeignKey("strategy_versions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ResearchJobRecord(Base):
    __tablename__ = "research_jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)


class RiskLockRecord(Base):
    __tablename__ = "risk_locks"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    scope: Mapped[str] = mapped_column(String, index=True)
    reason: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RiskSnapshotRecord(Base):
    __tablename__ = "risk_snapshots"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    scope: Mapped[str] = mapped_column(String)
    equity: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditRecord(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    action: Mapped[str] = mapped_column(String)
    payload_sha: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def database_url(root: Path = ROOT) -> str:
    value = os.environ.get("DATABASE_URL")
    if value is None:
        try:
            value = json.loads((root / "config/local_runtime.json").read_text())["database_url"]
        except (OSError, ValueError, KeyError) as exc:
            raise RuntimeError("PostgreSQL 尚未配置；请启动本地研究数据库") from exc
    if not value.startswith("postgresql+psycopg://"):
        raise ValueError("P1 research metadata requires PostgreSQL, no silent SQLite fallback")
    return value


@lru_cache(maxsize=4)
def _engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})


def engine(root: Path = ROOT) -> Engine:
    return _engine(database_url(root))


def list_datasets(root: Path = ROOT) -> list[dict[str, Any]]:
    with Session(engine(root)) as session:
        return [
            r.manifest
            for r in session.scalars(
                select(DatasetRecord).order_by(DatasetRecord.created_at.desc()).limit(30)
            )
        ]


def list_runs(root: Path = ROOT) -> list[dict[str, Any]]:
    with Session(engine(root)) as session:
        return [
            r.result
            for r in session.scalars(
                select(ResearchRunRecord)
                .where(ResearchRunRecord.result["record_state"].astext.is_distinct_from("DELETED"))
                .order_by(ResearchRunRecord.created_at.desc()).limit(30)
            )
        ]


def health(root: Path = ROOT) -> dict[str, Any]:
    try:
        from sqlalchemy import text

        with engine(root).connect() as connection:
            version = connection.execute(text("select version()")).scalar_one()
            revision = connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
        return {"ready": True, "version": version, "migration": revision, "checked_at": utc_now()}
    except Exception as exc:
        return {"ready": False, "error": type(exc).__name__, "checked_at": utc_now()}
