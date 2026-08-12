"""
🏭 شرکت: چوب‌بری و کارخانه آهن، تولید خودکار منابع چوب و آهن

تولید lazy حساب میشه و تو انبار خود کارخونه (stock) جمع میشه
ظرفیت انبار با هر ارتقا بیشتر میشه و ۱۲ ساعت طول میکشه از خالی پر شه
بازیکن با دکمه «📥 برداشت» خودش خالی‌ش می‌کنه تو انبارش
انبار پر = تولید متوقفه، همه اعداد تو config.py ن
"""

from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import User
from services.resources import add_res, take_res
from services.snitch import khaye_active
from utils import fa_num, money, now_utc


def factory_level(user: User, fac_key: str) -> int:
    return user.lumber_level if fac_key == "lumber" else user.ironmill_level


def company_locked(user: User) -> bool:
    """کارخونه زیر لول حداقل شرکت قفله، ولی لول کارخونه‌ش دست نمی‌خوره و با رسیدن لول باز میشه"""
    return (getattr(user, "level", None) or 1) < config.COMPANY_MIN_LEVEL


def _set_level(user: User, fac_key: str, level: int) -> None:
    if fac_key == "lumber":
        user.lumber_level = level
    else:
        user.ironmill_level = level


def factory_production(fac_key: str, level: int) -> float:
    """تولید هر تیک (۱۰ دقیقه) | راند ۲۱ نصف شد و آهن اعشاریه (۲٫۵)، جاهای مصرف int می‌گیرن"""
    return config.FACTORIES[fac_key]["per_tick"] * level


def factory_stock(user: User, fac_key: str) -> int:
    """موجودی انبار خود کارخونه"""
    return user.lumber_stock if fac_key == "lumber" else user.ironmill_stock


def _set_stock(user: User, fac_key: str, val: int) -> None:
    if fac_key == "lumber":
        user.lumber_stock = val
    else:
        user.ironmill_stock = val


def factory_stock_cap(fac_key: str, level: int) -> int:
    """ظرفیت انبار کارخونه، جوری تنظیم شده که تو ۱۲ ساعت از خالی پر شه"""
    return int(factory_production(fac_key, level) * config.FACTORY_FILL_TICKS)


def build_cost(fac_key: str) -> tuple[int, int]:
    """(تی‌پوینت, چوب) ساخت از صفر"""
    return config.FACTORIES[fac_key]["build"]


def upgrade_cost(fac_key: str, to_level: int) -> tuple[int, int]:
    """(تی‌پوینت, چوب) ارتقا به لول to_level از جدول دستی کانفیگ (اندیس ۰ = رفتن به لول ۲)"""
    cfg = config.FACTORIES[fac_key]
    idx = min(max(to_level - 2, 0), len(cfg["up_tp"]) - 1)
    return cfg["up_tp"][idx], cfg["up_wood"][idx]


# ───────── تسویه تولید ─────────

async def settle(session: AsyncSession, user: User) -> dict:
    """
    تیک‌های گذشته رو به انبار خود کارخونه اضافه می‌کنه (با سقف ظرفیت انبار)
    انبار پر = تولید متوقفه و تیک‌های اضافه سوخت میشن
    خروجی: {"wood":…, "iron":…, "ticks":…} مقدار واقعی ریخته‌شده تو انبار کارخونه
    """
    now = now_utc()
    if user.company_at is None:
        user.company_at = now
        return {"wood": 0, "iron": 0, "ticks": 0}

    elapsed = int((now - user.company_at).total_seconds())
    ticks = elapsed // config.FACTORY_TICK_SECONDS
    if ticks <= 0:
        return {"wood": 0, "iron": 0, "ticks": 0}

    got = {"wood": 0, "iron": 0, "ticks": ticks}
    # لقب چاپلوس: سرعت تولید شرکت‌ها کمتره (راند ۳۵، متن قطعی اعلان)
    prod_mult = (1 - config.KHAYE_COMPANY_SLOW) if khaye_active(user) else 1.0
    for key, cfg in config.FACTORIES.items():
        lv = factory_level(user, key)
        if lv <= 0:
            continue
        cap = factory_stock_cap(key, lv)
        cur = factory_stock(user, key)
        added = min(int(factory_production(key, lv) * ticks * prod_mult), max(0, cap - cur))
        if added > 0:
            _set_stock(user, key, cur + added)
        got[cfg["res"]] = added

    user.company_at = user.company_at + ticks_delta(ticks)
    return got


async def collect(session: AsyncSession, user: User, fac_key: str) -> tuple[bool, str]:
    """برداشت تولید از انبار کارخونه، هرچی انبار بازیکن جا داشته باشه منتقل میشه"""
    cfg = config.FACTORIES[fac_key]
    if factory_level(user, fac_key) <= 0:
        return False, f"{cfg['emoji']} اول {cfg['name']} رو بساز"
    if company_locked(user):
        return False, f"🔒 شرکتت تا لول {fa_num(config.COMPANY_MIN_LEVEL)} قفله، کارخونه‌ات سر جاشه و پاک نشده، لولت که رسید خودش باز میشه"
    stock = factory_stock(user, fac_key)
    if stock <= 0:
        return False, f"📥 انبار {cfg['name']} فعلا خالیه، هنوز چیزی تولید نشده"
    moved = add_res(user, cfg["res"], stock)
    if moved <= 0:
        return False, f"🏚 انبارت پره، اول جا باز کن بعد بیا برداشت کن"
    _set_stock(user, fac_key, stock - moved)
    unit = "چوب" if cfg["res"] == "wood" else "آهن"
    if moved < stock:
        return True, f"📥 {fa_num(moved)} {unit} برداشت شد، انبارت پر شد و {fa_num(stock - moved)} تا موند تو کارخونه"
    return True, f"📥 {fa_num(moved)} {unit} از کارخونه برداشت شد"


