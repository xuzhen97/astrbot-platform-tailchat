# Tailchat AstrBot 平台适配器

该目录提供 Tailchat OpenApp Bot 的 HTTP 回调接入与 AstrBot 平台适配器实现，支持多机器人与项目隔离（profile/backend 双模式）。

## 功能概览
- 多机器人回调入口（每个 bot 一个 path）
- Tailchat payload → `IncomingMessage`
- AstrBot 输出 → Tailchat OpenAPI sendMessage
- 安全：每 bot token/IP 白名单/可选 body hash

## 安装依赖
```bash
pip install fastapi uvicorn httpx pyyaml
```

## 配置
复制 `config.example.yaml` 为 `config.yaml` 并填写（支持多个 bot）：
```yaml
tailchat:
  bots:
    - bot_key: "finance"
      host: "https://tailchat.msgbyte.com"
      app_id: "YOUR_APP_ID_1"
      app_secret: "YOUR_APP_SECRET_1"
      callback:
        path: "/tailchat/callback/finance"
        token: "TOKEN_FINANCE"
      astrbot:
        mode: "profile"
        profile_id: "finance_profile"
    - bot_key: "legal"
      host: "https://tailchat.msgbyte.com"
      app_id: "YOUR_APP_ID_2"
      app_secret: "YOUR_APP_SECRET_2"
      callback:
        path: "/tailchat/callback/legal"
        token: "TOKEN_LEGAL"
      astrbot:
        mode: "backend"
        backend_url: "http://127.0.0.1:18080"
```

Tailchat 回调 URL（每个 bot 独立）：
```
https://your-domain.com/tailchat/callback/finance?token=TOKEN_FINANCE
https://your-domain.com/tailchat/callback/legal?token=TOKEN_LEGAL
```

## 启动方式（示例）
```python
from plugins.tailchat_adapter import TailchatPlugin

plugin = TailchatPlugin(config_path="plugins/tailchat_adapter/config.yaml")
plugin.start()
```

## 说明
- 默认 `require_mention: true`，需要在 payload 中检测到 mention 才会处理（未传 mentions 字段也会拒绝）。
- `session_key` 默认包含 `botKey`，避免不同 bot 共享上下文。
- `profile` 模式需 AstrBot 支持根据 metadata 中的 `astrbot_profile_id` 选择模型/知识库（或额外安装路由插件）。
- `backend` 模式会向 `backend_url/api/tailchat/ingest` 转发消息并回传回复文本。
- 附件支持 `url_only` 或 `download`。
- OpenAPI 的路径可在 config 中覆盖（`login_path`, `send_message_path` 等）。
## 安全建议
- 每个 bot 单独的 token 与 callback path。
- 建议启用 HTTPS 与 IP 白名单。

> 注意：请不要把 `app_secret` 提交到 git。
