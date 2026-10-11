import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from app import file_lock, local_workspace
from app.settings import ROOT
from app.storage import atomic_json


def test_process_lock_contention_release_and_blocking(tmp_path: Path) -> None:
    path = tmp_path / "lease.lock"
    script = (
        "import sys; from app import file_lock; "
        "stream = open(sys.argv[1], 'a'); "
        "file_lock.flock(stream, file_lock.LOCK_EX | file_lock.LOCK_NB)"
    )
    env = dict(os.environ, PYTHONPATH=str(ROOT / "backend"))
    with path.open("a") as owner:
        file_lock.flock(owner, file_lock.LOCK_EX)
        result = subprocess.run(
            [sys.executable, "-c", script, str(path)], env=env, capture_output=True, timeout=10
        )
        assert result.returncode != 0 and b"BlockingIOError" in result.stderr
        acquired = threading.Event()

        def wait_for_lock() -> None:
            with path.open("a") as contender:
                file_lock.flock(contender, file_lock.LOCK_EX)
                acquired.set()

        waiter = threading.Thread(target=wait_for_lock)
        waiter.start()
        try:
            assert not acquired.wait(0.1)
        finally:
            file_lock.flock(owner, file_lock.LOCK_UN)
            waiter.join(timeout=5)
        assert acquired.is_set() and not waiter.is_alive()
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)], env=env, capture_output=True, timeout=10
    )
    assert result.returncode == 0, result.stderr


def test_utf8_json_and_windows_replace_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "中文.json"
    replace = os.replace
    attempts = 0

    def busy_reader(source: Path, target: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1 and os.name == "nt":
            raise PermissionError("Windows reader holds destination")
        replace(source, target)

    monkeypatch.setattr("app.storage.os.replace", busy_reader)
    atomic_json(destination, {"name": "比特币"})
    assert "比特币" in destination.read_text(encoding="utf-8")
    assert attempts == (2 if os.name == "nt" else 1)


def test_frontend_uses_direct_node_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.local_workspace.shutil.which", lambda *args, **kwargs: "node")
    monkeypatch.setattr(Path, "exists", lambda self: True)
    command, _ = local_workspace.frontend_runtime()
    assert command == ["node", str(ROOT / "frontend/node_modules/vite/bin/vite.js")]


def test_file_mode_skips_database_and_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["workspace", "--file-only"])
    monkeypatch.setattr(
        "app.research_db.engine", lambda *args: pytest.fail("DB opened in file mode")
    )
    monkeypatch.setattr(local_workspace, "available", lambda url: True)
    opened: list[str] = []
    monkeypatch.setattr(local_workspace.webbrowser, "open", lambda url: opened.append(url))

    def stop(seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(local_workspace.time, "sleep", stop)
    local_workspace.main()
    assert opened == ["http://127.0.0.1:5173/#market"]
