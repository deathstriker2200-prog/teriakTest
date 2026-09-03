"""رگرسیون‌های حذف فرگمنت، بازیابی پلاسما، ایمنی پاک‌سازی اکانت و بکاپ."""
from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from database import Base
from handlers import admin as admin_handler
from handlers import jobs as jobs_handler
from models import GameMeta, InventoryItem, MarketListing, User
from services import backup, boss, compat_migrations, market, users
from utils import now_utc

PASS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS
    assert condition, f"FAIL: {name}" + (f" | {detail}" if detail else "")
    PASS += 1
    print(f"PASS: {name}")


def make_user(tg_id: int, **values) -> User:
    base = {
        "telegram_id": tg_id,
        "username": f"u{tg_id}",
        "first_name": f"U{tg_id}",
        "level": 30,
        "cash": 10_000,
    }
    base.update(values)
    return User(**base)


async def test_fragment_purge_and_market(Session) -> None:
    async with Session() as session:
        qty_pending = make_user(51001, boss_fragments=7)
        price_pending = make_user(51002, boss_fragments=5)
        unrelated = make_user(51003, boss_fragments=0)
        qty_pending.pending_action = "mkqty"
        qty_pending.pending_value = "fragment"
        qty_pending.pending_at = now_utc()
        qty_pending.pending_chat_id = -10
        price_pending.pending_action = "mkprice"
        price_pending.pending_value = "fragment:4"
        price_pending.pending_at = now_utc()
        price_pending.pending_chat_id = -20
        unrelated.pending_action = "mkqty"
        unrelated.pending_value = "wood"
        session.add_all([qty_pending, price_pending, unrelated])
        await session.flush()

        fragment_listing = MarketListing(
            seller_id=qty_pending.id, seller_name="legacy", item="fragment", qty=4, price=2_000,
        )
        fragment_listing_2 = MarketListing(
            seller_id=price_pending.id, seller_name="legacy2", item="fragment", qty=1, price=500,
        )
        active_listing = MarketListing(
            seller_id=unrelated.id, seller_name="active", item="part", qty=1, price=3_000,
        )
        session.add_all([fragment_listing, fragment_listing_2, active_listing])
        await session.flush()

        count = await market.count_listings(session)
        rows, _, _ = await market.fetch_page(session, None, 0, False)
        own = await market.my_listings(session, qty_pending.id)
        rejected, reason = await market.create_listing(session, qty_pending, "fragment", 1, 100)
        check(
            "فرگمنت legacy قبل از /update هم در هیچ نمای مارکت دیده یا دوباره ثبت نمی‌شود",
            count == 1 and [r.item for r in rows] == ["part"] and own == []
            and await market.get_listing(session, fragment_listing.id) is None
            and not rejected and isinstance(reason, str),
        )

        stats = await compat_migrations.remove_boss_fragments(session)
        await session.flush()
        fragments_left = int((await session.execute(
            select(func.sum(User.boss_fragments))
        )).scalar() or 0)
        fragment_rows = int((await session.execute(
            select(func.count(MarketListing.id)).where(MarketListing.item == "fragment")
        )).scalar_one())
        active_exists = await session.get(MarketListing, active_listing.id)
        check(
            "مایگریشن فرگمنت موجودی، escrow و هر دو state تعداد/قیمت را کامل گزارش و پاک می‌کند",
            stats == {"done": True, "users": 2, "fragments": 12, "listings": 2, "pending": 2}
            and fragments_left == 0 and fragment_rows == 0 and active_exists is not None
            and qty_pending.pending_action is None and qty_pending.pending_value is None
            and qty_pending.pending_at is None and qty_pending.pending_chat_id is None
            and price_pending.pending_action is None and price_pending.pending_value is None
            and unrelated.pending_action == "mkqty" and unrelated.pending_value == "wood",
            str(stats),
        )

        again = await compat_migrations.remove_boss_fragments(session)
        marker = await session.get(GameMeta, "remove_boss_fragments_v1")
        check(
            "مایگریشن حذف فرگمنت marker-based و در اجرای دوم idempotent است",
            again == {"done": False, "users": 0, "fragments": 0, "listings": 0, "pending": 0}
            and marker is not None,
            str(again),
        )


