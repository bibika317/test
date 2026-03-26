"""
handlers/catalog.py — Каталог номеров, покупка, продажа, мои номера, топ, профиль продавца.
"""
import logging
import math
from telegram import Update
from telegram.ext import ContextTypes

from config import E, EXAMPLE_NUMBER, ITEMS_PER_PAGE, TOP_DEPOSITS_COUNT, SELLERS_PER_PAGE
from data.storage import get_user, save_user, load_json, save_json, DB_NUMBERS, DB_USERS
from utils.finance import get_unified_balance, format_price, get_rate
from utils.helpers import btn, kb, edit_message, generate_id, format_number

logger = logging.getLogger(__name__)


# ============================================================
# ПОКУПКА
# ============================================================

async def buy_menu_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['buy_page'] = 0
    await _show_catalog_page(update, context, 0)


async def _show_catalog_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    numbers = load_json(DB_NUMBERS)
    active = [n for n in numbers if n.get('status') == 'active']
    total_pages = max(1, math.ceil(len(active) / ITEMS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))

    start = page * ITEMS_PER_PAGE
    items = active[start:start + ITEMS_PER_PAGE]

    if not items:
        await edit_message(update, context,
                           f"{E.CATALOG} В каталоге пока нет номеров.",
                           [[btn(f"{E.MENU} Главное меню", "start")]], "catalog.jpg")
        return

    text = f"{E.CATALOG} <b>Каталог номеров</b>\nСтр. {page + 1}/{total_pages}"
    rows = []
    for n in items:
        num_str = format_number(n['number'])
        price_str = format_price(n['price'], n['currency'])
        rows.append([btn(f"{num_str} · {price_str}", f"buy_number_view_{n['id']}")])

    nav = []
    if page > 0:
        nav.append(btn(f"⬅️ Назад", f"buy_page_prev_{page}"))
    if page < total_pages - 1:
        nav.append(btn(f"Вперёд ➡️", f"buy_page_next_{page}"))
    if nav:
        rows.append(nav)
    rows.append([btn(f"{E.MENU} Главное меню", "start")])
    await edit_message(update, context, text, rows, "catalog.jpg")


async def buy_page_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    direction = parts[2]  # prev / next
    current = int(parts[3])
    page = current - 1 if direction == 'prev' else current + 1
    await _show_catalog_page(update, context, page)


async def buy_number_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nid = query.data.replace("buy_number_view_", "")
    numbers = load_json(DB_NUMBERS)
    num = next((n for n in numbers if n.get('id') == nid), None)
    if not num or num.get('status') != 'active':
        await query.answer("Номер недоступен.", show_alert=True)
        return

    seller = get_user(num.get('seller_id', 0))
    dep = seller.get('deposit_usd', 0.0) + seller.get('deposit_kzt', 0.0) / get_rate()
    uname = f"@{seller.get('username', '—')}"
    code_type = num.get('code_type')
    code_label = "SMS" if code_type == 'sms' else "Аудио" if code_type == 'audio' else None
    text = (
        f"{E.PHONE} <b>{format_number(num['number'])}</b>\n\n"
        f"💰 {format_price(num['price'], num['currency'])}\n"
        f"👤 Продавец: {uname}\n"
        f"{E.DEPOSIT} Гарантия: ${dep:.2f}"
    )
    if code_label:
        text += f"\n{E.CODE} Тип кода: {code_label}"
    rows = [
        [btn(f"{E.BUY} Купить", f"buy_code_menu_{nid}")],
        [btn(f"👤 Профиль продавца", f"view_seller_numbers_{num.get('seller_id')}")],
        [btn(f"{E.BACK} К каталогу", "menu_buy")],
    ]
    await edit_message(update, context, text, rows, "catalog.jpg")


