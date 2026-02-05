from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable, Optional

import httpx

from .adapter import TailchatPlatformAdapter
from .types import IncomingMessage

LOGGER = logging.getLogger(__name__)


@dataclass
class AstrBotRouteConfig:
    mode: str = "profile"
    profile_id: Optional[str] = None
    backend_url: Optional[str] = None


class TailchatMessageRouter:
    def __init__(
        self,
        adapter_map: dict[str, TailchatPlatformAdapter],
        route_map: dict[str, AstrBotRouteConfig],
        message_handler: Optional[Callable[[IncomingMessage], Optional[Awaitable[object]]]] = None,
    ) -> None:
        self.adapter_map = adapter_map
        self.route_map = route_map
        self.message_handler = message_handler
        self._client = httpx.AsyncClient(timeout=15)

    async def route_incoming(self, message: IncomingMessage) -> None:
        bot_key = message.metadata.get("bot_key")
        if not bot_key:
            LOGGER.warning("Missing bot_key in metadata")
            return
        routing = self.route_map.get(bot_key)
        if not routing:
            LOGGER.warning("No routing config for bot %s", bot_key)
            return

        if routing.mode == "backend":
            await self._route_backend(message, routing)
            return

        await self._route_profile(message, routing)

    async def _route_profile(self, message: IncomingMessage, routing: AstrBotRouteConfig) -> None:
        if routing.profile_id:
            message.metadata["astrbot_profile_id"] = routing.profile_id
        if not self.message_handler:
            LOGGER.info("No AstrBot message handler set for profile mode")
            return
        result = self.message_handler(message)
        if asyncio.iscoroutine(result):
            result = await result
        await self._send_reply_if_present(message, result)

    async def _route_backend(self, message: IncomingMessage, routing: AstrBotRouteConfig) -> None:
        if not routing.backend_url:
            LOGGER.warning("Backend mode requires backend_url")
            return
        endpoint = routing.backend_url.rstrip("/") + "/api/tailchat/ingest"
        payload = {
            "text": message.text,
            "attachments": [asdict(item) for item in message.attachments],
            "session_key": message.session_key,
            "metadata": message.metadata,
            "reply": asdict(message.reply) if message.reply else None,
        }
        try:
            response = await self._client.post(endpoint, json=payload)
            response.raise_for_status()
        except Exception:
            LOGGER.exception("Failed to route to backend %s", endpoint)
            return
        data = response.json() if response.content else {}
        reply_text = data.get("text_reply") or data.get("text")
        await self._send_reply_if_present(message, reply_text)

    async def _send_reply_if_present(self, message: IncomingMessage, result: Any) -> None:
        if not result:
            return
        adapter = self.adapter_map.get(message.metadata.get("bot_key", ""))
        if not adapter:
            return
        if isinstance(result, str):
            adapter.send_text(message, result)
            return
        if isinstance(result, list):
            for item in result:
                if isinstance(item, str):
                    adapter.send_text(message, item)

    async def close(self) -> None:
        await self._client.aclose()