async def test_boss_part_only(Session) -> None:
    check(
        "شانس قطعه افسانه‌ای قاتل دقیقاً 3%/10%/15% و فرگمنت خارج از کانفیگ فعال است",
        config.BOSS_PART_DROP == {"common": 0.03, "epic": 0.10, "legendary": 0.15}
        and config.SPECIAL_WEAPON_FRAGMENTS == {}
        and config.SPECIAL_ARMOR_FRAGMENTS == {}
        and "fragment" not in config.MARKET_ITEMS
        and not any(name.startswith("BOSS_FRAGMENT") for name in vars(config)),
    )
    async with Session() as session:
        killer = make_user(52001, boss_fragments=9, legendary_parts=0)
        helper = make_user(52002, boss_fragments=4, legendary_parts=0)
        session.add_all([killer, helper])
        await session.flush()
        chat_id = -52000
        boss.BOSSES[chat_id] = {
            "key": "marlo", "tier": "common", "hp": 0, "max_hp": 6000,
            "expires_at": now_utc(), "damages": {helper.id: 500, killer.id: 100},
            "names": {killer.id: "killer", helper.id: "helper"}, "message_id": None,
        }
        with patch("services.boss.random.randint", return_value=1), patch(
            "services.boss.random.random", return_value=0.0,
        ):
            result = await boss._settle(session, chat_id, killer.id)
        check(
            "باس فقط برای قاتل قطعه افسانه‌ای رول می‌کند و هیچ فرگمنتی تولید نمی‌کند",
            result["drop_part"] is True and killer.legendary_parts == 1
            and helper.legendary_parts == 0 and killer.boss_fragments == 9
            and helper.boss_fragments == 4
            and all("fragment" not in key for key in result),
            str(result),
        )


async def test_plasma_recovery(Session) -> None:
    async with Session() as session:
        renamed = make_user(53001, equipped_armor="plasma", equipped_weapon="minigun")
        merged = make_user(53002, equipped_armor="plasma")
        missing = make_user(53003, equipped_armor="plasma")
        genuine = make_user(53004, equipped_weapon="minigun")
        session.add_all([renamed, merged, missing, genuine])
        await session.flush()

        source_max = users.armor_max_durability("plasma", 3)
        merge_source_max = users.armor_max_durability("plasma", 2)
        existing_max = users.armor_max_durability("plasma", 4)
        rows = [
            InventoryItem(
                user_id=renamed.id, item_key="minigun", level=3, ammo=77,
                durability=source_max - 7,
            ),
            InventoryItem(
                user_id=merged.id, item_key="minigun", level=2, ammo=11,
                durability=merge_source_max,
            ),
            InventoryItem(
                user_id=merged.id, item_key="plasma", level=4, ammo=99,
                durability=max(1, existing_max // 10),
            ),
            InventoryItem(
                user_id=genuine.id, item_key="minigun", level=5, ammo=7, durability=None,
            ),
        ]
        session.add_all(rows)
        await session.flush()

        stats = await compat_migrations.repair_plasma_inventory(session)
        await session.flush()
        renamed_row = (await session.execute(select(InventoryItem).where(
            InventoryItem.user_id == renamed.id,
        ))).scalar_one()
        merged_rows = list((await session.execute(select(InventoryItem).where(
            InventoryItem.user_id == merged.id,
        ))).scalars())
        missing_row = (await session.execute(select(InventoryItem).where(
            InventoryItem.user_id == missing.id,
        ))).scalar_one()
        genuine_row = (await session.execute(select(InventoryItem).where(
            InventoryItem.user_id == genuine.id,
        ))).scalar_one()
        merged_row = merged_rows[0]
        check(
            "ترمیم پلاسما rename قطعی را با لول/دوام/equip حفظ، merge را با قوی‌ترین نسبت انجام و گاتلینگ واقعی را دست‌نخورده می‌گذارد",
            stats == {"done": True, "restored": 1, "merged": 1, "recreated": 1, "weapon_fixed": 1}
            and (renamed_row.item_key, renamed_row.level, renamed_row.ammo, renamed_row.durability)
            == ("plasma", 3, None, source_max - 7)
            and renamed.equipped_armor == "plasma" and renamed.equipped_weapon is None
            and len(merged_rows) == 1 and merged_row.item_key == "plasma"
            and merged_row.level == 4 and merged_row.ammo is None
            and merged_row.durability == users.armor_max_durability("plasma", 4)
            and (missing_row.item_key, missing_row.level, missing_row.ammo, missing_row.durability)
            == ("plasma", 1, None, users.armor_max_durability("plasma", 1))
            and (genuine_row.item_key, genuine_row.level, genuine_row.ammo, genuine_row.durability)
            == ("minigun", 5, 7, None),
            str(stats),
        )
        again = await compat_migrations.repair_plasma_inventory(session)
        check(
            "ترمیم پلاسما marker-based است و اجرای دوم هیچ ردیفی را تغییر نمی‌دهد",
            again == {"done": False, "restored": 0, "merged": 0, "recreated": 0, "weapon_fixed": 0},
            str(again),
        )


async def test_forcejoin_never_wipes() -> None:
    with patch("services.users.wipe_account", new=AsyncMock()) as wipe:
        await jobs_handler.fj_wipe_job(SimpleNamespace(bot=SimpleNamespace()))
        wipe.assert_not_awaited()
    source = Path("handlers/jobs.py").read_text()
    check(
        "جاب عضویت اجباری نه wipe می‌زند و نه در JobQueue ثبت می‌شود",
        "run_repeating(fj_wipe_job" not in source and "wipe_account" not in source,
    )


def _callback_update(user_id: int, token: str, *, action: str = "ok", document_error: bool = False):
    query = SimpleNamespace(data=f"cacc:{action}:{token}", answer=AsyncMock())
    message = SimpleNamespace(
        reply_document=AsyncMock(side_effect=RuntimeError("telegram down") if document_error else None),
    )
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        callback_query=query,
        effective_message=message,
        effective_chat=None,
    )


