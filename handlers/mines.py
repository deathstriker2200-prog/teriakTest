# -*- coding: utf-8 -*-
"""
💣 بازی مین | هندلرها (راند ۲۸، درخواست کارفرما، جایگزین قمار تاسی حذف‌شده)

«تریاکی قمارخانه» / «تریاکی قمار» → هاب و قوانین + انتخاب میز
«تریاکی مین 5000» → شروع مستقیم میز با اون شرط
دکمه‌ها: mn:h هاب | mn:b:<bet> شروع | mn:p:<i> انتخاب خونه | mn:c برداشت | mn:x لغو | mn:noop
میز توسط صاحبش کنترل میشه، کلیک غریبه ساکت جواب می‌گیره (رکوردها با telegram_id کلید خوردن)
"""

from telegram import Update
from telegram.ext import ContextTypes

import config
import keyboards.keyboards as kb
from database import session_scope
from handlers.common import chat_id_of, respond, strip_bot_cmd
from services import mines as mines_svc, users
from utils import fa_dur, fa_num, money, now_utc

SAFE_TOTAL = 8  # تعداد خونه‌های امن میز ۹ تایی


# ───────── متن‌ها ─────────

def _rules_lines() -> str:
    """جدول پله‌های ضریب از روی کانفیگ، ارقام لاتین"""
    return "\n".join(
        f"بعد از {fa_num(i)} خونه امن: ×{m:g}"
        for i, m in enumerate(config.MINES_MULTS, 1)
    )


def hub_text(cash: int) -> str:
    return (
        "<b>🎰 قمارخانه | 💣 بازی مین</b>\n\n"
        f"💵 نقدت: {money(cash)}\n\n"
        f"تو میز {fa_num(9)} خونه‌ای دقیقا یه مین خوابیده\n"
        "هر خونه‌ای که بزنی مین نباشه ضریب برداشتت یه پله میره بالا\n"
        "هر وقت خواستی «برداشت» رو بزن و پولت رو قطعی کن\n"
        "ولی اگه مین رو بزنی شرطت می‌سوزه 💥\n\n"
        f"{_rules_lines()}\n"
        f"هر {fa_num(SAFE_TOTAL)} خونه امن رو روشن کنی خودکار ×{config.MINES_MULTS[-1]:g} برات واریز میشه 🏆\n\n"
        f"⏱ هر میز {fa_dur(config.MINES_TTL_SECONDS)} مهلت داره، بگذره شرطت کامل برمی‌گرده"
    )


def board_text(g: dict) -> str:
    """متن میز دست جاری"""
    safe, bet = g["safe"], g["bet"]
    left = max(0, int((g["expires_at"] - now_utc()).total_seconds()))
    lines = [
        f"<b>💣 مین رو نزن! | میز {money(bet)}</b>",
        "",
        f"✅ خونه‌های امن: {fa_num(safe)} از {fa_num(SAFE_TOTAL)}",
    ]
    if safe >= 1:
        lines.append(
            f"🔥 ضریب فعلی: {mines_svc.mult_label(safe)} | برداشت: {money(mines_svc.payout_at(bet, safe))}"
        )
    else:
        lines.append("اولین خونه رو بزن ببین شانس با کیه")
    lines.append(f"⏱ {fa_dur(left)} دیگه میزت منقضی میشه و شرطت برمی‌گرده")
    return "\n".join(lines)


def result_text(res: dict) -> str:
    """متن نتیجه بسته‌شدن دست"""
    st = res["status"]
    if st == "boom":
        return (
            "<b>💥 بوم!</b>\n\n"
            f"مین رو زدی و شرط {money(res['bet'])} سوخت\n"
            f"تونستی {fa_num(res['safe'])} خونه امن پیدا کنی\n"
            f"💵 نقدت: {money(res['cash'])}"
        )
    if st == "auto":
        return (
            "<b>🏆 تمیزکاری کامل!</b>\n\n"
            f"هر {fa_num(SAFE_TOTAL)} خونه امن رو پیدا کردی و ضریب ×{config.MINES_MULTS[-1]:g} خودکار زده شد\n"
            f"💰 {money(res['payout'])} واریز شد (خالص {money(res['net'])} برد)\n"
            f"💵 نقدت: {money(res['cash'])}"
        )
    # cashout
    return (
        "<b>💰 برداشت کردی</b>\n\n"
        f"{fa_num(res['safe'])} خونه امن با ضریب ×{res['payout'] / res['bet']:g} یعنی {money(res['payout'])}\n"
        f"خالص برد: {money(res['net'])}\n"
        f"💵 نقدت: {money(res['cash'])}"
    )


# ───────── خطاهای شروع میز ─────────

def _arm_err(code: str, cd_left: int) -> str:
    return {
        "locked": f"🔒 قمارخانه از لول {fa_num(config.MINES_MIN_LEVEL)} باز میشه",
        "bad_bet": "🤷 همچین میز شرطی نداریم",
        "busy": "💣 یه میز باز داری، همون رو اول تموم کن یا لغوش کن",
        "cd": f"⏳ دستت تازه تموم شده، {fa_dur(cd_left)} دیگه می‌تونی دوباره بازی کنی",
        "poor": "💸 نقدت برای این میز کمه، یه میز ارزون‌تر بخوابون",
    }.get(code, "❌ نشد")


