# astrbot-platform-tailchat 官方对齐修订方案（可直接照搬实现）

> 适用场景：你已经把仓库通过 AstrBot WebUI/插件市场安装进来，但日志提示  
> `插件 <name> 未找到 main.py 或者 <name>.py，跳过。`  
> 并且希望该项目作为 **AstrBot 平台适配器插件**，对接 **Tailchat OpenApp Bot（HTTP 回调）**，支持文本/图片/文件的转发与回复。

本修订方案以两份“官方文档”为准：
- AstrBot 插件开发（新）：要求 `metadata.yaml`、依赖用 `requirements.txt`、并以插件目录作为运行时注入单元。  
  https://docs.astrbot.app/dev/star/plugin-new.html
- AstrBot 平台适配器：要求使用 `@register_platform_adapter`、实现 `Platform` + `AstrMessageEvent.send()` 等规范，并最终在 `main.py` 中 import 适配器模块以触发装饰器注册。  
  https://docs.astrbot.app/en/dev/plugin-platform-adapter.html
- Tailchat OpenApp Bot：HTTP 回调、OpenAPI 登录与 sendMessage 结构。  
  https://tailchat.msgbyte.com/docs/advanced-usage/openapp/bot

---

## 0. 你当前代码的关键问题（必须修）

对你当前仓库（压缩包）审查后，存在以下会导致“安装成功但不加载 / 适配器不工作”的问题：

### 0.1 插件入口不符合 AstrBot Loader 规则（导致直接跳过）
AstrBot 插件加载器会在插件根目录找：
- `main.py` 或
- `<插件目录名>.py`  
找不到就 `skip`（你日志已证实）。

你当前把入口放在 `plugins/tailchat/__init__.py`，并用 `plugin.yaml` 指向 `plugins.tailchat:plugin_entry`。  
但 AstrBot loader **不会**读取 `plugin.yaml` 来找入口（至少在你当前版本的安装/加载链路中就是如此），因此直接跳过。

### 0.2 事件类型不符合 AstrBot 平台适配器规范（即使加载也无法工作）
你当前的 `TailchatMessageEvent` 是一个 `dataclass`，不是 `AstrMessageEvent` 子类，因此：
- `commit_event()` 进入 AstrBot pipeline 的时候会缺关键属性/方法
- `send()` 机制无法工作（无法把模型回复发回 Tailchat）

### 0.3 HTTP 回调路径与 Tailchat OpenApp 固定回调不匹配（容易配置错）
你当前 FastAPI 路由是：
`/tailchat/callback/{robot_id}`  
而 Tailchat OpenApp 的 callback URL 是固定配置的一条 URL（通常为 `/tailchat/callback`）。  
除非你明确把 callback URL 配成带 robot_id 的路径，否则不会命中。

### 0.4 FastAPI/回调线程与 AstrBot 主事件循环跨 loop 调用有风险
你当前在 uvicorn 线程里 `asyncio.create_task(platform.on_callback(payload))`。  
这会在 **uvicorn 的 event loop** 中执行，而 AstrBot 平台/队列通常属于 **AstrBot 主 loop**，跨 loop 可能出现：
- 队列不是同一个 loop 创建，抛错或 silently fail
- 并发时状态错乱

---

## 1. 修订后的“正确目标结构”（必须按这个来）

将仓库根目录改为 AstrBot 插件根目录（解压后就是 `/AstrBot/data/plugins/<插件目录>/`）：

```
astrbot-platform-tailchat/
  main.py                         # ✅ AstrBot loader 必需
  astrbot_platform_tailchat.py     # ✅ 可选：兼容性兜底（同名入口）
  metadata.yaml                   # ✅ AstrBot 插件新规范
  requirements.txt                # ✅ 依赖声明（httpx/fastapi/uvicorn 等）
  README.md
  config.example.yaml             # 默认配置模板（给用户抄）
  tailchat_adapter/               # 你的实际代码包（随便命名，但建议清晰）
    __init__.py
    platform.py                   # Platform 适配器（@register_platform_adapter）
    event.py                      # AstrMessageEvent 子类（send 实现）
    api.py                        # Tailchat OpenAPI（async httpx）
    server.py                     # FastAPI server（回调入口）
    parse.py                      # payload 解析 & 附件抽象
    types.py
```

