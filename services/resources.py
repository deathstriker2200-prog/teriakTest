"""
منابع 🪵⛏: چوب و آهن + ابزارهای کنده‌کاری (تبر/کلنگ)

ظرفیت‌ها با لول مخفیگاه رشد می‌کنن
همه ضرایب و قیمت‌ها توی config.py ن (RES_*, MINE_*, TOOLS)
"""

import random

import config
from models import User


# ───────── ظرفیت ─────────

def _table_cap(table: list, level: int) -> int:
    idx = min(max(int(level or 0), 0), len(table) - 1)
    return table[idx]


def wood_cap(user: User) -> int:
    return _table_cap(config.RES_WOOD_CAP_TABLE, user.shelter_level)


def iron_cap(user: User) -> int:
    return _table_cap(config.RES_IRON_CAP_TABLE, user.shelter_level)


def res_cap(user: User, res: str) -> int:
    return wood_cap(user) if res == "wood" else iron_cap(user)


# ───────── واریز/برداشت با سقف ─────────

def add_res(user: User, res: str, amount: int) -> int:
    """واریز با سقف انبار، خروجی: مقدار واقعی واریزشده"""
    if amount <= 0:
        return 0
    cur = getattr(user, res, 0)
    got = max(0, min(amount, res_cap(user, res) - cur))
    setattr(user, res, cur + got)
    return got


def take_res(user: User, res: str, amount: int) -> bool:
    """کم‌کردن منبع، فقط وقتی موجودی کافیه"""
    if getattr(user, res, 0) < amount:
        return False
    setattr(user, res, getattr(user, res, 0) - amount)
    return True


# ───────── فروش منابع (بخش مخفیگاه 💰) ─────────

def sell_price(res: str) -> int:
    """قیمت پایه فروش هر دونه منابع (بدون ضریب بازار)"""
    return config.RES_SELL_PRICES[res]


def sell_price_market(mults: dict[str, float], res: str) -> int:
    """قیمت فروش واقعی هر دونه با ضریب بازار سیاه (راند ۳۰، درخواست کارفرما)"""
    return max(1, int(config.RES_SELL_PRICES[res] * mults.get(res, 1.0)))


def sell_resource(user: User, res: str, amount: int, unit_price: int | None = None) -> tuple[bool, str, int]:
    """فروش منابع از مخفیگاه، خروجی: (اوکی, پیام خطا، مبلغ واریزی)
    راند ۳۰: unit_price ضریب بازار سیاه رو از هندلر می‌گیره، نباشه قیمت پایه‌ست"""
    if res not in config.RES_SELL_PRICES:
        return False, "❌ همچین جنسی فروختی نیس", 0
    if amount <= 0:
        return False, "❌ تعدادشو درست بگو", 0
    if not take_res(user, res, amount):
        return False, "❌ این همه نداری که بفروشی", 0
    total = amount * (unit_price if unit_price else sell_price(res))
    user.cash += total
    return True, "", total


# ───────── ابزارها (تبر/کلنگ) ─────────

def tool_level(user: User, tool_key: str) -> int:
    return user.axe_level if tool_key == "axe" else user.pick_level


def tool_upgrade_cost(tool_key: str, from_level: int) -> tuple[int, int] | None:
    """(تی‌پوینت, آهن) رفتن به لول بعد، None یعنی مکس"""
    cfg = config.TOOLS[tool_key]
    if from_level >= config.TOOL_MAX_LEVEL:
        return None
    return cfg["upgrades"][from_level - 1]


def tool_chance(user: User, tool_key: str, base: float) -> float:
    """شانس دراپ منبع با بونس لول ابزار خودش"""
    cfg = config.TOOLS[tool_key]
    return min(0.95, base + cfg["chance_per_level"] * max(0, tool_level(user, tool_key) - 1))


def tool_amount_mult(user: User, tool_key: str) -> float:
    cfg = config.TOOLS[tool_key]
    return 1 + cfg["amount_per_level"] * max(0, tool_level(user, tool_key) - 1)


def mine_cash_mult(user: User) -> float:
    """تی‌پوینت کنده‌کاری با بونس هر دو ابزار"""
    lv = (user.axe_level - 1) + (user.pick_level - 1)
    return 1 + config.TOOL_CASH_PER_LEVEL * lv


def mine_xp_mult(user: User) -> float:
    """تجربه کنده‌کاری هم با بونس هر دو ابزار رشد می‌کنه"""
    lv = (user.axe_level - 1) + (user.pick_level - 1)
    return 1 + config.TOOL_XP_PER_LEVEL * lv


def mine_rare_chance(user: User) -> float:
    """شانس شکار کمیاب با بونس هر دو ابزار"""
    lv = (user.axe_level - 1) + (user.pick_level - 1)
    return config.MINE_RARE_CHANCE + config.TOOL_RARE_PER_LEVEL * lv


# ───────── قرعه کنده‌کاری ─────────

def mine_loot(user: User) -> dict:
    """
    دراپ هر بار کنده‌کاری: تی‌پوینت + تجربه + شانسی چوب/آهن (+ ضربه کمیاب)
    خروجی: {"cash":…, "xp":…, "wood":…, "iron":…, "rare":bool}
    """
    from services import economy

    cash = int(economy.mine_roll() * mine_cash_mult(user))
    xp = max(1, int(random.randint(config.MINE_XP_MIN, config.MINE_XP_MAX) * mine_xp_mult(user)))
    wood, iron = 0, 0
    rare = random.random() < mine_rare_chance(user)

    if rare:
        # شکار کمیاب: چوب و آهن حتمی میفتن و همه درآمد ×مقدار کمیاب
        boost = config.MINE_RARE_MULT
        cash *= boost
        xp *= boost
        wood = max(1, int(random.randint(config.MINE_WOOD_MIN, config.MINE_WOOD_MAX)
                          * tool_amount_mult(user, "axe"))) * boost
        iron = max(1, int(random.randint(config.MINE_IRON_MIN, config.MINE_IRON_MAX)
                          * tool_amount_mult(user, "pick"))) * boost
    else:
        if random.random() < tool_chance(user, "axe", config.MINE_WOOD_CHANCE):
            wood = random.randint(config.MINE_WOOD_MIN, config.MINE_WOOD_MAX)
            wood = max(1, int(wood * tool_amount_mult(user, "axe")))
        if random.random() < tool_chance(user, "pick", config.MINE_IRON_CHANCE):
            iron = random.randint(config.MINE_IRON_MIN, config.MINE_IRON_MAX)
            iron = max(1, int(iron * tool_amount_mult(user, "pick")))

    return {"cash": cash, "xp": xp, "wood": wood, "iron": iron, "rare": rare}
