from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Callable, Iterable

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class TailchatCallbackServer:
    def __init__(
        self,
        listen_host: str,
        listen_port: int,
        callback_path: str,
        callback_token: str | None,
        allow_ips: Iterable[str],
        enqueue: Callable[[dict[str, Any]], None],
    ) -> None:
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.callback_path = callback_path
        self.callback_token = callback_token
        self.allow_ips = set([ip for ip in allow_ips if ip])
        self.enqueue = enqueue

        self._app = FastAPI()
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

        self._mount_routes()

    def _mount_routes(self) -> None:
        path = self.callback_path if self.callback_path.startswith("/") else ("/" + self.callback_path)

        @self._app.post(path)
        async def callback(request: Request) -> JSONResponse:
            request_id = str(uuid.uuid4())

            if self.allow_ips and request.client and request.client.host not in self.allow_ips:
                return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

            if self.callback_token:
                q = request.query_params.get("token")
                if q != self.callback_token:
                    return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

            raw_body = await request.body()
            try:
                payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except json.JSONDecodeError:
                return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)

            try:
                self.enqueue(payload)
            except Exception:
                return JSONResponse({"ok": True, "queued": False, "request_id": request_id})

            return JSONResponse({"ok": True, "queued": True, "request_id": request_id})

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        config = uvicorn.Config(self._app, host=self.listen_host, port=self.listen_port, log_level="info")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
