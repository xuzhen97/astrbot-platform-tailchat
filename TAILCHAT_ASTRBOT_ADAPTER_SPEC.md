# Tailchat ↔ AstrBot 平台适配器（方案 A）完整实现方案（可交付给 Code Agent）

> 目标：把 Tailchat OpenApp Bot（HTTP 回调）接入 AstrBot，使 Tailchat 内的**文字/图片/文件**消息可转发给 AstrBot 处理，并将结果正确回传 Tailchat。  
> 面向读者：对 Tailchat/AstrBot 都不熟的工程师；按本文逐步实现即可。

---

## 0. 术语速查（先看 1 分钟）

- **Tailchat OpenApp**：Tailchat 的开放平台应用，包含 `appId/appSecret`，可开启 Bot 能力并配置回调 URL。
- **HTTP 回调 Bot**：Tailchat 把触发的消息事件通过 HTTP POST 发到你的回调接口。
- **Tailchat OpenAPI**：用 `appId/appSecret` 登录换 JWT 后，调用接口发送消息/上传文件等。
- **AstrBot 平台适配器（Platform Adapter）**：AstrBot 的一种插件形态，把外部平台消息转为 AstrBot 的消息事件，并实现 send() 发回平台。

---

## 1. 最终交付物清单（你要实现这些）

在 AstrBot 项目（或 AstrBot 的插件目录）新增一个插件目录，例如：

```
plugins/
  tailchat_adapter/
    __init__.py
    adapter.py
    server.py
    tailchat_api.py
    types.py
    config.example.yaml
    README.md
```

**必须实现：**
1) 一个 HTTP Server，提供 `/tailchat/callback` 用于接收 Tailchat 回调  
2) Tailchat 回调 payload → 解析成 AstrBot 的消息事件（文字/图片/文件/引用）  
3) AstrBot 处理后 → 通过 Tailchat OpenAPI 把回复发回原会话（converse）  
4) 基础鉴权/安全（最小可用：白名单 IP / token / 时间戳签名 3 选 1，推荐 token）

**建议实现（便于上线）：**
- Tailchat JWT 自动刷新
- 附件 URL 下载（可选开关）与临时缓存
- 错误日志与可观测（请求 id、trace id、落盘日志）

---

## 2. 环境与前置条件

### 2.1 Tailchat 侧前置
1. 安装并启用插件（Tailchat 管理端）：
   - 开放平台相关插件（OpenAPI/OpenApp）
   - 第三方集成（Integrations）
2. 创建 OpenApp（应用）并记录：
   - `TAILCHAT_APP_ID`
   - `TAILCHAT_APP_SECRET`
3. 在 OpenApp 中开启 **Bot** 能力并配置：
   - `Callback URL`：例如 `https://bot.example.com/tailchat/callback`
4. 在目标群组的 **集成** 页面，通过 `AppId` 把应用添加到群组。
5. 确认群里能看到该 Bot 成员（或集成应用存在），并且 @bot 会触发回调。

> 注意：Callback URL 必须公网可访问；本机开发用 ngrok / cloudflared 暴露端口。

### 2.2 AstrBot 侧前置
- 已能正常启动 AstrBot
- 允许安装/加载本地插件（平台适配器插件）
- Python 版本与依赖可用（建议 Python 3.10+）
- 允许启动一个 HTTP 服务（FastAPI/aiohttp/Flask 任一）

---

## 3. 总体架构与数据流

```
Tailchat 群聊
  |
  | (1) HTTP POST webhook: message event
  v
AstrBot 插件 tailchat_adapter
  - server.py: HTTP 回调入口 /tailchat/callback
  - adapter.py: payload → AstrBotMessageEvent
  - tailchat_api.py: login JWT / sendMessage / upload(optional)
  |
  | (2) HTTP 调用 Tailchat OpenAPI: sendMessage (and upload if needed)
  v
Tailchat 群聊显示 bot 回复
```

---

## 4. 配置设计（config.yaml）

