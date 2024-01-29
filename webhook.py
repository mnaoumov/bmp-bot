from flask import Flask, request, abort
import subprocess
import hmac
import hashlib
import logging
import os
import sys
from dotenv import load_dotenv

def get_env(key: str) -> str:
    value = os.getenv(key)
    if (not value):
        raise Exception(f'Environment variable {key} is not set')
    return value

def handle_unhandled_exceptions(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))


def main():
    global logger
    logger = logging.getLogger('my_logger')
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(filename='!log-webhook.txt', encoding='utf-8')

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    sys.excepthook = handle_unhandled_exceptions

    app = Flask(__name__)
    load_dotenv()
    WEBHOOK_SECRET = get_env('WEBHOOK_SECRET')

    @app.route('/webhook', methods=['POST'])
    def webhook():
        if request.method == 'POST':
            request_secret = request.headers.get('X-Webhook-Secret')
            if request_secret != WEBHOOK_SECRET:
                abort(403)

            subprocess.run(['sh', './reinstall.sh'])
            return '', 200
        else:
            return '', 400

    app.run(host='0.0.0.0', port=5000)

if __name__ == '__main__':
    main()