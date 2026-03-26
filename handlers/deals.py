"""
handlers/deals.py — Основные сделки между покупателем и продавцом.
"""
import datetime
import logging
import os
import time
from telegram import Update
from telegram.ext import ContextTypes

from config import E, SUPPORT_USERNAME, ORDER_PHOTO, SECURITY_LOCK_MINUTES
from data.storage import (
    get_user, save_user, load_json, save_json,
    DB_DEALS, DB_NUMBERS, DB_USERS, DB_ARBITRATIONS, DB_WITHDRAW_REQUESTS
)
from utils.finance import (
    can_afford_price, deduct_payment, refund_payment,
    format_price, get_unified_balance, get_rate
)
from utils.helpers import btn, kb, edit_message, send_photo_message, generate_id, format_number

logger = logging.getLogger(__name__)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ
# ============================================================

def format_number(number: str) -> str:
    clean = ''.join(c for c in number if c.isdigit())
    if len(clean) == 11 and clean.startswith('77'):
        return f"+{clean[0]} {clean[1:4]} {clean[4:7]} {clean[7:9]} {clean[9:11]}"
    return f"+{clean}" if clean else number


async def cancel_deal_logic(update, context, deal_id: str, reason: str, initiator: str = "system"):
    deals = load_json(DB_DEALS)
    deal = deals.get(deal_id)
    if not deal:
        return
    if deal.get('status') in ['completed', 'cancelled', 'refunded']:
        return

    buyer_id = deal['buyer_id']
    seller_id = deal['seller_id']

    # Возврат средств покупателю если они были заморожены
    if deal.get('frozen_amount') and deal.get('status') == 'active':
        price = deal['frozen_amount']
        currency = deal.get('number_data', {}).get('currency', 'USD')
        buyer_u = get_user(buyer_id)
        buyer_u = refund_payment(buyer_u, price, currency)
        save_user(buyer_id, buyer_u)

    # Возврат номера в каталог
    nums = load_json(DB_NUMBERS)
    for n in nums:
        if n['id'] == deal.get('number_id'):
            n['status'] = 'active'
            break
    save_json(DB_NUMBERS, nums)

    deal['status'] = 'cancelled'
    deal['cancel_reason'] = reason
    deal['cancelled_at'] = datetime.datetime.now().isoformat()
    deals[deal_id] = deal
    save_json(DB_DEALS, deals)

    # Обновляем время последней сделки
    for uid in [buyer_id, seller_id]:
        u = get_user(uid)
        u['last_deal_end_time'] = time.time()
        save_user(uid, u)

    cancel_text = f"{E.CANCEL} <b>Сделка {deal_id} отменена</b>\nПричина: {reason}"
    for uid in [buyer_id, seller_id]:
        try:
            await context.bot.send_message(uid, cancel_text, parse_mode="HTML")
        except Exception:
            pass


# ============================================================
# МОИ СДЕЛКИ
# ============================================================

async def my_deals_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    deals = load_json(DB_DEALS)
    my = [d for d in deals.values()
          if str(d.get('buyer_id')) == str(uid) or str(d.get('seller_id')) == str(uid)]
    active = [d for d in my if d.get('status') not in ['completed', 'cancelled', 'refunded']]
    finished = [d for d in my if d.get('status') in ['completed', 'cancelled', 'refunded']]
    text = f"{E.DEAL} <b>Мои сделки</b>"
    rows = [
        [btn(f"🟢 Активные ({len(active)})", "my_deals_list_active"),
         btn(f"⚪ Завершённые ({len(finished)})", "my_deals_list_finished")],
        [btn(f"{E.MENU} Главное меню", "start")],
    ]
    await edit_message(update, context, text, rows, "menu.jpg")


