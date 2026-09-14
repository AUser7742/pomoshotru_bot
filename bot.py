import sys
import os
import time
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

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
import moderation

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
                            if now - last_edit_time > 1.2 and full_text.strip() and full_text != last_rendered_text:
                                display_chunk = full_text.strip()
                                if len(display_chunk) > 4000:
                                    display_chunk = display_chunk[-4000:]
                                display_text = display_chunk + " ▌"
                                try:
                                    bot.edit_message_text(display_text, chat_id=chat_id, message_id=msg_id, parse_mode="Markdown")
                                    last_rendered_text = full_text
                                    last_edit_time = now
                                except Exception:
                                    try:
                                        bot.edit_message_text(display_text, chat_id=chat_id, message_id=msg_id)
                                        last_rendered_text = full_text
                                        last_edit_time = now
                                    except Exception:
                                        pass
                break
            else:
                logger.warning(f"Model {model} returned {resp.status_code}, trying next...")
        except Exception as e:
            logger.warning(f"Streaming error on {model}: {e}")
            continue

    if not full_text.strip():
        full_text = "⚠️ Не удалось сгенерировать ответ. Попробуй переформулировать вопрос!"

    final_text = full_text.strip()
    try:
        bot.edit_message_text(final_text, chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=get_action_keyboard())
    except Exception:
        try:
            bot.edit_message_text(final_text, chat_id=chat_id, message_id=msg_id, reply_markup=get_action_keyboard())
        except Exception:
            pass

    return final_text

# ==========================================
# MODERATION & TARGET EXTRACTION HELPERS
# ==========================================

def extract_target_user(message, args):
    """
    Extracts (target_id, target_name, target_username, remaining_args).
    Works via message reply or @username/user_id argument.
    """
    chat_id = message.chat.id
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        uname = (u.first_name or "") + (" " + u.last_name if u.last_name else "")
        moderation.register_user_info(chat_id, u)
        return u.id, uname.strip() or f"id_{u.id}", u.username or "", args
    
    if args:
        first_arg = args[0]
        if first_arg.startswith("@") or first_arg.isdigit():
            uid, uinfo = moderation.find_user_by_mention(chat_id, first_arg)
            if uid:
                name = uinfo.get("name") if uinfo else f"id_{uid}"
                username = uinfo.get("username") if uinfo else first_arg.replace("@", "")
                return uid, name, username, args[1:]
    return None, None, None, args

# ==========================================
# COMMAND HANDLERS
# ==========================================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    moderation.register_user_info(message.chat.id, message.from_user)
    welcome_text = (
        "👋 *Привет! Я AI for copil (разработчик k3rnel).*\n\n"
        "✨ *Мои возможности:*\n"
        "💬 *Умный диалог:* отвечаю на любые вопросы, пишу скрипты (Lua, Python, JS, C++), помогаю с читами и играми.\n"
        "🎨 *Генерация артов:* напиши `нарисуй [описание]` или нажми кнопку.\n"
        "⚡️ *Живая печать:* вывожу мысли в реальном времени с анимацией `▌`.\n"
        "🛡 *Модерация бесед:* добавь меня в группу админом, и я буду следить за порядком!\n\n"
        "📌 *Команды для бесед:*\n"
        "• `/staff` — состав администрации группы\n"
        "• `/rules` — правила чата с интерактивными кнопками\n"
        "• `/ban`, `/mute`, `/kick`, `/warn` — команды модерации\n"
        "• `/modhelp` — полное руководство модератора"
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['modhelp'])
def send_modhelp(message):
    moderation.register_user_info(message.chat.id, message.from_user)
    help_text = (
        "🛡 *РУКОВОДСТВО ПО МОДЕРАЦИИ И РОЛЯМ*\n\n"
        "👑 *Иерархия ролей:*\n"
        "1. **Владелец (Owner)** — полный контроль, выдача/снятие Админов и Модеров.\n"
        "2. **Администратор (Admin)** — бан, мут, кик, варн, правила, выдача/снятие Модеров.\n"
        "3. **Модератор (Moder)** — мут, кик, варн нарушителей.\n\n"
        "👥 *Управление персоналом:*\n"
        "• `/staff` — посмотреть состав администрации\n"
        "• `/promote [moder/admin]` — повысить участника (ответом или по @нику)\n"
        "• `/demote` — снять роль с участника (ответом или по @нику)\n\n"
        "🔨 *Наказания (по ответу на сообщение или @нику):*\n"
        "• `/ban [время] [причина]` — заблокировать (напр. `/ban 1d Спам` или `/ban навсегда`)\n"
        "• `/unban [@ник/id]` — разбанить участника\n"
        "• `/mute [время] [причина]` — лишить права писать (напр. `/mute 15m Флуд`)\n"
        "• `/unmute` — снять мут\n"
        "• `/kick [причина]` — исключить из беседы\n"
        "• `/warn [причина]` — выдать предупреждение (3 варна = авто-мут на 24ч)\n"
        "• `/unwarn` — снять варн\n\n"
        "📜 *Правила чата:*\n"
        "• `/rules` — показать правила чата\n"
        "• `/setrules [текст]` — обновить правила чата"
    )
    bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['staff', 'admins', 'team'])
