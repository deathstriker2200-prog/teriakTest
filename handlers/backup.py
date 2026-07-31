"""
بک‌آپ و ری‌استور دیتابیس، ری‌استور فقط ادمین (مثل /admin به غریبه اصلا جواب نمیده)
/backup و «تی کپی» → فایل کامل دی‌بی با اسم «تریاکی-تاریخ.db» میاد
«تی بکاپ» → منوی بک‌آپ (ساخت و آپلود) باز میشه
/upload_backup → فایل رو می‌گیره و اگه سالم بود جایگزین می‌کنه (روی ولوم ذخیره میشه)
بکاپ گرفتن تو پی‌وی برای همه آزاده، تو گروه فقط ادمینه
"""

import os
from datetime import datetime

from sqlalchemy import func, select
from telegram import Update
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import respond
from keyboards import keyboards as kb
from models import Team, User
from services import backup, users
from utils import fa_num

BACKUP_MENU_TEXT = (
    "<b>🗄 بکاپ تریاکی</b>\n\n"
    "با «ساخت بکاپ» یه فایل کامل از دیتابیس برات میاد تا همیشه یه نسخه دستت باشه\n"
    "با «آپلود بکاپ» اون فایل رو برمی‌گردونی و اطلاعات ریستور میشه\n\n"
    "یا اگه عجلت داری «تی کپی» بزن تا راست راست فایلش برسه"
)


def _is_admin(update: Update) -> bool:
    return bool(update.effective_user) and update.effective_user.id in config.ADMIN_IDS


def _backup_filename() -> str:
    """تریاکی-20260725-1430.db"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return f"{config.BACKUP_NAME}-{stamp}.db"



async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return  # سکوت محض

    if not backup.backup_supported():
        return await update.effective_message.reply_html(
            "❌ دیتابیس SQLite نیس، بک‌آپ فایلی فقط روی SQLite کار می‌کنه"
        )

    async with session_scope() as s:
        n_users = (await s.execute(select(func.count(User.id)))).scalar_one()
        n_teams = (await s.execute(select(func.count(Team.id)))).scalar_one()

    try:
        snapshot = await backup.create_snapshot()
    except FileNotFoundError:
        return await update.effective_message.reply_html("❌ فایل دیتابیس پیدا نشد")

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    caption = (
        f"💾 بک‌آپ کامل تریاکی\n"
        f"👥 {fa_num(n_users)} بازیکن | 🏴 {fa_num(n_teams)} تیم\n"
        f"🗓 {stamp}\n"
        f"برای برگردوندنش: /upload_backup بزن و همین فایل رو برگردون"
    )
    try:
        with open(snapshot, "rb") as f:
            await update.effective_message.reply_document(
                document=f,
                filename=_backup_filename(),
                caption=caption,
            )
    finally:
        os.remove(snapshot)


async def upload_backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return  # سکوت محض

    if not backup.backup_supported():
        return await update.effective_message.reply_html(
            "❌ دیتابیس SQLite نیس، بک‌آپ فایلی فقط روی SQLite کار می‌کنه"
        )

    context.user_data["await_backup"] = True
    await update.effective_message.reply_html(
        "<b>📤 آپلود بک‌آپ</b>\n\n"
        "فایل بک‌آپ رو همینجا بفرست (همون فایلی که /backup بهت داده)\n"
        "⚠️ اگه سالم باشه تمام اطلاعات فعلی ربات با اطلاعات فایل جایگزین میشه\n\n"
        "منصرف شدی بنویس «تریاکی لغو بک‌آپ»"
    )


async def cancel_upload_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«تریاکی لغو بک‌آپ»، کنسل کردن حالت انتظار فایل"""
    if not _is_admin(update):
        return
    if (context.user_data or {}).pop("await_backup", False):
        await update.effective_message.reply_html("😅 بی‌خیال آپلود بک‌آپ شدیم")


async def backup_doc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """گرفتن فایل بک‌آپ بعد از /upload_backup"""
    if not _is_admin(update):
        return
    if not (context.user_data or {}).pop("await_backup", False):
        return  # منتظر فایل نبودیم

    doc = update.effective_message.document
    if not doc:
        return await update.effective_message.reply_html("❌ فایل نفرستادی که ")

    if doc.file_size and doc.file_size > 25 * 1024 * 1024:
        return await update.effective_message.reply_html("❌ فایل خیلی گنده‌ست، دی‌بی این‌قدری نداریم")

    await update.effective_message.reply_html("⏳ دارم فایل رو بررسی می‌کنم...")

    try:
        tg_file = await doc.get_file()
        data = await tg_file.download_as_bytearray()
    except Exception:
        return await update.effective_message.reply_html("❌ دانلود فایل از تلگرام نشد، دوباره بفرست")

    ok, msg = await backup.restore_bytes(bytes(data))
    await update.effective_message.reply_html(f"<b>{msg}</b>")


