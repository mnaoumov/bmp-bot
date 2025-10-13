#!/bin/bash

sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt

sudo cp bot.service /etc/systemd/system/bot.service
sudo systemctl daemon-reload
sudo systemctl enable bot
sudo systemctl restart bot

sudo cp bot-webhook.service /etc/systemd/system/bot-webhook.service
sudo systemctl daemon-reload
sudo systemctl enable bot-webhook
sudo systemctl restart bot-webhook
