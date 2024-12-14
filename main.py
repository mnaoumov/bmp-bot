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
from telegram import Chat, ChatMember, ChatMemberLeft, Update, User as TelegramUser, Bot
from telegram.constants import ChatMemberStatus
from telegram.ext import Application, ApplicationBuilder, ContextTypes, MessageHandler
from telegram.error import BadRequest
import asyncio


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
        bot_registration_date: datetime = None,
        group_registration_date: datetime = None,
        is_active: bool = None,
    ) -> None:
        self.id = id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.bot_registration_date = bot_registration_date
        self.group_registration_date = group_registration_date
        self.is_active = is_active

    def to_dict(self) -> dict:
        """
        for JSON serialization
        """

        return {
            "id": self.id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "bot_registration_date": (
                self.bot_registration_date.isoformat()
                if self.bot_registration_date
                else None
            ),
            "group_registration_date": (
                self.group_registration_date.isoformat()
                if self.group_registration_date
                else None
            ),
            "is_active": self.is_active,
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
            bot_registration_date=(
                datetime.fromisoformat(data["bot_registration_date"])
                if data.get("bot_registration_date")
                else None
            ),
            group_registration_date=(
                datetime.fromisoformat(data["group_registration_date"])
                if data.get("group_registration_date")
                else None
            ),
            is_active=data.get("is_active"),
        )

class ForwardedMessage:
    def __init__(self, message_id: int, message_thread_id: int | None):
        self.message_id = message_id
        self.message_thread_id = message_thread_id

    @classmethod
    def from_dict(cls, data: dict):
        """
        Parse ForwardedMessage object from dictionary
        """
        return cls(
            message_id =data.get("message_id"),
            message_thread_id=data.get("message_thread_id")
        )

    def to_dict(self) -> dict:
        """
        for JSON serialization
        """

        return {
            "message_id": self.message_id,
            "message_thread_id": self.message_thread_id
        }


