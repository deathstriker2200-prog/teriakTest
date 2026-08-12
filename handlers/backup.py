"""
بک‌آپ و ری‌استور دیتابیس، ری‌استور فقط ادمین (مثل /admin به غریبه اصلا جواب نمیده)
/backup و «تی کپی» → فایل کامل دی‌بی میاد (SQLite: ‎.db | Postgres: دامپ فشرده ‎.sql.gz، راند ۳۳)
«تی بکاپ» → منوی بک‌آپ (ساخت و آپلود) باز میشه
/upload_backup → فایل رو می‌گیره و ری‌استور یکپارچه از روی محتوا نوعش رو تشخیص میده (لیترال .db یا دامپ .sql)
راند ۳۴: ترکیب Postgres زنده و فایل SQLite قدیمی، به‌جای ری‌استور، ادغام افزایشی رو تو پس‌زمینه اجرا می‌کنه
بکاپ گرفتن تو پی‌وی برای همه آزاده، تو گروه فقط ادمینه
"""

import asyncio
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




async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return  # سکوت محض

    if not backup.dump_supported():
        return await update.effective_message.reply_html(
            "❌ روی این دیتابیس بک‌آپ فایلی نداریم"
        )

    async with session_scope() as s:
        n_users = (await s.execute(select(func.count(User.id)))).scalar_one()
        n_teams = (await s.execute(select(func.count(Team.id)))).scalar_one()

    payload = await backup.make_upload_payload()
    if payload is None:
        return await update.effective_message.reply_html("❌ بک‌آپ ساخته نشد، لاگ رو ببین")
    data, filename = payload
    fmt = "📦 فرمت: فایل کامل SQLite (db)" if filename.endswith(".db") else "📦 فرمت: دامپ SQL فشرده Postgres (sql.gz)"

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    caption = (
        f"💾 بک‌آپ کامل تریاکی\n"
        f"👥 {fa_num(n_users)} بازیکن | 🏴 {fa_num(n_teams)} کارتل\n"
        f"{fmt}\n"
        f"🗓 {stamp}\n"
        f"برای برگردوندنش: /upload_backup بزن و همین فایل رو برگردون"
    )
    await update.effective_message.reply_document(document=data, filename=filename, caption=caption)


async def upload_backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return  # سکوت محض

    if not backup.dump_supported():
        return await update.effective_message.reply_html(
            "❌ روی این دیتابیس بک‌آپ فایلی نداریم"
        )

    context.user_data["await_backup"] = True
    await update.effective_message.reply_html(
        "<b>📤 آپلود بک‌آپ</b>\n\n"
        "فایل بک‌آپ رو همینجا بفرست (همون فایلی که /backup بهت داده، ‎.db یا ‎.sql.gz فرقی نداره)\n"
        "⚠️ اگه سالم باشه تمام اطلاعات فعلی ربات با اطلاعات فایل جایگزین میشه\n"
        "اگه دیتابیس ربات Postgres باشه و فایلت بک‌آپ قدیمی SQLite، به‌جای جایگزینی دیتاش با دیتابیس فعلی ادغام میشه\n\n"
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

    data = bytes(data)
    if backup.merge_needed(data):
        if backup.merge_running():
            return await update.effective_message.reply_html("❌ یه ادغام دیگه الان تو حال اجراست، اول اون تموم شه")
        chat_id = update.effective_chat.id if update.effective_chat else update.effective_user.id
        bot = context.bot

        async def _notify_merge(text: str) -> None:
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            except Exception:
                pass  # چت ادمین در دسترس نبود، خلاصه تو لاگ میمونه

        await update.effective_message.reply_html(
            "<b>⏳ ادغام فایل قدیمی شروع شد</b>\n\n"
            "دیتابیس زنده Postgres ـه و فایلت SQLite قدیمیه، پس به‌جای جایگزینی، دیتاش داره با دیتابیس فعلی ادغام میشه (چیزی پاک نمیشه)\n"
            "ممکنه چند دقیقه طول بکشه، وقتی تموم شد خلاصه‌ش رو همینجا میفرستم"
        )
        asyncio.create_task(backup.merge_sqlite_bytes(data, notify=_notify_merge))
        return

    ok, msg = await backup.restore_bytes(data)
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
    if not backup.dump_supported():
        return await update.effective_message.reply_html(
            "❌ روی این دیتابیس بک‌آپ فایلی نداریم"
        )

    async with session_scope() as s:
        n_users = (await s.execute(select(func.count(User.id)))).scalar_one()
        n_teams = (await s.execute(select(func.count(Team.id)))).scalar_one()

    payload = await backup.make_upload_payload()
    if payload is None:
        return await update.effective_message.reply_html("❌ بک‌آپ ساخته نشد، لاگ رو ببین")
    data, filename = payload
    fmt = "📦 فرمت: فایل کامل SQLite (db)" if filename.endswith(".db") else "📦 فرمت: دامپ SQL فشرده Postgres (sql.gz)"

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    caption = (
        f"💾 بک‌آپ کامل تریاکی\n"
        f"👥 {fa_num(n_users)} بازیکن | 🏴 {fa_num(n_teams)} کارتل\n"
        f"{fmt}\n"
        f"🗓 {stamp}"
    )
    if _is_admin(update):
        caption += "\nبرای برگردوندنش: /upload_backup بزن و همین فایل رو برگردون"
    await update.effective_message.reply_document(document=data, filename=filename, caption=caption)
    if _is_admin(update) and context is not None and getattr(context, "bot", None) is not None:
        sender = update.effective_user.id if update.effective_user else None
        for admin_id in config.ADMIN_IDS - {sender}:
            try:
                await context.bot.send_document(chat_id=admin_id, document=data,
                                                filename=filename, caption=caption)
            except Exception:
                pass  # طرف ربات رو استارت نکرده، رد میشیم


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
    if not backup.dump_supported():
        return await query.answer("❌ روی این دیتابیس بک‌آپ نداریم", show_alert=True)
    await query.answer()
    context.user_data["await_backup"] = True
    await respond(
        update,
        "<b>📤 آپلود بکاپ</b>\n\n"
        "فایل بک‌آپ رو همینجا بفرست (همون فایلی که بات بهت داده، ‎.db یا ‎.sql.gz فرقی نداره)\n"
        "⚠️ اگه سالم باشه تمام اطلاعات فعلی ربات با اطلاعات فایل جایگزین میشه\n"
        "اگه دیتابیس ربات Postgres باشه و فایلت بک‌آپ قدیمی SQLite، به‌جای جایگزینی دیتاش با دیتابیس فعلی ادغام میشه\n\n"
        "منصرف شدی بنویس «تریاکی لغو بک‌آپ»",
        kb.backup_menu_kb(True),
    )
