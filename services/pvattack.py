"""
حمله پی‌وی کلاسیک ⚔️، سیستم قدیمی بدون HP

قدرت هر دو نفر متقارن و دقیقاً برابر حمله نهایی + دفاع نهایی پروفایل خودشان است.
قدرت بالاتر همیشه می‌برد و مساوی به سود مدافع است؛ رول شانس ۷۵/۲۵ قدیمی حذف شده.
جاسوسی و پیام نتیجه همان اسنپ‌شات حمله، دفاع و قدرت کل پیش از فرسایش زره را نشان می‌دهند.
هر هدف دیده‌شده تا ۲۰ نشون بعدی تکرار نمیشه
هدف‌ها اول حوالی لول خودتن (±۲ لول)، هر مرحله خالی بود یه لول بازتر تا ±۱۰، بعدش فالبک: اول بالاترها بعد پایین‌ترها
بعد هر حمله قربانی ۶ ساعت مصونیت می‌گیره
و از لیست حمله‌های پی‌وی خارج میشه
ماژولاره: همه ضرایب توی config بخش «حمله پی‌وی کلاسیک» قابل تغییره
"""

import random
from collections import deque
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import User
from services import actionlog, combat, economy
from services import dogs as dog_svc
from services import users as user_svc
from utils import fa_num, now_utc


# ───────── مصونیت قربانی 🛡 ─────────

def shield_left(user: User) -> int:
    """ثانیه مانده از هر نوع مصونیت پی‌وی."""
    untils = [x for x in (getattr(user, "shield_until", None), getattr(user, "paid_shield_until", None)) if x]
    if not untils:
        return 0
    return max(0, int((max(untils) - now_utc()).total_seconds()))


def paid_shield_left(user: User) -> int:
    """سپر جمی غیرقابل‌شکستن فروشگاه."""
    until = getattr(user, "paid_shield_until", None)
    return max(0, int((until - now_utc()).total_seconds())) if until else 0


def buy_protective_shield(user: User, key: str) -> tuple[bool, str]:
    """خرید/تمدید سپر جمی؛ زمان سپر جمی قبلی تمدید می‌شود و سپر رایگان به آن تبدیل نمی‌شود."""
    spec = config.PROTECTIVE_SHIELDS.get(key)
    if not spec:
        return False, "❌ همچین سپری نیست"
    cost = int(spec["gems"])
    if (user.gems or 0) < cost:
        return False, f"💎 {cost} جم می‌خواد و تو {int(user.gems or 0)} جم داری"
    now = now_utc()
    paid = getattr(user, "paid_shield_until", None)
    base = paid if paid and paid > now else now
    user.gems -= cost
    user.paid_shield_until = base + timedelta(hours=int(spec["hours"]))
    if not user.shield_until or user.shield_until < user.paid_shield_until:
        user.shield_until = user.paid_shield_until
    return True, f"🛡 {spec['name']} فعال شد"


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


def spy_cost(level: int) -> int:
    """هزینه دکمه جاسوسی، خطی با لول جست‌وجوگر بین حداقل و حداکثر کانفیگ"""
    lo, hi = config.PV_SPY_MIN_COST, config.PV_SPY_MAX_COST
    lv = max(1, min(config.MAX_LEVEL, level))
    span = max(1, config.MAX_LEVEL - 1)
    return int(lo + (hi - lo) * (lv - 1) / span)


# ───────── قدرت کل متقارن پروفایل 💪 ─────────

def is_close(a_total: int, t_total: int) -> bool:
    """کمک‌تابع سازگاری؛ نزدیکی قدرت دیگر هیچ شانس جداگانه‌ای ایجاد نمی‌کند."""
    return abs(a_total - t_total) <= config.PV_ATTACK_CLOSE_DIFF


def close_win_chance(a_total: int, t_total: int) -> float:
    """خروجی سازگاری قطعی: فقط مهاجمِ قوی‌تر برنده است و مساوی به مدافع می‌رسد."""
    return 1.0 if a_total > t_total else 0.0


def decide_win(a_total: int, t_total: int) -> bool:
    """داوری کلاسیک PvP قطعی است؛ قدرت بیشتر می‌برد و مساوی به سود مدافع است."""
    return a_total > t_total


