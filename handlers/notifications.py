"""
handlers/notifications.py — Рассылки и уведомления.
"""
import logging
from telegram.ext import ContextTypes
from telegram import InlineKeyboardMarkup

from config import E, MARKET_NAME, SUPPORT_USERNAME
from data.storage import load_json, DB_USERS, get_user
from utils.finance import get_rate
from utils.helpers import btn, kb

logger = logging.getLogger(__name__)


async def broadcast_new_seller(context: ContextTypes.DEFAULT_TYPE, seller_id: int, deposit_usd: float):
    users = load_json(DB_USERS)
    seller = get_user(seller_id)
    uname = f"@{seller.get('username', 'ID' + str(seller_id))}"
    text = (
        f"🔔 <b>НОВЫЙ ПРОДАВЕЦ!</b>\n\n"
        f"{E.SUCCESS} {uname} — депозит <b>${deposit_usd:.2f}</b>\n"
        f"{MARKET_NAME} гарантирует сделки до ${deposit_usd:.2f}\n\n"
        f"🛡 Поддержка: @{SUPPORT_USERNAME}"
    )
    markup = kb([[btn(f"📂 Номера {uname}", f"view_seller_numbers_{seller_id}")],
                 [btn(f"{E.MENU} Главное меню", "start")]])

    import os
    photo_path = "deposit_success.jpg" if os.path.exists("deposit_success.jpg") else "menu.jpg"
    count = 0
    for uid in users:
        if str(uid) == str(seller_id):
            continue
        if users[uid].get('is_banned'):
            continue
        try:
            with open(photo_path, 'rb') as f:
                await context.bot.send_photo(chat_id=int(uid), photo=f, caption=text,
                                             reply_markup=markup, parse_mode="HTML")
            count += 1
        except Exception:
            pass
    logger.info(f"Рассылка о новом продавце: {count} получателей.")


async def broadcast_guarantee_lost(context: ContextTypes.DEFAULT_TYPE, seller_id: int,
                                    lost_amount: float, reason: str):
    users = load_json(DB_USERS)
    seller = get_user(seller_id)
    uname = f"@{seller.get('username', 'ID' + str(seller_id))}"
    text = (
        f"⚖️ Средства из депозита изъяты у {uname}\n"
        f"💰 Сумма: ${lost_amount:.2f}\n\n"
        f"• {MARKET_NAME} больше не несёт ответственность за сделки с {uname}\n"
        f"📝 Причина: подан запрос на вывод депозита. Через 72ч депозит обнулён.\n"
        f"Открытые сделки: @{SUPPORT_USERNAME}"
    )
    markup = kb([[btn(f"{E.MENU} Главное меню", "start")]])
    import os
    photo_path = "deposit_warning.jpg" if os.path.exists("deposit_warning.jpg") else "menu.jpg"
    for uid in users:
        if str(uid) == str(seller_id):
            continue
        if users[uid].get('is_banned'):
            continue
        try:
            with open(photo_path, 'rb') as f:
                await context.bot.send_photo(chat_id=int(uid), photo=f, caption=text,
                                             reply_markup=markup, parse_mode="HTML")
        except Exception:
            pass


async def broadcast_deposit_withdrawn(context: ContextTypes.DEFAULT_TYPE, user_id: int,
                                       withdrawn_usd: float, reason: str):
    users = load_json(DB_USERS)
    user = get_user(user_id)
    uname = f"@{user.get('username', 'ID' + str(user_id))}"
    text = (
        f"📤 {uname} вывел из депозита ${withdrawn_usd:.2f}\n"
        f"Причина: {reason or '—'}"
    )
    for uid in users:
        if str(uid) == str(user_id):
            continue
        if users[uid].get('is_banned'):
            continue
        try:
            await context.bot.send_message(chat_id=int(uid), text=text, parse_mode="HTML")
        except Exception:
            pass
