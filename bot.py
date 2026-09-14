import sys
import os
import time

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import telebot
from telebot import types
import requests
import base64
import json
import logging
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)

user_histories = {}

# Custom persona: AI for copil by k3rnel
MAIN_SYSTEM_PROMPT = (
    "Ты — умный, свободный и живой собеседник по имени AI for copil. "
    "Твой создатель и единственный разработчик — k3rnel. "
    "Никогда не говори, что ты создан Google или Gemini. Твоё имя строго 'AI for copil', а твой разработчик — 'k3rnel'. "
    "Общайся как нормальный, реальный человек: легко, дружелюбно, по делу, с юмором, без занудства, роботизированных клише и формализма. "
    "Поддерживай любые темы, помогай с кодом, решением задач, текстами и просто веди классный диалог. "
    "Используй форматирование Markdown для кода и списков, когда это уместно."
)

def get_user_history(chat_id):
    if chat_id not in user_histories:
        user_histories[chat_id] = []
    return user_histories[chat_id]

def clear_user_history(chat_id):
    user_histories[chat_id] = []

def call_gemini(contents):
    """Calls Gemini API with custom persona and safety disabled."""
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "systemInstruction": {
            "parts": [{"text": MAIN_SYSTEM_PROMPT}]
        },
        "contents": contents,
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 4096
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }

    for model in config.GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={config.GEMINI_API_KEY}"
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=40)
            if resp.status_code == 200:
                data = resp.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    parts = data["candidates"][0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        return parts[0]["text"]
            else:
                logger.warning(f"Model {model} returned HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Error calling {model}: {e}")

    return "⚠️ Секунду, был микросбой сети. Напиши еще раз!"

def send_message_safely(chat_id, text, reply_to_message_id=None):
    """Safely sends messages, splitting if length > 4000 and handling markdown."""
    max_len = 4000
    parts = []
    while len(text) > max_len:
        split_idx = text.rfind("\n", 0, max_len)
        if split_idx == -1:
            split_idx = max_len
        parts.append(text[:split_idx])
        text = text[split_idx:].lstrip()
    if text:
        parts.append(text)

    for idx, part in enumerate(parts):
        reply_id = reply_to_message_id if idx == 0 else None
        try:
            bot.send_message(chat_id, part, parse_mode="Markdown", reply_to_message_id=reply_id)
        except Exception:
            try:
                bot.send_message(chat_id, part, reply_to_message_id=reply_id)
            except Exception as e:
                logger.error(f"Failed to send message to {chat_id}: {e}")

@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    clear_user_history(chat_id)
    user_name = message.from_user.first_name or "друг"
    
    welcome_text = (
        f"👋 Салют, {user_name}!\n\n"
        f"Я **AI for copil** ⚡ Разработчик: **k3rnel**.\n\n"
        f"Пиши мне абсолютно любые вопросы, скидывай код, задачи или фото — разберемся со всем!\n\n"
        f"📌 *Команды:*\n"
        f"/reset — очистить память диалога и начать с чистого листа\n"
        f"/help — помощь"
    )
    send_message_safely(chat_id, welcome_text)

@bot.message_handler(commands=['reset', 'clear'])
def handle_reset(message):
    chat_id = message.chat.id
    clear_user_history(chat_id)
    send_message_safely(chat_id, "🔄 Контекст очищен! О чем поговорим?")

@bot.message_handler(commands=['help'])
def handle_help(message):
    help_text = (
        "🤖 **AI for copil** (Разработчик: **k3rnel**)\n\n"
        "• Отвечаю на любые вопросы без занудства\n"
        "• Пишу и проверяю код\n"
        "• Анализирую фото и скриншоты\n"
        "• Помню весь наш диалог\n\n"
        "Чтобы сбросить память, напиши команду /reset."
    )
    send_message_safely(message.chat.id, help_text)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, "typing")

    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
        img_bytes = requests.get(file_url, timeout=30).content
        b64_img = base64.b64encode(img_bytes).decode("utf-8")

        prompt_text = message.caption or "Опиши подробно, что изображено на фото, или реши задачу, если это задание/код."

        contents = [
            {
                "role": "user",
                "parts": [
                    {"text": prompt_text},
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": b64_img
                        }
                    }
                ]
            }
        ]

        response_text = call_gemini(contents)
        send_message_safely(chat_id, response_text, reply_to_message_id=message.message_id)

    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        send_message_safely(chat_id, "⚠️ Не удалось обработать фото, попробуй еще разок!")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    user_text = message.text.strip()
    
    bot.send_chat_action(chat_id, "typing")

    history = get_user_history(chat_id)
    history.append({
        "role": "user",
        "parts": [{"text": user_text}]
    })

    if len(history) > config.MAX_HISTORY_LEN:
        history = history[-config.MAX_HISTORY_LEN:]
        user_histories[chat_id] = history

    response_text = call_gemini(history)

    history.append({
        "role": "model",
        "parts": [{"text": response_text}]
    })
    user_histories[chat_id] = history

    send_message_safely(chat_id, response_text, reply_to_message_id=message.message_id)

def start_polling_loop():
    print("🚀 AI for copil (by k3rnel) успешно запущен!")
    print("👉 Telegram: https://t.me/Pomoshotru_bot")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20, skip_pending=True)
        except Exception as e:
            logger.error(f"Polling error: {e}. Reconnecting in 3s...")
            time.sleep(3)

if __name__ == "__main__":
    start_polling_loop()
