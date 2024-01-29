from flask import Flask, request, abort
import subprocess
import hmac
import hashlib
import os
from dotenv import load_dotenv

def get_env(key: str) -> str:
    value = os.getenv(key)
    if (not value):
        raise Exception(f'Environment variable {key} is not set')
    return value

def main():
    app = Flask(__name__)
    load_dotenv()
    WEBHOOK_SECRET = get_env('WEBHOOK_SECRET')
    app.run(host='0.0.0.0', port=5000)

    @app.route('/webhook', methods=['POST'])
    def webhook():
        if request.method == 'POST':
            # Verify if the request is from GitHub
            signature = request.headers.get('X-Hub-Signature')
            sha, signature = signature.split('=')
            mac = hmac.new(bytes(WEBHOOK_SECRET, 'utf-8'), msg=request.data, digestmod=hashlib.sha1)
            if not hmac.compare_digest(str(mac.hexdigest()), str(signature)):
                abort(403)  # Forbidden

            subprocess.run(['sh', './reinstall.sh'])
            return '', 200
        else:
            return '', 400

if __name__ == '__main__':
    main()