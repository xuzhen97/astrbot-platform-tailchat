from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

from .registry import registry
from .utils import write_redacted_payload

LOGGER = logging.getLogger(__name__)

_app: Optional[FastAPI] = None
_server: Optional[uvicorn.Server] = None
_thread: Optional[threading.Thread] = None


def ensure_server_started(listen_host: str, listen_port: int) -> None:
    global _app, _server, _thread
    if _thread and _thread.is_alive():
        return

    _app = FastAPI()

    @_app.post("/tailchat/callback/{robot_id}")
    async def callback(robot_id: str, request: Request) -> JSONResponse:
        request_id = str(uuid.uuid4())
        platform = registry.get(robot_id)
        if not platform:
            return JSONResponse({"ok": False, "error": "unknown robot"}, status_code=404)

        if not _check_token(request, platform):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

        raw_body = await request.body()
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except json.JSONDecodeError:
            LOGGER.warning("[%s] Invalid JSON payload", request_id)
            write_redacted_payload(raw_body.decode("utf-8", errors="ignore"), request_id)
            return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)

        LOGGER.debug(
            "[%s] Tailchat callback: robot_id=%s keys=%s",
            request_id,
            robot_id,
            list(payload.keys()) if isinstance(payload, dict) else type(payload),
        )

        asyncio.create_task(platform.on_callback(payload))
        return JSONResponse({"ok": True})

    config = uvicorn.Config(
        _app,
        host=listen_host,
        port=listen_port,
        log_level="info",
    )
    _server = uvicorn.Server(config)
    _thread = threading.Thread(target=_server.run, daemon=True)
    _thread.start()


def _check_token(request: Request, platform: object) -> bool:
    token = getattr(platform, "callback_token", None)
    if token:
        request_token = request.query_params.get("token")
        if request_token != token:
            client_host = request.client.host if request.client else "unknown"
            LOGGER.warning("Invalid callback token from %s", client_host)
            return False
    return True
