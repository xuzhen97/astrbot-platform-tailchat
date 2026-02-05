# astrbot-platform-tailchat 修订方案（对齐 AstrBot 官方结构 + 支持多机器人隔离）

> 适用对象：对 AstrBot / Tailchat 不熟的工程师；可直接照搬按步骤修改你的仓库实现。  
> 目标：  
> 1) **结构/入口**与 AstrBot 官方“插件 + 平台适配器”模式一致（可被 AstrBot 自动发现/启用）。  
> 2) 支持**配置多个 Tailchat 机器人实例**（多个 appId/appSecret），并实现**项目隔离**：不同机器人使用不同模型/知识库配置。  
> 3) 保留你当前已实现的 HTTP 回调、payload fallback、JWT 自动重登、附件下载等能力，并补齐缺失的“平台注册/插件清单/mention 处理/可观测”等生产要点。

---

## 0. 你当前实现与“官方结构”的差异结论

你目前仓库的核心代码在：

```
plugins/tailchat_adapter/
  __init__.py
  adapter.py
  server.py
  tailchat_api.py
  types.py
  config.example.yaml
```

✅ 优点：模块拆分非常合理，HTTP 回调与 API 层清晰，payload fallback/401重登已实现。  
⚠️ 差异点（需要修订）：
1) 缺少 AstrBot 官方插件清单（如 `plugin.yaml` 或等价机制）与标准入口，导致 **AstrBot 不一定能自动发现/加载**。  
2) 缺少“平台适配器注册”到 AstrBot 的标准接口（你现在是可被外部脚本调用，但不一定被 AstrBot 当作 platform）。  
3) 不支持“多个机器人实例 + 模型/知识库隔离”这一核心诉求（目前 config 仅支持单 bot）。  
4) mention 处理逻辑存在两个问题：  
   - `require_mention` 当前仅在 payload 中 mentions 字段“存在”时才生效；如果 mentions 字段缺失，会误放行。  
   - 未 strip 掉 @bot 文本（会污染模型输入/指令解析）。

---

## 1. 修订后的目标仓库结构（对齐官方思路）

将插件从“脚本可调用模块”改造为“可被 AstrBot 自动加载的插件包”，建议采用以下结构：

```
astrbot-platform-tailchat/
  README.md
  pyproject.toml                # 推荐（或 requirements.txt）
  plugins/
    tailchat_adapter/
      plugin.yaml               # ★新增：AstrBot 插件清单（或等价 manifest）
      __init__.py
      config.example.yaml
      tailchat_adapter/
        __init__.py
        adapter.py
        server.py
        tailchat_api.py
        router.py               # ★新增：多机器人路由/隔离逻辑
        types.py
        utils.py                # ★新增：deep_get/get_first/mention strip/log redaction
```

> 说明：  
> - 外层 `plugins/tailchat_adapter` 是 AstrBot 插件目录（包含 plugin.yaml）。  
> - 内层 `tailchat_adapter/` 是 Python 包（避免与 AstrBot 插件系统命名冲突，也便于相对 import）。  
> - 你的现有代码文件将整体迁移到内层包中，外层仅保留插件入口与配置示例。

---

## 2. 多机器人（多 appId）+ 项目隔离：总体设计

### 2.1 需求拆解
你要的“多个机器人，不同机器人用不同模型/知识库（项目隔离）”，本质是 **同一个 AstrBot 进程里**同时存在多个 Tailchat Bot 入口，并且每个入口绑定到不同的 AstrBot “处理配置（profile/project）”。

因此设计为两层隔离：

**A. 接入隔离（Tailchat Bot 实例隔离）**  
- 每个 bot 有独立：`host/app_id/app_secret/bot_user_id`、安全 token、回调路径（可共享也可独立）。  
- 每个 bot 有独立：TailchatAPI（JWT/token 独立）与回调鉴权。

**B. 处理隔离（AstrBot 处理链隔离）**  
- 每个 bot 绑定一个 `profile_id`（或 `project_id`），用于选择不同模型/知识库/插件策略。  
- session_key 必须包含 bot_key：`{botKey}:{groupId}:{converseId}`，防止不同 bot 在同一群/会话产生上下文串扰。

