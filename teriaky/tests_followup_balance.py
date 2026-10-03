"""تست‌های تکمیلی زره نیمه‌خدایان، هزینه آزمایشگاه و ضد-dupe مارکت."""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from database import Base
from models import InventoryItem, LabWorker, MarketListing, User
from services import battle, economy, lab, market
from utils import now_utc

PASSED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    assert condition, f"❌ {name}: {detail}"
    PASSED += 1
    print(f"✅ {name}")


def make_user(
    tg: int,
    *,
    level: int = 30,
    cash: int = 1_000_000,
    wood: int = 0,
    iron: int = 0,
    shelter: int = 0,
    lab_level: int = 0,
) -> User:
    return User(
        telegram_id=tg,
        username=f"u{tg}",
        first_name=f"U{tg}",
        level=level,
        cash=cash,
        wood=wood,
        iron=iron,
        shelter_level=shelter,
        lab_level=lab_level,
    )


def test_static_config() -> None:
    demi = config.ARMORS["demigod"]
    gods = config.ARMORS["gods"]
    check(
        "نوترونی حفظ و زره نیمه‌خدایان مستقل اضافه شده",
        config.ARMORS["neutron"]["ability"]["kind"] == "neutron"
        and demi["name"] == "🪽 زره نیمه‌خدایان"
        and demi["ability"]["kind"] == "demigodshield",
    )
    check(
        "نیمه‌خدایان در همه لول‌های ارتقا فقط یک نجات دارد",
        [economy.armor_revive_charges(demi["ability"], lv) for lv in range(1, 6)] == [1, 1, 1, 1, 1],
    )
    check(
        "خدایان با ارتقا دقیقاً از دو تا چهار نجات می‌رسد",
        [economy.armor_revive_charges(gods["ability"], lv) for lv in range(1, 6)] == [2, 2, 3, 3, 4],
    )
    check(
        "جدول نهایی ساخت آزمایشگاه دقیقاً هزینه خیلی سنگین تأییدشده است",
        config.LAB_BUILD_COST == (500_000, 1_180, 630)
        and config.LAB_UPGRADE_COST == [
            (1_500_000, 1_960, 1_080),
            (4_000_000, 3_080, 2_200),
            (10_000_000, 3_700, 3_800),
        ],
    )
    check(
        "هر رده کارگر با لول متناظر خود آزمایشگاه باز می‌شود",
        [config.LAB_WORKERS[key]["unlock_lab_level"] for key in config.LAB_WORKER_ORDER] == [1, 2, 3, 4]
        and all("min_level" not in config.LAB_WORKERS[key] for key in config.LAB_WORKER_ORDER),
    )


async def test_real_revives(Session) -> None:
    async with Session() as session:
        attacker = make_user(31000, cash=1_000_000)
        session.add(attacker)
        await session.flush()
        session.add(InventoryItem(user_id=attacker.id, item_key="colt", level=1, ammo=100))
        attacker.equipped_weapon = "colt"

        cases = [
            ("demigod", 5, 1, 31001),
            ("gods", 1, 2, 31002),
            ("gods", 3, 3, 31003),
            ("gods", 5, 4, 31004),
        ]
        targets: list[tuple[User, int, str, int]] = []
        for armor_key, armor_level, expected, tg in cases:
            target = make_user(tg, cash=1_000_000)
            target.hp = 1
            target.equipped_armor = armor_key
            session.add(target)
            await session.flush()
            session.add(InventoryItem(user_id=target.id, item_key=armor_key, level=armor_level))
            targets.append((target, expected, armor_key, armor_level))
        await session.flush()

        with (
            patch("services.battle.random.random", return_value=0.99),
            patch("services.battle.roll_damage", return_value=(10, False)),
        ):
            for target, expected, armor_key, armor_level in targets:
                all_revived = True
                for used in range(1, expected + 1):
                    target.hp = 1
                    attacker.last_attack_at = None
                    attacker.energy = config.MAX_ENERGY
                    result = await battle.execute_hit(session, attacker, target)
                    all_revived = all_revived and result["ok"] and not result.get("killed")
                    all_revived = all_revived and target.gods_shield_charges == used
                used_before_death = target.gods_shield_charges
                target.hp = 1
                attacker.last_attack_at = None
                attacker.energy = config.MAX_ENERGY
                final = await battle.execute_hit(session, attacker, target)
                check(
                    f"{config.ARMORS[armor_key]['name']} لول {armor_level} دقیقاً {expected} بار نجات واقعی دارد",
                    all_revived and used_before_death == expected and final["ok"]
                    and final.get("killed") and target.gods_shield_charges == 0,
                    f"before={used_before_death}, final={final}, charges={target.gods_shield_charges}",
                )
        await session.rollback()


