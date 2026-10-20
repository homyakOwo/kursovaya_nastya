"""Воспроизводимая локальная демонстрация без токена и сетевых запросов."""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from taskbot.formatting import format_report, format_task
from taskbot.service import TaskService
from taskbot.storage import SQLiteStore


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        srv = TaskService(SQLiteStore(Path(folder) / "demo.sqlite3"),
                          admins={101}, allowed={202, 303}, clock=lambda: date(2026, 10, 20))
        for uid, name in ((101, "Руководитель"), (202, "Аня"), (303, "Илья")):
            srv.register(uid, name)
        task1 = srv.create(101, 202, "2026-10-23", "Подготовить проектный план")
        task2 = srv.create(101, 303, "2026-10-21", "Согласовать сроки")
        srv.change_status(202, task1["task_id"], "doing")
        srv.change_status(303, task2["task_id"], "done")
        print("=== ЗАДАЧИ ПОСЛЕ ОБРАБОТКИ ===")
        for task in srv.all_tasks(101):
            print(format_task(task), "\n")
        print("=== ОТЧЁТ ===")
        print(format_report(srv.report(101)))
        print("=== ИСТОРИЯ ЗАДАЧИ 1 ===")
        for event in srv.history(101, 1):
            print(event["event_type"], event["details"])


if __name__ == "__main__":
    main()
