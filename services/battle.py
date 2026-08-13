"""
سیستم نبرد HP گروهی ⚔️
HP دائمی تو دیتابیس | هر ضربه همون لحظه دمیج + غارت + تجربه | شکست = ۳۰ دقیقه بیهوشی

ماژولاره: هر عدد/ضریب توی config (بخش «نبرد HP» و HEAL_ITEMS) قابل تغییره
سلاح/زره/سگ/آیتم درمان/رویداد جدید فقط با یه خط به کاتالوگ‌ها اضافه میشه
"""

import random
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import User
from services import actionlog, combat
from services import dogs as dog_svc
from services import users as user_svc
from utils import fa_num, now_utc


# ───────── HP ❤️ ─────────

def max_hp(level: int) -> int:
    """HP کامل بر اساس جدول لول، بالاتر از سقف همون مقدار آخره"""
    lvl = min(max(int(level or 1), 1), len(config.HP_TABLE))
    return config.HP_TABLE[lvl - 1]


def ensure_hp(user: User) -> None:
    """مقداردهی اولیه جان، کاربرای قدیمی یا تازه‌ساخته‌شده‌ها با HP فول لول خودشون"""
    if getattr(user, "hp", None) is None:
        user.hp = max_hp(user.level)


def full_heal(user: User) -> None:
    """HP فول (لول‌آپ و زنده شدن بعد از بیهوشی)"""
    user.hp = max_hp(user.level)


# ───────── بیهوشی 💀 ─────────

def dead_left(user: User) -> int:
    """ثانیه مونده تا زنده شدن، صفر یعنی سر پاست"""
    if not user.dead_until:
        return 0
    left = (user.dead_until - now_utc()).total_seconds()
    return max(0, int(left))


def revive_if_due(user: User) -> bool:
    """وقت بیهوشی گذشته؟ خودکار با HP فول زنده‌ش کن (تنبلی، بدون جاب)"""
    if user.dead_until and dead_left(user) <= 0:
        user.dead_until = None
        full_heal(user)
        return True
    return False


# ───────── کولدان مهاجم ⏳ ─────────

async def cooldown_left(session: AsyncSession, user: User) -> int:
    """ثانیه مونده از کولدان حمله، فقط مهاجم می‌گیره | دوبرمن ⚡ و چابک 🌀 کوتاهش می‌کنن"""
    if not user.last_attack_at:
        return 0
    dogs = await dog_svc.get_user_dogs(session, user.id)
    cd = config.BATTLE_COOLDOWN_SECONDS * dog_svc.breed_cooldown_mult(dogs)
    cd *= (1 - combat.skill_pct(user, "speed"))  # مهارت ⚡ سرعت: هر لول ۲ درصد کولدان کمتر
    left = cd - (now_utc() - user.last_attack_at).total_seconds()
    return max(0, int(left))


# ───────── قدرت نبرد 💪 ─────────


def _poisoned(user: User) -> bool:
    """سم Viper-X هنوز اثر داره؟"""
    pu = getattr(user, "poison_until", None)
    return bool(pu and pu > now_utc())


def _is_night() -> bool:
    """الان به وقت ایران شبه؟ (ساعت ۱۸ تا ۴ بامداد، دامنه Shadow Fang)"""
    from utils import now_iran
    h = now_iran().hour
    return h >= config.SHADOW_NIGHT_FROM or h < config.SHADOW_NIGHT_TO


