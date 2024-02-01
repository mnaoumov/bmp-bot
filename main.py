"""
main.py
"""

import json
import logging
import os
import sys
from datetime import datetime

from dateutil.relativedelta import relativedelta
from dateutil.tz import gettz
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes, MessageHandler


class BmpBot:
    """
    Бот для чату ГО "Батько МАЄ ПРАВО"
    """

    NIGHT_TIME_START_HOUR = 22
    NIGHT_TIME_END_HOUR = 9
    logger: logging.Logger
    is_night_time: bool
    bot_token: str
    bmp_chat_id: int
    developer_chat_id: int
    allowed_topics = set(["SOS", "ВІЛЬНА ТЕМА"])
    user_ids: set[int]
    users: list[dict]
    app: Application
    SOS_LINK = "[SOS](https://t.me/c/1290587927/113812)"
    FREE_TOPIC_LINK = "[ВІЛЬНА ТЕМА](https://t.me/c/1290587927/113831)"

    def main(self):
        """
        Запускає бота
        """

        self.app = ApplicationBuilder().token(self.bot_token).build()
        self.app.job_queue.run_once(self._initialize, when=0)
        self.app.add_handler(MessageHandler(None, self._message))
        self.app.job_queue.run_once(
            self._start_night_time, self._get_next_time(self.NIGHT_TIME_START_HOUR)
        )
        self.app.job_queue.run_once(
            self._end_night_time, self._get_next_time(self.NIGHT_TIME_END_HOUR)
        )
        self.app.run_polling()

    async def _initialize(self, _: ContextTypes.DEFAULT_TYPE) -> None:
        self.logger = logging.getLogger("my_logger")
        self.logger.setLevel(logging.DEBUG)
        handler = logging.FileHandler(filename="!log.txt", encoding="utf-8")

        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        sys.excepthook = self._handle_unhandled_exceptions

        load_dotenv()
        self.bot_token = self._get_env("BOT_TOKEN")
        self.bmp_chat_id = int(self._get_env("BMP_CHAT_ID"))
        self.developer_chat_id = int(self._get_env("DEVELOPER_CHAT_ID"))

        kyiv_timezone = gettz("Europe/Kiev")

        if os.path.exists("users.json"):
            with open(file="users.json", mode="r", encoding="utf8") as file:
                self.users = json.load(file)
        else:
            self.users = []

        self.user_ids = set(user["id"] for user in self.users)
        now_in_kyiv = datetime.now(kyiv_timezone)
        self.is_night_time = (
            now_in_kyiv.hour >= self.NIGHT_TIME_START_HOUR
            or now_in_kyiv.hour < self.NIGHT_TIME_END_HOUR
        )
        self.logger.debug("Init: is_night_time = %s", self.is_night_time)

    def _handle_unhandled_exceptions(self, exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        self.logger.error(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback)
        )

    def _get_env(self, key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise EnvironmentError(f"Environment variable {key} is not set")
        return value

    async def _message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message.chat_id == self.bmp_chat_id:
            self.logger.debug("message: is_night_time = %s", self.is_night_time)
            if self.is_night_time:
                if (
                    update.message.reply_to_message is None
                    or update.message.reply_to_message.forum_topic_created.name
                    not in self.allowed_topics
                ):
                    await context.bot.delete_message(
                        chat_id=self.bmp_chat_id, message_id=update.message.message_id
                    )
        else:
            chat = await context.bot.get_chat(self.bmp_chat_id)
            user_id = update.message.from_user.id
            user = await chat.get_member(user_id)

            if user.status == "left":
                await context.bot.send_message(
                    chat_id=update.message.chat_id,
                    text='Ви не є активістом ГО "Батько МАЄ ПРАВО"',
                    parse_mode="Markdown",
                )
                return

            if user_id not in self.user_ids:
                self.user_ids.add(user_id)
                self.users.append(
                    {
                        "id": user_id,
                        "username": update.message.from_user.username,
                        "first_name": update.message.from_user.first_name,
                        "last_name": update.message.from_user.last_name,
                    }
                )
                with open(file="users.json", mode="w", encoding="utf8") as file:
                    json.dump(self.users, file, ensure_ascii=False, indent=2)
                await context.bot.send_message(
                    chat_id=update.message.chat_id, text="Дякую за реєстрацію"
                )
            else:
                developer_link = f"[Михайлу](tg://user?id={self.developer_chat_id})"
                await context.bot.send_message(
                    chat_id=update.message.chat_id,
                    text=f"""Я поки не вмію виконувати команди.
Якщо у вас є пропозиції корисних команд, напишіть, будь ласка, моєму розробнику {developer_link}""",
                    parse_mode="Markdown",
                )

    async def _start_night_time(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.is_night_time = True
        self.logger.debug("startNightTime: is_night_time = True")
        await context.bot.send_message(
            chat_id=self.bmp_chat_id,
            text="""Батьки, оголошується режим тиші з 22:00 до 9:00.
Всі повідомлення у цей час будуть автоматично видалятися.
У топіках {self.SOS_LINK} і {self.FREE_TOPIC_LINK} можна писати без часових обмежень""",
            parse_mode="Markdown",
        )
        self.app.job_queue.run_once(
            self._start_night_time, self._get_next_time(self.NIGHT_TIME_START_HOUR)
        )

    def _get_next_time(self, hour: int) -> datetime:
        kyiv_timezone = gettz("Europe/Kiev")
        now_in_kyiv = datetime.now(kyiv_timezone)
        next_time = now_in_kyiv.replace(hour=hour, minute=0, second=0, microsecond=0)
        if next_time <= now_in_kyiv:
            next_time += relativedelta(days=1)
        return next_time

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
        self.app.job_queue.run_once(
            self._end_night_time, self._get_next_time(self.NIGHT_TIME_END_HOUR)
        )


if __name__ == "__main__":
    BmpBot().main()
