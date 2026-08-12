"""منطق خرید فروشگاه، مرکزی برای هندلرهای اینلاین و دستورهای متنی"""

from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import InventoryItem, User
from services import dogs as dog_svc
from services import economy, users
from services.farming import add_seed_stock
from utils import fa_num, money

# نوع کاتالوگ‌ها برای routing خرید
CATALOGS = {
    "weap": config.WEAPONS,
    "arm": config.ARMORS,
    "seed": config.SEEDS,
    "arti": config.ARTIFACTS,
}

KIND_EMOJI = {"weap": "🗡", "arm": "🛡", "seed": "🌱", "dog": "🐕", "arti": "🧿"}


def shop_seeds() -> dict:
    """بذرهای قابل خرید تو شاپ، افسانه‌ای‌ها 🔥😈 تو بازار سیاه/شاپ نمیان"""
    return {k: v for k, v in CATALOGS["seed"].items() if not v.get("legendary")}


async def purchase_resource(
    session: AsyncSession, user: User, res: str, qty: int
) -> tuple[bool, str]:
    """
    خرید دونه‌ای چوب/آهن از بخش منابع شاپ، فاکتور با تعداد دلخواه کاربره
    انبار پر باشه یا جا نمیرسه رد میشه، پول فقط موقع موفقیت کم میشه
    """
    from services.resources import add_res, iron_cap, wood_cap

    info = config.RES_SHOP.get(res)
    if not info:
        return False, "❌ همچین جنسی نیس"
    qty = int(qty)
    if qty < 1:
        return False, "❌ تعداد باید حداقل 1 باشه"
    total = info["unit"] * qty
    cur = user.wood if res == "wood" else user.iron
    cap = wood_cap(user) if res == "wood" else iron_cap(user)
    free = max(0, cap - (cur or 0))
    if qty > free:
        return False, (
            "❌ توی انبارت جای خالی برای اینهمه نداری\n"
            f"انبارت فقط جای {fa_num(free)} تا {info['name']} دیگه داره"
        )
    if user.cash < total:
        return False, f"❌ تی‌پوینتت کافی نیس، {money(total)} می‌خواد"
    user.cash -= total
    got = add_res(user, res, qty)
    return True, f"{info['emoji']} {fa_num(got)} {info['name']} خریدی، جمع {money(total)}"


def seed_unit_price(user: User, key: str) -> int:
    """قیمت دونه بذر (راند ۳۵: تخفیف لقب حذف شد؛ جریمه‌های چاپلوس جدید فروش و سرعت شرکت‌ان)"""
    return int(config.SEEDS.get(key, {}).get("price") or 0)


async def purchase_seed(
    session: AsyncSession, user: User, key: str, qty: int
) -> tuple[bool, str]:
    """
    خرید بذر با تعداد دلخواه (مثل فلوی آهن و چوب)
    خروجی: (موفق, پیام)، گیت لول و سقف انبار هر بذر و موجودی چک میشه
    """
    from services.world import seed_storage_cap
    from services.farming import get_stock

    item = config.SEEDS.get(key)
    if not item:
        return False, "❌ همچین بذری نیس"
    if item.get("legendary"):
        return False, "❌ این بذر افسانه‌ایه و تو شاپ فروخته نمیشه، از جستجو یا کاروان برمی‌داری"
    if user.level < item.get("min_level", 1):
        return False, f"🔒 لول {fa_num(item['min_level'])} می‌خواد"
    qty = int(qty)
    if qty < 1:
        return False, "❌ تعداد باید حداقل 1 باشه"

    cap = seed_storage_cap(user)
    stock = await get_stock(session, user.id)
    have = stock.get(key, 0)
    free = max(0, cap - have)
    if qty > free:
        return False, (
            f"🌾 انبار بذرت جا نداره، ظرفیت هر بذر {fa_num(cap)} تاست\n"
            f"الان {fa_num(have)} تا {item['name']} داری، فقط {fa_num(free)} تا دیگه جا داری؛ با «انبار» بیشترش کن"
        )
    unit = seed_unit_price(user, key)
    total = unit * qty
    if user.cash < total:
        return False, f"❌ تی‌پوینتت کافی نیس، {money(total)} می‌خواد"

    user.cash -= total
    await add_seed_stock(session, user.id, key, qty)
    return True, f"{item.get('emoji', '🌱')} {fa_num(qty)} بذر {item['name']} خریدی، جمع {money(total)}، انبارت شد {fa_num(have + qty)} تا"


