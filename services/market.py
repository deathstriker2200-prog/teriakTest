"""
مارکت بازیکن‌ها 🛒 (راند ۲۳، درخواست کارفرما)
خرید و فروش قطعه افسانه‌ای | چوب | آهن بین خود بازیکن‌ها
آگهی ۲۴ ساعت مهلت داره، نرفته → باطل میشه و جنس خودش برمی‌گرده دست صاحبش
لیست با صفحه‌بندی ۱۰تایی، مرتب‌سازی ارزون‌تر/گرون‌تر و فیلتر آیتم
"""

from datetime import timedelta

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import MarketListing, User
from utils import money, now_utc

# موجودی جنس هر کاربر روی ستون‌های خودشه، با getattr که آبجکت‌های لین هم بخورن


def qty_of(user: User, item: str) -> int:
    if item == "part":
        return int(getattr(user, "legendary_parts", 0) or 0)
    if item == "fragment":
        return int(getattr(user, "boss_fragments", 0) or 0)
    if item == "wood":
        return int(getattr(user, "wood", 0) or 0)
    if item == "iron":
        return int(getattr(user, "iron", 0) or 0)
    return 0


def give(user: User, item: str, n: int) -> None:
    if item == "part":
        user.legendary_parts = qty_of(user, "part") + n
    elif item == "fragment":
        user.boss_fragments = qty_of(user, "fragment") + n
    elif item == "wood":
        user.wood = qty_of(user, "wood") + n
    elif item == "iron":
        user.iron = qty_of(user, "iron") + n


def take(user: User, item: str, n: int) -> bool:
    """کم کردن موجودی، اگه کم داشت False و دست نمی‌خوره"""
    if qty_of(user, item) < n:
        return False
    give(user, item, -n)
    return True


def return_room(user: User, item: str) -> int | None:
    """جای خالی واقعی برای برگشت آگهی؛ قطعه افسانه‌ای سقف نداره."""
    if item in ("part", "fragment"):
        return None
    if item in ("wood", "iron"):
        from services.resources import res_cap
        return max(0, res_cap(user, item) - qty_of(user, item))
    return 0


def can_return(user: User, item: str, qty: int) -> bool:
    room = return_room(user, item)
    return room is None or qty <= room


def _item_column(item: str):
    return {
        "part": User.legendary_parts,
        "fragment": User.boss_fragments,
        "wood": User.wood,
        "iron": User.iron,
    }.get(item)


def _resource_capacity_expr(item: str):
    """ظرفیت چوب/آهن به‌شکل SQL تا شرط سقف داخل همان UPDATE اتمیک باشد."""
    table = config.RES_WOOD_CAP_TABLE if item == "wood" else config.RES_IRON_CAP_TABLE
    whens = [(User.shelter_level <= 0, table[0])]
    whens.extend((User.shelter_level == level, cap) for level, cap in enumerate(table[1:-1], 1))
    return case(*whens, else_=table[-1])


async def _lock_user_rows(session: AsyncSession, *user_ids: int) -> bool:
    """کاربران درگیر را همیشه با ترتیب ID قفل می‌کند تا خریدهای متقاطع deadlock نسازند."""
    ids = sorted({int(uid) for uid in user_ids if uid is not None})
    if not ids:
        return False
    with session.no_autoflush:
        found = set((await session.execute(
            select(User.id).where(User.id.in_(ids)).order_by(User.id).with_for_update()
        )).scalars())
    return found == set(ids)


async def _refresh_market_user(session: AsyncSession, user: User) -> None:
    await session.refresh(
        user,
        ["cash", "wood", "iron", "legendary_parts", "boss_fragments", "shelter_level"],
    )


