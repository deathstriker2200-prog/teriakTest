"""
سوئیچ خاموش/روشن ربات 🔌

/botdown و /botup (فقط ادمین ربات) → خاموشی کلی، کاربرای عادی پیام مارک تعمیر می‌گیرن
/botoff و /boton (فقط ادمین همون گروه یا ادمین ربات) → خاموشی فقط یه گروه، سکوت محض
تو پی‌وی /boton و /botoff راهنما میدن که این دستورا مخصوص گروه‌ان
gate همه پیام‌ها و دکمه‌ها رو قبل از بقیه هندلرها چک می‌کنه
"""

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import ApplicationHandlerStop, ContextTypes

import config
from database import session_scope
from services import power as power_svc
from utils import fa_dur, money

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


# ───────── گیت زندان لو دادن ⛓ (راند ۲۲) ─────────

async def jail_gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    زندانی لو دادن تا آخر زندانش هیچ دستور و دکمه‌ای نمی‌تونه بزنه
    (راند ۳۵: معافیت ادمین برداشته شد، درخواست کارفرما «همه راه‌ها بسته»)
    سبکه، هر چک کوئری نمیزنه و وضعیت با کش چندثانیه‌ای خونده میشه
    """
    user = update.effective_user
    if user is None:
        return
    # راند ۳۷ (درخواست کارفرما): گیت زندان فقط به دستورهای واقعی بازی واکنش نشون بده،
    # نه به هر پیام متنی معمولی تو گروه (چت عادی نباید الرت زندان بگیره)
    msg = update.effective_message
    if msg and getattr(msg, "text", None):
        from handlers.common import strip_bot_cmd
        stripped = strip_bot_cmd(msg.text).rstrip("!").strip()
        # تنها دستوری که زندانی می‌تونه بزنه «رشوه دادن» عه، وگرنه هیچ راه آزادی نمی‌مونه (راند ۲۸)
        if stripped == "رشوه دادن":
            return
        if not msg.text.startswith("/"):
            from handlers import _quick_pairs
            text = msg.text.strip()
            if not any(pat.match(text) for pat, _f in _quick_pairs()):
                return
    if update.callback_query and update.callback_query.data:
        # راند ۲۹: دکمه‌های تایید و لغو رشوه هم باید از گیت زندان رد شن
        if update.callback_query.data.startswith(("brcf:", "brcl:")):
            return
    from services import snitch as snitch_svc
    async with session_scope() as s:
        left = await snitch_svc.jail_left_tg(s, user.id)
        await s.commit()
    if left <= 0:
        return
    text = (
        f"⛓ زندانی هستی و تا {fa_dur(left)} دیگه نمی‌تونی این کارو انجام بدی\n"
        f"💰 با دستور «رشوه دادن» و پرداخت {money(config.BRIBE_COST)} همین الان آزاد شو"
    )
    if update.callback_query:
        try:
            await update.callback_query.answer(text, show_alert=True)
        except Exception:
            pass
    elif update.effective_message:
        try:
            await update.effective_message.reply_html(f"<b>{text}</b>")
        except Exception:
            pass
    raise ApplicationHandlerStop()


# ───────── خاموشی کلی (/botdown و /botup) ─────────

async def botdown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_bot_admin(update):
        return
    async with session_scope() as s:
        await power_svc.set_down(s, True)
        await s.commit()
    await update.message.reply_html(
        "<b>🔧 ربات رفت رو حالت تعمیر</b>\n\n"
        "از الان به جز ادمین به هیچ‌کس هیچ واکنشی نشون داده نمیشه (نه پیام نه الرت دکمه)\n"
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
        # راند ۳۲ (درخواست کارفرما): حالت تعمیر سکوت محضه، نه پیام نه الرت به غیرادمین
        # فقط لودینگ دکمه با یه answer خالی قطع میشه (الگوی «کاملاً بی‌جواب»)
        if update.callback_query:
            try:
                await update.callback_query.answer()
            except Exception:
                pass
        raise ApplicationHandlerStop()
