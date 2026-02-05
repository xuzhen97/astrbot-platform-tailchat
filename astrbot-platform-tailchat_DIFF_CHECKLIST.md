# Diff 清单：将当前仓库修改为“按 AstrBot 官方多机器人实例工作流接入 Tailchat”的版本

> 目标：让 `astrbot-platform-tailchat` 作为 **Platform Adapter（通用适配器代码）** 被 AstrBot 官方机制加载；  
> 通过 **AstrBot UI 创建多个机器人实例** 来天然隔离模型/知识库；  
> 适配器只做“平台接入”，不再在适配器配置里维护 bots[]。  
>
> 说明：本 Diff 以你当前 zip 的仓库结构为基准：
> ```
> plugins/tailchat_adapter/
>   __init__.py
>   adapter.py
>   server.py
>   tailchat_api.py
>   types.py
>   config.example.yaml
> ```
> 改造后将对齐你要求的“官方思路”：**多个 Tailchat bot = 多个 AstrBot 机器人实例**（各自有独立 config 与模型/知识库）。

---

## 0) 总体变更摘要（一定要做的点）

- [ADD] 引入 AstrBot 官方平台适配器入口：`Platform` 子类 + `@register_platform_adapter(...)`
- [ADD] 进程级 **HTTP Server 单例** + `robot_id -> platform_instance` 注册表（避免多实例端口冲突）
- [MOD] Callback Path **自动生成**：`/tailchat/callback/{robot_id}`
- [MOD] Tailchat OpenAPI 路径对齐官方：
  - login: `/api/openapi/bot/login`
  - sendMessage: `/api/chat/message/sendMessage`
- [MOD] 回调 payload 解析补齐官方字段：`messageSnippet` / `messageAuthor`
- [MOD] mention：`require_mention` 强制生效 + strip @bot 文本
- [DEL] 删除/废弃“适配器内多机器人(bots[])”设计（你当前实现里没有，但需确保后续不引入）
- [MOD] README：明确“多机器人隔离由 AstrBot UI 多实例完成”

---

## 1) 目录结构 Diff（文件移动/新增）

### 1.1 [ADD] 新目录与文件
在 `plugins/` 下新增一个**标准插件包**（建议命名 `tailchat`，避免 `tailchat_adapter` 与内部模块混淆）：

```
plugins/
  tailchat/
    plugin.yaml                 # AstrBot 插件清单（或 manifest）
    __init__.py                 # 插件入口（仅负责导入 platform 以触发注册）
    config.example.yaml         # 单实例配置模板（与 UI 字段一致）
    tailchat/
      __init__.py
      platform.py               # ★ Platform Adapter（核心）
      event.py                  # ★ 平台事件
      server_singleton.py       # ★ HTTP Server 单例 + 路由
      registry.py               # ★ robot_id -> platform_instance
      tailchat_api.py           # OpenAPI 客户端（从现有迁移并修正路径）
      types.py                  # 从现有迁移
      utils.py                  # deep_get/get_first/mention strip/redact
```

### 1.2 [MOVE] 迁移现有文件内容
将你现有 `plugins/tailchat_adapter/*.py` 迁移到新包内，并按下文修改：
- `adapter.py` → 合并进 `platform.py`（或保留为 helper，但 platform 必须是入口）
- `server.py` → 拆为 `server_singleton.py` + `registry.py`
- `tailchat_api.py` → 移到 `tailchat/tailchat_api.py`
- `types.py` → 移到 `tailchat/types.py`
- `config.example.yaml` → 移到 `plugins/tailchat/config.example.yaml`
- `plugins/tailchat_adapter/README.md` → 合并进根 README 或迁到 `plugins/tailchat/README.md`

### 1.3 [DEL] 清理旧目录
- [DEL] `plugins/tailchat_adapter/`（迁移完成后删除，避免重复加载/歧义）
- [DEL] `plugins/__init__.py`（如无其他用途可删除；保留也不影响）

---

## 2) AstrBot 插件/平台注册（对齐官方）——关键 Diff

