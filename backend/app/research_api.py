"""Local research operations; background history/backtest jobs, no trading routes."""

import json
import logging
import threading
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app import backtest, file_lock, research_data, research_db, research_records
from app.market_catalog import (
    CatalogRequest,
    CatalogService,
    MarketCatalog,
    NameConflict,
    NameUpdateRequest,
    NameUpdateResult,
)
from app.models import utc_now
from app.research_models import BacktestRequest, DatasetRequest
from app.research_records import RecordChangeRequest
from app.risk import RiskRequest, preview
from app.storage import atomic_json


def local_request(request: Request) -> None:
    origins = {
        f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in (5173, 8000)
    }
    if (
        request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
        or request.headers.get("origin") not in origins
        or request.headers.get("host") not in {"127.0.0.1:8000", "localhost:8000"}
        or request.headers.get("content-type", "").split(";")[0] != "application/json"
    ):
        raise HTTPException(403, "仅允许本地控制台 JSON 操作")


class ResearchJobs:
    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "reports").mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.snapshot_lock = threading.Lock()
        self.path = root / "reports/research_job.json"
        self.snapshot: dict[str, Any] = {"state": "IDLE", "message": "尚未运行研究任务"}
        if self.path.exists():
            self.snapshot = json.loads(self.path.read_text(encoding="utf-8"))
            if self.snapshot["state"] == "RUNNING":
                with (root / "reports/research_worker.lock").open("a", encoding="utf-8") as lease:
                    try:
                        file_lock.flock(lease, file_lock.LOCK_EX | file_lock.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        self.update(
                            state="FAILED",
                            message="研究进程已中断；不自动重试",
                            finished_at=utc_now().isoformat(),
                        )

    def update(self, **values: Any) -> None:
        with self.snapshot_lock:
            self.snapshot = {**self.snapshot, **values}
            atomic_json(self.path, self.snapshot)
            with (self.root / "reports/research_jobs.jsonl").open("a", encoding="utf-8") as audit:
                audit.write(
                    json.dumps({"at": utc_now().isoformat(), **self.snapshot}, ensure_ascii=False)
                    + "\n"
                )

    def status(self) -> dict[str, Any]:
        with self.snapshot_lock:
            if self.path.exists():
                return dict(json.loads(self.path.read_text(encoding="utf-8")))
            return dict(self.snapshot)

    def start(self, kind: str, params: DatasetRequest | BacktestRequest) -> dict[str, Any]:
        if not self.lock.acquire(blocking=False):
            raise HTTPException(409, "已有研究任务正在运行")
        lease = (self.root / "reports/research_worker.lock").open("a", encoding="utf-8")
        try:
            file_lock.flock(lease, file_lock.LOCK_EX | file_lock.LOCK_NB)
        except BlockingIOError as exc:
            lease.close()
            self.lock.release()
            raise HTTPException(409, "其他进程已有研究任务") from exc
        self.update(
            parameters=params.model_dump(mode="json"),
            job_id=str(uuid4()),
            kind=kind,
            state="RUNNING",
            message="任务已开始",
            started_at=utc_now().isoformat(),
            finished_at=None,
            result_id=None,
        )
        snapshot = self.status()

        def work() -> None:
            try:
                if isinstance(params, DatasetRequest):
                    result = research_data.collect(
                        self.root, params, lambda msg: self.update(message=msg)
                    )
                    result_id = result["id"]
                else:
                    self.update(message="正在计算基准、2x 与 5x 滑点压力情景")
                    result = backtest.run(self.root, params)
                    result_id = result["run_id"]
                ledger = "FILE_STAGING_PENDING_POSTGRESQL"
                if research_db.health(self.root)["ready"]:
                    from app.research_ledger import synchronize

                    synchronize(self.root)
                    ledger = "POSTGRESQL"
                self.update(
                    state="SUCCEEDED",
                    message="研究任务完成",
                    result_id=result_id,
                    metadata_ledger=ledger,
                    finished_at=utc_now().isoformat(),
                )
            except Exception as exc:
                logging.exception("Research task failed: %s", kind)
                message = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else type(exc).__name__ + "；请查看服务日志"
                )
                self.update(state="FAILED", message=message, finished_at=utc_now().isoformat())
            finally:
                lease.close()
                self.lock.release()

        threading.Thread(target=work, name="research-job", daemon=True).start()
        return snapshot


