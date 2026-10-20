"""Конфигурация из переменных окружения без хранения токена в исходниках."""
from __future__ import annotations

import os
from dataclasses import dataclass


def read_ids(raw: str) -> set[int]:
    values = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                val = int(part)
            except ValueError as err:
                raise ValueError("ID участников должны быть целыми числами") from err
            if val <= 0:
                raise ValueError("ID участников должны быть положительными")
            values.add(val)
    return values


@dataclass(frozen=True)
class Settings:
    token: str
    db_path: str
    admin_ids: frozenset[int]
    allowed_user_ids: frozenset[int]

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        admins = read_ids(os.getenv("ADMIN_IDS", ""))
        allowed = read_ids(os.getenv("ALLOWED_USER_IDS", ""))
        if not token:
            raise ValueError("Не задана переменная BOT_TOKEN")
        if not admins:
            raise ValueError("Нужно задать хотя бы один Telegram ID в ADMIN_IDS")
        return cls(token, os.getenv("BOT_DB", "data/tasks.sqlite3"),
                   frozenset(admins), frozenset(allowed))
