# lifts/telegram_bot.py

import requests
import os

# Loaded from environment (see .env / host config). Never hard-code the token.
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def send_telegram_message(message):
    """
    Sends a message to the predefined Telegram group using the bot.
    """
    # The URL for the Telegram Bot API's sendMessage method
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    # The payload to send
    payload = {
        'chat_id': CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown' # Allows for simple formatting like bold, italics
    }

    # Don't send if the token/ID is not set
    if not BOT_TOKEN or not CHAT_ID:
        print("!!! TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured. Message not sent.")
        return False

    try:
        # Make the request to the Telegram API
        response = requests.post(api_url, json=payload)
        
        # Check if the request was successful
        if response.status_code == 200:
            print("Telegram message sent successfully.")
            return True
        else:
            print(f"Failed to send Telegram message. Status: {response.status_code}, Response: {response.text}")
            return False
    except Exception as e:
        print(f"An error occurred while sending Telegram message: {e}")
        return False