async def my_deals_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mode = query.data.split("_")[-1]
    uid = query.from_user.id
    deals = load_json(DB_DEALS)
    my = [d for d in deals.values()
          if str(d.get('buyer_id')) == str(uid) or str(d.get('seller_id')) == str(uid)]
    if mode == 'active':
        target = [d for d in my if d.get('status') not in ['completed', 'cancelled', 'refunded']]
    else:
        target = [d for d in my if d.get('status') in ['completed', 'cancelled', 'refunded']]

    if not target:
        await edit_message(update, context, "Пусто.",
                           [[btn(f"{E.BACK} Назад", "menu_my_deals")]], "menu.jpg")
        return
    rows = [
        [btn(f"{format_number(d.get('number_data', {}).get('number', '?'))} · {format_price(d.get('number_data', {}).get('price', 0), d.get('number_data', {}).get('currency', 'USD'))}",
             f"deal_status_menu_{d['id']}")]
        for d in target
    ]
    rows.append([btn(f"{E.BACK} Назад", "menu_my_deals")])
    title = "🟢 Активные" if mode == 'active' else "⚪ Завершённые"
    await edit_message(update, context, f"{E.DEAL} <b>{title}</b>", rows, "menu.jpg")


# ============================================================
# СТАТУС СДЕЛКИ
# ============================================================

async def deal_status_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    deal_id = query.data.split("_")[-1]
    deals = load_json(DB_DEALS)
    deal = deals.get(deal_id)
    if not deal:
        await query.answer("Сделка не найдена.", show_alert=True)
        return

    uid = query.from_user.id
    is_buyer = uid == deal.get('buyer_id')
    num = format_number(deal.get('number_data', {}).get('number', '?'))
    price = deal.get('number_data', {}).get('price', 0)
    currency = deal.get('number_data', {}).get('currency', 'USD')
    status = deal.get('status', '—')

    status_map = {
        'pending_confirm': f"{E.PENDING} Ожидание подтверждения",
        'active': f"🟢 Активна",
        'waiting_code_review': f"{E.CODE} Код отправлен",
        'completed': f"{E.SUCCESS} Завершена",
        'cancelled': f"{E.CANCEL} Отменена",
    }
    status_text = status_map.get(status, status)
    code_type = deal.get('code_type') or deal.get('number_data', {}).get('code_type')
    code_label = "SMS" if code_type == 'sms' else "Аудио" if code_type == 'audio' else None

    text = (
        f"{E.DEAL} <b>Сделка {deal_id}</b>\n\n"
        f"{E.PHONE} Номер: <code>{num}</code>\n"
        f"💰 {format_price(price, currency)}\n"
        f"Статус: {status_text}"
    )
    if code_label:
        text += f"\n{E.CODE} Тип кода: {code_label}"
    rows = []
    if status == 'active':
        if is_buyer:
            rows.append([btn(f"{E.CODE} Запросить код", f"deal_request_code_{deal_id}")])
            rows.append([btn(f"{E.CANCEL} Отменить", f"deal_cancel_buyer_{deal_id}")])
        else:
            rows.append([btn(f"{E.CANCEL} Отменить", f"deal_cancel_seller_{deal_id}")])
    elif status == 'pending_confirm':
        role = 'buyer' if is_buyer else 'seller'
        rows.append([btn(f"{E.SUCCESS} Подтвердить", f"deal_start_confirm_{deal_id}_{role}"),
                     btn(f"{E.CANCEL} Отклонить", f"deal_start_reject_{deal_id}")])
    rows.append([btn(f"{E.MENU} Главное меню", "start")])
    await edit_message(update, context, text, rows, ORDER_PHOTO)


async def deal_status_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await deal_status_menu(update, context)


# ============================================================
# СОЗДАНИЕ СДЕЛКИ
# ============================================================

