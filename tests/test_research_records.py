import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app import backtest, file_lock, research_records
from app.bars import payload_hash
from app.research_api import router
from app.storage import atomic_json
from fastapi import FastAPI
from fastapi.testclient import TestClient


def report_fixture(root: Path) -> dict[str, Any]:
    report = {
        "run_id": str(uuid4()),
        "symbol": "MUUSDT",
        "dataset_id": str(uuid4()),
        "created_at": "2026-09-01T00:00:00+00:00",
        "parameter_hash": "a" * 64,
        "data_hash": "b" * 64,
        "code_hash": "c" * 64,
        "splits": {},
        "stress": {},
    }
    keys = ["parameter_hash", "data_hash", "code_hash", "splits", "stress"]
    report["result_hash"] = payload_hash({k: report[k] for k in keys})
    atomic_json(root / "reports/research" / (report["run_id"] + ".json"), report)
    atomic_json(root / "data/research" / report["dataset_id"] / "manifest.json", {"keep": True})
    return report


def test_soft_delete_restore_bytes_dataset_and_audit(tmp_path: Path) -> None:
    report = report_fixture(tmp_path)
    identifier = report["run_id"]
    path = tmp_path / "reports/research" / (identifier + ".json")
    before = path.read_bytes()
    dataset = tmp_path / "data/research" / report["dataset_id"] / "manifest.json"
    dataset_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    removed = research_records.change(tmp_path, identifier, "delete", report["result_hash"])
    assert removed["dataset_retained"] is True and not path.exists()
    assert backtest.runs(tmp_path, None) == []
    assert research_records.trash(tmp_path)[0]["run_id"] == identifier
    assert research_records.deleted_reports(tmp_path)[0]["record_state"] == "DELETED"
    research_records.change(tmp_path, identifier, "restore", report["result_hash"])
    assert path.read_bytes() == before and research_records.trash(tmp_path) == []
    assert hashlib.sha256(dataset.read_bytes()).hexdigest() == dataset_hash
    audit = [
        json.loads(row)
        for row in (tmp_path / "reports/research_record_actions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [a["action"] for a in audit] == ["DELETE", "DELETE", "RESTORE", "RESTORE"]
    assert all(a["file_hash"] == hashlib.sha256(before).hexdigest() for a in audit)


def test_conflict_lock_missing_and_corruption_fail_closed(tmp_path: Path) -> None:
    report = report_fixture(tmp_path)
    identifier = report["run_id"]
    with pytest.raises(research_records.RecordConflict, match="已变化"):
        research_records.change(tmp_path, identifier, "delete", "0" * 64)
    with (tmp_path / "reports/research_worker.lock").open("a", encoding="utf-8") as lease:
        file_lock.flock(lease, file_lock.LOCK_EX | file_lock.LOCK_NB)
        with pytest.raises(research_records.RecordConflict, match="正在运行"):
            research_records.change(tmp_path, identifier, "delete", report["result_hash"])
    with pytest.raises(FileNotFoundError):
        research_records.change(tmp_path, str(uuid4()), "delete", report["result_hash"])
    research_records.change(tmp_path, identifier, "delete", report["result_hash"])
    with pytest.raises(research_records.RecordConflict):
        research_records.change(tmp_path, identifier, "delete", report["result_hash"])
    archived = tmp_path / "reports/research/trash" / (identifier + ".json")
    archived.write_bytes(archived.read_bytes() + b" ")
    with pytest.raises(ValueError, match="哈希"):
        research_records.change(tmp_path, identifier, "restore", report["result_hash"])
    assert archived.exists() and not (tmp_path / "reports/research" / archived.name).exists()


def test_result_hash_corruption_prevents_removal(tmp_path: Path) -> None:
    report = report_fixture(tmp_path)
    path = tmp_path / "reports/research" / (report["run_id"] + ".json")
    atomic_json(path, {**report, "splits": {"tampered": True}})
    with pytest.raises(ValueError, match="完整性"):
        research_records.change(tmp_path, report["run_id"], "delete", report["result_hash"])
    assert path.exists() and research_records.trash(tmp_path) == []


def test_record_routes_guards_download_hidden_and_restore(tmp_path: Path) -> None:
    report = report_fixture(tmp_path)
    app = FastAPI()
    app.include_router(router(tmp_path))
    client = TestClient(app, client=("127.0.0.1", 50000), base_url="http://127.0.0.1:8000")
    identifier = report["run_id"]
    url = f"/api/v1/research/runs/{identifier}/delete"
    body = {"expected_result_hash": report["result_hash"]}
    headers = {"Origin": "http://127.0.0.1:5173"}
    assert client.post(url, json=body).status_code == 403
    assert client.post(url, json={**body, "force": True}, headers=headers).status_code == 422
    assert (
        client.post(url.replace(identifier, "not-a-uuid"), json=body, headers=headers).status_code
        == 422
    )
    assert client.post(url, json=body, headers=headers).status_code == 200
    assert client.get(f"/api/v1/research/results/{identifier}").status_code == 404
    assert client.get("/api/v1/research/runs").json() == []
    assert client.get("/api/v1/research/trash").json()[0]["run_id"] == identifier
    assert (
        client.post(url.replace("/delete", "/restore"), json=body, headers=headers).status_code
        == 200
    )
    assert client.get(f"/api/v1/research/results/{identifier}").status_code == 200


def test_database_sync_failure_does_not_report_local_operation_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import research_db, research_ledger

    report = report_fixture(tmp_path)
    monkeypatch.setattr(research_db, "health", lambda root: {"ready": True})

    def failed(root: Path) -> None:
        raise OSError("offline database fixture")

    monkeypatch.setattr(research_ledger, "synchronize", failed)
    result = research_records.change(tmp_path, report["run_id"], "delete", report["result_hash"])
    assert result["state"] == "COMPLETED" and "同步待重试" in result["warning"]
    assert result["metadata_ledger"] == "FILE_STAGING_PENDING_POSTGRESQL"
