"""Local fixed-command public probe jobs; no account credentials or order commands."""

import fcntl
import os
import re
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import IO, Any, Literal
from uuid import UUID, uuid4

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models import utc_now
from app.settings import load_settings
from app.storage import atomic_json


class ProbeBusy(Exception):
    pass


class ProbeCooldown(Exception):
    pass


class ProbeStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: UUID | None = None
    state: Literal["IDLE", "RUNNING", "SUCCEEDED", "FAILED"] = "IDLE"
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    exit_code: int | None = None
    message: str = "尚未从控制台运行探测"
    completed_symbols: list[str] = Field(default_factory=list)
    total_symbols: int = 0
    log: str = ""
    live_trading_enabled: Literal[False] = False


@contextmanager
def exclusive_probe(root: Path) -> Iterator[None]:
    """Protect the whole report set across CLI and UI invocations."""
    directory = root / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".probe.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProbeBusy("已有只读探测正在运行，请等待完成") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class ProbeRunner:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.directory = root / "reports" / "jobs"
        self._mutex = threading.RLock()
        self.timeout_seconds = 180

    @property
    def status_path(self) -> Path:
        return self.directory / "latest.json"

    def _read(self) -> ProbeStatus:
        if not self.status_path.exists():
            return ProbeStatus()
        try:
            return ProbeStatus.model_validate_json(self.status_path.read_text())
        except (OSError, ValueError):
            return ProbeStatus(state="FAILED", message="本地任务状态文件不可用")

    def _write(self, status: ProbeStatus) -> None:
        atomic_json(self.status_path, status.model_dump(mode="json"))

    def _lock(self) -> IO[str]:
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = (self.directory / ".runner.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock.close()
            raise ProbeBusy("已有控制台探测正在运行") from exc
        return lock

    def status(self) -> ProbeStatus:
        with self._mutex:
            status = self._read()
            if status.state == "RUNNING":
                try:
                    lock = self._lock()
                except ProbeBusy:
                    pass
                else:
                    # A held process lock is required to claim a job is still running.
                    try:
                        status = status.model_copy(
                            update={
                                "state": "FAILED",
                                "finished_at": utc_now(),
                                "message": "任务控制进程已中断；采集子进程可能仍在运行，请检查日志",
                            }
                        )
                        self._write(status)
                    finally:
                        lock.close()
            if status.job_id:
                path = self.directory / f"{status.job_id}.log"
                try:
                    with path.open("rb") as stream:
                        stream.seek(0, 2)
                        stream.seek(max(0, stream.tell() - 16384))
                        log = stream.read().decode("utf-8", errors="replace")
                except OSError:
                    log = ""
                symbols = list(
                    dict.fromkeys(
                        re.findall(
                            r"^([A-Z0-9_]+): (?:VERIFIED_PUBLIC|UNKNOWN|UNAVAILABLE);", log, re.M
                        )
                    )
                )
                status = status.model_copy(update={"log": log, "completed_symbols": symbols})
            return status

    def start(self) -> ProbeStatus:
        with self._mutex:
            load_settings(self.root)
            lock = self._lock()
            try:
                previous = self._read()
                if previous.started_at and utc_now() - previous.started_at < timedelta(seconds=60):
                    raise ProbeCooldown("两次探测至少间隔 60 秒，请稍后再试")
                # Check CLI occupancy; the child also acquires this lock atomically.
                with exclusive_probe(self.root):
                    pass
                candidates: dict[str, Any] = yaml.safe_load(
                    (self.root / "config/instruments.example.yaml").read_text()
                )
                count = sum(len(x) for x in candidates["watchlist_candidates"].values())
                status = ProbeStatus(
                    job_id=uuid4(),
                    state="RUNNING",
                    started_at=utc_now(),
                    total_symbols=count,
                    message="正在执行公共 GET 与 WebSocket 只读探测",
                )
                self._write(status)
                thread = threading.Thread(target=self._execute, args=(status, lock), daemon=True)
                thread.start()
                return status
            except BaseException:
                lock.close()
                raise

    def _execute(self, status: ProbeStatus, lock: IO[str]) -> None:
        try:
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONPATH": str(self.root / "backend"),
                    "PYTHONUNBUFFERED": "1",
                    "LIVE_TRADING_ENABLED": "false",
                    "APPROVAL_MODE": "HUMAN",
                    "TRADE_ADAPTER": "PAPER_BROKER",
                }
            )
            with (self.directory / f"{status.job_id}.log").open("w") as output:
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "app.probe"],
                        cwd=self.root,
                        env=env,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        timeout=self.timeout_seconds,
                        check=False,
                    )
                    exit_code = result.returncode
                    state = "SUCCEEDED" if exit_code == 0 else "FAILED"
                    message = (
                        "探测完成；各项能力以报告证据为准"
                        if exit_code == 0
                        else "探测进程失败，查看日志；保留已有报告"
                    )
                except subprocess.TimeoutExpired:
                    state, exit_code = "FAILED", None
                    message = "探测超过 180 秒，进程已停止；保留已有报告"
                    output.write("\nPROBE_TIMEOUT: child process stopped\n")
                except OSError as exc:
                    state, exit_code = "FAILED", None
                    message = f"无法启动探测：{type(exc).__name__}"
            self._write(
                status.model_copy(
                    update={
                        "state": state,
                        "exit_code": exit_code,
                        "finished_at": utc_now(),
                        "message": message,
                    }
                )
            )
        finally:
            lock.close()
