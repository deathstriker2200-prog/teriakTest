"""
مارکت بازیکن‌ها 🛒 (راند ۲۳، درخواست کارفرما)
خرید و فروش قطعه افسانه‌ای | چوب | آهن بین خود بازیکن‌ها
آگهی ۲۴ ساعت مهلت داره، نرفته → باطل میشه و جنس خودش برمی‌گرده دست صاحبش
لیست با صفحه‌بندی ۱۰تایی، مرتب‌سازی ارزون‌تر/گرون‌تر و فیلتر آیتم
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import MarketListing, User
from utils import money, now_utc

# موجودی جنس هر کاربر روی ستون‌های خودشه، با getattr که آبجکت‌های لین هم بخورن


def qty_of(user: User, item: str) -> int:
    if item == "part":
        return int(getattr(user, "legendary_parts", 0) or 0)
    if item == "wood":
        return int(getattr(user, "wood", 0) or 0)
    return int(getattr(user, "iron", 0) or 0)


def give(user: User, item: str, n: int) -> None:
    if item == "part":
        user.legendary_parts = qty_of(user, "part") + n
    elif item == "wood":
        user.wood = qty_of(user, "wood") + n
    else:
        user.iron = qty_of(user, "iron") + n


def take(user: User, item: str, n: int) -> bool:
    """کم کردن موجودی، اگه کم داشت False و دست نمی‌خوره"""
    if qty_of(user, item) < n:
        return False
    give(user, item, -n)
    return True


# ───────── جاروی آگهی‌های باطل (۲۴ ساعت) ─────────

async def sweep_expired(session: AsyncSession) -> int:
    """آگهی‌های قدیمی‌تر از TTL باطل میشن و جنسشون به فروشنده برمی‌گرده، خروجی تعداد باطل‌شده"""
    cutoff = now_utc() - timedelta(hours=config.MARKET_TTL_HOURS)
    q = select(MarketListing).where(MarketListing.created_at < cutoff)
    rows = list((await session.execute(q)).scalars())
    n = 0
    for row in rows:
        seller = await session.get(User, row.seller_id)
        if seller is not None:
            give(seller, row.item, row.qty)
        await session.delete(row)
        n += 1
    return n


# ───────── ثبت آگهی ─────────

async def create_listing(session: AsyncSession, user: User, item: str, qty: int, price: int) -> tuple[bool, str | MarketListing]:
    """
    ثبت آگهی فروش: جنس همون لحظه از فروشنده کم میشه و می‌ره روی میز مارکت
    خروجی: (موفق، پیام خطا یا خود آگهی)
    """
    if item not in config.MARKET_ITEMS:
        return False, "❌ این جنس تو مارکت فروخته نمیشه"
    if qty <= 0 or qty > config.MARKET_MAX_QTY:
        return False, f"❌ تعداد باید بین ۱ تا {config.MARKET_MAX_QTY:,} باشه"
    if price <= 0 or price > config.MARKET_MAX_PRICE:
        return False, f"❌ قیمت باید بین ۱ تا {config.MARKET_MAX_PRICE:,} تی‌پوینت باشه"
    q_open = select(func.count(MarketListing.id)).where(MarketListing.seller_id == user.id)
    n_open = int((await session.execute(q_open)).scalar() or 0)
    if n_open >= config.MARKET_MAX_PER_USER:
        return False, f"❌ آگهی بازتو به {config.MARKET_MAX_PER_USER} تا رسیده، یکی رو لغو کن بعد آگهی جدید بذار"
    have = qty_of(user, item)
    if have < qty:
        return False, "nostock"
    take(user, item, qty)
    row = MarketListing(
        seller_id=user.id,
        seller_name=(user.first_name or user.username or "رفیق")[:64],
        item=item,
        qty=qty,
        price=price,
    )
    session.add(row)
    await session.flush()
    return True, row


# ───────── خواندن لیست ─────────

async def count_listings(session: AsyncSession, item: str | None = None) -> int:
    q = select(func.count(MarketListing.id))
    if item:
        q = q.where(MarketListing.item == item)
    return int((await session.execute(q)).scalar() or 0)


async def fetch_page(session: AsyncSession, item: str | None, page: int, desc: bool) -> tuple[list[MarketListing], int, int]:
    """
    یه صفحه از آگهی‌ها (۱۰تایی) + (شماره صفحه معتبر، تعداد کل صفحه‌ها)
    صفحه خواسته‌شده از ته اومد بیرون، آخرین صفحه داده میشه
    """
    order = MarketListing.price.desc() if desc else MarketListing.price.asc()
    q = select(MarketListing)
    if item:
        q = q.where(MarketListing.item == item)
    q = q.order_by(order, MarketListing.id.asc())
    rows = list((await session.execute(q)).scalars())
    size = config.MARKET_PAGE_SIZE
    pages = max(1, (len(rows) + size - 1) // size)
    page = max(0, min(page, pages - 1))
    return rows[page * size:(page + 1) * size], page, pages


async def get_listing(session: AsyncSession, listing_id: int) -> MarketListing | None:
    return await session.get(MarketListing, listing_id)


# ───────── آگهی‌های خود کاربر (راند ۲۶، درخواست کارفرما) ─────────

async def my_listings(session: AsyncSession, user_id: int) -> list[MarketListing]:
    """آگهی‌های باز خود کاربر به ترتیب ثبت"""
    q = select(MarketListing).where(MarketListing.seller_id == user_id).order_by(MarketListing.id)
    return list((await session.execute(q)).scalars())


async def cancel_listing(session: AsyncSession, user: User, listing_id: int) -> tuple[bool, MarketListing | None]:
    """لغو آگهی توسط صاحبش: جنس سالم برمی‌گرده انبارش، آگهی پاک میشه (فقط آگهی خودش)"""
    row = await session.get(MarketListing, listing_id)
    if row is None or row.seller_id != user.id:
        return False, None
    give(user, row.item, row.qty)
    await session.delete(row)
    return True, row


# ───────── خرید ─────────

async def buy_listing(session: AsyncSession, buyer: User, listing_id: int) -> tuple[str, dict]:
    """
    خرید آگهی: پول از جیب خریدار به فروشنده میره و جنس مال خریدار
    خروجی: (وضعیت، اطلاعات) → status: gone | own | poor | full | ok
    راند ۴۰ (درخواست کارفرما): چوب و آهن سقف انبار مخفیگاه دارن، جا نبود خرید انجام نمیشه
    """
    row = await session.get(MarketListing, listing_id)
    if row is None:
        return "gone", {}
    if row.seller_id == buyer.id:
        return "own", {"row": row}
    if buyer.cash < row.price:
        return "poor", {"row": row}
    if row.item in ("wood", "iron"):
        from services.resources import res_cap
        cur = qty_of(buyer, row.item)
        cap = res_cap(buyer, row.item)
        if cur + row.qty > cap:
            return "full", {"row": row, "cap": cap, "have": cur}
    buyer.cash -= row.price
    seller = await session.get(User, row.seller_id)
    if seller is not None:
        seller.cash = (seller.cash or 0) + row.price
    give(buyer, row.item, row.qty)
    info = {
        "item": row.item,
        "qty": row.qty,
        "price": row.price,
        "seller_id": row.seller_id,
        "seller_name": row.seller_name,
    }
    await session.delete(row)
    return "ok", info


# ───────── هدیه قطعه افسانه‌ای 🎁 ─────────

async def gift_parts(session: AsyncSession, sender: User, recipient: User, n: int) -> tuple[bool, str]:
    """هدیه قطعه افسانه‌ای به رفیق (فعلاً فقط همین جنس، درخواست کارفرما)"""
    if recipient.id == sender.id:
        return False, "😅 به خودت که هدیه نمی‌دی، همینجوری نگهدارشون"
    if n < config.GIFT_PART_MIN:
        return False, f"❌ حداقل {config.GIFT_PART_MIN} قطعه باید هدیه بدی"
    have = qty_of(sender, "part")
    if have < n:
        return False, f"❌ {n} قطعه نداری که، انبارت {have} تاست"
    take(sender, "part", n)
    give(recipient, "part", n)
    return True, ""


def money_of_price(row: MarketListing) -> str:
    return money(row.price)
