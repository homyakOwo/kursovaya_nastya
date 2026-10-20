"""Транзакционное хранение участников, задач и журнала изменений в SQLite."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class SQLiteStore:
    def __init__(self, path: str | Path = "data/tasks.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def _init_db(self) -> None:
        with self.connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS members (
                    user_id INTEGER PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    joined_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    creator_id INTEGER NOT NULL REFERENCES members(user_id),
                    assignee_id INTEGER NOT NULL REFERENCES members(user_id),
                    due_date TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new'
                        CHECK(status IN ('new', 'doing', 'done')),
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_assignee_status
                  ON tasks(assignee_id, status);
                CREATE INDEX IF NOT EXISTS idx_tasks_due
                  ON tasks(due_date);
                CREATE TABLE IF NOT EXISTS history (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES tasks(task_id),
                    actor_id INTEGER NOT NULL REFERENCES members(user_id),
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT ''
                );
            """)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.connect() as con:
            cursor = con.execute(sql, params)
            return int(cursor.lastrowid or 0)

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute(sql, params).fetchone()
            return dict(row) if row else None

    def many(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as con:
            return [dict(row) for row in con.execute(sql, params).fetchall()]

    def register(self, user_id: int, name: str, username: str, timestamp: str) -> None:
        with self.connect() as con:
            con.execute("""
                INSERT INTO members(user_id, display_name, username, joined_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    username=excluded.username
            """, (user_id, name, username, timestamp))

    def create_task(self, title: str, creator_id: int, assignee_id: int,
                    due_date: str, timestamp: str) -> int:
        with self.connect() as con:
            cur = con.execute("""
                INSERT INTO tasks(title, creator_id, assignee_id, due_date, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (title, creator_id, assignee_id, due_date, timestamp))
            task_id = int(cur.lastrowid)
            con.execute("""
                INSERT INTO history(task_id, actor_id, event_type, occurred_at, details)
                VALUES (?, ?, 'created', ?, ?)
            """, (task_id, creator_id, timestamp, f"assignee={assignee_id}"))
            return task_id

    def update_task(self, task_id: int, field: str, value: Any,
                    actor_id: int, event: str, details: str,
                    timestamp: str, finished_at: str | None = None) -> None:
        if field not in ("assignee_id", "status"):
            raise ValueError("Недопустимое поле для изменения")
        with self.connect() as con:
            if field == "status":
                con.execute("UPDATE tasks SET status=?, finished_at=? WHERE task_id=?",
                            (value, finished_at, task_id))
            else:
                con.execute("UPDATE tasks SET assignee_id=? WHERE task_id=?",
                            (value, task_id))
            con.execute("""
                INSERT INTO history(task_id, actor_id, event_type, occurred_at, details)
                VALUES (?, ?, ?, ?, ?)
            """, (task_id, actor_id, event, timestamp, details))