def cmd_staff(message):
    chat_id = message.chat.id
    if message.chat.type == "private":
        bot.send_message(chat_id, "ℹ️ Команда `/staff` работает в группах и беседах!", parse_mode="Markdown")
        return
    moderation.register_user_info(chat_id, message.from_user)
    staff_msg = moderation.generate_staff_message(bot, chat_id)
    bot.send_message(chat_id, staff_msg, parse_mode="Markdown")

@bot.message_handler(commands=['promote', 'setadmin', 'setmoder', 'moder', 'admin'])
def cmd_promote(message):
    chat_id = message.chat.id
    if message.chat.type == "private":
        bot.send_message(chat_id, "ℹ️ Эта команда работает в группах!", parse_mode="Markdown")
        return
        
    issuer_id = message.from_user.id
    moderation.register_user_info(chat_id, message.from_user)
    issuer_role, issuer_lvl = moderation.get_user_role(bot, chat_id, issuer_id)
    
    if issuer_lvl < 2:
        bot.reply_to(message, "⛔️ Только Администраторы и Владелец могут назначать персонал!")
        return
        
    tokens = message.text.split()
    cmd = tokens[0].lower().replace("@pomoshotru_bot", "")
    args = tokens[1:]
    
    target_id, target_name, target_user, remaining_args = extract_target_user(message, args)
    if not target_id:
        bot.reply_to(message, "⚠️ Укажите пользователя ответом на его сообщение или через `@username`!\nПример: `/promote @username moder`")
        return
        
    # Determine requested role
    role_to_assign = "moder"
    if "admin" in cmd:
        role_to_assign = "admin"
    elif "moder" in cmd:
        role_to_assign = "moder"
    elif remaining_args and remaining_args[0].lower() in ["admin", "админ", "администратор"]:
        role_to_assign = "admin"
    elif remaining_args and remaining_args[0].lower() in ["moder", "модер", "модератор"]:
        role_to_assign = "moder"
        
    if role_to_assign == "admin" and issuer_lvl < 3:
        bot.reply_to(message, "⛔️ Только Владелец группы может назначать Администраторов!")
        return
        
    chat_data = moderation.get_chat_data(chat_id)
    uid_str = str(target_id)
    user_info = {"id": target_id, "name": target_name, "username": target_user}
    
    if role_to_assign == "admin":
        if uid_str in chat_data.get("moders", {}):
            del chat_data["moders"][uid_str]
        if "admins" not in chat_data:
            chat_data["admins"] = {}
        chat_data["admins"][uid_str] = user_info
        moderation.update_chat_data(chat_id, chat_data)
        user_mention = moderation.format_user_mention(target_id, target_name, target_user)
        bot.send_message(chat_id, f"🛡 Участник {user_mention} успешно назначен на должность *Администратора*!", parse_mode="Markdown")
    else:
        if "moders" not in chat_data:
            chat_data["moders"] = {}
        chat_data["moders"][uid_str] = user_info
        moderation.update_chat_data(chat_id, chat_data)
        user_mention = moderation.format_user_mention(target_id, target_name, target_user)
        bot.send_message(chat_id, f"⚔️ Участник {user_mention} успешно назначен на должность *Модератора*!", parse_mode="Markdown")