> **注意**：你现在仓库里 `plugins/tailchat/...` 这一层要去掉。插件根就是仓库根。

---

## 2. 必改文件与可直接复制的内容（照抄即可）

下面给出“可完全照搬”的文件内容。你可以直接按本节重建目录。

### 2.1 `metadata.yaml`（新插件规范，必须）
放在仓库根目录：

```yaml
id: astrbot-platform-tailchat
display_name: "AstrBot Platform – Tailchat"
version: 0.2.0
author: xuzhen97
description: "Tailchat OpenApp Bot platform adapter for AstrBot (HTTP callback)."
repository: "https://github.com/xuzhen97/astrbot-platform-tailchat"
license: MIT
```

---

### 2.2 `requirements.txt`（必须）
放在根目录（AstrBot 会用它安装依赖）：

```txt
fastapi>=0.110
uvicorn>=0.27
httpx>=0.27
pydantic>=2.6
```

---

### 2.3 `main.py`（必须：AstrBot loader 入口）
放在根目录。按 AstrBot 平台适配器官方文档：main.py 里 import 适配器模块以触发装饰器注册。  
同时为了兼容“Star 插件”体系，我们也提供一个最小 Star 类（不会拦截消息，只负责加载）。

```python
from __future__ import annotations

from astrbot.api.star import Context, Star, register


@register(
    "astrbot-platform-tailchat",
    "xuzhen97",
    "Tailchat OpenApp Bot platform adapter for AstrBot",
    "0.2.0",
    "https://github.com/xuzhen97/astrbot-platform-tailchat",
)
class Main(Star):
    def __init__(self, context: Context):
        super().__init__(context)

        # 关键：导入适配器模块以触发 @register_platform_adapter 注册
        from .tailchat_adapter.platform import TailchatPlatform  # noqa: F401
```

---

### 2.4 `astrbot_platform_tailchat.py`（可选但强烈建议）
有些 AstrBot 版本会找 `<目录名>.py`，为了稳，放一个 shim：

```python
from .main import Main  # noqa: F401
```

---

### 2.5 `config.example.yaml`（根目录）
这是用户在 WebUI 里复制/填写的模板（也可被 default_config_tmpl 引用）：

```yaml
tailchat:
  host: "https://tailchat.msgbyte.com"
  app_id: "YOUR_APP_ID"
  app_secret: "YOUR_APP_SECRET"

server:
  listen_host: "0.0.0.0"
  listen_port: 8088
  callback_path: "/tailchat/callback"

security:
  callback_token: "CHANGE_ME"

features:
  require_mention: true
  attachment_mode: "url_only"
  max_attachment_mb: 50
  download_dir: "./data/tailchat_downloads"
```

---

## 3. 平台适配器：按 AstrBot 官方范式重写（必须）

### 3.1 `tailchat_adapter/platform.py`（完整可复制）

