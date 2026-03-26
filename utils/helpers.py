"""
utils/helpers.py — Вспомогательные функции: клавиатуры, ID, форматирование.
"""
import os
import random
import string
import logging
import re
from telegram import InlineKeyboardMarkup, InputMediaPhoto, InputMediaAnimation, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)
_TG_EMOJI_RE = re.compile(r'<tg-emoji\s+emoji-id="([^"]+)">([^<]+)</tg-emoji>')


# ——— Клавиатуры ———

def _fast_mode() -> bool:
    return str(os.getenv("FAST_MODE", "")).strip().lower() in ("1", "true", "yes")


def btn(text: str, callback_data: str = None, url: str = None) -> dict:
    """Создаёт словарь кнопки."""
    icon_id = None
    if isinstance(text, str):
        # Если в тексте есть <tg-emoji>, используем его как icon_custom_emoji_id.
        m = _TG_EMOJI_RE.search(text)
        if m:
            icon_id = m.group(1)
            # Убираем сам тег из текста
            text = _TG_EMOJI_RE.sub("", text).strip()
    data = {"text": text}
    if callback_data:
        data["callback_data"] = callback_data
    if url:
        data["url"] = url
    if icon_id:
        data["icon_custom_emoji_id"] = icon_id
    return data


def kb(rows: list) -> InlineKeyboardMarkup:
    """
    Строит InlineKeyboardMarkup из списка строк.
    Каждая строка — список btn() или InlineKeyboardButton.
    """
    from telegram import InlineKeyboardButton
    inline = []
    for row in rows:
        r = []
        for b in row:
            if isinstance(b, dict):
                api_kwargs = {}
                if b.get("icon_custom_emoji_id"):
                    api_kwargs["icon_custom_emoji_id"] = b.get("icon_custom_emoji_id")
                if b.get("style"):
                    api_kwargs["style"] = b.get("style")
                r.append(InlineKeyboardButton(
                    text=b["text"],
                    callback_data=b.get("callback_data"),
                    url=b.get("url"),
                    api_kwargs=api_kwargs or None,
                ))
            elif isinstance(b, InlineKeyboardButton):
                r.append(b)
        inline.append(r)
    return InlineKeyboardMarkup(inline)


# ——— Форматирование ———

def format_number(number: str) -> str:
    clean = ''.join(c for c in number if c.isdigit())
    if len(clean) == 11 and clean.startswith('77'):
        return f"+{clean[0]} {clean[1:4]} {clean[4:7]} {clean[7:9]} {clean[9:11]}"
    return number if number.startswith('+') else f"+{clean}" if clean else number


def generate_id(prefix: str = "") -> str:
    return prefix + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


# ——— Отправка/редактирование сообщений ———

async def send_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              text: str, keyboard=None, media_name: str = "menu.jpg"):
    """Отправляет новое сообщение с фото."""
    _kb = keyboard if isinstance(keyboard, InlineKeyboardMarkup) else None
    if isinstance(keyboard, list):
        _kb = kb(keyboard)

    if _fast_mode():
        target = update.message or (update.callback_query.message if update.callback_query else None)
        if not target:
            return
        msg_obj = await target.reply_text(text, reply_markup=_kb, parse_mode="HTML")
        if msg_obj:
            context.user_data['last_bot_message_id'] = msg_obj.message_id
            context.user_data['last_media_name'] = None
        return msg_obj

    if not os.path.exists(media_name):
        media_name = "menu.jpg"

    msg_obj = None
    is_gif = media_name.lower().endswith('.gif')
    cached_id = _get_cached_media_id(context, media_name)
    try:
        target = update.message or (update.callback_query.message if update.callback_query else None)
        if not target:
            return
        if cached_id:
            if is_gif:
                msg_obj = await target.reply_animation(animation=cached_id, caption=text, reply_markup=_kb, parse_mode="HTML")
            else:
                msg_obj = await target.reply_photo(photo=cached_id, caption=text, reply_markup=_kb, parse_mode="HTML")
        else:
            with open(media_name, 'rb') as f:
                if is_gif:
                    msg_obj = await target.reply_animation(animation=f, caption=text, reply_markup=_kb, parse_mode="HTML")
                else:
                    msg_obj = await target.reply_photo(photo=f, caption=text, reply_markup=_kb, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка send_photo_message ({media_name}): {e}")
        target = update.message or (update.callback_query.message if update.callback_query else None)
        if target:
            msg_obj = await target.reply_text(text, reply_markup=_kb, parse_mode="HTML")

    if msg_obj:
        context.user_data['last_bot_message_id'] = msg_obj.message_id
        context.user_data['last_media_name'] = media_name
        _store_cached_media_id(context, media_name, msg_obj)
    return msg_obj


async def edit_message(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       text: str, keyboard=None, media_name: str = "menu.jpg"):
    """
    Редактирует текущее сообщение с медиа.
    Если редактирование не удаётся — удаляет старое и отправляет новое.
    """
    query = update.callback_query

    _kb = keyboard if isinstance(keyboard, InlineKeyboardMarkup) else None
    if isinstance(keyboard, list):
        _kb = kb(keyboard)

    if not query:
        await send_photo_message(update, context, text, _kb, media_name)
        return

    if _fast_mode():
        try:
            await query.edit_message_text(text=text, reply_markup=_kb, parse_mode="HTML")
            context.user_data['last_bot_message_id'] = query.message.message_id
            context.user_data['last_media_name'] = None
            return
        except Exception:
            pass

    if not os.path.exists(media_name):
        media_name = "menu.jpg"

    is_gif = media_name.lower().endswith('.gif')
    cached_id = _get_cached_media_id(context, media_name)

    # Быстрая правка подписи, если медиа не меняется
    if context.user_data.get('last_media_name') == media_name:
        try:
            await query.edit_message_caption(caption=text, reply_markup=_kb, parse_mode="HTML")
            context.user_data['last_bot_message_id'] = query.message.message_id
            context.user_data['last_media_name'] = media_name
            return
        except Exception:
            pass

    try:
        media_cls = InputMediaAnimation if is_gif else InputMediaPhoto
        if cached_id:
            await query.edit_message_media(
                media=media_cls(media=cached_id, caption=text, parse_mode="HTML"),
                reply_markup=_kb
            )
        else:
            with open(media_name, 'rb') as f:
                await query.edit_message_media(
                    media=media_cls(media=f, caption=text, parse_mode="HTML"),
                    reply_markup=_kb
                )
        context.user_data['last_bot_message_id'] = query.message.message_id
        context.user_data['last_media_name'] = media_name
        return
    except Exception:
        pass

    # Fallback: удаляем старое, шлём новое
    try:
        last_id = context.user_data.get('last_bot_message_id')
        if last_id:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=last_id)
    except Exception:
        pass

    await send_photo_message(update, context, text, _kb, media_name)


def _get_cached_media_id(context: ContextTypes.DEFAULT_TYPE, media_name: str):
    cache = context.bot_data.get("media_file_ids", {})
    return cache.get(media_name)


def _store_cached_media_id(context: ContextTypes.DEFAULT_TYPE, media_name: str, msg_obj):
    try:
        file_id = None
        if getattr(msg_obj, "photo", None):
            file_id = msg_obj.photo[-1].file_id
        elif getattr(msg_obj, "animation", None):
            file_id = msg_obj.animation.file_id
        if not file_id:
            return
        cache = context.bot_data.setdefault("media_file_ids", {})
        cache[media_name] = file_id
    except Exception:
        pass
