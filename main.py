import asyncio
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler
import logging
from dotenv import load_dotenv
from datetime import datetime
import os
import json
import sys
from dateutil.relativedelta import relativedelta
from dateutil.tz import gettz

NIGHT_TIME_START_HOUR = 22
NIGHT_TIME_END_HOUR = 9
logger: logging.Logger

def handle_unhandled_exceptions(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

async def main():
    global logger
    logger = logging.getLogger('my_logger')
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(filename='!log.txt', encoding='utf-8')

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    sys.excepthook = handle_unhandled_exceptions

    load_dotenv()
    BOT_TOKEN = get_env('BOT_TOKEN')
    BMP_CHAT_ID = int(get_env('BMP_CHAT_ID'))
    DEVELOPER_CHAT_ID = int(get_env('DEVELOPER_CHAT_ID'))

    kyiv_timezone = gettz('Europe/Kiev')

    if os.path.exists('users.json'):
        with open(file='users.json', mode='r', encoding='utf8') as file:
          users = json.load(file)
    else:
        users = []

    bot = Bot(token=BOT_TOKEN)
    chat = await bot.get_chat(BMP_CHAT_ID)

    filtered_users = []

    for user in users:
        member = await chat.get_member(user['id'])
        if member.status != 'left':
            filtered_users.append(user)

    if (len(filtered_users) != len(users)):
        users = filtered_users
        save_users()

    user_ids = set(user['id'] for user in users)
    now_in_kyiv = datetime.now(kyiv_timezone)
    is_night_time = now_in_kyiv.hour >= NIGHT_TIME_START_HOUR or now_in_kyiv.hour < NIGHT_TIME_END_HOUR
    allowed_topics = set(['SOS', 'ВІЛЬНА ТЕМА'])

    async def message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message.chat_id == BMP_CHAT_ID:
            if is_night_time:
                if update.message.reply_to_message is None or update.message.reply_to_message.forum_topic_created.name not in allowed_topics:
                    await context.bot.delete_message(chat_id=BMP_CHAT_ID, message_id=update.message.message_id)
        else:
            chat = await context.bot.get_chat(BMP_CHAT_ID)
            user_id = update.message.from_user.id
            user = await chat.get_member(user_id)

            if user.status == 'left':
                await context.bot.send_message(chat_id=update.message.chat_id, text='Ви не є активістом ГО "Батько МАЄ ПРАВО"', parse_mode='Markdown')
                return

            if user_id not in user_ids:
                user_ids.add(user_id)
                users.append({
                    'id': user_id,
                    'username': update.message.from_user.username,
                    'first_name': update.message.from_user.first_name,
                    'last_name': update.message.from_user.last_name
                })
                save_users()
                await context.bot.send_message(chat_id=update.message.chat_id, text='Дякую за реєстрацію')
            else:
                await context.bot.send_message(chat_id=update.message.chat_id, text=f'Я поки не вмію виконувати команди. Якщо у вас є пропозиції корисних команд, напишіть, будь ласка, моєму розробнику [Михайлу](tg://user?id={DEVELOPER_CHAT_ID})', parse_mode='Markdown')

    def save_users() -> None:
        with open(file='users.json', mode='w', encoding='utf8') as file:
            json.dump(users, file, ensure_ascii=False, indent=2)

    async def startNightTime(context: ContextTypes.DEFAULT_TYPE) -> None:
        global is_night_time
        is_night_time = True
        await context.bot.send_message(chat_id=BMP_CHAT_ID, text='Батьки, оголошується режим тиші з 22:00 до 9:00. Всі повідомлення у цей час будуть автоматично видалятися.\nУ топіках [SOS](https://t.me/c/1290587927/113812) і [ВІЛЬНА ТЕМА](https://t.me/c/1290587927/113831) можна писати без часових обмежень', parse_mode='Markdown')
        app.job_queue.run_once(startNightTime, get_next_time(NIGHT_TIME_START_HOUR))
    
    async def endNightTime(context: ContextTypes.DEFAULT_TYPE) -> None:
        global is_night_time
        is_night_time = False
        BOT_HIMSELF = 1
        registered_users_count = len(users) + BOT_HIMSELF
        chat = await context.bot.get_chat(BMP_CHAT_ID)
        users_count = await chat.get_member_count()
        await context.bot.send_message(chat_id=BMP_CHAT_ID, text=f'Батьки, режим тиші закінчився\nДля того покращити роботу бота, необхідно, щоб кожен активіст написав йому хоча б раз особисте повідомлення. Будь ласка зробіть це. На разі це зробило лише {registered_users_count} активістів із {users_count}.\nДякую за розуміння', parse_mode='Markdown')
        app.job_queue.run_once(endNightTime, get_next_time(NIGHT_TIME_END_HOUR))

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(None, message))

    app.job_queue.run_once(startNightTime, get_next_time(NIGHT_TIME_START_HOUR))
    app.job_queue.run_once(endNightTime, get_next_time(NIGHT_TIME_END_HOUR))

    def run_polling_with_new_event_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app.run_polling()

    await asyncio.to_thread(run_polling_with_new_event_loop)

def get_env(key: str) -> str:
    value = os.getenv(key)
    if (not value):
        raise Exception(f'Environment variable {key} is not set')
    return value

def get_next_time(hour: int) -> datetime:
    kyiv_timezone = gettz('Europe/Kiev')
    now_in_kyiv = datetime.now(kyiv_timezone)
    next_time = now_in_kyiv.replace(hour=hour, minute=0, second=0, microsecond=0)
    if next_time <= now_in_kyiv:
        next_time += relativedelta(days=1)
    return next_time

if __name__ == '__main__':
    asyncio.run(main())
