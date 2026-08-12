"""استت‌های نبرد: قدرت حمله و دفاع از آیتم‌ها (با لول ارتقا) + سگ‌ها + آرتیفکت‌ها
درصدهای بوست همه additive روی مقدار اولیه جمع میشن (درخواست کارفرما)
مصرف‌کننده‌ها: services.battle | پروفایل | کاروان"""

import config
from models import User
from services import dogs as dog_svc, economy, energy as energy_svc, users


# ───────── استت‌ها ─────────

def _effective_bonus(base: int, user_level: int) -> int:
    """قدرت آیتم با بونس لول کاربر"""
    return int(base * (1 + config.LEVEL_ITEM_BONUS * max(0, user_level - 1)))


def _levels_map(items) -> dict[str, int]:
    """‌ورودی لیست کلید یا دیکشنری لول → همیشه دیکشنری لول"""
    if isinstance(items, dict):
        return items
    return {k: 1 for k in items}


def skill_pct(user: User, key: str) -> float:
    """ضریب اثر یه قابلیت مهارت (۰٫۰۲ یعنی +۲ درصد)، قدرت | سرعت | دفاع | غارت"""
    info = config.SKILLS.get(key)
    if not info:
        return 0.0
    lv = min(max(int(getattr(user, f"skill_{key}", 0) or 0), 0), config.SKILL_MAX_LEVEL)
    return lv * info["per"]


# ───────── مهمات 🔫 (راند ۲۹، درخواست کارفرما) ─────────

def is_gun(key: str | None) -> bool:
    """سلاح گرمه (مهمات داره)؟"""
    return bool(key) and key in config.WEAPONS and bool(config.WEAPONS[key].get("gun"))


def ammo_cap(key: str, level: int = 1) -> int:
    """ظرفیت خشاب: پایه × لول ارتقا (درخواست کارفرما: با لول سلاح جاش بیشتر میشه)"""
    spec = config.WEAPON_AMMO.get(key)
    return int(spec["cap"]) * max(1, int(level or 1)) if spec else 0


def ammo_price(key: str) -> int:
    """قیمت هر تیر این تفنگ"""
    spec = config.WEAPON_AMMO.get(key)
    return int(spec["price"]) if spec else 0


def ammo_left(key: str | None, level: int = 1, ammo: dict | None = None) -> int:
    """تیر باقی‌مونده؛ رکورد None/غایب یعنی خشاب پر (رفتار قدیمی/تازه‌خرید)"""
    if not is_gun(key):
        return -1  # سلاح سرد مهمات نداره
    stored = (ammo or {}).get(key)
    return ammo_cap(key, level) if stored is None else max(0, int(stored))


def weapon_choice(user: User, item_keys, ammo: dict | None = None) -> str | None:
    """
    سلاح موثر نبرد: تجهیزشده اگه هنوز تو انباره، وگرنه پرقدرت‌ترین
    راند ۲۹: تفنگ بدون تیر (ammo = صفر) حساب نمیشه و بهترین سلاح سرد جاش میاد (درخواست کارفرما)
    """
    levels = _levels_map(item_keys)
    eq = getattr(user, "equipped_weapon", None)

    def _usable(k: str) -> bool:
        if k not in levels or k not in config.WEAPONS:
            return False
        if not is_gun(k):
            return True
        if ammo is None:
            return True  # جاهایی که مهمات پاس نمیشه (نبرد گروهی و پروفایل) رفتار قدیمی
        return ammo_left(k, levels.get(k, 1), ammo) > 0

    if eq and _usable(eq):
        return eq
    owned = [k for k in levels if k in config.WEAPONS and _usable(k)]
    if not owned:
        return None
    return max(owned, key=lambda k: economy.gear_stat("weap", k, levels.get(k, 1)))


def armor_choice(user: User, item_keys) -> str | None:
    """زره موثر نبرد: تجهیزشده اگه هنوز تو انباره، وگرنه قوی‌ترین"""
    levels = _levels_map(item_keys)
    eq = getattr(user, "equipped_armor", None)
    if eq and eq in levels and eq in config.ARMORS:
        return eq
    owned = [k for k in levels if k in config.ARMORS]
    if not owned:
        return None
    return max(owned, key=lambda k: economy.gear_stat("arm", k, levels.get(k, 1)))


def weapon_power(item_keys, user_level: int, user: User | None = None) -> int:
    """قدرت موثر سلاح استفاده‌شده (تجهیزشده یا بهترین) با بونس لول، مبنای دمیج کاروان"""
    levels = _levels_map(item_keys)
    if user is not None:
        key = weapon_choice(user, levels)
        base = economy.gear_stat("weap", key, levels.get(key, 1)) if key else 0
    else:
        base = max(
            (economy.gear_stat("weap", k, levels.get(k, 1)) for k in levels if k in config.WEAPONS),
            default=0,
        )
    return _effective_bonus(base, user_level)


