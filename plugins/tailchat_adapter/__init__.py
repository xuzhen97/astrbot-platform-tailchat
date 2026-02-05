from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from .adapter import TailchatAdapterConfig, TailchatPlatformAdapter
from .server import SecurityConfig, ServerConfig, TailchatCallbackServer

LOGGER = logging.getLogger(__name__)


def load_config(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def build_adapter(config_data: dict[str, Any]) -> TailchatPlatformAdapter:
    tailchat = config_data.get("tailchat", {})
    features = config_data.get("features", {})
    mapping = config_data.get("mapping", {})

    adapter_config = TailchatAdapterConfig(
        host=tailchat.get("host", "https://tailchat.msgbyte.com"),
        app_id=tailchat.get("app_id", ""),
        app_secret=tailchat.get("app_secret", ""),
        require_mention=features.get("require_mention", True),
        attachment_mode=features.get("attachment_mode", "url_only"),
        download_dir=features.get("download_dir", "./data/tailchat_downloads"),
        max_attachment_mb=features.get("max_attachment_mb", 50),
        session_key_template=mapping.get("session_key_template", "{groupId}:{converseId}"),
        bot_user_id=tailchat.get("bot_user_id"),
        openapi_base=tailchat.get("openapi_base", "/api/openapi"),
        login_path=tailchat.get("login_path", "/bot/login"),
        send_message_path=tailchat.get("send_message_path", "/bot/sendMessage"),
        file_url_path=tailchat.get("file_url_path", "/bot/file"),
        upload_path=tailchat.get("upload_path", "/bot/upload"),
    )
    return TailchatPlatformAdapter(adapter_config)


def build_server(
    adapter: TailchatPlatformAdapter,
    config_data: dict[str, Any],
) -> TailchatCallbackServer:
    server_cfg = config_data.get("server", {})
    security_cfg = config_data.get("security", {})

    server_config = ServerConfig(
        listen_host=server_cfg.get("listen_host", "0.0.0.0"),
        listen_port=server_cfg.get("listen_port", 8088),
        callback_path=server_cfg.get("callback_path", "/tailchat/callback"),
    )
    security_config = SecurityConfig(
        callback_token=security_cfg.get("callback_token"),
        allow_ips=security_cfg.get("allow_ips", []),
        enable_body_hash=security_cfg.get("enable_body_hash", False),
    )
    return TailchatCallbackServer(adapter, server_config, security_config)
