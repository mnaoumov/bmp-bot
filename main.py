"""
main.py
"""

import asyncio
import json
import logging
import os
import sys
import textwrap
from datetime import datetime, tzinfo
from dateutil.relativedelta import relativedelta
from dateutil.tz import gettz

from dotenv import load_dotenv
from telegram import Bot, Chat, Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes, MessageHandler


class Common:
    """
    Common
    """

    logger: logging.Logger
    bot_token: str
    bmp_chat_id: int
    developer_chat_id: int
    kyiv_timezone: tzinfo
    bot: Bot
    bmp_chat: Chat
    users: list[dict]
    user_ids: set[int]
    is_night_time: bool
    app: Application


common = Common()
NIGHT_TIME_START_HOUR = 22
NIGHT_TIME_END_HOUR = 9
ALLOWED_TOPICS = set(["SOS", "ВІЛЬНА ТЕМА"])


async def _main():
    _init_logger()
    sys.excepthook = _handle_unhandled_exceptions
    _init_secrets()

    common.kyiv_timezone = gettz("Europe/Kiev")

    common.bot = Bot(token=common.bot_token)
    common.bmp_chat = await common.bot.get_chat(common.bmp_chat_id)

    await _load_users()

    common.user_ids = set(user["id"] for user in common.users)

    now_in_kyiv = datetime.now(common.kyiv_timezone)

    common.is_night_time = (
        now_in_kyiv.hour >= NIGHT_TIME_START_HOUR
        or now_in_kyiv.hour < NIGHT_TIME_END_HOUR
    )

    app = ApplicationBuilder().token(common.bot_token).build()
    common.app = app
    app.add_handler(MessageHandler(None, _message))

    app.job_queue.run_once(_start_night_time, _get_next_time(NIGHT_TIME_START_HOUR))
    app.job_queue.run_once(_end_night_time, _get_next_time(NIGHT_TIME_END_HOUR))
    await asyncio.to_thread(_run_polling_with_new_event_loop)


def _init_logger():
    logger = logging.getLogger("my_logger")
    common.logger = logger
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(filename="!log.txt", encoding="utf-8")

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def _handle_unhandled_exceptions(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    common.logger.error(
        "Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback)
    )


def _init_secrets():
    load_dotenv()
    common.bot_token = _get_env("BOT_TOKEN")
    common.bmp_chat_id = int(_get_env("BMP_CHAT_ID"))
    common.developer_chat_id = int(_get_env("DEVELOPER_CHAT_ID"))


def _get_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Environment variable {key} is not set")
    return value


def _get_next_time(hour: int) -> datetime:
    kyiv_timezone = gettz("Europe/Kiev")
    now_in_kyiv = datetime.now(kyiv_timezone)
    next_time = now_in_kyiv.replace(hour=hour, minute=0, second=0, microsecond=0)
    if next_time <= now_in_kyiv:
        next_time += relativedelta(days=1)
    return next_time


async def _load_users():
    if os.path.exists("users.json"):
        with open(file="users.json", mode="r", encoding="utf8") as file:
            common.users = json.load(file)
    else:
        common.users = []

    filtered_users = []

    for user in common.users:
        member = await common.bmp_chat.get_member(user["id"])
        if member.status != "left":
            filtered_users.append(user)

    if len(filtered_users) != len(common.users):
        common.users = filtered_users
        _save_users()


def _save_users() -> None:
    with open(file="users.json", mode="w", encoding="utf8") as file:
        json.dump(common.users, file, ensure_ascii=False, indent=2)


async def _message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    if update.message.chat_id == common.bmp_chat_id:
        if common.is_night_time and (
            update.message.reply_to_message is None
            or update.message.reply_to_message.forum_topic_created.name
            not in ALLOWED_TOPICS
        ):
            await context.bot.delete_message(
                chat_id=common.bmp_chat_id, message_id=update.message.message_id
            )
    else:
        chat = await context.bot.get_chat(common.bmp_chat_id)
        user_id = update.message.from_user.id
        user = await chat.get_member(user_id)

        if user.status == "left":
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text='Ви не є активістом ГО "Батько МАЄ ПРАВО"',
                parse_mode="Markdown",
            )
            return

        if user_id not in common.user_ids:
            common.user_ids.add(user_id)
            common.users.append(
                {
                    "id": user_id,
                    "username": update.message.from_user.username,
                    "first_name": update.message.from_user.first_name,
                    "last_name": update.message.from_user.last_name,
                }
            )
            _save_users()
            await context.bot.send_message(
                chat_id=update.message.chat_id, text="Дякую за реєстрацію"
            )
        else:
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=textwrap.dedent(
                    f"""
                        Я поки не вмію виконувати команди.
                        Якщо у вас є пропозиції корисних команд, напишіть, будь ласка, моєму розробнику [Михайлу](tg://user?id={common.developer_chat_id})
                    """
                ),
                parse_mode="Markdown",
            )


async def _start_night_time(context: ContextTypes.DEFAULT_TYPE) -> None:
    common.is_night_time = True
    await context.bot.send_message(
        chat_id=common.bmp_chat_id,
        text=textwrap.dedent(
            """
                Батьки, оголошується режим тиші з 22:00 до 9:00. Всі повідомлення у цей час будуть автоматично видалятися.
                У топіках [SOS](https://t.me/c/1290587927/113812) і [ВІЛЬНА ТЕМА](https://t.me/c/1290587927/113831) можна писати без часових обмежень.
            """
        ),
        parse_mode="Markdown",
    )
    common.app.job_queue.run_once(
        _start_night_time, _get_next_time(NIGHT_TIME_START_HOUR)
    )


async def _end_night_time(context: ContextTypes.DEFAULT_TYPE) -> None:
    common.is_night_time = False
    bot_himself = 1
    registered_users_count = len(common.users) + bot_himself
    chat = await context.bot.get_chat(common.bmp_chat_id)
    users_count = await chat.get_member_count()
    text_message = textwrap.dedent(
        f"""
            Батьки, режим тиші закінчився.
            Для того покращити роботу бота, необхідно, щоб кожен активіст написав йому хоча б раз особисте повідомлення.
            Будь ласка зробіть це. На разі це зробило лише {registered_users_count} активістів із {users_count}.
            Дякую за розуміння.
        """
    )
    await context.bot.send_message(
        chat_id=common.bmp_chat_id,
        text=text_message,
        parse_mode="Markdown",
    )
    common.app.job_queue.run_once(_end_night_time, _get_next_time(NIGHT_TIME_END_HOUR))


def _run_polling_with_new_event_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(common.app.run_polling())


if __name__ == "__main__":
    asyncio.run(_main())
