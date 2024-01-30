import asyncio
from flask import Flask, request, abort
import subprocess
import logging
import os
import sys
from dotenv import load_dotenv
from threading import Thread

WEBHOOK_SECRET: str
app = Flask(__name__)

def main():
    init_logger()
    sys.excepthook = handle_unhandled_exceptions
    init_secrets()

    app.run(host="0.0.0.0", port=5000)


def init_logger():
    global logger
    logger = logging.getLogger("my_logger")
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(filename="!log-webhook.txt", encoding="utf-8")

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def handle_unhandled_exceptions(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))


def init_secrets():
    load_dotenv()
    global WEBHOOK_SECRET
    WEBHOOK_SECRET = get_env("WEBHOOK_SECRET")


def get_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise Exception(f"Environment variable {key} is not set")
    return value


@app.route("/webhook", methods=["POST"])
def webhook():
    request_secret = request.headers.get("X-Webhook-Secret")
    if request_secret != WEBHOOK_SECRET:
        abort(403)

    Thread(target=run_in_new_loop, args=(runReinstall,)).start()
    return "", 200

def run_in_new_loop(async_fn):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(async_fn())
    loop.close()


async def runReinstall():
    await asyncio.sleep(1)
    subprocess.run(["sh", "./reinstall.sh"])

if __name__ == "__main__":
    main()
