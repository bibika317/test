"""
utils/finance.py — Финансовые операции: баланс, конвертация, списание, заморозка.
"""
from data.storage import get_rate


def convert_currency(amount, from_curr, to_curr):
    if from_curr == to_curr:
        return amount
    rate = get_rate()
    if from_curr == "KZT" and to_curr == "USD":
        return round(amount / rate, 2)
    elif from_curr == "USD" and to_curr == "KZT":
        return round(amount * rate, 2)
    return amount


def get_unified_balance(user) -> float:
    """Суммарный баланс в USD."""
    rate = get_rate()
    return round(user.get('balance_usd', 0.0) + (user.get('balance_kzt', 0.0) / rate), 2)


def get_unified_balance_kzt(user) -> float:
    """Суммарный баланс в KZT."""
    rate = get_rate()
    return round((user.get('balance_usd', 0.0) * rate) + user.get('balance_kzt', 0.0), 0)


def can_afford_price(user, price, currency) -> bool:
    """Проверяет, хватает ли средств."""
    required_usd = price if currency == "USD" else price / get_rate()
    return get_unified_balance(user) >= required_usd


def deduct_payment(user: dict, price: float, currency: str) -> dict:
    """
    Списывает средства. Сначала списывает в нужной валюте,
    при нехватке — конвертирует из другой.
    Возвращает обновлённый словарь пользователя.
    """
    rate = get_rate()
    bal_usd = user.get('balance_usd', 0.0)
    bal_kzt = user.get('balance_kzt', 0.0)

    if currency == "USD":
        if bal_usd >= price:
            user['balance_usd'] = round(bal_usd - price, 2)
        else:
            remaining_usd = price - bal_usd
            user['balance_usd'] = 0.0
            user['balance_kzt'] = round(bal_kzt - remaining_usd * rate, 0)
    else:  # KZT
        if bal_kzt >= price:
            user['balance_kzt'] = round(bal_kzt - price, 0)
        else:
            remaining_kzt = price - bal_kzt
            user['balance_kzt'] = 0.0
            user['balance_usd'] = round(bal_usd - remaining_kzt / rate, 2)
    return user


def refund_payment(user: dict, price: float, currency: str) -> dict:
    """Возвращает средства на баланс."""
    if currency == "USD":
        user['balance_usd'] = round(user.get('balance_usd', 0.0) + price, 2)
    else:
        user['balance_kzt'] = round(user.get('balance_kzt', 0.0) + price, 0)
    return user


def format_price(price, currency) -> str:
    if currency == "USD":
        return f"${price:.2f}"
    return f"{price:,.0f} ₸"


def get_total_users_balance(users: dict) -> dict:
    """
    Считает суммарный баланс всех пользователей.
    Используется в авто-отчёте для админа.
    """
    rate = get_rate()
    total_usd = 0.0
    total_kzt = 0.0
    total_deposit_usd = 0.0
    total_deposit_kzt = 0.0

    for uid, u in users.items():
        total_usd += u.get('balance_usd', 0.0)
        total_kzt += u.get('balance_kzt', 0.0)
        total_deposit_usd += u.get('deposit_usd', 0.0)
        total_deposit_kzt += u.get('deposit_kzt', 0.0)

    total_balance_in_usd = round(total_usd + total_kzt / rate, 2)
    total_deposit_in_usd = round(total_deposit_usd + total_deposit_kzt / rate, 2)

    return {
        "balance_usd": round(total_usd, 2),
        "balance_kzt": round(total_kzt, 0),
        "balance_total_usd": total_balance_in_usd,
        "deposit_usd": round(total_deposit_usd, 2),
        "deposit_kzt": round(total_deposit_kzt, 0),
        "deposit_total_usd": total_deposit_in_usd,
        "in_system_usd": round(total_balance_in_usd + total_deposit_in_usd, 2),
    }
