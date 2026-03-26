"""
handlers/text_input.py — Обработка всех входящих текстов и фото.
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes

from data.storage import (
    load_json, save_json, get_user, save_user, is_admin,
    DB_DEALS, DB_CHECKS, DB_ADMIN_SETTINGS
)
from utils.helpers import generate_id, format_number
from utils.finance import get_rate
from config import E, ADMIN_ID, CRYPTO_PAY_LINK

logger = logging.getLogger(__name__)


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    state = context.user_data.get('state')

    # === Заказы по запросу ===
    if state == 'waiting_cust_num_input' and context.user_data.get('cust_op_action') == 'send_num':
        from handlers.custom_orders import cust_op_send_num_process
        await cust_op_send_num_process(update, context)
        return
    if state == 'waiting_cust_reject_reason':
        from handlers.custom_orders import cust_op_reject_reason_process
        await cust_op_reject_reason_process(update, context)
        return
    if state == 'waiting_cust_code_input' and context.user_data.get('cust_op_action') == 'send_code':
        from handlers.custom_orders import cust_op_send_code_process
        await cust_op_send_code_process(update, context)
        return
    if state == 'waiting_cust_chat_msg':
        from handlers.custom_orders import handle_cust_chat_msg
        await handle_cust_chat_msg(update, context)
        return

    # === Чат в сделке ===
    if state == 'waiting_chat_message':
        from handlers.deals import handle_chat_message_input
        await handle_chat_message_input(update, context)
        return

    # === Админ: отправить конкретному пользователю ===
    if context.user_data.get('admin_state') == 'waiting_send_user':
        from handlers.admin import handle_admin_send_user_input
        await handle_admin_send_user_input(update, context)
        return

    # === Рассылка ===
    if context.user_data.get('admin_state') == 'waiting_broadcast':
        if is_admin(uid):
            from handlers.admin import handle_admin_broadcast_input
            await handle_admin_broadcast_input(update, context)
        return

    # === Промокод ===
    if state == 'waiting_promo_input':
        from handlers.profile import handle_promo_input
        await handle_promo_input(update, context)
        return

    # === Арбитраж ===
    if state == 'waiting_arb_reason':
        from handlers.deals import arb_receive_reason
        await arb_receive_reason(update, context)
        return
    if state == 'waiting_arb_screenshot':
        await update.message.reply_text("📸 Пожалуйста, отправьте фото (скриншот).")
        return

    # === Код продавца в основной сделке ===
    if state == 'waiting_seller_code_input':
        await _handle_seller_code(update, context, uid, text)
        return

    # === Отмена сделки продавцом ===
    if state == 'waiting_seller_cancel_reason':
        deal_id = context.user_data.get('current_deal_id')
        if deal_id:
            from handlers.deals import cancel_deal_logic
            await cancel_deal_logic(update, context, deal_id, text, initiator="seller")
        context.user_data['state'] = None
        return

    # === Отклонение завершения ===
    if state == 'waiting_reject_reason':
        deal_id = context.user_data.get('reject_deal_id')
        if deal_id:
            from handlers.deals import cancel_deal_logic
            deals = load_json(DB_DEALS)
            deal = deals.get(deal_id)
            if deal:
                await cancel_deal_logic(update, context, deal_id,
                                        f"Продавец отклонил: {text}", initiator="seller")
                try:
                    await context.bot.send_message(
                        deal['buyer_id'],
                        f"{E.WARNING} Продавец отклонил завершение. Причина: {text}"
                    )
                except Exception:
                    pass
        context.user_data['state'] = None
        return

    # === Бан номера ===
    if state == 'waiting_ban_platform':
        deal_id = context.user_data.get('ban_deal_id')
        if deal_id:
            from handlers.deals import cancel_deal_logic
            deals = load_json(DB_DEALS)
            deal = deals.get(deal_id)
            if deal:
                try:
                    await context.bot.send_message(
                        deal['seller_id'],
                        f"⛔ Заявлено о блокировке! Заказ: {deal_id}, платформа: {text}"
                    )
                except Exception:
                    pass
                await cancel_deal_logic(update, context, deal_id,
                                        f"Бан на {text}", initiator="buyer")
        context.user_data['state'] = None
        from handlers.menu import start_command
        await start_command(update, context)
        return

    # === Депозит/вывод ===
    if state in ('waiting_deposit_withdraw_amount', 'waiting_deposit_withdraw_reason'):
        from handlers.profile import deposit_withdraw_amount_input, deposit_withdraw_reason_input
        if state == 'waiting_deposit_withdraw_amount':
            await deposit_withdraw_amount_input(update, context)
        else:
            await deposit_withdraw_reason_input(update, context)
        return

    if state in ('waiting_deposit_amount', 'waiting_deposit_crypto_amount'):
        from handlers.profile import process_deposit_amount
        await process_deposit_amount(update, context)
        return

    if state == 'waiting_withdraw_amount':
        from handlers.profile import withdraw_amount_input
        await withdraw_amount_input(update, context)
        return
    if state == 'waiting_withdraw_link':
        from handlers.profile import withdraw_link_input
        await withdraw_link_input(update, context)
        return

    # === Продажа номера: ввод номера ===
    if context.user_data.get('sell_state') == 'waiting_number':
        clean = ''.join(c for c in text if c.isdigit())
        if not (text.startswith('+77') or text.startswith('77')):
            await update.message.reply_text("❌ Номер должен начинаться с +77 или 77")
            return
        if len(clean) != 11:
            await update.message.reply_text(f"❌ Номер должен содержать 11 цифр (сейчас: {len(clean)})")
            return
        context.user_data['temp_number'] = text
        context.user_data['sell_state'] = 'waiting_price_currency'
        await update.message.reply_text("💰 Введите цену (число, например 10 или 1.5):")
        return

    # === Продажа: ввод цены ===
    if context.user_data.get('sell_state') == 'waiting_price_currency':
        try:
            price = float(text.replace(",", "."))
            if price <= 0:
                raise ValueError
            context.user_data['temp_price'] = price
            context.user_data['sell_state'] = 'waiting_currency_select'
            from utils.helpers import btn, kb
            rows = [
                [btn("💲 USD ($)", "set_curr_usd"), btn("🇰🇿 KZT (₸)", "set_curr_kzt")],
                [btn(f"{E.MENU} Главное меню", "start")],
            ]
            await update.message.reply_text("💱 Выберите валюту:", reply_markup=kb(rows))
        except ValueError:
            await update.message.reply_text("❌ Введите корректную цену. Пример: 10 или 1.50")
        return

    # === Пополнение крипто ===
    if state == 'waiting_amount' and context.user_data.get('check_method') == 'crypto':
        from handlers.profile import process_crypto_payment
        await process_crypto_payment(update, context)
        return

    # === Настройки (курс) ===
    if state == 'admin_waiting_requisite':
        if not is_admin(uid):
            return
        mode = context.user_data.get('admin_set_mode')
        if mode == 'rate':
            try:
                rate = float(text.replace(",", "."))
                settings = load_json(DB_ADMIN_SETTINGS)
                settings['usd_kzt_rate'] = rate
                save_json(DB_ADMIN_SETTINGS, settings)
                await update.message.reply_text(f"✅ Курс обновлён: 1 USD = {rate} KZT")
            except ValueError:
                await update.message.reply_text("❌ Введите число.")
        context.user_data['state'] = None
        return

    # Ничего не совпало
    if state:
        await update.message.reply_text(
            f"{E.WARNING} Ожидаю ввод данных. Нажмите «Отмена» или используйте меню."
        )
    else:
        await update.message.reply_text("Используйте кнопки меню. /start — главное меню.")


async def _handle_seller_code(update, context, uid, text):
    """Продавец вводит код в основной сделке."""
    from utils.helpers import btn, kb
    deal_id = context.user_data.get('current_deal_id')
    if not deal_id:
        context.user_data['state'] = None
        await update.message.reply_text("❌ Ошибка сделки.")
        return
    deals = load_json(DB_DEALS)
    if deal_id not in deals:
        context.user_data['state'] = None
        await update.message.reply_text("❌ Сделка не найдена.")
        return
    deal = deals[deal_id]
    if uid != deal['seller_id']:
        await update.message.reply_text("❌ Только продавец может отправить код.")
        return

    deal['last_code'] = text
    deal['status'] = 'waiting_code_review'
    deals[deal_id] = deal
    save_json(DB_DEALS, deals)

    buyer_id = deal['buyer_id']
    from config import ORDER_PHOTO
    import os
    b_msg = f"🔑 <b>Код от продавца:</b>\n\n<code>{text}</code>\n\nПроверьте код и выберите действие:"
    rows = [
        [btn(f"{E.SUCCESS} Код подошёл", f"deal_confirm_code_{deal_id}")],
        [btn("🔄 Повтор кода", f"deal_request_code_{deal_id}")],
        [btn("⛔ Бан", f"deal_banned_{deal_id}"), btn(f"{E.CANCEL} Отмена", f"deal_cancel_buyer_{deal_id}")],
        [btn(f"{E.MENU} Главное меню", "start")],
    ]
    markup = kb(rows)
    try:
        if os.path.exists(ORDER_PHOTO):
            with open(ORDER_PHOTO, 'rb') as photo:
                await context.bot.send_photo(buyer_id, photo=photo, caption=b_msg,
                                             reply_markup=markup, parse_mode="HTML")
        else:
            await context.bot.send_message(buyer_id, b_msg, reply_markup=markup, parse_mode="HTML")
        await update.message.reply_text(f"{E.SUCCESS} Код отправлен покупателю!")
    except Exception as e:
        logger.error(f"Ошибка отправки кода: {e}")
        await update.message.reply_text("⚠️ Ошибка отправки.")
    context.user_data['state'] = None


async def handle_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    # Админ: отправка фото конкретному пользователю
    if context.user_data.get('admin_state') == 'waiting_send_user':
        if not is_admin(uid):
            context.user_data['admin_state'] = None
            return
        target_id = context.user_data.get('send_user_target_id')
        if not target_id:
            return
        file_id = update.message.photo[-1].file_id
        caption = update.message.caption or ""
        try:
            await context.bot.send_photo(target_id, photo=file_id,
                                         caption=caption, parse_mode="HTML")
            await update.message.reply_text(f"{E.SUCCESS} Фото отправлено!")
        except Exception:
            await update.message.reply_text("⚠️ Ошибка отправки.")
        context.user_data['admin_state'] = None
        return

    # Рассылка фото
    if context.user_data.get('admin_state') == 'waiting_broadcast' and is_admin(uid):
        from handlers.admin import handle_admin_broadcast_input
        await handle_admin_broadcast_input(update, context)
        return

    # Скриншот для арбитража
    if context.user_data.get('state') == 'waiting_arb_screenshot':
        from handlers.deals import arb_receive_screenshot
        await arb_receive_screenshot(update, context)
        return

    # Чек оплаты (скриншот)
    if context.user_data.get('state') == 'waiting_payment_proof':
        await _handle_payment_proof(update, context, uid)
        return


async def _handle_payment_proof(update, context, uid):
    """Пользователь отправил скриншот оплаты."""
    import datetime
    from utils.helpers import generate_id
    user = get_user(uid)
    photo_file_id = update.message.photo[-1].file_id
    amount_net = context.user_data.get('check_amount', 0)
    amount_fee = context.user_data.get('check_fee', 0)
    amount_total = context.user_data.get('check_total', 0)
    check_method = context.user_data.get('check_method', 'balance')
    check_type = 'deposit' if check_method == 'crypto_deposit' else 'balance'

    check_id = generate_id("CHK")
    checks = load_json(DB_CHECKS)
    checks.append({
        "id": check_id,
        "user_id": uid,
        "username": user.get('username', 'нет'),
        "amount_net": amount_net,
        "amount_fee": amount_fee,
        "amount_total": amount_total,
        "photo_file_id": photo_file_id,
        "type": check_type,
        "status": "pending",
        "date": datetime.datetime.now().isoformat(),
    })
    save_json(DB_CHECKS, checks)

    # Уведомление админу
    admin_text = (
        f"📸 <b>Новый чек #{check_id}</b>\n"
        f"👤 @{user.get('username', uid)}\n"
        f"Тип: {check_type}\n"
        f"Зачислить: <b>${amount_net:.2f}</b>\n"
        f"Комиссия: <b>${amount_fee:.2f}</b>\n"
        f"Оплачено: <b>${amount_total:.2f}</b>"
    )
    from utils.helpers import btn, kb
    rows = [
        [btn(f"{E.SUCCESS} Подтвердить", f"admin_check_approve_{check_id}"),
         btn(f"{E.CANCEL} Отклонить", f"admin_check_reject_{check_id}")],
    ]
    try:
        await context.bot.send_photo(
            ADMIN_ID, photo=photo_file_id, caption=admin_text,
            reply_markup=kb(rows), parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления admin: {e}")

    await update.message.reply_text(
        f"{E.SUCCESS} Чек <b>#{check_id}</b> отправлен на проверку. Ожидайте подтверждения.",
        parse_mode="HTML"
    )
    context.user_data['state'] = None
