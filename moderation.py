import os
import json
import time
import re
import logging
from telebot import types

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "moderation_data.json")

def load_db():
    if not os.path.exists(DB_PATH):
        return {"chats": {}}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading {DB_PATH}: {e}")
        return {"chats": {}}

def save_db(data):
    try:
        with open(DB_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving {DB_PATH}: {e}")

def get_chat_data(chat_id, chat_title=""):
    db = load_db()
    cid = str(chat_id)
    if cid not in db["chats"]:
        db["chats"][cid] = {
            "title": chat_title,
            "owner_id": None,
            "owner_name": "",
            "owner_username": "",
            "admins": {},
            "moders": {},
            "warns": {},
            "rules": "📌 *Правила чата пока не установлены.*\nИспользуйте команду `/setrules [текст]` для их создания.",
            "rules_buttons": []
        }
        save_db(db)
    return db["chats"][cid]

def update_chat_data(chat_id, chat_data):
    db = load_db()
    db["chats"][str(chat_id)] = chat_data
    save_db(db)

def register_user_info(chat_id, user):
    """Caches user basic info in chat database for mention resolution."""
    if not user or user.is_bot:
        return
    db = load_db()
    cid = str(chat_id)
    if cid not in db["chats"]:
        get_chat_data(chat_id)
        db = load_db()
    
    if "users" not in db["chats"][cid]:
        db["chats"][cid]["users"] = {}
    
    name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    db["chats"][cid]["users"][str(user.id)] = {
        "id": user.id,
        "name": name.strip() or f"id_{user.id}",
        "username": user.username or ""
    }
    save_db(db)

def find_user_by_mention(chat_id, mention_text):
    """Finds user_id and info from @username or user_id in database cache."""
    clean = mention_text.replace("@", "").strip()
    db = load_db()
    cid = str(chat_id)
    users = db.get("chats", {}).get(cid, {}).get("users", {})
    
    # Check numeric ID
    if clean.isdigit():
        uid = int(clean)
        if str(uid) in users:
            return uid, users[str(uid)]
        return uid, {"id": uid, "name": f"id_{uid}", "username": ""}
    
    # Check username
    for uid_str, u in users.items():
        if u.get("username", "").lower() == clean.lower():
            return int(uid_str), u
            
    return None, None

def parse_time_duration(time_str):
    """
    Parses time strings like '10m', '2h', '1d', '7d', '1w', '15м', '2ч', '1д', 'навсегда'.
    Returns (seconds, human_readable_ru).
    """
    if not time_str or time_str.lower() in ["навсегда", "forever", "0", "вечно", "perm", "permanent"]:
        return None, "Навсегда"
    
    pattern = r"^(\d+)([smhdwсмчднSMHDWСМЧДН]?)$"
    match = re.match(pattern, time_str.strip().lower())
    if not match:
        return None, None
    
    val = int(match.group(1))
    unit = match.group(2)
    
    if unit in ["s", "с", ""]:
        sec = val
        txt = f"{val} сек."
    elif unit in ["m", "м"]:
        sec = val * 60
        txt = f"{val} мин."
    elif unit in ["h", "ч"]:
        sec = val * 3600
        txt = f"{val} ч."
    elif unit in ["d", "д"]:
        sec = val * 86400
        txt = f"{val} дн."
    elif unit in ["w", "н"]:
        sec = val * 86400 * 7
        txt = f"{val} нед."
    else:
        return None, None
        
    return sec, txt

def get_user_role(bot, chat_id, user_id):
    """
    Returns role name ('owner', 'admin', 'moder', 'member') and role level:
    owner: 3, admin: 2, moder: 1, member: 0
    """
    chat_data = get_chat_data(chat_id)
    uid_str = str(user_id)
    
    # 1. Check local DB explicit owner
    if chat_data.get("owner_id") == user_id:
        return "owner", 3
        
    # 2. Check Telegram chat status
    try:
        member = bot.get_chat_member(chat_id, user_id)
        if member.status == "creator":
            if chat_data.get("owner_id") != user_id:
                name = (member.user.first_name or "") + (" " + member.user.last_name if member.user.last_name else "")
                chat_data["owner_id"] = user_id
                chat_data["owner_name"] = name.strip()
                chat_data["owner_username"] = member.user.username or ""
                update_chat_data(chat_id, chat_data)
            return "owner", 3
        elif member.status == "administrator":
            return "admin", 2
    except Exception as e:
        logger.debug(f"get_chat_member check failed: {e}")
        
    # 3. Check DB Admin
    if uid_str in chat_data.get("admins", {}):
        return "admin", 2
        
    # 4. Check DB Moder
    if uid_str in chat_data.get("moders", {}):
        return "moder", 1
        
    return "member", 0

def format_user_mention(user_id, name, username=None):
    if username:
        return f"@{username}"
    clean_name = (name or f"id_{user_id}").replace("[", "").replace("]", "")
    return f"[{clean_name}](tg://user?id={user_id})"

def generate_staff_message(bot, chat_id):
    """Generates a stylish hierarchy staff board."""
    chat_data = get_chat_data(chat_id)
    
    # Refresh owner & admins from Telegram if possible
    try:
        admins = bot.get_chat_administrators(chat_id)
        for adm in admins:
            u = adm.user
            uname = (u.first_name or "") + (" " + u.last_name if u.last_name else "")
            register_user_info(chat_id, u)
            if adm.status == "creator":
                chat_data["owner_id"] = u.id
                chat_data["owner_name"] = uname.strip()
                chat_data["owner_username"] = u.username or ""
    except Exception as e:
        logger.debug(f"get_chat_administrators error: {e}")
        
    update_chat_data(chat_id, chat_data)
    
    lines = ["👑 *СОСТАВ АДМИНИСТРАЦИИ*", ""]
    
    # Owner
    lines.append("👑 *Владелец:*")
    if chat_data.get("owner_id"):
        lines.append(f"└ {format_user_mention(chat_data['owner_id'], chat_data.get('owner_name'), chat_data.get('owner_username'))}")
    else:
        lines.append("└ _Не назначен (или скрыт)_")
    lines.append("")
    
    # Admins
    lines.append("🛡 *Администраторы:*")
    admins_dict = chat_data.get("admins", {})
    if admins_dict:
        adm_items = list(admins_dict.items())
        for i, (aid, ainfo) in enumerate(adm_items):
            prefix = "└" if i == len(adm_items) - 1 else "├"
            lines.append(f"{prefix} {format_user_mention(int(aid), ainfo.get('name'), ainfo.get('username'))}")
    else:
        lines.append("└ _Список пуст_")
    lines.append("")
    
    # Moders
    lines.append("⚔️ *Модерация:*")
    moders_dict = chat_data.get("moders", {})
    if moders_dict:
        mod_items = list(moders_dict.items())
        for i, (mid, minfo) in enumerate(mod_items):
            prefix = "└" if i == len(mod_items) - 1 else "├"
            lines.append(f"{prefix} {format_user_mention(int(mid), minfo.get('name'), minfo.get('username'))}")
    else:
        lines.append("└ _Список пуст_")
        
    return "\n".join(lines)