### 2.2 两种落地路径（必须二选一，但建议都支持）
由于不同 AstrBot 版本对“多 profile / 多模型 / 知识库”支持方式可能不同，修订方案提供两条可落地路径：

#### 路径 1（优先）：单 AstrBot 进程内多 Profile（推荐）
- 适配器将 `profile_id` 写入 IncomingMessage.metadata（或 AstrBot 事件对象的扩展字段）。
- 新增 `router.py`：在平台适配器侧按 `profile_id` 调用 AstrBot 的“选择模型/知识库”能力（若 AstrBot 提供），或者转发到不同的 AstrBot 内部 pipeline。

#### 路径 2（兜底）：多 AstrBot 实例（强隔离，最稳）
- 一个 `astrbot-platform-tailchat` 插件仍可管理多个 Tailchat bot，但每个 bot 指向一个不同的 AstrBot “后端实例”：
  - `astrbot_backend_url: http://127.0.0.1:xxxx`  
- router 将消息转发到对应实例（HTTP RPC），由该实例负责模型/知识库配置。
- 优点：100% 隔离、与 AstrBot 内部实现无关。缺点：资源开销更大。

> 本修订方案会把两个路径都设计进配置与代码中；默认启用路径 1，路径 2 作为 fallback。

---

## 3. 配置文件升级（支持多个机器人）

将当前单 bot 配置：

```yaml
tailchat:
  host: ...
  app_id: ...
  app_secret: ...
```

升级为 **bots 列表**：

```yaml
tailchat:
  bots:
    - bot_key: "finance"
      host: "https://tailchat.msgbyte.com"
      app_id: "APP_ID_1"
      app_secret: "APP_SECRET_1"
      bot_user_id: "BOT_USER_ID_1"         # 推荐填写
      callback:
        path: "/tailchat/callback/finance"  # 推荐每个 bot 独立路径（更清晰）
        token: "TOKEN_FINANCE"
      astrbot:
        mode: "profile"                     # profile | backend
        profile_id: "finance_profile"       # mode=profile 时必填
      features:
        require_mention: true
        attachment_mode: "url_only"

    - bot_key: "legal"
      host: "https://tailchat.msgbyte.com"
      app_id: "APP_ID_2"
      app_secret: "APP_SECRET_2"
      bot_user_id: "BOT_USER_ID_2"
      callback:
        path: "/tailchat/callback/legal"
        token: "TOKEN_LEGAL"
      astrbot:
        mode: "backend"                     # 兜底模式：指向另一个 AstrBot 实例
        backend_url: "http://127.0.0.1:18080"
      features:
        require_mention: true
        attachment_mode: "download"

server:
  listen_host: "0.0.0.0"
  listen_port: 8088

security:
  allow_ips: []              # 可选：全局 IP 白名单
  enable_body_hash: false

defaults:
  download_dir: "./data/tailchat_downloads"
  max_attachment_mb: 50
  session_key_template: "{botKey}:{groupId}:{converseId}"
```

### 3.1 关键字段说明
- `bot_key`：机器人实例标识（必填，唯一），用于路由与 session_key 前缀。
- `callback.path`：为每个 bot 单独提供回调路径（强烈推荐）。  
  - Tailchat OpenApp 的 Callback URL 配置为：`https://your.domain.com{path}?token=...`
- `callback.token`：每个 bot 单独的 token（最简单的回调鉴权方式）。
- `astrbot.mode`：  
  - `profile`：单进程内隔离（推荐）  
  - `backend`：转发到外部 AstrBot 实例（兜底）
- `features`：每个 bot 可覆盖默认值，实现“不同 bot 不同行为”。

---

## 4. 代码修订：逐文件“可照搬”修改清单

> 下文所有改动按“你当前代码”为基准，给出明确新增/迁移/替换点。  
> 重要：你当前已实现的核心逻辑（payload fallback、下载、401重登）会保留，只做结构与多 bot 扩展。

---

### 4.1 新增 `plugin.yaml`（让 AstrBot 识别并加载插件）

在 `plugins/tailchat_adapter/plugin.yaml` 新增（字段名根据 AstrBot 插件规范可能略有差异；如果你的 AstrBot 版本使用不同 manifest 名称，请按其规范等价替换）：