async def buy_code_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nid = query.data.replace("buy_code_menu_", "")
    numbers = load_json(DB_NUMBERS)
    num = next((n for n in numbers if n.get('id') == nid), None)
    if not num or num.get('status') != 'active':
        await query.answer("Номер недоступен.", show_alert=True)
        return
    code_type = num.get('code_type')
    hint = ""
    if code_type == 'sms':
        hint = f"\n\n{E.CODE} Продавец указал: SMS"
    elif code_type == 'audio':
        hint = f"\n\n{E.CODE} Продавец указал: Аудио"

    text = f"{E.CODE} Выберите тип подтверждения:{hint}"
    rows = [
        [btn(f"{E.CODE} SMS", f"create_deal_sms_{nid}"),
         btn(f"{E.CODE} Аудио", f"create_deal_audio_{nid}")],
        [btn(f"{E.BACK} Назад", f"buy_number_view_{nid}")],
    ]
    await edit_message(update, context, text, rows, "catalog.jpg")


# ============================================================
# ПРОДАЖА
# ============================================================

async def _show_sell_country_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    dep = user.get('deposit_usd', 0.0) + user.get('deposit_kzt', 0.0) / get_rate()
    text = (
        f"{E.SELL} <b>Продать номер</b>\n\n"
        f"Ваш депозит: <b>${dep:.2f}</b>\n\n"
        f"Выберите тип номера:"
    )
    rows = [
        [btn("📱 Казахстан (+77)", "sell_type_KZ")],
        [btn(f"{E.MENU} Главное меню", "start")],
    ]
    await edit_message(update, context, text, rows, "sellnumber.jpg")


async def sell_menu_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    dep = user.get('deposit_usd', 0.0) + user.get('deposit_kzt', 0.0) / get_rate()
    text = (
        f"{E.SELL} <b>Продать номер</b>\n\n"
        f"Ваш депозит: <b>${dep:.2f}</b>\n\n"
        f"Выберите тип подтверждения:"
    )
    rows = [
        [btn(f"{E.CODE} SMS", "sell_code_sms"),
         btn(f"{E.CODE} Аудио", "sell_code_audio")],
        [btn(f"{E.MENU} Главное меню", "start")],
    ]
    await edit_message(update, context, text, rows, "sellnumber.jpg")


async def sell_code_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code_type = query.data.replace("sell_code_", "")
    if code_type not in ("sms", "audio"):
        code_type = "sms"
    context.user_data['sell_code_type'] = code_type
    await _show_sell_country_menu(update, context)


async def sell_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not context.user_data.get('sell_code_type'):
        context.user_data['sell_code_type'] = 'sms'
    context.user_data['sell_country'] = query.data.replace("sell_type_", "")
    context.user_data['sell_state'] = 'waiting_number'
    await edit_message(update, context,
                       f"{E.PHONE} Введите номер телефона:\nПример: {EXAMPLE_NUMBER}",
                       [[btn(f"{E.CANCEL} Отмена", "menu_sell")]], "sellnumber.jpg")


async def set_currency_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    currency = 'USD' if query.data == 'set_curr_usd' else 'KZT'
    uid = query.from_user.id
    user = get_user(uid)
    number = context.user_data.get('temp_number')
    price = context.user_data.get('temp_price')

    if not number or not price:
        await edit_message(update, context, f"{E.ERROR} Ошибка данных. Начните заново.",
                           [[btn(f"{E.BACK} К продаже", "menu_sell")]], "menu.jpg")
        return

    # Доп. проверка номера перед сохранением (на случай некорректного ввода)
    clean = ''.join(c for c in str(number) if c.isdigit())
    if len(clean) != 11:
        context.user_data['sell_state'] = None
        await edit_message(update, context,
                           f"{E.ERROR} Номер должен содержать 11 цифр. Попробуйте снова.",
                           [[btn(f"{E.BACK} К продаже", "menu_sell")]], "menu.jpg")
        return

    nid = generate_id("NUM")
    numbers = load_json(DB_NUMBERS)
    numbers.append({
        "id": nid,
        "number": number,
        "price": price,
        "currency": currency,
        "seller_id": uid,
        "status": "active",
        "code_type": context.user_data.get('sell_code_type', 'sms'),
    })
    save_json(DB_NUMBERS, numbers)

    context.user_data['sell_state'] = None
    context.user_data.pop('temp_number', None)
    context.user_data.pop('temp_price', None)
    context.user_data.pop('sell_code_type', None)

    await edit_message(update, context,
                       f"{E.SUCCESS} Номер <code>{format_number(number)}</code> выставлен!\nЦена: {format_price(price, currency)}",
                       [[btn(f"{E.CATALOG} Мои номера", "menu_my_numbers"),
                         btn(f"{E.MENU} Главное меню", "start")]], "sellnumber.jpg")