async def total_powers(session: AsyncSession, attacker: User, target: User) -> tuple[int, int, dict]:
    """اسنپ‌شات متقارن پروفایل: قدرت هر نفر دقیقاً حمله نهایی + دفاع نهایی خودش است."""
    a_items = await user_svc.get_item_levels(session, attacker.id)
    t_items = await user_svc.get_item_levels(session, target.id)
    a_ammo = await user_svc.get_ammo_map(session, attacker.id)
    t_ammo = await user_svc.get_ammo_map(session, target.id)
    a_dogs = await dog_svc.get_user_dogs(session, attacker.id)
    t_dogs = await dog_svc.get_user_dogs(session, target.id)

    from models import Team
    from services import teams as team_svc
    a_membership = await team_svc.get_membership(session, attacker.id)
    t_membership = await team_svc.get_membership(session, target.id)
    a_team = await session.get(Team, a_membership.team_id) if a_membership else None
    t_team = await session.get(Team, t_membership.team_id) if t_membership else None
    a_team_atk = team_svc.atk_bonus(a_team) if a_membership else 0.0
    a_team_def = team_svc.def_bonus(a_team) if a_membership else 0.0
    t_team_atk = team_svc.atk_bonus(t_team) if t_membership else 0.0
    t_team_def = team_svc.def_bonus(t_team) if t_membership else 0.0

    # همین تابع و همین ورودی‌ها در پروفایل استفاده می‌شوند؛ هوا و نقش مهاجم/مدافع
    # این اسنپ‌شات را نامتقارن نمی‌کند. محاسبه پیش از مصرف مهمات و فرسایش زره انجام می‌شود.
    a_attack, a_defense = combat.combat_stats(
        attacker, a_items, a_dogs, a_team_atk, a_team_def, ammo=a_ammo,
    )
    t_attack, t_defense = combat.combat_stats(
        target, t_items, t_dogs, t_team_atk, t_team_def, ammo=t_ammo,
    )
    a_total = a_attack + a_defense
    t_total = t_attack + t_defense
    target_armor = combat.armor_choice(target, t_items)

    return a_total, t_total, {
        "a_attack": a_attack,
        "a_defense": a_defense,
        "t_attack": t_attack,
        "t_defense": t_defense,
        "a_display": a_total,
        "t_display": t_total,
        "target_armor_key": target_armor,
        # کلیدهای زیر فقط برای سازگاری مصرف‌کننده‌های قدیمی نگه داشته شده‌اند.
        "a_atk0": a_attack,
        "a_def0": a_defense,
        "t_atk0": t_attack,
        "t_def0": t_defense,
        "weather": None,
        "weapon_ability_bonus": 0.0,
        "armor_ability_bonus": 0.0,
        "mimic_armor_key": None,
    }


def pv_steal_range(cash: int) -> float:
    """رندوم داخل بازه غارت بر اساس جیب قربانی (پلکانی، درخواست کارفرما)"""
    for limit, lo, hi in config.PV_ATTACK_STEAL_TIERS:
        if limit is None or cash < limit:
            return random.uniform(lo, hi)
    lo, hi = config.PV_ATTACK_STEAL_TIERS[-1][1:]
    return random.uniform(lo, hi)



# ───────── هدف شانسی 🎯 ─────────

# دیده‌شده‌های سرچ هر کاربر (راند ۱۳، حافظه فرّار با کلید آیدی تلگرام | با ری‌استارت ریست میشه):
# هر هدفی که پیش‌نمایش داده میشه تا PV_SEEN_EXCLUDE_LAST نشون بعدی تکرار نمیشه
_SEEN: dict[int, deque] = {}


def note_target_shown(user_id: int, target_id: int) -> None:
    """هدف نشون‌داده‌شده رو لیست اخیرهای کاربر (آیدی تلگرام) بنداز، فقط آخرین N تا نگه می‌مونه (چرخه‌ای)"""
    dq = _SEEN.get(user_id)
    if dq is None or dq.maxlen != config.PV_SEEN_EXCLUDE_LAST:
        dq = deque(maxlen=config.PV_SEEN_EXCLUDE_LAST)
        _SEEN[user_id] = dq
    dq.append(target_id)


