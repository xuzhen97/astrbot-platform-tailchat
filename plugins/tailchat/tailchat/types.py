from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Attachment:
    name: str
    mime: Optional[str]
    size_bytes: Optional[int]
    url: Optional[str]
    file_id: Optional[str] = None


@dataclass
class ReplyInfo:
    message_id: Optional[str]
    author_id: Optional[str]
    author_name: Optional[str]
    content: Optional[str]


@dataclass
class IncomingMessage:
    text: str
    attachments: list[Attachment] = field(default_factory=list)
    sender_id: Optional[str] = None
    sender_name: Optional[str] = None
    group_id: Optional[str] = None
    converse_id: Optional[str] = None
    message_id: Optional[str] = None
    mentions: list[str] = field(default_factory=list)
    session_key: Optional[str] = None
    reply: Optional[ReplyInfo] = None
    metadata: dict[str, Any] = field(default_factory=dict)