> ⚠️ 这里存在 AstrBot 版本差异的唯一不确定点：  
> `Platform` / `register_platform_adapter` 的 import 路径与 `robot_id` 获取方式在不同版本可能不同。  
> 你需要按你实际 AstrBot 版本调整 import（但代码结构不变）。  
> 下述写法按官方文档示例风格编排。

### 2.1 [ADD] plugins/tailchat/plugin.yaml
新增 `plugins/tailchat/plugin.yaml`，用于让 AstrBot 发现该插件。

> 字段名可能随 AstrBot 版本略有差异（有的版本不需要 plugin.yaml，而是通过 Python entrypoint 自动发现）。  
> 若你使用的 AstrBot 版本明确要求 manifest，请按其规范填字段；否则保留此文件不影响。

建议内容（如 AstrBot 支持）：
```yaml
id: "astrbot-platform-tailchat"
name: "AstrBot Platform Tailchat"
version: "0.1.0"
entry: "plugins.tailchat:plugin_entry"
description: "Tailchat OpenApp Bot platform adapter for AstrBot"
author: "xuzhen97"
license: "MIT"
```

### 2.2 [ADD] plugins/tailchat/__init__.py
新增入口文件，仅用于触发 platform 注册：

```python
def plugin_entry():
    # 导入 platform 触发 @register_platform_adapter
    from .tailchat.platform import TailchatPlatform  # noqa: F401
```

### 2.3 [ADD] plugins/tailchat/tailchat/platform.py（核心）
新增 `TailchatPlatform`，继承 AstrBot `Platform`，并用 `@register_platform_adapter` 注册。

必须实现：
- `__init__`：读取本机器人实例配置，创建 TailchatAPI，注册到 registry，并确保 server 单例启动
- `handle_incoming_payload(payload)`：将 Tailchat payload 转换为 AstrBot 事件并 `commit_event()`
- `send_text(...)`：把 AstrBot 回复发回 Tailchat（通过 TailchatAPI）

伪结构（按你们 AstrBot 版本填真实 API）：
```python
from astrbot.api.platform import Platform, register_platform_adapter
from .event import TailchatMessageEvent
from .server_singleton import ensure_server_started
from .registry import registry
from .tailchat_api import TailchatAPI
from .utils import build_incoming_from_payload, gen_callback_path

@register_platform_adapter("tailchat", "Tailchat OpenApp Bot", default_config_tmpl="config.example.yaml")
class TailchatPlatform(Platform):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.robot_id = self.get_robot_id_safe()  # 见 2.4
        self.config = self.load_platform_config() # AstrBot 标准读取方式
        self.callback_path = gen_callback_path(self.robot_id)

        self.api = TailchatAPI(
            host=self.config.tailchat.host,
            app_id=self.config.tailchat.app_id,
            app_secret=self.config.tailchat.app_secret,
        )

        ensure_server_started(listen_host=..., listen_port=...)
        registry.register(self.robot_id, self)

    async def on_callback(self, payload: dict):
        incoming = build_incoming_from_payload(payload, self.config, self.robot_id)
        if incoming is None:
            return
        event = TailchatMessageEvent(platform=self, message=incoming.astrbot_message, raw=payload)
        self.commit_event(event)

    async def send_text(self, group_id: str, converse_id: str, text: str, reply_to: dict | None = None):
        await self.api.send_message(group_id, converse_id, text, reply_to=reply_to)
```

### 2.4 [ADD] “robot_id 获取”兼容函数（不确定点的处理）
在 `platform.py` 中添加兼容实现，避免你需要和我确认 AstrBot 版本：

```python
def get_robot_id_safe(self) -> str:
    # 优先使用 AstrBot 提供的稳定 robot_id
    for attr in ("robot_id", "id", "bot_id", "instance_id"):
        v = getattr(self, attr, None)
        if isinstance(v, str) and v:
            return v
    # 如果 AstrBot 只提供“机器人名称”，用名称兜底（可能不唯一，强烈建议使用官方 id）
    name = getattr(self, "name", None) or getattr(self, "robot_name", None)
    if isinstance(name, str) and name:
        return name
    # 最终兜底：生成 UUID（会导致回调 path 不稳定，不推荐）
    import uuid
    return str(uuid.uuid4())
```