async def create_deal_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split("_")
    code_type = None
    nid = None
    # create_deal_sms_{NID} | create_deal_audio_{NID} | create_deal_{NID}
    if len(parts) >= 4 and parts[0] == "create" and parts[1] == "deal" and parts[2] in ("sms", "audio"):
        code_type = parts[2]
        nid = parts[3]
    else:
        nid = data.replace("create_deal_", "")
    uid = query.from_user.id

    nums = load_json(DB_NUMBERS)
    num_data = next((n for n in nums if n.get('id') == nid and n.get('status') == 'active'), None)
    if not num_data:
        await query.answer("Номер недоступен.", show_alert=True)
        return

    seller_id = num_data.get('seller_id')
    if seller_id == uid:
        await query.answer("Нельзя купить свой номер.", show_alert=True)
        return

    buyer_u = get_user(uid)
    if not can_afford_price(buyer_u, num_data['price'], num_data['currency']):
        await edit_message(update, context,
                           f"{E.ERROR} Недостаточно средств!\nНужно: {format_price(num_data['price'], num_data['currency'])}",
                           [[btn(f"{E.MENU} Главное меню", "start")]], "menu.jpg")
        return

    deal_id = generate_id("DEAL")
    chosen_code = code_type or num_data.get('code_type') or 'sms'
    deal = {
        'id': deal_id,
        'buyer_id': uid,
        'seller_id': seller_id,
        'number_id': nid,
        'number_data': num_data,
        'code_type': chosen_code,
        'status': 'pending_confirm',
        'buyer_confirmed_start': False,
        'seller_confirmed_start': False,
        'frozen_amount': None,
        'created_at': datetime.datetime.now().isoformat(),
        'last_action': time.time(),
    }

    # Блокируем номер
    for n in nums:
        if n['id'] == nid:
            n['status'] = 'in_deal'
            break
    save_json(DB_NUMBERS, nums)

    deals = load_json(DB_DEALS)
    deals[deal_id] = deal
    save_json(DB_DEALS, deals)

    num_str = format_number(num_data['number'])
    price_str = format_price(num_data['price'], num_data['currency'])
    code_label = "SMS" if chosen_code == 'sms' else "Аудио"
    info = (
        f"{E.DEAL} <b>Новая сделка!</b>\n\n"
        f"{E.PHONE} Номер: <code>{num_str}</code>\n"
        f"💰 {price_str}\n"
        f"{E.CODE} Тип кода: {code_label}\n"
        f"🆔 ID: <code>{deal_id}</code>\n\n"
        f"Обе стороны должны подтвердить начало."
    )
    kb_buyer = kb([
        [btn(f"{E.SUCCESS} Подтвердить", f"deal_start_confirm_{deal_id}_buyer"),
         btn(f"{E.CANCEL} Отклонить", f"deal_start_reject_{deal_id}")],
    ])
    kb_seller = kb([
        [btn(f"{E.SUCCESS} Подтвердить", f"deal_start_confirm_{deal_id}_seller"),
         btn(f"{E.CANCEL} Отклонить", f"deal_start_reject_{deal_id}")],
    ])
    try:
        if os.path.exists(ORDER_PHOTO):
            with open(ORDER_PHOTO, 'rb') as f:
                photo_bytes = f.read()
            await context.bot.send_photo(uid, photo=photo_bytes, caption=info, reply_markup=kb_buyer, parse_mode="HTML")
            await context.bot.send_photo(seller_id, photo=photo_bytes, caption=info, reply_markup=kb_seller, parse_mode="HTML")
        else:
            await context.bot.send_message(uid, info, reply_markup=kb_buyer, parse_mode="HTML")
            await context.bot.send_message(seller_id, info, reply_markup=kb_seller, parse_mode="HTML")
    except Exception as e:
        logger.error(e)

    await edit_message(update, context, f"{E.PENDING} Запрос отправлен. Сделка <code>{deal_id}</code>",
                       [[btn(f"{E.MENU} Главное меню", "start")]], "menu.jpg")


# ============================================================
# ПОДТВЕРЖДЕНИЕ НАЧАЛА
# ============================================================

