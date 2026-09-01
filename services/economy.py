"""منطق اقتصادی: قیمت زمین | آپگرید | بذر | کنده‌کاری | منحنی تجربه"""

import random

import config


# ───────── منحنی تجربه؛ جدول صریح با مجموع دقیق 400,000 ─────────

def xp_need(level: int) -> int:
    """XP لازم برای رفتن از level به level+1؛ در لول مکس آخرین مقدار را برمی‌گرداند."""
    level = max(1, int(level or 1))
    idx = min(level - 1, len(config.PLAYER_XP_NEEDS) - 1)
    return int(config.PLAYER_XP_NEEDS[idx])


# ───────── زمین ─────────

def plot_info(plot_number: int) -> dict:
    """مشخصات زمین شماره n (۱ تا MAX)، قیمت/زمان ساخت/لول لازم"""
    n = min(max(plot_number, 1), config.MAX_PLOTS)
    return config.PLOT_CATALOG[n]


def plot_price(plots_count: int) -> int:
    """قیمت زمین بعدی بر اساس تعداد زمین‌های فعلی، هرکی خیلی گرون‌تر"""
    return plot_info(plots_count + 1)["price"]


def plot_required_level(plots_count: int) -> int:
    """گیت لول برای خرید زمین بعدی"""
    return plot_info(plots_count + 1)["min_level"]


def plot_build_seconds(plots_count: int) -> int:
    """زمان ساخت زمین بعدی به ثانیه"""
    return plot_info(plots_count + 1)["build_sec"]


def upgrade_price(plot_level: int) -> int:
    """هزینه آپگرید از لول فعلی به لول بعد، جدول رند قیمت"""
    lv = min(max(plot_level, 1), len(config.PLOT_UPGRADE_PRICES))
    return config.PLOT_UPGRADE_PRICES[lv - 1]


def upgrade_wood(plot_level: int) -> int:
    """چوب لازم برای آپگرید زمین از لول فعلی به بعدی"""
    lv = min(max(plot_level, 1), len(config.PLOT_UPGRADE_WOOD))
    return config.PLOT_UPGRADE_WOOD[lv - 1]


def plot_upgrade_required_level(plot_level: int) -> int:
    """گیت لول کاربر برای آپگرید زمین از لول فعلی به لول بعد"""
    lv = min(max(plot_level, 1), len(config.PLOT_UPGRADE_LEVELS))
    return config.PLOT_UPGRADE_LEVELS[lv - 1]


# ───────── بذر و محصول ─────────

def plot_speed_mult(plot_level: int) -> float:
    """ضریب سرعت رشد زمین تو لولش، هر لول ۴۰% سرعت بیشتر (زمان ÷۱٫۴۰)"""
    return config.PLOT_SPEED_PER_LEVEL ** max(0, plot_level - 1)


def plot_quality_bonus(plot_level: int) -> float:
    """شانس اضافه محصول ۵ ستاره بر اساس لول زمین، اثر مستقیم روی قیمت نیس"""
    return config.PLOT_Q5_PER_LEVEL * max(0, plot_level - 1)


def crop_xp(seed_key: str, stars: int) -> int:
    """تجربه برداشت هر ساقه: از رنج (کف، سقف) بذر بر اساس کیفیت ⭐1 تا ⭐5 درونیابی میشه
    راند ۳۱ (قطعی کارفرما): خروجی با FARM_XP_MULT سی درصد کمتر میشه"""
    lo, hi = config.SEEDS[seed_key]["xp"]
    stars = min(max(int(stars or 1), 1), 5)
    base = lo + round((hi - lo) * (stars - 1) / 4)
    return max(1, round(base * config.FARM_XP_MULT))


def crop_yield(seed_key: str, plot_level: int = 1, user_level: int = 1) -> int:
    """درآمد برداشت با بونس لول کاربر | لول زمین روی قیمت اثر مستقیم نداره (فقط کیفیت و سرعت)"""
    base = config.SEEDS[seed_key]["sell"]
    user_mult = 1 + config.LEVEL_YIELD_BONUS * max(0, user_level - 1)
    return int(base * user_mult)


def crop_grow_seconds(seed_key: str, plot_level: int = 1) -> int:
    """مدت آماده شدن با ضریب سرعت لول زمین، هر لول آپ ۴۰% سرعت بیشتر"""
    minutes = config.SEEDS[seed_key]["grow_min"]
    return max(30, int(minutes * 60 / plot_speed_mult(plot_level)))


def is_seed_unlocked(seed_key: str, user_level: int) -> bool:
    return user_level >= config.SEEDS[seed_key]["min_level"]


# ───────── گیت لول دراپ بذر (جستجو و کوئست، درخواست کارفرما) ─────────

def seed_drop_min_level(seed_key: str) -> int:
    """حداقل لول برای افتادن بذر از جستجو/کوئست، بقیه بذرها از لول ۱"""
    return config.SEED_DROP_MIN_LEVEL.get(seed_key, 1)


