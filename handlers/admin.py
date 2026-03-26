"""
handlers/admin.py — Админ-панель (доступ через кнопку), статистика, авто-отчёт.
"""
import logging
import datetime
from telegram import Update, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ContextTypes

from config import E, ADMIN_ID
from data.storage import (
    is_admin, load_json, save_json, get_user, save_user,
    DB_USERS, DB_DEALS, DB_NUMBERS, DB_CHECKS, DB_WITHDRAW_REQUESTS,
    DB_ADMIN_SETTINGS, DB_DEPOSIT_WITHDRAW_REQUESTS,
    DB_CUSTOM_ORDERS
)
from utils.finance import (
    get_unified_balance, get_rate, format_price, get_total_users_balance, deduct_payment
)
from utils.helpers import btn, kb, edit_message

logger = logging.getLogger(__name__)


async def admin_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ Доступ запрещён", show_alert=True)
        return
    await query.answer()

    checks_n = len([c for c in load_json(DB_CHECKS) if c.get('status') == 'pending'])
    wd_n = len([w for w in load_json(DB_WITHDRAW_REQUESTS) if w.get('status') == 'pending'])
    dep_wd_n = len([w for w in load_json(DB_DEPOSIT_WITHDRAW_REQUESTS) if w.get('status') == 'pending'])

    def badge(n): return f" ({n})" if n else ""

    text = (
        f"{E.ADMIN} <b>Админ-панель</b>\n\n"
        f"Чеков: <b>{checks_n}</b> | Выводов: <b>{wd_n}</b> | Деп.выводов: <b>{dep_wd_n}</b>"
    )
    rows = [
        [btn(f"📋 Чеки{badge(checks_n)}", "admin_checks_list"),
         btn(f"💸 Выводы{badge(wd_n)}", "admin_withdraw_list")],
        [btn(f"🏦 Деп.выводы{badge(dep_wd_n)}", "admin_deposit_withdraw_list"),
         btn(f"{E.STATS} Статистика", "admin_statistics")],
        [btn("👥 Пользователи", "admin_users_summary"),
         btn("🏦 Все депозиты", "admin_all_deposits")],
        [btn(f"{E.SETTINGS} Настройки", "admin_settings"),
         btn("📢 Рассылка", "admin_broadcast_start")],
        [btn(f"{E.MENU} Главное меню", "start")],
    ]
    await edit_message(update, context, text, rows, "menu.jpg")


async def admin_statistics_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ Доступ запрещён", show_alert=True)
        return
    await query.answer()

    deals = load_json(DB_DEALS)
    numbers = load_json(DB_NUMBERS)
    users = load_json(DB_USERS)
    checks = load_json(DB_CHECKS)
    withdraws = load_json(DB_WITHDRAW_REQUESTS)
    custom_orders = load_json(DB_CUSTOM_ORDERS)

    completed_deals = sum(1 for d in deals.values() if d.get('status') == 'completed')
    sold_nums = sum(1 for n in numbers if n.get('status') == 'sold')
    active_nums = sum(1 for n in numbers if n.get('status') == 'active')
    commission = sum(c.get('amount_fee', 0.0) for c in checks if c.get('status') == 'approved')
    commission += sum(w.get('amount_fee', 0.0) for w in withdraws if w.get('status') == 'approved')
    deposit_topup = sum(c.get('amount_net', 0.0) for c in checks
                        if c.get('status') == 'approved' and c.get('type') == 'deposit')
    balance_topup = sum(c.get('amount_net', 0.0) for c in checks
                        if c.get('status') == 'approved' and c.get('type') == 'balance')
    withdrawn = sum(w.get('amount_net', 0.0) for w in withdraws if w.get('status') == 'approved')
    custom_active = sum(1 for o in custom_orders.values()
                        if o.get('status') not in ['completed', 'cancelled'])
    custom_done = sum(1 for o in custom_orders.values() if o.get('status') == 'completed')

    fin = get_total_users_balance(users)

    text = (
        f"{E.STATS} <b>СТАТИСТИКА</b>\n\n"
        f"<b>Сделки:</b> всего {len(deals)} | завершено {completed_deals}\n"
        f"<b>Номера:</b> в каталоге {active_nums} | продано {sold_nums}\n"
        f"<b>По запросу:</b> активных {custom_active} | завершено {custom_done}\n"
        f"<b>Пользователей:</b> {len(users)}\n\n"
        f"<b>💰 В системе сейчас:</b>\n"
        f"  Балансы: <b>${fin['balance_total_usd']:.2f}</b>\n"
        f"  Депозиты: <b>${fin['deposit_total_usd']:.2f}</b>\n"
        f"  <b>Итого: ${fin['in_system_usd']:.2f}</b>\n\n"
        f"<b>📥 Пополнения:</b> депозит ${deposit_topup:.2f} | баланс ${balance_topup:.2f}\n"
        f"<b>📤 Выводы:</b> ${withdrawn:.2f}\n"
        f"<b>🏦 Комиссия:</b> ${commission:.2f}"
    )
    rows = [
        [btn("🔄 Обновить", "admin_statistics")],
        [btn(f"{E.BACK} Назад в админку", "admin_main")],
    ]
    await edit_message(update, context, text, rows, "menu.jpg")


