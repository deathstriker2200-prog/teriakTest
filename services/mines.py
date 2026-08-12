# -*- coding: utf-8 -*-
"""
💣 بازی مین (راند ۲۸، درخواست کارفرما، جایگزین کامل قمار تاسی حذف‌شده)

میز ۹ خونه‌ای که دقیقا یکیش مینه؛ هر خونه امنی که روشن بشه ضریب برداشت یه پله میره بالا
(جدول MINES_MULTS خود کارفرماست) و هر لحظه می‌تونی برداشت کنی، خوردن به مین = سوختن شرط
روشن شدن هر ۸ خونه امن خودکار با آخرین پله (×4) تسویه میشه، لغو فقط قبل از اولین انتخابه
منقضی شدن میز = برگشت کامل شرط (همون مدل استرداد قمار قبلی) و ری‌استارت = سوختن دست نیمه‌کاره
state تو حافظه‌ست و تمام عددها تو config.py ان
"""
from __future__ import annotations

from datetime import datetime, timedelta
from secrets import randbelow

from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import User
from services import actionlog, tracklog
from utils import esc, now_utc

TILES = 9  # میز ۳×3 با دقیقا یک مین

# telegram_id صاحب میز → رکورد دست
MINES: dict[int, dict] = {}


# ───────── ابزار مشترک ─────────

def cooldown_left(user: User, now: datetime | None = None) -> int:
    """ثانیه مونده از کولدان، صفر یعنی آزادی (همون فیلد last_casino_at قمار قبلی)"""
    now = now or now_utc()
    if not user.last_casino_at:
        return 0
    left = config.MINES_COOLDOWN_SECONDS - int((now - user.last_casino_at).total_seconds())
    return max(0, left)


def current_mult(safe: int) -> float:
    """ضریب برداشت بعد از این تعداد خونه امن روشن"""
    return config.MINES_MULTS[safe - 1] if safe >= 1 else 0.0


def payout_at(bet: int, safe: int) -> int:
    """مبلغ برداشت با این تعداد خونه امن (صفر یعنی هنوز برداشتی نداره)"""
    return int(bet * current_mult(safe)) if safe >= 1 else 0


def mult_label(safe: int) -> str:
    """ضریب فعلی برای نمایش مثل ×0.25 (ارقام لاتین)"""
    return f"×{current_mult(safe):g}" if safe >= 1 else "×0"


def get(tg: int) -> dict | None:
    """میز فعال این کاربر، منقضی None حساب میشه"""
    g = MINES.get(tg)
    if g is None or g["expires_at"] < now_utc():
        return None
    return g


# ───────── شروع میز ─────────

async def arm(session: AsyncSession, user: User, bet: int,
              now: datetime | None = None) -> tuple[bool, str]:
    """
    شروع میز مین: شرط همون لحظه از نقد کم میشه
    خروجی: (اوکی، کد خطا) ← locked | bad_bet | busy | cd | poor
    """
    now = now or now_utc()
    if (user.level or 1) < config.MINES_MIN_LEVEL:
        return False, "locked"
    if bet not in config.MINES_BETS:
        return False, "bad_bet"
    if user.telegram_id in MINES:
        return False, "busy"
    if cooldown_left(user, now) > 0:
        return False, "cd"
    if (user.cash or 0) < bet:
        return False, "poor"

    user.cash -= bet
    user.last_casino_at = now
    await actionlog.log(session, "casino")  # شمار دست قمارخانه پنل ادمین، کلید حفظ‌شده مثل قمار قبلی
    MINES[user.telegram_id] = {
        "uid": user.id, "bet": bet, "bomb": randbelow(TILES),
        "revealed": set(), "safe": 0,
        "chat_id": None, "msg_id": None,
        "expires_at": now + timedelta(seconds=config.MINES_TTL_SECONDS),
        "name": esc(user.first_name or "")[:40],
    }
    return True, ""


def bind_chat(tg: int, chat_id: int | None, msg_id: int | None = None) -> None:
    """چت و پیام میز روی رکورد بایند میشه که کلیک غریبه رو میز کسی اثر نذاره"""
    g = MINES.get(tg)
    if g is not None:
        g["chat_id"] = chat_id
        g["msg_id"] = msg_id


# ───────── تسویه ─────────

