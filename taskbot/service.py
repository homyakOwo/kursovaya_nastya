"""Бизнес-правила: авторизация, назначение задач, контроль сроков и отчёты."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from .storage import SQLiteStore


class AccessDenied(PermissionError):
    """Пользователь не имеет права выполнить операцию."""


class ValidationError(ValueError):
    """Недопустимые данные команды или переход статуса."""


@dataclass(frozen=True)
class TeamPolicy:
    admins: frozenset[int]
    allowed: frozenset[int]

    def __post_init__(self) -> None:
        if not self.admins:
            raise ValueError("Нужно указать хотя бы одного администратора")
        if any(user_id <= 0 for user_id in self.admins | self.allowed):
            raise ValueError("Идентификаторы участников должны быть положительными")

    def can_enter(self, user_id: int) -> bool:
        return user_id in self.admins or user_id in self.allowed

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admins


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskService:
    def __init__(self, store: SQLiteStore, *, admins: set[int], allowed: set[int],
                 clock: Callable[[], date] = date.today) -> None:
        self.store = store
        self.policy = TeamPolicy(frozenset(admins), frozenset(allowed))
        self.clock = clock

    def _user(self, user_id: int) -> None:
        if not self.policy.can_enter(user_id):
            raise AccessDenied("Нет доступа: обратитесь к руководителю проекта")
        if self.store.one("SELECT user_id FROM members WHERE user_id=?", (user_id,)) is None:
            raise AccessDenied("Сначала отправьте команду /start в личном чате")

    def _admin(self, user_id: int) -> None:
        self._user(user_id)
        if not self.policy.is_admin(user_id):
            raise AccessDenied("Команда доступна только руководителю")

    def register(self, user_id: int, name: str, username: str = "") -> None:
        if not self.policy.can_enter(user_id):
            raise AccessDenied("Этот Telegram ID не включён в список участников")
        name = name.strip()
        if not name or len(name) > 100:
            raise ValidationError("Имя должно содержать 1-100 символов")
        self.store.register(user_id, name, username[:64], timestamp())

    def members(self, actor_id: int) -> list[dict[str, Any]]:
        self._admin(actor_id)
        return self.store.many("SELECT user_id, display_name, username FROM members ORDER BY display_name")

    def create(self, actor_id: int, assignee_id: int, deadline: str, title: str) -> dict[str, Any]:
        self._admin(actor_id)
        if not isinstance(title, str) or not (3 <= len(title.strip()) <= 180):
            raise ValidationError("Название задачи должно содержать 3-180 символов")
        try:
            due = date.fromisoformat(deadline)
        except (TypeError, ValueError) as err:
            raise ValidationError("Срок указывается как ГГГГ-ММ-ДД") from err
        if due < self.clock():
            raise ValidationError("Нельзя создавать новую задачу с прошедшим сроком")
        if self.store.one("SELECT user_id FROM members WHERE user_id=?", (assignee_id,)) is None:
            raise ValidationError("Исполнитель должен сначала зарегистрироваться через /start")
        task_id = self.store.create_task(title.strip(), actor_id, assignee_id, deadline, timestamp())
        return self.get(actor_id, task_id)

    def get(self, actor_id: int, task_id: int) -> dict[str, Any]:
        self._user(actor_id)
        task = self.store.one("SELECT * FROM tasks WHERE task_id=?", (task_id,))
        if task is None:
            raise ValidationError("Задача с таким номером не найдена")
        if not self.policy.is_admin(actor_id) and task["assignee_id"] != actor_id:
            raise AccessDenied("Нельзя просматривать чужие задачи")
        return task

    def my_tasks(self, actor_id: int) -> list[dict[str, Any]]:
        self._user(actor_id)
        return self.store.many("""
            SELECT * FROM tasks WHERE assignee_id=?
            ORDER BY CASE status WHEN 'done' THEN 1 ELSE 0 END, due_date, task_id
        """, (actor_id,))

    def all_tasks(self, actor_id: int) -> list[dict[str, Any]]:
        self._admin(actor_id)
        return self.store.many("SELECT * FROM tasks ORDER BY due_date, task_id")

    def change_status(self, actor_id: int, task_id: int, new_status: str) -> dict[str, Any]:
        task = self.get(actor_id, task_id)
        if new_status not in ("doing", "done"):
            raise ValidationError("Допустимы только статусы «В работе» и «Готово»")
        transitions = {"new": {"doing", "done"}, "doing": {"done"}, "done": set()}
        if new_status not in transitions[task["status"]]:
            raise ValidationError("Этот переход статуса не разрешён")
        self.store.update_task(task_id, "status", new_status, actor_id, "status_changed",
                               f"{task['status']}->{new_status}", timestamp(),
                               timestamp() if new_status == "done" else None)
        return self.get(actor_id, task_id)

    def reassign(self, actor_id: int, task_id: int, assignee_id: int) -> dict[str, Any]:
        self._admin(actor_id)
        task = self.get(actor_id, task_id)
        if task["status"] == "done":
            raise ValidationError("Завершённую задачу нельзя переназначить")
        if self.store.one("SELECT user_id FROM members WHERE user_id=?", (assignee_id,)) is None:
            raise ValidationError("Новый исполнитель не зарегистрирован")
        if task["assignee_id"] == assignee_id:
            raise ValidationError("Этот участник уже назначен")
        self.store.update_task(task_id, "assignee_id", assignee_id, actor_id,
                               "reassigned", f"{task['assignee_id']}->{assignee_id}", timestamp())
        return self.get(actor_id, task_id)

    def report(self, actor_id: int) -> dict[str, Any]:
        self._admin(actor_id)
        tasks = self.all_tasks(actor_id)
        counts = {"new": 0, "doing": 0, "done": 0}
        workloads: dict[int, int] = {}
        overdue = 0
        for task in tasks:
            counts[task["status"]] += 1
            if task["status"] != "done":
                workloads[task["assignee_id"]] = workloads.get(task["assignee_id"], 0) + 1
                if task["due_date"] < self.clock().isoformat():
                    overdue += 1
        return {"total": len(tasks), "statuses": counts,
                "active_per_member": workloads, "overdue": overdue}

    def due_for_reminder(self, actor_id: int, days_ahead: int = 2) -> list[dict[str, Any]]:
        """Кандидаты для явной команды /remind; фактическую отправку выполняет bot.py."""
        self._admin(actor_id)
        if not (0 <= days_ahead <= 30):
            raise ValidationError("Период напоминания должен быть от 0 до 30 дней")
        until = (self.clock() + timedelta(days=days_ahead)).isoformat()
        return self.store.many("""
            SELECT * FROM tasks WHERE status != 'done' AND due_date<=?
            ORDER BY assignee_id, due_date, task_id
        """, (until,))

    def history(self, actor_id: int, task_id: int) -> list[dict[str, Any]]:
        self.get(actor_id, task_id)
        return self.store.many("SELECT * FROM history WHERE task_id=? ORDER BY event_id", (task_id,))
