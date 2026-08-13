"""
نبرد HP گروهی ⚔️ + بخش درمان ❤️

دستورهای حمله (با و بدون پیشوند، فقط تو گروه): حمله | شلیک | بنگ | بنگ بنگ | پیو پیو | پیو
هدف: ریپلای روی پیام طرف یا نوشتن @یوزرنیم / آیدی عددی جلوی دستور
درمان: /heal یا «تی درمان»، آیتم مثل غذای سگ همون لحظه استفاده میشه
"""

import math

from telegram import Update
from telegram.constants import ChatType
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import respond, strip_bot_cmd
from keyboards import keyboards as kb
from services import battle, seen as seen_svc, users
from utils import esc, fa_dur, fa_num, money


# ───────── متن‌ها ─────────

ATTACK_GUIDE_TEXT = (
    "<b>⚔️ نبرد</b>\n\n"
    "روی پیام حریف ریپلای کن یا آیدی اون رو وارد کن و یکی از دستورهای حمله رو بفرست\n"
    "حمله | شلیک | بنگ | پیو"
)

NOT_FOUND_TEXT = (
    "🤷 اینو پیدا نکردم\n"
    "روی پیامش ریپلای کن یا آیدی عددی‌ش رو بفرست"
)

# راند ۳۷ (متن قطعی کارفرما): بلاک حمله با خشاب خالی
NO_AMMO_TEXT = (
    "🔫 تیرات تموم شد\n\n"
    "دیگه نمی‌تونی شلیک کنی 😵‍💫\n\n"
    "برای پر کردن خشاب و ادامه نبرد، از دستور «ریلود» استفاده کن"
)


def hit_text(result: dict, target_name: str) -> str:
    """متن ضربه موفق، غارت و تجربه همون لحظه پرداخت شدن"""
    text = (
        f"<b>💥 به حریف «{target_name}» حمله کردی</b>\n\n"
        f"🩸 {fa_num(result['dmg'])} دمیج وارد شد\n"
    )
    if result.get("crit"):
        text += "⚡ کریتیکال\n"
    text += f"❤️ سلامت حریف {fa_num(result['hp_now'])} از {fa_num(result['hp_max'])}\n\n"
    if result["steal"]:
        text += f"💰 {money(result['steal'])} غارت کردی\n"
    else:
        text += "💰 جیب حریف خالی بود\n"
    text += f"✨ {fa_num(result['xp'])} تجربه گرفتی"

    # خطوط قابلیت سلاح ویژه (💀 سم | 🔥 آخرکار | 🩸 مکش | 🌑 شب | 👑 رندوم)
    for line in result.get("abil_lines") or []:
        text += f"\n{line}"
    if result.get("poison_self"):
        text += "\n💀 خودت هم مسمومی، تا اثرش تموم شه حمله و دفاعت کمتره"
    _al30 = result.get("ammo_left")
    if _al30 is not None and _al30 >= 0:  # راند ۳۰: تیر مونده خشاب بعد شلیک
        _w30 = (config.WEAPONS.get(result.get("wkey") or "") or {}).get("name", "")
        text += f"\n🔫 {_w30}: {fa_num(_al30)} تیر مونده"

    if result.get("killed"):
        text += (
            f"\n\n<b>☠️ حریف «{target_name}» شکست خورد</b>\n\n"
            f"🏆 دوئل به پایان رسید"
        )

    return text


def nodmg_text(target_name: str) -> str:
    """زره حریف همه ضربه رو خنثی کرد"""
    return (
        f"🛡 حریف «{target_name}» برای تو زیادی قدرتمنده\n"
        "فعلاً نمی‌تونی بهش آسیبی بزنی\n"
        "اول تجهیزاتت رو ارتقا بده یا یه حریف ضعیف‌تر پیدا کن"
    )


