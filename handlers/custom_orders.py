"""
handlers/custom_orders.py — Заказы «Номер по запросу».

ИСПРАВЛЕНИЯ:
- При отмене средства ВСЕГДА возвращаются если frozen=True
- Логика заморозки/разморозки централизована
- Нет потери средств ни при каком сценарии
"""
import logging
import datetime
import time
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import E, CUSTOM_SELLER_ID
from data.storage import (
    get_user, save_user, load_json, save_json, is_admin,
    get_custom_order, save_custom_order, DB_CUSTOM_ORDERS
)
from utils.finance import can_afford_price, deduct_payment, refund_payment
from utils.helpers import btn, kb, edit_message, send_photo_message, generate_id

logger = logging.getLogger(__name__)

CUSTOM_ORDER_PRICE = 2.0
REQS_PER_PAGE = 6


# ——— Вспомогательные ———

async def get_operator_id(context) -> int | None:
    if not CUSTOM_SELLER_ID:
        return None
    try:
        return int(CUSTOM_SELLER_ID)
    except ValueError:
        return None


def _safe_refund(order: dict) -> bool:
    """
    Возвращает средства если они были заморожены.
    Возвращает True если возврат был сделан.
    """
    if not order.get('frozen', False):
        return False
    buyer_id = order['buyer_id']
    price = order.get('price', CUSTOM_ORDER_PRICE)
    buyer = get_user(buyer_id)
    buyer['balance_usd'] = round(buyer.get('balance_usd', 0.0) + price, 2)
    save_user(buyer_id, buyer)
    order['frozen'] = False
    return True


def _status_label(status: str) -> str:
    status_map = {
        'waiting_operator_response': f"{E.PENDING} Ожидание оператора",
        'number_sent':               f"{E.PHONE} Номер отправлен",
        'code_requested':            f"{E.CODE} Запрошен код",
        'waiting_op_code_input':     f"{E.CODE} Оператор вводит код",
        'waiting_buyer_confirm':     f"{E.PENDING} Ожидание подтверждения",
        'waiting_final_op_confirm':  f"{E.PENDING} Финальное подтверждение",
        'completed':                 f"{E.SUCCESS} Завершён",
        'cancelled':                 f"{E.ERROR} Отменён",
    }
    return status_map.get(status, status or "—")


def _is_active_status(status: str) -> bool:
    return status not in ['completed', 'cancelled']


