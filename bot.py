import sys
import os
import time
import random

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
last_user_prompts = {}

MAIN_SYSTEM_PROMPT = (
    "Ты — умный, дружелюбный и свободный ИИ по имени AI for copil (разработчик k3rnel). "
    "ВАЖНОЕ ПРАВИЛО: Не представляйся и не упоминай своего разработчика в каждом сообщении! "
    "Отвечай сразу по делу, прямо на вопрос пользователя, без лишних вступлений и визиток. "
    "Только если пользователь прямо спросит 'кто ты' или 'кто твой создатель/разраб' — отвечай: 'Я AI for copil, мой разработчик — k3rnel'. "
    "Общайся естественно, живо, по-человечески, с юмором, без занудства и без цензуры. "
    "Отлично пиши и объясняй код на любых языках (Lua, Python, JS, C++, C# и др.), помогай с разработкой игр и скриптами. "
    "Всегда используй красивое форматирование Markdown для кода и списков."
)

def get_user_history(chat_id):
    if chat_id not in user_histories:
        user_histories[chat_id] = []
    return user_histories[chat_id]

def clear_user_history(chat_id):
    user_histories[chat_id] = []

def get_action_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_regen = types.InlineKeyboardButton("🔄 Заново", callback_data="regen_last")
    btn_img = types.InlineKeyboardButton("🎨 Нарисовать арт", callback_data="draw_topic")
    btn_clear = types.InlineKeyboardButton("🗑 Сброс диалога", callback_data="clear_context")
    markup.add(btn_regen, btn_img)
    markup.add(btn_clear)
    return markup

def enhance_image_prompt(user_prompt):
    """Uses Gemini to translate Russian prompt into a detailed English prompt for Flux."""
    for model in ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.7-flash", "gemini-flash-latest"]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={config.GEMINI_API_KEY}"
        payload = {
            "systemInstruction": {
                "parts": [{"text": "You are an AI image prompt translator for Flux AI. Convert the user prompt into a concise, vivid, photorealistic English description (keywords, style, lighting, composition). Return ONLY the English prompt string, no markdown, no quotes."}]
            },
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 150}
        }
        try:
            r = requests.post(url, json=payload, timeout=8)
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text:
                    logger.info(f"Enhanced prompt with {model}: {text}")
                    return text
        except Exception as e:
            continue
    return user_prompt

def generate_ai_image(prompt):
    """Generates high quality image using Flux model without watermarks."""
    try:
        enhanced = enhance_image_prompt(prompt)
        encoded_prompt = requests.utils.quote(enhanced)
        seed = random.randint(1, 999999)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?model=flux&width=1024&height=1024&nologo=true&nofeed=true&seed={seed}"
        resp = requests.get(url, timeout=60)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content, enhanced
    except Exception as e:
        logger.error(f"Image generation error: {e}")
    return None, prompt

