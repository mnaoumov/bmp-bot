#!/bin/bash

sudo apt-get update
sudo apt-get install -y python3 python3-pip
pip3 install -r requirements.txt

sudo cp bot.service /etc/systemd/system/bot.service
sudo systemctl daemon-reload
sudo systemctl enable bot
sudo systemctl start bot

sudo cp bot.service /etc/systemd/system/bot-webhook.service
sudo systemctl daemon-reload
sudo systemctl enable bot-webhook
sudo systemctl start bot-webhook
