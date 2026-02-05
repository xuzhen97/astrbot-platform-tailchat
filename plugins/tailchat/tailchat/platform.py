from __future__ import annotations

import logging
import uuid
from typing import Any

from astrbot.api.platform import Platform, register_platform_adapter

from .event import TailchatMessageEvent
from .registry import registry
from .server_singleton import ensure_server_started
from .tailchat_api import TailchatAPI
from .utils import build_incoming_from_payload, config_get, gen_callback_path

LOGGER = logging.getLogger(__name__)


@register_platform_adapter(
    "tailchat",
    "Tailchat OpenApp Bot",
    default_config_tmpl="config.example.yaml",
)
class TailchatPlatform(Platform):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self.config = self._load_platform_config()
        self.robot_id = self._get_robot_id_safe()
        self.callback_path = gen_callback_path(self.robot_id)
        self.callback_token = config_get(self.config, "security.callback_token", None)

        host = config_get(self.config, "tailchat.host", "https://tailchat.msgbyte.com")
        app_id = config_get(self.config, "tailchat.app_id", "")
        app_secret = config_get(self.config, "tailchat.app_secret", "")
        self.api = TailchatAPI(host=host, app_id=app_id, app_secret=app_secret)

        listen_host = config_get(self.config, "server.listen_host", "0.0.0.0")
        listen_port = int(config_get(self.config, "server.listen_port", 8088))
        ensure_server_started(listen_host=listen_host, listen_port=listen_port)
        registry.register(self.robot_id, self)

        LOGGER.info(
            "Tailchat callback path registered: %s?token=%s",
            self.callback_path,
            self.callback_token or "",
        )

    async def on_callback(self, payload: dict[str, Any]) -> None:
        incoming = build_incoming_from_payload(payload, self.config, self.robot_id)
        if incoming is None:
            return
        event = TailchatMessageEvent(platform=self, message=incoming, raw=payload)
        self.commit_event(event)

    async def send_text(
        self,
        group_id: str,
        converse_id: str,
        text: str,
        reply_to: Any | None = None,
    ) -> dict[str, Any]:
        return self.api.send_message(group_id=group_id, converse_id=converse_id, content=text, reply=reply_to)

    def _load_platform_config(self) -> Any:
        if hasattr(self, "load_platform_config"):
            return self.load_platform_config()
        if hasattr(self, "config") and self.config:
            return self.config
        if hasattr(self, "ctx") and hasattr(self.ctx, "config"):
            return self.ctx.config
        return {}

    def _get_robot_id_safe(self) -> str:
        for attr in ("robot_id", "id", "bot_id", "instance_id"):
            value = getattr(self, attr, None)
            if isinstance(value, str) and value:
                return value
        name = getattr(self, "name", None) or getattr(self, "robot_name", None)
        if isinstance(name, str) and name:
            return name
        return str(uuid.uuid4())