```yaml
id: "astrbot-platform-tailchat"
name: "AstrBot Platform Tailchat"
version: "0.1.0"
entry: "tailchat_adapter:plugin_entry"    # 指向外层 __init__.py 的入口函数
description: "Tailchat OpenApp Bot platform adapter for AstrBot"
author: "xuzhen97"
license: "MIT"
```

> 说明：  
> - `entry` 采用“module:function”风格；在外层 `plugins/tailchat_adapter/__init__.py` 中实现 `plugin_entry()`。

---

### 4.2 外层 `plugins/tailchat_adapter/__init__.py`：实现插件入口与启动多 bot

新增/替换为：

**职责：**
1) 读取配置（支持 bots 列表）  
2) 为每个 bot 创建一个 `TailchatPlatformAdapter` 实例  
3) 创建一个 FastAPI app，注册多个 callback path（每个 bot 一个路由）  
4) 启动 uvicorn（或交给 AstrBot 主进程的 web 服务，按 AstrBot 规范）

**必须具备：**
- 插件启用时自动 start server
- 插件停用时 stop server
- 注入 AstrBot 的“消息处理入口”（由 AstrBot 提供的 callback/hook）

---

### 4.3 新增 `tailchat_adapter/router.py`：多 bot 路由与隔离核心

新增 `router.py`：

**核心接口：**
- `route_incoming(bot_key, IncomingMessage) -> None`
  - mode=profile：将 `profile_id` 写入 message.metadata 并投递给 AstrBot（或调用 AstrBot pipeline）
  - mode=backend：把消息序列化后 HTTP POST 到 backend_url，由对方 AstrBot 实例返回回复文本/附件，再发回 Tailchat

**落地要点：**
- 统一输出：最终都会调用 `adapter.send_text(...)`（第一版只回文字；附件回传可后续补全）
- session_key 必须包含 bot_key（从 defaults/session_key_template 生成）

---

### 4.4 内层 `tailchat_adapter/adapter.py`：支持 botKey + mention 修复 + 生产可观测

你现有 `TailchatPlatformAdapter` 保留，但需扩展：

#### 4.4.1 TailchatAdapterConfig 增加 `bot_key` 与 per-bot callback 配置（仅用于日志/metadata）
```python
@dataclass
class TailchatAdapterConfig:
    bot_key: str
    host: str
    app_id: str
    app_secret: str
    bot_user_id: Optional[str] = None
    require_mention: bool = True
    ...
```

#### 4.4.2 修复 require_mention 逻辑（必须）
你当前逻辑：
```python
if self.config.require_mention and mentions_present:
    ...
```
问题：mentions 字段缺失时会误放行。  
修复为：

```python
if self.config.require_mention:
    # 若 payload 没有 mentions 字段，仍应视为未 mention
    if self.config.bot_user_id:
        if self.config.bot_user_id not in mentions:
            return None
    else:
        if not mentions:
            return None
```

#### 4.4.3 增加 mention strip（必须）
新增 `utils.py` 的函数（或写在 adapter 内部）：
- `strip_mention_text(text: str) -> str`：去掉类似 `<@xxxx>`、`@AstrBot`、`@ bot` 等常见 mention 形式（以实际 Tailchat 内容格式为准，先做保守 strip）。

在 convert_message 最终赋值前：
```python
clean_text = strip_mention_text(str(content or ""))
```

#### 4.4.4 metadata 打码与落原始 payload（建议但很关键）
当前你直接 `metadata={"raw": payload}`，可能含大量信息。  
改为：
- metadata 中仅保存必要字段（bot_key、request_id、event_type、attachments 摘要）
- 完整 raw payload 仅在 debug 或异常时写入本地（并对 token/app_secret 打码）

新增 `utils.py`：
- `redact_payload(payload) -> payload'`：递归将 `token/secret/appSecret` 等键值替换为 `"***"`

在异常时：
- 写入 `./data/tailchat_payloads/{date}/{request_id}.json`

---

### 4.5 内层 `tailchat_adapter/server.py`：从“单一路由”升级为“多 bot 多路由”

你当前 `TailchatCallbackServer` 只注册一个 callback_path。  
修订方式：

