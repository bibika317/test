"""
handlers/moderation.py — Бан, варны, промокоды, рассылка (команды для admin).
"""
import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes

from config import E, ADMIN_ID
from data.storage import (
    is_admin, get_user, save_user, load_json, save_json,
    DB_USERS, DB_WARNINGS, DB_NUMBERS, DB_PROMOCODES
)
from utils.helpers import btn, kb

logger = logging.getLogger(__name__)


async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /warn @username")
        return
    uname = context.args[0].replace('@', '')
    users = load_json(DB_USERS)
    uid = next((int(k) for k, v in users.items() if v.get('username') == uname), None)
    if not uid:
        await update.message.reply_text(f"{E.ERROR} @{uname} не найден.")
        return
    warnings = load_json(DB_WARNINGS)
    entry = warnings.get(str(uid), {'count': 0})
    entry['count'] = entry.get('count', 0) + 1
    warnings[str(uid)] = entry
    save_json(DB_WARNINGS, warnings)
    count = entry['count']
    await update.message.reply_text(f"{E.WARNING} @{uname} — предупреждение #{count}")
    try:
        await context.bot.send_message(uid, f"{E.WARNING} Вы получили предупреждение #{count}.", parse_mode="HTML")
    except Exception:
        pass


async def cmd_unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        return
    uname = context.args[0].replace('@', '')
    users = load_json(DB_USERS)
    uid = next((int(k) for k, v in users.items() if v.get('username') == uname), None)
    if not uid:
        await update.message.reply_text(f"{E.ERROR} @{uname} не найден.")
        return
    warnings = load_json(DB_WARNINGS)
    if str(uid) in warnings:
        warnings[str(uid)]['count'] = max(0, warnings[str(uid)].get('count', 1) - 1)
        save_json(DB_WARNINGS, warnings)
    await update.message.reply_text(f"{E.SUCCESS} Предупреждение снято у @{uname}")


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /ban @username")
        return
    uname = context.args[0].replace('@', '')
    users = load_json(DB_USERS)
    uid = next((int(k) for k, v in users.items() if v.get('username') == uname), None)
    if not uid:
        await update.message.reply_text(f"{E.ERROR} @{uname} не найден.")
        return
    user = get_user(uid)
    user['is_banned'] = True
    save_user(uid, user)
    await update.message.reply_text(f"🔨 @{uname} заблокирован.")
    try:
        await context.bot.send_message(uid, "🔨 Ваш аккаунт заблокирован.", parse_mode="HTML")
    except Exception:
        pass


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        return
    uname = context.args[0].replace('@', '')
    users = load_json(DB_USERS)
    uid = next((int(k) for k, v in users.items() if v.get('username') == uname), None)
    if not uid:
        await update.message.reply_text(f"{E.ERROR} @{uname} не найден.")
        return
    user = get_user(uid)
    user['is_banned'] = False
    save_user(uid, user)
    await update.message.reply_text(f"{E.SUCCESS} @{uname} разблокирован.")


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /search @username")
        return
    uname = context.args[0].replace('@', '')
    users = load_json(DB_USERS)
    found = [(k, v) for k, v in users.items() if v.get('username') == uname]
    if not found:
        await update.message.reply_text(f"{E.ERROR} @{uname} не найден.")
        return
    uid, data = found[0]
    from utils.finance import get_unified_balance
    bal = get_unified_balance(data)
    dep = data.get('deposit_usd', 0.0)
    banned = "🔨 Заблокирован" if data.get('is_banned') else "✅ Активен"
    text = (
        f"👤 @{uname}\nID: <code>{uid}</code>\n"
        f"Баланс: ${bal:.2f}\nДепозит: ${dep:.2f}\n"
        f"Статус: {banned}\nРефералов: {data.get('ref_count', 0)}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_delete_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /delete NUM_ID")
        return
    nid = context.args[0]
    numbers = load_json(DB_NUMBERS)
    before = len(numbers)
    numbers = [n for n in numbers if n.get('id') != nid]
    if len(numbers) == before:
        await update.message.reply_text(f"{E.ERROR} Номер {nid} не найден.")
        return
    save_json(DB_NUMBERS, numbers)
    await update.message.reply_text(f"{E.SUCCESS} Номер {nid} удалён.")


