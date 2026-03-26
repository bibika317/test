"""
handlers/menu.py — Главное меню, старт, проверка подписки.
"""
import logging
import os
import time
from telegram import Update
from telegram.ext import ContextTypes

from config import FORCE_SUB_CHANNEL, SUPPORT_USERNAME, E
from data.storage import get_user, save_user, is_admin, load_json, DB_DEALS, DB_CUSTOM_ORDERS
from utils.finance import get_unified_balance, format_price
from utils.helpers import btn, kb, edit_message, send_photo_message

logger = logging.getLogger(__name__)


_SUB_CACHE_TTL = int(os.getenv("SUB_CHECK_TTL", "300"))


async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not FORCE_SUB_CHANNEL:
        return True
    # Кешируем результат на короткое время, чтобы не дергать API на каждое нажатие кнопки
    cache = context.user_data.get("sub_cache")
    now = time.time()
    if cache and (now - cache.get("ts", 0)) < _SUB_CACHE_TTL:
        return cache.get("ok", True)
    try:
        member = await context.bot.get_chat_member(
            chat_id=FORCE_SUB_CHANNEL, user_id=update.effective_user.id
        )
        ok = member.status in ['member', 'administrator', 'creator']
        context.user_data["sub_cache"] = {"ok": ok, "ts": now}
        return ok
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        context.user_data["sub_cache"] = {"ok": True, "ts": now}
        return True


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Если пользователь нажал "Я подписался" — обновим кеш проверки
    if update.callback_query and update.callback_query.data == "check_sub_done":
        context.user_data.pop("sub_cache", None)
    user_id = update.effective_user.id
    user = get_user(user_id)

    # Обновляем username
    if update.effective_user.username:
        user['username'] = update.effective_user.username
        save_user(user_id, user)

    # Реферальная система
    if update.message and context.args:
        ref_code = context.args[0]
        if ref_code.startswith("ref_") and not user.get("ref_by"):
            ref_id_str = ref_code[4:]
            if ref_id_str.isdigit() and int(ref_id_str) != user_id:
                ref_id = int(ref_id_str)
                ref_user = get_user(ref_id)
                ref_user["ref_count"] = ref_user.get("ref_count", 0) + 1
                save_user(ref_id, ref_user)
                user["ref_by"] = ref_id
                save_user(user_id, user)

    # Проверка подписки
    if not await check_subscription(update, context):
        await _send_sub_required(update, context)
        return

    if user.get("is_banned"):
        text = f"{E.ERROR} <b>Аккаунт заблокирован.</b>\n\nОбратитесь в поддержку: @{SUPPORT_USERNAME}"
        await (update.message.reply_text if update.message else update.callback_query.message.reply_text)(
            text, parse_mode="HTML"
        )
        return

    # Проверяем активную сделку
    active_deal = _get_active_deal(user_id)
    active_order = _get_active_custom_order(user_id)

    bal = get_unified_balance(user)
    bal_kzt = user.get('balance_kzt', 0.0)

    text = (
        f"{E.MENU} <b>Главное меню</b>\n\n"
        f"{E.BALANCE} Баланс: <b>${bal:.2f}</b>"
        + (f" / <b>{bal_kzt:,.0f} ₸</b>" if bal_kzt > 0 else "")
        + (f"\n\n{E.DEAL} <b>Есть активная сделка!</b>" if active_deal else "")
        + (f"\n{E.CUSTOM_ORDER} <b>Есть активный заказ по запросу!</b>" if active_order else "")
    )

    rows = []
    if active_deal:
        rows.append([btn(f"{E.DEAL} К активной сделке", f"deal_status_menu_{active_deal}")])
    if active_order:
        rows.append([btn(f"{E.CUSTOM_ORDER} К активному заказу", f"cust_status_menu_BUYER_{active_order}")])

    rows += [
        [btn(f"{E.BUY} Купить номер", "menu_buy"),
         btn(f"{E.SELL} Продать номер", "menu_sell")],
        [btn(f"{E.CUSTOM_ORDER} Номер по запросу", "menu_custom_order"),
         btn(f"{E.CATALOG} Мои номера", "menu_my_numbers")],
        [btn(f"{E.BALANCE} Баланс", "menu_balance"),
         btn(f"{E.DEPOSIT} Депозит", "menu_deposit")],
        [btn(f"{E.DEAL} Сделки", "menu_my_deals"),
         btn(f"{E.TOP} Топ", "top_deposits")],
        [btn(f"{E.PROFILE} Профиль", "menu_profile"),
         btn(f"{E.ARBITRATION} Арбитраж", "menu_arbitration")],
        [btn(f"{E.SUPPORT} Поддержка", "support_contact")],
    ]

    # Кнопка админки — только для администраторов
    if is_admin(user_id):
        rows.append([btn(f"{E.ADMIN} Админ-панель", "admin_main")])

    await edit_message(update, context, text, rows, _menu_media())


def _get_active_deal(user_id):
    deals = load_json(DB_DEALS)
    for did, d in deals.items():
        if (str(d.get('buyer_id')) == str(user_id) or str(d.get('seller_id')) == str(user_id)):
            if d.get('status') not in ['completed', 'cancelled', 'refunded', 'cancelled_no_funds']:
                return did
    return None


def _get_active_custom_order(user_id):
    orders = load_json(DB_CUSTOM_ORDERS)
    for oid, o in orders.items():
        if o.get('buyer_id') == user_id and o.get('status') not in ['completed', 'cancelled']:
            return oid
    return None


async def _send_sub_required(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from config import FORCE_SUB_CHANNEL
    link = FORCE_SUB_CHANNEL if FORCE_SUB_CHANNEL.startswith("http") else \
        f"https://t.me/{FORCE_SUB_CHANNEL.lstrip('@')}"
    text = (
        f"{E.ERROR} <b>Доступ ограничен</b>\n\n"
        f"Подпишитесь на канал, затем нажмите «Я подписался»."
    )
    rows = [
        [btn("📢 Подписаться", url=link)],
        [btn(f"{E.SUCCESS} Я подписался", "check_sub_done")],
    ]
    await edit_message(update, context, text, rows, "menu.jpg")


def _file_exists(name):
    import os
    return os.path.exists(name)


def _menu_media() -> str:
    """
    По умолчанию используем статичное меню, чтобы избежать таймаутов на больших GIF.
    Включить GIF можно через переменную окружения USE_MENU_GIF=1.
    """
    use_gif = str(os.getenv("USE_MENU_GIF", "")).strip().lower() in ("1", "true", "yes")
    if use_gif and _file_exists("menu.gif"):
        return "menu.gif"
    return "menu.jpg"


async def support_contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = f"{E.SUPPORT} <b>Поддержка</b>\n\n@{SUPPORT_USERNAME}"
    rows = [[btn(f"{E.MENU} Главное меню", "start")]]
    await edit_message(update, context, text, rows, "helper.jpg")
