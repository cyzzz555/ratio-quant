"""Local public read-only API. Authenticated account APIs belong to later phases."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models import Capability, Phase0Report, utc_now
from app.probe_jobs import ProbeBusy, ProbeCooldown, ProbeRunner, ProbeStatus
from app.research_api import router
from app.settings import ROOT, load_settings


def read_report(root: Path) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(
            (root / "reports/instrument_capabilities.json").read_text()
        )
        return Phase0Report.model_validate(data).model_dump(mode="json")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, "Capability evidence unavailable or invalid") from exc


class EmptyProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QualityRow(BaseModel):
    symbol: str
    closed_sample: int = Field(ge=0)
    unclosed_sample: int = Field(ge=0)
    closed_total: int = Field(ge=0)
    timeliness: Literal["FRESH", "STALE", "UNAVAILABLE"]
    quality: Literal["VALID", "UNAVAILABLE"]
    gaps: list[dict[str, Any]]
    normalization_errors: list[str]
    latest_closed_at: AwareDatetime | None


def create_app(root: Path = ROOT) -> FastAPI:
    load_settings(root)
    api = FastAPI(title="Quant System Research", version="0.1.0")
    api.include_router(router(root))
    runner = ProbeRunner(root)

    @api.get("/health/live")
    def live() -> dict[str, Any]:
        return {"alive": True, "phase": "P1_RESEARCH_IN_PROGRESS", "live_trading_enabled": False}

    @api.get("/health/ready")
    def ready() -> JSONResponse:
        reasons = ["RESEARCH_ONLY", "LIVE_DISABLED", "ACCOUNT_PERMISSIONS_UNVERIFIED"]
        service_ready = False
        try:
            report = read_report(root)
            caps = [Capability.model_validate(x) for x in report["instruments"]]
            age = utc_now() - max(x.verified_at for x in caps)
            service_ready = timedelta(0) <= age <= timedelta(minutes=15)
            if not service_ready:
                reasons.append("EVIDENCE_STALE_OR_FUTURE")
        except HTTPException:
            reasons.append("EVIDENCE_UNAVAILABLE")
        # /ready is trading readiness: must never return a green 200 in P0.
        return JSONResponse(
            status_code=503,
            content={
                "service_ready": service_ready,
                "trading_ready": False,
                "allow_new_risk": False,
                "live_trading_enabled": False,
                "reasons": reasons,
                "checked_at": utc_now().isoformat(),
            },
        )

    @api.get("/api/v1/instruments")
    def instruments() -> dict[str, Any]:
        return read_report(root)

    @api.get("/api/v1/probe", response_model=ProbeStatus)
    def probe_status() -> ProbeStatus:
        return runner.status()

    @api.post("/api/v1/probe", response_model=ProbeStatus, status_code=202)
    def start_probe(request: Request, body: EmptyProbeRequest) -> ProbeStatus:
        # Local orchestration only. Binance traffic remains public GET / WS receive.
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
            raise HTTPException(403, "Only local console JSON requests may start a public probe")
        try:
            return runner.start()
        except ProbeBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except ProbeCooldown as exc:
            raise HTTPException(429, str(exc)) from exc

    @api.get("/api/v1/data-quality")
    def data_quality() -> list[QualityRow]:
        try:
            result: Any = json.loads((root / "reports/data_quality.json").read_text())
            if not isinstance(result, list) or not all(isinstance(x, dict) for x in result):
                raise ValueError("invalid data quality report")
            return [QualityRow.model_validate(x) for x in result]
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Data quality report unavailable") from exc

    @api.get("/api/v1/reports/{name}")
    def download_report(
        name: Literal["capabilities_json", "capabilities_csv", "quality_md", "quality_json"],
    ) -> FileResponse:
        files = {
            "capabilities_json": "instrument_capabilities.json",
            "capabilities_csv": "instrument_capabilities.csv",
            "quality_md": "data_quality_report.md",
            "quality_json": "data_quality.json",
        }
        path = root / "reports" / files[name]
        if not path.is_file():
            raise HTTPException(503, "Report unavailable")
        return FileResponse(path, filename=path.name)

    return api


app = create_app()