@bot.message_handler(commands=['demote', 'unadmin', 'unmoder'])
def cmd_demote(message):
    chat_id = message.chat.id
    if message.chat.type == "private":
        bot.send_message(chat_id, "ℹ️ Эта команда работает в группах!", parse_mode="Markdown")
        return
        
    issuer_id = message.from_user.id
    moderation.register_user_info(chat_id, message.from_user)
    issuer_role, issuer_lvl = moderation.get_user_role(bot, chat_id, issuer_id)
    
    if issuer_lvl < 2:
        bot.reply_to(message, "⛔️ У вас нет прав снимать персонал!")
        return
        
    tokens = message.text.split()
    args = tokens[1:]
    target_id, target_name, target_user, _ = extract_target_user(message, args)
    
    if not target_id:
        bot.reply_to(message, "⚠️ Укажите пользователя ответом на его сообщение или через `@username`!")
        return
        
    target_role, target_lvl = moderation.get_user_role(bot, chat_id, target_id)
    if target_lvl >= issuer_lvl:
        bot.reply_to(message, "⛔️ Вы не можете снять пользователя с равным или более высоким рангом!")
        return
        
    chat_data = moderation.get_chat_data(chat_id)
    uid_str = str(target_id)
    removed = False
    
    if uid_str in chat_data.get("admins", {}):
        del chat_data["admins"][uid_str]
        removed = True
    if uid_str in chat_data.get("moders", {}):
        del chat_data["moders"][uid_str]
        removed = True
        
    if removed:
        moderation.update_chat_data(chat_id, chat_data)
        user_mention = moderation.format_user_mention(target_id, target_name, target_user)
        bot.send_message(chat_id, f"🔻 Участник {user_mention} был снят с должности персонала.", parse_mode="Markdown")
    else:
        bot.reply_to(message, "ℹ️ У данного пользователя не было назначенных должностей персонала.")

@bot.message_handler(commands=['ban'])
def cmd_ban(message):
    chat_id = message.chat.id
    if message.chat.type == "private":
        return
        
    issuer_id = message.from_user.id
    moderation.register_user_info(chat_id, message.from_user)
    issuer_role, issuer_lvl = moderation.get_user_role(bot, chat_id, issuer_id)
    
    if issuer_lvl < 2:
        bot.reply_to(message, "⛔️ Банить участников могут только Администраторы и Владелец!")
        return
        
    args = message.text.split()[1:]
    target_id, target_name, target_user, remaining_args = extract_target_user(message, args)
    
    if not target_id:
        bot.reply_to(message, "⚠️ Укажите кого забанить ответом на сообщение или по `@username`!\nПример: `/ban @username 1d Спам`")
        return
        
    target_role, target_lvl = moderation.get_user_role(bot, chat_id, target_id)
    if target_lvl >= issuer_lvl:
        bot.reply_to(message, "⛔️ Вы не можете забанить пользователя с равным или более высоким рангом!")
        return
        
    duration_sec = None
    duration_text = "Навсегда"
    reason = "Не указана"
    
    if remaining_args:
        sec, dur_txt = moderation.parse_time_duration(remaining_args[0])
        if dur_txt:
            duration_sec = sec
            duration_text = dur_txt
            reason = " ".join(remaining_args[1:]).strip() or "Не указана"
        else:
            reason = " ".join(remaining_args).strip() or "Не указана"
            
    until_ts = int(time.time() + duration_sec) if duration_sec else 0
    
    try:
        bot.ban_chat_member(chat_id, target_id, until_date=until_ts)
        user_mention = moderation.format_user_mention(target_id, target_name, target_user)
        issuer_mention = moderation.format_user_mention(issuer_id, message.from_user.first_name, message.from_user.username)
        
        ban_msg = (
            f"🚫 *ПОЛЬЗОВАТЕЛЬ ЗАБЛОКИРОВАН*\n\n"
            f"👤 *Нарушитель:* {user_mention}\n"
            f"👮‍♂️ *Модератор:* {issuer_mention}\n"
            f"⏳ *Срок:* `{duration_text}`\n"
            f"📝 *Причина:* _{reason}_"
        )
        bot.send_message(chat_id, ban_msg, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"⚠️ Не удалось забанить: убедитесь, что бот является администратором с правом блокировки!")

