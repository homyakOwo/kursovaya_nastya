"""Интерфейс Telegram (aiogram 3); используется только при реальном запуске."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from .config import Settings
from .formatting import format_report, format_task
from .service import AccessDenied, TaskService, ValidationError
from .storage import SQLiteStore

router = Router()
service: TaskService  # создаётся при старте процесса

HELP = (
    "Команды (в личном чате):\n"
    "/start — регистрация разрешённого участника\n"
    "/id — показать собственный Telegram ID\n"
    "/tasks — мои задачи\n"
    "/doing НОМЕР — взять задачу в работу\n"
    "/done НОМЕР — завершить задачу\n"
    "/history НОМЕР — история доступной задачи\n"
    "Для руководителя:\n"
    "/members — список участников\n"
    "/new ID | ГГГГ-ММ-ДД | Название — создать задачу\n"
    "/all — все задачи\n"
    "/assign НОМЕР ID — назначить нового исполнителя\n"
    "/report — сводка по задачам\n"
    "/remind — напоминания о просроченных и ближайших задачах"
)


def actor_id(message: Message) -> int:
    if message.from_user is None:
        raise ValidationError("Не удалось определить отправителя")
    return message.from_user.id


def private_only(message: Message) -> None:
    if message.chat.type != "private":
        raise AccessDenied("Отправьте команду боту в личном чате")


async def respond(message: Message, work) -> None:
    try:
        private_only(message)
        await work()
    except (AccessDenied, ValidationError, ValueError) as err:
        await message.answer(f"Не выполнено: {err}")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    async def run() -> None:
        user = message.from_user
        if user is None:
            raise ValidationError("Нет идентификатора пользователя")
        service.register(user.id, user.full_name, user.username or "")
        await message.answer("Регистрация выполнена.\n" + HELP)
    await respond(message, run)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await respond(message, lambda: message.answer(HELP))


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await respond(message, lambda: message.answer(f"Ваш Telegram ID: {actor_id(message)}"))


@router.message(Command("tasks"))
async def cmd_tasks(message: Message) -> None:
    async def run() -> None:
        tasks = service.my_tasks(actor_id(message))
        await message.answer("\n\n".join(map(format_task, tasks))[:3900] if tasks else "Задач пока нет")
    await respond(message, run)


@router.message(Command("all"))
async def cmd_all(message: Message) -> None:
    async def run() -> None:
        tasks = service.all_tasks(actor_id(message))
        await message.answer("\n\n".join(map(format_task, tasks))[:3900] if tasks else "Список задач пуст")
    await respond(message, run)


@router.message(Command("members"))
async def cmd_members(message: Message) -> None:
    async def run() -> None:
        members = service.members(actor_id(message))
        lines = [f"{m['user_id']} — {m['display_name']}" for m in members]
        await message.answer("\n".join(lines)[:3900] if lines else "Участников пока нет")
    await respond(message, run)


@router.message(Command("new"))
async def cmd_new(message: Message, bot: Bot) -> None:
    async def run() -> None:
        raw = (message.text or "").partition(" ")[2]
        parts = [x.strip() for x in raw.split("|", 2)]
        if len(parts) != 3:
            raise ValidationError("Формат: /new ID | ГГГГ-ММ-ДД | Название")
        task = service.create(actor_id(message), int(parts[0]), parts[1], parts[2])
        await message.answer("Задача создана:\n" + format_task(task))
        try:
            await bot.send_message(task["assignee_id"], "Вам назначена задача:\n" + format_task(task))
        except Exception:
            logging.exception("Не удалось отправить уведомление исполнителю")
            await message.answer("Задача сохранена, но уведомление не доставлено")
    await respond(message, run)


@router.message(Command("doing", "done"))
async def cmd_status(message: Message) -> None:
    async def run() -> None:
        bits = (message.text or "").split()
        if len(bits) != 2:
            raise ValidationError("Укажите номер задачи: /doing 1 или /done 1")
        status = "done" if bits[0].split("@")[0] == "/done" else "doing"
        task = service.change_status(actor_id(message), int(bits[1]), status)
        await message.answer("Статус изменён:\n" + format_task(task))
    await respond(message, run)


@router.message(Command("assign"))
async def cmd_assign(message: Message, bot: Bot) -> None:
    async def run() -> None:
        bits = (message.text or "").split()
        if len(bits) != 3:
            raise ValidationError("Формат: /assign НОМЕР ID")
        task = service.reassign(actor_id(message), int(bits[1]), int(bits[2]))
        await message.answer("Исполнитель изменён:\n" + format_task(task))
        try:
            await bot.send_message(task["assignee_id"], "Вам передана задача:\n" + format_task(task))
        except Exception:
            logging.exception("Не удалось отправить уведомление после переназначения")
            await message.answer("Изменение сохранено, но уведомление не доставлено")
    await respond(message, run)


@router.message(Command("report"))
async def cmd_report(message: Message) -> None:
    async def run() -> None:
        await message.answer(format_report(service.report(actor_id(message))))
    await respond(message, run)


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    async def run() -> None:
        bits = (message.text or "").split()
        if len(bits) != 2:
            raise ValidationError("Формат: /history НОМЕР")
        rows = service.history(actor_id(message), int(bits[1]))
        lines = [f"{r['occurred_at']} {r['event_type']} {r['details']}" for r in rows]
        await message.answer("\n".join(lines)[:3900] or "Событий нет")
    await respond(message, run)


@router.message(Command("remind"))
async def cmd_remind(message: Message, bot: Bot) -> None:
    async def run() -> None:
        tasks = service.due_for_reminder(actor_id(message))
        delivered = 0
        for task in tasks:
            try:
                await bot.send_message(task["assignee_id"],
                                       "Напоминание о сроке:\n" + format_task(task))
                delivered += 1
            except Exception:
                logging.exception("Не удалось отправить напоминание для задачи %s", task["task_id"])
        await message.answer(f"Напоминания: отправлено {delivered} из {len(tasks)}")
    await respond(message, run)


async def main() -> None:
    global service
    settings = Settings.from_env()
    service = TaskService(SQLiteStore(settings.db_path),
                          admins=set(settings.admin_ids), allowed=set(settings.allowed_user_ids))
    bot = Bot(settings.token)
    dp = Dispatcher()
    dp.include_router(router)
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