async def battle_powers(session: AsyncSession, attacker: User, target: User) -> tuple[int, int, dict]:
    """
    (حمله مهاجم, دفاع مدافع, اطلاعات مادیفایرها)
    حمله: پایه + سلاح + لول + سگ + هوا + ساختمان حمله کارتل
    دفاع: پایه + زره + لول + هوا + ساختمان دفاع کارتل + قابلیت‌های ویژه (گرگ دفاع رو خرد می‌کنه)
    """
    a_items = await user_svc.get_item_levels(session, attacker.id)   # راند ۳۰: لول ارتقا تو قدرت حساب بشه
    t_items = await user_svc.get_item_levels(session, target.id)
    a_dogs = await dog_svc.get_user_dogs(session, attacker.id)
    t_dogs = await dog_svc.get_user_dogs(session, target.id)

    info: dict = {"tbuff": 0.0, "defcut": 0.0, "weather": "normal"}

    from services import teams as team_svc
    a_team = await team_svc.get_team_of(session, attacker.id)
    t_team = await team_svc.get_team_of(session, target.id)
    tbuff = team_svc.atk_bonus(a_team)
    tbuff_def = team_svc.def_bonus(t_team)
    if tbuff:
        info["tbuff"] = tbuff

    from services import world as world_svc
    wkey, wpct, _ = await world_svc.weather_state(session)
    watk, wdef = world_svc.weather_combat_mods(wkey, wpct)
    info["weather"] = wkey

    # گرگ سیاه دفاع حریف رو خرد می‌کنه، تا ۳۰% بسته به لولش
    def_cut = dog_svc.rare_defense_cut(a_dogs)
    if def_cut:
        info["defcut"] = def_cut

    # همه مادیفایرها یه‌جا additive روی مقدار اولیه: باف کارتل + هوا + (گرگ و پوینت‌کات منفی)
    a_extra = tbuff + watk
    d_extra = tbuff_def + wdef - def_cut

    # 💀 سم Viper-X: هر طرفی که مسمومه حمله و دفاعش کمتره
    if _poisoned(attacker):
        a_extra -= config.POISON_CUT
        info["poison_self"] = True
    if _poisoned(target):
        d_extra -= config.POISON_CUT
        info["poison_target"] = True

    _a_ammo = await user_svc.get_ammo_map(session, attacker.id)
    atk, _ = combat.combat_stats(attacker, a_items, a_dogs, atk_extra=a_extra, ammo=_a_ammo)
    _, dfn = combat.combat_stats(target, t_items, t_dogs, def_extra=d_extra)
    atk = max(1, atk)
    dfn = max(1, dfn)

    info["a_items"] = a_items
    info["t_items"] = t_items
    info["a_dogs"] = a_dogs
    info["t_dogs"] = t_dogs
    return atk, dfn, info


# ───────── دمیج 🩸 ─────────

def roll_damage(atk: int, dfn: int, victim_max_hp: int) -> tuple[int, bool]:
    """
    (دمیج نهایی یه ضربه, کریتیکال بود؟)
    فرمول درخواستی کارفرما (راند ۱۹): هر ۱ حمله = ۱ دمیج، هر ۱ دفاع = ۱ کاهش، تهش ÷2
    بعد واریانس رندوم که نبرد هیجانی و غیرقابل پیش‌بینی بمونه
    دفاع حریف به‌بزرگی حمله یا مساوی‌اش باشه ضربه اصلاً نمی‌نشینه (پیام زیادی قدرتمنده)
    کریتیکال با شانس کم دمیج نهایی رو چند برابر می‌کنه
    راند ۳۹ (درخواست کارفرما): سقف دمیج هر ضربه، شانسی بین BATTLE_DMG_MAX_LOW و BATTLE_DMG_MAX_HIGH رول میشه
    """
    base = (atk - dfn) / config.BATTLE_DMG_DIVISOR
    if base < 1:
        return 0, False
    v = config.BATTLE_DMG_VARIANCE
    dmg = max(1, round(base * random.uniform(1 - v, 1 + v)))
    crit = random.random() < config.BATTLE_CRIT_CHANCE
    if crit:
        dmg = max(1, round(dmg * config.BATTLE_CRIT_MULT))
    dmg_cap = random.randint(config.BATTLE_DMG_MAX_LOW, config.BATTLE_DMG_MAX_HIGH)
    dmg = min(dmg, dmg_cap)
    return dmg, crit


# ───────── غارت و تجربه همون لحظه 💰 ─────────

def steal_pct_for(cash: int) -> float:
    """درصد سقف غارت بر اساس جیب قربانی (پلکانی، درخواست کارفرما: پولدارا فشار نمی‌خورن)"""
    for limit, pct in config.BATTLE_STEAL_TIERS:
        if limit is None or cash < limit:
            return pct
    return config.BATTLE_STEAL_TIERS[-1][1]


def steal_for_hit(
    dmg: int, victim_max_hp: int, victim_cash: int,
    attacker_dogs: list, victim_items: list[str], victim_dogs: list,
    attacker_items=None,
) -> tuple[int, dict]:
    """
    مبلغ غارت یه ضربه بر اساس دمیج نسبت به HP کامل حریف
    دمیج بیشتر، غارت بیشتر | مادیفایر سگ‌ها و آرتیفکت اعمال میشه | سقف سخت پله موجودی
    خروجی: (مبلغ, اطلاعات مادیفایرها)
    """
    meta = {"bonus": 0.0, "cut": 0.0}
    if victim_cash <= 0 or dmg <= 0:
        return 0, meta

    cap_pct = steal_pct_for(victim_cash)
    pct = cap_pct * min(1.0, dmg / max(1, victim_max_hp))
    amount = float(victim_cash) * pct

    bonus = dog_svc.rare_steal_bonus(attacker_dogs)
    bonus += user_svc.artifact_steal_bonus(user_svc.artifact_keys(attacker_items or []))
    if bonus:
        amount *= 1 + bonus
        meta["bonus"] = bonus

    amount = min(amount, victim_cash * cap_pct)
    return max(0, int(amount)), meta


