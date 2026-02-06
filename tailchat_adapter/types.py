from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ReplyInfo:
    message_id: str
    author_id: str
    content: str


@dataclass
class Attachment:
    name: str
    url: str
    mime: str = ""
    size_bytes: int = 0
    kind: str = "file"  # image | file


@dataclass
class IncomingMessage:
    self_id: str
    group_id: str
    converse_id: str
    message_id: str
    sender_id: str
    sender_name: str
    text: str
    session_key: str
    attachments: list[Attachment]
    reply: Optional[ReplyInfo] = None