def _parse_bet(text: str) -> int | None:
    """عدد شرط ته دستور «تریاکی مین 5000»، نامعتبر یا خالی = None"""
    words = strip_bot_cmd(text or "").split()
    if len(words) < 2:
        return None
    raw = words[1].replace(",", "").replace("٬", "")
    return int(raw) if raw.isdigit() else None


# ───────── شروع میز (مشترک دکمه و دستور متنی) ─────────

async def _arm(update: Update, bet: int) -> None:
    q = update.callback_query
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, code = await mines_svc.arm(s, user, bet)
        cd_left = 0
        if ok:
            msg_id = getattr(q.message, "message_id", None) if q else None
            mines_svc.bind_chat(user.telegram_id, chat_id_of(update), msg_id)
            g = dict(mines_svc.get(user.telegram_id))
            g["revealed"] = set(g["revealed"])
            await s.commit()
        else:
            cd_left = mines_svc.cooldown_left(user)
            await s.commit()

    if not ok:
        if q:
            await q.answer(_arm_err(code, cd_left), show_alert=True)
            return
        return await respond(update, _arm_err(code, cd_left))

    await respond(
        update, board_text(g),
        kb.mines_board_kb(g["revealed"], g["safe"], 0),
    )


# ───────── دستورها ─────────

async def mines_hub_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«تریاکی قمارخانه» | «تریاکی قمار» → قوانین + انتخاب میز شرط"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        level, cash, left = user.level, user.cash, mines_svc.cooldown_left(user)
        await s.commit()
    if level < config.MINES_MIN_LEVEL:
        return await respond(update, f"🔒 قمارخانه از لول {fa_num(config.MINES_MIN_LEVEL)} باز میشه")
    text = hub_text(cash)
    if left > 0:
        text += f"\n\n⏳ {fa_dur(left)} دیگه می‌تونی میز بعدی رو بخوابونی"
    await respond(update, text, kb.mines_bets_kb())


async def mines_text_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«تریاکی مین 5000» → شروع مستقیم، بدون عدد مثل هاب رفتار می‌کنه"""
    if not update.message:
        return
    bet = _parse_bet(update.message.text or "")
    if bet is None:
        return await mines_hub_cmd(update, context)
    await _arm(update, bet)


# ───────── دکمه‌ها ─────────

async def mines_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    data = q.data or ""
    parts = data.split(":")

    if data == "mn:noop":
        return await q.answer()

    if data == "mn:h":
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            level, cash, left = user.level, user.cash, mines_svc.cooldown_left(user)
            await s.commit()
        if level < config.MINES_MIN_LEVEL:
            return await q.answer(f"🔒 قمارخانه از لول {fa_num(config.MINES_MIN_LEVEL)} باز میشه", show_alert=True)
        text = hub_text(cash)
        if left > 0:
            text += f"\n\n⏳ {fa_dur(left)} دیگه می‌تونی میز بعدی رو بخوابونی"
        return await respond(update, text, kb.mines_bets_kb())

    if len(parts) == 3 and parts[1] == "b":
        if not parts[2].isdigit():
            return await q.answer()
        return await _arm(update, int(parts[2]))

    # اکشن‌های دست جاری: p:<i> | c | x
    action = parts[1] if len(parts) > 1 else ""
    if action not in ("p", "c", "x"):
        return await q.answer()
    idx = None
    if action == "p":
        if len(parts) < 3 or not parts[2].isdigit():
            return await q.answer()
        idx = int(parts[2])

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        g = mines_svc.get(user.telegram_id)
        if g is None:
            await s.commit()
            return await q.answer()
        # کلیک فقط روی پیام خودش (the board bound at arm) با ارزشه، کلیک غریبه ساکته
        bound_mid = g.get("msg_id")
        q_mid = getattr(q.message, "message_id", None)
        if bound_mid is not None and q_mid is not None and bound_mid != q_mid:
            await s.commit()
            return await q.answer()

        res = None
        if action == "p":
            res = await mines_svc.pick(s, user, idx)
        elif action == "c":
            res = await mines_svc.cashout(s, user)
        else:
            res = await mines_svc.cancel(s, user)

        # رکورد میز بعد از بستن دست از MINES پاک میشه ولی خود آبجکت حیات داره و
        # revealed/bomb اش برای میز کامل‌نمای نتیجه لازمه
        board = dict(g)
        board["revealed"] = set(board["revealed"])
        await s.commit()

    if res is None:
        return await q.answer()

    if res.get("expired"):
        return await respond(update, f"⌛ مهلت میزت تموم شده بود، شرط {money(res['bet'])} کامل برگشت جیبت")

    if res.get("status") == "late":
        return await q.answer("💣 دیگه نمی‌شه لغو کرد، یا بازی کن یا برداشت", show_alert=True)

    if res.get("status") == "cancelled":
        return await respond(update, f"❌ دست لغو شد و شرط {money(res['bet'])} برگشت جیبت")

    if res.get("status") == "safe":
        return await respond(
            update, board_text(board),
            kb.mines_board_kb(board["revealed"], board["safe"], res["payout"]),
        )

    # boom | auto | out → میز نتیجه کامل‌نما
    await respond(update, result_text(res), kb.mines_result_kb(board["revealed"], board["bomb"], res["bet"]))