# ============================================================
# МОИ НОМЕРА
# ============================================================

async def my_numbers_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    numbers = load_json(DB_NUMBERS)
    my_active = [n for n in numbers if n.get('seller_id') == uid and n.get('status') == 'active']
    my_deal = [n for n in numbers if n.get('seller_id') == uid and n.get('status') == 'in_deal']
    text = f"{E.CATALOG} <b>Мои номера</b>\n\nАктивных: {len(my_active)} | В сделке: {len(my_deal)}"
    rows = [
        [btn(f"🟢 Активные ({len(my_active)})", "my_nums_list_active"),
         btn(f"🤝 В сделке ({len(my_deal)})", "my_nums_list_deal")],
        [btn(f"{E.MENU} Главное меню", "start")],
    ]
    await edit_message(update, context, text, rows, "mynumber.jpg")


async def my_numbers_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mode = query.data.split("_")[-1]
    uid = query.from_user.id
    numbers = load_json(DB_NUMBERS)
    items = [n for n in numbers if n.get('seller_id') == uid and n.get('status') == mode]
    if not items:
        await edit_message(update, context, "Пусто.",
                           [[btn(f"{E.BACK} Назад", "menu_my_numbers")]], "menu.jpg")
        return
    rows = [[btn(f"{format_number(n['number'])} · {format_price(n['price'], n['currency'])}",
                 f"my_num_detail_{n['id']}")] for n in items]
    rows.append([btn(f"{E.BACK} Назад", "menu_my_numbers")])
    await edit_message(update, context, f"{E.CATALOG} Мои номера:", rows, "mynumber.jpg")


async def my_number_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nid = query.data.replace("my_num_detail_", "")
    numbers = load_json(DB_NUMBERS)
    n = next((x for x in numbers if x['id'] == nid), None)
    if not n:
        return
    text = (
        f"{E.PHONE} <b>{format_number(n['number'])}</b>\n\n"
        f"💰 {format_price(n['price'], n['currency'])}\n"
        f"Статус: {'🟢 Активен' if n['status'] == 'active' else '🤝 В сделке'}"
    )
    rows = []
    if n.get('status') == 'active':
        rows.append([btn(f"{E.CANCEL} Удалить", f"delete_number_{nid}")])
    rows.append([btn(f"{E.BACK} Назад", "menu_my_numbers")])
    await edit_message(update, context, text, rows, "mynumber.jpg")


async def delete_number_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nid = query.data.replace("delete_number_", "")
    uid = query.from_user.id
    numbers = load_json(DB_NUMBERS)
    before = len(numbers)
    numbers = [n for n in numbers if not (n['id'] == nid and n.get('seller_id') == uid)]
    if len(numbers) < before:
        save_json(DB_NUMBERS, numbers)
        await edit_message(update, context, f"{E.SUCCESS} Номер удалён.",
                           [[btn(f"{E.BACK} Назад", "menu_my_numbers")]], "menu.jpg")
    else:
        await query.answer("Номер не найден.", show_alert=True)


# ============================================================
# ТОП ДЕПОЗИТОВ
# ============================================================