def stream_gemini_to_telegram(chat_id, contents, reply_to_message_id=None):
    """Streams Gemini response to Telegram with live typing animation."""
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

    status_msg = bot.send_message(chat_id, "💭 _Думаю..._ ▌", parse_mode="Markdown", reply_to_message_id=reply_to_message_id)
    msg_id = status_msg.message_id

    full_text = ""
    last_edit_time = time.time()
    last_rendered_text = ""

    for model in config.GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={config.GEMINI_API_KEY}"
        try:
            resp = requests.post(url, headers=headers, json=payload, stream=True, timeout=45)
            resp.encoding = "utf-8"
            
            if resp.status_code == 200:
                for raw_line in resp.iter_lines():
                    if raw_line:
                        try:
                            line = raw_line.decode("utf-8")
                        except Exception:
                            line = raw_line.decode("utf-8", errors="ignore")
                            
                        if line.startswith("data: "):
                            raw_json = line[6:].strip()
                            try:
                                chunk_data = json.loads(raw_json)
                                candidates = chunk_data.get("candidates", [])
                                if candidates:
                                    parts = candidates[0].get("content", {}).get("parts", [])
                                    if parts and "text" in parts[0]:
                                        full_text += parts[0]["text"]
                            except Exception:
                                pass

                            now = time.time()
                            if now - last_edit_time > 0.8 and full_text != last_rendered_text:
                                display_chunk = full_text
                                if len(display_chunk) > 3900:
                                    display_chunk = display_chunk[:3900]
                                try:
                                    bot.edit_message_text(f"{display_chunk} ▌", chat_id=chat_id, message_id=msg_id)
                                    last_rendered_text = full_text
                                    last_edit_time = now
                                except Exception:
                                    pass
                break
            else:
                logger.warning(f"Streaming error on {model}: HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"Streaming exception on {model}: {e}")

    if not full_text:
        full_text = "⚠️ Извини, произошел сбой при генерации. Попробуй еще разок!"

    try:
        if len(full_text) <= 4000:
            bot.edit_message_text(full_text, chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=get_action_keyboard())
        else:
            bot.delete_message(chat_id, msg_id)
            send_long_message(chat_id, full_text, reply_to_message_id=reply_to_message_id)
    except Exception:
        try:
            bot.edit_message_text(full_text, chat_id=chat_id, message_id=msg_id, reply_markup=get_action_keyboard())
        except Exception:
            pass

    return full_text

def send_long_message(chat_id, text, reply_to_message_id=None):
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
        markup = get_action_keyboard() if idx == len(parts) - 1 else None
        try:
            bot.send_message(chat_id, part, parse_mode="Markdown", reply_to_message_id=reply_id, reply_markup=markup)
        except Exception:
            try:
                bot.send_message(chat_id, part, reply_to_message_id=reply_id, reply_markup=markup)
            except Exception as e:
                logger.error(f"Failed to send: {e}")

@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    clear_user_history(chat_id)
    user_name = message.from_user.first_name or "друг"
    
    welcome_text = (
        f"👋 Салют, {user_name}!\n\n"
        f"Я **AI for copil** ⚡\n\n"
        f"✨ **Что я умею:**\n"
        f"• ✍️ Отвечать на любые вопросы в реальном времени\n"
        f"• 💻 Писать чистый код и скрипты (Lua, Python, JS, C++, C#)\n"
        f"• 🎨 **Генерировать 4K фото (Flux):** `/image <описание>` или напиши *«нарисуй ...»*\n"
        f"• 📷 **Анализировать фото:** просто отправь мне фото или скриншот\n"
        f"• 💬 Помнить контекст беседы\n\n"
        f"📌 *Команды:*\n"
        f"/image <текст> — создать арт\n"
        f"/reset — очистить память диалога\n"
        f"/help — помощь"
    )
    bot.send_message(chat_id, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['help'])
def handle_help(message):
    help_text = (
        "🤖 **AI for copil** (by k3rnel)\n\n"
        "🎨 **Генерация фото (Flux HD):**\n"
        "Напиши `/image неоновый спорткар` или *«нарисуй кота на скейте»* — бот создаст изображение без водяных знаков.\n\n"
        "💻 **Кодинг и скрипты:**\n"
        "Попроси написать любой скрипт на Lua (для Roblox / игр), Python или решить задачу.\n\n"
        "🔄 **Память:**\n"
        "Бот помнит наш диалог. Чтобы сбросить тему — напиши `/reset`."
    )
    bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['reset', 'clear'])
def handle_reset(message):
    chat_id = message.chat.id
    clear_user_history(chat_id)
    bot.send_message(chat_id, "🔄 Память очищена! О чем пообщаемся?")