async def cmd_create_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /createpromo CODE 5.00")
        return
    code = context.args[0].upper()
    try:
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Неверная сумма.")
        return
    promos = load_json(DB_PROMOCODES)
    promos[code] = {'amount': amount, 'used': False}
    save_json(DB_PROMOCODES, promos)
    await update.message.reply_text(f"{E.SUCCESS} Промокод <code>{code}</code> на ${amount:.2f} создан!", parse_mode="HTML")


async def cmd_check_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        return
    code = context.args[0].upper()
    promos = load_json(DB_PROMOCODES)
    p = promos.get(code)
    if not p:
        await update.message.reply_text(f"{E.ERROR} Не найден.")
        return
    status = "Использован" if p.get('used') else "Активен"
    await update.message.reply_text(f"Промокод: {code}\nСумма: ${p['amount']:.2f}\nСтатус: {status}")


# ============================================================
# РАССЫЛКА
# ============================================================

async def cmd_send_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data['admin_state'] = 'waiting_broadcast'
    await update.message.reply_text("📢 Отправьте сообщение (текст или фото) для рассылки всем пользователям:")


async def handle_admin_broadcast_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('admin_state') != 'waiting_broadcast':
        return
    if not is_admin(update.effective_user.id):
        context.user_data['admin_state'] = None
        return

    users = load_json(DB_USERS)
    count = 0
    failed = 0

    await update.message.reply_text(f"🔄 Начинаем рассылку {len(users)} пользователям...")

    for uid_str, u_data in users.items():
        if u_data.get('is_banned'):
            continue
        try:
            if update.message.photo:
                file_id = update.message.photo[-1].file_id
                caption = update.message.caption or ""
                await context.bot.send_photo(chat_id=int(uid_str), photo=file_id,
                                             caption=caption, parse_mode="HTML")
            elif update.message.text:
                await context.bot.send_message(chat_id=int(uid_str),
                                               text=update.message.text, parse_mode="HTML")
            count += 1
            if count % 30 == 0:
                await asyncio.sleep(0.5)
        except Exception:
            failed += 1

    context.user_data['admin_state'] = None
    await update.message.reply_text(f"{E.SUCCESS} Рассылка завершена!\nОтправлено: {count}\nОшибок: {failed}")


async def cmd_send_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /send @username")
        return
    uname = context.args[0].replace('@', '')
    users = load_json(DB_USERS)
    uid = next((int(k) for k, v in users.items() if v.get('username') == uname), None)
    if not uid:
        await update.message.reply_text(f"{E.ERROR} @{uname} не найден.")
        return
    context.user_data['admin_state'] = 'waiting_send_user'
    context.user_data['send_user_target_id'] = uid
    context.user_data['send_user_target_name'] = f"@{uname}"
    await update.message.reply_text(f"Отправьте сообщение для @{uname}:")


async def handle_admin_send_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('admin_state') != 'waiting_send_user':
        return
    target_id = context.user_data.get('send_user_target_id')
    target_name = context.user_data.get('send_user_target_name', '—')
    if not target_id:
        context.user_data['admin_state'] = None
        return
    try:
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            caption = update.message.caption or ""
            await context.bot.send_photo(chat_id=target_id, photo=file_id, caption=caption, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=target_id, text=update.message.text, parse_mode="HTML")
        await update.message.reply_text(f"{E.SUCCESS} Сообщение отправлено {target_name}!")
    except Exception as e:
        await update.message.reply_text(f"{E.WARNING} Ошибка отправки.")
    context.user_data['admin_state'] = None
    context.user_data.pop('send_user_target_id', None)
    context.user_data.pop('send_user_target_name', None)
