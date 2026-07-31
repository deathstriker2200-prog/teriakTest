"""
سوئیچ خاموش/روشن ربات 🔌

/botdown و /botup (فقط ادمین ربات) → خاموشی کلی، کاربرای عادی پیام مارک تعمیر می‌گیرن
/botoff و /boton (فقط ادمین همون گروه یا ادمین ربات) → خاموشی فقط یه گروه، سکوت محض
تو پی‌وی /boton و /botoff راهنما میدن که این دستورا مخصوص گروه‌ان
gate همه پیام‌ها و دکمه‌ها رو قبل از بقیه هندلرها چک می‌کنه
"""

import time as _time

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import ApplicationHandlerStop, ContextTypes

import config
from database import session_scope
from services import power as power_svc

# آخرین لحظه مارک تعمیر هر چت، که سیل پیام مارک تعمیر نشه
_MAINT_LAST: dict[int, float] = {}

# الرت دکمه‌ها HTML نمی‌فهمه، نسخه ساده متن تعمیر رو بهش میدیم
MAINTENANCE_PLAIN = config.MAINTENANCE_TEXT.replace("<b>", "").replace("</b>", "")


def _is_bot_admin(update: Update) -> bool:
    return bool(update.effective_user) and update.effective_user.id in config.ADMIN_IDS


async def _is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """ادمین یا سازنده همون گروه؟ ادمین ربات هم همه‌جا مجازه"""
    if _is_bot_admin(update):
        return True
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


# ───────── خاموشی کلی (/botdown و /botup) ─────────

async def botdown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_bot_admin(update):
        return
    async with session_scope() as s:
        await power_svc.set_down(s, True)
        await s.commit()
    await update.message.reply_html(
        "<b>🔧 ربات رفت رو حالت تعمیر</b>\n\n"
        "از الان به کاربرای عادی فقط پیام «در دست توسعه و تعمیره» داده میشه\n"
        "با /botup برش گردون"
    )


async def botup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_bot_admin(update):
        return
    async with session_scope() as s:
        await power_svc.set_down(s, False)
        await s.commit()
    await update.message.reply_html("<b>✅ ربات برگشت رو هوا</b>\n\nهمه چی مثل قبل کار می‌کنه 🚀")


# ───────── خاموشی یه گروه (/botoff و /boton) ─────────

async def botoff_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None or chat.type == ChatType.PRIVATE:
        return await update.message.reply_html(
            "<b>🔌 خاموش کردن تو گروه</b>\n\n"
            "این دستورات ویژه گروه هستن\n"
            "برای خاموش کردن ربات در گروه، همین دستور رو داخل خود گروه بزن"
        )
    if not await _is_group_admin(update, context):
        return await update.message.reply_html("❌ این دستور فقط توسط ادمین گروه قابل استفاده است")
    async with session_scope() as s:
        await power_svc.set_group_off(s, chat.id, True)
        await s.commit()
    await update.message.reply_html(
        "<b>🔌 ربات تو این گروه خاموش شد</b>\n\n"
        "به هیچ دستور و پیامی واکنش نمیدم تا دوباره روشنم کنی\n"
        "روشن کردن: /boton"
    )


async def boton_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None or chat.type == ChatType.PRIVATE:
        return await update.message.reply_html(
            "<b>🔌 روشن کردن تو گروه</b>\n\n"
            "این دستورات ویژه گروه هستن\n"
            "برای روشن کردن ربات در گروه، همین دستور رو داخل خود گروه بزن"
        )
    if not await _is_group_admin(update, context):
        return await update.message.reply_html("❌ این دستور فقط توسط ادمین گروه قابل استفاده است")
    async with session_scope() as s:
        await power_svc.set_group_off(s, chat.id, False)
        await s.commit()
    await update.message.reply_html("<b>✅ ربات تو این گروه دوباره روشن شد</b>\n\nبزن بریم 🚀")


# ───────── گیت خاموشی، قبل از همه هندلرها ─────────

async def power_gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    ۱) گروه خاموش → سکوت محض (خود /boton از این گیت رد نمیشه چون CommandHandler جدا ثبته
       ولی تلگرام آپدیتش رو هم به ما میده، پس اینجا اونو رد می‌کنیم تا هندلرش برسه)
    ۲) خاموشی کلی → کاربر عادی پیام تعمیر می‌گیره، دکمه‌اش هم الرت می‌گیره
    ادمین ربات از هر دو گیت رد میشه
    """
    chat = update.effective_chat
    user = update.effective_user

    # /boton و /botoff تو گروه خاموش باید برسن به هندلرشون
    msg = update.message
    text = (msg.text or "") if msg else ""
    if text.startswith(("/boton", "/botoff")):
        return

    async with session_scope() as s:
        if _is_bot_admin(update):
            await s.commit()  # ادمین همیشه رد میشه
            return
        down = await power_svc.is_down(s)
        goff = bool(chat) and chat.type != ChatType.PRIVATE and await power_svc.group_off(s, chat.id)
        await s.commit()

    if goff:
        # سکوت محض، فقط لودینگ دکمه قطع میشه
        if update.callback_query:
            try:
                await update.callback_query.answer()
            except Exception:
                pass
        raise ApplicationHandlerStop()

    if down:
        if update.callback_query:
            try:
                await update.callback_query.answer(MAINTENANCE_PLAIN, show_alert=True)
            except Exception:
                pass
        elif update.effective_message:
            # سیل پیام‌ تکراری، فقط چند ثانیه یه بار مارک تعمیر جواب میدیم
            cid = update.effective_chat.id if chat else 0
            now = _time.monotonic()
            if now - _MAINT_LAST.get(cid, 0.0) >= 8:
                _MAINT_LAST[cid] = now
                try:
                    await update.effective_message.reply_html(config.MAINTENANCE_TEXT)
                except Exception:
                    pass
        raise ApplicationHandlerStop()
