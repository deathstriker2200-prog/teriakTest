"""
سیستم لو دادن و لقب خایه‌مال 🚨 (راند ۲۲، درخواست کارفرما)

دستور «لو دادن» (ریپلای یا @یوزرنیم یا آیدی عددی، مثل حمله): اگه طرف تو بخش محصولات انبارش
چیزی داشته باشه همه محصولاتش توقیف میشن و SNITCH_JAIL_MINUTES دقیقه زندانی میشه
و تو اون مدت هیچ دستوری ازش قبول نمیشه (گیت جداش تو handlers/power.py ثبته)
لو‌دهنده SNITCH_REWARD_PCT از ارزش توقیفی + پاداش ثابت SNITCH_BONUS تی‌پوینت می‌گیره
هر SNITCH_WEEK_LIMIT لو دادن موفق تو هفته لقب «خایه‌مال» (KHAYE_TITLE_HOURS ساعته):
خرید بذر با تخفیف KHAYE_SEED_DISCOUNT و بازده کارخونه با افت KHAYE_FACTORY_MALUS
بعد از تموم شدنش لقب خودکار برمی‌گرده به لقب عادی | تمام عددها تو config.py ان
"""

import time as _time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import ProductStock, User
from utils import fa_num, now_utc


# ───────── لقب و زندان ─────────

def khaye_active(user) -> bool:
    """الان لقب خایه‌مال داره؟ (شبه‌کاربرای تستی بدون ستون هم False می‌گیرن)"""
    until = getattr(user, "khaye_until", None)
    return bool(until and until > now_utc())


def jail_left(user: User) -> int:
    """ثانیه‌های باقی زندان کاربر، صفر یعنی آزاده"""
    until = getattr(user, "jailed_until", None)
    if not until:
        return 0
    return max(0, int((until - now_utc()).total_seconds()))


def cooldown_left(user: User) -> int:
    """ثانیه‌های باقی کولدان لو دادن، صفر یعنی آزاده"""
    last = getattr(user, "last_snitch_at", None)
    if not last:
        return 0
    left = config.SNITCH_COOLDOWN_SECONDS - (now_utc() - last).total_seconds()
    return max(0, int(left))


# ───────── کش زندانی‌ها برای گیت تند (هر چند ثانیه از دی‌بی تازه میشه) ─────────

_JAIL_TTL = 10.0
_jail_cache: dict = {"at": 0.0, "map": {}}  # tg_id -> datetime پایان زندان


def jail_invalidate() -> None:
    _jail_cache["at"] = 0.0


async def jail_left_tg(session: AsyncSession, tg_id: int) -> int:
    """زمان مونده زندان با آیدی تلگرام (برای گیت پیام‌ها، سبک و کش‌شونده)"""
    now = now_utc()
    if _time.monotonic() - _jail_cache["at"] >= _JAIL_TTL:
        rows = (await session.execute(
            select(User.telegram_id, User.jailed_until).where(User.jailed_until > now)
        )).all()
        _jail_cache["map"] = {tid: until for tid, until in rows if until}
        _jail_cache["at"] = _time.monotonic()
    until: datetime | None = _jail_cache["map"].get(tg_id)
    if not until or until <= now:
        return 0
    return int((until - now).total_seconds())


async def _jail_note(tg_id: int, until: datetime) -> None:
    _jail_cache["map"][tg_id] = until


# ───────── توقیف انبار ─────────

async def seize_all_products(session: AsyncSession, target: User) -> tuple[int, list[str]]:
    """همه محصولات بخش محصولات انبار طرف صفر میشن؛ خروجی (ارزش کل توقیفی، لیست قلم‌ها)"""
    rows = list((await session.execute(
        select(ProductStock).where(ProductStock.user_id == target.id, ProductStock.qty > 0)
    )).scalars())
    total, names = 0, []
    for r in rows:
        if r.value <= 0:
            continue
        total += r.value
        sd = config.SEEDS.get(r.crop, {})
        names.append(f"{sd.get('name', r.crop)} ×{fa_num(r.qty)}")
        r.qty = 0
        r.value = 0
    return total, names


# ───────── لو دادن ─────────

async def snitch(session: AsyncSession, snitcher: User, target: User) -> dict:
    """
    لو دادن طرف به پلیس، کولدان از همون تلاش می‌خوره (حتی اگه انبارش خالی باشه)
    خروجی: {"status": "empty"} یا {"status": "ok", seized, share, bonus, names, khaye}
    """
    now = now_utc()
    snitcher.last_snitch_at = now

    seized, names = await seize_all_products(session, target)
    if seized <= 0:
        return {"status": "empty"}

    share = round(seized * config.SNITCH_REWARD_PCT)
    snitcher.cash += share + config.SNITCH_BONUS
    target.jailed_until = now + timedelta(minutes=config.SNITCH_JAIL_MINUTES)
    await _jail_note(target.telegram_id, target.jailed_until)

    # شمارنده هفتگی لو دادن موفق، پر شدنش لقب خایه‌مال میده و از نو شروع میشه
    window = timedelta(days=config.SNITCH_WEEK_WINDOW_DAYS)
    if not snitcher.snitch_window_at or now - snitcher.snitch_window_at >= window:
        snitcher.snitch_window_at = now
        snitcher.snitch_count = 0
    snitcher.snitch_count = (snitcher.snitch_count or 0) + 1

    got_khaye = False
    if snitcher.snitch_count >= config.SNITCH_WEEK_LIMIT:
        snitcher.khaye_until = now + timedelta(hours=config.KHAYE_TITLE_HOURS)
        snitcher.snitch_count = 0
        snitcher.snitch_window_at = now
        got_khaye = True

    return {
        "status": "ok",
        "seized": seized,
        "share": share,
        "bonus": config.SNITCH_BONUS,
        "names": names,
        "khaye": got_khaye,
    }


# ───────── رشوه دادن 💰 (راند ۲۸، درخواست کارفرما) ─────────

async def bribe(session: AsyncSession, user: User) -> dict:
    """
    زندانی با پرداخت BRIBE_COST همون لحظه آزاد میشه
    خروجی: {"status": "free"} یا {"status": "broke", "left"} یا {"status": "ok", "cost"}
    """
    left = jail_left(user)
    if left <= 0:
        return {"status": "free"}
    cost = config.BRIBE_COST
    if (user.cash or 0) < cost:
        return {"status": "broke", "left": left}
    user.cash -= cost
    user.jailed_until = None
    _jail_cache["map"].pop(user.telegram_id, None)  # کش گیت زندان هم فورا پاک شه
    return {"status": "ok", "cost": cost}
