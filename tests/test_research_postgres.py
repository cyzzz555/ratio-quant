"""Explicit integration tests, disposable schema only; run after local PG starts."""

import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.models import utc_now
from app.research_db import (
    DatasetRecord,
    InstrumentRecord,
    RiskSnapshotRecord,
    UnderlyingRecord,
    database_url,
    engine,
)
from app.research_ledger import is_locked, persist_lock
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.postgres


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    if os.environ.get("QUANT_TEST_POSTGRES") != "1":
        pytest.skip("Set QUANT_TEST_POSTGRES=1 only after starting local research PostgreSQL")
    from app.settings import ROOT

    url = database_url(ROOT)
    schema = "research_test_" + uuid4().hex
    base = engine(ROOT)
    with base.begin() as conn:
        conn.execute(text("CREATE SCHEMA " + schema))
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query))
    query["options"] = "-csearch_path=" + schema
    monkeypatch.setenv("DATABASE_URL", urlunsplit(parsed._replace(query=urlencode(query))))
    try:
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        command.upgrade(config, "head")
        yield ROOT
    finally:
        engine(ROOT).dispose()
        with base.begin() as conn:
            conn.execute(text("DROP SCHEMA " + schema + " CASCADE"))


def test_migrations_metadata_and_atomic_foreign_keys(database: Path) -> None:
    names = set(inspect(engine(database)).get_table_names())
    assert {"research_datasets", "risk_locks", "events", "research_runs", "audit_logs"} <= names
    with Session(engine(database)) as session, session.begin():
        session.add(UnderlyingRecord(id="fixture", metadata_json={"state": "UNVERIFIED"}))
        session.flush()
        session.add(
            InstrumentRecord(
                id="fixture:contract",
                underlying_id="fixture",
                metadata_json={"account_permission": "UNKNOWN"},
            )
        )
        session.flush()
        session.add(
            DatasetRecord(
                id="fixture:data",
                instrument_id="fixture:contract",
                data_sha="1" * 64,
                created_at=utc_now(),
                manifest={"status": "RESEARCH_ONLY"},
            )
        )
    with Session(engine(database)) as session:
        record = session.get(DatasetRecord, "fixture:data")
        assert record and record.manifest["status"] == "RESEARCH_ONLY"
    with engine(database).connect() as conn:
        assert (
            conn.execute(text("select version_num from alembic_version")).scalar_one()
            == "001_research"
        )


def test_persisted_lock_survives_new_connection_and_deposit(database: Path) -> None:
    scope = "OFFLINE_TEST_SCOPE"
    persist_lock(database, scope, "PRINCIPAL_LOCK")
    engine(database).dispose()
    assert is_locked(database, scope)
    with Session(engine(database)) as session, session.begin():
        session.add(
            RiskSnapshotRecord(
                id="deposit-fixture",
                scope=scope,
                equity=Decimal("2000"),
                snapshot={"net_flows": "1500", "day_changed": True},
                created_at=utc_now(),
            )
        )
    assert is_locked(database, scope)