def dead_self_text(left: int) -> str:
    mins = max(1, math.ceil(left / 60))
    return (
        "💀 هنوز حالت جا نیومده\n"
        f"{fa_num(mins)} دقیقه دیگه دوباره آماده نبرد میشی"
    )


def dead_target_text(name: str, left: int) -> str:
    mins = max(1, math.ceil(left / 60))
    return (
        f"💀 حریف «{name}» مرده و تا {fa_num(mins)} دقیقه دیگه زنده نمیشه\n"
        "یه هدف دیگه پیدا کن"
    )


# ───────── پیدا کردن هدف ─────────

async def _resolve_target(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    """
    هدف رو از ریپلای یا آرگومان دستور پیدا می‌کنه
    خروجی: (آبجکت شبه‌تلگرامی هدف, متن خطا یا None)
    فقط حضور طرف تو گروه کافیه، نیازی نیس ربات رو استارت کرده باشه
    """
    reply = update.message.reply_to_message
    if reply and getattr(reply, "from_user", None):
        return reply.from_user, None

    # آرگومان جلوی دستور (بعد از پاک کردن پیشوند تریاکی)
    text = strip_bot_cmd(update.message.text or "")
    words = text.split()
    arg = words[1].strip() if len(words) >= 2 else ""
    # دستور دوکلمه‌ای مثل «پیو پیو» یا «بنگ بنگ» آرگومان نداره
    if arg and arg.lower() in ("پیو", "بنگ", "حمله", "شلیک") and len(words) == 2:
        arg = ""
    if not arg:
        return None, ATTACK_GUIDE_TEXT

    if arg.lstrip("-").isdigit():
        tg_id = int(arg)
        row = None
    else:
        row = await seen_svc.find_by_username(session, arg)
        if not row:
            return None, NOT_FOUND_TEXT
        tg_id = row.telegram_id

    # حضورش تو همین گروه چک میشه (تنها شرط لازم برای حمله به غریبه)
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
        pass  # ربات دسترسی نداره یا تستیه، از رجیستری دیده‌شده‌ها استفاده می‌کنیم

    if row is None:
        from models import SeenUser
        row = await session.get(SeenUser, tg_id)
    if row is None:
        return None, NOT_FOUND_TEXT

    class _TG:
        __slots__ = ("id", "username", "first_name", "is_bot")

        def __init__(self, r):
            self.id = r.telegram_id
            self.username = r.username
            self.first_name = r.first_name
            self.is_bot = False

    return _TG(row), None


# ───────── دستور حمله (فقط گروه) ─────────

async def attack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    chat = update.effective_chat
    if chat is None or chat.type == ChatType.PRIVATE:
        # تو پی‌وی سیستم حمله کلاسیک جداست، لیست هدف رو نشون بده
        from handlers import attack as pv_attack_h
        return await pv_attack_h.pv_panel(update)

    tg_attacker = update.effective_user
    dq_done, dq_left, uname = [], 0, ""
    congrats = None

    async with session_scope() as s:
        tg_target, err = await _resolve_target(update, context, s)
        if err:
            return await respond(update, err, kb.home_kb() if err == ATTACK_GUIDE_TEXT else None)

        if getattr(tg_target, "is_bot", False):
            return await respond(update, "😅 ربات رو نمیشه زد")
        if tg_target.id == tg_attacker.id:
            return await respond(update, "😅 خودتو نزن رفیق")

        user, _ = await users.get_or_create(s, tg_attacker)
        users.apply_energy_regen(user)

        target, _ = await users.get_or_create(s, tg_target)  # پروفایل اولیه خودکار
        target_name = esc(users.display_name(target))

        result = {}
        if target.lb_hidden:
            err_hide = True  # نامرئی‌های /hideboard هدف حمله نمیشن، انگار وجود ندارن
        else:
            err_hide = False
            result = await battle.execute_hit(s, user, target)
            if result["ok"] and not result.get("nodmg"):
                from services import quests as dq_svc
                dq_done, dq_left = await dq_svc.track(s, user, "attack")
                uname = users.display_name(user)
                from services import onboarding as onb
                congrats = await onb.maybe_congrats(s, user)  # تبریک پایان مأموریت، فقط یه بار
        await s.commit()

    if err_hide:
        return await respond(update, NOT_FOUND_TEXT)

    if not result["ok"]:
        reason = result["reason"]
        if reason == "dead_self":
            return await respond(update, dead_self_text(result["left"]))
        if reason == "dead_target":
            return await respond(update, dead_target_text(target_name, result["left"]))
        if reason == "no_ammo":
            return await respond(update, NO_AMMO_TEXT)  # راند ۳۷: متن قطعی خشاب خالی
        if reason == "cooldown":
            return await respond(
                update, f"⏳ {fa_dur(result['left'])} دیگه می‌تونی حمله کنی"
            )
        if reason == "energy":
            return await respond(update, "⚡ انرژیت برای حمله کمه")
        return await respond(update, "😅 خودتو نزن رفیق")

    if result.get("nodmg"):
        extra = ""
        for line in result.get("armor_lines") or []:
            extra += f"\n{line}"
        return await respond(update, nodmg_text(target_name) + extra)

    await respond(update, hit_text(result, target_name))
    # لول‌آپ به‌صورت پیام جدا میاد
    from handlers.common import announce_notes
    notes_out = (result.get("notes") or []) + ([congrats] if congrats else [])
    await announce_notes(update, notes_out)
    from handlers import dquests
    await dquests.announce_completed(update, uname, dq_done, dq_left)


# ───────── بخش درمان ❤️ ─────────

def heal_home_text(hp_now: int, hp_max: int) -> str:
    """صفحه درمان، آیتم‌ها با قیمت و مقدار فقط روی دکمه‌ها میان"""
    return "\n".join([
        "<b>❤️ درمان</b>",
        "",
        "❤️ سلامت تو",
        f"{fa_num(hp_now)} از {fa_num(hp_max)}",
        "",
        "هر آیتم همون لحظه استفاده میشه و توی انبار ذخیره نمیشه",
    ])


HEAL_FULL_TEXT = (
    "❤️ سلامتت کامله\n"
    "فعلاً نیازی به درمان نداری"
)


async def render_heal(update: Update, alert: str | None = None) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        battle.revive_if_due(user)
        left = battle.dead_left(user)
        hp_now = None
        if left:
            text = dead_self_text(left)
        else:
            battle.ensure_hp(user)
            hp_now, hp_max = user.hp, battle.max_hp(user.level)
            if hp_now >= hp_max:
                text = HEAL_FULL_TEXT
            else:
                text = heal_home_text(hp_now, hp_max)
        await s.commit()

    if left or hp_now is None:
        return await respond(update, text, kb.home_kb(), alert=alert)
    if hp_now >= hp_max:
        return await respond(update, text, kb.home_kb(), alert=alert)
    await respond(update, text, kb.heal_kb(), alert=alert)


async def heal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/heal و «تی درمان»، هم PV هم گروه"""
    await render_heal(update)


async def heal_buy_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """خرید و استفاده همون لحظه آیتم درمان، مثل غذای سگ"""
    key = update.callback_query.data.split(":")[-1]
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, why, gain = battle.apply_heal(user, key)
        hp_now = user.hp
        await s.commit()

    if not ok:
        if why == "full":
            return await render_heal(update, alert=HEAL_FULL_TEXT.replace("\n", "، "))
        if why == "dead":
            return await render_heal(update, alert="💀 هنوز حالت جا نیومده")
        if why == "poor":
            return await render_heal(update, alert="💸 پولت برای این آیتم کمه")
        return await render_heal(update, alert="🤷 همچین آیتمی نداریم")

    await render_heal(update, alert=f"❤️ نوش جون، {fa_num(gain)} HP برگشت")
