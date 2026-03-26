"""
handlers/profile.py — Профиль, баланс, пополнение, вывод, рефералы, промокоды.
"""
import datetime
import logging
import os
import time
from telegram import Update
from telegram.ext import ContextTypes

from config import E, MARKET_FEE_PERCENT, CRYPTO_PAY_LINK, SUPPORT_USERNAME
from config import REF_BONUS_AMOUNT, REF_REQUIRED_COUNT, REF_MAX_BONUS_TIMES
from data.storage import (
    get_user, save_user, is_admin, load_json, save_json,
    DB_CHECKS, DB_WITHDRAW_REQUESTS, DB_USERS, DB_ADMIN_SETTINGS, DB_PROMOCODES
)
from utils.finance import (
    get_unified_balance, get_unified_balance_kzt, can_afford_price,
    deduct_payment, format_price, get_rate
)
from utils.helpers import btn, kb, edit_message, send_photo_message, generate_id

logger = logging.getLogger(__name__)


# ============================================================
# ПРОФИЛЬ
# ============================================================

async def profile_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    bal_usd = user.get('balance_usd', 0.0)
    bal_kzt = user.get('balance_kzt', 0.0)
    dep_usd = user.get('deposit_usd', 0.0)
    dep_kzt = user.get('deposit_kzt', 0.0)
    uname = user.get('username', '—')
    reg_date = user.get('created_at', '')[:10] if user.get('created_at') else '—'
    ref_count = user.get('ref_count', 0)
    warnings = load_json("warnings.txt")
    warns = warnings.get(str(uid), {}).get('count', 0)

    text = (
        f"{E.PROFILE} <b>Профиль</b>\n\n"
        f"👤 @{uname} | ID: <code>{uid}</code>\n"
        f"📅 Регистрация: {reg_date}\n\n"
        f"{E.BALANCE} Баланс USD: <b>${bal_usd:.2f}</b>\n"
        f"{E.BALANCE} Баланс KZT: <b>{bal_kzt:,.0f} ₸</b>\n"
        f"{E.DEPOSIT} Депозит: <b>${dep_usd:.2f}</b> / <b>{dep_kzt:,.0f} ₸</b>\n\n"
        f"{E.REF} Рефералов: <b>{ref_count}</b>\n"
        f"⚠️ Предупреждений: <b>{warns}</b>"
    )
    rows = [
        [btn(f"{E.REF} Реферальная программа", "menu_referral")],
        [btn(f"{E.MENU} Главное меню", "start")],
    ]
    await edit_message(update, context, text, rows, "profile.jpg")


# ============================================================
# БАЛАНС
# ============================================================

async def balance_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    bal_usd = user.get('balance_usd', 0.0)
    bal_kzt = user.get('balance_kzt', 0.0)
    total_usd = get_unified_balance(user)

    text = (
        f"{E.BALANCE} <b>Баланс</b>\n\n"
        f"💵 USD: <b>${bal_usd:.2f}</b>\n"
        f"🇰🇿 KZT: <b>{bal_kzt:,.0f} ₸</b>\n"
        f"📊 Итого: <b>${total_usd:.2f}</b>"
    )
    rows = [
        [btn(f"{E.MONEY} Пополнить", "topup_crypto"),
         btn(f"{E.WITHDRAW} Вывести", "withdraw_init")],
        [btn("🎟 Промокод", "menu_promo")],
        [btn(f"{E.MENU} Главное меню", "start")],
    ]
    await edit_message(update, context, text, rows, "balance.jpg")


# ============================================================
# ПОПОЛНЕНИЕ
# ============================================================

async def topup_crypto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['state'] = 'waiting_amount'
    context.user_data['check_method'] = 'crypto'
    await edit_message(update, context,
                       f"{E.MONEY} Введите сумму пополнения (USD):\nМинимум: $1.00",
                       [[btn(f"{E.CANCEL} Отмена", "menu_balance")]], "depozit.jpg")