class TelegramHandler(logging.Handler):
    def __init__(self, bot: Bot, chat_id: int):
        super().__init__()
        self.bot: Bot = bot
        self.chat_id: int = chat_id
        self.queue: asyncio.Queue = asyncio.Queue()
        self.task: asyncio.Task | None = None

    def emit(self, record: logging.LogRecord) -> None:
        log_entry: str = self.format(record)
        asyncio.create_task(self.queue.put(log_entry))
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.send_logs())

    async def send_logs(self) -> None:
        while True:
            try:
                log_entry = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                await self.bot.send_message(chat_id=self.chat_id, text=f"Log: {log_entry}")
                self.queue.task_done()
            except asyncio.TimeoutError:
                if self.queue.empty():
                    break

    def close(self) -> None:
        if self.task:
            self.task.cancel()
        super().close()


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
    ALLOWED_TOPICS = {
        "SOS": 113812,
        "ВІЛЬНА ТЕМА": 113831,
        "БЛАГОДІЙНІ ВНЕСКИ": 113806,
        "БАЗА ЗНАНЬ": 113810,
        "НІЧНІ ПОВІДОМЛЕННЯ": 225231
    }
    allowed_topic_ids = set(ALLOWED_TOPICS.values())
    allowed_topic_links_str: str
    bot_registered_user_ids: set[int]
    users: list[User]
    forwarded_messages: list[ForwardedMessage]
    app: Application
    USERS_JSON_FILE_NAME: str = "users.json"
    FORWARDED_MESSAGES_JSON_FILE_NAME: str = "forwarded_messages.json"
    KYIV_TIMEZONE_NAME: str = "Europe/Kiev"
    kyiv_timezone: tzinfo
    mandatory_registration_date: datetime
    BOT_TOPIC_ID: int = 207968
    night_topic_link: str
    silence_rule_link: str = "https://t.me/c/1290587927/1/207964"
    registration_rule_link: str = "https://t.me/c/1290587927/1/207446"
    payments_rule_link: str = "https://t.me/c/1290587927/113806/224345"

    def main(self) -> None:
        """
        Запускає бота
        """

        self._setup_logger()
        self._init_secrets()

        self.allowed_topic_links_str = ", ".join(
            [self._get_topic_link(topic_name) for topic_name in self.ALLOWED_TOPICS if topic_name != "НІЧНІ ПОВІДОМЛЕННЯ"]
        )

        self.night_topic_link = self._get_topic_link("НІЧНІ ПОВІДОМЛЕННЯ")

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

    def _get_topic_link(self, topic_name: str) -> str:
        short_bmp_chat_id = str(self.bmp_chat_id)[-10:]
        topic_id = self.ALLOWED_TOPICS[topic_name]
        return f"[{topic_name}](https://t.me/c/{short_bmp_chat_id}/{topic_id})"

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

    async def _initialize(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Add Telegram handler for logging
        telegram_handler: TelegramHandler = TelegramHandler(context.bot, self.developer_chat_id)
        telegram_handler.setLevel(logging.INFO)
        telegram_formatter: logging.Formatter = logging.Formatter("%(levelname)s - %(message)s")
        telegram_handler.setFormatter(telegram_formatter)
        self.logger.addHandler(telegram_handler)

        if os.path.exists(self.USERS_JSON_FILE_NAME):
            with open(
                file=self.USERS_JSON_FILE_NAME, mode="r", encoding="utf8"
            ) as file:
                self.users: list[User] = [User.from_dict(d) for d in json.load(file)]
        else:
            self.users: list[User] = []

        self.bot_registered_user_ids: set[int] = set(
            user.id
            for user in self.users
            if user.is_active and user.bot_registration_date is not None
        )
        now_in_kyiv: datetime = self._now_in_kyiv()
        self.is_night_time: bool = (
            now_in_kyiv.hour >= self.NIGHT_TIME_START_HOUR
            or now_in_kyiv.hour < self._night_time_end_hour(now_in_kyiv)
        )
        self.logger.debug("Init: is_night_time = %s", self.is_night_time)

        chat: Chat = await context.bot.get_chat(self.bmp_chat_id)
        await self._refresh_users(chat)

        if os.path.exists(self.FORWARDED_MESSAGES_JSON_FILE_NAME):
            with open(
                file=self.FORWARDED_MESSAGES_JSON_FILE_NAME, mode="r", encoding="utf8"
            ) as file:
                self.forwarded_messages: list[ForwardedMessage] = [ForwardedMessage.from_dict(d) for d in json.load(file)]
        else:
            self.forwarded_messages: list[ForwardedMessage] = []


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
        message = update.message or update.edited_message

        if message is None:
            self.logger.warning("Cannot handle update without message: %s", update)
            return

        chat = await context.bot.get_chat(self.bmp_chat_id)
        user_id = message.from_user.id
        chat_member = await self._get_chat_member(chat, user_id)

        if message.chat_id == self.bmp_chat_id:
            self.logger.debug("message: is_night_time = %s", self.is_night_time)
            if message.new_chat_members:
                for new_member in message.new_chat_members:
                    self.logger.info("New user registered: %s", new_member.id)
                    user_link = self._make_user_link(new_member)

                    await context.bot.send_message(
                        chat_id=self.bmp_chat_id,
                        text=(
                            f'Шановний {user_link}, вітаємо у чаті ГО "Батько МАЄ ПРАВО"!\n'
                            f"Відповідно до [правил]({self.registration_rule_link}) чату, "
                            "будь ласка, зареєструйтеся у чат-боті.\n"
                            "Ви не зможете писати у чаті поки не зареєструєтеся.\n"
                            "Для того, щоб зареєструватися у чат-боті @BatkoMaePravoBot, треба написати йому одне приватне повідомлення з довільним текстом."
                        ),
                        parse_mode="Markdown",
                    )

                    user = next((u for u in self.users if u.id == new_member.id), None)

                    if user is None:
                        self.users.append(
                            User(
                                id=new_member.id,
                                username=new_member.username,
                                first_name=new_member.first_name,
                                last_name=new_member.last_name,
                                group_registration_date=self._now_in_kyiv(),
                                bot_registration_date=None,
                                is_active=True,
                            )
                        )
                    else:
                        user.is_active = True
                        user.group_registration_date = self._now_in_kyiv()

                self._update_users_json()

                return

            if (self._is_admin(chat_member)):
                self.logger.debug("message: is admin")
                return

            should_remove = False
            should_redirect = True

            if (
                self._now_in_kyiv() >= self.mandatory_registration_date
                and user_id not in self.bot_registered_user_ids
            ):
                should_remove = True
                should_redirect = False

            date = message.date or message.forward_date
            diff = self._now_in_kyiv() - date
            if diff.total_seconds() > 60:
                return

            if self.is_night_time:
                if (
                    message.message_thread_id is None
                    or message.message_thread_id not in self.allowed_topic_ids
                ):
                    should_remove = True

            if should_remove:
                user_link = self._make_user_link(message.from_user)

                if should_redirect:
                    forwarded_message = await context.bot.forward_message(
                        chat_id=self.bmp_chat_id,
                        from_chat_id=self.bmp_chat_id,
                        message_id=message.message_id,
                        message_thread_id=self.ALLOWED_TOPICS["НІЧНІ ПОВІДОМЛЕННЯ"],
                    )

                    self.forwarded_messages.append(ForwardedMessage(forwarded_message.message_id, message.message_thread_id if message.is_topic_message else None))
                    self._update_forwarded_messages_json()

                    await context.bot.send_message(
                        chat_id=self.bmp_chat_id,
                        message_thread_id=self.BOT_TOPIC_ID,
                        text=(
                            f"Шановний {user_link}, ваше повідомлення було переправлено у топік "
                            f"{self.night_topic_link}, оскільки ви намагалися написати у "
                            "недозволений топік під час режиму тиші.\n"
                            f"Будь ласка, дотримуйтесь [правил]({self.silence_rule_link}) чату."
                        ),
                        parse_mode="Markdown",
                    )
                else:
                    await context.bot.send_message(
                        chat_id=self.bmp_chat_id,
                        message_thread_id=self.BOT_TOPIC_ID,
                        text=(
                            f"Шановний {user_link}, ваше повідомлення було видалене, "
                            "оскільки ви ще не зареєструвалися у чат-боті.\n"
                            f"Будь ласка, дотримуйтесь [правил]({self.registration_rule_link}) "
                            "чату.\n"
                            "Для того, щоб зареєструватися у чат-боті @BatkoMaePravoBot, треба написати йому одне приватне повідомлення з довільним текстом."
                        ),
                        parse_mode="Markdown",
                    )

                await context.bot.delete_message(
                    chat_id=self.bmp_chat_id, message_id=message.message_id
                )
        else:
            if not self._is_active(chat_member):
                await context.bot.send_message(
                    chat_id=message.chat_id,
                    text='Ви не є учасником ГО "Батько МАЄ ПРАВО"!',
                    parse_mode="Markdown",
                )
                return

            if user_id not in self.bot_registered_user_ids:
                self.bot_registered_user_ids.add(user_id)
                chat_member = next((u for u in self.users if u.id == user_id))
                chat_member.bot_registration_date = self._now_in_kyiv()
                self._update_users_json()
                await context.bot.send_message(
                    chat_id=message.chat_id, text="Дякую за реєстрацію!"
                )
            else:
                developer_link = f"[Михайлу](tg://user?id={self.developer_chat_id})"
                await context.bot.send_message(
                    chat_id=message.chat_id,
                    text=(
                        "Я поки не вмію виконувати команди.\n"
                        "Якщо у вас є пропозиції корисних команд, напишіть, будь ласка, "
                        f"моєму розробнику {developer_link}."
                    ),
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
            message_thread_id=self.BOT_TOPIC_ID,
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

        chat = await context.bot.get_chat(self.bmp_chat_id)
        await self._refresh_users(chat)

        active_users = [user for user in self.users if user.is_active]
        bot_registered_users = [
            user for user in active_users if user.bot_registration_date is not None
        ]
        bot_registered_users_count = len(bot_registered_users)
        active_users_count = len(active_users)

        await context.bot.send_message(
            chat_id=self.bmp_chat_id,
            message_thread_id=self.BOT_TOPIC_ID,
            text=(
                "Батьки, режим тиші закінчився. Можна вільно писати у всіх "
                f"топіках до {self.NIGHT_TIME_START_HOUR}:00."
            ),
            parse_mode="Markdown",
        )

        await context.bot.send_message(
            chat_id=self.bmp_chat_id,
            message_thread_id=self.BOT_TOPIC_ID,
            text=f"""*ВАЖЛИВА ІНФОРМАЦІЯ ВІД АДМІНІСТРАТОРІВ ТЕЛЕГРАМ ЧАТІВ ГО "БАТЬКО МАЄ ПРАВО*"

В Телеграм чатах діє чат-бот @BatkoMaePravoBot.
Бот було розроблено з метою надсилання важливих повідомлень від ГО "Батько МАЄ ПРАВО" для учасників груп.
Натомість, у чат-боті зареєструвалося лише {bot_registered_users_count} учасників групи зі {active_users_count}.
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

        bot_unregistered_users = [
            user for user in active_users if user.bot_registration_date is None
        ]
        bot_unregistered_user_links = ", ".join(
            [self._make_user_link(user) for user in bot_unregistered_users]
        )

        await context.bot.send_message(
            chat_id=self.bmp_chat_id,
            message_thread_id=self.BOT_TOPIC_ID,
            text=f"Шановні {bot_unregistered_user_links}!\nПросимо зареєструватися у чат-боті!",
            parse_mode="Markdown",
        )

        if self._is_monday_or_friday(self._now_in_kyiv()):
            await context.bot.send_message(
                chat_id=self.bmp_chat_id,
                text=(
                    "‼️НАГАДУЄМО ПРО ОБОВ'ЯЗКОВІСТЬ СПЛАТИ БЛАГОДІЙНИХ ВНЕСКІВ ЗГІДНО "
                    "ПРАВИЛ ГРУПИ. НЕСПЛАТА ВНЕСКІВ ПРИЗВОДИТЬ ДО ВИДАЛЕННЯ З ГРУП "
                    "ГО БАТЬКО МАЄ ПРАВО.\n"
                    "Правила сплати благодійних внесків за посиланням:\n"
                    f"{self.payments_rule_link} ‼️"
                ),
                parse_mode="Markdown",
            )

        for forwarded_message in self.forwarded_messages:
            await context.bot.forward_message(
                chat_id=self.bmp_chat_id,
                from_chat_id=self.bmp_chat_id,
                message_id=forwarded_message.message_id,
                message_thread_id=forwarded_message.message_thread_id
            )
        self.forwarded_messages = []
        self._update_forwarded_messages_json()

    async def _run_hourly(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        now_in_kyiv = self._now_in_kyiv()
        hour = now_in_kyiv.hour

        if hour == self.NIGHT_TIME_START_HOUR:
            await self._start_night_time(context)
        elif hour == self._night_time_end_hour(now_in_kyiv):
            await self._end_night_time(context)

    def _update_users_json(self) -> None:
        with open(file=self.USERS_JSON_FILE_NAME, mode="w", encoding="utf8") as file:
            json.dump(
                [user.to_dict() for user in self.users],
                file,
                ensure_ascii=False,
                indent=2,
            )

    def _update_forwarded_messages_json(self) -> None:
        with open(file=self.FORWARDED_MESSAGES_JSON_FILE_NAME, mode="w", encoding="utf8") as file:
            json.dump(
                [forwarded_message.to_dict() for forwarded_message in self.forwarded_messages],
                file,
                ensure_ascii=False,
                indent=2,
            )

    def _make_user_link(self, user: User) -> str:
        user_name = user.username or user.first_name or "Учасник"
        return f"[{user_name}](tg://user?id={user.id})"

    async def _get_chat_member(self, chat: Chat, user_id: str) -> ChatMember:
        try:
            chat_member = await chat.get_member(user_id)
            return chat_member
        except BadRequest as e:
            if e.message == "Member not found":
                return ChatMemberLeft(
                    TelegramUser(id=user_id, first_name="User not found", is_bot=False)
                )
            raise e
        
    async def _refresh_users(self, chat) -> None:
        for user in self.users:
            if not user.is_active:
                continue
            chat_member = await self._get_chat_member(chat, user.id)
            if not self._is_active(chat_member):
                user.is_active = False
        self._update_users_json()

    def _is_admin(self, chat_member: ChatMember) -> bool:
        return chat_member.status == ChatMemberStatus.ADMINISTRATOR or chat_member.status == ChatMemberStatus.OWNER
    
    def _is_active(self, chat_member: ChatMember) -> bool:
        return self._is_admin(chat_member) or chat_member.status == ChatMemberStatus.MEMBER

if __name__ == "__main__":
    BmpBot().main()
