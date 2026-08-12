"""
دستور «لو دادن» 🚨 (راند ۲۲، درخواست کارفرما، فقط گروه)

شکل‌ها: ریپلای روی پیام طرف + «لو دادن» | «لو دادن @یوزرنیم» | «لو دادن ۱۲۳۴۵۶»
هدف مثل حمله پیدا میشه و منطقش تو services/snitch.py عه
راند ۳۵ (متن‌های قطعی کارفرما): کارت یورش پلیس + پی‌وی دستگیری + اعلان لقب «چاپلوس» تو همون گروه
"""

from telegram import Update
from telegram.constants import ChatType
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import respond, strip_bot_cmd
from keyboards import keyboards as kb
from services import seen as seen_svc, snitch as snitch_svc, users
from utils import esc, fa_dur, fa_num, money

SNITCH_GUIDE_TEXT = (
    "<b>🚨 لو دادن</b>\n\n"
    "روی پیام طرف ریپلای کن و بنویس «لو دادن»\n"
    "یا یوزرنیمش رو بگو: «لو دادن @user»\n"
    "یا آیدی عددیش رو: «لو دادن 123456»"
)

SNITCH_NOT_FOUND_TEXT = (
    "🤷 اینو پیدا نکردم\n"
    "روی پیامش ریپلای کن یا آیدی عددی‌ش رو بفرست"
)


async def _dm(context, tg: int | None, text: str) -> None:
    """پی‌وی خبر به کاربر، بلاک‌کرده یا استارت‌نکرده بی‌خیال"""
    if not tg:
        return
    bot = getattr(context, "bot", None)
    if bot is None:
        return
    try:
        await bot.send_message(tg, text, parse_mode="HTML")
    except Exception:
        pass


async def _resolve_target(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    """هدف لو دادن از ریپلای یا آرگومان دستور، مثل حمله (ریجیستری دیده‌شده‌ها فالبکه)"""
    reply = getattr(update.message, "reply_to_message", None)
    if reply and getattr(reply, "from_user", None):
        return reply.from_user, None

    text = strip_bot_cmd(update.message.text or "")
    words = text.split()
    arg = words[2].strip() if len(words) >= 3 else ""
    if not arg:
        return None, SNITCH_GUIDE_TEXT

    if arg.lstrip("-").isdigit():
        tg_id = int(arg)
        row = None
    else:
        row = await seen_svc.find_by_username(session, arg)
        if not row:
            return None, SNITCH_NOT_FOUND_TEXT
        tg_id = row.telegram_id

    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, tg_id)
        status = getattr(member, "status", "member")
        if str(status) in ("kicked", "left", "ChatMemberStatus.LEFT", "ChatMemberStatus.KICKED"):
            return None, "🤷 طرف تو این گروه نیس"
        u = getattr(member, "user", None)
        if u is not None:
            return u, None
    except BadRequest:
        return None, "🤷 طرف تو این گروه نیس"
    except Exception:
        pass  # دسترسی نداریم یا تستیه، از رجیستری استفاده می‌کنیم

    if row is None:
        from models import SeenUser
        row = await session.get(SeenUser, tg_id)
    if row is None:
        return None, SNITCH_NOT_FOUND_TEXT

    class _TG:
        __slots__ = ("id", "username", "first_name", "is_bot")

        def __init__(self, r):
            self.id = r.telegram_id
            self.username = r.username
            self.first_name = r.first_name
            self.is_bot = False

    return _TG(row), None


