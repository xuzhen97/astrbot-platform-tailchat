from __future__ import annotations

from typing import Any, Optional

from .types import Attachment, IncomingMessage, ReplyInfo


def _get_first(obj: dict[str, Any], paths: list[str]) -> Any:
    for p in paths:
        cur: Any = obj
        ok = True
        for part in p.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur not in (None, ""):
            return cur
    return None


def parse_incoming(payload: dict[str, Any], config: dict[str, Any]) -> Optional[IncomingMessage]:
    typ = payload.get("type") or payload.get("event") or _get_first(payload, ["data.type"])
    if typ and typ != "message":
        return None

    p = payload.get("payload") or payload.get("data") or payload

    group_id = _get_first(p, ["groupId", "group_id", "group.id"])
    converse_id = _get_first(p, ["converseId", "converse_id", "panelId", "panel_id"])
    message_id = _get_first(p, ["messageId", "_id", "id"])

    sender_id = _get_first(p, ["messageAuthor", "author", "sender.userId", "sender._id", "userId"])
    sender_name = _get_first(p, ["messageAuthorName", "sender.nickname", "sender.name", "authorName", "username"]) or str(sender_id or "")

    text = _get_first(p, ["messageSnippet", "content", "plain", "text"]) or ""

    features = (config.get("features") or {})
    require_mention = bool(features.get("require_mention", True))
    if require_mention:
        mentions = _get_first(p, ["mentions", "meta.mentions"])
        if isinstance(mentions, list) and len(mentions) == 0:
            return None

    atts: list[Attachment] = []
    raw_files = _get_first(p, ["files", "attachments", "meta.files", "meta.attachments"])
    if isinstance(raw_files, list):
        for f in raw_files:
            if not isinstance(f, dict):
                continue
            url = f.get("url") or f.get("src") or f.get("downloadUrl") or ""
            name = f.get("name") or f.get("filename") or "file"
            mime = f.get("mime") or f.get("type") or ""
            size = int(f.get("size") or 0)
            kind = "image" if (mime.startswith("image/") or name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))) else "file"
            if url:
                atts.append(Attachment(name=name, url=url, mime=mime, size_bytes=size, kind=kind))

    reply = None
    reply_obj = _get_first(p, ["meta.reply", "reply"])
    if isinstance(reply_obj, dict):
        rid = reply_obj.get("_id") or reply_obj.get("id") or ""
        rauthor = reply_obj.get("author") or ""
        rcontent = reply_obj.get("content") or ""
        if rid:
            reply = ReplyInfo(message_id=rid, author_id=rauthor, content=rcontent)

    session_key = f"{group_id}:{converse_id}" if group_id and converse_id else (converse_id or sender_id or "tailchat")

    return IncomingMessage(
        self_id="tailchat-bot",
        group_id=group_id or "",
        converse_id=converse_id or "",
        message_id=message_id or "",
        sender_id=str(sender_id or ""),
        sender_name=str(sender_name or ""),
        text=str(text or ""),
        session_key=session_key,
        attachments=atts,
        reply=reply,
    )