async def deal_start_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 5:
        return
    deal_id = parts[3]
    role = parts[4]
    deals = load_json(DB_DEALS)
    deal = deals.get(deal_id)
    if not deal:
        return
    uid = query.from_user.id
    if role == 'buyer' and uid != deal.get('buyer_id'):
        return
    if role == 'seller' and uid != deal.get('seller_id'):
        return

    if role == 'buyer':
        deal['buyer_confirmed_start'] = True
    else:
        deal['seller_confirmed_start'] = True
    deals[deal_id] = deal
    save_json(DB_DEALS, deals)

    if deal['buyer_confirmed_start'] and deal['seller_confirmed_start']:
        # Замораживаем средства
        price = deal['number_data']['price']
        currency = deal['number_data']['currency']
        buyer_id = deal['buyer_id']
        seller_id = deal['seller_id']
        users = load_json(DB_USERS)
        buyer_u = users.get(str(buyer_id), {})
        if not can_afford_price(buyer_u, price, currency):
            deal['status'] = 'cancelled_no_funds'
            deals[deal_id] = deal
            save_json(DB_DEALS, deals)
            nums = load_json(DB_NUMBERS)
            for n in nums:
                if n['id'] == deal['number_id']:
                    n['status'] = 'active'
                    break
            save_json(DB_NUMBERS, nums)
            await query.edit_message_text(f"{E.ERROR} Недостаточно средств у покупателя.", parse_mode="HTML")
            try:
                await context.bot.send_message(seller_id, f"{E.CANCEL} Сделка отменена: нет средств у покупателя.")
                await context.bot.send_message(buyer_id, f"{E.CANCEL} Сделка отменена: недостаточно средств.")
            except Exception:
                pass
            return

        deduct_payment(buyer_u, price, currency)
        deal['frozen_amount'] = price
        save_user(buyer_id, buyer_u)
        deal['status'] = 'active'
        deals[deal_id] = deal
        save_json(DB_DEALS, deals)

        num_str = format_number(deal['number_data']['number'])
        code_type = deal.get('code_type') or deal.get('number_data', {}).get('code_type') or 'sms'
        code_label = "SMS" if code_type == 'sms' else "аудио"
        msg = (
            f"{E.SUCCESS} <b>Сделка {deal_id} началась!</b>\n\n"
            f"{E.PHONE} Номер: <code>{num_str}</code>\n"
            f"Средства заморожены. Запросите {code_label}-код когда будете готовы."
        )
        kb_buy = kb([
            [btn(f"{E.CODE} Запросить код", f"deal_request_code_{deal_id}"),
             btn(f"{E.CANCEL} Отменить", f"deal_cancel_buyer_{deal_id}")],
            [btn(f"{E.MENU} Главное меню", "start")],
        ])
        kb_sell = kb([
            [btn(f"{E.CANCEL} Отменить", f"deal_cancel_seller_{deal_id}"),
             btn(f"{E.MENU} Главное меню", "start")],
        ])
        try:
            if os.path.exists(ORDER_PHOTO):
                with open(ORDER_PHOTO, 'rb') as f:
                    photo_bytes = f.read()
                await context.bot.send_photo(buyer_id, photo=photo_bytes, caption=msg, reply_markup=kb_buy, parse_mode="HTML")
                await context.bot.send_photo(seller_id, photo=photo_bytes, caption=msg, reply_markup=kb_sell, parse_mode="HTML")
            else:
                await context.bot.send_message(buyer_id, msg, reply_markup=kb_buy, parse_mode="HTML")
                await context.bot.send_message(seller_id, msg, reply_markup=kb_sell, parse_mode="HTML")
        except Exception as e:
            logger.error(e)
        await query.edit_message_text(f"{E.SUCCESS} Сделка началась!", parse_mode="HTML")
    else:
        await query.edit_message_text(
            f"✅ Вы подтвердили. Ожидание второй стороны...\n"
            f"👤 Покупатель: {'✅' if deal['buyer_confirmed_start'] else '⏳'}\n"
            f"👤 Продавец: {'✅' if deal['seller_confirmed_start'] else '⏳'}",
            parse_mode="HTML"
        )


async def deal_start_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    deal_id = parts[3]
    nums = load_json(DB_NUMBERS)
    deals = load_json(DB_DEALS)
    deal = deals.get(deal_id)
    if deal:
        for n in nums:
            if n['id'] == deal.get('number_id'):
                n['status'] = 'active'
                break
        save_json(DB_NUMBERS, nums)
    await cancel_deal_logic(update, context, deal_id, "Одна из сторон отклонила", "system")
    await edit_message(update, context, f"{E.CANCEL} Сделка отклонена.",
                       [[btn(f"{E.MENU} Главное меню", "start")]], "menu.jpg")


# ============================================================
# КОД
# ============================================================