```python
from __future__ import annotations

import asyncio
from typing import Any

from astrbot import logger
from astrbot.api.platform import (
    AstrBotMessage,
    MessageMember,
    MessageType,
    Platform,
    PlatformMetadata,
    register_platform_adapter,
)
from astrbot.api.message_components import Plain, Image
from astrbot.api.event import MessageChain

from .api import TailchatAPI
from .parse import parse_incoming
from .server import TailchatCallbackServer
from .types import IncomingMessage
from .event import TailchatAstrMessageEvent


@register_platform_adapter(
    "tailchat",
    "Tailchat OpenApp Bot (HTTP callback)",
    default_config_tmpl="config.example.yaml",
)
class TailchatPlatform(Platform):
    def __init__(
        self,
        platform_config: dict[str, Any],
        platform_settings: dict[str, Any],
        event_queue: asyncio.Queue,
    ) -> None:
        super().__init__(event_queue)

        self.config = platform_config or {}
        self.settings = platform_settings or {}

        host = self.config.get("tailchat", {}).get("host", "https://tailchat.msgbyte.com")
        app_id = self.config.get("tailchat", {}).get("app_id", "")
        app_secret = self.config.get("tailchat", {}).get("app_secret", "")

        self.api = TailchatAPI(host=host, app_id=app_id, app_secret=app_secret)

        srv_cfg = self.config.get("server", {}) or {}
        sec_cfg = self.config.get("security", {}) or {}

        self.callback_path = srv_cfg.get("callback_path", "/tailchat/callback")
        self.listen_host = srv_cfg.get("listen_host", "0.0.0.0")
        self.listen_port = int(srv_cfg.get("listen_port", 8088))

        self.callback_token = sec_cfg.get("callback_token", None)
        self.allow_ips = sec_cfg.get("allow_ips", []) or []

        self._incoming_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        self._server: TailchatCallbackServer | None = None

    def meta(self) -> PlatformMetadata:
        return PlatformMetadata("tailchat", "Tailchat OpenApp Bot (HTTP callback)")

    async def run(self):
        logger.info(
            "[tailchat] callback server at %s:%s%s",
            self.listen_host,
            self.listen_port,
            self.callback_path,
        )
        self._server = TailchatCallbackServer(
            listen_host=self.listen_host,
            listen_port=self.listen_port,
            callback_path=self.callback_path,
            callback_token=self.callback_token,
            allow_ips=self.allow_ips,
            enqueue=self._enqueue_payload_threadsafe,
        )
        self._server.start()

        while True:
            payload = await self._incoming_queue.get()
            try:
                incoming = parse_incoming(payload, self.config)
                if incoming is None:
                    continue
                abm = await self.convert_message(incoming=incoming, raw=payload)
                await self.handle_msg(abm, incoming=incoming, raw=payload)
            except Exception as e:
                logger.exception("[tailchat] failed to handle payload: %s", e)

    def _enqueue_payload_threadsafe(self, payload: dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(self._incoming_queue.put_nowait, payload)

    async def convert_message(self, incoming: IncomingMessage, raw: dict[str, Any]) -> AstrBotMessage:
        abm = AstrBotMessage()
        abm.type = MessageType.GROUP_MESSAGE if incoming.group_id else MessageType.FRIEND_MESSAGE
        abm.group_id = incoming.group_id or ""
        abm.self_id = incoming.self_id or "tailchat-bot"
        abm.session_id = incoming.session_key
        abm.message_id = incoming.message_id
        abm.raw_message = raw

        abm.sender = MessageMember(user_id=incoming.sender_id, nickname=incoming.sender_name)

        abm.message_str = incoming.text or ""
        chain = [Plain(text=abm.message_str)] if abm.message_str else []

        for att in incoming.attachments:
            if att.kind == "image" and att.url:
                chain.append(Image(file=att.url))
            elif att.url:
                chain.append(Plain(text=f"\n[File] {att.name} {att.url}"))

        abm.message = chain
        return abm

    async def handle_msg(self, message: AstrBotMessage, incoming: IncomingMessage, raw: dict[str, Any]) -> None:
        event = TailchatAstrMessageEvent(
            message_str=message.message_str,
            message_obj=message,
            platform_meta=self.meta(),
            session_id=message.session_id,
            platform=self,
            incoming=incoming,
            raw=raw,
        )
        self.commit_event(event)

    async def send_by_session(self, session, message_chain: MessageChain):
        await super().send_by_session(session, message_chain)

    async def send_text(self, group_id: str, converse_id: str, text: str, reply_to: dict[str, Any] | None = None):
        return await self.api.send_message(group_id=group_id, converse_id=converse_id, content=text, reply=reply_to)

    async def terminate(self):
        if self._server:
            self._server.stop()
        await self.api.close()
```

---

### 3.2 `tailchat_adapter/event.py`（AstrMessageEvent 子类：必须）

```python
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
```

---

## 4. Tailchat 回调 Server：固定路径 + token 校验（必须）

### 4.1 `tailchat_adapter/server.py`（完整可复制）

```python
from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Callable, Iterable

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class TailchatCallbackServer:
    def __init__(
        self,
        listen_host: str,
        listen_port: int,
        callback_path: str,
        callback_token: str | None,
        allow_ips: Iterable[str],
        enqueue: Callable[[dict[str, Any]], None],
    ) -> None:
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.callback_path = callback_path
        self.callback_token = callback_token
        self.allow_ips = set([ip for ip in allow_ips if ip])
        self.enqueue = enqueue

        self._app = FastAPI()
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

        self._mount_routes()

    def _mount_routes(self) -> None:
        path = self.callback_path if self.callback_path.startswith("/") else ("/" + self.callback_path)

        @self._app.post(path)
        async def callback(request: Request) -> JSONResponse:
            request_id = str(uuid.uuid4())

            if self.allow_ips and request.client and request.client.host not in self.allow_ips:
                return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

            if self.callback_token:
                q = request.query_params.get("token")
                if q != self.callback_token:
                    return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

            raw_body = await request.body()
            try:
                payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except json.JSONDecodeError:
                return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)

            try:
                self.enqueue(payload)
            except Exception:
                return JSONResponse({"ok": True, "queued": False, "request_id": request_id})

            return JSONResponse({"ok": True, "queued": True, "request_id": request_id})

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        config = uvicorn.Config(self._app, host=self.listen_host, port=self.listen_port, log_level="info")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
```