async def admin_users_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌", show_alert=True)
        return
    await query.answer()
    users = load_json(DB_USERS)
    fin = get_total_users_balance(users)
    banned = sum(1 for u in users.values() if u.get('is_banned'))
    text = (
        f"👥 <b>Пользователи</b>\n\n"
        f"Всего: <b>{len(users)}</b> | Забанено: <b>{banned}</b>\n\n"
        f"<b>Средства:</b>\n"
        f"  Балансы: <b>${fin['balance_total_usd']:.2f}</b>\n"
        f"  Депозиты: <b>${fin['deposit_total_usd']:.2f}</b>\n"
        f"  <b>В системе: ${fin['in_system_usd']:.2f}</b>\n"
        f"  Курс: {get_rate()} KZT/USD"
    )
    rows = [
        [btn("🔄 Обновить", "admin_users_summary")],
        [btn(f"{E.BACK} Назад", "admin_main")],
    ]
    await edit_message(update, context, text, rows, "menu.jpg")


async def send_daily_report(context):
    """Ежедневный авто-отчёт для администратора."""
    try:
        users = load_json(DB_USERS)
        deals = load_json(DB_DEALS)
        fin = get_total_users_balance(users)
        today = datetime.date.today().strftime("%d.%m.%Y")
        today_deals = sum(
            1 for d in deals.values()
            if d.get('created_at', '').startswith(str(datetime.date.today()))
            and d.get('status') == 'completed'
        )
        text = (
            f"{E.STATS} <b>Авто-отчёт — {today}</b>\n\n"
            f"👥 Пользователей: <b>{len(users)}</b>\n"
            f"🤝 Сделок завершено сегодня: <b>{today_deals}</b>\n\n"
            f"<b>💰 Средства в системе:</b>\n"
            f"  Балансы: <b>${fin['balance_total_usd']:.2f}</b>\n"
            f"  Депозиты: <b>${fin['deposit_total_usd']:.2f}</b>\n"
            f"  <b>Итого: ${fin['in_system_usd']:.2f}</b>"
        )
        await context.bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка авто-отчёта: {e}")


# ——— Чеки ———

async def admin_checks_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    checks = load_json(DB_CHECKS)
    pending = [c for c in checks if c.get('status') == 'pending']
    if not pending:
        await edit_message(update, context, f"{E.SUCCESS} Новых чеков нет.",
                           [[btn(f"{E.BACK} Назад", "admin_main")]], "menu.jpg")
        return
    rows = [[btn(f"{c['id']} | ${c['amount_total']:.2f}", f"admin_check_view_{c['id']}")]
            for c in pending[:10]]
    rows.append([btn(f"{E.BACK} Назад", "admin_main")])
    await edit_message(update, context, f"📋 Чеки ({len(pending)})", rows, "menu.jpg")


