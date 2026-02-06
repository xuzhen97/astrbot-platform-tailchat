from __future__ import annotations

from typing import Any

from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import Plain, Image

from .types import IncomingMessage


class TailchatAstrMessageEvent(AstrMessageEvent):
    def __init__(
        self,
        message_str: str,
        message_obj,
        platform_meta,
        session_id: str,
        platform: Any,
        incoming: IncomingMessage,
        raw: dict[str, Any],
    ) -> None:
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.platform = platform
        self.incoming = incoming
        self.raw = raw

    async def send(self, message: MessageChain):
        reply_to = None
        if self.incoming.reply:
            reply_to = {
                "message_id": self.incoming.reply.message_id,
                "author_id": self.incoming.reply.author_id,
                "content": self.incoming.reply.content,
            }

        out_text = []
        for seg in message.chain:
            if isinstance(seg, Plain):
                out_text.append(seg.text)
            elif isinstance(seg, Image):
                if seg.file:
                    out_text.append(seg.file)

        text = "\n".join([t for t in out_text if t]).strip()
        if not text:
            text = "\u200b"

        await self.platform.send_text(
            group_id=self.incoming.group_id,
            converse_id=self.incoming.converse_id,
            text=text,
            reply_to=reply_to,
        )

        await super().send(message)