async def test_lab_build_and_workers(Session) -> None:
    total_cash = config.LAB_BUILD_COST[0] + sum(row[0] for row in config.LAB_UPGRADE_COST)
    total_wood = config.LAB_BUILD_COST[1] + sum(row[1] for row in config.LAB_UPGRADE_COST)
    total_iron = config.LAB_BUILD_COST[2] + sum(row[2] for row in config.LAB_UPGRADE_COST)
    async with Session() as session:
        builder = make_user(
            32001, level=30, cash=total_cash, wood=total_wood,
            iron=total_iron, shelter=10,
        )
        session.add(builder)
        await session.flush()
        results = [await lab.build_lab(session, builder)]
        results.extend([await lab.upgrade_lab(session, builder) for _ in range(3)])
        check(
            "ساخت لول‌های 1 تا 4 پول، چوب و آهن جدول را دقیق و اتمیک کم می‌کند",
            all(ok for ok, _ in results) and builder.lab_level == 4
            and builder.cash == builder.wood == builder.iron == 0,
            f"results={results}, balances={builder.cash}/{builder.wood}/{builder.iron}",
        )
        before = (builder.cash, builder.wood, builder.iron, builder.lab_level)
        again = await lab.upgrade_lab(session, builder)
        check(
            "تکرار ارتقای آزمایشگاه مکس هیچ هزینه دوباره‌ای کم نمی‌کند",
            not again[0] and before == (builder.cash, builder.wood, builder.iron, builder.lab_level),
        )

        short = make_user(32002, level=15, cash=500_000, wood=1_179, iron=630, shelter=10)
        session.add(short)
        await session.flush()
        short_before = (short.cash, short.wood, short.iron, short.lab_level)
        denied = await lab.build_lab(session, short)
        check(
            "کمبود یکی از مصالح ساخت را بدون برداشت هیچ هزینه‌ای رد می‌کند",
            not denied[0] and "چوب" in denied[1]
            and short_before == (short.cash, short.wood, short.iron, short.lab_level),
        )

        high_player_low_lab = make_user(32003, level=30, cash=2_000_000, lab_level=1)
        max_lab = make_user(32004, level=30, cash=2_000_000, lab_level=4)
        session.add_all([high_player_low_lab, max_lab])
        await session.flush()
        skilled_denied = await lab.hire_worker(session, high_player_low_lab, "skilled")
        basic_ok = await lab.hire_worker(session, high_player_low_lab, "basic")
        scientist_ok = await lab.hire_worker(session, max_lab, "scientist")
        check(
            "لول بالای بازیکن قفل کارگر را دور نمی‌زند و فقط لول آزمایشگاه ملاک است",
            not skilled_denied[0] and "لول آزمایشگاه 2" in skilled_denied[1]
            and basic_ok[0] and scientist_ok[0],
            f"skilled={skilled_denied}, basic={basic_ok}, scientist={scientist_ok}",
        )
        legacy_scientist = LabWorker(user_id=high_player_low_lab.id, worker_key="scientist")
        session.add(legacy_scientist)
        await session.flush()
        legacy_quote = await lab.production_quote(
            session, high_player_low_lab, legacy_scientist.id, "crystal",
        )
        check(
            "کارگر قدیمی رده‌بالا تا رسیدن لول آزمایشگاه قابل سوءاستفاده برای تولید نیست",
            not legacy_quote[0] and "لول آزمایشگاه 4" in str(legacy_quote[1]),
            str(legacy_quote),
        )
        await session.rollback()