#### 4.5.1 让 server 支持“动态注册多个路由”
- 构造函数接收一个 dict：`path -> handler`
- 或构造函数接收 `bots` 列表，每个 bot 注册一条 route：

```python
for bot in bots:
    @app.post(bot.callback_path)
    async def callback(request: Request, bot_key=bot.bot_key):
        ...
        validate token = bot.callback_token
        create_task(adapter_map[bot_key].handle_incoming(...))
```

> 注意：Python 闭包变量陷阱  
> 必须用 `bot_key=...` 的默认参数方式绑定当前值，否则所有路由会用最后一个 bot_key。

#### 4.5.2 安全校验：token 按 bot 独立（必须）
你当前是 `security_config.callback_token` 全局。  
修订为：
- 每个 bot 有自己的 token  
- 全局 allow_ips 仍可保留

---

### 4.6 内层 `tailchat_adapter/tailchat_api.py`：支持多实例（已天然支持）
你当前 TailchatAPI 是实例化的，天然支持多 bot。  
仅建议：
- 增加 `close()`，在插件 stop 时关闭 httpx client：
  ```python
  def close(self): self._client.close()
  ```

---

## 5. AstrBot 官方结构一致性：你要做到的“最低对齐标准”

由于不同 AstrBot 版本的插件系统细节可能略有差异，但**最低对齐标准**如下（必须满足）：

1) 有可被 AstrBot 发现的插件 manifest（如 plugin.yaml）  
2) 有明确插件入口函数/类（manifest entry 指向）  
3) 插件启动时自动启动回调服务（或挂到 AstrBot 的 WebServer 上）  
4) 平台适配器必须向 AstrBot 注册 “platform=tailchat” 或通过 AstrBot 约定的方式把消息投递到统一事件系统  
5) session_key 规则与 AstrBot 会话隔离一致（建议 botKey 前缀）

> 如果你的 AstrBot 版本没有“平台注册 API”，则采用等价方案：  
> - 将 IncomingMessage 转换为 AstrBot 的内部 MessageEvent（按其类型）并投递到事件总线；  
> - 并在 metadata 写入 `platform="tailchat"`，以便插件链识别来源。

---

## 6. 多机器人隔离：如何绑定不同模型/知识库（实现方案细化）

### 6.1 Path 1：profile 模式（推荐）
**目标：** 同一 AstrBot 进程中，不同 bot 使用不同模型/知识库配置。

实现方式（按“可照搬”层面给出）：

1) 在配置中为每个 bot 指定 `profile_id`
2) 在 router 中将 `profile_id` 写入 message.metadata：
   ```python
   message.metadata["astrbot_profile_id"] = profile_id
   message.metadata["bot_key"] = bot_key
   ```
3) 在 AstrBot 侧（两种实现二选一）：
   - A) 若 AstrBot 提供 `select_profile(profile_id)` / `with_profile(profile_id)`：  
     router 在调用 AstrBot pipeline 前切换 profile（处理完再切回）。
   - B) 若 AstrBot 没有该能力：  
     在 AstrBot 内新增一个轻量“ProfileRouter 插件”，根据 metadata.profile_id 把请求转发到不同的 LLM/知识库实例。

> 交付要求：在 README 中明确“需要 AstrBot 支持 profile 或需要额外安装 ProfileRouter 插件”。

### 6.2 Path 2：backend 模式（强隔离兜底）
当 AstrBot 内部无法按 profile 切换时，使用 backend 模式：

1) 为每个 bot 配置 `backend_url`
2) router 将 IncomingMessage 序列化并 POST：
   - `POST {backend_url}/api/tailchat/ingest`
   - body: {text, attachments, session_key, metadata, reply...}
3) backend AstrBot 实例返回：
   - {text_reply, attachments_reply(optional)}
4) adapter 调用 TailchatAPI send_message 回 Tailchat

> 注意：backend 模式下，“平台适配器”仍在主 AstrBot 中，但模型/知识库隔离由多个 AstrBot 实例保证，最稳。

---

## 7. “拿来即改”的实施步骤（推荐顺序）

### Step 1：重构目录（不改逻辑）
- 新建内层包 `tailchat_adapter/`
- 把现有 `adapter.py/server.py/tailchat_api.py/types.py` 移入内层包
- 外层保留 `plugin.yaml`、外层 `__init__.py`（入口）、`config.example.yaml`

