"""
حمله پی‌وی کلاسیک ⚔️، سیستم قدیمی بدون HP

راند ۱۲ درخواست کارفرما: «قدرت کل» ((حمله خودش - دفاع طرف مقابل) / ۴، اصلاح راند ۳۸) دو طرف مقایسه میشه و درصدی نیس، مهاجم بیشتر بود برده وگرنه باخته
بوست‌ها نقش‌محورن: مهاجم فقط بوست‌های حمله‌ای (نژاد سگ | آرتیفکت | مهارت قدرت | هوای تهاجمی) رو می‌گیره و هدف فقط بوست‌های دفاعی
جاسوسی به‌جای شانس درصدی، استت‌ها و قدرت کل طرف رو نشون میده
راند ۱۳: اختلاف قدرت تا PV_ATTACK_CLOSE_DIFF شانسیه، بیرونش قطعیه | راند ۱۷: بازه ۵۰ با برتری قوی‌تر | راند ۲۲: لبه برتری ۹۵ درصد شد (تیون حرفه‌ای، درخواست کارفرما) | هر هدف دیده‌شده تا ۲۰ نشون بعدی تکرار نمیشه
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


def spy_cost(level: int) -> int:
    """هزینه دکمه جاسوسی، خطی با لول جست‌وجوگر بین حداقل و حداکثر کانفیگ"""
    lo, hi = config.PV_SPY_MIN_COST, config.PV_SPY_MAX_COST
    lv = max(1, min(config.MAX_LEVEL, level))
    span = max(1, config.MAX_LEVEL - 1)
    return int(lo + (hi - lo) * (lv - 1) / span)


# ───────── قدرت کل نقش‌محور 💪 (راند ۱۲) ─────────

def is_close(a_total: int, t_total: int) -> bool:
    """اختلاف قدرت‌ها تو رنج نزدیکه؟ (راند ۱۳: اینجا برد قطعی نیس و شانس رول میشه)"""
    return abs(a_total - t_total) <= config.PV_ATTACK_CLOSE_DIFF


def close_win_chance(a_total: int, t_total: int) -> float:
    """
    شانس برد مهاجم تو رنج نزدیک (راند ۱۷، تیون حرفه‌ای راند ۲۲: لبه ۹۵ درصد)
    خطی از ۵۰ درصد روی تساوی تا PV_ATTACK_CLOSE_EDGE_CHANCE روی لبه بازه
    طرف قوی‌تر همیشه بالای پنجاه‌پنجاهه و هرچی نزدیک لبه، برتریش بیشتر میشه
    """
    diff = config.PV_ATTACK_CLOSE_DIFF
    edge = config.PV_ATTACK_CLOSE_EDGE_CHANCE
    c = 0.5 + ((a_total - t_total) / max(1, diff)) * (edge - 0.5)
    return max(0.0, min(1.0, c))


def decide_win(a_total: int, t_total: int) -> bool:
    """
    داور نهایی برد مهاجم (راند ۱۳، اصلاح راند ۱۷ و ۲۲):
    اختلاف تا بازه نزدیک شانسی با برتری قوی‌تره (تا لبه ۹۵ درصد)، بیرون بازه قوی‌تر قطعی می‌بره
    """
    if is_close(a_total, t_total):
        return random.random() < close_win_chance(a_total, t_total)
    return a_total > t_total


async def total_powers(session: AsyncSession, attacker: User, target: User) -> tuple[int, int, dict]:
    """
    (قدرت کل مهاجم, قدرت کل هدف, جزئیات استت خام) | مبنا = (حمله خودش - دفاع طرف مقابل) / ۴ (راند ۳۸)
    بوست‌ها نقش‌محورن (درخواست کارفرما): به قدرت کل مهاجم فقط بوست‌های حمله‌ای‌اش اضافه میشه (نه بوست دفاع)
    و به قدرت کل هدف فقط بوست‌های دفاعی‌اش (نه بوست حمله) | هوا هم همین نقش رو داره (طوفان مهاجم رو ضعیف می‌کنه، مه مدافع رو قوی)
    """
    a_items = await user_svc.get_item_levels(session, attacker.id)
    t_items = await user_svc.get_item_levels(session, target.id)
    # راند ۲۹ (درخواست کارفرما): تفنگ بی‌تیر نه تو حمله مهاجم حسابه نه تو دفاع مدافع
    a_ammo = await user_svc.get_ammo_map(session, attacker.id)
    t_ammo = await user_svc.get_ammo_map(session, target.id)
    a_dogs = await dog_svc.get_user_dogs(session, attacker.id)
    t_dogs = await dog_svc.get_user_dogs(session, target.id)

    a_atk0, a_def0 = combat.combat_raw_stats(attacker, a_items, a_dogs, a_ammo)
    t_atk0, t_def0 = combat.combat_raw_stats(target, t_items, t_dogs, t_ammo)
    # باف ساختمان کارتل هم رو قدرت کل سوار میشه (راند ۱۹، درخواست کارفرما)
    from services import teams as team_svc
    from models import Team
    a_m = await team_svc.get_membership(session, attacker.id)
    t_m = await team_svc.get_membership(session, target.id)
    a_team = await session.get(Team, a_m.team_id) if a_m else None
    t_team = await session.get(Team, t_m.team_id) if t_m else None
    a_tb = team_svc.atk_bonus(a_team) if a_m else 0.0
    t_tb = team_svc.def_bonus(t_team) if t_m else 0.0
    a_ap, _ = combat.combat_boost_pcts(attacker, a_items, a_dogs, a_tb, 0.0)
    _, t_dp = combat.combat_boost_pcts(target, t_items, t_dogs, 0.0, t_tb)

    from services import world as world_svc
    wkey, wpct, _ = await world_svc.weather_state(session)
    watk, wdef = world_svc.weather_combat_mods(wkey, wpct)

    # راند ۳۸ (اصلاح درخواست کارفرما): «قدرت کل» یعنی حمله مهاجم منهای دفاع هدف، هرچی موند تقسیم بر ۴
    # (نه حمله و دفاع خودِ هر نفر با هم، وگرنه مهاجم‌های دفاع‌بالا مصنوعی قوی می‌شدن)
    a_raw = (a_atk0 - t_def0) * (1 + a_ap + watk)
    t_raw = (t_atk0 - a_def0) * (1 + t_dp + wdef)
    a_total = int(a_raw / 4)
    t_total = int(t_raw / 4)

    # قدرت مطلق نمایشی (حمله+دفاع خودِ بازیکن)، دقیقاً فرمول پروفایل (باف کارتل هر دو طرف خودش، بدون اثر هوا)
    # نتیجه برد/باخت همچنان با a_total/t_total نسبی بالا تعیین میشه، این فقط عدد نمایشیه که با پروفایل هم بخونه
    a_tb_atk = team_svc.atk_bonus(a_team) if a_m else 0.0
    a_tb_def = team_svc.def_bonus(a_team) if a_m else 0.0
    t_tb_atk = team_svc.atk_bonus(t_team) if t_m else 0.0
    t_tb_def = team_svc.def_bonus(t_team) if t_m else 0.0
    a_atk_disp, a_def_disp = combat.combat_stats(attacker, a_items, a_dogs, a_tb_atk, a_tb_def, a_ammo)
    t_atk_disp, t_def_disp = combat.combat_stats(target, t_items, t_dogs, t_tb_atk, t_tb_def, t_ammo)
    a_display = a_atk_disp + a_def_disp
    t_display = t_atk_disp + t_def_disp

    return a_total, t_total, {
        "a_atk0": a_atk0, "a_def0": a_def0,
        "t_atk0": t_atk0, "t_def0": t_def0, "weather": wkey,
        "a_display": a_display, "t_display": t_display,
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
    won = decide_win(a_total, t_total)

    # راند ۲۹ (درخواست کارفرما): هر حمله پی‌وی با سلاح گرم یه تیر مصرف می‌کنه
    weapon_key, ammo_left = None, -1
    a_lvls2 = await user_svc.get_item_levels(session, attacker.id)
    a_ammo2 = await user_svc.get_ammo_map(session, attacker.id)
    w_try = combat.weapon_choice(attacker, a_lvls2, a_ammo2)
    if w_try and combat.is_gun(w_try):
        weapon_key = w_try
        ammo_left = await user_svc.consume_ammo(session, attacker.id, w_try)

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
        "weapon": weapon_key,
        "ammo_left": ammo_left,
        "wood_loot": wood_loot,
        "iron_loot": iron_loot,
    }
