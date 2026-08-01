"""استت‌های نبرد: قدرت حمله و دفاع از آیتم‌ها (با لول ارتقا) + سگ‌ها + آرتیفکت‌ها
مصرف‌کننده‌ها: services.battle | پروفایل | کاروان"""

import config
from models import User
from services import dogs as dog_svc, economy, users


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


def weapon_choice(user: User, item_keys) -> str | None:
    """سلاح موثر نبرد: تجهیزشده اگه هنوز تو انباره، وگرنه پرقدرت‌ترین"""
    levels = _levels_map(item_keys)
    eq = getattr(user, "equipped_weapon", None)
    if eq and eq in levels and eq in config.WEAPONS:
        return eq
    owned = [k for k in levels if k in config.WEAPONS]
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


def combat_stats(user: User, item_keys, dogs: list) -> tuple[int, int]:
    """
    (حمله, دفاع) = پایه بر اساس لول + بهترین سلاح (با لول ارتقا) + سگ‌ها / بهترین زره
    سگ‌ها فقط قدرت حمله میدن (شخصیت حذف شده)، بونس تیم و آب و هوا توی services.battle
    آرتیفکت‌ها (قلب اژدها/سنگ نگهبان) درصدی روی مجموع اثر می‌ذارن
    """
    levels = _levels_map(item_keys)
    atk = config.ATK_BASE + config.ATK_PER_LEVEL * user.level
    dfn = config.DEF_BASE + config.DEF_PER_LEVEL * user.level

    wkey = weapon_choice(user, levels)
    akey = armor_choice(user, levels)
    weapon_bonus = economy.gear_stat("weap", wkey, levels.get(wkey, 1)) if wkey else 0
    armor_bonus = economy.gear_stat("arm", akey, levels.get(akey, 1)) if akey else 0

    atk += _effective_bonus(weapon_bonus, user.level)
    dfn += _effective_bonus(armor_bonus, user.level)

    atk += sum(dog_svc.dog_attack(d) for d in dogs)

    # ویژگی نژادی سگ‌ها: کانگال 💥 حمله و دوبرمن 🛡 دفاع رو درصدی بیشتر می‌کنن
    atk = int(atk * (1 + dog_svc.trait_atk_pct(dogs)))
    dfn = int(dfn * (1 + dog_svc.trait_def_pct(dogs)))

    artis = users.artifact_keys(levels)
    atk = int(atk * users.artifact_atk_mult(artis))
    dfn = int(dfn * users.artifact_def_mult(artis))

    # مهارت‌های 💥 قدرت و 🛡 دفاع درصدی به استت نهایی اضافه می‌کنن
    atk = int(atk * (1 + skill_pct(user, "power")))
    dfn = int(dfn * (1 + skill_pct(user, "defense")))
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


def best_armor_name(item_keys: list[str]) -> str | None:
    owned = [k for k in item_keys if k in config.ARMORS]
    if not owned:
        return None
    best = max(owned, key=lambda k: config.ARMORS[k]["defense"])
    return config.ARMORS[best]["name"]


def has_legend_armor(item_keys: list[str]) -> bool:
    """آیا زره افسانه‌ای داره؟، سکه دزدیده‌شده ازش نصف میشه"""
    return any(config.ARMORS.get(k, {}).get("legendary") for k in item_keys)