async def admin_check_view_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cid = query.data.split("_")[-1]
    checks = load_json(DB_CHECKS)
    c = next((x for x in checks if x['id'] == cid), None)
    if not c:
        return
    user = get_user(c['user_id'])
    text = (
        f"📋 Чек <code>{cid}</code>\n"
        f"👤 @{user.get('username', c['user_id'])}\n"
        f"Зачислить: <b>${c['amount_net']:.2f}</b>\n"
        f"Комиссия: <b>${c['amount_fee']:.2f}</b>\n"
        f"Оплачено: <b>${c['amount_total']:.2f}</b>"
    )
    rows = [
        [btn(f"{E.SUCCESS} Подтвердить", f"admin_check_approve_{cid}"),
         btn(f"{E.ERROR} Отклонить", f"admin_check_reject_{cid}")],
        [btn(f"{E.BACK} Назад", "admin_checks_list")],
    ]
    markup = kb(rows)
    if c.get('photo_file_id'):
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(media=c['photo_file_id'], caption=text, parse_mode="HTML"),
                reply_markup=markup
            )
            return
        except Exception:
            pass
    await edit_message(update, context, text, rows, "menu.jpg")


async def admin_process_check(update: Update, context: ContextTypes.DEFAULT_TYPE, approve: bool):
    query = update.callback_query
    await query.answer()
    cid = query.data.split("_")[-1]
    checks = load_json(DB_CHECKS)
    c = next((x for x in checks if x['id'] == cid), None)
    if not c:
        return
    idx = checks.index(c)
    users = load_json(DB_USERS)
    u_str = str(c['user_id'])

    if approve:
        c['status'] = 'approved'
        if u_str in users:
            amount_net = c['amount_net']
            is_deposit = c.get('type') == 'deposit'
            if is_deposit:
                users[u_str]['deposit_usd'] = users[u_str].get('deposit_usd', 0.0) + amount_net
                msg = f"{E.SUCCESS} Депозит пополнен на <b>${amount_net:.2f}</b>"
                if amount_net > 0:
                    from handlers.notifications import broadcast_new_seller
                    await broadcast_new_seller(context, c['user_id'], amount_net)
            else:
                users[u_str]['balance_usd'] = users[u_str].get('balance_usd', 0.0) + amount_net
                msg = f"{E.SUCCESS} Баланс пополнен на <b>${amount_net:.2f}</b>"
            save_json(DB_USERS, users)
            try:
                await context.bot.send_message(c['user_id'], msg, parse_mode="HTML")
            except Exception:
                pass
    else:
        c['status'] = 'rejected'
        try:
            await context.bot.send_message(c['user_id'],
                                           f"{E.ERROR} Чек отклонён администратором.")
        except Exception:
            pass

    checks[idx] = c
    save_json(DB_CHECKS, checks)
    await edit_message(update, context, "✔️ Обработано.",
                       [[btn(f"{E.BACK} Назад", "admin_checks_list")]], "menu.jpg")


# ——— Выводы ———

async def admin_withdraw_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ws = load_json(DB_WITHDRAW_REQUESTS)
    pending = [w for w in ws if w.get('status') == 'pending']
    if not pending:
        await edit_message(update, context, f"{E.SUCCESS} Заявок нет.",
                           [[btn(f"{E.BACK} Назад", "admin_main")]], "menu.jpg")
        return
    rows = [[btn(f"{w['id']} | ${w['amount_net']:.2f}", f"admin_withdraw_view_{w['id']}")]
            for w in pending[:10]]
    rows.append([btn(f"{E.BACK} Назад", "admin_main")])
    await edit_message(update, context, f"💸 Выводы ({len(pending)})", rows, "menu.jpg")