async def _locked_listing(session: AsyncSession, listing_id: int) -> MarketListing | None:
    with session.no_autoflush:
        return (await session.execute(
            select(MarketListing)
            .where(MarketListing.id == listing_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()


async def _atomic_take_item(session: AsyncSession, user_id: int, item: str, qty: int) -> bool:
    col = _item_column(item)
    if col is None:
        return False
    result = await session.execute(
        update(User)
        .where(User.id == user_id, col >= qty)
        .values({col.key: col - qty})
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0) == 1


async def _atomic_return_item(session: AsyncSession, user_id: int, item: str, qty: int) -> bool:
    """برگشت escrow؛ برای چوب/آهن شرط ظرفیت داخل خود UPDATE است و قابل race نیست."""
    col = _item_column(item)
    if col is None:
        return False
    conditions = [User.id == user_id]
    if item in ("wood", "iron"):
        conditions.append(col + qty <= _resource_capacity_expr(item))
    result = await session.execute(
        update(User)
        .where(*conditions)
        .values({col.key: col + qty})
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0) == 1


async def _claim_listing(
    session: AsyncSession,
    listing_id: int,
    *,
    seller_id: int | None = None,
    expired_before=None,
) -> bool:
    """DELETE اتمیک نقش claim دارد؛ فقط یک خرید/لغو/انقضا می‌تواند آگهی را تسویه کند."""
    stmt = delete(MarketListing).where(MarketListing.id == listing_id)
    if seller_id is not None:
        stmt = stmt.where(MarketListing.seller_id == seller_id)
    if expired_before is not None:
        stmt = stmt.where(MarketListing.created_at < expired_before)
    result = await session.execute(
        stmt.returning(MarketListing.id).execution_options(synchronize_session="fetch")
    )
    return result.scalar_one_or_none() is not None


async def _atomic_buy_for_user(
    session: AsyncSession,
    buyer_id: int,
    item: str,
    qty: int,
    price: int,
) -> bool:
    """پول و آیتم خریدار با هم و با شرط موجودی/ظرفیت در یک UPDATE تغییر می‌کنند."""
    col = _item_column(item)
    if col is None:
        return False
    conditions = [User.id == buyer_id, User.cash >= price]
    if item in ("wood", "iron"):
        conditions.append(col + qty <= _resource_capacity_expr(item))
    result = await session.execute(
        update(User)
        .where(*conditions)
        .values({"cash": User.cash - price, col.key: col + qty})
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0) == 1


# ───────── جاروی آگهی‌های باطل (۲۴ ساعت) ─────────

async def sweep_expired(session: AsyncSession) -> int:
    """
    انقضا هم مثل خرید claim اتمیک دارد. اگر انبار چوب/آهن پر باشد، escrow امن می‌ماند
    و زمان آگهی برای بررسی بعدی تازه می‌شود؛ نه گم می‌شود، نه تکثیر و نه از سقف رد می‌شود.
    """
    cutoff = now_utc() - timedelta(hours=config.MARKET_TTL_HOURS)
    with session.no_autoflush:
        candidate_ids = list((await session.execute(
            select(MarketListing.id).where(MarketListing.created_at < cutoff).order_by(MarketListing.id)
        )).scalars())
    n = 0
    for listing_id in candidate_ids:
        with session.no_autoflush:
            preview = await session.get(MarketListing, listing_id)
        if preview is None or not await _lock_user_rows(session, preview.seller_id):
            continue
        row = await _locked_listing(session, listing_id)
        if row is None or row.created_at >= cutoff:
            continue
        seller = await session.get(User, row.seller_id)
        if seller is not None:
            await _refresh_market_user(session, seller)
            if not can_return(seller, row.item, row.qty):
                row.created_at = now_utc()
                continue

        savepoint = await session.begin_nested()
        claimed = await _claim_listing(
            session, row.id, seller_id=row.seller_id, expired_before=cutoff,
        )
        returned = seller is None or (
            claimed and await _atomic_return_item(session, seller.id, row.item, row.qty)
        )
        if not claimed or not returned:
            await savepoint.rollback()
            continue
        await savepoint.commit()
        if seller is not None:
            await _refresh_market_user(session, seller)
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
    if not await _lock_user_rows(session, user.id):
        return False, "❌ صاحب موجودی پیدا نشد"
    await _refresh_market_user(session, user)
    q_open = select(func.count(MarketListing.id)).where(MarketListing.seller_id == user.id)
    n_open = int((await session.execute(q_open)).scalar() or 0)
    if n_open >= config.MARKET_MAX_PER_USER:
        return False, f"❌ آگهی بازتو به {config.MARKET_MAX_PER_USER} تا رسیده، یکی رو لغو کن بعد آگهی جدید بذار"
    if qty_of(user, item) < qty:
        return False, "nostock"
    if not await _atomic_take_item(session, user.id, item, qty):
        await _refresh_market_user(session, user)
        return False, "nostock"
    row = MarketListing(
        seller_id=user.id,
        seller_name=(user.first_name or user.username or "رفیق")[:64],
        item=item,
        qty=qty,
        price=price,
    )
    session.add(row)
    await session.flush()
    await _refresh_market_user(session, user)
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
    """
    لغو آگهی توسط صاحبش. False/None یعنی آگهی مال کاربر نیست؛ False/row یعنی انبار جا نداره.
    claim اتمیک تضمین می‌کند لغو هم‌زمان با خرید یا انقضا جنس را دوبار برنگرداند.
    """
    with session.no_autoflush:
        preview = await session.get(MarketListing, listing_id)
    if preview is None or preview.seller_id != user.id:
        return False, None
    if not await _lock_user_rows(session, user.id):
        return False, None
    row = await _locked_listing(session, listing_id)
    if row is None or row.seller_id != user.id:
        return False, None
    await _refresh_market_user(session, user)
    if not can_return(user, row.item, row.qty):
        return False, row

    savepoint = await session.begin_nested()
    claimed = await _claim_listing(session, row.id, seller_id=user.id)
    returned = claimed and await _atomic_return_item(session, user.id, row.item, row.qty)
    if not claimed or not returned:
        await savepoint.rollback()
        await _refresh_market_user(session, user)
        current = await _locked_listing(session, listing_id)
        return (False, current) if current is not None else (False, None)
    await savepoint.commit()
    await _refresh_market_user(session, user)
    return True, row


# ───────── خرید ─────────

async def buy_listing(session: AsyncSession, buyer: User, listing_id: int) -> tuple[str, dict]:
    """
    خرید اتمیک آگهی. پول و آیتم خریدار در یک UPDATE شرطی تغییر می‌کنند و DELETE آگهی
    نقش claim یک‌بارمصرف دارد؛ ظرفیت، پول و فروشنده بعد از قفل دوباره بررسی می‌شوند.
    """
    with session.no_autoflush:
        preview = await session.get(MarketListing, listing_id)
    if preview is None:
        return "gone", {}
    if preview.seller_id == buyer.id:
        return "own", {"row": preview}
    if not await _lock_user_rows(session, buyer.id, preview.seller_id):
        return "gone", {}
    row = await _locked_listing(session, listing_id)
    if row is None:
        return "gone", {}
    if row.seller_id == buyer.id:
        return "own", {"row": row}
    seller = await session.get(User, row.seller_id)
    if seller is None:
        return "gone", {"row": row}
    await _refresh_market_user(session, buyer)
    await _refresh_market_user(session, seller)
    if buyer.cash < row.price:
        return "poor", {"row": row}
    if row.item in ("wood", "iron"):
        from services.resources import res_cap
        cur = qty_of(buyer, row.item)
        cap = res_cap(buyer, row.item)
        if cur + row.qty > cap:
            return "full", {"row": row, "cap": cap, "have": cur}

    info = {
        "item": row.item,
        "qty": row.qty,
        "price": row.price,
        "seller_id": row.seller_id,
        "seller_name": row.seller_name,
    }
    savepoint = await session.begin_nested()
    claimed = await _claim_listing(session, row.id, seller_id=row.seller_id)
    bought = claimed and await _atomic_buy_for_user(
        session, buyer.id, row.item, row.qty, row.price,
    )
    paid = False
    if bought:
        paid_result = await session.execute(
            update(User)
            .where(User.id == row.seller_id)
            .values(cash=User.cash + row.price)
            .execution_options(synchronize_session=False)
        )
        paid = int(paid_result.rowcount or 0) == 1
    if not claimed or not bought or not paid:
        await savepoint.rollback()
        await _refresh_market_user(session, buyer)
        await _refresh_market_user(session, seller)
        if not claimed:
            return "gone", {}
        if buyer.cash < row.price:
            return "poor", {"row": row}
        if row.item in ("wood", "iron"):
            from services.resources import res_cap
            cap = res_cap(buyer, row.item)
            if qty_of(buyer, row.item) + row.qty > cap:
                return "full", {"row": row, "cap": cap, "have": qty_of(buyer, row.item)}
        return "gone", {}
    await savepoint.commit()
    await _refresh_market_user(session, buyer)
    await _refresh_market_user(session, seller)
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