async def purchase(
    session: AsyncSession, user: User, kind: str, key: str, dog_name: str | None = None
) -> tuple[bool, str]:
    """
    خرید از هر بخش فروشگاه
    خروجی: (موفق, پیام کوتاه)
    """
    if kind == "dog":
        if dog_name:
            # اسمشو تو همون دستور داده، خرید مستقیم
            return await dog_svc.buy_dog(session, user, key, custom_name=dog_name)
        # بعد از پرداخت اسمشو ازش می‌پرسیم
        return await dog_svc.hold_dog(session, user, key)

    catalog = CATALOGS.get(kind)
    if not catalog:
        return False, "❌ همچین بخشی نیس"

    item = catalog.get(key)
    if not item:
        return False, "❌ همچین جنسی نیس"

    # گیت لول
    min_level = item.get("min_level", 1)
    if kind == "arti":
        min_level = max(min_level, config.ARTIFACT_MIN_LEVEL)
    if user.level < min_level:
        return False, f"🔒 لول {fa_num(min_level)} می‌خواد"

    # سلاح و زره و آرتیفکت یه بار خرید میشن
    if kind in ("weap", "arm", "arti"):
        owned = await users.get_item_keys(session, user.id)
        store_key = f"arti_{key}" if kind == "arti" else key
        if store_key in owned:
            return False, "اینو داری که"

    if user.cash < item["price"]:
        return False, "❌ تی‌پوینتت کافی نیس"

    # سلاح علاوه بر پول آهن هم می‌خواد
    need_iron = item.get("iron", 0) if kind == "weap" else 0
    if need_iron and user.iron < need_iron:
        return False, f"⛏️ {fa_num(need_iron)} آهن می‌خواد و {fa_num(user.iron)} تا داری"

    # راند ۲۳ (درخواست کارفرما): ساخت سلاح ویژه ۱ تا ۳ قطعه افسانه‌ای هم می‌خواد
    # راند ۲۶ (درخواست کارفرما): زره ویژه هم قطعه افسانه‌ای می‌خواد (plasma/void ۱، neutron ۲، gods ۳)
    if kind == "weap":
        need_parts = config.SPECIAL_WEAPON_PARTS.get(key, 0)
    elif kind == "arm":
        need_parts = config.SPECIAL_ARMOR_PARTS.get(key, 0)
    else:
        need_parts = 0
    if need_parts and int(getattr(user, "legendary_parts", 0) or 0) < need_parts:
        return False, f"{config.LEGENDARY_PART_NAME} ×{fa_num(need_parts)} می‌خواد و {fa_num(int(getattr(user, 'legendary_parts', 0) or 0))} تا داری"

    # بذر افسانه‌ای قابل خرید نیس، فقط از جستجو/کاروان/ایونت
    if kind == "seed" and item.get("legendary"):
        return False, "❌ این بذر افسانه‌ایه و تو شاپ فروخته نمیشه، از جستجو یا کاروان برمی‌داری"

    if kind == "seed":
        from services.world import seed_storage_cap
        from services.farming import get_stock
        cap = seed_storage_cap(user)
        stock = await get_stock(session, user.id)
        if stock.get(key, 0) >= cap:
            return False, f"🌾 انبارت پره، ظرفیت هر بذر {fa_num(cap)} تاست؛ با «انبار» بیشترش کن"

    user.cash -= item["price"]
    if need_iron:
        user.iron -= need_iron
    if need_parts:
        user.legendary_parts = int(getattr(user, "legendary_parts", 0) or 0) - need_parts

    if kind in ("weap", "arm"):
        ammo = None
        if kind == "weap":
            from services import combat as _cbt  # تفنگ تازه خشابش پره (راند ۲۹)
            ammo = _cbt.ammo_cap(key, 1) if _cbt.is_gun(key) else None
        session.add(InventoryItem(user_id=user.id, item_key=key, ammo=ammo))
    elif kind == "arti":
        session.add(InventoryItem(user_id=user.id, item_key=f"arti_{key}"))
    elif kind == "seed":
        await add_seed_stock(session, user.id, key, 1)

    emoji = KIND_EMOJI.get(kind, "🎉")
    return True, f"{emoji} {item['name']} خریداری شد"


def find_shop_item(query: str) -> tuple[str | None, str | None, dict | None]:
    """
    پیدا کردن آیتم از اسم، ترتیب جستجو: سلاح → زره → بذر
    خروجی: (kind, key, item)
    """
    from utils import find_by_name

    for kind, catalog in CATALOGS.items():
        key, item = find_by_name(catalog, query)
        if key:
            return kind, key, item
    return None, None, None