def seen_targets(user_id: int) -> set[int]:
    """ست آیدی هدف‌های اخیراً دیده‌شده کاربر"""
    return set(_SEEN.get(user_id, ()))


def clear_seen_targets(user_id: int) -> None:
    """با تموم شدن سرچ (حمله یا برگشت به پنل) لیست دیده‌شده‌ها پاک میشه تا سرچ بعدی تازه باشه"""
    _SEEN.pop(user_id, None)


async def _pick(session: AsyncSession, user: User, exclude_id: int | None = None,
                exclude_ids: set[int] | None = None) -> User | None:
    """بدنه انتخاب هدف با امکان حذف دسته‌جمعی (دیده‌شده‌های سرچ)"""
    base = [
        User.id != user.id,
        (User.shield_until.is_(None)) | (User.shield_until <= now_utc()),
        User.lb_hidden == 0,  # نامرئی‌های /hideboard هدف حمله نمیشن
    ]
    if exclude_id:
        base.append(User.id != exclude_id)
    if exclude_ids:
        base.append(User.id.notin_(exclude_ids))
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


async def pick_random_target(session: AsyncSession, user: User, exclude_id: int | None = None) -> User | None:
    """
    یه هدف شانسی حوالی لول کاربر، خودش و مصونیت‌دارها و نامرئی‌ها حذف میشن
    اهداف اخیراً دیده‌شده تو سرچ همین کاربر (تا PV_SEEN_EXCLUDE_LAST تای آخر) هم کنار گذاشته میشن
    exclude_id آیدی هدف فعلی پیش‌نمایشه که دکمه «هدف دیگه» باید ردش کنه
    فالبک آخر: همه حوالی دیده شده باشن لیست دیده‌شده نادیده گرفته میشه تا سرچ هرگز نخشکه
    """
    seen = seen_targets(user.telegram_id)
    t = await _pick(session, user, exclude_id=exclude_id, exclude_ids=seen or None)
    if t is None and seen:
        t = await _pick(session, user, exclude_id=exclude_id)
    return t


# ───────── اجرای حمله ⚔️ ─────────