async def top_deposits_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    users = load_json(DB_USERS)
    sellers = sorted(
        [{'id': uid, 'name': f"@{d.get('username', uid)}",
          'total': d.get('deposit_usd', 0.0) + d.get('deposit_kzt', 0.0) / get_rate()}
         for uid, d in users.items() if d.get('deposit_usd', 0) + d.get('deposit_kzt', 0) > 0],
        key=lambda x: x['total'], reverse=True
    )[:TOP_DEPOSITS_COUNT]

    if not sellers:
        await edit_message(update, context, f"{E.TOP} Депозитов пока нет.",
                           [[btn(f"{E.MENU} Главное меню", "start")]], "top.jpg")
        return

    lines = "\n".join(f"{i}. {s['name']} — <b>${s['total']:.2f}</b>" for i, s in enumerate(sellers, 1))
    text = f"{E.TOP} <b>Топ продавцов</b>\n\n{lines}"
    rows = [[btn(s['name'], f"top_seller_profile_{s['id']}")] for s in sellers]
    rows.append([btn(f"{E.MENU} Главное меню", "start")])
    await edit_message(update, context, text, rows, "top.jpg")


async def top_seller_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    seller_id = query.data.split("_")[-1]
    await view_seller_numbers(update, context, seller_id)


async def view_seller_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE, seller_id=None):
    if not seller_id:
        query = update.callback_query
        await query.answer()
        seller_id = query.data.replace("view_seller_numbers_", "")

    seller = get_user(int(seller_id))
    dep = seller.get('deposit_usd', 0.0) + seller.get('deposit_kzt', 0.0) / get_rate()
    uname = f"@{seller.get('username', seller_id)}"

    numbers = load_json(DB_NUMBERS)
    nums = [n for n in numbers if str(n.get('seller_id')) == str(seller_id) and n.get('status') == 'active']

    text = (
        f"👤 <b>{uname}</b>\n"
        f"{E.DEPOSIT} Гарантия: <b>${dep:.2f}</b>\n\n"
        f"📱 Номеров в продаже: {len(nums)}"
    )
    rows = [[btn(f"{format_number(n['number'])} · {format_price(n['price'], n['currency'])}",
                 f"buy_number_view_{n['id']}")] for n in nums[:10]]
    rows.append([btn(f"{E.BACK} Назад", "menu_buy")])
    await edit_message(update, context, text, rows, "profile.jpg")


async def seller_profile_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    seller_id = query.data.replace("seller_profile_", "")
    await view_seller_numbers(update, context, seller_id)


async def sellers_list_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    query = update.callback_query
    await query.answer()
    users = load_json(DB_USERS)
    sellers = [
        (uid, d) for uid, d in users.items()
        if d.get('deposit_usd', 0) + d.get('deposit_kzt', 0) > 0
    ]
    sellers.sort(key=lambda x: x[1].get('deposit_usd', 0), reverse=True)
    total_pages = max(1, math.ceil(len(sellers) / SELLERS_PER_PAGE))
    page = max(1, min(page, total_pages))
    start = (page - 1) * SELLERS_PER_PAGE
    items = sellers[start:start + SELLERS_PER_PAGE]

    text = f"👥 <b>Продавцы</b> (стр. {page}/{total_pages})"
    rows = [[btn(f"@{d.get('username', uid)} · ${d.get('deposit_usd', 0):.2f}", f"seller_profile_{uid}")] for uid, d in items]
    nav = []
    if page > 1:
        nav.append(btn("⬅️", f"sellers_list_page_{page - 1}"))
    if page < total_pages:
        nav.append(btn("➡️", f"sellers_list_page_{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([btn(f"{E.MENU} Главное меню", "start")])
    await edit_message(update, context, text, rows, "catalog.jpg")


# ============================================================
# АКТИВНЫЕ СДЕЛКИ
# ============================================================

async def check_active_deal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    from handlers.menu import start_command
    await start_command(update, context)
