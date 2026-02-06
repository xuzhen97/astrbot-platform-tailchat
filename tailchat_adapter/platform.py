from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yaml
from astrbot import logger
from astrbot.api.platform import (
    AstrBotMessage,
    MessageMember,
    MessageType,
    Platform,
    PlatformMetadata,
    register_platform_adapter,
)
from astrbot.api.message_components import Plain, Image
from astrbot.api.event import MessageChain

DEFAULT_CONFIG_TMPL_FALLBACK: dict[str, Any] = {
    "tailchat": {
        "host": "https://tailchat.msgbyte.com",
        "app_id": "YOUR_APP_ID",
        "app_secret": "YOUR_APP_SECRET",
    },
    "server": {
        "listen_host": "0.0.0.0",
        "listen_port": 8088,
        "callback_path": "/tailchat/callback",
    },
    "security": {
        "callback_token": "CHANGE_ME",
    },
    "features": {
        "require_mention": True,
        "attachment_mode": "url_only",
        "max_attachment_mb": 50,
        "download_dir": "./data/tailchat_downloads",
    },
}


def _load_default_config() -> dict[str, Any]:
    config_path = Path(__file__).resolve().parents[1] / "config.example.yaml"
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception as exc:
            logger.warning("[tailchat] failed to load %s: %s", config_path, exc)
    return DEFAULT_CONFIG_TMPL_FALLBACK


DEFAULT_CONFIG_TMPL = _load_default_config()

from .api import TailchatAPI
from .parse import parse_incoming
from .server import TailchatCallbackServer
from .types import IncomingMessage
from .event import TailchatAstrMessageEvent


@register_platform_adapter(
    "tailchat",
    "Tailchat OpenApp Bot (HTTP callback)",
    default_config_tmpl=DEFAULT_CONFIG_TMPL,
)
class TailchatPlatform(Platform):
    def __init__(
        self,
        platform_config: dict[str, Any],
        platform_settings: dict[str, Any],
        event_queue: asyncio.Queue,
    ) -> None:
        super().__init__(event_queue)

        self.config = platform_config or {}
        self.settings = platform_settings or {}

        host = self.config.get("tailchat", {}).get("host", "https://tailchat.msgbyte.com")
        app_id = self.config.get("tailchat", {}).get("app_id", "")
        app_secret = self.config.get("tailchat", {}).get("app_secret", "")

        self.api = TailchatAPI(host=host, app_id=app_id, app_secret=app_secret)

        srv_cfg = self.config.get("server", {}) or {}
        sec_cfg = self.config.get("security", {}) or {}

        self.callback_path = srv_cfg.get("callback_path", "/tailchat/callback")
        self.listen_host = srv_cfg.get("listen_host", "0.0.0.0")
        self.listen_port = int(srv_cfg.get("listen_port", 8088))

        self.callback_token = sec_cfg.get("callback_token", None)
        self.allow_ips = sec_cfg.get("allow_ips", []) or []

        self._incoming_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        self._server: TailchatCallbackServer | None = None

    def meta(self) -> PlatformMetadata:
        return PlatformMetadata("tailchat", "Tailchat OpenApp Bot (HTTP callback)")

    async def run(self):
        logger.info(
            "[tailchat] callback server at %s:%s%s",
            self.listen_host,
            self.listen_port,
            self.callback_path,
        )
        self._server = TailchatCallbackServer(
            listen_host=self.listen_host,
            listen_port=self.listen_port,
            callback_path=self.callback_path,
            callback_token=self.callback_token,
            allow_ips=self.allow_ips,
            enqueue=self._enqueue_payload_threadsafe,
        )
        self._server.start()

        while True:
            payload = await self._incoming_queue.get()
            try:
                incoming = parse_incoming(payload, self.config)
                if incoming is None:
                    continue
                abm = await self.convert_message(incoming=incoming, raw=payload)
                await self.handle_msg(abm, incoming=incoming, raw=payload)
            except Exception as e:
                logger.exception("[tailchat] failed to handle payload: %s", e)

    def _enqueue_payload_threadsafe(self, payload: dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(self._incoming_queue.put_nowait, payload)

    async def convert_message(self, incoming: IncomingMessage, raw: dict[str, Any]) -> AstrBotMessage:
        abm = AstrBotMessage()
        abm.type = MessageType.GROUP_MESSAGE if incoming.group_id else MessageType.FRIEND_MESSAGE
        abm.group_id = incoming.group_id or ""
        abm.self_id = incoming.self_id or "tailchat-bot"
        abm.session_id = incoming.session_key
        abm.message_id = incoming.message_id
        abm.raw_message = raw

        abm.sender = MessageMember(user_id=incoming.sender_id, nickname=incoming.sender_name)

        abm.message_str = incoming.text or ""
        chain = [Plain(text=abm.message_str)] if abm.message_str else []

        for att in incoming.attachments:
            if att.kind == "image" and att.url:
                chain.append(Image(file=att.url))
            elif att.url:
                chain.append(Plain(text=f"\n[File] {att.name} {att.url}"))

        abm.message = chain
        return abm

    async def handle_msg(self, message: AstrBotMessage, incoming: IncomingMessage, raw: dict[str, Any]) -> None:
        event = TailchatAstrMessageEvent(
            message_str=message.message_str,
            message_obj=message,
            platform_meta=self.meta(),
            session_id=message.session_id,
            platform=self,
            incoming=incoming,
            raw=raw,
        )
        self.commit_event(event)

    async def send_by_session(self, session, message_chain: MessageChain):
        await super().send_by_session(session, message_chain)

    async def send_text(self, group_id: str, converse_id: str, text: str, reply_to: dict[str, Any] | None = None):
        return await self.api.send_message(group_id=group_id, converse_id=converse_id, content=text, reply=reply_to)

    async def terminate(self):
        if self._server:
            self._server.stop()
        await self.api.close()