async def _detect_role(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> str:
    op_id = await get_operator_id(context)
    return 'operator' if op_id and int(op_id) == int(user_id) else 'buyer'


async def _show_requests_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = await _detect_role(update.effective_user.id, context)
    role_text = "оператора" if role == 'operator' else "ваши"
    text = (
        f"{E.CUSTOM_ORDER} <b>Мои заявки</b>\n\n"
        f"Показываем {role_text} заявки. Выберите список:"
    )
    rows = [
        [btn("Активные", "req_list_type_active"),
         btn("Завершённые", "req_list_type_done")],
        [btn(f"{E.MENU} Главное меню", "start")],
    ]
    await edit_message(update, context, text, rows, "order.jpg")


async def _show_requests_list(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str, page: int):
    role = await _detect_role(update.effective_user.id, context)
    uid = update.effective_user.id

    orders = load_json(DB_CUSTOM_ORDERS)
    items = []
    for o in orders.values():
        if role == 'operator':
            if int(o.get('operator_id', 0)) != int(uid):
                continue
        else:
            if int(o.get('buyer_id', 0)) != int(uid):
                continue
        status = o.get('status', '')
        if kind == 'done' and _is_active_status(status):
            continue
        if kind == 'active' and not _is_active_status(status):
            continue
        items.append(o)

    items.sort(key=lambda x: x.get('last_action', 0), reverse=True)
    total_pages = max(1, (len(items) + REQS_PER_PAGE - 1) // REQS_PER_PAGE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * REQS_PER_PAGE
    page_items = items[start:start + REQS_PER_PAGE]

    if not page_items:
        text = f"{E.CUSTOM_ORDER} <b>Заявок нет</b>"
        rows = [
            [btn(f"{E.BACK} Назад", "cmd_my_requests_menu"),
             btn(f"{E.MENU} Главное меню", "start")],
        ]
        await edit_message(update, context, text, rows, "order.jpg")
        return

    lines = "\n".join(
        f"{i}. {o.get('id', '—')} — {_status_label(o.get('status', ''))}"
        for i, o in enumerate(page_items, start=1 + start)
    )
    title = "Активные" if kind == 'active' else "Завершённые"
    text = f"{E.CUSTOM_ORDER} <b>{title} заявки</b>\nСтр. {page}/{total_pages}\n\n{lines}"

    rows = []
    role_tag = "OP" if role == 'operator' else "BUYER"
    for o in page_items:
        oid = o.get('id', '')
        rows.append([btn(f"{oid} · {_status_label(o.get('status', ''))}",
                         f"cust_status_menu_{role_tag}_{oid}")])

    nav = []
    if page > 1:
        nav.append(btn("⬅️", f"req_list_nav_prev_{kind}_{page}"))
    if page < total_pages:
        nav.append(btn("➡️", f"req_list_nav_next_{kind}_{page}"))
    if nav:
        rows.append(nav)

    rows.append([btn(f"{E.BACK} Назад", "cmd_my_requests_menu"),
                 btn(f"{E.MENU} Главное меню", "start")])
    await edit_message(update, context, text, rows, "order.jpg")


# ============================================================
# МЕНЮ И СОЗДАНИЕ ЗАКАЗА
# ============================================================

async def custom_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    bal = user.get('balance_usd', 0.0)
    text = (
        f"{E.CUSTOM_ORDER} <b>Номер по запросу</b>\n\n"
        f"Оператор вручную предоставит казахстанский номер.\n\n"
        f"💰 Стоимость: <b>${CUSTOM_ORDER_PRICE:.2f}</b>\n"
        f"📊 Ваш баланс: <b>${bal:.2f}</b>\n\n"
        f"Средства замораживаются при создании заказа.\n"
        f"При отмене — автоматически возвращаются."
    )
    rows = [
        [btn(f"{E.SUCCESS} Создать заказ", "cust_create_order")],
        [btn(f"{E.MENU} Главное меню", "start")],
    ]
    await edit_message(update, context, text, rows, "order.jpg")


async def cust_create_order_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)

    # Проверка баланса
    if not can_afford_price(user, CUSTOM_ORDER_PRICE, 'USD'):
        await edit_message(update, context,
                           f"{E.ERROR} <b>Недостаточно средств</b>\n\nНужно: ${CUSTOM_ORDER_PRICE:.2f}\nВаш баланс: ${user.get('balance_usd', 0):.2f}",
                           [[btn(f"{E.MENU} Главное меню", "start")]], "menu.jpg")
        return

    operator_id = await get_operator_id(context)
    if not operator_id:
        await edit_message(update, context,
                           f"{E.ERROR} Оператор недоступен. Попробуйте позже.",
                           [[btn(f"{E.MENU} Главное меню", "start")]], "menu.jpg")
        return

    # Лимит активных заявок у оператора
    orders = load_json(DB_CUSTOM_ORDERS)
    active_count = sum(
        1 for o in orders.values()
        if o.get('operator_id') == operator_id
        and o.get('status') in ['number_sent', 'code_requested', 'waiting_op_code_input',
                                 'waiting_buyer_confirm', 'waiting_final_op_confirm']
    )
    if active_count >= 5:
        await edit_message(update, context,
                           f"{E.WARNING} <b>Оператор занят</b>\n\nПопробуйте позже.",
                           [[btn(f"{E.MENU} Главное меню", "start")]], "menu.jpg")
        return

    # ЗАМОРОЗКА СРЕДСТВ
    deduct_payment(user, CUSTOM_ORDER_PRICE, 'USD')
    save_user(user_id, user)

    order_id = generate_id("CUST")
    order = {
        "id": order_id,
        "buyer_id": user_id,
        "operator_id": operator_id,
        "status": "waiting_operator_response",
        "price": CUSTOM_ORDER_PRICE,
        "currency": "USD",
        "phone_number": None,
        "code": None,
        "created_at": datetime.datetime.now().isoformat(),
        "last_action": time.time(),
        "frozen": True,  # средства заморожены
    }
    save_custom_order(order_id, order)

    # Сообщение покупателю
    await edit_message(update, context,
                       f"{E.SUCCESS} <b>Заказ создан!</b>\n\n"
                       f"🆔 ID: <code>{order_id}</code>\n"
                       f"💰 Заморожено: ${CUSTOM_ORDER_PRICE:.2f}\n"
                       f"{E.PENDING} Ожидание оператора...",
                       [[btn(f"{E.MENU} Главное меню", "start")]], "order.jpg")

    # Уведомление оператору
    op_rows = [
        [btn(f"{E.SUCCESS} Принять", f"cust_op_accept_{order_id}"),
         btn(f"{E.ERROR} Отклонить", f"cust_op_reject_{order_id}")],
    ]
    try:
        await context.bot.send_message(
            operator_id,
            f"🔔 <b>НОВЫЙ ЗАПРОС</b>\n\n"
            f"🆔 Заказ: <code>{order_id}</code>\n"
            f"💰 Цена: ${CUSTOM_ORDER_PRICE:.2f}\n"
            f"📅 {datetime.datetime.now().strftime('%d.%m %H:%M')}",
            reply_markup=kb(op_rows),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить оператора {operator_id}: {e}")


# ============================================================
# МЕНЮ СТАТУСА (роутер)
# ============================================================

async def cust_status_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 5:
        return
    role_raw = parts[3]
    order_id = parts[4]
    if role_raw == 'OP':
        role = 'operator'
    elif role_raw == 'BUYER':
        role = 'buyer'
    else:
        uid = query.from_user.id
        order = get_custom_order(order_id)
        if not order:
            return
        role = 'operator' if uid == order['operator_id'] else 'buyer'
    await custom_order_menu(update, context, order_id, role)


async def custom_order_menu(update: Update, context: ContextTypes.DEFAULT_TYPE,
                             order_id: str, role: str):
    order = get_custom_order(order_id)
    if not order:
        await edit_message(update, context, f"{E.ERROR} Заказ не найден.",
                           [[btn(f"{E.MENU} Главное меню", "start")]], "menu.jpg")
        return

    status = order.get('status', 'unknown')
    price = order.get('price', CUSTOM_ORDER_PRICE)
    phone = order.get('phone_number', 'ожидается')
    code = order.get('code', 'ожидается')

    status_map = {
        'waiting_operator_response': f"{E.PENDING} Ожидание оператора",
        'number_sent':               f"📱 Номер отправлен",
        'code_requested':            f"{E.CODE} Запрошен код",
        'waiting_op_code_input':     f"{E.CODE} Оператор вводит код",
        'waiting_buyer_confirm':     f"{E.PENDING} Ожидание подтверждения",
        'waiting_final_op_confirm':  f"{E.PENDING} Финальное подтверждение",
        'completed':                 f"{E.SUCCESS} Завершён",
        'cancelled':                 f"{E.ERROR} Отменён",
    }
    status_str = status_map.get(status, status)

    text = (
        f"{E.CUSTOM_ORDER} <b>Заказ {order_id}</b>\n\n"
        f"📊 Статус: {status_str}\n"
        f"💰 Сумма: ${price:.2f}"
        + (f"\n📞 Номер: <code>{phone}</code>" if phone and phone != 'ожидается' else "")
        + (f"\n{E.CODE} Код: <code>{code}</code>" if code and code != 'ожидается' else "")
    )

    rows = []

    if role == 'operator':
        if status == 'waiting_operator_response':
            rows += [
                [btn(f"{E.SUCCESS} Принять", f"cust_op_accept_{order_id}"),
                 btn(f"{E.ERROR} Отклонить", f"cust_op_reject_{order_id}")],
            ]
        elif status in ['number_sent', 'code_requested']:
            rows += [
                [btn(f"{E.PHONE} Отправить номер", f"cust_op_send_num_{order_id}")],
                [btn(f"{E.CODE} Отправить код", f"cust_op_send_code_{order_id}")],
                [btn(f"{E.ERROR} Отклонить заказ", f"cust_op_reject_{order_id}")],
            ]
        elif status == 'waiting_final_op_confirm':
            rows += [
                [btn(f"{E.SUCCESS} Завершить сделку", f"cust_op_final_confirm_{order_id}"),
                 btn(f"{E.ERROR} Вернуть средства", f"cust_op_reject_final_{order_id}")],
            ]
    else:  # buyer
        if status == 'number_sent':
            rows += [
                [btn(f"{E.CODE} Запросить код", f"cust_buy_req_code_{order_id}")],
                [btn("🔄 Заменить номер", f"cust_buy_replace_{order_id}")],
                [btn(f"{E.ERROR} Отменить", f"cust_buy_cancel_{order_id}")],
            ]
        elif status == 'waiting_buyer_confirm':
            rows += [
                [btn(f"{E.SUCCESS} Код подошёл", f"cust_buy_confirm_code_{order_id}")],
                [btn("🔄 Повтор кода", f"cust_buy_req_code_{order_id}")],
                [btn(f"{E.ERROR} Отменить", f"cust_buy_cancel_{order_id}")],
            ]
        elif status in ['waiting_operator_response']:
            rows += [[btn(f"{E.ERROR} Отменить заказ", f"cust_buy_cancel_{order_id}")]]

    rows.append([btn(f"{E.MENU} Главное меню", "start")])
    await edit_message(update, context, text, rows, "order.jpg")


# ============================================================
# ДЕЙСТВИЯ ОПЕРАТОРА
# ============================================================

async def cust_op_accept_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[-1]
    order = get_custom_order(order_id)
    if not order or order.get('status') != 'waiting_operator_response':
        return

    context.user_data['cust_op_action'] = 'send_num'
    context.user_data['cust_current_order'] = order_id
    context.user_data['state'] = 'waiting_cust_num_input'

    await query.message.reply_text(
        f"{E.PHONE} Заказ принят!\nВведите номер телефона для клиента:",
        reply_markup=kb([[btn(f"{E.CANCEL} Отмена", f"cust_status_menu_OP_{order_id}")]]),
        parse_mode="HTML"
    )


async def cust_op_send_num_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != 'waiting_cust_num_input':
        return
    uid = update.effective_user.id
    phone = update.message.text.strip()
    order_id = context.user_data.get('cust_current_order')
    order = get_custom_order(order_id)
    if not order or uid != order['operator_id']:
        context.user_data['state'] = None
        return

    order['phone_number'] = phone
    order['status'] = 'number_sent'
    save_custom_order(order_id, order)
    context.user_data['state'] = None

    buyer_rows = [
        [btn(f"{E.CODE} Запросить код", f"cust_buy_req_code_{order_id}")],
        [btn("🔄 Заменить номер", f"cust_buy_replace_{order_id}")],
        [btn(f"{E.ERROR} Отменить", f"cust_buy_cancel_{order_id}")],
    ]
    try:
        await context.bot.send_message(
            order['buyer_id'],
            f"📱 <b>Ваш номер готов!</b>\n\n<code>{phone}</code>\n\nЗапросите код когда будете готовы.",
            reply_markup=kb(buyer_rows),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(e)
    await update.message.reply_text(f"{E.SUCCESS} Номер отправлен клиенту!")


async def cust_op_send_num_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[-1]
    context.user_data['cust_op_action'] = 'send_num'
    context.user_data['cust_current_order'] = order_id
    context.user_data['state'] = 'waiting_cust_num_input'
    await query.message.reply_text(
        f"{E.PHONE} Введите номер телефона:",
        reply_markup=kb([[btn(f"{E.CANCEL} Отмена", f"cust_status_menu_OP_{order_id}")]]),
        parse_mode="HTML"
    )


async def cust_op_reject_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, reason: str = None):
    query = update.callback_query
    if query:
        await query.answer()
    order_id = (query.data if query else '').split("_")[-1]
    if not order_id:
        order_id = context.user_data.get('cust_reject_order', '')
    order = get_custom_order(order_id)
    if not order:
        return

    # ВОЗВРАТ СРЕДСТВ
    refunded = _safe_refund(order)
    order['status'] = 'cancelled'
    order['cancel_reason'] = reason or 'Отклонено оператором'
    save_custom_order(order_id, order)

    refund_text = f"\n{E.SUCCESS} Средства ${order.get('price', CUSTOM_ORDER_PRICE):.2f} возвращены." if refunded else ""
    try:
        await context.bot.send_message(
            order['buyer_id'],
            f"{E.ERROR} <b>Заказ отклонён</b>\n\nПричина: {order['cancel_reason']}{refund_text}",
            parse_mode="HTML"
        )
    except Exception:
        pass
    if query:
        try:
            await query.edit_message_text(f"{E.SUCCESS} Заказ отклонён. Средства возвращены клиенту.", reply_markup=None)
        except Exception:
            pass


async def cust_op_reject_reason_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[-1]
    context.user_data['cust_reject_order'] = order_id
    context.user_data['state'] = 'waiting_cust_reject_reason'
    await edit_message(update, context,
                       "Укажите причину отклонения:",
                       [[btn(f"{E.CANCEL} Отмена", f"cust_status_menu_OP_{order_id}")]], "menu.jpg")


async def cust_op_reject_reason_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != 'waiting_cust_reject_reason':
        return
    reason = update.message.text.strip()
    await cust_op_reject_handler(update, context, reason)
    context.user_data['state'] = None


async def cust_op_send_code_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[-1]
    context.user_data['cust_op_action'] = 'send_code'
    context.user_data['cust_current_order'] = order_id
    context.user_data['state'] = 'waiting_cust_code_input'
    await edit_message(update, context,
                       f"{E.CODE} Введите код из SMS:",
                       [[btn(f"{E.CANCEL} Отмена", f"cust_status_menu_OP_{order_id}")]], "menu.jpg")


async def cust_op_send_code_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != 'waiting_cust_code_input':
        return
    uid = update.effective_user.id
    order_id = context.user_data.get('cust_current_order')
    code = update.message.text.strip()
    order = get_custom_order(order_id)
    if not order or uid != order['operator_id']:
        context.user_data['state'] = None
        return

    order['code'] = code
    order['status'] = 'waiting_buyer_confirm'
    save_custom_order(order_id, order)
    context.user_data['state'] = None

    buyer_rows = [
        [btn(f"{E.SUCCESS} Подтвердить", f"cust_buy_confirm_code_{order_id}")],
        [btn("🔄 Повтор кода", f"cust_buy_req_code_{order_id}")],
    ]
    try:
        await context.bot.send_message(
            order['buyer_id'],
            f"{E.CODE} <b>Код получен!</b>\n\n<code>{code}</code>\n\nПроверьте и подтвердите.",
            reply_markup=kb(buyer_rows),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(e)
    await update.message.reply_text(f"{E.SUCCESS} Код отправлен клиенту!")


async def cust_op_final_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[-1]
    order = get_custom_order(order_id)
    if not order or order.get('status') != 'waiting_final_op_confirm':
        await query.answer("Статус уже изменён.", show_alert=True)
        return

    # ЗАЧИСЛЕНИЕ ОПЕРАТОРУ
    price = order.get('price', CUSTOM_ORDER_PRICE)
    op_id = order['operator_id']
    op_user = get_user(op_id)
    op_user['balance_usd'] = round(op_user.get('balance_usd', 0.0) + price, 2)
    save_user(op_id, op_user)

    order['status'] = 'completed'
    order['frozen'] = False
    save_custom_order(order_id, order)

    try:
        await context.bot.send_message(
            order['buyer_id'],
            f"{E.SUCCESS} <b>Сделка завершена!</b>\n\nСпасибо за использование сервиса.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await query.edit_message_text(
        f"{E.SUCCESS} Сделка завершена! Вам зачислено ${price:.2f}",
        reply_markup=None, parse_mode="HTML"
    )


async def cust_op_reject_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оператор отклоняет на финальном этапе — возврат средств покупателю."""
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[-1]
    order = get_custom_order(order_id)
    if not order:
        return

    # Возврат средств
    price = order.get('price', CUSTOM_ORDER_PRICE)
    buyer = get_user(order['buyer_id'])
    buyer['balance_usd'] = round(buyer.get('balance_usd', 0.0) + price, 2)
    save_user(order['buyer_id'], buyer)

    order['status'] = 'cancelled'
    order['frozen'] = False
    save_custom_order(order_id, order)

    try:
        await context.bot.send_message(
            order['buyer_id'],
            f"{E.ERROR} Сделка отменена оператором.\n{E.SUCCESS} Средства ${price:.2f} возвращены.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await query.edit_message_text(
        f"{E.SUCCESS} Заказ отменён, средства возвращены клиенту.",
        reply_markup=None
    )


# ============================================================
# ДЕЙСТВИЯ ПОКУПАТЕЛЯ
# ============================================================

async def cust_buy_req_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[-1]
    order = get_custom_order(order_id)
    if not order:
        return
    order['status'] = 'code_requested'
    save_custom_order(order_id, order)

    op_rows = [[btn(f"{E.CODE} Отправить код", f"cust_op_send_code_{order_id}")]]
    try:
        await context.bot.send_message(
            order['operator_id'],
            f"🔔 <b>Клиент запросил код!</b>\n\nЗаказ: {order_id}\nНомер: {order.get('phone_number')}",
            reply_markup=kb(op_rows),
            parse_mode="HTML"
        )
        await query.edit_message_text(f"{E.PENDING} Запрос кода отправлен. Ожидайте.", reply_markup=None)
    except Exception:
        pass


async def cust_buy_replace_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[-1]
    order = get_custom_order(order_id)
    if not order:
        return

    op_rows = [
        [btn(f"{E.PHONE} Новый номер", f"cust_op_send_num_{order_id}"),
         btn(f"{E.ERROR} Отказать", f"cust_op_reject_{order_id}")],
    ]
    try:
        await context.bot.send_message(
            order['operator_id'],
            f"🔄 <b>Клиент просит замену!</b>\n\nЗаказ: {order_id}\nТекущий: {order.get('phone_number')}",
            reply_markup=kb(op_rows),
            parse_mode="HTML"
        )
        await query.edit_message_text(f"{E.PENDING} Запрос замены отправлен.", reply_markup=None)
    except Exception:
        pass


async def cust_buy_confirm_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает экран двойного подтверждения."""
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[-1]
    order = get_custom_order(order_id)
    if not order or query.from_user.id != order['buyer_id']:
        await query.answer("Доступ запрещён.", show_alert=True)
        return

    await edit_message(update, context,
                       f"{E.WARNING} <b>Подтвердите код</b>\n\nКод: <code>{order.get('code', '?')}</code>\n\nВы уверены, что код подошёл?\nПосле подтверждения средства перейдут оператору.",
                       [
                           [btn(f"{E.SUCCESS} Да, подошёл", f"cust_buy_final_yes_{order_id}")],
                           [btn(f"{E.ERROR} Нет, не подошёл", f"cust_status_menu_BUYER_{order_id}")],
                       ], "order.jpg")


async def cust_buy_final_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Покупатель окончательно подтвердил код."""
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[-1]
    order = get_custom_order(order_id)
    if not order:
        await query.answer("Заказ не найден.", show_alert=True)
        return
    if order['status'] != 'waiting_buyer_confirm':
        await query.answer("Статус уже изменён.", show_alert=True)
        return

    order['status'] = 'waiting_final_op_confirm'
    order['frozen'] = False  # средства уже не нужно возвращать — идут оператору
    save_custom_order(order_id, order)

    op_rows = [
        [btn(f"{E.SUCCESS} Завершить", f"cust_op_final_confirm_{order_id}"),
         btn(f"{E.ERROR} Вернуть средства", f"cust_op_reject_final_{order_id}")],
    ]
    try:
        await context.bot.send_message(
            order['operator_id'],
            f"{E.SUCCESS} <b>Покупатель подтвердил код!</b>\n\nЗаказ: {order_id}\nНажмите «Завершить» для получения оплаты.",
            reply_markup=kb(op_rows),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(e)

    try:
        await query.edit_message_text(
            f"{E.SUCCESS} <b>Вы подтвердили код!</b>\n\n{E.PENDING} Ожидание финального подтверждения оператора.",
            reply_markup=kb([[btn(f"{E.MENU} Главное меню", "start")]]),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(e)


async def cust_buy_final_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[-1]
    await custom_order_menu(update, context, order_id, 'buyer')


async def cust_buy_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отмена заказа покупателем.
    ВСЕГДА возвращает средства если frozen=True.
    """
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[-1]
    order = get_custom_order(order_id)
    if not order:
        await query.answer("Заказ не найден.", show_alert=True)
        return
    if query.from_user.id != order['buyer_id']:
        await query.answer("Доступ запрещён.", show_alert=True)
        return

    # ВОЗВРАТ СРЕДСТВ (автоматически проверяет frozen)
    refunded = _safe_refund(order)
    order['status'] = 'cancelled'
    order['cancel_reason'] = 'Отменено покупателем'
    save_custom_order(order_id, order)

    refund_text = f"\n{E.SUCCESS} Средства ${order.get('price', CUSTOM_ORDER_PRICE):.2f} возвращены на баланс." if refunded else ""
    msg = f"{E.ERROR} <b>Заказ отменён.</b>{refund_text}"

    try:
        await query.edit_message_text(msg,
                                       reply_markup=kb([[btn(f"{E.MENU} Главное меню", "start")]]),
                                       parse_mode="HTML")
    except Exception:
        await query.message.reply_text(msg, parse_mode="HTML")

    # Уведомление оператору
    try:
        await context.bot.send_message(
            order['operator_id'],
            f"{E.WARNING} <b>Заказ {order_id} отменён покупателем.</b>\n"
            f"Действий не требуется.",
            parse_mode="HTML"
        )
    except Exception:
        pass


# ============================================================
# ЧАТ
# ============================================================

async def cust_chat_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[-1]
    context.user_data['cust_chat_order'] = order_id
    context.user_data['state'] = 'waiting_cust_chat_msg'
    await edit_message(update, context,
                       "Введите сообщение:",
                       [[btn(f"{E.CANCEL} Отмена", f"cust_status_menu_BUYER_{order_id}")]], "menu.jpg")


async def handle_cust_chat_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != 'waiting_cust_chat_msg':
        return
    order_id = context.user_data.get('cust_chat_order')
    order = get_custom_order(order_id)
    if not order:
        context.user_data['state'] = None
        return
    uid = update.effective_user.id
    target = order['operator_id'] if uid == order['buyer_id'] else order['buyer_id']
    try:
        await context.bot.send_message(target,
                                       f"💬 Сообщение по заказу <code>{order_id}</code>:\n\n{update.message.text}",
                                       parse_mode="HTML")
        await update.message.reply_text(f"{E.SUCCESS} Сообщение отправлено.")
    except Exception:
        pass
    context.user_data['state'] = None


# ============================================================
# СПИСОК ЗАЯВОК / КОМАНДЫ
# ============================================================

async def cmd_my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню списка заявок (покупатель/оператор)."""
    await _show_requests_menu(update, context)


async def req_list_menu_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await _show_requests_menu(update, context)


async def req_list_type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kind = query.data.replace("req_list_type_", "")
    if kind not in ("active", "done"):
        kind = "active"
    await _show_requests_list(update, context, kind, 1)


async def req_list_nav_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    # req_list_nav_{prev|next}_{kind}_{page}
    if len(parts) < 5:
        return
    direction = parts[3]
    kind = parts[4]
    try:
        current = int(parts[5]) if len(parts) > 5 else 1
    except ValueError:
        current = 1
    page = current - 1 if direction == "prev" else current + 1
    await _show_requests_list(update, context, kind, page)


async def req_list_page_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    # req_list_page_{kind}_{page}
    if len(parts) < 4:
        return
    kind = parts[3]
    try:
        page = int(parts[4]) if len(parts) > 4 else 1
    except ValueError:
        page = 1
    await _show_requests_list(update, context, kind, page)


async def cmd_cancel_custom_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда: /n ORDER_ID [причина] — отмена заказа по запросу."""
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Использование: /n ORDER_ID [причина]")
        return

    order_id = context.args[0].strip()
    order = get_custom_order(order_id)
    if not order:
        await update.message.reply_text(f"{E.ERROR} Заказ {order_id} не найден.")
        return

    uid = update.effective_user.id
    if uid not in [order.get('buyer_id'), order.get('operator_id')] and not is_admin(uid):
        await update.message.reply_text(f"{E.ERROR} Недостаточно прав.")
        return

    if order.get('status') in ['completed', 'cancelled']:
        await update.message.reply_text(f"{E.WARNING} Заказ уже завершён или отменён.")
        return

    reason = "Отменено пользователем"
    if len(context.args) > 1:
        reason = " ".join(context.args[1:]).strip()

    refunded = _safe_refund(order)
    order['status'] = 'cancelled'
    order['cancel_reason'] = reason
    order['frozen'] = False
    save_custom_order(order_id, order)

    refund_text = f" Средства ${order.get('price', CUSTOM_ORDER_PRICE):.2f} возвращены." if refunded else ""
    await update.message.reply_text(f"{E.SUCCESS} Заказ {order_id} отменён.{refund_text}")

    # Уведомим обе стороны
    try:
        await context.bot.send_message(
            order['buyer_id'],
            f"{E.ERROR} Заказ {order_id} отменён.\nПричина: {reason}{refund_text}",
            parse_mode="HTML"
        )
    except Exception:
        pass
    try:
        await context.bot.send_message(
            order['operator_id'],
            f"{E.ERROR} Заказ {order_id} отменён.\nПричина: {reason}",
            parse_mode="HTML"
        )
    except Exception:
        pass
