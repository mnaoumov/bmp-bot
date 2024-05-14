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
from telegram.constants import ChatMemberStatus
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
        registration_date: datetime = None,
    ) -> None:
        self.id = id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.registration_date = registration_date

    def to_dict(self) -> dict:
        """
        for JSON serialization
        """

        return {
            "id": self.id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "registration_date": (
                self.registration_date.isoformat() if self.registration_date else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict):
        """
        Parse User object from dictionary
        """
        return cls(
            id=data.get("id"),
            username=data.get("username"),
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            registration_date=(
                datetime.fromisoformat(data["registration_date"])
                if data.get("registration_date")
                else None
            ),
        )


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
    ALLOWED_TOPICS = {"SOS": 113812, "ВІЛЬНА ТЕМА": 113831, "БЛАГОДІЙНІ ВНЕСКИ": 113806}
    allowed_topic_ids = set(ALLOWED_TOPICS.values())
    allowed_topic_links_str: str
    user_ids: set[int]
    users: list[User]
    app: Application
    USERS_JSON_FILE_NAME: str = "users.json"
    KYIV_TIMEZONE_NAME: str = "Europe/Kiev"
    kyiv_timezone: tzinfo
    mandatory_registration_date: datetime

    def main(self) -> None:
        """
        Запускає бота
        """

        self._setup_logger()
        self._init_secrets()

        short_bmp_chat_id = str(self.bmp_chat_id)[-10:]
        self.allowed_topic_links_str = ", ".join(
            [
                f"[{topic_name}](https://t.me/c/${short_bmp_chat_id}/{topic_id})"
                for topic_name, topic_id in self.ALLOWED_TOPICS.items()
            ]
        )

        self.kyiv_timezone = gettz(self.KYIV_TIMEZONE_NAME)
        self.mandatory_registration_date = datetime(
            2024, 6, 1, tzinfo=self.kyiv_timezone
        )

        self.app = ApplicationBuilder().token(self.bot_token).build()
        self.app.add_error_handler(self._handle_error)
        self.app.job_queue.run_once(self._initialize, when=0)
        self.app.add_handler(MessageHandler(None, self._handle_message))

        now_in_kyiv = self._now_in_kyiv()
        next_hour = now_in_kyiv.replace(
            minute=0, second=0, microsecond=0
        ) + relativedelta(hours=1)
        seconds_till_next_hour = (next_hour - now_in_kyiv).total_seconds()
        self.app.job_queue.run_repeating(
            self._run_hourly, interval=3600, first=seconds_till_next_hour
        )

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
        error_message = f"update\n${update}\n\ncaused error\n{exception_str}"
        self.logger.error(error_message)
        await context.bot.send_message(self.developer_chat_id, error_message)

    async def _initialize(self, _: ContextTypes.DEFAULT_TYPE) -> None:
        if os.path.exists(self.USERS_JSON_FILE_NAME):
            with open(
                file=self.USERS_JSON_FILE_NAME, mode="r", encoding="utf8"
            ) as file:
                self.users = [User.from_dict(d) for d in json.load(file)]
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

    def _is_monday_or_friday(self, date: datetime) -> bool:
        monday_day_index = 0
        friday_day_index = 4
        return date.weekday() in [monday_day_index, friday_day_index]

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.message

        if update.edited_message and update.edited_message.forward_date:
            message = update.edited_message

        if message is None:
            self.logger.warning("Cannot handle update without message: %s", update)
            return

        chat = await context.bot.get_chat(self.bmp_chat_id)
        user_id = message.from_user.id
        user = await chat.get_member(user_id)

        if message.chat_id == self.bmp_chat_id:
            self.logger.debug("message: is_night_time = %s", self.is_night_time)
            if (
                user.status == ChatMemberStatus.ADMINISTRATOR
                or user.status == ChatMemberStatus.OWNER
            ):
                self.logger.debug("message: is admin")
                return

            should_remove = False

            if (
                self._now_in_kyiv() >= self.mandatory_registration_date
                and user_id not in self.user_ids
            ):
                should_remove = True

            if self.is_night_time:
                if (
                    message.message_thread_id is None
                    or message.message_thread_id not in self.allowed_topic_ids
                ):
                    should_remove = True

            if should_remove:
                await context.bot.delete_message(
                    chat_id=self.bmp_chat_id, message_id=message.message_id
                )
        else:
            if user.status == ChatMemberStatus.LEFT:
                await context.bot.send_message(
                    chat_id=message.chat_id,
                    text='Ви не є учасником ГО "Батько МАЄ ПРАВО"!',
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
                        registration_date=self._now_in_kyiv(),
                    )
                )

                with open(
                    file=self.USERS_JSON_FILE_NAME, mode="w", encoding="utf8"
                ) as file:
                    json.dump(
                        [user.to_dict() for user in self.users],
                        file,
                        ensure_ascii=False,
                        indent=2,
                    )
                await context.bot.send_message(
                    chat_id=message.chat_id, text="Дякую за реєстрацію!"
                )
            else:
                developer_link = f"[Михайлу](tg://user?id={self.developer_chat_id})"
                await context.bot.send_message(
                    chat_id=message.chat_id,
                    text=f"""Я поки не вмію виконувати команди.
Якщо у вас є пропозиції корисних команд, напишіть, будь ласка, моєму розробнику {developer_link}.""",
                    parse_mode="Markdown",
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
У топіках {self.allowed_topic_links_str} можна писати без часових обмежень.""",
            parse_mode="Markdown",
        )

    def _tomorrow_in_kyiv(self) -> datetime:
        now_in_kyiv = self._now_in_kyiv()
        return now_in_kyiv + relativedelta(days=1)

    async def _end_night_time(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.is_night_time = False
        self.logger.debug("endNightTime: is_night_time = False")
        bot_himself = 1
        registered_users_count = len(self.users) + bot_himself
        chat = await context.bot.get_chat(self.bmp_chat_id)
        users_count = await chat.get_member_count()

        await context.bot.send_message(
            chat_id=self.bmp_chat_id,
            text=f"""Батьки, режим тиші закінчився. Можна вільно писати у всіх топіках до {self.NIGHT_TIME_START_HOUR}:00.""",
            parse_mode="Markdown",
        )

        await context.bot.send_message(
            chat_id=self.bmp_chat_id,
            text=f"""**ВАЖЛИВА ІНФОРМАЦІЯ ВІД АДМІНІСТРАТОРІВ ТЕЛЕГРАМ ЧАТІВ ГО "БАТЬКО МАЄ ПРАВО**"

В Телеграм чатах діє чат-бот @BatkoMaePravoBot.
Бот було розроблено з метою надсилання важливих повідомлень від ГО "Батько МАЄ ПРАВО" для учасників груп.
Натомість, у чат-боті зареєструвалося лише {registered_users_count} учасників групи зі {users_count}.
Це значно погіршує комунікацію.

Адміністрацією ГО "Батько МАЄ ПРАВО" було прийнято рішення ввести правило обов'язкової реєстрації кожного учасника груп у чат-боті @BatkoMaePravoBot.
З 01 червня 2024, учасники групи не зможуть надсилати повідомлення у групу, поки не зареєструються у чат-боті.

Для того, щоб зареєструватися у чат-боті @BatkoMaePravoBot, треба написати йому одне приватне повідомлення з довільним текстом.

У разі виникнення питань щодо роботи чат-бота, просимо звертатись до адміністратора груп і розробника чат-боту [Михайла](tg://user?id={self.developer_chat_id}).

З повагою,
ГО "Батько МАЄ ПРАВО"
""",
            parse_mode="Markdown",
        )

        if self._is_monday_or_friday(self._now_in_kyiv()):
            await context.bot.send_message(
                chat_id=self.bmp_chat_id,
                text="""‼️НАГАДУЄМО ПРО ОБОВ'ЯЗКОВІСТЬ СПЛАТИ БЛАГОДІЙНИХ ВНЕСКІВ ЗГІДНО ПРАВИЛ ГРУПИ. НЕСПЛАТА ВНЕСКІВ ПРИЗВОДИТЬ ДО ВИДАЛЕННЯ З ГРУП ГО БАТЬКО МАЄ ПРАВО.
Правила сплати благодійних внесків за посиланням:
https://t.me/c/1290587927/113806/191878 ‼️
""",
                parse_mode="Markdown",
            )

    async def _run_hourly(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        now_in_kyiv = self._now_in_kyiv()
        hour = now_in_kyiv.hour

        if hour == self.NIGHT_TIME_START_HOUR:
            await self._start_night_time(context)
        elif hour == self._night_time_end_hour(now_in_kyiv):
            await self._end_night_time(context)


if __name__ == "__main__":
    BmpBot().main()
