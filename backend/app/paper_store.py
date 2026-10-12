"""Atomic offline simulation journal; PostgreSQL backend is an explicit separate mode."""

import fcntl
import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.bars import payload_hash
from app.models import utc_now
from app.paper_engine import PaperEngine, PaperError, create_state
from app.paper_models import CreatePaper, PaperCommand, PaperState


class PaperStoreError(RuntimeError):
    pass


class PaperConflict(PaperError):
    pass


def record(
    state: PaperState | None,
    body: dict[str, Any],
    kind: str,
    at: datetime,
    runtime: str,
    sequence: int,
    previous: str,
    engine_version: str = "paper.engine.v3",
) -> tuple[PaperState, dict[str, Any]]:
    if kind == "CREATE":
        config = CreatePaper.model_validate(body)
        if state is not None:
            raise PaperConflict("SESSION_ALREADY_EXISTS")
        updated = create_state(config, runtime, at)
        result = {"created": True}
    else:
        if state is None:
            raise PaperError("SESSION_NOT_FOUND")
        updated = state.model_copy(deep=True)
        if engine_version not in {"paper.engine.v1", "paper.engine.v2", "paper.engine.v3"}:
            raise PaperStoreError("PAPER_ENGINE_VERSION_UNSUPPORTED")
        result = PaperEngine(
            updated, legacy_submit_trace=engine_version == "paper.engine.v1"
        ).execute(PaperCommand.model_validate(body), at, runtime)
    content = dict(
        schema_version="paper.journal.v1",
        sequence=sequence,
        previous=previous,
        kind=kind,
        command_id=body["command_id"],
        body=body,
        body_hash=payload_hash(body),
        at=at.isoformat(),
        runtime=runtime,
        state_hash=payload_hash(updated.model_dump(mode="json")),
        result=result,
    )
    if engine_version != "paper.engine.v1":
        content["engine_version"] = engine_version
    return updated, {**content, "hash": payload_hash(content)}


def restore(
    records: list[dict[str, Any]],
) -> tuple[PaperState | None, dict[str, dict[str, Any]], str]:
    state: PaperState | None = None
    seen: dict[str, dict[str, Any]] = {}
    previous = "0" * 64
    for seq, item in enumerate(records):
        required = {
            "hash",
            "schema_version",
            "sequence",
            "previous",
            "body",
            "body_hash",
            "command_id",
            "at",
            "runtime",
            "kind",
            "state_hash",
            "result",
        }
        if (
            not isinstance(item, dict)
            or not required <= item.keys()
            or not isinstance(item["body"], dict)
        ):
            raise PaperStoreError("PAPER_JOURNAL_CORRUPTED")
        digest = item["hash"]
        content = {k: v for k, v in item.items() if k != "hash"}
        if (
            item["schema_version"] != "paper.journal.v1"
            or item["sequence"] != seq
            or item["previous"] != previous
            or payload_hash(content) != digest
            or payload_hash(item["body"]) != item["body_hash"]
            or item["command_id"] in seen
        ):
            raise PaperStoreError("PAPER_JOURNAL_CORRUPTED")
        try:
            state, expected = record(
                state,
                item["body"],
                item["kind"],
                datetime.fromisoformat(item["at"]),
                item["runtime"],
                seq,
                previous,
                item.get("engine_version", "paper.engine.v1"),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise PaperStoreError("PAPER_REPLAY_REJECTED") from exc
        if expected != item:
            raise PaperStoreError("PAPER_STATE_REPLAY_MISMATCH")
        seen[item["command_id"]] = item
        previous = digest
    if state is not None:
        PaperEngine(state).invariants()
    return state, seen, previous


class FilePaperStore:
    persistence = "OFFLINE_FILE_JOURNAL_NOT_POSTGRESQL"

    def __init__(
        self, root: Path, clock: Callable[[], datetime] = utc_now, runtime_id: str | None = None
    ) -> None:
        self.directory = root / ".runtime/paper"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.runtime = runtime_id or str(uuid4())
        self.clock = clock

    def _paths(self, identifier: str) -> tuple[Path, Path]:
        # Validate before any path interpolation, including reads.
        import re

        from app.paper_models import UUID_PATTERN

        if not re.fullmatch(UUID_PATTERN, identifier):
            raise PaperError("INVALID_SESSION_ID")
        return self.directory / (identifier + ".jsonl"), self.directory / (identifier + ".lock")

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        if path.stat().st_size == 0:
            raise PaperStoreError("PAPER_JOURNAL_EMPTY_NO_RESET")
        if path.stat().st_size > 32 * 1024 * 1024:
            raise PaperStoreError("PAPER_JOURNAL_SIZE_LIMIT")
        try:
            return [json.loads(line) for line in path.read_text().splitlines()]
        except (OSError, ValueError) as exc:
            raise PaperStoreError("PAPER_JOURNAL_UNREADABLE") from exc

    def read(self, identifier: str) -> tuple[PaperState, list[dict[str, Any]]]:
        path, lock = self._paths(identifier)
        with lock.open("a") as lease:
            fcntl.flock(lease, fcntl.LOCK_SH)
            items = self._read(path)
            state, _, _ = restore(items)
        if state is None:
            raise PaperError("SESSION_NOT_FOUND")
        return state, items

    def list_sessions(self) -> list[dict[str, Any]]:
        results = []
        for path in sorted(
            self.directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            state, _ = self.read(path.stem)
            results.append(
                dict(id=state.id, name=state.config.name, created_at=state.created_at.isoformat())
            )
        return results

    def _commit(self, identifier: str, body: dict[str, Any], kind: str) -> dict[str, Any]:
        path, lock = self._paths(identifier)
        with lock.open("a") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            items = self._read(path)
            state, seen, previous = restore(items)
            if body["command_id"] in seen:
                original = seen[body["command_id"]]
                if original["body_hash"] != payload_hash(body):
                    raise PaperConflict("IDEMPOTENCY_KEY_CONFLICT")
                assert state is not None
                return self.snapshot(state, original["result"], duplicate=True)
            updated, item = record(
                state, body, kind, self.clock(), self.runtime, len(items), previous
            )
            data = (json.dumps(item, ensure_ascii=False) + "\n").encode()
            if sum(len(json.dumps(x).encode()) + 1 for x in items) + len(data) > 32 * 1024 * 1024:
                raise PaperStoreError("PAPER_JOURNAL_SIZE_LIMIT")
            # One append + fsync under the process-wide lock. A truncated write blocks later replay.
            descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                with os.fdopen(descriptor, "ab") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError as exc:
                raise PaperStoreError("PAPER_JOURNAL_WRITE_FAILED") from exc
            return self.snapshot(updated, item["result"])

    def create(self, config: CreatePaper) -> dict[str, Any]:
        return self._commit(config.command_id, config.model_dump(mode="json"), "CREATE")

    def execute(self, command: PaperCommand) -> dict[str, Any]:
        return self._commit(command.session_id, command.model_dump(mode="json"), "COMMAND")

    def snapshot(
        self, state: PaperState, result: dict[str, Any] | None = None, duplicate: bool = False
    ) -> dict[str, Any]:
        return {
            **PaperEngine(state).snapshot(self.clock(), self.runtime),
            "persistence": self.persistence,
            "result": result,
            "duplicate_command": duplicate,
        }

    def status(self, identifier: str) -> dict[str, Any]:
        state, _ = self.read(identifier)
        return self.snapshot(state)