async def snitch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    chat = update.effective_chat
    if chat is None or chat.type == ChatType.PRIVATE:
        return await respond(update, "🚨 لو دادن فقط تو گروه‌ها کار می‌کنه، طرفو بیار تو گروه بعد لوش بده")

    async with session_scope() as s:
        me, _ = await users.get_or_create(s, update.effective_user)
        tg_target, err = await _resolve_target(update, context, s)
        if err:
            return await respond(update, err)
        if tg_target.id == me.telegram_id:
            return await respond(update, "🐀 رو خودت که نمی‌تونی لو بدی، برو بهت بار بگیره")
        left = snitch_svc.cooldown_left(me)
        if left:
            return await respond(
                update,
                f"⏳ تازه یه نفر رو لو دادی، هر {fa_dur(config.SNITCH_COOLDOWN_SECONDS)} فقط یه بار می‌تونی\n"
                f"{fa_dur(left)} دیگه آزاد میشی",
            )
        target = await users.get_by_tg(s, tg_target.id)
        if target is None:
            return await respond(update, "🤷 طرف هنوز ربات رو استارت نکرده و انباری نداره که پلیس بره توش")
        res = await snitch_svc.snitch(s, me, target)
        src_tg, src_name = me.telegram_id, users.display_name(me)
        tgt_tg, tgt_name = target.telegram_id, users.display_name(target)
        await s.commit()


    items = "، ".join(res["names"])
    src_men = f'<a href="tg://user?id={src_tg}">{esc(src_name)}</a>'
    tgt_men = f'<a href="tg://user?id={tgt_tg}">{esc(tgt_name)}</a>'

    if res["status"] == "empty":
        await respond(
            update,
            f"🚔 پلیس رفت سراغ انبار {tgt_men} ولی محصولی پیدا نکرد، دست خالی برگشت\n\n"
            f"لو دادنت سوخت، {fa_dur(config.SNITCH_COOLDOWN_SECONDS)} دیگه می‌تونی یکی دیگه رو لو بدی\n"
            "ولی همین تلاشم تو شمارش هفتگی لقب چاپلوس حسابه",
        )
    else:
        # کارت یورش پلیس (راند ۳۵، متن قطعی کارفرما)
        await respond(
            update,
            f"""🚨 {src_men} یکی رو لو داد

🚔 پلیس به انبار {tgt_men} یورش برد و تمام محصولاتش توقیف شد

🌾 اقلام توقیفی: {esc(items)}

💰 پاداش لو‌دهنده: {money(res["share"])}
🎁 پاداش ثابت: {money(res["bonus"])}

⛓ متاسفانه {tgt_men} به مدت {fa_num(config.SNITCH_JAIL_MINUTES)} دقیقه زندانی شد و تا پایان این زمان قادر به انجام هیچ کاری نیست""",
        )

        # پی‌وی به دستگیرشده (راند ۳۵، متن قطعی کارفرما)
        dm = f"""🚔 دستگیر شدی

📢 گزارشی از طرف {src_men} به پلیس رسید و نیروها به مخفیگاهت یورش بردند

📦 بخشی از محصولاتت توقیف شد و تو به مدت {fa_num(config.SNITCH_JAIL_MINUTES)} دقیقه زندانی شدی

⛓ تا پایان این زمان هیچ فعالیتی نمی‌توانی انجام دهی

💸 اگر عجله داری، با دستور «رشوه دادن» می‌توانی با پرداخت رشوه زودتر آزاد شوی"""
        await _dm(context, tgt_tg, dm)

    # راند ۳۵ (درخواست کارفرما): اعلام لقب چاپلوس فقط تو همون گروهی که لو دادنش رو کرده (آخرین فعالیتش)
    if res["khaye"]:
        announce = f"""📢 اهالی محله، {src_men} تو این هفته {fa_num(config.SNITCH_WEEK_LIMIT)} نفر رو لو داده

🏷 لقب «چاپلوس» براش {fa_num(config.KHAYE_TITLE_HOURS)} ساعت فعال شد

📉 فروش: {fa_num(int(config.KHAYE_SELL_MALUS * 100))}% کمتر
🏭 سرعت شرکت‌ها: {fa_num(int(config.KHAYE_COMPANY_SLOW * 100))}% کمتر"""
        await respond(update, announce)


async def bribe_text_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«رشوه دادن» (پیشوند دلخواه)، راند ۲۹: اول کارت تایید میاد بعد پرداخت انجام میشه"""
    if not update.message or not update.effective_user:
        return
    async with session_scope() as s:
        me, _ = await users.get_or_create(s, update.effective_user)
        left = snitch_svc.jail_left(me)
        cash = me.cash or 0
        await s.commit()
    if not left:
        return await respond(update, "🤷 تو که زندانی نیستی، این رشوه رو نگه دار به کارت میاد")
    if cash < config.BRIBE_COST:
        return await respond(
            update,
            f"💸 رشوه {money(config.BRIBE_COST)} میشه ولی نقدت کمتر از اینه\n"
            f"پول نداری که نداری، باید همون {fa_dur(left)} دیگه تو زندان بمونی",
        )
    await respond(
        update,
        "<b>💰 رشوه به پلیس</b>\n\n"
        f"🚔 {fa_dur(left)} از حبست مونده\n"
        f"💸 رشوه آزادی: {money(config.BRIBE_COST)}\n"
        f"💵 نقدینگیت: {money(cash)}\n\n"
        "پرداخت می‌کنی؟",
        kb.bribe_confirm_kb(update.effective_user.id),
    )


async def bribe_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """اجرای رشوه بعد از تایید (راند ۲۹)، فقط خودِ زندانی"""
    owner_id = update.callback_query.data.split(":")[1]
    if update.effective_user.id != int(owner_id):
        await update.callback_query.answer()  # غریبه هیچ واکنشی نمی‌بینه
        return
    async with session_scope() as s:
        me, _ = await users.get_or_create(s, update.effective_user)
        res = await snitch_svc.bribe(s, me)
        await s.commit()
    q = update.callback_query
    if res["status"] == "free":
        await q.answer("🤷 زندانی که نیستی", show_alert=True)
        return
    if res["status"] == "broke":
        await q.answer(f"💸 پولت به {money(config.BRIBE_COST)} رشوه نمیرسه", show_alert=True)
        return
    await q.answer()
    await respond(
        update,
        f"""<b>💰 رشوه رو گرفت</b>

پلیس {money(res["cost"])} گرفت و دستتو ول کرد
آزادی، ولی مراقب باش دوباره لوت ندن""",
    )


async def bribe_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لغو رشوه، زندانی تو حبس می‌مونه"""
    owner_id = update.callback_query.data.split(":")[1]
    if update.effective_user.id != int(owner_id):
        await update.callback_query.answer()
        return
    await update.callback_query.answer("❌ لغو شد")
    await respond(update, "❌ رشوه رو لغو کردی، پس همون تو زندان می‌مونی")

