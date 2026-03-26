"""
data/storage.py — Работа с базой данных (JSON-файлы).
"""
import os
import json
import datetime
import logging
from config import (
    DB_USERS, DB_NUMBERS, DB_DEALS, DB_CHECKS,
    DB_CANCEL_REQUESTS, DB_ADMIN_SETTINGS, DB_WITHDRAW_REQUESTS,
    DB_WARNINGS, DB_ARBITRATIONS, DB_DEPOSIT_WITHDRAW_REQUESTS,
    DB_PROMOCODES, DB_CUSTOM_ORDERS
)

logger = logging.getLogger(__name__)

_LIST_DBS = {DB_NUMBERS, DB_ARBITRATIONS, DB_DEPOSIT_WITHDRAW_REQUESTS, DB_CHECKS,
             DB_CANCEL_REQUESTS, DB_WITHDRAW_REQUESTS}


def load_json(filename):
    try:
        if not os.path.exists(filename):
            default = [] if filename in _LIST_DBS else {}
            save_json(filename, default)
            return default
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return [] if filename in _LIST_DBS else {}
            return json.loads(content)
    except Exception as e:
        logger.error(f"Ошибка загрузки {filename}: {e}")
        return [] if filename in _LIST_DBS else {}


def save_json(filename, data):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения {filename}: {e}")


def init_db():
    files = [
        (DB_USERS, {}),
        (DB_DEALS, {}),
        (DB_CHECKS, []),
        (DB_CUSTOM_ORDERS, {}),
        (DB_CANCEL_REQUESTS, []),
        (DB_ADMIN_SETTINGS, {"crypto_link": "", "card_details": "", "usd_kzt_rate": 450.0}),
        (DB_WITHDRAW_REQUESTS, []),
        (DB_WARNINGS, {}),
        (DB_ARBITRATIONS, []),
        (DB_PROMOCODES, {}),
        (DB_DEPOSIT_WITHDRAW_REQUESTS, []),
    ]
    for filename, default in files:
        if not os.path.exists(filename):
            save_json(filename, default)
    if not os.path.exists(DB_NUMBERS):
        save_json(DB_NUMBERS, [])


# ——— Пользователи ———

def get_user(user_id):
    users = load_json(DB_USERS)
    uid_str = str(user_id)
    if uid_str not in users:
        users[uid_str] = {
            "balance_usd": 0.0,
            "balance_kzt": 0.0,
            "deposit_usd": 0.0,
            "deposit_kzt": 0.0,
            "ref_by": None,
            "ref_count": 0,
            "is_admin": False,
            "username": None,
            "is_banned": False,
            "last_deal_end_time": 0,
            "last_withdraw_time": 0,
            "created_at": datetime.datetime.now().isoformat(),
        }
        save_json(DB_USERS, users)
    else:
        u = users[uid_str]
        # Миграция старых ключей
        for key in ["balance_usd", "balance_kzt", "deposit_usd", "deposit_kzt",
                    "last_deal_end_time", "last_withdraw_time"]:
            if key not in u:
                u[key] = 0 if "time" in key else 0.0
            for spaces in range(1, 4):
                old = key + " " * spaces
                if old in u:
                    u[key] = u.pop(old)
        if "is_banned" not in u:
            u["is_banned"] = False
        if "created_at" not in u:
            u["created_at"] = datetime.datetime.now().isoformat()
            save_json(DB_USERS, users)
    return users[uid_str]


def save_user(user_id, data):
    users = load_json(DB_USERS)
    users[str(user_id)] = data
    save_json(DB_USERS, users)


def is_admin(user_id):
    from config import ADMIN_IDS, ADMIN_ID
    if user_id in ADMIN_IDS:
        return True
    if user_id == ADMIN_ID:
        return True
    return get_user(user_id).get("is_admin", False)


# ——— Заказы по запросу ———

def get_custom_order(order_id):
    return load_json(DB_CUSTOM_ORDERS).get(order_id)


def save_custom_order(order_id, data):
    orders = load_json(DB_CUSTOM_ORDERS)
    orders[order_id] = data
    save_json(DB_CUSTOM_ORDERS, orders)


# ——— Настройки ———

def get_rate():
    settings = load_json(DB_ADMIN_SETTINGS)
    return float(settings.get("usd_kzt_rate", 450.0))