async def _settle(session: AsyncSession, user: User, g: dict, payout: int) -> int:
    """بستن میز و پرداخت جایزه، خروجی = خالص برد یا باخت"""
    net = payout - g["bet"]
    if payout:
        user.cash = (user.cash or 0) + payout
    await tracklog.bump_casino(session, user.id, net > 0, net)  # لاگ ردیابی ادمین، فیلدهای حفظ‌شده
    MINES.pop(user.telegram_id, None)
    return net


async def _expire(session: AsyncSession, user: User, g: dict) -> dict:
    """زدن روی میز منقضی: شرط کامل برمی‌گرده (مدل استرداد قمار قبلی)"""
    user.cash = (user.cash or 0) + g["bet"]
    MINES.pop(user.telegram_id, None)
    return {"expired": True, "bet": g["bet"], "cash": user.cash}


# ───────── انتخاب خونه ─────────

async def pick(session: AsyncSession, user: User, idx: int,
               now: datetime | None = None) -> dict | None:
    """
    زدن یه خونه میز؛ خونه تکراری یا میز ناموجود = None (الرت ساکت)
    خروجی: {"status": boom} | {"status": safe} | {"status": auto} | {"expired": True}
    """
    now = now or now_utc()
    g = MINES.get(user.telegram_id)
    if g is None:
        return None
    if not 0 <= idx < TILES or idx in g["revealed"]:
        return None
    if g["expires_at"] < now:
        return await _expire(session, user, g)

    g["revealed"].add(idx)
    if idx == g["bomb"]:
        net = await _settle(session, user, g, 0)
        return {"status": "boom", "bet": g["bet"], "net": net,
                "safe": g["safe"], "cash": user.cash}

    g["safe"] += 1
    if g["safe"] >= TILES - 1:  # هر ۸ خونه امن روشن شد، خودکار با آخرین پله تسویه
        payout = payout_at(g["bet"], g["safe"])
        net = await _settle(session, user, g, payout)
        return {"status": "auto", "bet": g["bet"], "payout": payout,
                "net": net, "safe": g["safe"], "cash": user.cash}

    return {"status": "safe", "bet": g["bet"], "safe": g["safe"],
            "mult": current_mult(g["safe"]), "payout": payout_at(g["bet"], g["safe"])}


# ───────── برداشت و لغو ─────────

async def cashout(session: AsyncSession, user: User,
                  now: datetime | None = None) -> dict | None:
    """برداشت با ضریب فعلی، حداقل یه خونه امن لازمه؛ میز نباشه None، منقضی استرداد"""
    now = now or now_utc()
    g = MINES.get(user.telegram_id)
    if g is None:
        return None
    if g["expires_at"] < now:
        return await _expire(session, user, g)
    if g["safe"] < 1:
        return None  # هنوز خونه امنی نزده، چیزی برای برداشت نداره
    payout = payout_at(g["bet"], g["safe"])
    net = await _settle(session, user, g, payout)
    return {"status": "out", "bet": g["bet"], "payout": payout,
            "net": net, "safe": g["safe"], "cash": user.cash}


async def cancel(session: AsyncSession, user: User) -> dict | None:
    """لغو فقط قبل از اولین انتخاب، شرط کامل برمی‌گرده؛ بعدش یا بازی یا برداشت"""
    g = MINES.get(user.telegram_id)
    if g is None:
        return None
    if g["safe"] > 0:
        return {"status": "late"}
    user.cash = (user.cash or 0) + g["bet"]
    MINES.pop(user.telegram_id, None)
    return {"status": "cancelled", "bet": g["bet"], "cash": user.cash}


# ───────── سوئیپ منقضی‌ها ─────────

async def sweep_expired(session: AsyncSession, now: datetime | None = None) -> list[dict]:
    """میزهای منقضی شرطشون کامل پس می‌گیرن و مشخصات پیامشون برای ادیت برمی‌گرده"""
    now = now or now_utc()
    out: list[dict] = []
    for tg in list(MINES):
        g = MINES[tg]
        if g["expires_at"] >= now:
            continue
        u = await session.get(User, g["uid"])
        if u is not None:
            u.cash = (u.cash or 0) + g["bet"]
        out.append({"tg": tg, "bet": g["bet"], "chat_id": g.get("chat_id"),
                    "msg_id": g.get("msg_id"), "name": g.get("name", "")})
        del MINES[tg]
    return out
