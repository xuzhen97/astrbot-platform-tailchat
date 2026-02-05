from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

from .adapter import TailchatPlatformAdapter
from .utils import write_redacted_payload

LOGGER = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    listen_host: str = "0.0.0.0"
    listen_port: int = 8088


@dataclass
class BotCallbackConfig:
    bot_key: str
    callback_path: str
    callback_token: Optional[str]
    adapter: TailchatPlatformAdapter


@dataclass
class SecurityConfig:
    allow_ips: list[str] | None = None
    enable_body_hash: bool = False
    body_hash_header: str = "X-Body-Hash"


class TailchatCallbackServer:
    def __init__(
        self,
        bots: list[BotCallbackConfig],
        server_config: ServerConfig,
        security_config: SecurityConfig,
    ) -> None:
        self.bots = bots
        self.server_config = server_config
        self.security_config = security_config
        self.app = FastAPI()
        self._server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None
        self._setup_routes()

    def _setup_routes(self) -> None:
        for bot in self.bots:
            @self.app.post(bot.callback_path)
            async def callback(request: Request, bot_key: str = bot.bot_key) -> JSONResponse:
                request_id = str(uuid.uuid4())
                if not self._check_security(request, bot_key):
                    return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

                raw_body = await request.body()
                if self.security_config.enable_body_hash:
                    if not self._check_body_hash(request, raw_body):
                        return JSONResponse({"ok": False, "error": "invalid body hash"}, status_code=401)

                try:
                    payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                except json.JSONDecodeError:
                    LOGGER.warning("[%s] Invalid JSON payload", request_id)
                    write_redacted_payload(raw_body.decode("utf-8", errors="ignore"), request_id)
                    return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)

                LOGGER.debug(
                    "[%s] Tailchat callback: bot=%s keys=%s",
                    request_id,
                    bot_key,
                    list(payload.keys()) if isinstance(payload, dict) else type(payload),
                )

                adapter = self._get_adapter(bot_key)
                if not adapter:
                    return JSONResponse({"ok": False, "error": "unknown bot"}, status_code=404)
                asyncio.create_task(adapter.handle_incoming(payload, request_id))
                return JSONResponse({"ok": True})

    def _get_adapter(self, bot_key: str) -> Optional[TailchatPlatformAdapter]:
        for bot in self.bots:
            if bot.bot_key == bot_key:
                return bot.adapter
        return None

    def _check_security(self, request: Request, bot_key: str) -> bool:
        token = self._get_callback_token(bot_key)
        if token:
            request_token = request.query_params.get("token")
            if request_token != token:
                LOGGER.warning("Invalid callback token for %s from %s", bot_key, request.client.host if request.client else "unknown")
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

    def _get_callback_token(self, bot_key: str) -> Optional[str]:
        for bot in self.bots:
            if bot.bot_key == bot_key:
                return bot.callback_token
        return None

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