def xp_for_hit(dmg: int) -> int:
    """تجربه همون لحظه هر ضربه، دمیج بیشتر تجربه بیشتر
    راند ۳۱ (قطعی کارفرما): ضربه گروهی با BATTLE_XP_MULT سی درصد تجربه کمتر میده"""
    raw = config.BATTLE_HIT_XP_BASE + dmg * config.BATTLE_HIT_XP_PER_DMG
    return max(1, round(raw * config.BATTLE_XP_MULT))


# ───────── اجرای کامل یه ضربه ⚔️ ─────────

async def execute_hit(session: AsyncSession, attacker: User, target: User) -> dict:
    """
    همه چک‌ها + محاسبات + تغییرات دیتابیس برای یه ضربه (بدون کامیت)
    خروجی: اگه ok نباشه reason داره
    reason: dead_self | dead_target | no_ammo | cooldown | energy | self
    nodmg=True یعنی حمله انجام شد ولی زره حریف هیچ آسیبی نگه داشت
    """
    revive_if_due(attacker)
    revive_if_due(target)
    ensure_hp(attacker)
    ensure_hp(target)

    if target.id == attacker.id:
        return {"ok": False, "reason": "self"}

    d_self = dead_left(attacker)
    if d_self:
        return {"ok": False, "reason": "dead_self", "left": d_self}

    d_target = dead_left(target)
    if d_target:
        return {"ok": False, "reason": "dead_target", "left": d_target}

    # راند ۳۷ (متن قطعی کارفرما): خشاب خالی یعنی بلاک کامل حمله؛ فالبک خودکار به سلاح سرد از بین رفت
    # گیت قبل از کولدان و هزینه انرژیه، پس حمله بلاک‌شده نه انرژی می‌سوزونه نه کولدان فعال می‌کنه
    _lv37 = await user_svc.get_item_levels(session, attacker.id)
    _am37 = await user_svc.get_ammo_map(session, attacker.id)
    _wg37 = combat.weapon_choice(attacker, _lv37, None)   # انتخاب بدون توجه به مهمات
    if _wg37 and combat.is_gun(_wg37) and combat.ammo_left(_wg37, _lv37.get(_wg37, 1), _am37) <= 0:
        return {"ok": False, "reason": "no_ammo"}

    cd = await cooldown_left(session, attacker)
    if cd:
        return {"ok": False, "reason": "cooldown", "left": cd}

    if attacker.energy < config.ATTACK_ENERGY_COST:
        return {"ok": False, "reason": "energy"}

    # هزینه تلاش برای حمله، حتی اگه دمیج نخوره
    attacker.energy -= config.ATTACK_ENERGY_COST
    attacker.last_attack_at = now_utc()
    await actionlog.log(session, "battle")  # آمار نبردهای گروهی پنل ادمین

    atk, dfn, info = await battle_powers(session, attacker, target)
    hp_max = max_hp(target.level)

    dmg, crit = roll_damage(atk, dfn, hp_max)
    # راند ۳۰ (درخواست کارفرما): هر شلیک نبرد گروهی یه تیر می‌سوزونه و تفنگ خالی دمیج نداره
    a_levels = await user_svc.get_item_levels(session, attacker.id)
    a_ammo_b = await user_svc.get_ammo_map(session, attacker.id)
    wkey = combat.weapon_choice(attacker, a_levels, a_ammo_b)
    ammo_shot = None  # (کلید، باقی‌مونده) برای نمایش تو نتیجه
    if wkey and combat.is_gun(wkey):
        _al30 = await user_svc.consume_ammo(session, attacker.id, wkey)
        if _al30 >= 0:
            ammo_shot = (wkey, _al30)
    # ── قابلیت زره ویژه 🛡 (زره‌های بخش ویژه، با لول ارتقای زره رشد می‌کنن) ──
    armor_lines: list[str] = []
    t_levels19 = await user_svc.get_item_levels(session, target.id)
    akey19 = combat.armor_choice(target, t_levels19)
    aabil = ((config.ARMORS.get(akey19) or {}).get("ability") if akey19 else None)
    aname19 = ((config.ARMORS.get(akey19) or {}).get("name", "") if akey19 else "")
    agrowth19 = 1 + config.SPECIAL_ABILITY_GROWTH * max(0, (t_levels19.get(akey19, 1) or 1) - 1)
    # 🌑 زره خلأ: حمله گاهی کامل بلعیده میشه
    if dmg > 0 and aabil and aabil["kind"] == "void" and random.random() < config.VOID_CHANCE * agrowth19:
        armor_lines.append(f"{aname19} حمله رو قورت داد، اثری ازش نیس")
        dmg = 0
    # ☄️ زره نواترون: دمیج ورودی همیشه کمتر (رشد با لول تا سقف 90%)
    if dmg > 0 and aabil and aabil["kind"] == "reduce":
        cut19 = min(0.9, config.NEUTRON_CUT * agrowth19)
        dmg = max(0, round(dmg * (1 - cut19)))
        armor_lines.append(f"{aname19} ضربه رو له کرد، {fa_num(int(round(cut19 * 100)))}% دمیج کمتر")
    if dmg <= 0:
        return {"ok": True, "nodmg": True, "a_pow": atk, "d_pow": dfn, "info": info,
                "armor_lines": armor_lines, "wkey": wkey, "ammo_left": (ammo_shot[1] if ammo_shot else None)}

    # ── قابلیت سلاح ویژه 🌟 (سلاح‌های لول ۱۶ به بعد، با لول ارتقای سلاح رشد می‌کنن) ──
    abil_lines: list[str] = []
    wcfg = config.WEAPONS.get(wkey) if wkey else None
    abil = (wcfg or {}).get("ability")
    wlvl = (a_levels.get(wkey, 1) if wkey else 1) or 1
    growth = 1 + config.SPECIAL_ABILITY_GROWTH * max(0, wlvl - 1)
    wname = (wcfg or {}).get("name", "")
    kind = abil.get("kind") if abil else None

    def _pc(x: float) -> str:
        return fa_num(int(round(x * 100)))

    def _aline(emoji: str, txt: str) -> None:
        # اسم سلاح‌های ویژه خودشون ایموجی شروع دارن، پس دوباره ایموجی نمی‌زنیم اولشون
        if abil and abil.get("kind") == "oblivion":
            abil_lines.append(f"{wname} این بار: {emoji} {txt}")
        else:
            abil_lines.append(f"{wname} {txt}")

    if kind == "oblivion":
        # راند ۳۰ (درخواست کارفرما): قدرت شب Shadow Fang وقتی شب نیس برای Oblivion اصلا فعال نمیشه
        pool = ("poison", "hellfire", "vampire", "shadow") if _is_night() else ("poison", "hellfire", "vampire")
        kind = random.choice(pool)

    # Hellfire و Shadow روی دمیج قبل از کم شدن HP و غارت اثر می‌ذارن
    if kind == "hellfire" and (target.hp or 0) < config.HELLFIRE_THRESHOLD * hp_max:
        bonus = config.HELLFIRE_BONUS * growth
        dmg = max(1, round(dmg * (1 + bonus)))
        _aline("🔥", "حریف نیمه‌جان رو گرفت، %s%% دمیج بیشتر" % _pc(bonus))
    if kind == "shadow" and _is_night():
        bonus = config.SHADOW_BONUS * growth
        dmg = max(1, round(dmg * (1 + bonus)))
        _aline("🌑", f"تو تاریکی شب {_pc(bonus)}% دمیج بیشتر زد")

    target.hp = max(0, (target.hp or 0) - dmg)

    # 🛡️ زره پلاسمایی: بخشی از دمیج به خود مهاجم برمی‌گرده (کشنده نیس)
    if aabil and aabil["kind"] == "reflect" and dmg > 0:
        back19 = min(max(0, (attacker.hp or 1) - 1), max(0, round(dmg * config.PLASMA_REFLECT * agrowth19)))
        if back19 > 0:
            attacker.hp = (attacker.hp or 1) - back19
            armor_lines.append(f"{aname19} داشت، {fa_num(back19)} دمیج به خودت برگشت")

    # 👑 زره خدایان (راند ۲۳، درخواست کارفرما): ضربه‌ای که خون رو صفر می‌کنه، زره فعال میشه و نصف خون برمی‌گرده
    # یه بار که فعال شد تا واقعاً نمیره دیگه دوباره فعال نمیشه، وگرنه با شانس هر ضربه عملاً بی‌مرگ میشه
    if target.hp <= 0 and aabil and aabil["kind"] == "godshield" and not target.gods_shield_used:
        target.hp = max(1, round(config.GODS_REVIVE_PCT * hp_max))
        target.gods_shield_used = True
        armor_lines.append(f"برکت {aname19} فعال شد و خونش به {fa_num(target.hp)} برگشت")

    # 💀 سم: برای ضربه‌های بعدی حریف ضعیف‌تر میشه
    if kind == "poison" and random.random() < config.POISON_CHANCE * growth:
        target.poison_until = now_utc() + timedelta(seconds=config.POISON_SECONDS)
        _aline("💀", f"نیش سمی اثر گرفت، تا {fa_num(config.POISON_SECONDS // 60)} دقیقه حریف {_pc(config.POISON_CUT)}% ضعیف‌تره")

    steal, meta = steal_for_hit(
        dmg, hp_max, target.cash, info["a_dogs"], info["t_items"], info["t_dogs"],
        info["a_items"],
    )
    if steal:
        steal = int(steal * (1 + combat.skill_pct(attacker, "loot")))  # مهارت 💰 غارت
        target.cash -= steal
        attacker.cash += steal

    # 🩸 Vampire: بخشی از دمیج به HP مهاجم برمی‌گرده
    if kind == "vampire":
        healed = min(
            max_hp(attacker.level) - (attacker.hp or 0),
            max(0, round(dmg * config.VAMPIRE_LEECH * growth)),
        )
        if healed > 0:
            attacker.hp = (attacker.hp or 0) + healed
            _aline("🩸", f"{fa_num(healed)} HP از حریف مکید و بهت برگردوند")

    xp = xp_for_hit(dmg)
    xp = int(xp * dog_svc.battle_xp_mult(info["a_dogs"]))
    xp = int(xp * user_svc.artifact_xp_mult(user_svc.artifact_keys(info["a_items"])))
    notes = user_svc.add_xp(attacker, xp)
    from services import teams as team_svc
    notes += await team_svc.add_team_xp(session, attacker, xp)
    notes += await dog_svc.add_battle_xp(info["a_dogs"], config.DOG_BATTLE_XP_HIT)

    killed = target.hp <= 0
    if killed:
        target.dead_until = now_utc() + timedelta(seconds=config.BATTLE_DEAD_SECONDS)
        target.gods_shield_used = False  # واقعاً مرد، دفعه بعد که زنده شد زره خدایان دوباره می‌تونه فعال بشه
        attacker.wins += 1
        target.losses += 1
        from services import teams as team_svc
        quest_msg = await team_svc.record_kill(session, attacker)
        if quest_msg:
            notes.append(quest_msg)

    from services import tracklog as tl
    await tl.bump_battle(session, attacker.id, target.id, steal, xp, killed)  # لاگ ردیابی ادمین

    return {
        "ok": True,
        "nodmg": False,
        "killed": killed,
        "dmg": dmg,
        "crit": crit,
        "hp_now": target.hp,
        "hp_max": hp_max,
        "steal": steal,
        "meta": meta,
        "xp": xp,
        "notes": notes,
        "a_pow": atk,
        "d_pow": dfn,
        "info": info,
        "abil_lines": [*armor_lines, *abil_lines],
        "poison_self": bool(info.get("poison_self")),
        "wkey": wkey,
        "ammo_left": (ammo_shot[1] if ammo_shot else None),
    }


# ───────── درمان ❤️ ─────────

def heal_preview(user: User, key: str) -> int:
    """چقدر HP با این آیتم برمی‌گرده (با سقف HP کامل)"""
    item = config.HEAL_ITEMS.get(key)
    if not item:
        return 0
    ensure_hp(user)
    if item["heal"] is None:
        return max_hp(user.level) - user.hp
    return min(item["heal"], max_hp(user.level) - user.hp)


def apply_heal(user: User, key: str) -> tuple[bool, str, int]:
    """
    خرید و استفاده همون لحظه آیتم درمان (بدون انبار)
    خروجی: (موفق, پیام, مقدار برگشتی)
    دلیل ناموفق: dead | full | poor | badkey
    """
    item = config.HEAL_ITEMS.get(key)
    if not item:
        return False, "badkey", 0

    revive_if_due(user)
    if dead_left(user):
        return False, "dead", 0

    ensure_hp(user)
    gain = heal_preview(user, key)
    if gain <= 0:
        return False, "full", 0

    if user.cash < item["price"]:
        return False, "poor", 0

    user.cash -= item["price"]
    user.hp += gain
    return True, "ok", gain
