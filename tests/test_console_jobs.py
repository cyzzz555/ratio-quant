import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import IO, Any
from uuid import uuid4

import pytest
from app.main import create_app
from app.models import utc_now
from app.probe_jobs import ProbeBusy, ProbeCooldown, ProbeRunner, ProbeStatus, exclusive_probe
from app.settings import ROOT
from app.storage import atomic_json
from fastapi.testclient import TestClient


@pytest.fixture
def console_root(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "config", tmp_path / "config")
    (tmp_path / "reports").mkdir()
    return tmp_path


def wait_finished(runner: ProbeRunner) -> ProbeStatus:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        status = runner.status()
        if status.state != "RUNNING":
            return status
        time.sleep(0.01)
    pytest.fail("offline job failed to finish")


def test_jobs_serialized_across_runners_and_logs_visible(
    console_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release = threading.Event(), threading.Event()

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        kwargs["stdout"].write("NVDAUSDT: VERIFIED_PUBLIC; history=True; ws=None; closed=59\n")
        kwargs["stdout"].flush()
        entered.set()
        assert release.wait(2)
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr("app.probe_jobs.subprocess.run", fake_run)
    runner = ProbeRunner(console_root)
    runner.start()
    assert entered.wait(1)
    try:
        assert runner.status().state == "RUNNING"
        assert runner.status().completed_symbols == ["NVDAUSDT"]
        with pytest.raises(ProbeBusy):
            ProbeRunner(console_root).start()
    finally:
        release.set()
    status = wait_finished(runner)
    assert status.state == "SUCCEEDED" and status.exit_code == 0
    assert status.live_trading_enabled is False
    with pytest.raises(ProbeCooldown):
        runner.start()


@pytest.mark.parametrize("failure", ["nonzero", "timeout"])
def test_failed_probe_preserves_previous_report(
    failure: str,
    console_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = console_root / "reports/instrument_capabilities.json"
    report.write_text('{"previous": true}')

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args[0], 180)
        return subprocess.CompletedProcess(args[0], 7)

    monkeypatch.setattr("app.probe_jobs.subprocess.run", fake_run)
    runner = ProbeRunner(console_root)
    runner.start()
    status = wait_finished(runner)
    assert status.state == "FAILED"
    assert status.exit_code == (7 if failure == "nonzero" else None)
    assert report.read_text() == '{"previous": true}'
    if failure == "timeout":
        assert "PROBE_TIMEOUT" in status.log


def test_orphan_state_not_claimed_running(console_root: Path) -> None:
    runner = ProbeRunner(console_root)
    atomic_json(
        runner.status_path,
        ProbeStatus(
            state="RUNNING",
            started_at=utc_now(),
        ).model_dump(mode="json"),
    )
    assert runner.status().state == "FAILED"
    assert "中断" in runner.status().message


def test_completion_between_status_read_and_lock_is_preserved(
    console_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = ProbeRunner(console_root)
    running = ProbeStatus(state="RUNNING", job_id=uuid4(), started_at=utc_now())
    atomic_json(runner.status_path, running.model_dump(mode="json"))
    acquire = runner._lock
    completed = running.model_copy(
        update={"state": "SUCCEEDED", "exit_code": 0, "finished_at": utc_now()}
    )

    def completed_before_lock() -> IO[str]:
        atomic_json(runner.status_path, completed.model_dump(mode="json"))
        return acquire()

    monkeypatch.setattr(runner, "_lock", completed_before_lock)
    status = runner.status()
    assert status.state == "SUCCEEDED" and status.exit_code == 0
    assert ProbeStatus.model_validate_json(runner.status_path.read_text()).state == "SUCCEEDED"


def test_cli_probe_lock_prevents_overlapping_job(console_root: Path) -> None:
    with exclusive_probe(console_root):
        with pytest.raises(ProbeBusy):
            ProbeRunner(console_root).start()


@pytest.mark.parametrize("origin", [None, "https://untrusted.example", "null"])
def test_external_origin_cannot_start_probe(
    origin: str | None,
    console_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(self: ProbeRunner) -> ProbeStatus:
        pytest.fail("untrusted request reached job runner")

    monkeypatch.setattr(ProbeRunner, "start", forbidden)
    client = TestClient(
        create_app(console_root),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50000),
    )
    headers = {} if origin is None else {"origin": origin}
    assert client.post("/api/v1/probe", json={}, headers=headers).status_code == 403


def test_local_console_fixed_request_and_rejections(
    console_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_start(self: ProbeRunner) -> ProbeStatus:
        calls.append(True)
        return ProbeStatus(state="RUNNING", started_at=utc_now())

    monkeypatch.setattr(ProbeRunner, "start", fake_start)
    api = create_app(console_root)
    client = TestClient(api, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    headers = {"origin": "http://127.0.0.1:5173"}
    assert client.post("/api/v1/probe", json={}, headers=headers).status_code == 202
    assert (
        client.post("/api/v1/probe", json={"command": "anything"}, headers=headers).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/probe", json={}, headers={**headers, "host": "evil.example"}
        ).status_code
        == 403
    )
    remote = TestClient(api, base_url="http://127.0.0.1:8000", client=("203.0.113.1", 50000))
    assert remote.post("/api/v1/probe", json={}, headers=headers).status_code == 403
    assert len(calls) == 1
    assert client.post("/api/v1/orders", json={}, headers=headers).status_code == 404
    assert client.post("/api/v1/instruments", json={}, headers=headers).status_code == 405


def test_reports_download_allowlist_and_missing_data(console_root: Path) -> None:
    client = TestClient(create_app(console_root))
    assert client.get("/api/v1/data-quality").status_code == 503
    assert client.get("/api/v1/reports/quality_json").status_code == 503
    row = {
        "symbol": "NVDAUSDT",
        "closed_sample": 59,
        "unclosed_sample": 1,
        "closed_total": 59,
        "quality": "VALID",
        "timeliness": "FRESH",
        "gaps": [],
        "normalization_errors": [],
        "latest_closed_at": None,
    }
    (console_root / "reports/data_quality.json").write_text(json.dumps([row]))
    assert client.get("/api/v1/data-quality").json() == [row]
    response = client.get("/api/v1/reports/quality_json")
    assert response.status_code == 200
    assert "data_quality.json" in response.headers["content-disposition"]
    assert client.get("/api/v1/reports/settings.example.yaml").status_code == 422
    assert client.get("/api/v1/reports/..%2Fconfig%2Fsettings.example.yaml").status_code == 404
    (console_root / "reports/data_quality.json").write_text("{}")
    assert client.get("/api/v1/data-quality").status_code == 503
    (console_root / "reports/data_quality.json").write_text('[{"symbol": "NVDAUSDT"}]')
    assert client.get("/api/v1/data-quality").status_code == 503


def test_start_rechecks_live_disabled(console_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = ProbeRunner(console_root)
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    with pytest.raises(ValueError, match="P0 requires"):
        runner.start()
    assert runner.status().state == "IDLE"
