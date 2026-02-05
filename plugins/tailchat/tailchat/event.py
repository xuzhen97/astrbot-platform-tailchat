from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .types import IncomingMessage


@dataclass
class TailchatMessageEvent:
    platform: Any
    message: IncomingMessage
    raw: dict[str, Any]