---

## 5. Tailchat OpenAPI：按官方文档实现（async 版）

### 5.1 `tailchat_adapter/api.py`（完整可复制）

```python
from __future__ import annotations

import hashlib
from typing import Any, Optional

import httpx


class TailchatAPI:
    def __init__(self, host: str, app_id: str, app_secret: str) -> None:
        self.host = host.rstrip("/")
        self.app_id = app_id
        self.app_secret = app_secret
        self._jwt: Optional[str] = None
        self._client = httpx.AsyncClient(timeout=15)

    async def login(self) -> str:
        token = hashlib.md5(f"{self.app_id}{self.app_secret}".encode("utf-8")).hexdigest()
        resp = await self._client.post(
            f"{self.host}/api/openapi/bot/login",
            json={"appId": self.app_id, "token": token},
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        jwt = (data.get("data") or {}).get("jwt") or (data.get("data") or {}).get("token") or data.get("jwt") or data.get("token")
        if not jwt:
            raise RuntimeError(f"Tailchat login: cannot find jwt in response: {data}")
        self._jwt = jwt
        return jwt

    async def send_message(
        self,
        group_id: str,
        converse_id: str,
        content: str,
        reply: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._jwt:
            await self.login()

        payload: dict[str, Any] = {
            "converseId": converse_id,
            "groupId": group_id,
            "content": content,
            "plain": content,
            "meta": {},
        }

        if reply and reply.get("message_id"):
            payload["meta"] = {
                "mentions": [reply.get("author_id")] if reply.get("author_id") else [],
                "reply": {
                    "_id": reply.get("message_id"),
                    "author": reply.get("author_id") or "",
                    "content": reply.get("content") or "",
                },
            }

        resp = await self._client.post(
            f"{self.host}/api/chat/message/sendMessage",
            json=payload,
            headers={"Content-Type": "application/json", "X-Token": self._jwt or ""},
        )

        if resp.status_code in (401, 403):
            await self.login()
            resp = await self._client.post(
                f"{self.host}/api/chat/message/sendMessage",
                json=payload,
                headers={"Content-Type": "application/json", "X-Token": self._jwt or ""},
            )

        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()
```

---

## 6. Tailchat payload 解析：容错（必须）

### 6.1 `tailchat_adapter/types.py`

```python
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
```

### 6.2 `tailchat_adapter/parse.py`

```python
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
```

---

## 7. 迁移步骤（对你现有仓库的最短路径）

1. **重构目录**：删掉 `plugins/` 这一层，把代码包挪到根目录下 `tailchat_adapter/`
2. **新增根文件**：`main.py`、`metadata.yaml`、`requirements.txt`、`config.example.yaml`
3. **覆盖实现**：用本文件中的 `platform.py/event.py/server.py/api.py/parse.py/types.py` 覆盖旧实现
4. 推送到 GitHub 默认分支
5. 在 AstrBot 中删除插件目录后重装（或卸载后重装）
6. Tailchat OpenApp Bot callback URL 填：  
   `https://<你的公网域名>/tailchat/callback?token=CHANGE_ME`

---

## 8. 验收清单（必须全部通过）

- [ ] 不再出现 “未找到 main.py…跳过”
- [ ] 平台列表出现 `tailchat`
- [ ] Tailchat 群 @bot 文本 -> AstrBot 回复成功
- [ ] Tailchat 图片 -> AstrBot message chain 能看到 Image(url)（第一版以 URL 透传）
- [ ] Tailchat 文件 -> AstrBot 收到文件 URL（Plain 链接）并回复
- [ ] sendMessage 401/403 时能自动重登重试