> ✅ 这段代码让你无需确认 AstrBot 版本也能先跑起来；  
> ⚠️ 最佳做法是替换成你 AstrBot 版本提供的“稳定实例 ID”。

---

## 3) Callback Path 自动生成（有规律，自动生成）

### 3.1 [ADD] plugins/tailchat/tailchat/utils.py
添加：
```python
def gen_callback_path(robot_id: str) -> str:
    return f"/tailchat/callback/{robot_id}"
```

### 3.2 [MOD] Tailchat 回调路由
采用统一路由：
- `POST /tailchat/callback/{robot_id}?token=...`

Tailchat 侧配置 Callback URL 时：
- 每个 AstrBot 机器人实例会显示/输出自己的回调 URL（见 README/日志输出）

---

## 4) HTTP Server 单例 + Registry（多机器人实例不冲突）

### 4.1 [ADD] plugins/tailchat/tailchat/registry.py
```python
class TailchatRegistry:
    def __init__(self):
        self._map = {}  # robot_id -> TailchatPlatform
    def register(self, robot_id, platform):
        self._map[robot_id] = platform
    def get(self, robot_id):
        return self._map.get(robot_id)

registry = TailchatRegistry()
```

### 4.2 [ADD] plugins/tailchat/tailchat/server_singleton.py
- 用 FastAPI/aiohttp 建一个进程级 server
- 只启动一次（模块级 singleton）
- 提供 `ensure_server_started(...)`
- 路由：`/tailchat/callback/{robot_id}`

关键点：
- token 校验按“该 robot 实例的配置”校验（每个实例自己的 token）
- 校验失败必须返回 JSONResponse（不能 `return None`）
- 回调处理必须 `asyncio.create_task(platform.on_callback(payload))` 后立刻 200

---

## 5) Tailchat OpenAPI 对齐官方（必须改的 Diff）

### 5.1 [MOD] 迁移并修改 tailchat_api.py
将 `plugins/tailchat_adapter/tailchat_api.py` 移到 `plugins/tailchat/tailchat/tailchat_api.py` 并做以下修改：

#### 5.1.1 [MOD] 默认 API 路径
- login：固定为 `/api/openapi/bot/login`
- sendMessage：固定为 `/api/chat/message/sendMessage`（★关键）
- file url：如你需要 file API，保留可配置，但不要默认指向不存在的 openapi 路径

建议实现：
```python
LOGIN_PATH = "/api/openapi/bot/login"
SEND_MESSAGE_PATH = "/api/chat/message/sendMessage"
```

#### 5.1.2 [MOD] 401/403 自动重登 + 重试一次
你现有实现若已做，保留；否则加：
- send_message 遇到 401/403：
  - self.login()
  - retry once

#### 5.1.3 [MOD] reply meta 字段对齐官方示例
官方示例 reply 使用 `_id` 字段（而不是 `messageId`）：
```json
"reply": {"_id": "...", "author": "...", "content": "..."}
```
你的实现需统一为 `_id`。

---

## 6) Tailchat 回调 payload 解析（对齐官方字段 + 兼容 fallback）

### 6.1 [MOD] types.py：补齐 IncomingMessage 字段
建议结构：
- group_id, converse_id, message_id
- sender_id, sender_name
- text
- mentions(list[str])
- attachments(list[Attachment])
- session_key
- reply(optional: dict)
- metadata(dict)

### 6.2 [ADD] utils.py：deep_get / get_first
必须实现：
- 点路径访问：`data.groupId`
- 多候选字段 fallback

### 6.3 [MOD] payload 字段候选（必须包含官方字段）
在 `build_incoming_from_payload()` 里：
- group_id candidates: `["groupId","data.groupId","payload.groupId"]`
- converse_id: `["converseId","data.converseId","payload.converseId"]`
- message_id: `["messageId","_id","data.messageId","payload.messageId"]`
- content/text: `["content","text","data.content","payload.messageSnippet","messageSnippet"]` ★
- author: `["author","sender","data.author","payload.messageAuthor","messageAuthor"]` ★

并兼容 author 是 dict 的情况：
- sender_id candidates: `["userId","id","_id"]`
- sender_name: `["nickname","name","username"]`

