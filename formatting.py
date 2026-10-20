"""Текстовые ответы, безопасные для отправки в Telegram без parse_mode."""
from __future__ import annotations

from typing import Any

NAMES = {"new": "Запланировано", "doing": "В работе", "done": "Готово"}


def format_task(task: dict[str, Any]) -> str:
    return (f"№{task['task_id']} | {NAMES[task['status']]}\n"
            f"{task['title']}\nИсполнитель: {task['assignee_id']}\n"
            f"Срок: {task['due_date']}")


def format_report(report: dict[str, Any]) -> str:
    x = report["statuses"]
    members = report["active_per_member"]
    loads = ", ".join(f"{uid}: {count}" for uid, count in sorted(members.items())) or "нет"
    return (f"Всего задач: {report['total']}\n"
            f"Запланировано: {x['new']}\nВ работе: {x['doing']}\n"
            f"Готово: {x['done']}\nПросрочено: {report['overdue']}\n"
            f"Активные задачи по исполнителям: {loads}")