async def test_clearacc_guards() -> None:
    admin_handler._CLEARACC_REQUESTS.clear()
    token = "expired01"
    admin_handler._CLEARACC_REQUESTS[token] = (54001, 999, time.monotonic() - 1)
    update = _callback_update(54001, token)
    with patch.object(config, "ADMIN_IDS", [54001, 54002]), patch(
        "handlers.admin.respond", new=AsyncMock(),
    ) as respond_mock, patch("services.users.wipe_account", new=AsyncMock()) as wipe:
        await admin_handler.clearacc_cb(update, SimpleNamespace(bot=SimpleNamespace()))
        wipe.assert_not_awaited()
        check(
            "توکن منقضی /clearacc ریست را رد می‌کند",
            token not in admin_handler._CLEARACC_REQUESTS
            and "منقضی" in respond_mock.await_args.args[1],
        )

    token = "owneronly1"
    admin_handler._CLEARACC_REQUESTS[token] = (54001, 999, time.monotonic() + 60)
    update = _callback_update(54002, token)
    with patch.object(config, "ADMIN_IDS", [54001, 54002]), patch(
        "services.users.wipe_account", new=AsyncMock(),
    ) as wipe:
        await admin_handler.clearacc_cb(update, SimpleNamespace(bot=SimpleNamespace()))
        wipe.assert_not_awaited()
        check(
            "توکن /clearacc فقط برای ادمین آغازکننده معتبر است",
            token in admin_handler._CLEARACC_REQUESTS
            and update.callback_query.answer.await_args.kwargs.get("show_alert") is True,
        )
    admin_handler._CLEARACC_REQUESTS.pop(token, None)

    token = "backupbad1"
    admin_handler._CLEARACC_REQUESTS[token] = (54001, 999, time.monotonic() + 60)
    update = _callback_update(54001, token)
    with patch.object(config, "ADMIN_IDS", [54001]), patch(
        "services.backup.make_upload_payload", new=AsyncMock(return_value=None),
    ), patch("handlers.admin.respond", new=AsyncMock()) as respond_mock, patch(
        "services.users.wipe_account", new=AsyncMock(),
    ) as wipe:
        await admin_handler.clearacc_cb(update, SimpleNamespace(bot=SimpleNamespace()))
        wipe.assert_not_awaited()
        check(
            "شکست ساخت بکاپ تازه /clearacc را قبل از wipe لغو می‌کند",
            "بکاپ امن ساخته نشد" in respond_mock.await_args.args[1],
        )

    token = "sendfail01"
    admin_handler._CLEARACC_REQUESTS[token] = (54001, 999, time.monotonic() + 60)
    update = _callback_update(54001, token, document_error=True)
    with patch.object(config, "ADMIN_IDS", [54001]), patch(
        "services.backup.make_upload_payload", new=AsyncMock(return_value=(b"verified", "fresh.db")),
    ), patch("handlers.admin.respond", new=AsyncMock()) as respond_mock, patch(
        "services.users.wipe_account", new=AsyncMock(),
    ) as wipe:
        await admin_handler.clearacc_cb(update, SimpleNamespace(bot=SimpleNamespace()))
        wipe.assert_not_awaited()
        check(
            "شکست تحویل بکاپ به تلگرام /clearacc را قبل از wipe لغو می‌کند",
            "ارسال بکاپ" in respond_mock.await_args.args[1],
        )


