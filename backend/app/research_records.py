"""Reversible research report removal; immutable datasets and report bytes are retained."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app import file_lock
from app.bars import payload_hash
from app.models import utc_now
from app.storage import atomic_json


class RecordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RecordConflict(ValueError):
    pass


def valid_id(identifier: str) -> None:
    if str(UUID(identifier)) != identifier:
        raise ValueError("无效回测记录 ID")


def read_report(path: Path, identifier: str) -> dict[str, Any]:
    report: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    keys = ["parameter_hash", "data_hash", "code_hash", "splits", "stress"]
    if (
        not isinstance(report, dict)
        or report.get("run_id") != identifier
        or not all(key in report for key in keys)
        or payload_hash({key: report[key] for key in keys}) != report.get("result_hash")
    ):
        raise ValueError("回测报告完整性校验失败，禁止操作")
    return report


def deleted_reports(root: Path) -> list[dict[str, Any]]:
    folder = root / "reports/research/trash"
    records = []
    for path in folder.glob("*.json"):
        valid_id(path.stem)
        report = read_report(path, path.stem)
        meta = json.loads((folder / "metadata" / path.name).read_text(encoding="utf-8"))
        if hashlib.sha256(path.read_bytes()).hexdigest() != meta["file_hash"]:
            raise ValueError("回收站报告哈希校验失败，禁止恢复")
        records.append({**report, "record_state": "DELETED", "deleted_at": meta["deleted_at"]})
    return sorted(records, key=lambda item: item["deleted_at"], reverse=True)


def trash(root: Path) -> list[dict[str, Any]]:
    keys = ["run_id", "symbol", "created_at", "deleted_at", "result_hash", "dataset_id"]
    return [{key: item[key] for key in keys} for item in deleted_reports(root)]


def change(
    root: Path, identifier: str, action: Literal["delete", "restore"], expected_hash: str
) -> dict[str, Any]:
    valid_id(identifier)
    reports = root / "reports/research"
    reports.mkdir(parents=True, exist_ok=True)
    with (root / "reports/research_worker.lock").open("a", encoding="utf-8") as lease:
        try:
            file_lock.flock(lease, file_lock.LOCK_EX | file_lock.LOCK_NB)
        except BlockingIOError as exc:
            raise RecordConflict("研究任务或记录操作正在运行，请完成后重试") from exc
        active = reports / (identifier + ".json")
        archived = reports / "trash" / active.name
        source, destination = (active, archived) if action == "delete" else (archived, active)
        if destination.exists():
            raise RecordConflict("目标记录已存在，请刷新记录；不会覆盖报告")
        report = read_report(source, identifier)
        if report["result_hash"] != expected_hash:
            raise RecordConflict("回测记录已变化，请刷新后重新确认")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        meta_path = reports / "trash/metadata" / active.name
        at = utc_now().isoformat()
        if action == "delete":
            atomic_json(meta_path, {"deleted_at": at, "file_hash": digest})
        elif digest != json.loads(meta_path.read_text(encoding="utf-8"))["file_hash"]:
            raise ValueError("回收站报告哈希校验失败，禁止恢复")
        event = {
            "at": at,
            "action": action.upper(),
            "run_id": identifier,
            "dataset_id": report["dataset_id"],
            "result_hash": expected_hash,
            "file_hash": digest,
            "live_trading_enabled": False,
        }
        # The atomic rename is the source of truth after an interrupted operation.
        # A pre-operation audit survives interruption before the completion entry.
        audit_path = root / "reports/research_record_actions.jsonl"
        with audit_path.open("a", encoding="utf-8") as audit:
            audit.write(json.dumps({**event, "state": "REQUESTED"}) + "\n")
            audit.flush()
            os.fsync(audit.fileno())
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
            audit.write(json.dumps({**event, "state": "COMPLETED"}) + "\n")
        result: dict[str, Any] = {
            **event,
            "state": "COMPLETED",
            "dataset_retained": True,
            "metadata_ledger": "FILE_STAGING_PENDING_POSTGRESQL",
        }
        from app import research_db

        if research_db.health(root)["ready"]:
            try:
                from app.research_ledger import synchronize

                synchronize(root)
                result["metadata_ledger"] = "POSTGRESQL"
            except Exception:
                import logging

                logging.exception("Research record ledger synchronization failed")
                result["warning"] = "记录操作已完成；PostgreSQL 同步待重试"
        return result