async def test_market_capacity_and_idempotency(Session) -> None:
    async with Session() as session:
        seller = make_user(33001, cash=1_000, wood=50)
        buyer = make_user(33002, cash=100_000, wood=190, shelter=0)
        session.add_all([seller, buyer])
        await session.flush()
        ok, listing = await market.create_listing(session, seller, "wood", 20, 10_000)
        full_status, _ = await market.buy_listing(session, buyer, listing.id)
        listing_still_there = await market.get_listing(session, listing.id)
        check(
            "خرید چوبی که از ظرفیت رد می‌شود پول یا escrow را تغییر نمی‌دهد",
            ok and full_status == "full" and buyer.cash == 100_000 and buyer.wood == 190
            and seller.cash == 1_000 and seller.wood == 30 and listing_still_there is not None,
        )

        buyer.wood = 180
        await session.flush()
        status, _ = await market.buy_listing(session, buyer, listing.id)
        paid_state = (buyer.cash, buyer.wood, seller.cash)
        repeated, _ = await market.buy_listing(session, buyer, listing.id)
        check(
            "خرید موفق فقط یک بار تا سقف ظرفیت تسویه می‌شود و دوبارکلیک dupe نمی‌زند",
            status == "ok" and paid_state == (90_000, 200, 11_000)
            and repeated == "gone" and (buyer.cash, buyer.wood, seller.cash) == paid_state,
        )

        escrow_seller = make_user(33003, wood=25)
        session.add(escrow_seller)
        await session.flush()
        first_ok, first_listing = await market.create_listing(session, escrow_seller, "wood", 20, 2_000)
        second_ok, second_msg = await market.create_listing(session, escrow_seller, "wood", 10, 2_000)
        open_qty = sum((await session.execute(select(MarketListing.qty).where(
            MarketListing.seller_id == escrow_seller.id,
        ))).scalars())
        check(
            "یک موجودی چوب نمی‌تواند در چند آگهی بیشتر از مقدار واقعی escrow شود",
            first_ok and not second_ok and second_msg == "nostock"
            and escrow_seller.wood == 5 and open_qty == 20,
        )

        escrow_seller.wood = config.RES_WOOD_CAP_TABLE[0] - 5
        await session.flush()
        cancel_full, held = await market.cancel_listing(session, escrow_seller, first_listing.id)
        still_held = await market.get_listing(session, first_listing.id)
        escrow_seller.wood = config.RES_WOOD_CAP_TABLE[0] - 20
        await session.flush()
        cancel_ok, _ = await market.cancel_listing(session, escrow_seller, first_listing.id)
        check(
            "لغو آگهی چوب ظرفیت را دور نمی‌زند و escrow را تا بازشدن جا نگه می‌دارد",
            not cancel_full and held is not None and still_held is not None
            and cancel_ok and escrow_seller.wood == config.RES_WOOD_CAP_TABLE[0]
            and await market.get_listing(session, first_listing.id) is None,
        )

        iron_seller = make_user(33004, iron=30)
        iron_buyer = make_user(33005, cash=50_000, iron=95, shelter=0)
        session.add_all([iron_seller, iron_buyer])
        await session.flush()
        _, iron_listing = await market.create_listing(session, iron_seller, "iron", 10, 5_000)
        iron_full, _ = await market.buy_listing(session, iron_buyer, iron_listing.id)
        iron_buyer.iron = 90
        await session.flush()
        iron_ok, _ = await market.buy_listing(session, iron_buyer, iron_listing.id)
        check(
            "کنترل اتمیک ظرفیت برای آهن هم مثل چوب اعمال می‌شود",
            iron_full == "full" and iron_ok == "ok" and iron_buyer.iron == config.RES_IRON_CAP_TABLE[0],
        )

        exp_seller = make_user(33006, wood=40)
        session.add(exp_seller)
        await session.flush()
        _, expiring = await market.create_listing(session, exp_seller, "wood", 30, 3_000)
        exp_seller.wood = 190
        expiring.created_at = now_utc() - timedelta(hours=config.MARKET_TTL_HOURS + 1)
        await session.flush()
        blocked_sweep = await market.sweep_expired(session)
        held_after_sweep = await market.get_listing(session, expiring.id)
        exp_seller.wood = 170
        held_after_sweep.created_at = now_utc() - timedelta(hours=config.MARKET_TTL_HOURS + 1)
        await session.flush()
        returned_sweep = await market.sweep_expired(session)
        check(
            "انقضای آگهی پرظرفیت جنس را نگه می‌دارد و بعد از بازشدن جا فقط یک بار برمی‌گرداند",
            blocked_sweep == 0 and held_after_sweep is not None and returned_sweep == 1
            and exp_seller.wood == 200 and await market.get_listing(session, expiring.id) is None,
        )
        await session.rollback()