async def process_crypto_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get('state') != 'waiting_amount':
        return False
    text = update.message.text.strip()
    try:
        amount = float(text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Введите число больше 0.")
        return True

    fee = round(amount * MARKET_FEE_PERCENT, 2)
    total = round(amount + fee, 2)
    context.user_data.update({
        'check_amount': amount,
        'check_fee': fee,
        'check_total': total,
        'check_method': 'crypto',
        'state': 'waiting_payment_proof',
    })
    user = get_user(update.effective_user.id)
    msg = (
        f"💳 <b>Счёт на пополнение</b>\n\n"
        f"Зачислится: <b>${amount:.2f}</b>\n"
        f"Комиссия ({int(MARKET_FEE_PERCENT*100)}%): <b>${fee:.2f}</b>\n"
        f"К оплате: <b>${total:.2f}</b>\n\n"
        f"Оплатите через @CryptoBot и пришлите скриншот."
    )
    rows = [[btn("💳 Оплатить", url=CRYPTO_PAY_LINK)]]
    await update.message.reply_text(msg, reply_markup=kb(rows), parse_mode="HTML")
    await update.message.reply_text("📸 После оплаты пришлите скриншот следующим сообщением...")
    return True


# ============================================================
# ВЫВОД
# ============================================================

async def withdraw_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['state'] = 'waiting_withdraw_amount'
    await edit_message(update, context,
                       f"{E.WITHDRAW} Введите сумму вывода (USD):\nМинимум $1.00",
                       [[btn(f"{E.CANCEL} Отмена", "menu_balance")]], "balance.jpg")


async def withdraw_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != 'waiting_withdraw_amount':
        return
    text = update.message.text.strip()
    try:
        amount = float(text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Введите корректную сумму.")
        return

    uid = update.effective_user.id
    user = get_user(uid)
    fee = round(amount * MARKET_FEE_PERCENT, 2)
    total_needed = round(amount + fee, 2)
    amount_net = amount

    if not can_afford_price(user, total_needed, 'USD'):
        await update.message.reply_text(
            f"{E.ERROR} Недостаточно средств.\nНужно: ${total_needed:.2f} (с комиссией {int(MARKET_FEE_PERCENT*100)}%)\n"
            f"Ваш баланс: ${get_unified_balance(user):.2f}"
        )
        context.user_data['state'] = None
        return

    context.user_data.update({
        'withdraw_amount_net': amount_net,
        'withdraw_amount_fee': fee,
        'withdraw_amount_total': total_needed,
        'state': 'waiting_withdraw_link',
    })
    await update.message.reply_text(
        f"{E.WITHDRAW} Сумма: ${amount_net:.2f}\nКомиссия: ${fee:.2f}\nСписание: ${total_needed:.2f}\n\n"
        f"Введите ваш кошелёк USDT (TRC-20):",
        reply_markup=kb([[btn(f"{E.CANCEL} Отмена", "menu_balance")]]),
        parse_mode="HTML"
    )


async def withdraw_link_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != 'waiting_withdraw_link':
        return
    uid = update.effective_user.id
    wallet = update.message.text.strip()
    amount_net = context.user_data.get('withdraw_amount_net')
    amount_fee = context.user_data.get('withdraw_amount_fee')
    amount_total = context.user_data.get('withdraw_amount_total')

    user = get_user(uid)
    wid = generate_id("WDR")
    ws = load_json(DB_WITHDRAW_REQUESTS)
    ws.append({
        "id": wid,
        "user_id": uid,
        "username": user.get('username', '—'),
        "amount_net": amount_net,
        "amount_fee": amount_fee,
        "amount_total": amount_total,
        "wallet": wallet,
        "status": "pending",
        "date": datetime.datetime.now().isoformat(),
    })
    save_json(DB_WITHDRAW_REQUESTS, ws)

    from config import ADMIN_ID
    admin_text = (
        f"{E.WITHDRAW} <b>ЗАЯВКА НА ВЫВОД</b>\n\n"
        f"ID: <code>{wid}</code>\n"
        f"👤 @{user.get('username', uid)}\n"
        f"💰 К выдаче: ${amount_net:.2f} | Комиссия: ${amount_fee:.2f}\n"
        f"Кошелёк: <code>{wallet}</code>"
    )
    rows_admin = [
        [btn(f"{E.SUCCESS} Подтвердить", f"admin_withdraw_approve_{wid}"),
         btn(f"{E.CANCEL} Отклонить", f"admin_withdraw_reject_{wid}")],
    ]
    try:
        await context.bot.send_message(ADMIN_ID, admin_text, reply_markup=kb(rows_admin), parse_mode="HTML")
    except Exception:
        pass

    context.user_data['state'] = None
    await update.message.reply_text(
        f"{E.SUCCESS} Заявка на вывод отправлена!\nОжидайте подтверждения администратора.",
        parse_mode="HTML"
    )


# ============================================================
# ДЕПОЗИТ
# ============================================================

async def deposit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    dep_usd = user.get('deposit_usd', 0.0)
    dep_kzt = user.get('deposit_kzt', 0.0)
    text = (
        f"{E.DEPOSIT} <b>Депозит</b>\n\n"
        f"USD: <b>${dep_usd:.2f}</b>\n"
        f"KZT: <b>{dep_kzt:,.0f} ₸</b>\n\n"
        f"Депозит — это гарантия для ваших покупателей."
    )
    rows = [
        [btn("📥 Пополнить (Crypto)", "dep_in_crypto")],
        [btn("📥 Пополнить USD", "dep_in_usd"),
         btn("📥 Пополнить KZT", "dep_in_kzt")],
        [btn("📤 Вывести USD", "dep_out_usd"),
         btn("📤 Вывести KZT", "dep_out_kzt")],
        [btn(f"{E.MENU} Главное меню", "start")],
    ]
    await edit_message(update, context, text, rows, "depozit.jpg")


async def deposit_crypto_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['state'] = 'waiting_deposit_crypto_amount'
    await edit_message(update, context,
                       f"{E.DEPOSIT} Введите сумму пополнения депозита (USD):\nМинимум: $10.00",
                       [[btn(f"{E.CANCEL} Отмена", "menu_deposit")]], "depozit.jpg")


async def deposit_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    action = parts[1]  # in / out
    currency = parts[2].upper()  # USD / KZT
    context.user_data['dep_action'] = {'action': action, 'currency': currency}
    context.user_data['state'] = 'waiting_deposit_amount'
    action_text = "пополнения" if action == 'in' else "вывода"
    min_hint = ""
    if action == 'in':
        if currency == 'USD':
            min_hint = "\nМинимум: $10.00"
        else:
            min_kzt = round(10.0 * get_rate(), 0)
            min_hint = f"\nМинимум: {min_kzt:,.0f} ₸"
    await edit_message(update, context,
                       f"{E.DEPOSIT} Введите сумму {action_text} ({currency}):{min_hint}",
                       [[btn(f"{E.CANCEL} Отмена", "menu_deposit")]], "depozit.jpg")


async def process_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    state = context.user_data.get('state')
    action_data = context.user_data.get('dep_action')

    if state == 'waiting_deposit_crypto_amount':
        try:
            amount = float(text.replace(",", "."))
            if amount < 10.0:
                await update.message.reply_text(f"{E.ERROR} Минимальная сумма пополнения депозита $10.00.")
                return
        except ValueError:
            await update.message.reply_text(f"{E.ERROR} Введите число.")
            return
        fee = round(amount * MARKET_FEE_PERCENT, 2)
        total = round(amount + fee, 2)
        context.user_data.update({
            'check_amount': amount, 'check_fee': fee, 'check_total': total,
            'check_method': 'crypto_deposit', 'state': 'waiting_payment_proof',
        })
        crypto_link = "http://t.me/send?start=IV2fCB3pt8Lq"
        msg = (
            f"💳 <b>Счёт на пополнение депозита</b>\n\n"
            f"Зачислится: <b>${amount:.2f}</b>\n"
            f"Комиссия: <b>${fee:.2f}</b>\n"
            f"К оплате: <b>${total:.2f}</b>"
        )
        await update.message.reply_text(msg, reply_markup=kb([[btn("💳 Оплатить", url=crypto_link)]]), parse_mode="HTML")
        await update.message.reply_text("📸 Пришлите скриншот после оплаты...")
        return

    if state == 'waiting_deposit_amount' and action_data:
        try:
            amount = float(text.replace(",", "."))
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(f"{E.ERROR} Введите корректную сумму.")
            return
        action = action_data.get('action')
        currency = action_data.get('currency', 'USD')
        if action == 'in':
            if currency == 'USD' and amount < 10.0:
                await update.message.reply_text(f"{E.ERROR} Минимальная сумма пополнения депозита $10.00.")
                return
            if currency == 'KZT':
                min_kzt = round(10.0 * get_rate(), 0)
                if amount < min_kzt:
                    await update.message.reply_text(f"{E.ERROR} Минимальная сумма пополнения депозита {min_kzt:,.0f} ₸.")
                    return
        user = get_user(uid)
        if action == 'out':
            dep_key = f"deposit_{currency.lower()}"
            current = user.get(dep_key, 0.0)
            if current < amount:
                await update.message.reply_text(f"{E.ERROR} Недостаточно средств в депозите. Доступно: {current} {currency}")
                return
            context.user_data.update({
                'deposit_withdraw_amount': amount,
                'deposit_withdraw_currency': currency,
                'state': 'waiting_deposit_withdraw_reason',
            })
            await update.message.reply_text("Укажите причину вывода из депозита:")
        else:
            # Пополнение через карту/касса
            context.user_data.update({
                'check_amount': amount, 'check_fee': 0,
                'check_total': amount, 'check_method': 'deposit_card',
                'state': 'waiting_payment_proof',
            })
            await update.message.reply_text("📸 Пришлите скриншот оплаты...")
        return


async def deposit_withdraw_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != 'waiting_deposit_withdraw_amount':
        return
    text = update.message.text.strip()
    try:
        amount = float(text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Введите корректную сумму.")
        return
    context.user_data['deposit_withdraw_amount'] = amount
    context.user_data['state'] = 'waiting_deposit_withdraw_reason'
    await update.message.reply_text("Укажите причину:")


async def deposit_withdraw_reason_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != 'waiting_deposit_withdraw_reason':
        return
    uid = update.effective_user.id
    reason = update.message.text.strip()
    amount = context.user_data.get('deposit_withdraw_amount')
    currency = context.user_data.get('deposit_withdraw_currency', 'USD')
    user = get_user(uid)
    wid = generate_id("DWD")
    from data.storage import DB_DEPOSIT_WITHDRAW_REQUESTS
    reqs = load_json(DB_DEPOSIT_WITHDRAW_REQUESTS)
    reqs.append({
        "id": wid, "user_id": uid, "username": user.get('username', '—'),
        "amount": amount, "currency": currency, "reason": reason,
        "status": "pending", "date": datetime.datetime.now().isoformat()
    })
    save_json(DB_DEPOSIT_WITHDRAW_REQUESTS, reqs)
    from config import ADMIN_ID
    admin_text = (
        f"💸 <b>ЗАЯВКА НА ВЫВОД ИЗ ДЕПОЗИТА</b>\n\n"
        f"ID: <code>{wid}</code>\n"
        f"👤 @{user.get('username', uid)}\n"
        f"💰 {amount:,.2f} {currency}\n"
        f"Причина: {reason}"
    )
    rows_admin = [
        [btn(f"{E.SUCCESS} Подтвердить", f"admin_deposit_withdraw_approve_{wid}"),
         btn(f"{E.CANCEL} Отклонить", f"admin_deposit_withdraw_reject_{wid}")],
    ]
    try:
        await context.bot.send_message(ADMIN_ID, admin_text, reply_markup=kb(rows_admin), parse_mode="HTML")
    except Exception:
        pass
    context.user_data['state'] = None
    await update.message.reply_text(f"{E.SUCCESS} Заявка отправлена!")


# ============================================================
# ОБРАБОТКА СКРИНШОТА ОПЛАТЫ
# ============================================================

async def handle_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = context.user_data.get('state')

    # Скриншот оплаты
    if state == 'waiting_payment_proof':
        if not update.message.photo:
            await update.message.reply_text(f"{E.ERROR} Отправьте фото (скриншот).")
            return

        photo_file_id = update.message.photo[-1].file_id
        amount = context.user_data.get('check_amount', 0)
        fee = context.user_data.get('check_fee', 0)
        total = context.user_data.get('check_total', 0)
        method = context.user_data.get('check_method', 'crypto')
        is_deposit = 'deposit' in method
        cid = generate_id("CHK")
        user = get_user(uid)

        checks = load_json(DB_CHECKS)
        checks.append({
            "id": cid, "user_id": uid,
            "username": user.get('username', '—'),
            "amount_net": amount, "amount_fee": fee, "amount_total": total,
            "photo_file_id": photo_file_id,
            "type": "deposit" if is_deposit else "balance",
            "status": "pending",
            "date": datetime.datetime.now().isoformat(),
        })
        save_json(DB_CHECKS, checks)

        from config import ADMIN_ID
        admin_text = (
            f"📋 <b>НОВЫЙ ЧЕК</b>\n\n"
            f"ID: <code>{cid}</code>\n"
            f"👤 @{user.get('username', uid)} ({uid})\n"
            f"💰 Зачислить: ${amount:.2f}\n"
            f"Комиссия: ${fee:.2f} | Оплачено: ${total:.2f}\n"
            f"Тип: {'Депозит' if is_deposit else 'Баланс'}"
        )
        rows_admin = [
            [btn(f"{E.SUCCESS} Подтвердить", f"admin_check_approve_{cid}"),
             btn(f"{E.CANCEL} Отклонить", f"admin_check_reject_{cid}")],
        ]
        try:
            await context.bot.send_photo(
                ADMIN_ID, photo=photo_file_id,
                caption=admin_text, reply_markup=kb(rows_admin), parse_mode="HTML"
            )
        except Exception as e:
            logger.error(e)

        context.user_data['state'] = None
        await update.message.reply_text(
            f"{E.SUCCESS} Чек отправлен на проверку!\nОжидайте подтверждения администратора."
        )
        return

    # Скриншот для арбитража
    if state == 'waiting_arb_screenshot':
        from handlers.deals import arb_receive_screenshot
        await arb_receive_screenshot(update, context)
        return

    # Рассылка для админа
    if context.user_data.get('admin_state') == 'waiting_broadcast':
        if is_admin(uid):
            from handlers.moderation import handle_admin_broadcast_input
            await handle_admin_broadcast_input(update, context)


# ============================================================
# ПРОМОКОДЫ
# ============================================================

async def promo_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['state'] = 'waiting_promo_input'
    await edit_message(update, context,
                       "🎟 Введите промокод:",
                       [[btn(f"{E.CANCEL} Отмена", "start")]], "menu.jpg")


async def handle_promo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != 'waiting_promo_input':
        return
    uid = update.effective_user.id
    code = update.message.text.strip().upper()
    promos = load_json(DB_PROMOCODES)
    promo = promos.get(code)
    context.user_data['state'] = None

    if not promo:
        await update.message.reply_text(f"{E.ERROR} Промокод не найден.")
        return
    if promo.get('used'):
        await update.message.reply_text(f"{E.ERROR} Промокод уже использован.")
        return

    user = get_user(uid)
    amount = promo.get('amount', 0)
    user['balance_usd'] = round(user.get('balance_usd', 0.0) + amount, 2)
    save_user(uid, user)
    promo['used'] = True
    promo['used_by'] = uid
    promos[code] = promo
    save_json(DB_PROMOCODES, promos)
    await update.message.reply_text(f"{E.SUCCESS} Промокод активирован! +${amount:.2f} на баланс.")


# ============================================================
# РЕФЕРАЛЫ
# ============================================================

async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    ref_count = user.get('ref_count', 0)
    bonus_times = user.get('ref_bonus_times', 0)
    can_claim = (ref_count >= REF_REQUIRED_COUNT * (bonus_times + 1)) and (
            bonus_times < REF_MAX_BONUS_TIMES or REF_MAX_BONUS_TIMES == 999)

    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{uid}"

    text = (
        f"{E.REF} <b>Реферальная программа</b>\n\n"
        f"Ваша ссылка:\n<code>{ref_link}</code>\n\n"
        f"Приглашено: <b>{ref_count}</b>\n"
        f"Нужно: <b>{REF_REQUIRED_COUNT}</b> для бонуса ${REF_BONUS_AMOUNT}\n"
        f"Получено бонусов: {bonus_times} / {'∞' if REF_MAX_BONUS_TIMES == 999 else REF_MAX_BONUS_TIMES}"
    )
    rows = []
    if can_claim:
        rows.append([btn(f"{E.SUCCESS} Получить бонус ${REF_BONUS_AMOUNT}", "claim_ref_bonus")])
    rows.append([btn(f"{E.MENU} Главное меню", "start")])
    await edit_message(update, context, text, rows, "profile.jpg")


async def claim_ref_bonus_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    ref_count = user.get('ref_count', 0)
    bonus_times = user.get('ref_bonus_times', 0)
    required = REF_REQUIRED_COUNT * (bonus_times + 1)
    if ref_count < required or (bonus_times >= REF_MAX_BONUS_TIMES and REF_MAX_BONUS_TIMES != 999):
        await query.answer(f"Нужно ещё рефералов!", show_alert=True)
        return
    user['balance_usd'] = round(user.get('balance_usd', 0.0) + REF_BONUS_AMOUNT, 2)
    user['ref_bonus_times'] = bonus_times + 1
    save_user(uid, user)
    await edit_message(update, context,
                       f"{E.SUCCESS} Бонус ${REF_BONUS_AMOUNT} зачислен на баланс!",
                       [[btn(f"{E.MENU} Главное меню", "start")]], "menu.jpg")
