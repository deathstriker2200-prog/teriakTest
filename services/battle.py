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
from services import actionlog, combat, economy
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

    # 💀 سم Viper-X از combat_boost_pcts روی حمله و دفاع همه مودهای بازیکنی اعمال می‌شود؛ اینجا فقط فلگ متن را نگه می‌داریم.
    if _poisoned(attacker):
        info["poison_self"] = True
    if _poisoned(target):
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
    دمیج = پایه + ضریب اختلاف قدرت. سقف مصنوعی ندارد؛ خود قدرت سلاح و دفاع زره نتیجه را می‌سازند.
    بالانس پایه: مکس‌لول/مکس‌سلاح مقابل زره خدایان مکس نزدیک ۱۰۰ دمیج و مقابل لول۱۵ حدود ۲٫۵–۳ برابر.
    """
    power_gap = atk - dfn
    base = config.BATTLE_DMG_BASE + power_gap * config.BATTLE_DMG_PER_POWER
    if base < 1:
        return 0, False
    v = config.BATTLE_DMG_VARIANCE
    dmg = max(1, round(base * random.uniform(1 - v, 1 + v)))
    crit = random.random() < config.BATTLE_CRIT_CHANCE
    if crit:
        dmg = max(1, round(dmg * config.BATTLE_CRIT_MULT))
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
    # ── موتور یکپارچه قابلیت تفنگ و زره ──
    abil_lines: list[str] = []
    armor_lines: list[str] = []
    wcfg = config.WEAPONS.get(wkey) if wkey else None
    base_abil = (wcfg or {}).get("ability")
    wlvl = (a_levels.get(wkey, 1) if wkey else 1) or 1
    wname = (wcfg or {}).get("name", "سلاح")
    pre_weapon_dmg = dmg  # برای زره کوانتومی که باید همه اثرهای قابلیت سلاح را برگرداند

    def _pc(x: float) -> str:
        return fa_num(int(round(x * 100)))

    def _wline(text: str) -> None:
        abil_lines.append(f"{wname} {text}")

    # Oblivion یکی از چهار قابلیت قبلی را می‌گیرد و در لول بالا ممکن است دوتا بگیرد.
    effects: list[dict] = []
    if base_abil and base_abil.get("kind") == "oblivion":
        pool_keys = ["viperx", "hellfire", "vampire"] + (["shadowfang"] if _is_night() else [])
        count = 2 if random.random() < economy.gear_ability_value(base_abil, "double_chance", wlvl) else 1
        for key in random.sample(pool_keys, k=min(count, len(pool_keys))):
            effects.append(config.WEAPONS[key]["ability"])
        _wline("این بار " + " + ".join(config.WEAPONS[k]["name"] for k in pool_keys if config.WEAPONS[k]["ability"] in effects))
    elif base_abil:
        effects = [base_abil]

    # زره فعال هدف و لولش
    t_levels19 = await user_svc.get_item_levels(session, target.id)
    akey19 = combat.armor_choice(target, t_levels19)
    acfg19 = config.ARMORS.get(akey19) if akey19 else None
    aabil = (acfg19 or {}).get("ability")
    alvl19 = (t_levels19.get(akey19, 1) if akey19 else 1) or 1
    aname19 = (acfg19 or {}).get("name", "زره")

    # جهان‌شکن و داوری ممکن است قابلیت زره را در همین ضربه خاموش کنند.
    bypass_armor = False
    judgment_mult = 1.0
    for effect in effects:
        ek = effect.get("kind")
        if ek == "worldbreaker" and random.random() < economy.gear_ability_value(effect, "chance", wlvl):
            bypass_armor = True
            _wline("قابلیت زره حریف رو برای این ضربه شکست")
        elif ek == "judgment" and random.random() < economy.gear_ability_value(effect, "chance", wlvl):
            bypass_armor = True
            judgment_mult = float(effect.get("mult", 1.5))
            _wline(f"ضربه داوری ×{judgment_mult:g} فعال کرد و از قابلیت زره رد شد")

    # نفوذ دفاع به‌صورت اضافه‌دمیج متناظر با همان فرمول power-gap اعمال می‌شود.
    pierce = max((economy.gear_ability_value(e, "pierce", wlvl) for e in effects if "pierce" in e), default=0.0)
    if pierce > 0 and dmg > 0:
        pierce_gain = dfn * pierce * config.BATTLE_DMG_PER_POWER
        if crit:
            pierce_gain *= config.BATTLE_CRIT_MULT
        dmg += max(0, round(pierce_gain))
        _wline(f"از {_pc(pierce)}% دفاع حریف رد شد")

    weapon_cancelled = False
    # کوانتومی قبل از سایر افکت‌ها تصمیم می‌گیرد؛ در صورت فاز، قابلیت سلاح خاموش و ضربه نصف می‌شود.
    if (dmg > 0 and aabil and aabil.get("kind") == "quantum" and not bypass_armor
            and random.random() < economy.gear_ability_value(aabil, "chance", alvl19)):
        weapon_cancelled = True
        dmg = max(0, round(pre_weapon_dmg * (1 - float(aabil.get("reduce", 0.50)))))
        armor_lines.append(f"{aname19} وارد فاز شد؛ قابلیت سلاح خاموش و دمیج نصف شد")

    # افکت‌های تهاجمی؛ همه مقدارهای درصدی از لول واقعی آیتم خوانده می‌شوند.
    if not weapon_cancelled:
        for effect in effects:
            kind = effect.get("kind")
            if kind == "quickdraw" and not crit and random.random() < economy.gear_ability_value(effect, "chance", wlvl):
                crit = True
                dmg = max(1, round(dmg * config.BATTLE_CRIT_MULT))
                _wline("با نشونه‌گیری سریع یه کریت زد")
            elif kind in ("burst", "barrage") and random.random() < economy.gear_ability_value(effect, "chance", wlvl):
                extra = int(effect.get("extra_ammo", 0))
                left = ammo_shot[1] if ammo_shot else -1
                if left >= extra > 0:
                    for _ in range(extra):
                        left = await user_svc.consume_ammo(session, attacker.id, wkey)
                    ammo_shot = (wkey, left)
                    bonus = float(effect.get("bonus", 0.0))
                    dmg = max(1, round(dmg * (1 + bonus)))
                    _wline(f"رگبار فعال کرد؛ {_pc(bonus)}% دمیج بیشتر")
            elif kind == "headshot" and random.random() < economy.gear_ability_value(effect, "chance", wlvl):
                mult = float(effect.get("mult", 1.75))
                dmg = max(1, round(dmg * mult))
                _wline(f"هدشات ×{mult:g} زد")
            elif kind == "sniper" and crit:
                bonus = economy.gear_ability_value(effect, "crit_bonus", wlvl)
                dmg = max(1, round(dmg * (1 + bonus)))
                _wline(f"کریت تک‌تیر {_pc(bonus)}% قوی‌تر شد")
            elif kind == "hellfire" and (target.hp or 0) < economy.gear_ability_value(effect, "threshold", wlvl, 0.35) * hp_max:
                bonus = economy.gear_ability_value(effect, "bonus", wlvl)
                dmg = max(1, round(dmg * (1 + bonus)))
                _wline(f"حریف نیمه‌جان رو گرفت؛ {_pc(bonus)}% دمیج بیشتر")
            elif kind == "shadow":
                bonus = economy.gear_ability_value(effect, "bonus", wlvl)
                if _is_night():
                    bonus += economy.gear_ability_value(effect, "night_bonus", wlvl)
                dmg = max(1, round(dmg * (1 + bonus)))
                _wline(f"قدرت سایه {_pc(bonus)}% دمیج اضافه داد")
            elif kind == "storm" and random.random() < economy.gear_ability_value(effect, "chance", wlvl):
                bonus = float(effect.get("bonus", 0.25))
                dmg = max(1, round(dmg * (1 + bonus)))
                drain = min(int(target.energy or 0), int(effect.get("energy_drain", 10)))
                target.energy = max(0, int(target.energy or 0) - drain)
                _wline(f"شوک زد؛ {_pc(bonus)}% دمیج بیشتر و {fa_num(drain)} انرژی حریف کم شد")
            elif kind == "dragonburn":
                burn = min(int(effect.get("damage_cap", 90)), round(hp_max * economy.gear_ability_value(effect, "maxhp_damage", wlvl)))
                if aabil and aabil.get("kind") == "dragonward" and not bypass_armor:
                    burn = round(burn * (1 - economy.gear_ability_value(aabil, "burn_cut", alvl19)))
                if burn > 0:
                    dmg += burn
                    _wline(f"{fa_num(burn)} دمیج سوختگی اژدها اضافه کرد")
        if judgment_mult > 1:
            dmg = max(1, round(dmg * judgment_mult))

    # قابلیت‌های دفاعی بعد از افکت سلاح؛ bypass_armor همه‌شان را فقط برای همین ضربه خاموش می‌کند.
    if dmg > 0 and aabil and not bypass_armor:
        akind = aabil.get("kind")
        if akind == "void" and random.random() < economy.gear_ability_value(aabil, "chance", alvl19):
            armor_lines.append(f"{aname19} حمله رو کامل قورت داد")
            dmg = 0
        elif akind == "neutron":
            cut = economy.gear_ability_value(aabil, "reduce", alvl19)
            dmg = max(0, round(dmg * (1 - cut)))
            armor_lines.append(f"{aname19} {_pc(cut)}% دمیج رو خرد کرد")
        elif akind == "dragonward" and crit:
            cut = economy.gear_ability_value(aabil, "crit_cut", alvl19)
            dmg = max(1, round(dmg * (1 - cut * 0.5)))
            armor_lines.append(f"{aname19} شدت کریت رو {_pc(cut)}% مهار کرد")
        elif akind == "emperor":
            cap_pct = economy.gear_ability_value(aabil, "damage_cap_pct", alvl19)
            cap_dmg = max(1, round(hp_max * cap_pct))
            if dmg > cap_dmg:
                dmg = cap_dmg
                armor_lines.append(f"{aname19} دمیج رو روی {fa_num(cap_dmg)} سقف کرد")

    if dmg <= 0:
        return {"ok": True, "nodmg": True, "a_pow": atk, "d_pow": dfn, "info": info,
                "armor_lines": armor_lines, "abil_lines": [*armor_lines, *abil_lines],
                "wkey": wkey, "ammo_left": (ammo_shot[1] if ammo_shot else None)}

    target.hp = max(0, (target.hp or 0) - dmg)

    # پلاسمایی بازتاب غیرکشنده دارد.
    if aabil and aabil.get("kind") == "plasma" and not bypass_armor and dmg > 0:
        reflect = economy.gear_ability_value(aabil, "reflect", alvl19)
        back = min(max(0, (attacker.hp or 1) - 1), max(0, round(dmg * reflect)))
        if back > 0:
            attacker.hp = (attacker.hp or 1) - back
            armor_lines.append(f"{aname19} {fa_num(back)} دمیج به خودت برگردوند")

    # آسمانی بخشی از HP را بعد ضربه برمی‌گرداند، اما بیشتر از ۳۰٪ همان ضربه نه.
    if aabil and aabil.get("kind") == "celestial" and not bypass_armor and target.hp > 0:
        heal = min(
            hp_max - target.hp,
            round(hp_max * economy.gear_ability_value(aabil, "heal_pct", alvl19)),
            round(dmg * float(aabil.get("hit_heal_cap", 0.30))),
        )
        if heal > 0:
            target.hp += heal
            dmg = max(0, dmg - heal)
            armor_lines.append(f"{aname19} {fa_num(heal)} HP ترمیم کرد")

    # زره خدایان فقط یک احیا در هر زندگی دارد و درصد احیا با لول رشد می‌کند.
    if target.hp <= 0 and aabil and aabil.get("kind") == "godshield" and not bypass_armor:
        charges = int(aabil.get("charges", 1))
        if int(target.gods_shield_charges or 0) < charges:
            revive = economy.gear_ability_value(aabil, "revive_pct", alvl19)
            target.hp = max(1, round(revive * hp_max))
            target.gods_shield_charges = int(target.gods_shield_charges or 0) + 1
            armor_lines.append(f"برکت {aname19} فعال شد و خونش به {fa_num(target.hp)} برگشت")

    # افکت‌های پس از ضربه
    if not weapon_cancelled:
        for effect in effects:
            kind = effect.get("kind")
            if kind == "poison" and random.random() < economy.gear_ability_value(effect, "chance", wlvl):
                target.poison_until = now_utc() + timedelta(seconds=int(effect.get("seconds", 600)))
                _wline(f"حریف رو برای {fa_num(int(effect.get('seconds', 600)) // 60)} دقیقه مسموم کرد")
            elif kind == "suppress" and random.random() < economy.gear_ability_value(effect, "chance", wlvl):
                target.suppressed_until = now_utc() + timedelta(seconds=int(effect.get("seconds", 300)))
                _wline("حمله حریف رو برای 5 دقیقه 10% سرکوب کرد")

    steal, meta = steal_for_hit(
        dmg, hp_max, target.cash, info["a_dogs"], info["t_items"], info["t_dogs"],
        info["a_items"],
    )
    if steal:
        steal = int(steal * (1 + combat.skill_pct(attacker, "loot")))
        target.cash -= steal
        attacker.cash += steal

    # خون‌آشام از دمیج نهاییِ واقعی جان می‌گیرد.
    if not weapon_cancelled:
        for effect in effects:
            if effect.get("kind") == "vampire":
                leech = economy.gear_ability_value(effect, "leech", wlvl)
                healed = min(max_hp(attacker.level) - (attacker.hp or 0), max(0, round(dmg * leech)))
                if healed > 0:
                    attacker.hp = (attacker.hp or 0) + healed
                    _wline(f"{fa_num(healed)} HP از حریف مکید")
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
        target.gods_shield_charges = 0  # واقعاً مرد، دفعه بعد که زنده شد شمارشگر زره خدایان از نو شروع میشه
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


