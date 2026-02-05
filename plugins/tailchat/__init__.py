from __future__ import annotations


def plugin_entry() -> None:
    # Import platform to trigger @register_platform_adapter
    from .tailchat.platform import TailchatPlatform  # noqa: F401