async def execute(session: AsyncSession, attacker: User, victim: User) -> dict:
    """
    همه چک‌ها + رول شانس + تغییرات دیتابیس یه حمله پی‌وی (بدون کامیت)
    reason: self | shield | no_ammo | energy | cooldown
    هر حمله، برد یا باخت، قربانی رو ۶ ساعت مصون می‌کنه
    کولدان مهاجم ثبت میشه و به قربانی هم یه تجربه ناچیز میرسه
    """
    if victim.id == attacker.id:
        return {"ok": False, "reason": "self"}

    sl = shield_left(victim)
    if sl:
        return {"ok": False, "reason": "shield", "left": sl}

    # راند ۳۷ (متن قطعی کارفرما): تفنگ خالی یعنی حمله پی‌وی لغوه و پاپ‌آپ «تیر نداری» میاد
    # قبل از چک انرژی و کولدانه که حمله بلاک‌شده هیچ هزینه‌ای نداشته باشه
    _lv37 = await user_svc.get_item_levels(session, attacker.id)
    _am37 = await user_svc.get_ammo_map(session, attacker.id)
    _wg37 = combat.weapon_choice(attacker, _lv37, None)   # انتخاب بدون توجه به مهمات
    if _wg37 and combat.is_gun(_wg37) and combat.ammo_left(_wg37, _lv37.get(_wg37, 1), _am37) <= 0:
        return {"ok": False, "reason": "no_ammo"}

    if attacker.energy < config.PV_ATTACK_ENERGY_COST:
        return {"ok": False, "reason": "energy"}

    cd = cooldown_left(attacker)
    if cd:
        return {"ok": False, "reason": "cooldown", "left": cd}

    attacker.energy -= config.PV_ATTACK_ENERGY_COST
    attacker.pv_attack_at = now_utc()
    await actionlog.log(session, "pvattack")  # آمار حمله‌های پی‌وی پنل ادمین

    a_total, t_total, _info = await total_powers(session, attacker, victim)
    artis = user_svc.artifact_keys(await user_svc.get_item_keys(session, attacker.id))
    # داوری دقیقاً با همین اسنپ‌شات قابل‌نمایش است: قوی‌تر قطعی می‌برد و مساوی سهم مدافع است.
    won = decide_win(a_total, t_total)

    # راند ۲۹ (درخواست کارفرما): هر حمله پی‌وی با سلاح گرم یه تیر مصرف می‌کنه
    weapon_key, ammo_left = None, -1
    a_lvls2 = await user_svc.get_item_levels(session, attacker.id)
    a_ammo2 = await user_svc.get_ammo_map(session, attacker.id)
    w_try = combat.weapon_choice(attacker, a_lvls2, a_ammo2)
    if w_try and combat.is_gun(w_try):
        weapon_key = w_try
        ammo_left = await user_svc.consume_ammo(session, attacker.id, w_try)

    # اسنپ‌شات قدرت قبل از این اثرها ثبت شده؛ فرسایش و دباف نتیجه همان حمله‌اند.
    ability_notes: list[str] = []
    wear = await user_svc.damage_armor(session, victim, _info.get("target_armor_key"))
    if wear and wear["loss"]:
        ability_notes.append(
            f"🛡 دوام زره حریف {fa_num(wear['loss'])} تا کم شد؛ "
            f"{fa_num(wear['current'])}/{fa_num(wear['maximum'])}"
        )
        if wear["broken"]:
            ability_notes.append("💔 زره حریف شکست و خودکار از تنش دراومد")
    wabil = (config.WEAPONS.get(w_try) or {}).get("ability") if w_try else None
    wlvl = a_lvls2.get(w_try, 1) if w_try else 1
    if wabil and wabil.get("kind") == "poison" and random.random() < economy.gear_ability_value(wabil, "chance", wlvl):
        victim.poison_until = now_utc() + timedelta(seconds=int(wabil.get("seconds", 600)))
        ability_notes.append("💀 حریف مسموم شد")
    if wabil and wabil.get("kind") == "suppress" and random.random() < economy.gear_ability_value(wabil, "chance", wlvl):
        victim.suppressed_until = now_utc() + timedelta(seconds=int(wabil.get("seconds", 300)))
        ability_notes.append("🔻 حمله حریف 5 دقیقه سرکوب شد")

    # مصونیت قربانی بعد از حمله، تو برد و باخت هر دو
    victim.shield_until = now_utc() + timedelta(seconds=config.PV_ATTACK_SHIELD_SECONDS)

    steal = 0
    penalty = 0
    wood_loot, iron_loot = 0, 0
    if won:
        attacker.wins += 1
        victim.losses += 1
        pct = pv_steal_range(victim.cash)
        pct *= 1 + user_svc.artifact_steal_bonus(artis)
        steal = max(0, int(victim.cash * pct))
        if steal:
            victim.cash -= steal
            attacker.cash += steal
        from services import resources as res_svc
        for _res in ("wood", "iron"):
            _have = int(getattr(victim, _res, 0) or 0)
            if _have > 0:
                _want = max(1, int(_have * config.PV_RES_LOOT_CHANCE_SHARE))
                _took = min(_want, max(0, res_svc.res_cap(attacker, _res) - int(getattr(attacker, _res, 0) or 0)))
                if _took > 0:
                    setattr(victim, _res, _have - _took)
                    setattr(attacker, _res, int(getattr(attacker, _res, 0) or 0) + _took)
                    if _res == "wood":
                        wood_loot = _took
                    else:
                        iron_loot = _took
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
    from services import tracklog as tl
    await tl.bump_pv(session, attacker.id, won, steal if won else -penalty, xp)  # لاگ ردیابی ادمین
    return {
        "ok": True,
        "won": won,
        "steal": steal,
        "penalty": penalty,
        "xp": xp,
        "victim_xp": victim_xp,
        "notes": notes,
        "a_pow": a_total,
        "d_pow": t_total,
        "a_pow_disp": _info["a_display"],
        "d_pow_disp": _info["t_display"],
        "a_attack": _info["a_attack"],
        "a_defense": _info["a_defense"],
        "d_attack": _info["t_attack"],
        "d_defense": _info["t_defense"],
        "weapon": weapon_key,
        "ammo_left": ammo_left,
        "wood_loot": wood_loot,
        "iron_loot": iron_loot,
        "ability_notes": ability_notes,
    }


