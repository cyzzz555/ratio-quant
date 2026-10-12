"""Local-only paper experiment controls. Public dummy codes are not real 2FA."""

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.paper_db import PostgresPaperStore
from app.paper_engine import PaperError
from app.paper_models import CreatePaper, PaperCommand
from app.paper_store import FilePaperStore, PaperConflict, PaperStoreError
from app.research_api import local_request


def router(root: Path) -> APIRouter:
    mode = os.environ.get("QUANT_PAPER_STORE", "offline_file")
    if mode not in {"offline_file", "postgresql"}:
        raise ValueError("invalid explicit paper store mode")
    store = PostgresPaperStore(root) if mode == "postgresql" else FilePaperStore(root)
    api = APIRouter()

    def failure(exc: Exception) -> HTTPException:
        if isinstance(exc, PaperConflict):
            return HTTPException(409, str(exc))
        if isinstance(exc, PaperError):
            return HTTPException(422, str(exc))
        if isinstance(exc, ValidationError):
            return HTTPException(422, "模拟参数格式无效，请检查字段和数值")
        return HTTPException(503, "纸面台账不可用，禁止新增模拟风险；请检查存储与回放完整性")

    @api.get("/api/v1/paper/sessions")
    def sessions() -> dict[str, Any]:
        try:
            return dict(
                sessions=store.list_sessions(),
                persistence=store.persistence,
                live_trading_enabled=False,
                phase="P3_IN_PROGRESS",
            )
        except (PaperError, PaperStoreError, OSError, SQLAlchemyError) as exc:
            raise failure(exc) from exc

    @api.post("/api/v1/paper/sessions", status_code=201)
    def create(request: Request, body: CreatePaper) -> dict[str, Any]:
        local_request(request)
        try:
            return store.create(body)
        except (PaperError, PaperStoreError, OSError, SQLAlchemyError) as exc:
            raise failure(exc) from exc

    @api.get("/api/v1/paper/sessions/{identifier}")
    def status(identifier: str) -> dict[str, Any]:
        try:
            return store.status(identifier)
        except (PaperError, PaperStoreError, OSError, SQLAlchemyError) as exc:
            raise failure(exc) from exc

    @api.post("/api/v1/paper/commands")
    def command(request: Request, body: PaperCommand) -> dict[str, Any]:
        local_request(request)
        try:
            return store.execute(body)
        except (PaperError, PaperStoreError, ValidationError, OSError, SQLAlchemyError) as exc:
            raise failure(exc) from exc

    return api
