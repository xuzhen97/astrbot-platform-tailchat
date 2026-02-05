from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

from .adapter import TailchatPlatformAdapter

LOGGER = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    listen_host: str = "0.0.0.0"
    listen_port: int = 8088
    callback_path: str = "/tailchat/callback"


@dataclass
class SecurityConfig:
    callback_token: Optional[str] = None
    allow_ips: list[str] | None = None
    enable_body_hash: bool = False
    body_hash_header: str = "X-Body-Hash"


class TailchatCallbackServer:
    def __init__(
        self,
        adapter: TailchatPlatformAdapter,
        server_config: ServerConfig,
        security_config: SecurityConfig,
    ) -> None:
        self.adapter = adapter
        self.server_config = server_config
        self.security_config = security_config
        self.app = FastAPI()
        self._server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None
        self._setup_routes()

    def _setup_routes(self) -> None:
        @self.app.post(self.server_config.callback_path)
        async def callback(request: Request) -> JSONResponse:
            request_id = str(uuid.uuid4())
            if not self._check_security(request):
                return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

            raw_body = await request.body()
            if self.security_config.enable_body_hash:
                if not self._check_body_hash(request, raw_body):
                    return JSONResponse({"ok": False, "error": "invalid body hash"}, status_code=401)

            try:
                payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except json.JSONDecodeError:
                LOGGER.warning("[%s] Invalid JSON payload", request_id)
                return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)

            LOGGER.debug(
                "[%s] Tailchat callback: keys=%s",
                request_id,
                list(payload.keys()) if isinstance(payload, dict) else type(payload),
            )

            asyncio.create_task(self.adapter.handle_incoming(payload, request_id))
            return JSONResponse({"ok": True})

    def _check_security(self, request: Request) -> bool:
        if self.security_config.callback_token:
            token = request.query_params.get("token")
            if token != self.security_config.callback_token:
                LOGGER.warning("Invalid callback token from %s", request.client.host if request.client else "unknown")
                return False
        if self.security_config.allow_ips:
            client_ip = request.client.host if request.client else ""
            if client_ip not in self.security_config.allow_ips:
                LOGGER.warning("IP not allowed: %s", client_ip)
                return False
        return True

    def _check_body_hash(self, request: Request, raw_body: bytes) -> bool:
        header = request.headers.get(self.security_config.body_hash_header)
        if not header:
            return False
        digest = hashlib.sha256(raw_body).hexdigest()
        return digest == header

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        config = uvicorn.Config(
            self.app,
            host=self.server_config.listen_host,
            port=self.server_config.listen_port,
            log_level="info",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)
