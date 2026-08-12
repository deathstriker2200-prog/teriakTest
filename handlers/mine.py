"""کنده‌کاری ⛏: بخش مستقل تو منوی اصلی + ابزار (تبر/کلنگ) + دراپ منابع
دستور متنی «کنده کاری» هم مستقیم ضربه می‌زنه"""

from datetime import timedelta

from telegram import Update
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import parts, respond
from keyboards import keyboards as kb
from services import resources as res_svc
from services import users
from utils import esc, fa_dur, fa_num, money, money_tp, now_utc


# ───────── متن‌ها ─────────

def mine_home_text(user) -> str:
    """صفحه اصلی کنده‌کاری، وضعیت ابزار و هزینه ارتقاشون هم همینجاست (بخش جدا نداره)"""
    lines = [
        "<b>⛏ کنده کاری</b>",
        "",
        "تی‌پوینت و تجربه می‌گیری",
        "شانسی چوب و آهن هم پیدا می‌کنی",
        "",
        f"🪵 چوب {fa_num(user.wood)} | ⛏️ آهن {fa_num(user.iron)}",
        "",
    ]
    for key, cfg in config.TOOLS.items():
        lv = user.axe_level if key == "axe" else user.pick_level
        lines.append(f"{cfg['emoji']} {cfg['name']} لول {fa_num(lv)}")
        if lv >= config.TOOL_MAX_LEVEL:
            lines.append("👑 لول مکس")
        else:
            tp, iron = res_svc.tool_upgrade_cost(key, lv)
            lines.append(f"⬆️ هزینه ارتقا: 💰 {money(tp)} + ⛏️ {fa_num(iron)} آهن")
    lines += [
        "",
        "هر لول ابزار چوب و آهن و تی‌پوینت بیشتری میده",
        "شانس پیدا کردن منابع کمیاب هم بیشتر میشه",
    ]
    return "\n".join(lines)


def _loot_text(loot: dict, user) -> str:
    lines = ["<b>⛏️ کنده‌کاری</b>", ""]
    if loot["rare"]:
        lines.append("<b>🎉 شکار کمیاب</b>")
        lines.append("")
    lines.append(f"<b>💰 {money(loot['cash'])} به دست آوردی</b>")
    if loot["wood"]:
        lines.append(f"<b>🪵 {fa_num(loot['wood'])} چوب دریافت کردی</b>")
    if loot["iron"]:
        lines.append(f"<b>⛏️ {fa_num(loot['iron'])} آهن دریافت کردی</b>")
    lines.append(f"<b>✨ {fa_num(loot['xp'])} تجربه گرفتی</b>")
    lines += [
        "",
        f"🪙 موجودی: {money(user.cash)}",
        "",
        f"خستت شده نیاز به {fa_num(config.MINE_COOLDOWN_SECONDS)}ثانیه استراحت داری برای کنده کاری بعدی",
    ]
    return "\n".join(lines)


def _tired_text(left: float) -> str:
    return (
        "<b>⛏️ کنده‌کاری</b>\n\n"
        f"خستت شده نیاز به {fa_dur(left)} استراحت داری برای کنده کاری بعدی"
    )


# ───────── ضربه ─────────