def router(root: Path) -> APIRouter:
    api = APIRouter(prefix="/api/v1")
    jobs = ResearchJobs(root)
    market_lock = threading.Lock()
    catalog_service = CatalogService(root)

    @api.get("/research/status")
    def status() -> dict[str, Any]:
        return {
            "phase": "P1_RESEARCH_IN_PROGRESS",
            "database": research_db.health(root),
            "live_trading_enabled": False,
            "paper_trading_phase": "P3_PENDING",
            "job": jobs.status(),
        }

    @api.get("/research/datasets")
    def datasets() -> list[dict[str, Any]]:
        return research_data.manifests(root)

    @api.get("/research/runs")
    def runs() -> list[dict[str, Any]]:
        return backtest.runs(root, None)

    @api.get("/research/trash")
    def trash() -> list[dict[str, Any]]:
        return research_records.trash(root)

    @api.post("/research/runs/{identifier}/{action}")
    def change_record(
        request: Request,
        identifier: str,
        action: Literal["delete", "restore"],
        params: RecordChangeRequest,
    ) -> dict[str, Any]:
        local_request(request)
        try:
            result = research_records.change(root, identifier, action, params.expected_result_hash)
        except FileNotFoundError as exc:
            raise HTTPException(404, "回测记录不存在，请刷新记录") from exc
        except research_records.RecordConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "记录操作未能完成，请刷新后重试") from exc
        return result

    @api.post("/research/datasets", status_code=202)
    def collect(request: Request, params: DatasetRequest) -> dict[str, Any]:
        local_request(request)
        # The worker rechecks current exchangeInfo before any symbol history request.
        return jobs.start("DATASET", params)

    @api.post("/research/backtests", status_code=202)
    def test(request: Request, params: BacktestRequest) -> dict[str, Any]:
        local_request(request)
        if not (root / "data/research" / params.dataset_id / "manifest.json").is_file():
            raise HTTPException(404, "研究数据集不存在")
        return jobs.start("BACKTEST", params)

    @api.post("/market/catalog", response_model=MarketCatalog)
    def catalog(request: Request, params: CatalogRequest) -> MarketCatalog:
        local_request(request)
        try:
            return catalog_service.get(refresh=params.refresh)
        except (ValueError, OSError) as exc:
            raise HTTPException(503, "合约目录读取失败：" + str(exc)) from exc

    @api.post("/market/names", response_model=NameUpdateResult)
    def save_name(request: Request, params: NameUpdateRequest) -> NameUpdateResult:
        local_request(request)
        try:
            return catalog_service.save_name(params)
        except NameConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "本地名称文件无法保存，请查看服务日志") from exc

    @api.post("/market/{symbol}")
    def market(
        request: Request, symbol: str, timeframe: Literal["1m", "5m", "15m", "1h", "1d"] = "1m"
    ) -> dict[str, Any]:
        local_request(request)
        if not market_lock.acquire(blocking=False):
            raise HTTPException(409, "行情请求正在进行")
        try:
            return research_data.market(root, symbol, timeframe)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            market_lock.release()

    @api.post("/risk/preview")
    def risk(request: Request, params: RiskRequest) -> dict[str, object]:
        local_request(request)
        return preview(params)

    @api.get("/research/results/{identifier}")
    def download(identifier: str) -> FileResponse:
        try:
            if str(__import__("uuid").UUID(identifier)) != identifier:
                raise ValueError("invalid uuid")
        except ValueError as exc:
            raise HTTPException(422, "无效报告 ID") from exc
        path = root / "reports/research" / (identifier + ".json")
        if not path.exists():
            raise HTTPException(404, "报告不存在")
        return FileResponse(path, filename=path.name)

    return api