def _make_snapshot_source(path: str) -> list[tuple[str, int, int | None, int | None]]:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id INTEGER)")
    conn.execute(
        "CREATE TABLE inventory ("
        "id INTEGER PRIMARY KEY, user_id INTEGER, item_key TEXT, level INTEGER, "
        "ammo INTEGER, durability INTEGER)"
    )
    conn.execute("INSERT INTO users VALUES (1, 55001)")
    rows = [
        (1, 1, "minigun", 5, 37, None),
        (2, 1, "plasma", 4, None, 173),
        (3, 1, "knife", 2, None, None),
    ]
    conn.executemany("INSERT INTO inventory VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    exact = conn.execute(
        "SELECT item_key, level, ammo, durability FROM inventory ORDER BY id"
    ).fetchall()
    conn.close()
    return exact


async def test_backup_integrity_and_exact_inventory() -> None:
    with tempfile.TemporaryDirectory(prefix="teriaky-backup-test-") as td:
        src = os.path.join(td, "live.db")
        expected = _make_snapshot_source(src)
        with patch("services.backup.config.sqlite_path", return_value=src), patch(
            "services.backup.shutil.copy2", side_effect=AssertionError("raw copy forbidden"),
        ):
            snap = await backup.create_snapshot()
        try:
            conn = sqlite3.connect(snap)
            got = conn.execute(
                "SELECT item_key, level, ammo, durability FROM inventory ORDER BY id"
            ).fetchall()
            conn.close()
            check(
                "SQLite Online Backup snapshot کلید/لول/ammo/durability آیتم‌ها را دقیق حفظ می‌کند",
                backup.is_valid_backup_file(snap) and got == expected,
                f"expected={expected}, got={got}",
            )
        finally:
            os.remove(snap)

        users_only = os.path.join(td, "users-only.db")
        conn = sqlite3.connect(users_only)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO users VALUES (1)")
        conn.commit()
        conn.close()
        check(
            "بکاپ SQLite بدون inventory حتی با users سالم رد می‌شود",
            not backup.is_valid_backup_file(users_only),
        )

    users_dump = b"-- PostgreSQL database dump\nCREATE TABLE public.users (id bigint);\n"
    full_dump = users_dump + b"CREATE TABLE public.inventory (id bigint);\n"
    check(
        "تشخیص و اعتبارسنجی pg_dump وجود schema هر دو جدول users/inventory را اجباری می‌کند",
        backup._detect_backup_kind(users_dump)[0] == "bad"
        and backup._detect_backup_kind(full_dump)[0] == "pgdump",
    )


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    await test_fragment_purge_and_market(Session)
    await test_boss_part_only(Session)
    await test_plasma_recovery(Session)
    await test_forcejoin_never_wipes()
    await test_clearacc_guards()
    await test_backup_integrity_and_exact_inventory()
    await engine.dispose()
    print(f"\n{PASS} fragment/recovery safety tests passed")


if __name__ == "__main__":
    asyncio.run(main())
