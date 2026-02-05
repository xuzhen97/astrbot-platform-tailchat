# Tailchat AstrBot 平台适配器

该目录提供 Tailchat OpenApp Bot 的 HTTP 回调接入与 AstrBot 平台适配器实现。

## 功能概览
- `/tailchat/callback` HTTP 回调入口（FastAPI）
- Tailchat payload → `IncomingMessage`
- AstrBot 输出 → Tailchat OpenAPI sendMessage
- 最小可用安全：token/IP 白名单/可选 body hash

## 安装依赖
```bash
pip install fastapi uvicorn httpx pyyaml
```

## 配置
复制 `config.example.yaml` 为 `config.yaml` 并填写：
```yaml
tailchat:
  host: "https://tailchat.msgbyte.com"
  app_id: "YOUR_APP_ID"
  app_secret: "YOUR_APP_SECRET"
  # bot_user_id: "YOUR_BOT_USER_ID"
```

Tailchat 回调 URL：
```
https://your-domain.com/tailchat/callback?token=CHANGE_ME
```

## 启动方式（示例）
```python
from plugins.tailchat_adapter import build_adapter, build_server, load_config

config = load_config("plugins/tailchat_adapter/config.yaml")
adapter = build_adapter(config)
server = build_server(adapter, config)
server.start()
```

## 说明
- 默认 `require_mention: true`，需要在 payload 中检测到 mention 才会处理。
- 附件支持 `url_only` 或 `download`。
- OpenAPI 的路径可在 config 中覆盖（`login_path`, `send_message_path` 等）。

> 注意：请不要把 `app_secret` 提交到 git。
