from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable

SENSITIVE_KEYS = {
    "token",
    "secret",
    "app_secret",
    "appsecret",
    "jwt",
    "authorization",
}


def get_first(data: Any, paths: Iterable[str], default: Any = None) -> Any:
    value, found = get_first_with_presence(data, paths)
    return value if found else default


def get_first_with_presence(data: Any, paths: Iterable[str]) -> tuple[Any, bool]:
    for path in paths:
        current = data
        valid = True
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                valid = False
                break
        if valid and current not in (None, ""):
            return current, True
        if valid:
            return current, True
    return None, False


def strip_mention_text(text: str) -> str:
    if not text:
        return text
    cleaned = re.sub(r"<@[^>]+>", " ", text)
    cleaned = re.sub(r"@[\w\-]+", " ", cleaned)
    return " ".join(cleaned.split())


def redact_payload(payload: Any) -> Any:
    data = deepcopy(payload)
    return _redact_value(data)


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                redacted[key] = "***"
            else:
                redacted[key] = _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    return key.lower() in SENSITIVE_KEYS


def write_redacted_payload(payload: Any, request_id: str, base_dir: str = "./data/tailchat_payloads") -> None:
    if not request_id:
        return
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    dir_path = os.path.join(base_dir, day)
    os.makedirs(dir_path, exist_ok=True)
    file_path = os.path.join(dir_path, f"{request_id}.json")
    with open(file_path, "w", encoding="utf-8") as handle:
        json.dump(redact_payload(payload), handle, ensure_ascii=False, indent=2)