### 4.1 配置文件范例（config.example.yaml）
```yaml
tailchat:
  host: "https://tailchat.msgbyte.com"  # 或自建域名
  app_id: "YOUR_APP_ID"
  app_secret: "YOUR_APP_SECRET"

server:
  listen_host: "0.0.0.0"
  listen_port: 8088
  callback_path: "/tailchat/callback"

security:
  # 推荐：简单 token 校验。Tailchat 回调 URL 可加 query: ?token=xxx
  callback_token: "CHANGE_ME"
  # 可选：IP 白名单（如果你是自建 Tailchat 或固定出口）
  allow_ips: []
  # 可选：启用 request body hash 校验（如果你们在网关层做签名）
  enable_body_hash: false

features:
  # 仅在被 @ 时处理：若 payload 能识别 mention 且非 mention 则忽略
  require_mention: true
  # 附件处理策略：url_only | download
  attachment_mode: "url_only"
  # 下载缓存目录（attachment_mode=download 时）
  download_dir: "./data/tailchat_downloads"
  # 附件最大大小（MB）
  max_attachment_mb: 50

mapping:
  # 会话键：用于 AstrBot 的会话隔离
  # 推荐："{groupId}:{converseId}"
  session_key_template: "{groupId}:{converseId}"
```

---

## 5. Tailchat 回调接入（HTTP Server）

### 5.1 技术选型建议
- 推荐 FastAPI + uvicorn（异步、易部署）
- 或 aiohttp（轻量）、Flask（同步亦可）

### 5.2 回调路由行为要求
- 方法：POST
- 路径：`/tailchat/callback`
- 解析 JSON body
- 进行安全校验（token / ip / body hash）
- 解析事件类型：只处理消息事件（`type == "message"` 或同义字段）
- 立即返回 200（不要长时间阻塞 Tailchat），耗时处理应异步（放入 AstrBot 事件队列）

### 5.3 安全校验（最小可用）
**推荐 token 校验：**
- Callback URL 填：`https://bot.example.com/tailchat/callback?token=YOUR_TOKEN`
- 服务器端检查 query token 是否匹配 `security.callback_token`
- 不匹配返回 401

> 如果 Tailchat 的回调能力支持签名头（不同版本/部署可能不同），可升级为签名校验；本方案以 token 为可落地最小实现。

---

## 6. Tailchat payload 解析规范（关键：避免“猜字段”导致失败）

### 6.1 原则
Tailchat 回调 payload 的字段在不同版本/部署下可能有差异。实现时必须：
1) **先记录原始 payload**（debug 日志）
2) **以“存在即用，不存在降级”**的方式解析
3) 对关键字段提供“候选字段列表”（多 key fallback）

### 6.2 你必须从 payload 拿到的最小字段
- groupId：群组 id（候选：`groupId`, `group_id`, `data.groupId`）
- converseId：会话/频道 id（候选：`converseId`, `converse_id`, `data.converseId`）
- messageId：消息 id（候选：`messageId`, `_id`, `data.messageId`）
- authorId/authorName：发送者信息（候选：`author`, `sender`, `data.author`）
- content：内容（候选：`content`, `text`, `data.content`）
- mentions：提及列表（候选：`mentions`, `meta.mentions`）
- attachments：附件列表（候选：`files`, `attachments`, `meta.files`）

> 如果某些字段缺失，至少保证能拿到 `groupId + converseId + content`，否则无法路由回消息。

### 6.3 附件结构（实现策略）
附件在 payload 中可能表现为：
- 直接带 url（`url`, `src`, `downloadUrl`）
- 只带 fileId，需要你通过 OpenAPI 换取临时 URL

实现要求：
- 解析时对每个附件产出统一的内部结构 `Attachment`：
  - `name`
  - `mime`
  - `size_bytes`
  - `url`（如果无 url，则填 None 并进入“补全 URL”流程）
  - `file_id`（如果有）

---

## 7. AstrBot 侧：平台适配器插件实现

### 7.1 插件入口与生命周期
- 插件加载时：
  1) 读取 config
  2) 初始化 Tailchat API client（不立即 login 也可，首次发消息时再 login）
  3) 启动 HTTP Server（独立线程/协程）
  4) 注册 platform adapter（名称：`tailchat`）

- 插件卸载时：
  - 优雅停止 HTTP Server

### 7.2 核心类与职责

#### `TailchatPlatformAdapter`（adapter.py）
职责：
- `convert_message(payload) -> AstrBotMessage`：把 Tailchat 消息转成 AstrBot 消息对象
- `commit_event(event)`：提交到 AstrBot 事件队列
- `send(event, content, attachments?)`：把 AstrBot 回复发回 Tailchat

