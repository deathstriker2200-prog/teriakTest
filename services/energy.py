"""انرژی‌زا ⚡ بخش «تی انرژی» و /Energy (راند ۱۳، درخواست کارفرما)

مثل درمان: کلیک یعنی خرید و استفاده همون لحظه، انبار نداره
سه نوشیدنی شارژ (25 | 50 | 100) و بمب انرژی: انرژی فول + 30% قدرت حمله به مدت ۱۰ دقیقه
بوست روی کاربر ذخیره میشه (boost_until) و combat_boost_pcts فقط به حمله‌اش اعمالش می‌کنه
پس تو قدرت کل نقش‌محور پی‌وی فقط مهاجم سودش رو می‌بره و مدافع بی‌نصیبه
تموم شدنش با جاروی boost-sweep به پی‌وی کاربر خبر می‌ره: «اثر انرژی‌زا به پایان رسید»
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import User
from utils import now_utc


def boost_left(user: User) -> int:
    """ثانیه مونده از بوست حمله انرژی‌زا، صفر یعنی فعال نیس"""
    if not user.boost_until:
        return 0
    return max(0, int((user.boost_until - now_utc()).total_seconds()))


def drink_atk_boost(user: User) -> float:
    """ضریب بوست فعال انرژی‌زا روی قدرت حمله (مثل ۰٫۳)، منقضی شده یا نداشت صفر"""
    if not boost_left(user):
        return 0.0
    return float(config.ENERGY_DRINKS["bomb"]["boost"] or 0.0)


def apply_drink(user: User, key: str) -> tuple[bool, str, dict]:
    """
    خرید و استفاده همون لحظه انرژی‌زا (بدون انبار، کامیت با صدا‌کننده‌ست)
    خروجی: (موفق, دلیل, جزئیات) | دلیل ناموفق: badkey | full | poor
    جزئیات موفق: gain انرژی شارژشده | boosted بوست حمله گرفته یا نه
    بمب انرژی حتی با انرژی فول هم قابل خریده، چون بوستش مهم‌تره و تایمرش تازه میشه
    """
    item = config.ENERGY_DRINKS.get(key)
    if not item:
        return False, "badkey", {}
    if item["energy"] is not None and user.energy >= config.MAX_ENERGY:
        return False, "full", {}
    if user.cash < item["price"]:
        return False, "poor", {}

    user.cash -= item["price"]
    if item["energy"] is None:
        gain = max(0, config.MAX_ENERGY - user.energy)
        user.energy = config.MAX_ENERGY
    else:
        new_energy = min(config.MAX_ENERGY, user.energy + item["energy"])
        gain = new_energy - user.energy
        user.energy = new_energy
    boosted = False
    if item["boost"]:
        user.boost_until = now_utc() + timedelta(seconds=config.ENERGY_BOOST_SECONDS)
        boosted = True
    return True, "ok", {"gain": gain, "boosted": boosted}


async def process_expired_boosts(session: AsyncSession) -> list[int]:
    """
    بوست‌های تموم‌شده رو جارو می‌کنه و آیدی تلگرام صاحباش رو برمی‌گردونه (کامیت با صدا‌کننده‌ست)
    تا جاب به پی‌وی‌شون پیام «اثر انرژی‌زا به پایان رسید» رو بفرسته
    """
    q = select(User).where(User.boost_until.isnot(None), User.boost_until <= now_utc())
    tgs: list[int] = []
    for u in (await session.execute(q)).scalars():
        tgs.append(u.telegram_id)
        u.boost_until = None
    return tgs
