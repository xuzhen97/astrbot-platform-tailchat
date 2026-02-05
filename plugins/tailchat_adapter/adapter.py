from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .tailchat_api import TailchatAPI
from .types import Attachment, IncomingMessage, ReplyInfo

LOGGER = logging.getLogger(__name__)


@dataclass
class TailchatAdapterConfig:
    host: str
    app_id: str
    app_secret: str
    require_mention: bool = True
    attachment_mode: str = "url_only"
    download_dir: str = "./data/tailchat_downloads"
    max_attachment_mb: int = 50
    session_key_template: str = "{groupId}:{converseId}"
    bot_user_id: Optional[str] = None

    openapi_base: str = "/api/openapi"
    login_path: str = "/bot/login"
    send_message_path: str = "/bot/sendMessage"
    file_url_path: str = "/bot/file"
    upload_path: str = "/bot/upload"


class TailchatPlatformAdapter:
    def __init__(
        self,
        config: TailchatAdapterConfig,
        event_callback: Optional[Callable[[IncomingMessage], None]] = None,
    ) -> None:
        self.config = config
        self.event_callback = event_callback
        self.api = TailchatAPI(
            host=config.host,
            app_id=config.app_id,
            app_secret=config.app_secret,
            openapi_base=config.openapi_base,
            login_path=config.login_path,
            send_message_path=config.send_message_path,
            file_url_path=config.file_url_path,
            upload_path=config.upload_path,
        )

    async def handle_incoming(self, payload: dict[str, Any], request_id: str) -> None:
        try:
            message = self.convert_message(payload)
        except Exception:
            LOGGER.exception("[%s] Failed to convert payload", request_id)
            return

        if message is None:
            return

        if self.event_callback:
            self.event_callback(message)
        else:
            LOGGER.info(
                "[%s] Incoming message (no handler). group=%s converse=%s sender=%s text_len=%s attachments=%s",
                request_id,
                message.group_id,
                message.converse_id,
                message.sender_id,
                len(message.text or ""),
                len(message.attachments),
            )

    def convert_message(self, payload: dict[str, Any]) -> Optional[IncomingMessage]:
        event_type = self._get_first(payload, ["type", "eventType", "data.type"]) or ""
        if str(event_type).lower() not in {"message", "message.created", "message.create"}:
            return None

        group_id = self._get_first(payload, ["groupId", "group_id", "data.groupId"])
        converse_id = self._get_first(payload, ["converseId", "converse_id", "data.converseId"])
        if not group_id or not converse_id:
            LOGGER.warning("Missing groupId or converseId in payload")
            return None

        message_id = self._get_first(payload, ["messageId", "_id", "data.messageId"])
        sender = self._get_first(payload, ["author", "sender", "data.author"], default={})
        sender_id = self._get_first(sender, ["_id", "id", "userId"]) if isinstance(sender, dict) else None
        sender_name = self._get_first(sender, ["nickname", "name", "username"]) if isinstance(sender, dict) else None
        content = self._get_first(payload, ["content", "text", "data.content"], default="")
        mentions, mentions_present = self._extract_mentions(payload)

        if self.config.require_mention and mentions_present:
            if self.config.bot_user_id and self.config.bot_user_id not in mentions:
                return None
            if not self.config.bot_user_id and not mentions:
                return None

        attachments = self._extract_attachments(payload)
        reply = self._extract_reply(payload)

        session_key = self.config.session_key_template.format(
            groupId=group_id, converseId=converse_id, messageId=message_id or ""
        )

        message = IncomingMessage(
            text=str(content or ""),
            attachments=attachments,
            sender_id=sender_id,
            sender_name=sender_name,
            group_id=group_id,
            converse_id=converse_id,
            message_id=message_id,
            session_key=session_key,
            mentions=mentions,
            reply=reply,
            metadata={"raw": payload},
        )

        if self.config.attachment_mode == "download":
            self._download_attachments(message)

        return message

    def send_text(self, message: IncomingMessage, content: str) -> None:
        self.api.send_message(
            group_id=message.group_id,
            converse_id=message.converse_id,
            content=content,
            reply=message.reply,
        )

    def _download_attachments(self, message: IncomingMessage) -> None:
        if not message.attachments:
            return

        os.makedirs(self.config.download_dir, exist_ok=True)
        session_dir = os.path.join(self.config.download_dir, message.session_key or "default")
        os.makedirs(session_dir, exist_ok=True)
        max_bytes = self.config.max_attachment_mb * 1024 * 1024

        for attachment in message.attachments:
            if not attachment.url:
                if attachment.file_id:
                    attachment.url = self.api.resolve_file_url(attachment.file_id)
                if not attachment.url:
                    continue

            try:
                data = self.api.download_file(attachment.url, max_bytes=max_bytes)
            except Exception:
                LOGGER.exception("Failed to download attachment: %s", attachment.url)
                continue

            name = attachment.name or hashlib.md5(attachment.url.encode("utf-8")).hexdigest()
            file_path = os.path.join(session_dir, name)
            with open(file_path, "wb") as handle:
                handle.write(data)
            message.metadata.setdefault("downloaded_files", []).append(file_path)

    def _extract_mentions(self, payload: dict[str, Any]) -> tuple[list[str], bool]:
        mentions_value, present = self._get_first_with_presence(
            payload,
            ["mentions", "meta.mentions", "data.meta.mentions"],
        )
        if not present or not mentions_value:
            return [], present

        mentions: list[str] = []
        if isinstance(mentions_value, list):
            for item in mentions_value:
                if isinstance(item, str):
                    mentions.append(item)
                elif isinstance(item, dict):
                    mention_id = self._get_first(item, ["_id", "id", "userId"])
                    if mention_id:
                        mentions.append(str(mention_id))
        return mentions, present

    def _extract_attachments(self, payload: dict[str, Any]) -> list[Attachment]:
        attachments_value = self._get_first(payload, ["files", "attachments", "meta.files", "data.meta.files"], default=[])
        attachments: list[Attachment] = []
        if not attachments_value:
            return attachments

        for item in attachments_value:
            if not isinstance(item, dict):
                continue
            url = self._get_first(item, ["url", "src", "downloadUrl"])
            file_id = self._get_first(item, ["fileId", "file_id", "_id"])
            attachments.append(
                Attachment(
                    name=str(self._get_first(item, ["name", "filename"], default="")),
                    mime=self._get_first(item, ["mime", "mimetype", "type"]),
                    size_bytes=self._get_first(item, ["size", "sizeBytes", "length"]),
                    url=url,
                    file_id=file_id,
                )
            )
        return attachments

    def _extract_reply(self, payload: dict[str, Any]) -> Optional[ReplyInfo]:
        reply = self._get_first(payload, ["reply", "meta.reply", "data.meta.reply"], default=None)
        if not isinstance(reply, dict):
            return None
        author = reply.get("author") if isinstance(reply.get("author"), dict) else {}
        return ReplyInfo(
            message_id=self._get_first(reply, ["messageId", "_id"]),
            author_id=self._get_first(author, ["_id", "id", "userId"]),
            author_name=self._get_first(author, ["nickname", "name"]).strip() if self._get_first(author, ["nickname", "name"], default="") else None,
            content=self._get_first(reply, ["content", "text"]),
        )

    def _get_first(self, data: Any, paths: list[str], default: Any = None) -> Any:
        value, found = self._get_first_with_presence(data, paths)
        return value if found else default

    def _get_first_with_presence(self, data: Any, paths: list[str]) -> tuple[Any, bool]:
        for path in paths:
            current = data
            valid = True
            for part in path.split("."):
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    valid = False
                    break
            if valid and current not in (None, ""):
                return current, True
            if valid:
                return current, True
        return None, False
