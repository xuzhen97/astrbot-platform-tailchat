from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .types import Attachment, IncomingMessage, ReplyInfo

SENSITIVE_KEYS = {
    "token",
    "secret",
    "app_secret",
    "appsecret",
    "jwt",
    "authorization",
}


def deep_get(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def get_first(data: Any, paths: Iterable[str], default: Any = None) -> Any:
    value, found = get_first_with_presence(data, paths)
    return value if found else default


def get_first_with_presence(data: Any, paths: Iterable[str]) -> tuple[Any, bool]:
    for path in paths:
        current = data
        valid = True
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                valid = False
                break
        if valid:
            return current, True
    return None, False


def config_get(config: Any, path: str, default: Any = None) -> Any:
    current = config
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
        if current is None:
            return default
    return current


def gen_callback_path(robot_id: str) -> str:
    return f"/tailchat/callback/{robot_id}"


def strip_mention_text(text: str) -> str:
    if not text:
        return text
    cleaned = re.sub(r"<@[^>]+>", " ", text)
    cleaned = re.sub(r"@[^\s]+", " ", cleaned)
    return " ".join(cleaned.split())


def build_incoming_from_payload(payload: dict[str, Any], config: Any, robot_id: str) -> Optional[IncomingMessage]:
    event_type = get_first(payload, ["type", "eventType", "data.type", "payload.type"]) or ""
    if str(event_type).lower() not in {"message", "message.created", "message.create"}:
        return None

    group_id = get_first(payload, ["groupId", "data.groupId", "payload.groupId"])
    converse_id = get_first(payload, ["converseId", "data.converseId", "payload.converseId"])
    if not group_id or not converse_id:
        return None

    message_id = get_first(payload, ["messageId", "_id", "data.messageId", "payload.messageId"])
    content = get_first(
        payload,
        ["content", "text", "data.content", "payload.messageSnippet", "messageSnippet"],
        default="",
    )

    author = get_first(
        payload,
        ["author", "sender", "data.author", "payload.messageAuthor", "messageAuthor"],
        default={},
    )
    sender_id = None
    sender_name = None
    if isinstance(author, dict):
        sender_id = get_first(author, ["userId", "id", "_id"])
        sender_name = get_first(author, ["nickname", "name", "username"])

    mentions, mentions_present = _extract_mentions(payload)
    require_mention = bool(config_get(config, "features.require_mention", True))
    bot_user_id = config_get(config, "tailchat.bot_user_id", None)

    if require_mention:
        if not mentions_present:
            return None
        if bot_user_id:
            if bot_user_id not in mentions:
                return None
        elif not mentions:
            return None

    attachments = _extract_attachments(payload)
    reply = _extract_reply(payload)

    session_template = config_get(config, "defaults.session_key_template", "{groupId}:{converseId}")
    session_key = session_template.format(
        groupId=group_id,
        converseId=converse_id,
        messageId=message_id or "",
        robotId=robot_id,
    )

    clean_text = strip_mention_text(str(content or ""))

    return IncomingMessage(
        text=clean_text,
        attachments=attachments,
        sender_id=sender_id,
        sender_name=sender_name,
        group_id=group_id,
        converse_id=converse_id,
        message_id=message_id,
        mentions=mentions,
        session_key=session_key,
        reply=reply,
        metadata={
            "event_type": event_type,
            "mentions_present": mentions_present,
            "robot_id": robot_id,
        },
    )


def _extract_mentions(payload: dict[str, Any]) -> tuple[list[str], bool]:
    mentions_value, present = get_first_with_presence(
        payload,
        ["mentions", "meta.mentions", "data.meta.mentions", "payload.meta.mentions"],
    )
    if not present or not mentions_value:
        return [], present

    mentions: list[str] = []
    if isinstance(mentions_value, list):
        for item in mentions_value:
            if isinstance(item, str):
                mentions.append(item)
            elif isinstance(item, dict):
                mention_id = get_first(item, ["_id", "id", "userId"])
                if mention_id:
                    mentions.append(str(mention_id))
    return mentions, present


def _extract_attachments(payload: dict[str, Any]) -> list[Attachment]:
    attachments_value = get_first(
        payload,
        ["files", "attachments", "meta.files", "data.meta.files", "payload.meta.files"],
        default=[],
    )
    attachments: list[Attachment] = []
    if not attachments_value:
        return attachments

    for item in attachments_value:
        if not isinstance(item, dict):
            continue
        url = get_first(item, ["url", "src", "downloadUrl"])
        file_id = get_first(item, ["fileId", "file_id", "_id"])
        attachments.append(
            Attachment(
                name=str(get_first(item, ["name", "filename"], default="")),
                mime=get_first(item, ["mime", "mimetype", "type"]),
                size_bytes=get_first(item, ["size", "sizeBytes", "length"]),
                url=url,
                file_id=file_id,
            )
        )
    return attachments


def _extract_reply(payload: dict[str, Any]) -> Optional[ReplyInfo]:
    reply = get_first(payload, ["reply", "meta.reply", "data.meta.reply", "payload.meta.reply"], default=None)
    if not isinstance(reply, dict):
        return None
    author = reply.get("author") if isinstance(reply.get("author"), dict) else {}
    return ReplyInfo(
        message_id=get_first(reply, ["_id", "messageId"]),
        author_id=get_first(author, ["_id", "id", "userId"]),
        author_name=get_first(author, ["nickname", "name"]),
        content=get_first(reply, ["content", "text"]),
    )


def redact_payload(payload: Any) -> Any:
    data = deepcopy(payload)
    return _redact_value(data)


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                redacted[key] = "***"
            else:
                redacted[key] = _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    return key.lower() in SENSITIVE_KEYS


def write_redacted_payload(payload: Any, request_id: str, base_dir: str = "./data/tailchat_payloads") -> None:
    if not request_id:
        return
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    dir_path = os.path.join(base_dir, day)
    os.makedirs(dir_path, exist_ok=True)
    file_path = os.path.join(dir_path, f"{request_id}.json")
    with open(file_path, "w", encoding="utf-8") as handle:
        json.dump(redact_payload(payload), handle, ensure_ascii=False, indent=2)
