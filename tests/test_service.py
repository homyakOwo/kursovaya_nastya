"""Автоматические тесты независимого от Telegram уровня бизнес-логики."""
from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from taskbot.config import read_ids
from taskbot.formatting import format_report, format_task
from taskbot.service import AccessDenied, TaskService, ValidationError
from taskbot.storage import SQLiteStore


class TaskServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "test.sqlite3"
        self.today = date(2026, 10, 20)
        self.service = TaskService(SQLiteStore(self.path), admins={101}, allowed={202, 303},
                                   clock=lambda: self.today)
        self.service.register(101, "Руководитель")
        self.service.register(202, "Исполнитель А")
        self.service.register(303, "Исполнитель Б")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def add(self):
        return self.service.create(101, 202, "2026-10-23", "Согласовать макет интерфейса")

    def test_register_allowed_member(self):
        self.assertEqual(len(self.service.members(101)), 3)

    def test_unlisted_user_denied(self):
        with self.assertRaises(AccessDenied):
            self.service.register(999, "Посторонний")

    def test_create_task_and_listing(self):
        item = self.add()
        self.assertEqual(item["task_id"], 1)
        self.assertEqual(len(self.service.my_tasks(202)), 1)
        self.assertEqual(len(self.service.all_tasks(101)), 1)

    def test_regular_user_cannot_create(self):
        with self.assertRaises(AccessDenied):
            self.service.create(202, 303, "2026-10-23", "Не разрешено")

    def test_title_validation(self):
        with self.assertRaises(ValidationError):
            self.service.create(101, 202, "2026-10-23", "а")

    def test_date_format_validation(self):
        with self.assertRaises(ValidationError):
            self.service.create(101, 202, "23/10/2026", "Проверить документы")

    def test_past_date_rejected(self):
        with self.assertRaises(ValidationError):
            self.service.create(101, 202, "2026-10-19", "Проверить документы")

    def test_unknown_assignee_rejected(self):
        with self.assertRaises(ValidationError):
            self.service.create(101, 404, "2026-10-23", "Проверить документы")

    def test_foreign_task_not_visible(self):
        self.add()
        with self.assertRaises(AccessDenied):
            self.service.get(303, 1)

    def test_assignee_starts_and_finishes(self):
        self.add()
        self.service.change_status(202, 1, "doing")
        done = self.service.change_status(202, 1, "done")
        self.assertIsNotNone(done["finished_at"])
        self.assertEqual(done["status"], "done")

    def test_other_assignee_cannot_edit(self):
        self.add()
        with self.assertRaises(AccessDenied):
            self.service.change_status(303, 1, "done")

    def test_completed_task_cannot_be_reopened(self):
        self.add()
        self.service.change_status(202, 1, "done")
        with self.assertRaises(ValidationError):
            self.service.change_status(202, 1, "doing")

    def test_reassign_only_manager(self):
        self.add()
        with self.assertRaises(AccessDenied):
            self.service.reassign(202, 1, 303)
        self.service.reassign(101, 1, 303)
        self.assertEqual(self.service.get(303, 1)["assignee_id"], 303)

    def test_completed_not_reassigned(self):
        self.add()
        self.service.change_status(202, 1, "done")
        with self.assertRaises(ValidationError):
            self.service.reassign(101, 1, 303)

    def test_report(self):
        self.add()
        self.service.create(101, 303, "2026-10-24", "Подготовить инструкцию")
        self.service.change_status(202, 1, "doing")
        report = self.service.report(101)
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["statuses"], {"new": 1, "doing": 1, "done": 0})
        self.assertEqual(report["active_per_member"], {202: 1, 303: 1})

    def test_remind_only_active_near_deadline(self):
        self.add()
        self.service.create(101, 303, "2026-10-20", "Отчёт")
        self.service.create(101, 303, "2026-11-01", "Позже")
        self.service.change_status(303, 2, "done")
        self.assertEqual([x["task_id"] for x in self.service.due_for_reminder(101, 3)], [1])

    def test_reminder_access(self):
        with self.assertRaises(AccessDenied):
            self.service.due_for_reminder(202)

    def test_history_records(self):
        self.add()
        self.service.change_status(202, 1, "doing")
        events = self.service.history(101, 1)
        self.assertEqual([e["event_type"] for e in events], ["created", "status_changed"])

    def test_data_persist_between_instances(self):
        self.add()
        new_service = TaskService(SQLiteStore(self.path), admins={101}, allowed={202},
                                  clock=lambda: self.today)
        self.assertEqual(new_service.get(101, 1)["title"], "Согласовать макет интерфейса")

    def test_invalid_reminder_period(self):
        with self.assertRaises(ValidationError):
            self.service.due_for_reminder(101, 40)

    def test_invalid_role_config(self):
        with self.assertRaises(ValueError):
            TaskService(SQLiteStore(self.path), admins=set(), allowed={202})

    def test_rendering(self):
        task = self.add()
        self.assertIn("Согласовать макет", format_task(task))
        self.assertIn("Всего задач: 1", format_report(self.service.report(101)))

    def test_read_ids(self):
        self.assertEqual(read_ids(" 101, 202,101 "), {101, 202})
        with self.assertRaises(ValueError):
            read_ids("101,abc")

    def test_sql_injection_is_data(self):
        attack = "Отчёт'); DROP TABLE members; --"
        self.service.create(101, 202, "2026-10-23", attack)
        self.assertEqual(len(self.service.members(101)), 3)
        self.assertEqual(self.service.get(202, 1)["title"], attack)


if __name__ == "__main__":
    unittest.main()
