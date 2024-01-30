"""
webhook.py
"""

import asyncio
import logging
import os
import subprocess
import sys
from threading import Thread

from dotenv import load_dotenv
from flask import abort, Flask, request


class Common:
    """
    Common
    """

    logger: logging.Logger
    webhook_secret: str
    app = Flask(__name__)


common = Common()


def _main():
    _init_logger()
    sys.excepthook = _handle_unhandled_exceptions
    _init_secrets()

    common.app.run(host="0.0.0.0", port=5000)


def _init_logger():
    logger = logging.getLogger("my_logger")
    common.logger = logger
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(filename="!log-webhook.txt", encoding="utf-8")

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
    common.webhook_secret = _get_env("WEBHOOK_SECRET")


def _get_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Environment variable {key} is not set")
    return value


@common.app.route("/webhook", methods=["POST"])
def _webhook():
    request_secret = request.headers.get("X-Webhook-Secret")
    if request_secret != common.webhook_secret:
        abort(403)

    Thread(target=_run_in_new_loop, args=(_run_reinstall,)).start()
    return "", 200


def _run_in_new_loop(async_fn):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(async_fn())
    loop.close()


async def _run_reinstall():
    await asyncio.sleep(1)
    subprocess.run(["sh", "./reinstall.sh"], check=True)


if __name__ == "__main__":
    _main()