def seed_drop_allowed(seed_key: str, user_level: int) -> bool:
    """این بذر با این لول می‌تونه دراپ بشه؟ (کوکائین 3+ | جهنم/ابلیس 5+ | جهش‌یافته 8+)"""
    return user_level >= seed_drop_min_level(seed_key)


def allowed_normal_seeds(user_level: int) -> list[str]:
    """بذرهای غیرافسانه‌ای که با این لول اجازه دراپ دارن، به ترتیب کاتالوگ"""
    return [k for k, v in config.SEEDS.items()
            if not v.get("legendary") and seed_drop_allowed(k, user_level)]


# ───────── ارتقای سلاح و زره ⬆️ ─────────

def gear_catalog(kind: str) -> dict:
    return config.WEAPONS if kind == "weap" else config.ARMORS


def gear_stat(kind: str, key: str, level: int) -> int:
    """استت آیتم با لول ارتقاش، هر لول یه ضریب روی استت پایه"""
    item = gear_catalog(kind)[key]
    base = item["attack"] if kind == "weap" else item["defense"]
    return int(base * (1 + config.GEAR_UPG_STAT_PER_LEVEL * max(0, level - 1)))


def gear_upg_tp(kind: str, key: str, from_level: int) -> int:
    """هزینه پله‌ای ارتقا؛ مجموع لول ۱ تا ۵ برابر ۳٫۵ قیمت خرید است."""
    price = gear_catalog(kind)[key]["price"]
    idx = min(max(int(from_level or 1) - 1, 0), len(config.GEAR_UPG_TP_STEPS) - 1)
    return int(round(price * config.GEAR_UPG_TP_STEPS[idx]))


def gear_upg_iron(kind: str, key: str, from_level: int) -> int:
    """آهن ارتقا با مسیر سبک‌تر؛ تفنگ از آهن خرید و زره از رتبه آیتم مقیاس می‌گیرد."""
    idx = min(max(int(from_level or 1) - 1, 0), config.GEAR_UPG_MAX - 2)
    if kind == "weap":
        base = int(gear_catalog(kind)[key].get("iron", 0) or 0)
        ratio = config.GEAR_UPG_WEAPON_IRON_RATIOS[idx]
        return max(1, int(round(base * ratio)) + config.GEAR_UPG_WEAPON_IRON_EXTRA[idx])
    rank = list(gear_catalog(kind).keys()).index(key)
    base = config.GEAR_UPG_IRON_ARMOR_BASE + rank * 2
    return max(1, int(round(base * config.GEAR_UPG_ARMOR_IRON_RATIOS[idx])))


def gear_upg_min_level(from_level: int) -> int:
    """گیت لول بازیکن برای رفتن به لول بعدی آیتم"""
    idx = min(max(from_level - 1, 0), len(config.GEAR_UPG_LEVELS) - 1)
    return config.GEAR_UPG_LEVELS[idx]


# ───────── کنده‌کاری ─────────

def mine_roll() -> int:
    """قرعه روزانه، بازه پایین با وزن بیشتر (۱۰ تا ۱۰۰ پرتکرارتر از ۱۰۰ تا ۱۵۰)"""
    if random.random() < config.MINE_COMMON_WEIGHT:
        return random.randint(config.MINE_MIN, config.MINE_COMMON_MAX)
    return random.randint(config.MINE_COMMON_MAX + 1, config.MINE_MAX)


def gear_ability_value(ability: dict | None, field: str, level: int, default: float = 0.0) -> float:
    """مقدار واقعی یک فیلد قابلیت در لول فعلی با step و cap/floor مستقل."""
    if not ability or field not in ability:
        return float(default)
    value = float(ability.get(field, default))
    value += float(ability.get(f"{field}_step", 0.0)) * max(0, int(level or 1) - 1)
    cap = ability.get(f"{field}_cap")
    floor = ability.get(f"{field}_floor")
    if cap is not None:
        value = min(value, float(cap))
    if floor is not None:
        value = max(value, float(floor))
    return value


def gear_ability_primary(ability: dict | None) -> str | None:
    """فیلد اصلی قابل نمایش قابلیت؛ برای کارت ارتقا و تست‌ها."""
    if not ability:
        return None
    for field in (
        "chance", "pierce", "leech", "bonus", "crit_bonus", "reflect", "reduce",
        "crit_cut", "heal_pct", "damage_cap_pct", "revive_pct", "maxhp_damage",
        "double_chance",
    ):
        if field in ability:
            return field
    return None


def gear_ability_pct_now(ability: dict, level: int) -> float:
    """سازگاری UI قدیمی: درصد اصلی قابلیت را از موتور پله‌ای جدید برمی‌گرداند."""
    field = gear_ability_primary(ability)
    return gear_ability_value(ability, field, level) if field else 0.0


def gear_ability_change_text(ability: dict | None, level: int) -> tuple[int | None, int | None]:
    """درصد اصلی الان و لول بعد برای نمایش «الان ← بعد»."""
    field = gear_ability_primary(ability)
    if not field:
        return None, None
    now = int(round(gear_ability_value(ability, field, level) * 100))
    nxt = int(round(gear_ability_value(ability, field, min(config.GEAR_UPG_MAX, level + 1)) * 100))
    return now, nxt


