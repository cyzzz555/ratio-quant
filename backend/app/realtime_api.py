"""Loopback-only P2 controls and snapshot stream, never trading endpoints."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict

from app.realtime_models import StartRealtime
from app.realtime_worker import RealtimeBusy, RealtimeController
from app.research_api import local_request


class StopRealtime(BaseModel):
    model_config = ConfigDict(extra="forbid")


def router(controller: RealtimeController) -> APIRouter:
    api = APIRouter()

    @api.get("/api/v1/realtime")
    async def status() -> dict[str, Any]:
        return controller.snapshot()

    @api.post("/api/v1/realtime/start", status_code=202)
    async def start(request: Request, body: StartRealtime) -> dict[str, Any]:
        local_request(request)
        try:
            return await controller.start(body)
        except RealtimeBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "本机归档不可写，采集未启动") from exc

    @api.post("/api/v1/realtime/stop", status_code=202)
    async def stop(request: Request, body: StopRealtime) -> dict[str, Any]:
        local_request(request)
        return await controller.stop()

    @api.websocket("/api/v1/stream")
    async def stream(socket: WebSocket) -> None:
        allowed = {f"http://{h}:{p}" for h in ("localhost", "127.0.0.1") for p in (5173, 8000)}
        if (
            socket.client is None
            or socket.client.host not in {"127.0.0.1", "::1"}
            or socket.headers.get("origin") not in allowed
            or socket.headers.get("host") not in {"127.0.0.1:8000", "localhost:8000"}
        ):
            await socket.close(code=1008)
            return
        await socket.accept()
        try:
            while True:
                await socket.send_json(jsonable_encoder(controller.snapshot()))
                # Receive once per cycle to observe close and enforce read-only operation.
                try:
                    await asyncio.wait_for(socket.receive_text(), timeout=2)
                    await socket.close(code=1008)
                    return
                except TimeoutError:
                    pass
        except WebSocketDisconnect:
            pass

    return api
