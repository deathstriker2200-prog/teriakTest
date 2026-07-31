"""
گیت عضویت اجباری 🔒
توی گروه -3 رجیستر میشه (قبل از قفل مالکیت و همه دستورها) ولی فقط روی پی‌وی ربات
داخل گروه همه‌چی مثل قبل عادی کار می‌کنه و چک عضویت انجام نمیشه
کاربر عضو کانال نباشه دستور پی‌وی‌اش بلاک میشه و پیام گیت با دکمه‌های عضویت/تایید می‌گیره
آپدیت بلاک‌شده توی حافظه نگه داشته میشه تا بعد «تایید عضویت» خودشش ادامه پیدا کنه

پرفورمنس: خاموش = صفر کوئری و صفر تلگرام | روشن = کش ستینگ (TTL کوتاه) + کش عضویت کاربر
recheck رویدادمحوره (ChatMemberHandler) و فولبکش چک تنبل فقط موقع پیام خود کاربره
لفت رویدادی فوراً دسترسی رو قطع می‌کنه، پاکسازی اکانت با مهلت (جاب ساعتی) انجام میشه
"""

import logging
import time

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

import config
from keyboards import keyboards as kb
from services import forcejoin as fj

logger = logging.getLogger("teriaky.gate")

# user_id → آپدیت بلاک‌شده (هر نفر آخرین دستوری که بلاک شده)
PENDING: dict[int, Update] = {}
# user_id → timestamp آخرین پیام گیت (آنتی‌اسپم برای کالبک‌ها)
_LAST_GATE: dict[int, float] = {}


def _skip(update: Update) -> bool:
    u = update.effective_user
    return u is None or getattr(u, "is_bot", False) or u.id in config.ADMIN_IDS


def _in_pv(update: Update) -> bool:
    """گیت فقط توی پی‌وی ربات اعمال میشه، گروه‌ها آزادن"""
    chat = update.effective_chat
    return chat is not None and chat.type == "private"


async def _settings_and_member(context, user_id: int) -> tuple[dict, bool]:
    """
    اجازه عبور از گیت، پرترددترین مسیر رباته
    خاموش یا بدون کانال: هیچ session و تلگرامی نداره (ستینگ کش‌شده)
    روشن: جواب از کش حافظه عضویت یا ردیف تازه کاربره، تلگرام فقط بار اول/انقضا
    خروجی: (ستینگ، عضو؟)، ستینگ برای لینک دکمه پیام گیت لازمه
    """
    st = await fj.get_settings_cached()
    if not (st["on"] and st["channel"]):
        return st, True
    return st, await fj.resolve_member(context.bot, st["channel"], user_id)


async def gate_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """متن‌ها و کامندهای پی‌وی قبل از هر هندلری از اینجا رد میشن"""
    if _skip(update) or not _in_pv(update):
        return
    st, member = await _settings_and_member(context, update.effective_user.id)
    if member:
        return

    PENDING[update.effective_user.id] = update
    if update.message:
        await update.message.reply_html(fj.gate_text(), reply_markup=kb.force_join_kb(st["link"]))
    raise ApplicationHandlerStop()


async def gate_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌های پی‌وی هم گیت میشن (بجز خود دکمه تایید که هندلر جدا داره و زودتر رجیستر شده)"""
    if not update.callback_query or _skip(update) or not _in_pv(update):
        return
    st, member = await _settings_and_member(context, update.effective_user.id)
    if member:
        return

    uid = update.effective_user.id
    PENDING[uid] = update
    await update.callback_query.answer(
        "🔒 اول توی کانال عضو شو، بعد «✅ تایید عضویت» رو بزن", show_alert=True,
    )
    # پیام گیت با دکمه لینک فقط یه بار هر چند لحظه، که گروه اسپم نشه
    now = time.monotonic()
    if now - _LAST_GATE.get(uid, 0) > config.FORCE_JOIN_STALE_SECONDS:
        _LAST_GATE[uid] = now
        try:
            await context.bot.send_message(
                update.effective_chat.id, fj.gate_text(),
                parse_mode="HTML", reply_markup=kb.force_join_kb(st["link"]),
            )
        except Exception as e:
            logger.debug("فرستادن پیام گیت %s: %s", uid, e)
    raise ApplicationHandlerStop()


async def gate_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«✅ تایید عضویت»، اگه عضو شده باشه ادامه همون دستور بلاک‌شده اجرا میشه"""
    q = update.callback_query
    st = await fj.get_settings_cached()

    if not st["channel"]:
        await q.answer("عضویت اجباری غیرفعاله ✅")
        try:
            await q.edit_message_text("✅ عضویت اجباری خاموشه، دستورت رو دوباره بزن")
        except Exception:
            pass
        return

    member = True
    if st["on"]:
        # چک واقعی + ثبت وضعیت، تنها راه برگشت غیرعضوی بلاک‌شده‌ست
        member = await fj.membership_check(context.bot, st["channel"], update.effective_user.id)

    if not member:
        await q.answer("❌ هنوز عضو کانال نشدی، اول عضو شو بعد دوباره تایید رو بزن", show_alert=True)
        return

    await q.answer("✅ عضویتت تایید شد")
    try:
        await q.edit_message_text("✅ <b>عضویتت تایید شد، خوش اومدی</b> 🌹", parse_mode="HTML")
    except Exception:
        pass

    uid = update.effective_user.id
    pending_update = PENDING.pop(uid, None)
    if pending_update is None:
        return
    # ادامه همون دستوری که بلاک شده بود از نو دیسپچ میشه
    try:
        await context.application.process_update(pending_update)
    except Exception as e:
        logger.warning("ادامه دستور بلاک‌شده %s خطا: %s", uid, e)


# ───────── رویداد chat_member کانال (recheck رویدادمحور) ─────────

async def fj_member_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    خود تلگرام این آپدیت رو می‌فرسته وقتی وضعیت عضویت یه نفر تو کانال عوض بشه
    (ربات باید ادمین کانال باشه و run_polling با Update.ALL_TYPES اجرا بشه)
    لفت/کیک = فوراً غیرعضو و قطع دسترسی، حتی قبل از اینکه خودش پیام بده
    جوین = فوراً عضو و رفع گیت، polling اضافه‌ای رو هیچ پیامی نداریم
    """
    cm = update.chat_member
    if cm is None or cm.new_chat_member is None:
        return
    st = await fj.get_settings_cached()
    if not (st["on"] and st["channel"]):
        return
    if not fj.same_channel(st["channel"], cm.chat.id, getattr(cm.chat, "username", None)):
        return
    user = cm.new_chat_member.user
    if user is None or getattr(user, "is_bot", False):
        return
    status = getattr(cm.new_chat_member, "status", "")
    if status in ("member", "administrator", "creator"):
        await fj.mark_joined(user.id)
        logger.debug("عضویت اجباری: %s جوین شد، گیتش باز شد", user.id)
    else:  # left | kicked | restricted، دسترسی همین لحظه بسته میشه
        await fj.mark_left(user.id)
        logger.info("عضویت اجباری: %s لفت/کیک شد (%s)، دسترسیش قطع شد", user.id, status)