@bot.message_handler(commands=['unban'])
def cmd_unban(message):
    chat_id = message.chat.id
    if message.chat.type == "private":
        return
        
    issuer_id = message.from_user.id
    moderation.register_user_info(chat_id, message.from_user)
    issuer_role, issuer_lvl = moderation.get_user_role(bot, chat_id, issuer_id)
    
    if issuer_lvl < 2:
        bot.reply_to(message, "⛔️ Разбанивать могут только Администраторы и Владелец!")
        return
        
    args = message.text.split()[1:]
    target_id, target_name, target_user, _ = extract_target_user(message, args)
    
    if not target_id:
        bot.reply_to(message, "⚠️ Укажите кого разбанить по `@username` или ID!\nПример: `/unban @username`")
        return
        
    try:
        bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
        user_mention = moderation.format_user_mention(target_id, target_name, target_user)
        bot.send_message(chat_id, f"✅ Участник {user_mention} успешно разблокирован!", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"⚠️ Ошибка разбана: {e}")

@bot.message_handler(commands=['mute'])
def cmd_mute(message):
    chat_id = message.chat.id
    if message.chat.type == "private":
        return
        
    issuer_id = message.from_user.id
    moderation.register_user_info(chat_id, message.from_user)
    issuer_role, issuer_lvl = moderation.get_user_role(bot, chat_id, issuer_id)
    
    if issuer_lvl < 1:
        bot.reply_to(message, "⛔️ Мутить участников могут только Модераторы и Администраторы!")
        return
        
    args = message.text.split()[1:]
    target_id, target_name, target_user, remaining_args = extract_target_user(message, args)
    
    if not target_id:
        bot.reply_to(message, "⚠️ Укажите кого замутить ответом на сообщение или по `@username`!\nПример: `/mute 15m Флуд`")
        return
        
    target_role, target_lvl = moderation.get_user_role(bot, chat_id, target_id)
    if target_lvl >= issuer_lvl:
        bot.reply_to(message, "⛔️ Вы не можете выдать мут пользователю с равным или более высоким рангом!")
        return
        
    duration_sec = 600
    duration_text = "10 мин."
    reason = "Не указана"
    
    if remaining_args:
        sec, dur_txt = moderation.parse_time_duration(remaining_args[0])
        if dur_txt:
            duration_sec = sec or (86400 * 365)
            duration_text = dur_txt
            reason = " ".join(remaining_args[1:]).strip() or "Не указана"
        else:
            reason = " ".join(remaining_args).strip() or "Не указана"
            
    until_ts = int(time.time() + duration_sec)
    
    try:
        bot.restrict_chat_member(
            chat_id,
            target_id,
            until_date=until_ts,
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False
        )
        user_mention = moderation.format_user_mention(target_id, target_name, target_user)
        issuer_mention = moderation.format_user_mention(issuer_id, message.from_user.first_name, message.from_user.username)
        
        mute_msg = (
            f"🔇 *ПОЛЬЗОВАТЕЛЬ ЗАГЛУШЕН (МУТ)*\n\n"
            f"👤 *Нарушитель:* {user_mention}\n"
            f"👮‍♂️ *Модератор:* {issuer_mention}\n"
            f"⏳ *Срок:* `{duration_text}`\n"
            f"📝 *Причина:* _{reason}_"
        )
        bot.send_message(chat_id, mute_msg, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"⚠️ Не удалось замутить: убедитесь, что бот имеет права ограничения пользователей!")

