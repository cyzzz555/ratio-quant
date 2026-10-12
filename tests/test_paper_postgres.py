"""Real PG integration only on explicit isolated test schema; never SQLite."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from app.paper_db import PaperEventRecord, PaperOutboxRecord, PostgresPaperStore
from app.paper_models import CreatePaper, PaperCommand
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_research_postgres import database as isolated_postgres_fixture

database = isolated_postgres_fixture

pytestmark = pytest.mark.postgres


def test_pg_atomic_state_events_outbox_and_idempotency(database: Path) -> None:
    at = datetime(2026, 10, 12, tzinfo=UTC)
    store = PostgresPaperStore(database, clock=lambda: at, runtime_id="fixture")
    config = CreatePaper(command_id=str(uuid4()), name="PG fixture")
    store.create(config)
    cmd = PaperCommand(
        session_id=config.command_id, command_id=str(uuid4()), action="FLOW", args={"amount": "100"}
    )
    store.execute(cmd)
    store.execute(cmd)
    snap = store.status(config.command_id)
    assert Decimal(snap["metrics"]["cash"]) == 1100
    with Session(store.db) as session:
        assert session.scalar(select(func.count()).select_from(PaperEventRecord)) == 2
        assert session.scalar(select(func.count()).select_from(PaperOutboxRecord)) == 2
    reopened = PostgresPaperStore(database, clock=lambda: at, runtime_id="another-process")
    assert reopened.status(config.command_id)["recovery_required"]


def test_pg_sql_exception_rolls_back_without_fallback(
    database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.paper_store import PaperStoreError

    at = datetime(2026, 10, 12, tzinfo=UTC)
    store = PostgresPaperStore(database, clock=lambda: at, runtime_id="fixture")
    config = CreatePaper(command_id=str(uuid4()), name="PG transaction fixture")
    store.create(config)

    def failed(*args: object, **kwargs: object) -> None:
        raise PaperStoreError("forced rollback fixture")

    monkeypatch.setattr("app.paper_db.record", failed)
    with pytest.raises(PaperStoreError):
        store.execute(
            PaperCommand(
                session_id=config.command_id,
                command_id=str(uuid4()),
                action="FLOW",
                args={"amount": "100"},
            )
        )
    assert Decimal(store.status(config.command_id)["metrics"]["cash"]) == 1000
    assert store.persistence == "POSTGRESQL_PAPER_TRANSACTIONAL_OUTBOX"
