"""
حمله پی‌وی کلاسیک ⚔️، سیستم قدیمی بدون HP

قدرت حمله مهاجم با دفاع حریف مقایسه میشه و شانس برد درصدی درمیاد
هدف‌ها اول حوالی لول خودتن (±۲ لول)، هر مرحله خالی بود یه لول بازتر تا ±۱۰، بعدش فالبک: اول بالاترها بعد پایین‌ترها
بعد هر حمله قربانی ۶ ساعت مصونیت می‌گیره
و از لیست حمله‌های پی‌وی خارج میشه
ماژولاره: همه ضرایب توی config بخش «حمله پی‌وی کلاسیک» قابل تغییره
"""

import random
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import User
from services import actionlog, combat
from services import dogs as dog_svc
from services import users as user_svc
from utils import now_utc


# ───────── مصونیت قربانی 🛡 ─────────

def shield_left(user: User) -> int:
    """ثانیه مونده از مصونیت پی‌وی، صفر یعنی دوباره تو لیست حمله‌ست"""
    if not user.shield_until:
        return 0
    left = (user.shield_until - now_utc()).total_seconds()
    return max(0, int(left))


# ───────── کولدان مهاجم ⏳ ─────────

def cooldown_left(user: User) -> int:
    """ثانیه مونده از کولدان حمله پی‌وی، صفر یعنی آماده حمله‌ست"""
    if not user.pv_attack_at:
        return 0
    end = user.pv_attack_at + timedelta(seconds=config.PV_ATTACK_COOLDOWN_SECONDS)
    return max(0, int((end - now_utc()).total_seconds()))


# ───────── هزینه «هدف دیگه» 🎲 ─────────

def reroll_cost(level: int) -> int:
    """هزینه دکمه هدف دیگه، خطی با لول جست‌وجوگر بین حداقل و حداکثر کانفیگ"""
    lo, hi = config.PV_REROLL_MIN_COST, config.PV_REROLL_MAX_COST
    lv = max(1, min(config.MAX_LEVEL, level))
    span = max(1, config.MAX_LEVEL - 1)
    return int(lo + (hi - lo) * (lv - 1) / span)


def spy_is_free(user: User, target: User) -> bool:
    """جاسوسی دوباره همون طرف رایگانه، تا هدف جاسوسیش عوض شه"""
    return user.last_spy_target_id is not None and user.last_spy_target_id == target.id


def spy_cost(level: int) -> int:
    """هزینه دکمه جاسوسی، خطی با لول جست‌وجوگر بین حداقل و حداکثر کانفیگ"""
    lo, hi = config.PV_SPY_MIN_COST, config.PV_SPY_MAX_COST
    lv = max(1, min(config.MAX_LEVEL, level))
    span = max(1, config.MAX_LEVEL - 1)
    return int(lo + (hi - lo) * (lv - 1) / span)


# ───────── قدرت و شانس 🎲 ─────────

async def powers(session: AsyncSession, user: User) -> tuple[int, int]:
    """(حمله, دفاع) کاربر با آیتم‌ها و سگ‌هاش، مبنای مقایسه کلاسیک"""
    items = await user_svc.get_item_keys(session, user.id)
    dogs = await dog_svc.get_user_dogs(session, user.id)
    return combat.combat_stats(user, items, dogs)


def pv_steal_range(cash: int) -> float:
    """رندوم داخل بازه غارت بر اساس جیب قربانی (پلکانی، درخواست کارفرما)"""
    for limit, lo, hi in config.PV_ATTACK_STEAL_TIERS:
        if limit is None or cash < limit:
            return random.uniform(lo, hi)
    lo, hi = config.PV_ATTACK_STEAL_TIERS[-1][1:]
    return random.uniform(lo, hi)


def win_chance(a_atk: int, t_dfn: int) -> float:
    """شانس برد مهاجم، پایه ۵۰ درصد و هر واحد اختلاف قدرت جابه‌جاش می‌کنه (با کف و سقف)"""
    raw = config.PV_BASE_CHANCE + (a_atk - t_dfn) * config.PV_ATTACK_CHANCE_SCALE
    return max(config.PV_ATTACK_MIN_CHANCE, min(config.PV_ATTACK_MAX_CHANCE, raw))


# ───────── هدف شانسی 🎯 ─────────

