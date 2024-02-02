"""
main.py
"""

import json
import logging
import os
import sys
import traceback
from datetime import datetime, tzinfo

from dateutil.relativedelta import relativedelta
from dateutil.tz import gettz
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes, MessageHandler


class User:
    """
    Користувач
    """

    def __init__(
        self,
        # pylint: disable=W0622
        id: int = None,
        username: str = None,
        first_name: str = None,
        last_name: str = None,
    ) -> None:
        self.id = id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name

    def to_dict(self) -> dict:
        """
        for JSON serialization
        """

        return {
            "id": self.id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name
        }

class BmpBot:
    """
    Бот для чату ГО "Батько МАЄ ПРАВО"
    """

    NIGHT_TIME_START_HOUR = 22
    NIGHT_TIME_END_HOUR_WEEKDAY = 8
    NIGHT_TIME_END_HOUR_WEEKEND = 9
    logger: logging.Logger
    is_night_time: bool
    bot_token: str
    bmp_chat_id: int
    developer_chat_id: int
    ALLOWED_TOPICS = set(["SOS", "ВІЛЬНА ТЕМА"])
    user_ids: set[int]
    users: list[User]
    app: Application
    SOS_LINK: str = "[SOS](https://t.me/c/1290587927/113812)"
    FREE_TOPIC_LINK: str = "[ВІЛЬНА ТЕМА](https://t.me/c/1290587927/113831)"
    USERS_JSON_FILE_NAME: str = "users.json"
    KYIV_TIMEZONE_NAME: str = "Europe/Kiev"
    kyiv_timezone: tzinfo

    def main(self) -> None:
        """
        Запускає бота
        """

        self._setup_logger()
        self._init_secrets()

        self.kyiv_timezone = gettz(self.KYIV_TIMEZONE_NAME)

        self.app = ApplicationBuilder().token(self.bot_token).build()
        self.app.add_error_handler(self._handle_error)
        self.app.job_queue.run_once(self._initialize, when=0)
        self.app.add_handler(MessageHandler(None, self._handle_message))
        self._schedule_start_night_time()
        self._schedule_end_night_time()
        self.app.run_polling()

    def _setup_logger(self) -> None:
        self.logger = logging.getLogger("my_logger")
        self.logger.setLevel(logging.DEBUG)
        handler = logging.FileHandler(filename="!log.txt", encoding="utf-8")

        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        sys.excepthook = self._handle_unhandled_exceptions

    def _init_secrets(self) -> None:
        load_dotenv()
        self.bot_token = self._get_env("BOT_TOKEN")
        self.bmp_chat_id = int(self._get_env("BMP_CHAT_ID"))
        self.developer_chat_id = int(self._get_env("DEVELOPER_CHAT_ID"))

    async def _handle_error(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        exception_str = "".join(
            traceback.format_exception(
                type(context.error), context.error, context.error.__traceback__
            )
        )
        self.logger.error('Update "%s" caused error "%s"', update, exception_str)

    async def _initialize(self, _: ContextTypes.DEFAULT_TYPE) -> None:
        if os.path.exists(self.USERS_JSON_FILE_NAME):
            with open(
                file=self.USERS_JSON_FILE_NAME, mode="r", encoding="utf8"
            ) as file:
                self.users = [User(**d) for d in json.load(file)]
        else:
            self.users = []

        self.user_ids = set(user.id for user in self.users)
        now_in_kyiv = self._now_in_kyiv()
        self.is_night_time = (
            now_in_kyiv.hour >= self.NIGHT_TIME_START_HOUR
            or now_in_kyiv.hour < self._night_time_end_hour(now_in_kyiv)
        )
        self.logger.debug("Init: is_night_time = %s", self.is_night_time)

    def _handle_unhandled_exceptions(self, exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        self.logger.error(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback)
        )

    def _now_in_kyiv(self) -> datetime:
        return datetime.now(self.kyiv_timezone)

    def _get_env(self, key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise EnvironmentError(f"Environment variable {key} is not set")
        return value

    def _night_time_end_hour(self, date: datetime) -> int:
        if self._is_weekend(date):
            return self.NIGHT_TIME_END_HOUR_WEEKEND
        return self.NIGHT_TIME_END_HOUR_WEEKDAY

    def _is_weekend(self, date: datetime) -> bool:
        saturday_day_index = 5
        sunday_day_index = 6
        return date.weekday() in [saturday_day_index, sunday_day_index]

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.message or update.edited_message
        if message is None:
            self.logger.warning("Cannot handle update without message: %s", update)
            return
        if message.chat_id == self.bmp_chat_id:
            self.logger.debug("message: is_night_time = %s", self.is_night_time)
            if self.is_night_time:
                if (
                    message.reply_to_message is None
                    or message.reply_to_message.forum_topic_created.name
                    not in self.ALLOWED_TOPICS
                ):
                    await context.bot.delete_message(
                        chat_id=self.bmp_chat_id, message_id=message.message_id
                    )
        else:
            chat = await context.bot.get_chat(self.bmp_chat_id)
            user_id = message.from_user.id
            user = await chat.get_member(user_id)

            if user.status == "left":
                await context.bot.send_message(
                    chat_id=message.chat_id,
                    text='Ви не є активістом ГО "Батько МАЄ ПРАВО"',
                    parse_mode="Markdown",
                )
                return

            if user_id not in self.user_ids:
                self.user_ids.add(user_id)
                self.users.append(
                    User(
                        id=user_id,
                        username=message.from_user.username,
                        first_name=message.from_user.first_name,
                        last_name=message.from_user.last_name,
                    )
                )

                with open(
                    file=self.USERS_JSON_FILE_NAME, mode="w", encoding="utf8"
                ) as file:
                    json.dump([user.to_dict() for user in self.users], file, ensure_ascii=False, indent=2)
                await context.bot.send_message(
                    chat_id=message.chat_id, text="Дякую за реєстрацію"
                )
            else:
                developer_link = f"[Михайлу](tg://user?id={self.developer_chat_id})"
                await context.bot.send_message(
                    chat_id=message.chat_id,
                    text=f"""Я поки не вмію виконувати команди.
Якщо у вас є пропозиції корисних команд, напишіть, будь ласка, моєму розробнику {developer_link}""",
                    parse_mode="Markdown",
                )

    def _schedule_start_night_time(self) -> None:
        self.app.job_queue.run_once(
            self._start_night_time, self._get_next_time(self.NIGHT_TIME_START_HOUR)
        )

    async def _start_night_time(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.is_night_time = True
        self.logger.debug("startNightTime: is_night_time = True")
        tomorrow_in_kyiv = self._tomorrow_in_kyiv()
        night_time_end_hour = self._night_time_end_hour(tomorrow_in_kyiv)

        if self._is_weekend(tomorrow_in_kyiv):
            day_type = "вихідний"
        else:
            day_type = "робочий"

        schedule_str = f"з {self.NIGHT_TIME_START_HOUR}:00 до {night_time_end_hour}:00"
        await context.bot.send_message(
            chat_id=self.bmp_chat_id,
            text=f"""Батьки, оголошується режим тиші {schedule_str} ({day_type} день).
Всі повідомлення у цей час будуть автоматично видалятися.
У топіках {self.SOS_LINK} і {self.FREE_TOPIC_LINK} можна писати без часових обмежень""",
            parse_mode="Markdown",
        )
        self._schedule_start_night_time()

    def _tomorrow_in_kyiv(self) -> datetime:
        now_in_kyiv = self._now_in_kyiv()
        return now_in_kyiv + relativedelta(days=1)

    def _get_next_time(self, hour: int) -> datetime:
        now_in_kyiv = self._now_in_kyiv()
        next_time = now_in_kyiv.replace(hour=hour, minute=0, second=0, microsecond=0)
        if next_time <= now_in_kyiv:
            next_time += relativedelta(days=1)
        return next_time

    def _schedule_end_night_time(self) -> None:
        now_in_kyiv = self._now_in_kyiv()
        night_time_end_hour = self._night_time_end_hour(now_in_kyiv)
        next_time = self._get_next_time(night_time_end_hour)

        if next_time < now_in_kyiv:
            tomorrow_in_kyiv = self._tomorrow_in_kyiv()
            night_time_end_hour = self._night_time_end_hour(tomorrow_in_kyiv)
            next_time = self._get_next_time(night_time_end_hour)
            if next_time.day == now_in_kyiv.day:
                next_time += relativedelta(days=1)

        self.app.job_queue.run_once(self._end_night_time, next_time)

    async def _end_night_time(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.is_night_time = False
        self.logger.debug("endNightTime: is_night_time = False")
        bot_himself = 1
        registered_users_count = len(self.users) + bot_himself
        chat = await context.bot.get_chat(self.bmp_chat_id)
        users_count = await chat.get_member_count()
        await context.bot.send_message(
            chat_id=self.bmp_chat_id,
            text=f"""Батьки, режим тиші закінчився
Для того покращити роботу бота, необхідно, щоб кожен активіст написав йому хоча б раз особисте повідомлення. Будь ласка зробіть це. На разі це зробило лише {registered_users_count} активістів із {users_count}.
Дякую за розуміння""",
            parse_mode="Markdown",
        )
        self._schedule_end_night_time()


if __name__ == "__main__":
    BmpBot().main()
