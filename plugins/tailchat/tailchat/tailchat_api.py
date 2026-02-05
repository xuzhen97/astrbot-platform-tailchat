from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

import httpx

from .types import ReplyInfo
from .utils import get_first

LOGGER = logging.getLogger(__name__)

LOGIN_PATH = "/api/openapi/bot/login"
SEND_MESSAGE_PATH = "/api/chat/message/sendMessage"


class TailchatAPI:
    def __init__(
        self,
        host: str,
        app_id: str,
        app_secret: str,
        login_path: str = LOGIN_PATH,
        send_message_path: str = SEND_MESSAGE_PATH,
        file_url_path: str = "/api/openapi/bot/file",
        upload_path: str = "/api/openapi/bot/upload",
    ) -> None:
        self.host = host.rstrip("/")
        self.app_id = app_id
        self.app_secret = app_secret
        self.login_path = login_path
        self.send_message_path = send_message_path
        self.file_url_path = file_url_path
        self.upload_path = upload_path
        self._token: Optional[str] = None
        self._client = httpx.Client(timeout=10)

    def login(self) -> str:
        token = hashlib.md5(f"{self.app_id}{self.app_secret}".encode("utf-8")).hexdigest()
        payload = {"appId": self.app_id, "token": token}
        response = self._client.post(self._build_url(self.login_path), json=payload)
        response.raise_for_status()
        data = response.json()
        token_value = get_first(data, ["data.token", "data.jwt", "token", "jwt"])
        if not token_value:
            raise RuntimeError(f"Unable to parse login token: {data}")
        self._token = token_value
        return token_value

    def send_message(
        self,
        group_id: str,
        converse_id: str,
        content: str,
        reply: Optional[ReplyInfo] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "groupId": group_id,
            "converseId": converse_id,
            "content": content,
        }
        if reply and reply.message_id:
            payload["meta"] = {
                "reply": {
                    "_id": reply.message_id,
                    "author": reply.author_id,
                    "content": reply.content,
                }
            }
        return self._post(self.send_message_path, payload)

    def resolve_file_url(self, file_id: str) -> Optional[str]:
        if not file_id:
            return None
        try:
            data = self._post(self.file_url_path, {"fileId": file_id})
        except Exception:
            LOGGER.exception("Failed to resolve file url for %s", file_id)
            return None
        return get_first(data, ["data.url", "url", "data.downloadUrl"])

    def download_file(self, url: str, max_bytes: int) -> bytes:
        with self._client.stream("GET", url) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise ValueError("Attachment exceeds max size")
            return bytes(data)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._token:
            self.login()
        response = self._client.post(
            self._build_url(path),
            headers={"X-Token": self._token or ""},
            json=payload,
        )
        if response.status_code in {401, 403}:
            self.login()
            response = self._client.post(
                self._build_url(path),
                headers={"X-Token": self._token or ""},
                json=payload,
            )
        response.raise_for_status()
        return response.json()

    def _build_url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.host}{path}"

    def close(self) -> None:
        self._client.close()
