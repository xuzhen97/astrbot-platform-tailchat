from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from .tailchat_adapter import (
    AstrBotRouteConfig,
    BotCallbackConfig,
    SecurityConfig,
    ServerConfig,
    TailchatAdapterConfig,
    TailchatCallbackServer,
    TailchatMessageRouter,
    TailchatPlatformAdapter,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class BotConfig:
    bot_key: str
    host: str
    app_id: str
    app_secret: str
    bot_user_id: Optional[str]
    callback_path: str
    callback_token: Optional[str]
    features: dict[str, Any]
    openapi_base: str
    login_path: str
    send_message_path: str
    file_url_path: str
    upload_path: str
    astrbot: AstrBotRouteConfig


@dataclass
class TailchatPlugin:
    config_path: Optional[Path] = None
    config_data: Optional[dict[str, Any]] = None
    message_handler: Optional[Callable[[Any], Any]] = None

    def __post_init__(self) -> None:
        if not self.config_data:
            path = self.config_path or Path("plugins/tailchat_adapter/config.yaml")
            if path.exists():
                self.config_data = load_config(path)
            else:
                self.config_data = {}
        self.router: Optional[TailchatMessageRouter] = None
        self.server: Optional[TailchatCallbackServer] = None
        self.adapters: dict[str, TailchatPlatformAdapter] = {}

    def start(self) -> None:
        self._build()
        if self.server:
            self.server.start()

    def stop(self) -> None:
        if self.server:
            self.server.stop()
        if self.router:
            for adapter in self.adapters.values():
                adapter.api.close()
            try:
                import asyncio

                asyncio.run(self.router.close())
            except RuntimeError:
                pass

    def _build(self) -> None:
        bots, server_config, security_config = build_bot_configs(self.config_data or {})
        self.router = TailchatMessageRouter(
            adapter_map=self.adapters,
            route_map={bot.bot_key: bot.astrbot for bot in bots},
            message_handler=self.message_handler,
        )
        for bot in bots:
            adapter_config = TailchatAdapterConfig(
                bot_key=bot.bot_key,
                host=bot.host,
                app_id=bot.app_id,
                app_secret=bot.app_secret,
                require_mention=bot.features.get("require_mention", True),
                attachment_mode=bot.features.get("attachment_mode", "url_only"),
                download_dir=bot.features.get("download_dir", "./data/tailchat_downloads"),
                max_attachment_mb=bot.features.get("max_attachment_mb", 50),
                session_key_template=bot.features.get("session_key_template", "{botKey}:{groupId}:{converseId}"),
                bot_user_id=bot.bot_user_id,
                openapi_base=bot.openapi_base,
                login_path=bot.login_path,
                send_message_path=bot.send_message_path,
                file_url_path=bot.file_url_path,
                upload_path=bot.upload_path,
            )
            adapter = TailchatPlatformAdapter(adapter_config, event_callback=self.router.route_incoming)
            self.adapters[bot.bot_key] = adapter
        bot_callbacks = [
            BotCallbackConfig(
                bot_key=bot.bot_key,
                callback_path=bot.callback_path,
                callback_token=bot.callback_token,
                adapter=self.adapters[bot.bot_key],
            )
            for bot in bots
        ]
        self.server = TailchatCallbackServer(bot_callbacks, server_config, security_config)


def plugin_entry(*args: Any, **kwargs: Any) -> TailchatPlugin:
    plugin = TailchatPlugin(*args, **kwargs)
    plugin.start()
    return plugin


def load_config(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def build_bot_configs(config_data: dict[str, Any]) -> tuple[list[BotConfig], ServerConfig, SecurityConfig]:
    normalized = normalize_config(config_data)
    server_cfg = normalized.get("server", {})
    security_cfg = normalized.get("security", {})
    bots_data = normalized.get("tailchat", {}).get("bots", [])
    defaults = normalized.get("defaults", {})

    server_config = ServerConfig(
        listen_host=server_cfg.get("listen_host", "0.0.0.0"),
        listen_port=server_cfg.get("listen_port", 8088),
    )
    security_config = SecurityConfig(
        allow_ips=security_cfg.get("allow_ips", []),
        enable_body_hash=security_cfg.get("enable_body_hash", False),
        body_hash_header=security_cfg.get("body_hash_header", "X-Body-Hash"),
    )

    base_features = {
        "require_mention": True,
        "attachment_mode": "url_only",
        "download_dir": defaults.get("download_dir", "./data/tailchat_downloads"),
        "max_attachment_mb": defaults.get("max_attachment_mb", 50),
        "session_key_template": defaults.get("session_key_template", "{botKey}:{groupId}:{converseId}"),
    }

    tailchat_defaults = normalized.get("tailchat", {})
    bots: list[BotConfig] = []
    for index, bot_data in enumerate(bots_data):
        bot_key = bot_data.get("bot_key") or f"bot_{index + 1}"
        features = {**base_features, **bot_data.get("features", {})}
        callback = bot_data.get("callback", {})
        astrbot_cfg = bot_data.get("astrbot", {}) or {}
        bots.append(
            BotConfig(
                bot_key=bot_key,
                host=bot_data.get("host") or tailchat_defaults.get("host", "https://tailchat.msgbyte.com"),
                app_id=bot_data.get("app_id") or tailchat_defaults.get("app_id", ""),
                app_secret=bot_data.get("app_secret") or tailchat_defaults.get("app_secret", ""),
                bot_user_id=bot_data.get("bot_user_id") or tailchat_defaults.get("bot_user_id"),
                callback_path=callback.get("path", "/tailchat/callback"),
                callback_token=callback.get("token"),
                features=features,
                openapi_base=bot_data.get("openapi_base") or tailchat_defaults.get("openapi_base", "/api/openapi"),
                login_path=bot_data.get("login_path") or tailchat_defaults.get("login_path", "/bot/login"),
                send_message_path=bot_data.get("send_message_path")
                or tailchat_defaults.get("send_message_path", "/bot/sendMessage"),
                file_url_path=bot_data.get("file_url_path") or tailchat_defaults.get("file_url_path", "/bot/file"),
                upload_path=bot_data.get("upload_path") or tailchat_defaults.get("upload_path", "/bot/upload"),
                astrbot=AstrBotRouteConfig(
                    mode=astrbot_cfg.get("mode", "profile"),
                    profile_id=astrbot_cfg.get("profile_id"),
                    backend_url=astrbot_cfg.get("backend_url"),
                ),
            )
        )

    return bots, server_config, security_config


def normalize_config(config_data: dict[str, Any]) -> dict[str, Any]:
    if "tailchat" not in config_data:
        return config_data
    tailchat = config_data.get("tailchat", {})
    bots = tailchat.get("bots")
    if bots:
        return config_data
    if tailchat.get("app_id") or tailchat.get("app_secret"):
        server_cfg = config_data.get("server", {})
        security_cfg = config_data.get("security", {})
        features = config_data.get("features", {})
        mapping = config_data.get("mapping", {})
        config_data = {
            **config_data,
            "defaults": {
                "download_dir": features.get("download_dir", "./data/tailchat_downloads"),
                "max_attachment_mb": features.get("max_attachment_mb", 50),
                "session_key_template": mapping.get("session_key_template", "{botKey}:{groupId}:{converseId}"),
            },
            "tailchat": {
                **tailchat,
                "bots": [
                    {
                        "bot_key": "default",
                        "host": tailchat.get("host", "https://tailchat.msgbyte.com"),
                        "app_id": tailchat.get("app_id", ""),
                        "app_secret": tailchat.get("app_secret", ""),
                        "bot_user_id": tailchat.get("bot_user_id"),
                        "callback": {
                            "path": server_cfg.get("callback_path", "/tailchat/callback"),
                            "token": security_cfg.get("callback_token"),
                        },
                        "features": {
                            "require_mention": features.get("require_mention", True),
                            "attachment_mode": features.get("attachment_mode", "url_only"),
                        },
                        "astrbot": {
                            "mode": "profile",
                            "profile_id": tailchat.get("profile_id"),
                        },
                    }
                ],
            },
        }
    return config_data