def combat_boost_pcts(user: User, item_keys, dogs: list,
                      team_atk: float = 0.0, team_def: float = 0.0) -> tuple[float, float]:
    """
    (جمع درصدهای بوست حمله، دفاع) روی مقدار اولیه، additive (درخواست کارفرما):
    نژاد سگ (کانگال/دوبرمن) + آرتیفکت (قلب اژدها/سنگ نگهبان) + مهارت (قدرت/دفاع) + باف ساختمان کارتل
    team_atk/team_def راند ۱۹: فقط جاهایی که به دیتابیس دسترسی دارن پاس میدن (پروفایل و قدرت کل پی‌وی)
    مثلاً آرتیفکت ۱۰% با مهارت ۱۰% دیگه ۲۱% نمیشه، تمیز و خوانا ۲۰% میشه
    پروفایل همین رو به‌صورت یه درصد واحد کنار حمله/دفاع نشون میده
    """
    levels = _levels_map(item_keys)
    artis = users.artifact_keys(levels)
    atk_p = dog_svc.trait_atk_pct(dogs) + (users.artifact_atk_mult(artis) - 1) + skill_pct(user, "power")
    def_p = dog_svc.trait_def_pct(dogs) + (users.artifact_def_mult(artis) - 1) + skill_pct(user, "defense")
    atk_p += energy_svc.drink_atk_boost(user)  # بمب انرژی (راند ۱۳): بوست موقت فقط روی حمله، پس تو پی‌وی فقط مهاجم سود می‌بره
    return atk_p + team_atk, def_p + team_def


def combat_raw_stats(user: User, item_keys, dogs: list, ammo: dict | None = None) -> tuple[int, int]:
    """
    (حمله, دفاع) خام = پایه بر اساس لول + بهترین سلاح/زره (با لول ارتقا) + سگ‌ها | بدون درصدهای بوست
    مبنای «قدرت کل» حمله پی‌وی راند ۱۲، که بوست‌ها نقش‌محور روش سوار میشن
    سگ‌ها فقط قدرت حمله میدن (شخصیت حذف شده) | راند ۲۹: ammo پاس بشه تفنگ بی‌تیر حساب نمیشه
    """
    levels = _levels_map(item_keys)
    atk = config.ATK_BASE + config.ATK_PER_LEVEL * user.level
    dfn = config.DEF_BASE + config.DEF_PER_LEVEL * user.level

    wkey = weapon_choice(user, levels, ammo)
    akey = armor_choice(user, levels)
    weapon_bonus = economy.gear_stat("weap", wkey, levels.get(wkey, 1)) if wkey else 0
    armor_bonus = economy.gear_stat("arm", akey, levels.get(akey, 1)) if akey else 0

    atk += _effective_bonus(weapon_bonus, user.level)
    dfn += _effective_bonus(armor_bonus, user.level)

    atk += sum(dog_svc.dog_attack(d) for d in dogs)
    return atk, dfn


def combat_stats(user: User, item_keys, dogs: list,
                 atk_extra: float = 0.0, def_extra: float = 0.0,
                 ammo: dict | None = None) -> tuple[int, int]:
    """
    (حمله, دفاع) = استت خام + همه درصدها (نژاد سگ + آرتیفکت + مهارت + extraهای نبردی مثل باف کارتل/هوا/سم)
    روی مقدار اولیه جمع میشن (additive، درخواست کارفرما) نه ضرب پشت سر هم
    بونس کارتل و آب و هوا توی services.battle به‌صورت atk_extra/def_extra تزریق میشن
    راند ۲۹: ammo پاس بشه تفنگ بی‌تیر تو دمیج کاروان/باس حساب نمیشه
    """
    atk, dfn = combat_raw_stats(user, item_keys, dogs, ammo)
    atk_p, def_p = combat_boost_pcts(user, item_keys, dogs)
    atk = int(atk * (1 + atk_p + atk_extra))
    dfn = int(dfn * (1 + def_p + def_extra))
    return atk, dfn


def best_weapon_key(item_keys, user: User | None = None) -> str | None:
    """کلید سلاح استفاده‌شده (تجهیزشده یا بهترین انبار)، نداشت None"""
    levels = _levels_map(item_keys)
    if user is not None:
        return weapon_choice(user, levels)
    owned = [k for k in levels if k in config.WEAPONS]
    if not owned:
        return None
    return max(owned, key=lambda k: economy.gear_stat("weap", k, levels.get(k, 1)))


def best_weapon_name(item_keys: list[str]) -> str | None:
    key = best_weapon_key(item_keys)
    return config.WEAPONS[key]["name"] if key else None


def armor_defense(user: User, item_keys) -> int:
    """عدد دفاع زره موثر با بونس لول (راند ۲۹: دمیج باس اول از این کم میشه)"""
    levels = _levels_map(item_keys)
    akey = armor_choice(user, levels)
    if not akey:
        return 0
    return _effective_bonus(economy.gear_stat("arm", akey, levels.get(akey, 1)), user.level)


def best_armor_name(item_keys: list[str]) -> str | None:
    owned = [k for k in item_keys if k in config.ARMORS]
    if not owned:
        return None
    best = max(owned, key=lambda k: config.ARMORS[k]["defense"])
    return config.ARMORS[best]["name"]