---

## 7) mention 逻辑（必须修复）

### 7.1 [MOD] require_mention 强制生效
规则：
- 如果 `require_mention=true`：
  - 若 payload 没 mentions 字段：视为未 mention → 忽略
  - 若配置了 `bot_user_id`：mentions 必须包含该 id
  - 若未配置 bot_user_id：只要 mentions 非空才算 mention（弱校验）

### 7.2 [ADD] strip_mention_text
实现对常见格式的剥离（保守）：
- `<@xxxx>` 形式
- `@BotName` 形式
- 多空格处理

在传入 AstrBot 前清洗 text。

---

## 8) README 与运行方式 Diff（让用户按官方 UI 用）

### 8.1 [MOD] README.md（根目录与插件 README）
必须写清：
- “多机器人隔离”的官方用法：在 AstrBot UI 创建多个机器人实例，每个实例都选 Tailchat 平台并绑定不同配置文件（模型/知识库不同）
- 回调 URL 的展示方式：
  - 启动时日志打印：`Callback URL: https://<domain>/tailchat/callback/{robot_id}?token=...`
- 部署要求：
  - 单端口 server
  - HTTPS / 反向代理
  - ngrok 调试

---

## 9) 逐文件 Diff 指令（给 Code Agent 的执行顺序）

### Step A：新增新插件目录
- [ADD] `plugins/tailchat/` + 子目录结构（见 1.1）

### Step B：迁移现有实现
- [MOVE] `plugins/tailchat_adapter/tailchat_api.py` → `plugins/tailchat/tailchat/tailchat_api.py`
- [MOVE] `plugins/tailchat_adapter/types.py` → `plugins/tailchat/tailchat/types.py`
- [MOVE] `plugins/tailchat_adapter/server.py` → 拆解实现到 `server_singleton.py`/`registry.py`
- [MOVE] `plugins/tailchat_adapter/adapter.py` → 合并/重写为 `platform.py`（必须继承 Platform + 注册）

### Step C：修改 TailchatAPI 路径与 reply meta
- [MOD] sendMessage path 改为 `/api/chat/message/sendMessage`
- [MOD] reply meta `_id` 字段
- [MOD] 401/403 重登

### Step D：实现 server 单例与 callback path 自动生成
- [ADD] registry
- [ADD] server_singleton
- [ADD] utils.gen_callback_path

### Step E：完善 payload 解析与 mention 处理
- [ADD] deep_get/get_first
- [MOD] 加 `messageSnippet`/`messageAuthor` fallback
- [MOD] require_mention + strip

### Step F：清理旧目录
- [DEL] `plugins/tailchat_adapter/`（迁移完成后）

---

## 10) 需要你确认的“唯一不确定点”（可选）

> 仅当 Code Agent 在落地时遇到编译错误才需要确认；否则按 2.4 的兼容写法可先跑通。

- 你当前使用的 AstrBot 版本中：
  - `Platform` / `register_platform_adapter` 的准确 import 路径
  - 获取稳定 `robot_id` 的准确 API（例如 `self.ctx.robot_id` / `self.id` / `self.bot_id` 等）

✅ 若你不想确认：使用 2.4 的 `get_robot_id_safe()` 兜底即可跑通；  
⚠️ 但为了 callback path 稳定，最终建议替换为 AstrBot 提供的“稳定实例 id”。

---

## 11) 最终验收（必须全部通过）

1) 在 AstrBot UI 创建两个 Tailchat 机器人实例（不同 appId/appSecret），绑定不同配置文件  
2) 两个机器人实例启动不冲突（同一端口 server 单例）  
3) Tailchat 回调分别打到：
   - `/tailchat/callback/<robot1_id>`
   - `/tailchat/callback/<robot2_id>`
4) 在 Tailchat 中 @ 不同机器人，回复内容体现不同模型/知识库（隔离成功）  
5) login 与 sendMessage 路径符合 Tailchat 官方文档，消息可正常发回  
6) 解析 `messageSnippet/messageAuthor` 不丢内容  
7) require_mention 生效且 strip @ 文本后模型输入干净  