#### `TailchatCallbackServer`（server.py）
职责：
- 提供 `/tailchat/callback` endpoint
- 安全校验
- 将 payload 丢给 adapter 的 `handle_incoming(payload)`（异步）

#### `TailchatAPI`（tailchat_api.py）
职责：
- `login()`：OpenAPI bot login（appId + md5 token）→ jwt
- `send_message(groupId, converseId, content, meta?)`
- 可选：`upload_file(...)` / `resolve_file_url(fileId)`

---

## 8. Tailchat OpenAPI 对接（必须能发消息回去）

### 8.1 登录换 JWT（必做）
实现一个 `login()`：
- 调用 Tailchat OpenAPI 的 bot 登录接口
- 输入：`appId`, `token=md5(appId+appSecret)`
- 输出：`jwt`
- 后续请求头：`X-Token: <jwt>`

> 注意：jwt 会过期，遇到 401/403 需自动重登重试一次。

### 8.2 发送消息（必做）
实现 `send_message(groupId, converseId, content, meta)`：
- 用 `X-Token` 调用 sendMessage 接口
- 参数里必须包含目标会话标识（converseId / groupId）
- content 支持纯文本（先保证最小闭环）

### 8.3 回复消息（建议）
如果你想在 Tailchat 里呈现“引用回复”，需要在 meta 里带 reply 信息：
- reply.messageId
- reply.author
- reply.content（可选）

具体字段按 Tailchat 实际接口要求实现；先做“普通发送”也可满足需求。

---

## 9. 多模态（文字/图片/文件）如何传递给 AstrBot

### 9.1 统一内部消息结构
在 `types.py` 定义：
- `IncomingMessage`：
  - `text: str`
  - `attachments: list[Attachment]`
  - `sender_id`, `sender_name`
  - `group_id`, `converse_id`, `message_id`
  - `session_key`

### 9.2 URL 直传模式（attachment_mode=url_only）
- 把附件的 `url`、`mime`、`name` 直接塞进 AstrBotMessage 的扩展字段（如 `metadata`）
- AstrBot/模型侧收到后自行拉取 URL 做图像理解/文件解析

### 9.3 下载模式（attachment_mode=download）
- 回调收到附件后，下载到 `download_dir/session_key/`
- 生成本地文件路径列表，作为 AstrBot 的输入（或作为模型文件上传）
- 注意限制：max_attachment_mb；超出则只传 url 或直接拒绝并提示

> 建议先实现 url_only 跑通闭环，再上 download 模式。

---

## 10. 从 AstrBot 返回 Tailchat（文字/图片/文件）

### 10.1 文字回复（必做）
- AstrBot 输出文本 → `TailchatAPI.send_message(...)`

### 10.2 图片/文件回复（可选，取决于 Tailchat 是否支持 OpenAPI 上传）
两条路：
- 若 Tailchat OpenAPI 支持上传并在消息中引用文件：
  1) `upload_file()` → 得到 fileId/url
  2) `send_message()` meta 里带 attachments
- 若 Tailchat 无上传接口或受限：
  - 将文件上传到你们自己的对象存储（S3/OSS）→ 发送链接

**建议：**
- 第一版：仅文字 + 链接（最稳定）
- 第二版：再对接 Tailchat 上传

---

## 11. 会话与上下文隔离（必须）

### 11.1 session_key 生成规则
默认：
- `session_key = f"{groupId}:{converseId}"`

用于：
- AstrBot 对话上下文隔离（不同频道不同上下文）
- 附件缓存目录隔离
- 日志聚合定位问题

---

## 12. 错误处理与可观测（必须写，不然线上难排障）

### 12.1 日志要求
每次回调记录（至少 debug）：
- request_id（自己生成 uuid）
- groupId/converseId/messageId
- sender_id
- text length
- attachments count
- 解析失败时：落盘原始 payload（打码敏感字段）

### 12.2 重试策略
- Tailchat 回调：不做重试（由 Tailchat 决定是否重试）。你的服务收到后应尽快 200。
- Tailchat OpenAPI send：
  - 401/403：自动 login 后重试 1 次
  - 5xx：指数退避重试 2 次（可选）
  - 超时：重试 1 次

---

## 13. 实现步骤（按里程碑交付）