@bot.message_handler(commands=['unmute'])
def cmd_unmute(message):
    chat_id = message.chat.id
    if message.chat.type == "private":
        return
        
    issuer_id = message.from_user.id
    moderation.register_user_info(chat_id, message.from_user)
    issuer_role, issuer_lvl = moderation.get_user_role(bot, chat_id, issuer_id)
    
    if issuer_lvl < 1:
        bot.reply_to(message, "⛔️ Снимать мут могут только Модераторы и Администраторы!")
        return
        
    args = message.text.split()[1:]
    target_id, target_name, target_user, _ = extract_target_user(message, args)
    
    if not target_id:
        bot.reply_to(message, "⚠️ Укажите кого размутить ответом или по нику!")
        return
        
    try:
        bot.restrict_chat_member(
            chat_id,
            target_id,
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
        user_mention = moderation.format_user_mention(target_id, target_name, target_user)
        bot.send_message(chat_id, f"🔊 Мут с пользователя {user_mention} успешно снят!", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"⚠️ Ошибка снятия мута: {e}")

@bot.message_handler(commands=['kick'])
def cmd_kick(message):
    chat_id = message.chat.id
    if message.chat.type == "private":
        return
        
    issuer_id = message.from_user.id
    moderation.register_user_info(chat_id, message.from_user)
    issuer_role, issuer_lvl = moderation.get_user_role(bot, chat_id, issuer_id)
    
    if issuer_lvl < 1:
        bot.reply_to(message, "⛔️ Кикать участников могут только Модераторы и Администраторы!")
        return
        
    args = message.text.split()[1:]
    target_id, target_name, target_user, remaining_args = extract_target_user(message, args)
    
    if not target_id:
        bot.reply_to(message, "⚠️ Укажите кого кикнуть ответом на сообщение или по `@username`!")
        return
        
    target_role, target_lvl = moderation.get_user_role(bot, chat_id, target_id)
    if target_lvl >= issuer_lvl:
        bot.reply_to(message, "⛔️ Вы не можете кикнуть пользователя с равным или более высоким рангом!")
        return
        
    reason = " ".join(remaining_args).strip() or "Не указана"
    
    try:
        bot.ban_chat_member(chat_id, target_id)
        bot.unban_chat_member(chat_id, target_id)
        user_mention = moderation.format_user_mention(target_id, target_name, target_user)
        bot.send_message(chat_id, f"👞 Участник {user_mention} был исключён из группы.\n📝 *Причина:* _{reason}_", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"⚠️ Не удалось кикнуть: {e}")

@bot.message_handler(commands=['warn'])
def cmd_warn(message):
    chat_id = message.chat.id
    if message.chat.type == "private":
        return
        
    issuer_id = message.from_user.id
    moderation.register_user_info(chat_id, message.from_user)
    issuer_role, issuer_lvl = moderation.get_user_role(bot, chat_id, issuer_id)
    
    if issuer_lvl < 1:
        bot.reply_to(message, "⛔️ Выдавать предупреждения могут только Модераторы и Администраторы!")
        return
        
    args = message.text.split()[1:]
    target_id, target_name, target_user, remaining_args = extract_target_user(message, args)
    
    if not target_id:
        bot.reply_to(message, "⚠️ Укажите кому выдать варн ответом на сообщение или по нику!")
        return
        
    target_role, target_lvl = moderation.get_user_role(bot, chat_id, target_id)
    if target_lvl >= issuer_lvl:
        bot.reply_to(message, "⛔️ Вы не можете выдать предупреждение пользователю с равным или более высоким рангом!")
        return
        
    reason = " ".join(remaining_args).strip() or "Не указана"
    chat_data = moderation.get_chat_data(chat_id)
    uid_str = str(target_id)
    
    if "warns" not in chat_data:
        chat_data["warns"] = {}
        
    curr_warns = chat_data["warns"].get(uid_str, 0) + 1
    chat_data["warns"][uid_str] = curr_warns
    moderation.update_chat_data(chat_id, chat_data)
    
    user_mention = moderation.format_user_mention(target_id, target_name, target_user)
    
    if curr_warns >= 3:
        chat_data["warns"][uid_str] = 0
        moderation.update_chat_data(chat_id, chat_data)
        until_ts = int(time.time() + 86400)
        try:
            bot.restrict_chat_member(chat_id, target_id, until_date=until_ts, can_send_messages=False)
            bot.send_message(chat_id, f"⚠️ {user_mention} набрал *3/3 предупреждений* и отправлен в мут на 24 часа!", parse_mode="Markdown")
        except Exception:
            bot.send_message(chat_id, f"⚠️ {user_mention} набрал *3/3 предупреждений*!", parse_mode="Markdown")
    else:
        bot.send_message(chat_id, f"⚠️ *ПРЕДУПРЕЖДЕНИЕ [{curr_warns}/3]*\n\n👤 *Нарушитель:* {user_mention}\n📝 *Причина:* _{reason}_", parse_mode="Markdown")

@bot.message_handler(commands=['unwarn'])
def cmd_unwarn(message):
    chat_id = message.chat.id
    if message.chat.type == "private":
        return
        
    issuer_id = message.from_user.id
    moderation.register_user_info(chat_id, message.from_user)
    issuer_role, issuer_lvl = moderation.get_user_role(bot, chat_id, issuer_id)
    
    if issuer_lvl < 1:
        bot.reply_to(message, "⛔️ Снимать предупреждения могут только Модераторы и Администраторы!")
        return
        
    args = message.text.split()[1:]
    target_id, target_name, target_user, _ = extract_target_user(message, args)
    
    if not target_id:
        bot.reply_to(message, "⚠️ Укажите кому снять варн ответом на сообщение!")
        return
        
    chat_data = moderation.get_chat_data(chat_id)
    uid_str = str(target_id)
    curr = chat_data.get("warns", {}).get(uid_str, 0)
    
    if curr > 0:
        chat_data["warns"][uid_str] = curr - 1
        moderation.update_chat_data(chat_id, chat_data)
        user_mention = moderation.format_user_mention(target_id, target_name, target_user)
        bot.send_message(chat_id, f"✅ С участника {user_mention} снят 1 варн (теперь: {curr - 1}/3)", parse_mode="Markdown")
    else:
        bot.reply_to(message, "ℹ️ У данного пользователя нет активных предупреждений.")

@bot.message_handler(commands=['rules'])
def cmd_rules(message):
    chat_id = message.chat.id
    moderation.register_user_info(chat_id, message.from_user)
    chat_data = moderation.get_chat_data(chat_id, getattr(message.chat, "title", "Беседа"))
    
    rules_text = chat_data.get("rules", "📌 *Правила чата пока не установлены.*")
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_agree = types.InlineKeyboardButton("✅ Ознакомлен", callback_data="rules_agree")
    btn_staff = types.InlineKeyboardButton("👑 Состав администрации", callback_data="view_staff")
    markup.add(btn_agree, btn_staff)
    
    bot.send_message(chat_id, f"📜 *ПРАВИЛА БЕСЕДЫ*\n\n{rules_text}", parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['setrules'])
def cmd_setrules(message):
    chat_id = message.chat.id
    if message.chat.type == "private":
        bot.send_message(chat_id, "ℹ️ Эта команда работает в группах!", parse_mode="Markdown")
        return
        
    issuer_id = message.from_user.id
    moderation.register_user_info(chat_id, message.from_user)
    issuer_role, issuer_lvl = moderation.get_user_role(bot, chat_id, issuer_id)
    
    if issuer_lvl < 2:
        bot.reply_to(message, "⛔️ Изменять правила могут только Администраторы и Владелец!")
        return
        
    new_rules = message.text.replace("/setrules", "", 1).strip()
    if not new_rules:
        bot.reply_to(message, "⚠️ Укажите текст правил после команды!\nПример: `/setrules 1. Без мата\n2. Без спама`", parse_mode="Markdown")
        return
        
    chat_data = moderation.get_chat_data(chat_id, getattr(message.chat, "title", "Беседа"))
    chat_data["rules"] = new_rules
    moderation.update_chat_data(chat_id, chat_data)
    
    bot.send_message(chat_id, "✅ *Правила чата успешно обновлены!*", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    moderation.register_user_info(chat_id, call.from_user)
    
    if call.data == "rules_agree":
        bot.answer_callback_query(call.id, f"Спасибо, {call.from_user.first_name}! Приятного общения в чате!", show_alert=True)
    elif call.data == "view_staff":
        staff_msg = moderation.generate_staff_message(bot, chat_id)
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, staff_msg, parse_mode="Markdown")
    elif call.data == "clear_context":
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
        last_prompt = last_user_prompts.get(chat_id, "futuristic neon art")
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
    moderation.register_user_info(chat_id, message.from_user)
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
    moderation.register_user_info(chat_id, message.from_user)

    is_group = message.chat.type in ["group", "supergroup"]

    # Image generation triggers
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
                status_msg = bot.send_message(chat_id, f"🎨 Рисую через Flux AI: *{prompt}*...", parse_mode="Markdown", reply_to_message_id=message.message_id)
                img_data, enhanced = generate_ai_image(prompt)
                if img_data:
                    try:
                        bot.delete_message(chat_id, status_msg.message_id)
                    except Exception:
                        pass
                    bot.send_photo(chat_id, img_data, caption=f"✨ *Готово:* {prompt}", parse_mode="Markdown", reply_to_message_id=message.message_id)
                    return
                else:
                    try:
                        bot.edit_message_text("⚠️ Ошибка при создании картинки. Попробуй другой запрос!", chat_id=chat_id, message_id=status_msg.message_id)
                    except Exception:
                        pass
                    return

    # In groups: respond with AI only when addressed directly or replied to
    bot_username = "pomoshotru_bot"
    is_addressed = False
    clean_ai_prompt = user_text

    if is_group:
        if f"@{bot_username}" in lower_text:
            is_addressed = True
            clean_ai_prompt = re.sub(rf"@{bot_username}", "", user_text, flags=re.IGNORECASE).strip()
        elif message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.is_bot and message.reply_to_message.from_user.username and message.reply_to_message.from_user.username.lower() == bot_username:
            is_addressed = True
        elif lower_text.startswith("/ai ") or lower_text.startswith("бот "):
            is_addressed = True
            clean_ai_prompt = re.sub(r"^(/ai|бот)\s*", "", user_text, flags=re.IGNORECASE).strip()
            
        if not is_addressed:
            return  # Do not spam group chat on regular conversations

    # Real-time Stream Typing Chat with Gemini
    history = get_user_history(chat_id)
    history.append({
        "role": "user",
        "parts": [{"text": clean_ai_prompt or user_text}]
    })

    if len(history) > config.MAX_HISTORY_LEN:
        history = history[-config.MAX_HISTORY_LEN:]
        user_histories[chat_id] = history

    response_text = stream_gemini_to_telegram(chat_id, history, reply_to_message_id=message.message_id)

    history.append({
        "role": "model",
        "parts": [{"text": response_text}]
    })
    user_histories[chat_id] = history

# ==========================================
# HEALTHCHECK HTTP SERVER (RENDER COMPATIBLE)
# ==========================================

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
    print("🚀 AI for copil (by k3rnel) успешно запущен!")
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
