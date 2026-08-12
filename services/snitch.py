"""
سیستم لو دادن و لقب چاپلوس 🚨 (راند ۲۲، درخواست کارفرما؛ راند ۳۵ رینیم خایه‌مال و بازطراحی افکت‌ها)

دستور «لو دادن» (ریپلای یا @یوزرنیم یا آیدی عددی، مثل حمله): اگه طرف تو بخش محصولات انبارش
چیزی داشته باشه همه محصولاتش توقیف میشن و SNITCH_JAIL_MINUTES دقیقه زندانی میشه
و تو اون مدت هیچ دستوری ازش قبول نمیشه (گیت جداش تو handlers/power.py ثبته، حتی ادمین)
لو‌دهنده SNITCH_REWARD_PCT از ارزش توقیفی + پاداش ثابت SNITCH_BONUS تی‌پوینت می‌گیره
راند ۳۵ (درخواست کارفرما): هر تلاش لو دادن، جوابگو باشه یا نه، تو شمارنده هفتگی حسابه
و با SNITCH_WEEK_LIMIT تا پر شدنش لقب «چاپلوس» (KHAYE_TITLE_HOURS ساعته) میاد:
فروش محصول با افت KHAYE_SELL_MALUS و سرعت شرکت‌ها با افت KHAYE_COMPANY_SLOW
+ اعلام لقب تو همون گروهی که لو دادن آخرش توش زده شد
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
    """الان لقب چاپلوس داره؟ (شبه‌کاربرای تستی بدون ستون هم False می‌گیرن)"""
    until = getattr(user, "khaye_until", None)
    return bool(until and until > now_utc())


def sell_mult(user) -> float:
    """ضریب فروش محصول (محموله یا کاروان قاچاق)، لقب چاپلوس فروش رو KHAYE_SELL_MALUS کم می‌کنه (راند ۳۵)"""
    return (1 - config.KHAYE_SELL_MALUS) if khaye_active(user) else 1.0


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
    لو دادن طرف به پلیس، کولدان و شمارنده هفتگی از همون تلاش می‌خورن (حتی اگه انبارش خالی باشه)
    خروجی: {"status": "empty", khaye} یا {"status": "ok", seized, share, bonus, names, khaye}
    """
    now = now_utc()
    snitcher.last_snitch_at = now

    # راند ۳۵ (درخواست کارفرما): هر تلاش لو دادن، چه جوابگو باشه چه نه، جزو SNITCH_WEEK_LIMIT تا حسابه
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

    seized, names = await seize_all_products(session, target)
    if seized <= 0:
        return {"status": "empty", "khaye": got_khaye}

    share = round(seized * config.SNITCH_REWARD_PCT)
    snitcher.cash += share + config.SNITCH_BONUS
    target.jailed_until = now + timedelta(minutes=config.SNITCH_JAIL_MINUTES)
    await _jail_note(target.telegram_id, target.jailed_until)

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