async def _do_roll(update: Update) -> None:
    # تو گروه فقط پیام نتیجه میره، منوی دکمه‌دار نمی‌فرسکارتل
    chat = update.effective_chat
    in_group = chat is not None and chat.type in ("group", "supergroup")
    kb_out = None if in_group else kb.mine_kb()

    dq_done, dq_left, uname = [], 0, ""
    notes: list[str] = []
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        now = now_utc()
        cooldown = timedelta(seconds=config.MINE_COOLDOWN_SECONDS)

        if user.last_mine_at and now - user.last_mine_at < cooldown:
            left = cooldown - (now - user.last_mine_at)
            text = _tired_text(left.total_seconds())
        else:
            loot = res_svc.mine_loot(user)
            user.cash += loot["cash"]
            got_w = res_svc.add_res(user, "wood", loot["wood"])
            got_i = res_svc.add_res(user, "iron", loot["iron"])
            loot["wood"], loot["iron"] = got_w, got_i
            user.last_mine_at = now
            from services import actionlog
            await actionlog.log(s, "mine")  # آمار کنده‌کاری‌های پنل ادمین
            from services import tracklog as tl
            await tl.bump_mine(s, user.id, loot["cash"], loot["xp"])  # لاگ ردیابی ادمین، فقط اگه طرف ترک‌شده باشه
            notes = users.add_xp(user, loot["xp"])
            from services import onboarding as onb
            chain = await onb.first_mine(s, user)  # جایزه و راهنمای اولین کنده‌کاری
            if chain:
                notes.insert(0, chain)
            congrats = await onb.maybe_congrats(s, user)  # تبریک پایان مأموریت شروع، فقط یه بار
            if congrats:
                notes.append(congrats)
            from services import teams as team_svc
            notes += await team_svc.add_team_xp(s, user, loot["xp"])
            tq = await team_svc.record_mine(s, user)  # کوئست روزانه کارتل، کنده‌کاری اعضا
            if tq:
                notes.append(tq)

            from services import quests as dq_svc
            dq_done, dq_left = await dq_svc.track(s, user, "mine")
            uname = users.display_name(user)

            text = _loot_text(loot, user)
        await s.commit()

    await respond(update, text, kb_out)
    # لول‌آپ به‌صورت پیام جدا میاد تا متن کنده‌کاری شلوغ نشه
    from handlers.common import announce_notes
    await announce_notes(update, notes)
    from handlers import dquests
    await dquests.announce_completed(update, uname, dq_done, dq_left)


async def mine_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«کنده کاری» متنی، مستقیم ضربه"""
    await _do_roll(update)


async def mine_home_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, alert: str | None = None) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        text = mine_home_text(user)
        await s.commit()
    await respond(update, text, kb.mine_kb(), alert=alert)


async def mine_roll_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _do_roll(update)


async def mine_tools_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, alert: str | None = None) -> None:
    """بخش وضعیت ابزار حذف شده، دکمه‌های قدیمی و دستور متنی آپگرید میان رو صفحه اصلی کنده‌کاری"""
    await mine_home_cb(update, context, alert=alert)


async def mine_upg_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tool_key = parts(update)[2]
    cfg = config.TOOLS.get(tool_key)
    if not cfg:
        return await mine_home_cb(update, context)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        lv = user.axe_level if tool_key == "axe" else user.pick_level
        cost = res_svc.tool_upgrade_cost(tool_key, lv)
        await s.commit()

    if cost is None:
        return await mine_home_cb(update, context)
    tp, iron = cost
    text = (
        f"<b>⬆️ ارتقای {esc(cfg['emoji'])} {esc(cfg['name'])}</b>\n\n"
        f"از لول {fa_num(lv)} به لول {fa_num(lv + 1)}\n"
        f"💸 تی‌پوینت {money(tp)}\n"
        f"⛏️ آهن {fa_num(iron)}\n\n"
        "انجامش بدیم؟"
    )
    await respond(update, text, kb.mine_up_confirm_kb(tool_key))


async def mine_upg_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tool_key = parts(update)[3]
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        lv = user.axe_level if tool_key == "axe" else user.pick_level
        cost = res_svc.tool_upgrade_cost(tool_key, lv) if tool_key in config.TOOLS else None
        if cost is None:
            alert = "👑 ابزارت لول مکسه"
        else:
            tp, iron = cost
            if user.cash < tp:
                alert = "❌ تی‌پوینتت کافی نیس"
            elif user.iron < iron:
                alert = f"⛏️ {fa_num(iron)} آهن می‌خواد و {fa_num(user.iron)} تا داری"
            else:
                user.cash -= tp
                user.iron -= iron
                if tool_key == "axe":
                    user.axe_level += 1
                else:
                    user.pick_level += 1
                alert = f"⬆️ {config.TOOLS[tool_key]['name']} رفت رو لول {fa_num(lv + 1)}"
        await s.commit()
    await mine_home_cb(update, context, alert=alert)


async def mine_upg_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await mine_home_cb(update, context)
