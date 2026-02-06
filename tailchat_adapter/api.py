from __future__ import annotations

import hashlib
from typing import Any, Optional

import httpx


class TailchatAPI:
    def __init__(self, host: str, app_id: str, app_secret: str) -> None:
        self.host = host.rstrip("/")
        self.app_id = app_id
        self.app_secret = app_secret
        self._jwt: Optional[str] = None
        self._client = httpx.AsyncClient(timeout=15)

    async def login(self) -> str:
        token = hashlib.md5(f"{self.app_id}{self.app_secret}".encode("utf-8")).hexdigest()
        resp = await self._client.post(
            f"{self.host}/api/openapi/bot/login",
            json={"appId": self.app_id, "token": token},
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        jwt = (data.get("data") or {}).get("jwt") or (data.get("data") or {}).get("token") or data.get("jwt") or data.get("token")
        if not jwt:
            raise RuntimeError(f"Tailchat login: cannot find jwt in response: {data}")
        self._jwt = jwt
        return jwt

    async def send_message(
        self,
        group_id: str,
        converse_id: str,
        content: str,
        reply: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._jwt:
            await self.login()

        payload: dict[str, Any] = {
            "converseId": converse_id,
            "groupId": group_id,
            "content": content,
            "plain": content,
            "meta": {},
        }

        if reply and reply.get("message_id"):
            payload["meta"] = {
                "mentions": [reply.get("author_id")] if reply.get("author_id") else [],
                "reply": {
                    "_id": reply.get("message_id"),
                    "author": reply.get("author_id") or "",
                    "content": reply.get("content") or "",
                },
            }

        resp = await self._client.post(
            f"{self.host}/api/chat/message/sendMessage",
            json=payload,
            headers={"Content-Type": "application/json", "X-Token": self._jwt or ""},
        )

        if resp.status_code in (401, 403):
            await self.login()
            resp = await self._client.post(
                f"{self.host}/api/chat/message/sendMessage",
                json=payload,
                headers={"Content-Type": "application/json", "X-Token": self._jwt or ""},
            )

        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()
