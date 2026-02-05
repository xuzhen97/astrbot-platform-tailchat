from __future__ import annotations

from typing import Optional


class TailchatRegistry:
    def __init__(self) -> None:
        self._map: dict[str, object] = {}

    def register(self, robot_id: str, platform: object) -> None:
        self._map[robot_id] = platform

    def get(self, robot_id: str) -> Optional[object]:
        return self._map.get(robot_id)


registry = TailchatRegistry()