async def pick_random_target(session: AsyncSession, user: User, exclude_id: int | None = None) -> User | None:
    """
    یه هدف شانسی حوالی لول کاربر (±۴)، خودش و کسایی که مصونیت دارن حذف میشن
    توی رنج کسی نبود فالبک وسیع: اول شانسی بین همه بالاترلولی‌ها، نبود بین پایین‌ترلولی‌ها
    exclude_id آیدی هدف فعلی پیش‌نمایشه که دکمه «هدف دیگه» باید ردش کنه
    هدفی نبود None برمی‌گرده
    """
    base = [
        User.id != user.id,
        (User.shield_until.is_(None)) | (User.shield_until <= now_utc()),
        User.lb_hidden == 0,  # نامرئی‌های /hideboard هدف حمله نمیشن
    ]
    if exclude_id:
        base.append(User.id != exclude_id)
    # اول نزدیک‌ترین بازه لول، هر مرحله که خالی بود یه لول بازتر میشه تا رنج مکس
    for rng in range(config.PV_ATTACK_LEVEL_RANGE, config.PV_ATTACK_MAX_RANGE + 1):
        q = select(User).where(*base, User.level >= user.level - rng, User.level <= user.level + rng)             .order_by(func.random()).limit(1)
        t = (await session.execute(q)).scalar_one_or_none()
        if t is not None:
            return t
    # فالبک: هرکی بالاتره
    q = select(User).where(*base, User.level > user.level).order_by(func.random()).limit(1)
    t = (await session.execute(q)).scalar_one_or_none()
    if t is not None:
        return t
    # فالبک آخر: هرکی پایین‌تره
    q = select(User).where(*base, User.level < user.level).order_by(func.random()).limit(1)
    return (await session.execute(q)).scalar_one_or_none()


# ───────── اجرای حمله ⚔️ ─────────

async def execute(session: AsyncSession, attacker: User, victim: User) -> dict:
    """
    همه چک‌ها + رول شانس + تغییرات دیتابیس یه حمله پی‌وی (بدون کامیت)
    reason: self | shield | energy | cooldown
    هر حمله، برد یا باخت، قربانی رو ۶ ساعت مصون می‌کنه
    کولدان مهاجم ثبت میشه و به قربانی هم یه تجربه ناچیز میرسه
    """
    if victim.id == attacker.id:
        return {"ok": False, "reason": "self"}

    sl = shield_left(victim)
    if sl:
        return {"ok": False, "reason": "shield", "left": sl}

    if attacker.energy < config.PV_ATTACK_ENERGY_COST:
        return {"ok": False, "reason": "energy"}

    cd = cooldown_left(attacker)
    if cd:
        return {"ok": False, "reason": "cooldown", "left": cd}

    attacker.energy -= config.PV_ATTACK_ENERGY_COST
    attacker.pv_attack_at = now_utc()
    await actionlog.log(session, "pvattack")  # آمار حمله‌های پی‌وی پنل ادمین

    a_atk, _ = await powers(session, attacker)
    _, t_dfn = await powers(session, victim)
    artis = user_svc.artifact_keys(await user_svc.get_item_keys(session, attacker.id))
    chance = win_chance(a_atk, t_dfn)
    won = random.random() < chance

    # مصونیت قربانی بعد از حمله، تو برد و باخت هر دو
    victim.shield_until = now_utc() + timedelta(seconds=config.PV_ATTACK_SHIELD_SECONDS)

    steal = 0
    penalty = 0
    if won:
        attacker.wins += 1
        victim.losses += 1
        pct = pv_steal_range(victim.cash)
        pct *= 1 + user_svc.artifact_steal_bonus(artis)
        steal = max(0, int(victim.cash * pct))
        if steal:
            victim.cash -= steal
            attacker.cash += steal
        xp = config.PV_ATTACK_WIN_XP
    else:
        victim.wins += 1
        attacker.losses += 1
        penalty = max(0, int(attacker.cash * config.PV_ATTACK_LOSE_PENALTY_PCT))
        if penalty:
            attacker.cash -= penalty
            victim.cash += penalty
        xp = config.PV_ATTACK_LOSE_XP

    xp = int(xp * user_svc.artifact_xp_mult(artis))
    notes = user_svc.add_xp(attacker, xp)
    from services import teams as team_svc
    notes += await team_svc.add_team_xp(session, attacker, xp)
    # قربانی هم یه تجربه ناچیز می‌گیره، حمله نکرده ولی خورده
    victim_xp = config.PV_ATTACK_VICTIM_XP
    if victim_xp:
        user_svc.add_xp(victim, victim_xp)
        await team_svc.add_team_xp(session, victim, victim_xp)
    return {
        "ok": True,
        "won": won,
        "chance": chance,
        "steal": steal,
        "penalty": penalty,
        "xp": xp,
        "victim_xp": victim_xp,
        "notes": notes,
        "a_pow": a_atk,
        "d_pow": t_dfn,
    }