async def deal_request_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    deal_id = query.data.split("_")[-1]
    deals = load_json(DB_DEALS)
    deal = deals.get(deal_id)
    if not deal:
        return
    seller_id = deal['seller_id']
    code_type = deal.get('code_type') or deal.get('number_data', {}).get('code_type') or 'sms'
    code_label = "SMS" if code_type == 'sms' else "Аудио"
    rows_seller = [[btn(f"{E.CODE} Отправить код", f"seller_send_code_{deal_id}")]]
    try:
        await context.bot.send_message(
            seller_id,
            f"{E.CODE} Покупатель запросил {code_label}-код!\nСделка: {deal_id}",
            reply_markup=kb(rows_seller), parse_mode="HTML"
        )
        await query.edit_message_text(f"{E.PENDING} Запрос кода отправлен продавцу...", parse_mode="HTML")
    except Exception as e:
        logger.error(e)


async def seller_send_code_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    deal_id = query.data.split("_")[-1]
    deals = load_json(DB_DEALS)
    deal = deals.get(deal_id, {})
    code_type = deal.get('code_type') or deal.get('number_data', {}).get('code_type') or 'sms'
    code_label = "SMS" if code_type == 'sms' else "аудио"
    context.user_data['current_deal_id'] = deal_id
    context.user_data['state'] = 'waiting_seller_code_input'
    await query.message.reply_text(f"{E.CODE} Введите код из {code_label}:",
                                   reply_markup=kb([[btn(f"{E.CANCEL} Отмена", f"deal_status_menu_{deal_id}")]]))