### Step 2：升级配置为 bots 列表
- 新增 `defaults` 段
- 将单 bot 配置迁移到 `tailchat.bots[0]`
- 保证兼容：如果用户仍给旧格式（host/app_id/app_secret），在 load_config 时自动转换为 bots 列表

### Step 3：改造 server 为多路由
- 按每个 bot 的 callback.path 注册 route
- route 内按 bot.token 校验
- route 内 create_task 调用对应 adapter 实例

### Step 4：修复 require_mention + mention strip
- 修改 convert_message 逻辑（见 4.4.2）
- 新增 strip_mention_text 并调用

### Step 5：实现 router.py（profile/backend 两模式）
- profile 模式：metadata 注入 + 调用 AstrBot pipeline（按你们实际 AstrBot API 接口实现）
- backend 模式：HTTP 转发（先只回文本）

### Step 6：完善可观测与错误落盘
- 异常时写 raw payload（redact）
- 日志包含：request_id/bot_key/group/converse/sender

### Step 7：补齐 stop/close
- server.stop()
- tailchat_api.close()

---

## 8. 验收清单（多 bot + 隔离必测）

1) finance bot 与 legal bot 均能在 Tailchat 各自群组中收到 @ 并回复  
2) finance bot 的 session_key 为：`finance:{groupId}:{converseId}`  
3) legal bot 的 session_key 为：`legal:{groupId}:{converseId}`  
4) 在同一群组同一会话里，用不同 bot 发相同问题，返回结果明显体现不同模型/知识库（隔离成功）  
5) JWT 过期后自动重登并继续可回复  
6) payload 缺少 mentions 字段时仍不会误触发（require_mention 生效）  
7) @bot 文本不会进入模型输入（strip 生效）  
8) 附件 url_only 与 download 均可用，且超大文件会被拒绝/降级  
9) 回调接口响应 < 200ms（不在回调内做推理）  
10) 解析失败会落盘 payload（可排障）

---

## 9. 你需要在 README 里新增的“使用说明”（必须写清）

- 如何配置多个 bot（每个 bot 对应一个 Tailchat OpenApp）
- 每个 bot 的 Callback URL 如何填写（不同 path + token）
- profile 模式需要 AstrBot 支持什么（或额外插件）
- backend 模式如何启动多个 AstrBot 实例与端口
- 安全建议：token、IP 白名单、HTTPS、限流

---

## 10. 最小代码改动提示（基于你现有实现的关键差异）

你现有实现中以下能力已满足，无需推倒重来：
- payload 字段 fallback（_get_first/_get_first_with_presence）
- attachments 解析 + download 模式
- TailchatAPI 401/403 自动 login 重试
- 回调中 asyncio.create_task 非阻塞

你需要重点修订的是：
- “插件/平台注册”对齐 AstrBot（plugin.yaml + 入口 + 注册/投递到 AstrBot 事件系统）
- 多 bot 路由与隔离（bots 配置 + 多 callback 路由 + router.py）
- mention 修复（require_mention 与 strip）

---

## 11. 附：建议的版本计划（便于你发布 tag）

- `v0.1.0`：单 bot + 官方结构对齐 + mention 修复 + 稳定回调
- `v0.2.0`：多 bot 支持 + session_key 隔离 + profile mode（metadata 注入）
- `v0.3.0`：backend mode + 文件回传（上传或对象存储链接）
- `v0.4.0`：更完整 payload 兼容 + 富消息/引用回复增强

---

> 备注：  
> 本方案没有假定 AstrBot 内部的某个具体 API 一定存在，因此在“profile 模式”的调用处用“可插拔”方式描述；工程实现时，Code Agent 需根据你当前 AstrBot 版本的插件/事件接口对接到正确的 pipeline。  
> 如果你希望我进一步“把 router.py 里调用 AstrBot 的具体代码也写死”，请再提供：你当前 AstrBot 的版本号与平台适配器接口（或你希望接入的 AstrBot 处理入口函数/类名）。在缺少这一信息时，按本方案实现仍可通过 backend 模式保证 100% 可用。
