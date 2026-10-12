"""Explicit PostgreSQL paper state, immutable event and transactional outbox backend."""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.bars import payload_hash
from app.models import utc_now
from app.paper_engine import PaperError
from app.paper_models import PaperState
from app.paper_store import FilePaperStore, PaperConflict, PaperStoreError, record, restore
from app.research_db import Base, engine


class PaperSessionRecord(Base):
    __tablename__ = "paper_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB)
    cash: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperEventRecord(Base):
    __tablename__ = "paper_events"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence"),
        UniqueConstraint("session_id", "command_id"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("paper_sessions.id"))
    sequence: Mapped[int] = mapped_column(Integer)
    command_id: Mapped[str] = mapped_column(String)
    record: Mapped[dict[str, Any]] = mapped_column(JSONB)


class PaperOrderRecord(Base):
    __tablename__ = "paper_orders"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("paper_sessions.id"))
    client_order_id: Mapped[str] = mapped_column(String, unique=True)
    plan_hash: Mapped[str] = mapped_column(String)
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String)


class PaperOutboxRecord(Base):
    __tablename__ = "paper_outbox"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("paper_sessions.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivery: Mapped[str] = mapped_column(String, default="IN_APP_ONLY_PENDING")


class PostgresPaperStore(FilePaperStore):
    persistence = "POSTGRESQL_PAPER_TRANSACTIONAL_OUTBOX"

    def __init__(
        self, root: Path, clock: Callable[[], datetime] = utc_now, runtime_id: str | None = None
    ) -> None:
        self.root, self.clock, self.runtime = root, clock, runtime_id or str(uuid4())
        # Selecting this mode never falls back to a file or SQLite if PG is unavailable.
        self.db = engine(root)

    @staticmethod
    def _restore(
        session: Session, identifier: str
    ) -> tuple[PaperState | None, dict[str, dict[str, Any]], str]:
        items = [
            r.record
            for r in session.scalars(
                select(PaperEventRecord)
                .where(PaperEventRecord.session_id == identifier)
                .order_by(PaperEventRecord.sequence)
            )
        ]
        state, seen, previous = restore(items)
        cached = session.get(PaperSessionRecord, identifier)
        if cached is not None and (
            state is None
            or cached.revision != len(items)
            or payload_hash(cached.state) != payload_hash(state.model_dump(mode="json"))
        ):
            raise PaperStoreError("POSTGRES_PAPER_CACHE_MISMATCH")
        return state, seen, previous

    def _commit(self, identifier: str, body: dict[str, Any], kind: str) -> dict[str, Any]:
        with Session(self.db) as session, session.begin():
            number = int(payload_hash(identifier)[:16], 16)
            if number >= 2**63:
                number -= 2**64
            session.execute(select(func.pg_advisory_xact_lock(number)))
            cached = session.scalars(
                select(PaperSessionRecord)
                .where(PaperSessionRecord.id == identifier)
                .with_for_update()
            ).first()
            state, seen, previous = self._restore(session, identifier)
            if body["command_id"] in seen:
                old = seen[body["command_id"]]
                if old["body_hash"] != payload_hash(body):
                    raise PaperConflict("IDEMPOTENCY_KEY_CONFLICT")
                assert state is not None
                return self.snapshot(state, old["result"], duplicate=True)
            updated, item = record(
                state, body, kind, self.clock(), self.runtime, len(seen), previous
            )
            if cached is None:
                cached = PaperSessionRecord(
                    id=identifier,
                    revision=1,
                    state=updated.model_dump(mode="json"),
                    cash=updated.cash,
                    updated_at=updated.updated_at,
                )
                session.add(cached)
            else:
                cached.revision += 1
                cached.state = updated.model_dump(mode="json")
                cached.cash, cached.updated_at = updated.cash, updated.updated_at
            session.flush()
            session.add(
                PaperEventRecord(
                    id=identifier + ":" + body["command_id"],
                    session_id=identifier,
                    sequence=len(seen),
                    command_id=body["command_id"],
                    record=item,
                )
            )
            for order in updated.orders.values():
                key = identifier + ":" + order.id
                existing = session.get(PaperOrderRecord, key)
                if existing and existing.plan_hash != order.plan_hash:
                    raise PaperStoreError("IMMUTABLE_POSTGRES_PLAN_CONFLICT")
                if existing:
                    existing.state = order.state
                else:
                    session.add(
                        PaperOrderRecord(
                            id=key,
                            session_id=identifier,
                            client_order_id=order.client_order_id,
                            plan_hash=order.plan_hash,
                            plan=order.plan.model_dump(mode="json"),
                            state=order.state,
                        )
                    )
            session.add(
                PaperOutboxRecord(
                    id=item["hash"],
                    session_id=identifier,
                    payload={"action": kind, "result": item["result"], "hash": item["hash"]},
                    created_at=updated.updated_at,
                )
            )
        return self.snapshot(updated, item["result"])

    def read(self, identifier: str) -> tuple[PaperState, list[dict[str, Any]]]:
        with Session(self.db) as session, session.begin():
            cached = session.scalars(
                select(PaperSessionRecord)
                .where(PaperSessionRecord.id == identifier)
                .with_for_update()
            ).first()
            if cached is None:
                raise PaperError("SESSION_NOT_FOUND")
            state, _, _ = self._restore(session, identifier)
            assert state is not None
            return state, []

    def list_sessions(self) -> list[dict[str, Any]]:
        with Session(self.db) as session:
            return [
                dict(id=s.id, name=s.state["config"]["name"], created_at=s.state["created_at"])
                for s in session.scalars(
                    select(PaperSessionRecord).order_by(PaperSessionRecord.updated_at.desc())
                )
            ]