async def deal_confirm_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Покупатель говорит 'код подошёл' — запрос двойного подтверждения."""
    query = update.callback_query
    await query.answer()
    deal_id = query.data.split("_")[-1]
    text = (
        f"{E.WARNING} <b>Подтверждение кода</b>\n\n"
        f"Код действительно подошёл?\n"
        f"После подтверждения деньги перейдут продавцу."
    )
    rows = [
        [btn(f"{E.SUCCESS} Да, подтвердить", f"deal_confirm_final_YES_{deal_id}"),
         btn(f"{E.CANCEL} Нет", f"deal_confirm_final_NO_{deal_id}")],
    ]
    await edit_message(update, context, text, rows, ORDER_PHOTO)


async def deal_confirm_code_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    answer = parts[3]
    deal_id = parts[4]

    if answer == 'NO':
        await deal_status_menu(update, context)
        return

    deals = load_json(DB_DEALS)
    deal = deals.get(deal_id)
    if not deal or deal.get('status') not in ['active', 'waiting_code_review']:
        return

    price = deal['number_data']['price']
    currency = deal['number_data']['currency']
    seller_id = deal['seller_id']

    # Завершение сделки
    fee_amount = round(price * 0.0, 2)  # Комиссия уже учтена при создании чека
    seller_u = get_user(seller_id)
    if currency == 'USD':
        seller_u['balance_usd'] = round(seller_u.get('balance_usd', 0.0) + price, 2)
    else:
        seller_u['balance_kzt'] = round(seller_u.get('balance_kzt', 0.0) + price, 0)
    save_user(seller_id, seller_u)

    # Обновляем номер
    nums = load_json(DB_NUMBERS)
    for n in nums:
        if n['id'] == deal['number_id']:
            n['status'] = 'sold'
            break
    save_json(DB_NUMBERS, nums)

    deal['status'] = 'completed'
    deal['completed_at'] = time.time()
    deals[deal_id] = deal
    save_json(DB_DEALS, deals)

    for uid in [deal['buyer_id'], seller_id]:
        u = get_user(uid)
        u['last_deal_end_time'] = time.time()
        save_user(uid, u)

    seller_notify = f"{E.SUCCESS} Сделка {deal_id} завершена! +{format_price(price, currency)} на ваш баланс."
    try:
        await context.bot.send_message(seller_id, seller_notify, parse_mode="HTML")
    except Exception:
        pass

    await edit_message(update, context,
                       f"{E.SUCCESS} <b>Сделка завершена!</b>\nСпасибо за использование сервиса.",
                       [[btn(f"{E.MENU} Главное меню", "start")]], ORDER_PHOTO)


# ============================================================
# ФИНАЛЬНОЕ ПОДТВЕРЖДЕНИЕ ПРОДАВЦА
# ============================================================

async def deal_final_confirm_seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    deal_id = query.data.split("_")[-1]
    deals = load_json(DB_DEALS)
    deal = deals.get(deal_id)
    if not deal:
        return
    # Заглушка — логика идёт через deal_confirm_code_final
    await deal_status_menu(update, context)


async def deal_reject_reason_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    deal_id = query.data.split("_")[-1]
    context.user_data['reject_deal_id'] = deal_id
    context.user_data['state'] = 'waiting_reject_reason'
    await edit_message(update, context, "Укажите причину отклонения:",
                       [[btn(f"{E.CANCEL} Отмена", f"deal_status_menu_{deal_id}")]], "menu.jpg")


# ============================================================
# ОТМЕНА
# ============================================================

async def deal_cancel_buyer_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    deal_id = query.data.split("_")[-1]
    await cancel_deal_logic(update, context, deal_id, "Покупатель отменил сделку", "buyer")
    await edit_message(update, context, f"{E.CANCEL} Сделка отменена. Средства возвращены.",
                       [[btn(f"{E.MENU} Главное меню", "start")]], "menu.jpg")


async def deal_cancel_seller_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    deal_id = query.data.split("_")[-1]
    context.user_data['current_deal_id'] = deal_id
    context.user_data['state'] = 'waiting_seller_cancel_reason'
    await edit_message(update, context, "Укажите причину отмены:",
                       [[btn(f"{E.CANCEL} Отмена", f"deal_status_menu_{deal_id}")]], "menu.jpg")


async def deal_cancel_init_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await deal_cancel_buyer_init(update, context)


# ============================================================
# ЧАТ В СДЕЛКЕ
# ============================================================

async def chat_write_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    deal_id = query.data.split("_")[-1]
    context.user_data['chat_deal_id'] = deal_id
    context.user_data['state'] = 'waiting_chat_message'
    await edit_message(update, context, "✍️ Введите сообщение:",
                       [[btn(f"{E.CANCEL} Отмена", f"deal_status_menu_{deal_id}")]], "menu.jpg")


async def handle_chat_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != 'waiting_chat_message':
        return
    uid = update.effective_user.id
    deal_id = context.user_data.get('chat_deal_id')
    deals = load_json(DB_DEALS)
    deal = deals.get(deal_id)
    if not deal:
        return
    context.user_data['state'] = None
    is_buyer = uid == deal['buyer_id']
    target = deal['seller_id'] if is_buyer else deal['buyer_id']
    prefix = "💬 Покупатель" if is_buyer else "💬 Продавец"
    try:
        await context.bot.send_message(target, f"{prefix}: {update.message.text}", parse_mode="HTML")
        await update.message.reply_text(f"{E.SUCCESS} Сообщение отправлено.")
    except Exception as e:
        logger.error(e)


# ============================================================
# БАН НОМЕРА (сообщение от покупателя)
# ============================================================

async def deal_banned_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    deal_id = query.data.split("_")[-1]
    context.user_data['ban_deal_id'] = deal_id
    context.user_data['state'] = 'waiting_ban_platform'
    await edit_message(update, context, "⛔ Введите название платформы, где заблокировали номер:",
                       [[btn(f"{E.CANCEL} Отмена", f"deal_status_menu_{deal_id}")]], "menu.jpg")


# ============================================================
# АРБИТРАЖ
# ============================================================

async def arbitration_menu_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    deals = load_json(DB_DEALS)
    my = [
        (did, d) for did, d in deals.items()
        if (str(d.get('buyer_id')) == str(uid)) and d.get('status') == 'completed'
    ]
    if not my:
        await edit_message(update, context, f"{E.ARBITRATION} Нет сделок для арбитража.",
                           [[btn(f"{E.MENU} Главное меню", "start")]], "arbitration.jpg")
        return
    now = time.time()
    available = [
        (did, d) for did, d in my
        if (now - d.get('completed_at', 0)) < SECURITY_LOCK_MINUTES * 60
    ]
    text = f"{E.ARBITRATION} <b>Арбитраж</b>\n\nДоступно для жалобы: {len(available)} сделок\n(в течение {SECURITY_LOCK_MINUTES} мин после завершения)"
    rows = [[btn(f"{format_number(d.get('number_data', {}).get('number', '?'))} · {format_price(d.get('number_data', {}).get('price', 0), d.get('number_data', {}).get('currency', 'USD'))}", f"arb_select_deal_{did}")] for did, d in available[:5]]
    rows.append([btn(f"{E.MENU} Главное меню", "start")])
    await edit_message(update, context, text, rows, "arbitration.jpg")


async def arb_select_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    deal_id = query.data.split("_")[-1]
    deals = load_json(DB_DEALS)
    deal = deals.get(deal_id)
    if not deal or deal.get('status') != 'completed':
        await query.answer("Сделка недоступна.", show_alert=True)
        return
    now = time.time()
    if (now - deal.get('completed_at', 0)) >= SECURITY_LOCK_MINUTES * 60:
        await query.answer("Время арбитража истекло.", show_alert=True)
        return
    context.user_data['arb_deal_id'] = deal_id
    context.user_data['state'] = 'waiting_arb_reason'
    await edit_message(update, context,
                       f"{E.ARBITRATION} Опишите проблему подробно:",
                       [[btn(f"{E.CANCEL} Отмена", "start")]], "arbitration.jpg")


async def arb_receive_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != 'waiting_arb_reason':
        return
    context.user_data['arb_reason'] = update.message.text.strip()
    context.user_data['state'] = 'waiting_arb_screenshot'
    await update.message.reply_text("📸 Отправьте скриншот, подтверждающий проблему:")


async def arb_receive_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != 'waiting_arb_screenshot':
        return
    if not update.message.photo:
        await update.message.reply_text(f"{E.ERROR} Отправьте фото (скриншот).")
        return
    uid = update.effective_user.id
    deal_id = context.user_data.get('arb_deal_id')
    reason = context.user_data.get('arb_reason', '')
    photo_id = update.message.photo[-1].file_id
    deals = load_json(DB_DEALS)
    deal = deals.get(deal_id)
    if not deal:
        return

    seller_id = deal['seller_id']
    seller_data = get_user(seller_id)
    buyer_data = get_user(uid)
    total_dep = seller_data.get('deposit_usd', 0.0) + seller_data.get('deposit_kzt', 0.0) / get_rate()
    arb_id = generate_id("ARB")

    arbitrations = load_json(DB_ARBITRATIONS)
    arbitrations.append({
        "id": arb_id, "deal_id": deal_id, "buyer_id": uid, "seller_id": seller_id,
        "reason": reason, "photo_id": photo_id, "status": "pending",
        "date": datetime.datetime.now().isoformat(),
        "deal_price": deal.get('number_data', {}).get('price', 0),
        "deal_currency": deal.get('number_data', {}).get('currency', 'USD'),
    })
    save_json(DB_ARBITRATIONS, arbitrations)

    from config import ADMIN_ID
    b_uname = f"@{buyer_data.get('username', uid)}"
    s_uname = f"@{seller_data.get('username', seller_id)}"
    admin_text = (
        f"{E.ARBITRATION} <b>АРБИТРАЖ #{arb_id}</b>\n\n"
        f"Сделка: {deal_id}\n"
        f"Покупатель: {b_uname}\n"
        f"Продавец: {s_uname} (депозит: ${total_dep:.2f})\n\n"
        f"Причина: {reason}"
    )
    rows_admin = [
        [btn(f"{E.SUCCESS} Принять (вернуть покупателю)", f"admin_arb_approve_{arb_id}"),
         btn(f"{E.CANCEL} Отклонить", f"admin_arb_reject_{arb_id}")],
    ]
    try:
        await context.bot.send_photo(ADMIN_ID, photo=photo_id, caption=admin_text,
                                     reply_markup=kb(rows_admin), parse_mode="HTML")
        await update.message.reply_text(f"{E.SUCCESS} Жалоба отправлена! Ожидайте решения.")
    except Exception as e:
        logger.error(e)
    context.user_data['state'] = None


async def admin_arb_process(update: Update, context: ContextTypes.DEFAULT_TYPE, approve: bool):
    query = update.callback_query
    await query.answer()
    arb_id = query.data.split("_")[-1]
    arbitrations = load_json(DB_ARBITRATIONS)
    arb = next((a for a in arbitrations if a['id'] == arb_id), None)
    if not arb:
        return
    seller_id = arb['seller_id']
    buyer_id = arb['buyer_id']
    deal_price = arb['deal_price']
    deal_currency = arb['deal_currency']

    if approve:
        users = load_json(DB_USERS)
        s_str = str(seller_id)
        b_str = str(buyer_id)
        s = users.get(s_str, {})
        b = users.get(b_str, {})
        dep_usd = s.get('deposit_usd', 0.0)
        dep_kzt = s.get('deposit_kzt', 0.0)
        rate = get_rate()

        if deal_currency == 'USD':
            if dep_usd >= deal_price:
                s['deposit_usd'] = round(dep_usd - deal_price, 2)
            else:
                remaining = deal_price - dep_usd
                s['deposit_usd'] = 0.0
                s['deposit_kzt'] = round(dep_kzt - remaining * rate, 0)
            b['balance_usd'] = round(b.get('balance_usd', 0.0) + deal_price, 2)
        else:
            if dep_kzt >= deal_price:
                s['deposit_kzt'] = round(dep_kzt - deal_price, 0)
            else:
                remaining = deal_price - dep_kzt
                s['deposit_kzt'] = 0.0
                s['deposit_usd'] = round(dep_usd - remaining / rate, 2)
            b['balance_kzt'] = round(b.get('balance_kzt', 0.0) + deal_price, 0)

        save_json(DB_USERS, users)
        new_dep = s.get('deposit_usd', 0.0) + s.get('deposit_kzt', 0.0) / rate
        if new_dep <= 0:
            from handlers.notifications import broadcast_guarantee_lost
            await broadcast_guarantee_lost(context, seller_id, deal_price if deal_currency == 'USD' else deal_price / rate, arb['reason'])

        try:
            await context.bot.send_message(seller_id, f"🚫 Арбитраж принят. Списано: {format_price(deal_price, deal_currency)}", parse_mode="HTML")
            await context.bot.send_message(buyer_id, f"{E.SUCCESS} Арбитраж принят. Вам компенсировано {format_price(deal_price, deal_currency)}", parse_mode="HTML")
        except Exception:
            pass
    else:
        try:
            await context.bot.send_message(buyer_id, f"{E.CANCEL} Арбитраж отклонён. Обратитесь в поддержку @{SUPPORT_USERNAME}", parse_mode="HTML")
        except Exception:
            pass

    idx = arbitrations.index(arb)
    arb['status'] = 'approved' if approve else 'rejected'
    arbitrations[idx] = arb
    save_json(DB_ARBITRATIONS, arbitrations)
    await edit_message(update, context, "✅ Обработано.",
                       [[btn(f"{E.MENU} Главное меню", "start")]], "menu.jpg")


# ============================================================
# ТАЙМЕР СДЕЛОК
# ============================================================

async def check_deal_timeouts(context):
    """Фоновая задача: отменяет зависшие сделки."""
    deals = load_json(DB_DEALS)
    now = time.time()
    changed = False
    TIMEOUT = 3600 * 24  # 24 часа

    for deal_id, deal in deals.items():
        if deal.get('status') not in ['active', 'pending_confirm', 'waiting_code_review']:
            continue
        last = deal.get('last_action', 0) or deal.get('created_at', '')
        if isinstance(last, str):
            try:
                last = datetime.datetime.fromisoformat(last).timestamp()
            except Exception:
                continue
        if (now - last) > TIMEOUT:
            buyer_id = deal['buyer_id']
            seller_id = deal['seller_id']
            if deal.get('frozen_amount') and deal.get('status') == 'active':
                price = deal['frozen_amount']
                currency = deal.get('number_data', {}).get('currency', 'USD')
                buyer_u = get_user(buyer_id)
                buyer_u = refund_payment(buyer_u, price, currency)
                save_user(buyer_id, buyer_u)
            nums = load_json(DB_NUMBERS)
            for n in nums:
                if n['id'] == deal.get('number_id'):
                    n['status'] = 'active'
                    break
            save_json(DB_NUMBERS, nums)
            deal['status'] = 'cancelled'
            deal['cancel_reason'] = 'Таймаут (24ч)'
            changed = True
            for uid in [buyer_id, seller_id]:
                try:
                    await context.bot.send_message(uid, f"{E.WARNING} Сделка {deal_id} автоматически отменена (таймаут).", parse_mode="HTML")
                except Exception:
                    pass

    if changed:
        save_json(DB_DEALS, deals)
