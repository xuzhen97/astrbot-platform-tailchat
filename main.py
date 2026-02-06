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
