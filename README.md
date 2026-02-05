# astrbot-platform-tailchat

AstrBot Tailchat 平台适配器（Platform Adapter）。

## 使用方式（官方推荐的多机器人隔离）

- 在 AstrBot UI 中创建多个机器人实例。
- 每个机器人实例选择 **Tailchat** 平台，分别填写各自的 `app_id`/`app_secret` 并绑定独立配置文件（模型/知识库不同）。
- 适配器仅负责平台接入，不维护 bots[] 列表。

## 回调 URL 规则

适配器会自动为每个 AstrBot 机器人实例生成回调路径：

```
/tailchat/callback/{robot_id}
```

Tailchat OpenApp 中填写的 Callback URL 示例：

```
https://your.domain.com/tailchat/callback/{robot_id}?token=CALLBACK_TOKEN
```

启动后日志会打印当前实例的 callback path（含 token）。

## 部署说明

- 适配器使用进程级单例 HTTP Server（单端口）。
- 如果部署在公网，需配置 HTTPS 反向代理（ngrok/cloudflared 也可用于调试）。

## 配置示例

参见 `plugins/tailchat/config.example.yaml`，单实例配置字段包含：

- Tailchat OpenApp 凭证（host/app_id/app_secret）
- 回调 token（每实例独立）
- 是否 require_mention
- 单端口 server 监听配置