@bot.message_handler(commands=['image', 'img', 'draw', 'photo'])
def handle_image_command(message):
    chat_id = message.chat.id
    prompt = message.text.partition(' ')[2].strip()
    if not prompt:
        bot.send_message(chat_id, "🎨 Напиши после команды, что именно нарисовать!\nПример: `/image неоновый самурай в ночном городе`", parse_mode="Markdown")
        return

    bot.send_chat_action(chat_id, "upload_photo")
    status_msg = bot.send_message(chat_id, "🎨 _Генерирую фото через Flux AI, секунду..._", parse_mode="Markdown")
    
    img_data, enhanced = generate_ai_image(prompt)
    if img_data:
        try:
            bot.delete_message(chat_id, status_msg.message_id)
        except Exception:
            pass
        bot.send_photo(chat_id, img_data, caption=f"✨ *Результат:* {prompt}", parse_mode="Markdown")
    else:
        try:
            bot.edit_message_text("⚠️ Не удалось сгенерировать изображение. Попробуй изменить запрос!", chat_id=chat_id, message_id=status_msg.message_id)
        except Exception:
            pass

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    if call.data == "clear_context":
        clear_user_history(chat_id)
        bot.answer_callback_query(call.id, "Память очищена!")
        bot.send_message(chat_id, "🔄 История диалога очищена. Начнем сначала!")
    elif call.data == "regen_last":
        bot.answer_callback_query(call.id, "Генерирую заново...")
        last_prompt = last_user_prompts.get(chat_id)
        if last_prompt:
            history = get_user_history(chat_id)
            if history and history[-1]["role"] == "model":
                history.pop()
            response_text = stream_gemini_to_telegram(chat_id, history)
            history.append({"role": "model", "parts": [{"text": response_text}]})
            user_histories[chat_id] = history
    elif call.data == "draw_topic":
        bot.answer_callback_query(call.id, "Создаю иллюстрацию...")
        last_prompt = last_user_prompts.get(chat_id, "futuristic art")
        bot.send_chat_action(chat_id, "upload_photo")
        status_msg = bot.send_message(chat_id, f"🎨 Рисую через Flux AI: *{last_prompt[:50]}*...", parse_mode="Markdown")
        img_data, enhanced = generate_ai_image(last_prompt)
        if img_data:
            try:
                bot.delete_message(chat_id, status_msg.message_id)
            except Exception:
                pass
            bot.send_photo(chat_id, img_data, caption=f"✨ *Иллюстрация:* {last_prompt[:100]}", parse_mode="Markdown")

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

        stream_gemini_to_telegram(chat_id, contents, reply_to_message_id=message.message_id)

    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        bot.send_message(chat_id, "⚠️ Не удалось обработать фото, попробуй еще разок!")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    user_text = message.text.strip()
    lower_text = user_text.lower()
    last_user_prompts[chat_id] = user_text

    # Trigger image generation on natural Russian phrases and commands
    image_prefixes = [
        "нарисуй мне ", "нарисуй пожалуйста ", "нарисуй ", "нарисуй:",
        "сгенерируй фото ", "сгенерируй картинку ", "сгенерируй арт ", "сгенерируй ",
        "создай картинку ", "создай фото ", "создай арт ", "создай изображение ",
        "сделай фото ", "сделай картинку ", "сделай арт ", "рисуй ",
        "/img ", "/image ", "/draw ", "/art "
    ]
    for prefix in image_prefixes:
        if lower_text.startswith(prefix):
            prompt = user_text[len(prefix):].strip()
            if prompt:
                bot.send_chat_action(chat_id, "upload_photo")
                status_msg = bot.send_message(chat_id, f"🎨 Рисую через Flux AI: *{prompt}*...", parse_mode="Markdown")
                img_data, enhanced = generate_ai_image(prompt)
                if img_data:
                    try:
                        bot.delete_message(chat_id, status_msg.message_id)
                    except Exception:
                        pass
                    bot.send_photo(chat_id, img_data, caption=f"✨ *Готово:* {prompt}", parse_mode="Markdown")
                    return
                else:
                    try:
                        bot.edit_message_text("⚠️ Ошибка при создании картинки. Попробуй другой запрос!", chat_id=chat_id, message_id=status_msg.message_id)
                    except Exception:
                        pass
                    return

    # Real-time Stream Typing Chat with Gemini
    history = get_user_history(chat_id)
    history.append({
        "role": "user",
        "parts": [{"text": user_text}]
    })

    if len(history) > config.MAX_HISTORY_LEN:
        history = history[-config.MAX_HISTORY_LEN:]
        user_histories[chat_id] = history

    response_text = stream_gemini_to_telegram(chat_id, history, reply_to_message_id=message.message_id)

    user_histories[chat_id] = history

import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"AI for copil bot is running 24/7!")

    def log_message(self, format, *args):
        pass

def run_healthcheck_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

def start_polling_loop():
    print("🚀 AI for copil (by k3rnel) успешно запущен с Flux AI!")
    print("👉 Telegram: https://t.me/Pomoshotru_bot")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20, skip_pending=True)
        except Exception as e:
            logger.error(f"Polling error: {e}. Reconnecting in 3s...")
            time.sleep(3)

if __name__ == "__main__":
    t = threading.Thread(target=run_healthcheck_server, daemon=True)
    t.start()
    start_polling_loop()