async def admin_withdraw_view_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wid = query.data.split("_")[-1]
    ws = load_json(DB_WITHDRAW_REQUESTS)
    w = next((x for x in ws if x['id'] == wid), None)
    if not w:
        return
    text = (
        f"💸 Вывод <code>{wid}</code>\n"
        f"👤 @{w.get('username', w['user_id'])}\n"
        f"К выдаче: <b>${w['amount_net']:.2f}</b>\n"
        f"Комиссия: <b>${w['amount_fee']:.2f}</b>\n"
        f"Списано: <b>${w['amount_total']:.2f}</b>"
    )
    rows = [
        [btn(f"{E.SUCCESS} Подтвердить", f"admin_withdraw_approve_{wid}"),
         btn(f"{E.ERROR} Отклонить", f"admin_withdraw_reject_{wid}")],
        [btn(f"{E.BACK} Назад", "admin_withdraw_list")],
    ]
    await edit_message(update, context, text, rows, "menu.jpg")


async def admin_process_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE, approve: bool):
    query = update.callback_query
    await query.answer()
    wid = query.data.split("_")[-1]
    ws = load_json(DB_WITHDRAW_REQUESTS)
    w = next((x for x in ws if x['id'] == wid), None)
    if not w:
        return
    if approve:
        u = get_user(w['user_id'])
        if get_unified_balance(u) >= w['amount_total']:
            deduct_payment(u, w['amount_total'], 'USD')
            save_user(w['user_id'], u)
            w['status'] = 'approved'
            try:
                await context.bot.send_message(
                    w['user_id'],
                    f"{E.SUCCESS} Вывод подтверждён! К получению: <b>${w['amount_net']:.2f}</b>",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        else:
            w['status'] = 'error'
            try:
                await context.bot.send_message(w['user_id'],
                                               f"{E.ERROR} Недостаточно средств.")
            except Exception:
                pass
    else:
        w['status'] = 'rejected'
        try:
            await context.bot.send_message(w['user_id'], f"{E.ERROR} Вывод отклонён.")
        except Exception:
            pass
    idx = ws.index(w)
    ws[idx] = w
    save_json(DB_WITHDRAW_REQUESTS, ws)
    await edit_message(update, context, "✔️ Обработано.",
                       [[btn(f"{E.BACK} Назад", "admin_withdraw_list")]], "menu.jpg")


# ——— Выводы из депозита ———

async def admin_deposit_withdraw_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ws = load_json(DB_DEPOSIT_WITHDRAW_REQUESTS)
    pending = [w for w in ws if w.get('status') == 'pending']
    if not pending:
        await edit_message(update, context, f"{E.SUCCESS} Заявок нет.",
                           [[btn(f"{E.BACK} Назад", "admin_main")]], "menu.jpg")
        return
    rows = [[btn(f"{w['id']} | {w['amount']:,.0f} {w['currency']}",
                 f"admin_deposit_withdraw_view_{w['id']}")] for w in pending[:10]]
    rows.append([btn(f"{E.BACK} Назад", "admin_main")])
    await edit_message(update, context, f"🏦 Выводы из депозита ({len(pending)})", rows, "menu.jpg")


async def admin_deposit_withdraw_view_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wid = query.data.split("_")[-1]
    ws = load_json(DB_DEPOSIT_WITHDRAW_REQUESTS)
    w = next((x for x in ws if x['id'] == wid), None)
    if not w:
        return
    text = (
        f"🏦 Вывод из депозита <code>{wid}</code>\n"
        f"👤 @{w.get('username', w['user_id'])}\n"
        f"Сумма: <b>{w['amount']:,.0f} {w['currency']}</b>\n"
        f"Причина: {w.get('reason', '—')}"
    )
    rows = [
        [btn(f"{E.SUCCESS} Подтвердить", f"admin_deposit_withdraw_approve_{wid}"),
         btn(f"{E.ERROR} Отклонить", f"admin_deposit_withdraw_reject_{wid}")],
        [btn(f"{E.BACK} Назад", "admin_deposit_withdraw_list")],
    ]
    await edit_message(update, context, text, rows, "menu.jpg")


async def admin_process_deposit_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE, approve: bool):
    query = update.callback_query
    await query.answer()
    wid = query.data.split("_")[-1]
    ws = load_json(DB_DEPOSIT_WITHDRAW_REQUESTS)
    w = next((x for x in ws if x['id'] == wid), None)
    if not w:
        return
    user_id, amount, currency = w['user_id'], w['amount'], w['currency']

    if approve:
        u = get_user(user_id)
        dep_key = f"deposit_{currency.lower()}"
        bal_key = f"balance_{currency.lower()}"
        if u.get(dep_key, 0.0) >= amount:
            u[dep_key] = round(u[dep_key] - amount, 2 if currency == 'USD' else 0)
            u[bal_key] = round(u.get(bal_key, 0.0) + amount, 2 if currency == 'USD' else 0)
            save_user(user_id, u)
            w['status'] = 'approved'
            try:
                await context.bot.send_message(
                    user_id,
                    f"{E.SUCCESS} Вывод из депозита подтверждён!\n"
                    f"<b>{amount} {currency}</b> зачислены на баланс.",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            new_dep = u.get('deposit_usd', 0.0) + u.get('deposit_kzt', 0.0) / get_rate()
            if new_dep <= 0:
                from handlers.notifications import broadcast_guarantee_lost
                amount_usd = amount if currency == 'USD' else amount / get_rate()
                await broadcast_guarantee_lost(context, user_id, amount_usd, w.get('reason', ''))
        else:
            w['status'] = 'error'
            try:
                await context.bot.send_message(user_id, f"{E.ERROR} Недостаточно средств в депозите.")
            except Exception:
                pass
    else:
        w['status'] = 'rejected'
        try:
            await context.bot.send_message(user_id, f"{E.ERROR} Вывод из депозита отклонён.")
        except Exception:
            pass

    idx = ws.index(w)
    ws[idx] = w
    save_json(DB_DEPOSIT_WITHDRAW_REQUESTS, ws)
    await edit_message(update, context, "✔️ Обработано.",
                       [[btn(f"{E.BACK} Назад", "admin_deposit_withdraw_list")]], "menu.jpg")


# ——— Настройки ———

async def admin_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rate = load_json(DB_ADMIN_SETTINGS).get('usd_kzt_rate', 450.0)
    text = f"{E.SETTINGS} <b>Настройки</b>\n\nКурс USD/KZT: <b>{rate}</b>"
    rows = [
        [btn("✏️ Изменить курс", "set_rate")],
        [btn(f"{E.BACK} Назад", "admin_main")],
    ]
    await edit_message(update, context, text, rows, "menu.jpg")


async def admin_set_rate_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['admin_set_mode'] = 'rate'
    context.user_data['state'] = 'admin_waiting_requisite'
    rows = [[btn(f"{E.CANCEL} Отмена", "admin_settings")]]
    await edit_message(update, context, "Введите новый курс USD/KZT:", rows, "menu.jpg")


# ——— Все депозиты ———

async def admin_all_deposits_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("❌", show_alert=True)
        return
    users = load_json(DB_USERS)
    sellers = []
    for uid, data in users.items():
        dep_usd = data.get('deposit_usd', 0.0)
        dep_kzt = data.get('deposit_kzt', 0.0)
        total = dep_usd + dep_kzt / get_rate()
        if total > 0:
            sellers.append({'id': uid, 'name': f"@{data.get('username', 'ID:' + uid)}",
                            'total': total, 'usd': dep_usd, 'kzt': dep_kzt})
    sellers.sort(key=lambda x: x['total'], reverse=True)
    if not sellers:
        await edit_message(update, context, "ℹ️ Депозитов нет.",
                           [[btn(f"{E.BACK} Назад", "admin_main")]], "menu.jpg")
        return
    text = f"{E.DEPOSIT} <b>Все депозиты:</b>\n\n"
    rows = []
    for i, s in enumerate(sellers, 1):
        text += f"{i}. {s['name']} — <b>${s['total']:.2f}</b>\n"
        rows.append([btn(f"👤 {s['name']}", f"top_seller_profile_{s['id']}")])
    rows.append([btn(f"{E.BACK} Назад", "admin_main")])
    await edit_message(update, context, text, rows, "menu.jpg")


# ——— Изменение баланса командой /balance ———

async def cmd_balance_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /balance @username +100")
        return
    target_username = context.args[0].replace('@', '')
    try:
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Неверная сумма.")
        return
    users_db = load_json(DB_USERS)
    target_id = next((int(uid) for uid, d in users_db.items()
                      if d.get('username') == target_username), None)
    if not target_id:
        await update.message.reply_text(f"❌ @{target_username} не найден.")
        return
    context.user_data.update({
        'admin_balance_target_id': target_id,
        'admin_balance_amount': amount,
        'admin_state': 'waiting_balance_currency',
    })
    action = "начислить" if amount > 0 else "списать"
    rows = [
        [btn(f"💵 USD", "admin_bal_usd"), btn(f"🇰🇿 KZT", "admin_bal_kzt")],
        [btn(f"{E.CANCEL} Отмена", "start")],
    ]
    await update.message.reply_text(
        f"👤 @{target_username}\n{action}: {abs(amount)}\n\nВыберите валюту:",
        reply_markup=kb(rows), parse_mode="HTML"
    )


async def admin_balance_currency_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if context.user_data.get('admin_state') != 'waiting_balance_currency':
        return
    target_id = context.user_data.get('admin_balance_target_id')
    amount = context.user_data.get('admin_balance_amount')
    if not target_id or amount is None:
        await query.edit_message_text("❌ Ошибка сессии.")
        return
    currency = 'USD' if query.data == 'admin_bal_usd' else 'KZT'
    bal_key = 'balance_usd' if currency == 'USD' else 'balance_kzt'
    user = get_user(target_id)
    new_val = user.get(bal_key, 0.0) + amount
    if new_val < 0:
        await query.edit_message_text(f"{E.ERROR} Недостаточно средств.")
        return
    user[bal_key] = round(new_val, 2 if currency == 'USD' else 0)
    save_user(target_id, user)
    sign = "+" if amount > 0 else ""
    action = "Зачислено" if amount > 0 else "Списано"
    await query.edit_message_text(
        f"{E.SUCCESS} {action}: <b>{sign}{amount} {currency}</b>\nНовый баланс: {user[bal_key]} {currency}",
        parse_mode="HTML"
    )
    try:
        await context.bot.send_message(
            target_id,
            f"💸 <b>Изменение баланса</b>\n{action}: <b>{sign}{amount} {currency}</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass
    context.user_data['admin_state'] = None


# ——— Рассылка ———

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌", show_alert=True)
        return
    await query.answer()
    context.user_data['admin_state'] = 'waiting_broadcast'
    await edit_message(update, context,
                       "📢 <b>Рассылка</b>\n\nОтправьте текст или фото с подписью.",
                       [[btn(f"{E.CANCEL} Отмена", "admin_main")]], "menu.jpg")


async def handle_admin_broadcast_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import asyncio
    uid = update.effective_user.id
    if not is_admin(uid):
        context.user_data['admin_state'] = None
        return
    users = load_json(DB_USERS)
    await update.message.reply_text(f"🔄 Рассылка для {len(users)} пользователей...")

    content_type, file_id, caption = None, None, ""
    if update.message.photo:
        content_type, file_id = 'photo', update.message.photo[-1].file_id
        caption = update.message.caption or ""
    elif update.message.text:
        content_type, caption = 'text', update.message.text

    count, failed = 0, 0
    for uid_str, u_data in users.items():
        if u_data.get('is_banned'):
            continue
        try:
            if content_type == 'photo':
                await context.bot.send_photo(int(uid_str), photo=file_id,
                                             caption=caption, parse_mode="HTML")
            else:
                await context.bot.send_message(int(uid_str), text=caption, parse_mode="HTML")
            count += 1
            if count % 30 == 0:
                await asyncio.sleep(0.5)
        except Exception:
            failed += 1

    context.user_data['admin_state'] = None
    await update.message.reply_text(
        f"{E.SUCCESS} <b>Рассылка завершена</b>\nОтправлено: {count} | Ошибок: {failed}",
        parse_mode="HTML"
    )