# ───────── منوی بک‌آپ و «تی‌کپی» ─────────

async def backup_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«تی بکاپ»، باز کردن منوی بک‌آپ (آپلود فقط برای ادمین دیده میشه)"""
    await respond(update, BACKUP_MENU_TEXT, kb.backup_menu_kb(_is_admin(update)))


async def backup_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه بکاپ پنل ادمین، همون منو"""
    await respond(update, BACKUP_MENU_TEXT, kb.backup_menu_kb(_is_admin(update)))


async def _send_db_copy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ساخت اسنپ‌شات و فرستادن فایل، اگه ادمین داده باشه نسخه به پی‌وی بقیه اونرها هم میره"""
    if not backup.backup_supported():
        return await update.effective_message.reply_html(
            "❌ دیتابیس SQLite نیس، بک‌آپ فایلی فقط روی SQLite کار می‌کنه"
        )

    async with session_scope() as s:
        n_users = (await s.execute(select(func.count(User.id)))).scalar_one()
        n_teams = (await s.execute(select(func.count(Team.id)))).scalar_one()

    try:
        snapshot = await backup.create_snapshot()
    except FileNotFoundError:
        return await update.effective_message.reply_html("❌ فایل دیتابیس پیدا نشد")

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    caption = (
        f"💾 بک‌آپ کامل تریاکی\n"
        f"👥 {fa_num(n_users)} بازیکن | 🏴 {fa_num(n_teams)} تیم\n"
        f"🗓 {stamp}"
    )
    if _is_admin(update):
        caption += "\nبرای برگردوندنش: /upload_backup بزن و همین فایل رو برگردون"
    try:
        with open(snapshot, "rb") as f:
            data = f.read()
        filename = _backup_filename()
        await update.effective_message.reply_document(document=data, filename=filename, caption=caption)
        if _is_admin(update) and context is not None and getattr(context, "bot", None) is not None:
            sender = update.effective_user.id if update.effective_user else None
            for admin_id in config.ADMIN_IDS - {sender}:
                try:
                    await context.bot.send_document(chat_id=admin_id, document=data,
                                                    filename=filename, caption=caption)
                except Exception:
                    pass  # طرف ربات رو استارت نکرده، رد میشیم
    finally:
        os.remove(snapshot)


async def backup_copy_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«تی کپی»، ساخت فوری بک‌آپ و فرستادن فایلش، تو گروه فقط ادمینه"""
    chat_type = getattr(update.effective_chat, "type", "private")
    if chat_type != "private" and not _is_admin(update):
        return  # سکوت محض
    await _send_db_copy(update, context)


async def backup_make_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه «🗄 ساخت بکاپ» تو منوی بک‌آپ"""
    query = update.callback_query
    chat_type = getattr(update.effective_chat, "type", "private")
    if chat_type != "private" and not _is_admin(update):
        return await query.answer("❌ تو گروه فقط ادمین می‌تونه بکاپ بگیره", show_alert=True)
    await query.answer("⏳ داره آماده میشه...")
    await _send_db_copy(update, context)


async def backup_upload_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه «📤 آپلود بکاپ»، مثل /upload_backup حالت انتظار فایل روشن میشه"""
    query = update.callback_query
    if not _is_admin(update):
        return await query.answer("❌ آپلود بکاپ فقط دست ادمینه", show_alert=True)
    if not backup.backup_supported():
        return await query.answer("❌ بک‌آپ فایلی فقط روی SQLite کار می‌کنه", show_alert=True)
    await query.answer()
    context.user_data["await_backup"] = True
    await respond(
        update,
        "<b>📤 آپلود بکاپ</b>\n\n"
        "فایل بک‌آپ رو همینجا بفرست (همون فایلی که بات بهت داده)\n"
        "⚠️ اگه سالم باشه تمام اطلاعات فعلی ربات با اطلاعات فایل جایگزین میشه\n\n"
        "منصرف شدی بنویس «تریاکی لغو بک‌آپ»",
        kb.backup_menu_kb(True),
    )