async def test_real_sqlite_concurrency() -> None:
    """دو اتصال واقعی SQLite برای اثبات claim یک‌بارمصرف و شرط اتمیک ظرفیت."""
    fd, path = tempfile.mkstemp(prefix="teriaky_market_", suffix=".db")
    os.close(fd)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", connect_args={"timeout": 30})
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with Session() as session:
            seller = make_user(34001, cash=0, wood=20)
            buyer1 = make_user(34002, cash=10_000)
            buyer2 = make_user(34003, cash=10_000)
            seller_a = make_user(34004, cash=0, wood=20)
            seller_b = make_user(34005, cash=0, wood=20)
            cap_buyer = make_user(34006, cash=20_000, wood=180)
            session.add_all([seller, buyer1, buyer2, seller_a, seller_b, cap_buyer])
            await session.flush()
            _, shared = await market.create_listing(session, seller, "wood", 20, 5_000)
            _, listing_a = await market.create_listing(session, seller_a, "wood", 20, 5_000)
            _, listing_b = await market.create_listing(session, seller_b, "wood", 20, 5_000)
            ids = {
                "seller": seller.id, "buyer1": buyer1.id, "buyer2": buyer2.id,
                "seller_a": seller_a.id, "seller_b": seller_b.id, "cap_buyer": cap_buyer.id,
                "shared": shared.id, "a": listing_a.id, "b": listing_b.id,
            }
            await session.commit()

        async def buy(user_id: int, listing_id: int) -> str:
            async with Session() as session:
                user = await session.get(User, user_id)
                status, _ = await market.buy_listing(session, user, listing_id)
                await session.commit()
                return status

        shared_results = await asyncio.gather(
            buy(ids["buyer1"], ids["shared"]),
            buy(ids["buyer2"], ids["shared"]),
        )
        async with Session() as session:
            b1 = await session.get(User, ids["buyer1"])
            b2 = await session.get(User, ids["buyer2"])
            seller = await session.get(User, ids["seller"])
            shared_left = await session.get(MarketListing, ids["shared"])
            check(
                "دو خرید هم‌زمان یک آگهی فقط یک برنده، یک پرداخت و یک تحویل می‌سازد",
                sorted(shared_results) == ["gone", "ok"]
                and b1.wood + b2.wood == 20 and seller.cash == 5_000 and shared_left is None,
                str(shared_results),
            )

        cap_results = await asyncio.gather(
            buy(ids["cap_buyer"], ids["a"]),
            buy(ids["cap_buyer"], ids["b"]),
        )
        async with Session() as session:
            cap_buyer = await session.get(User, ids["cap_buyer"])
            seller_a = await session.get(User, ids["seller_a"])
            seller_b = await session.get(User, ids["seller_b"])
            listings_left = len(list((await session.execute(
                select(MarketListing.id).where(MarketListing.id.in_([ids["a"], ids["b"]]))
            )).scalars()))
            check(
                "خرید هم‌زمان دو آگهی نمی‌تواند ظرفیت چوب یک خریدار را رد کند",
                sorted(cap_results) == ["full", "ok"] and cap_buyer.wood == 200
                and cap_buyer.cash == 15_000 and seller_a.cash + seller_b.cash == 5_000
                and listings_left == 1,
                str(cap_results),
            )
    finally:
        await engine.dispose()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except FileNotFoundError:
                pass


async def main() -> None:
    test_static_config()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await test_real_revives(Session)
    await test_lab_build_and_workers(Session)
    await test_market_capacity_and_idempotency(Session)
    await engine.dispose()
    await test_real_sqlite_concurrency()
    print(f"\n🎉 {PASSED} تست تکمیلی زره، آزمایشگاه و مارکت پاس شد")


if __name__ == "__main__":
    asyncio.run(main())
