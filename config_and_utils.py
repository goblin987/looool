import logging
import os
import json
import sqlite3
from dotenv import load_dotenv

load_dotenv()

# --- Configurations ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_TELEGRAM_ID_STR = os.getenv("ADMIN_TELEGRAM_ID") # Keep as string for now
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "lt")
RENDER_DISK_MOUNT_PATH = os.getenv("RENDER_DISK_MOUNT_PATH")

# --- Global Variables ---
translations = {}
ADMIN_IDS = [] # Will be populated in main bot.py

# --- Database Path Setup (copied from original bot.py) ---
if RENDER_DISK_MOUNT_PATH:
    if not os.path.exists(RENDER_DISK_MOUNT_PATH):
        try:
            os.makedirs(RENDER_DISK_MOUNT_PATH)
            print(f"INFO: Created RENDER_DISK_MOUNT_PATH at {RENDER_DISK_MOUNT_PATH}")
        except OSError as e:
            print(f"ERROR: Error creating RENDER_DISK_MOUNT_PATH {RENDER_DISK_MOUNT_PATH}: {e}. Using local bot.db.")
            DB_FILE_PATH = "bot.db"
    else:
        DB_FILE_PATH = os.path.join(RENDER_DISK_MOUNT_PATH, "bot.db")
else:
    DB_FILE_PATH = "bot.db"
DB_NAME = DB_FILE_PATH

# --- Logging Setup ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Core Utility Functions ---

def load_translations():
    global translations
    translations = {}
    for lang_code in ["en", "lt"]:
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(script_dir, "locales", f"{lang_code}.json")
            with open(file_path, "r", encoding="utf-8") as f:
                translations[lang_code] = json.load(f)
            logger.info(f"Successfully loaded translation file: {file_path}")
        except FileNotFoundError:
            logger.error(f"Translation file for {lang_code}.json not found at {file_path}")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from {lang_code}.json at {file_path}: {e}")
    if not translations.get("en") or not translations.get("lt"):
        logger.error("Essential English or Lithuanian translation files are missing or failed to load.")

async def get_user_language(context, user_id: int) -> str: # context can be ContextTypes.DEFAULT_TYPE
    if 'language_code' in context.user_data:
        return context.user_data['language_code']

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    result = None
    try:
        cursor.execute("SELECT language_code FROM users WHERE telegram_id = ?", (user_id,))
        result = cursor.fetchone()
    except sqlite3.Error as e:
        logger.error(f"DB error in get_user_language for user {user_id}: {e}")
    finally:
        conn.close()

    if result and result[0]:
        context.user_data['language_code'] = result[0]
        return result[0]

    context.user_data['language_code'] = DEFAULT_LANGUAGE
    return DEFAULT_LANGUAGE

async def _(context, key: str, user_id: int = None, **kwargs) -> str: # context can be ContextTypes.DEFAULT_TYPE
    actual_user_id_for_lang = user_id
    if actual_user_id_for_lang is None:
        if hasattr(context, 'effective_user') and context.effective_user:
            actual_user_id_for_lang = context.effective_user.id
        elif hasattr(context, 'chat_data') and 'user_id_for_translation' in context.chat_data:
            actual_user_id_for_lang = context.chat_data['user_id_for_translation']

    lang_code = DEFAULT_LANGUAGE
    if actual_user_id_for_lang:
        lang_code = await get_user_language(context, actual_user_id_for_lang)

    text_to_return = translations.get(lang_code, {}).get(key)
    if text_to_return is None and lang_code != DEFAULT_LANGUAGE:
        text_to_return = translations.get(DEFAULT_LANGUAGE, {}).get(key)
    if text_to_return is None and lang_code != "en" and DEFAULT_LANGUAGE != "en":
         text_to_return = translations.get("en", {}).get(key)
    if text_to_return is None:
        default_text = kwargs.pop("default", key)
        text_to_return = default_text

    try:
        if isinstance(text_to_return, str) and (("{" in text_to_return and "}" in text_to_return) or kwargs):
            return text_to_return.format(**kwargs)
        return str(text_to_return)
    except KeyError as e:
        logger.warning(f"Missing placeholder {e} for key '{key}' (lang '{lang_code}'). String: '{text_to_return}'. Kwargs: {kwargs}")
        return text_to_return
    except Exception as e:
        logger.error(f"Error formatting string for key '{key}': {e}")
        return key