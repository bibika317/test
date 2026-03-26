import os
import re
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# ОСНОВНЫЕ НАСТРОЙКИ
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

def _parse_admin_ids(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return []
    # Support comma/space/semicolon separated IDs: "1, 2 3;4"
    parts = re.split(r"[,\s;]+", raw)
    ids = []
    for p in parts:
        if not p:
            continue
        try:
            val = int(p)
        except ValueError:
            continue
        if val > 0:
            ids.append(val)
    return ids


ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_ID", ""))
ADMIN_ID = ADMIN_IDS[0] if ADMIN_IDS else 0
CUSTOM_SELLER_ID = os.getenv("CUSTOM_SELLER_ID", "")
MARKET_NAME = os.getenv("MARKET_NAME", "PRIME SMS")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "support")

CRYPTO_PAY_LINK = os.getenv("CRYPTO_PAY_LINK", "")
FORCE_SUB_CHANNEL = os.getenv("FORCE_SUB_CHANNEL", "")

MARKET_FEE_PERCENT = float(os.getenv("MARKET_FEE_PERCENT", "0.05"))
SECURITY_LOCK_MINUTES = int(os.getenv("SECURITY_LOCK_MINUTES", "15"))

REF_BONUS_AMOUNT = float(os.getenv("REF_BONUS_AMOUNT", "0.5"))
REF_REQUIRED_COUNT = int(os.getenv("REF_REQUIRED_COUNT", "10"))
REF_MAX_BONUS_TIMES = int(os.getenv("REF_MAX_BONUS_TIMES", "1"))

# ============================================================
# ПУТИ К ФАЙЛАМ
# ============================================================
if os.path.exists('/data') and os.path.isdir('/data'):
    DATA_DIR = '/data'
else:
    DATA_DIR = '.'

def get_db_path(filename):
    return os.path.join(DATA_DIR, filename.strip())

DB_USERS          = get_db_path("users.txt")
DB_NUMBERS        = get_db_path("numbers.txt")
DB_DEALS          = get_db_path("deals.txt")
DB_CHECKS         = get_db_path("checks.txt")
DB_CANCEL_REQUESTS = get_db_path("cancel_requests.txt")
DB_ADMIN_SETTINGS = get_db_path("admin_settings.txt")
DB_WITHDRAW_REQUESTS = get_db_path("withdraw_requests.txt")
DB_WARNINGS       = get_db_path("warnings.txt")
DB_ARBITRATIONS   = get_db_path("arbitrations.txt")
DB_DEPOSIT_WITHDRAW_REQUESTS = get_db_path("deposit_withdraw_requests.txt")
DB_PROMOCODES     = get_db_path("promocodes.txt")
DB_CUSTOM_ORDERS  = get_db_path("custom_orders.txt")

# ============================================================
# КОНСТАНТЫ
# ============================================================
COUNTRY_FLAGS = {"KAZAKHSTAN": "🇰🇿"}
DEFAULT_COUNTRY = "KAZAKHSTAN"
EXAMPLE_NUMBER = "+77000999333"
ITEMS_PER_PAGE = 10
TOP_DEPOSITS_COUNT = 5
SELLERS_PER_PAGE = 10
ORDER_PHOTO = "order.jpg"

# ============================================================
# ЭМОДЗИ — автоматически подставляет премиум если указан ID
# ============================================================
def _e(key: str, default: str) -> str:
    """
    Возвращает кастомный эмодзи-тег для премиум эмодзи,
    либо обычный эмодзи если премиум ID не задан.

    Премиум эмодзи в Telegram: <tg-emoji emoji-id="ID">FALLBACK</tg-emoji>
    Работает только при parse_mode="HTML".
    """
    premium_id = os.getenv(f"{key}_PREMIUM_ID", "").strip()
    plain = os.getenv(key, default).strip()
    if premium_id:
        return f'<tg-emoji emoji-id="{premium_id}">{plain}</tg-emoji>'
    return plain


class E:
    """Глобальные эмодзи. Используй E.SUCCESS, E.MENU и т.д."""
    MENU          = _e("EMOJI_MENU", "🏠")
    BACK          = _e("EMOJI_BACK", "🔙")
    CANCEL        = _e("EMOJI_CANCEL", "❌")
    BALANCE       = _e("EMOJI_BALANCE", "💰")
    DEPOSIT       = _e("EMOJI_DEPOSIT", "🏦")
    WITHDRAW      = _e("EMOJI_WITHDRAW", "💸")
    MONEY         = _e("EMOJI_MONEY", "💵")
    CATALOG       = _e("EMOJI_CATALOG", "📋")
    BUY           = _e("EMOJI_BUY", "🛒")
    SELL          = _e("EMOJI_SELL", "📤")
    DEAL          = _e("EMOJI_DEAL", "🤝")
    PHONE         = _e("EMOJI_PHONE", "📞")
    SUCCESS       = _e("EMOJI_SUCCESS", "✅")
    ERROR         = _e("EMOJI_ERROR", "❌")
    WARNING       = _e("EMOJI_WARNING", "⚠️")
    PENDING       = _e("EMOJI_PENDING", "⏳")
    CODE          = _e("EMOJI_CODE", "🔑")
    PROFILE       = _e("EMOJI_PROFILE", "👤")
    REF           = _e("EMOJI_REF", "🔗")
    TOP           = _e("EMOJI_TOP", "🏆")
    SUPPORT       = _e("EMOJI_SUPPORT", "💬")
    ARBITRATION   = _e("EMOJI_ARBITRATION", "⚖️")
    CUSTOM_ORDER  = _e("EMOJI_CUSTOM_ORDER", "📦")
    ADMIN         = _e("EMOJI_ADMIN", "🛡")
    STATS         = _e("EMOJI_STATS", "📊")
    SETTINGS      = _e("EMOJI_SETTINGS", "⚙️")