### Milestone 1：最小闭环（1 天内可完成）
- [ ] Tailchat OpenApp 创建 + Bot 回调能打到你的服务（用 ngrok 验证）
- [ ] AstrBot 插件能启动 HTTP server 并收到 payload
- [ ] 从 payload 提取 groupId/converseId/text
- [ ] 把 text 交给 AstrBot（哪怕先简单 echo）
- [ ] AstrBot 回复通过 OpenAPI 发回 Tailchat（文字）

验收：
- 在 Tailchat 里 @bot 发送“hello”，机器人回复“hello”或模型输出。

### Milestone 2：附件 URL 透传（1~2 天）
- [ ] payload 解析 attachments（url_only）
- [ ] AstrBot/模型侧拿到 url（记录日志即可）
- [ ] 根据 url 做图片/文件处理（由 AstrBot 现有能力决定）
- [ ] 输出文本总结/结果回 Tailchat

验收：
- 发一张图片，机器人能描述图片/或完成指定任务并回复文本。

### Milestone 3：下载模式 + 文件回复（2~4 天）
- [ ] 下载附件到本地缓存并传给模型
- [ ] 可选：实现 Tailchat 上传或外部对象存储链接回传

验收：
- 发文件（pdf/docx）→ 机器人解析后返回摘要或生成新文件链接。

---

## 14. 代码实现要点（给 Code Agent 的“强约束”）

### 14.1 不允许“硬编码猜字段”
必须实现 `get_first(payload, ["a.b", "c", ...])`：
- 支持点路径读取嵌套字段
- 候选字段逐一尝试，取第一个存在且非空的

### 14.2 不允许在回调里做耗时模型推理
回调路由必须：
- 校验 → 入队 → 立即 200
模型推理在后台执行（AstrBot 事件系统/队列）

### 14.3 必须可配置
host/appId/appSecret/token/端口/require_mention/attachment_mode 都要从配置读取。

---

## 15. 安全与合规

- `appSecret` 不得写死在代码中；只允许 env 或配置文件（并在 README 提示不要提交到 git）
- 回调入口必须有至少一种保护：
  - token（推荐）
  - IP 白名单
  - 签名（可选高级）
- 下载附件要限制大小，避免被大文件打爆磁盘

---

## 16. 本地调试与部署指南

### 16.1 本地调试（ngrok 示例）
1) 启动 AstrBot（插件启用，HTTP server 监听 8088）
2) `ngrok http 8088`
3) Tailchat OpenApp 的 Callback URL 填：
   `https://xxxx.ngrok-free.app/tailchat/callback?token=YOUR_TOKEN`
4) 在群里 @bot 测试消息

### 16.2 生产部署
- 建议 Docker
- 入口放在 Nginx/Traefik 后面
- 配置 HTTPS（Let’s Encrypt）
- 监控：请求量、错误率、发送失败率、队列积压

---

## 17. 验收用例（必须全通过）

1) **文字**：@bot “你好” → 机器人回复一段模型输出  
2) **图片**：发送图片并 @bot → 机器人能返回描述（至少能拿到图片 URL 并在日志可见）  
3) **文件**：发送文件并 @bot → 机器人能返回“已收到文件：xxx（size）”并后续给摘要/结果  
4) **引用回复**：引用一条消息 @bot → payload 能识别 reply（可先不回引用，仅能处理内容即可）  
5) **并发**：连续发 10 条消息 → 不丢消息，不阻塞回调（回调响应 < 200ms）  
6) **JWT 过期**：模拟 401 → 自动 login 并重试成功

---

## 18. 开发者备注（与 Tailchat/AstrBot 文档对齐）
- Tailchat Bot（HTTP 回调）与 OpenAPI 登录/发消息在 Tailchat 文档的 OpenApp Bot 部分
- AstrBot 平台适配器开发在 AstrBot 文档的 Plugin Platform Adapter 部分

> 如果在实现过程中发现 Tailchat payload 或接口字段不一致：以“抓到的实际 payload + Tailchat 实际返回”为准更新 `types.py` 与字段映射。

---

## 19. TODO：后续增强（可选）
- WS Bot：不 @bot 也能监听（需长连接与权限）
- 富消息/卡片：更好的展示
- 多会话路由：私聊/群聊区分
- 指令系统：`/help` `/reset` 等