def ticks_delta(ticks: int):
    from datetime import timedelta
    return timedelta(seconds=ticks * config.FACTORY_TICK_SECONDS)


# ───────── ساخت و ارتقا ─────────

async def build(session: AsyncSession, user: User, fac_key: str) -> tuple[bool, str]:
    cfg = config.FACTORIES[fac_key]
    if factory_level(user, fac_key) > 0:
        return False, f"{cfg['emoji']} {cfg['name']} رو که ساختی"
    if company_locked(user):
        return False, f"🔒 ساخت شرکت از لول {fa_num(config.COMPANY_MIN_LEVEL)} باز میشه، فعلا لولت کمه"
    tp, wood = build_cost(fac_key)
    if user.cash < tp:
        return False, "❌ تی‌پوینتت کافی نیس"
    if user.wood < wood:
        return False, f"🪵 {fa_num(wood)} چوب می‌خواد و {fa_num(user.wood)} تا داری"
    user.cash -= tp
    take_res(user, "wood", wood)
    _set_level(user, fac_key, 1)
    if user.company_at is None:
        user.company_at = now_utc()
    return True, f"{cfg['emoji']} {cfg['name']} راه اومد"


async def upgrade(session: AsyncSession, user: User, fac_key: str) -> tuple[bool, str]:
    cfg = config.FACTORIES[fac_key]
    if company_locked(user) and factory_level(user, fac_key) > 0:
        return False, f"🔒 شرکتت تا لول {fa_num(config.COMPANY_MIN_LEVEL)} قفله، کارخونه‌ات سر جاشه و پاک نشده، لولت که رسید خودش باز میشه"
    cur = factory_level(user, fac_key)
    if cur >= config.FACTORY_MAX_LEVEL:
        return False, "👑 این ساختمان لول مکسه"
    tp, wood = upgrade_cost(fac_key, cur + 1)
    if user.cash < tp:
        return False, "❌ تی‌پوینتت کافی نیس"
    if user.wood < wood:
        return False, f"🪵 {fa_num(wood)} چوب می‌خواد و {fa_num(user.wood)} تا داری"
    user.cash -= tp
    take_res(user, "wood", wood)
    _set_level(user, fac_key, cur + 1)
    return True, f"{cfg['emoji']} {cfg['name']} رفت رو لول {fa_num(cur + 1)}"


# ───────── متن‌ها ─────────

def company_text(user: User, got: dict | None = None) -> str:
    """متن صفحه شرکت، هر ساختمان بلاک خودشو داره: وضعیت تولید/توقف، انبار کارخونه و سرعت ساعتی"""
    lines = ["<b>🏭 شرکت</b>", ""]
    lines.append(f"🪵 چوب {fa_num(user.wood)} | ⛏️ آهن {fa_num(user.iron)}")
    has_factory = any(factory_level(user, k) > 0 for k in config.FACTORIES)
    if company_locked(user) and has_factory:
        lines.append(f"🔒 شرکتت تا لول {fa_num(config.COMPANY_MIN_LEVEL)} قفله، کارخونه‌ات سر جاشه و با رسیدن لول باز میشه")
    if got and (got["wood"] or got["iron"]):
        parts = []
        if got["wood"]:
            parts.append(f"🪵 {fa_num(got['wood'])} چوب")
        if got["iron"]:
            parts.append(f"⛏️ {fa_num(got['iron'])} آهن")
        lines.append(f"📥 تولید اومد تو انبار کارخونه: {' + '.join(parts)}")

    res_name = {"lumber": "چوب", "ironmill": "آهن"}
    ticks_per_hour = 3600 // config.FACTORY_TICK_SECONDS
    # لقب چاپلوس: افت سرعت تو نمایش هم دیده میشه (راند ۳۵)
    prod_mult = (1 - config.KHAYE_COMPANY_SLOW) if khaye_active(user) else 1.0
    if prod_mult < 1.0:
        lines.append(f"🏭 لقب چاپلوس: سرعت شرکت‌هات {fa_num(int(config.KHAYE_COMPANY_SLOW * 100))}% کمتره")
    for key, cfg in config.FACTORIES.items():
        lv = factory_level(user, key)
        lines.append("")
        lines.append(f"<b>{cfg['emoji']} {cfg['name']}</b>")
        if lv <= 0:
            tp, wood = build_cost(key)
            cost = money(tp)
            if wood:
                cost += f" + 🪵 {fa_num(wood)} چوب"
            lines.append("وضعیت: ساخته نشده")
            lines.append(f"هزینه ساخت: {cost}")
        else:
            stock = factory_stock(user, key)
            cap = factory_stock_cap(key, lv)
            full = stock >= cap
            status = "متوقف شده 🔴" if full else "در حال تولید 🟢"
            per_hour = int(factory_production(key, lv) * ticks_per_hour * prod_mult)
            lines.append(f"وضعیت {cfg['name']}: {status} (لول {fa_num(lv)})")
            lines.append(f"📦 انبار کارخونه: {fa_num(stock)}/{fa_num(cap)}")
            lines.append(f"⚙️ سرعت تولید: {fa_num(per_hour)} {res_name[key]} در ساعت")
            if full:
                lines.append("انبارش پره، اول برداشت بزن تا تولید دوباره شروع شه")
    return "\n".join(lines)
