"""تست‌های متمرکز بچ قمار/دوز، آزمایشگاه، XP، زره و فرگمنت."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from database import Base
from handlers import jobs as jobs_handler
from handlers.attack import _victim_text
from models import GambleMatch, GambleTicTacToeMove, InventoryItem, LabCompletionEvent, LabWorker, User
from services import boss, compat_migrations, gambling, lab, market, users
from utils import now_utc

PASSED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    assert condition, f"❌ {name}: {detail}"
    PASSED += 1
    print(f"✅ {name}")


def make_user(tg: int, *, cash: int = 100_000, level: int = 30, xp: int = 0) -> User:
    return User(
        telegram_id=tg,
        username=f"u{tg}",
        first_name=f"U{tg}",
        cash=cash,
        level=level,
        xp=xp,
    )


def test_static_balance() -> None:
    check(
        "جدول XP دقیقاً 400,000 است و پله‌های قدیمی تا لول 20 حفظ شده‌اند",
        sum(config.PLAYER_XP_NEEDS) == config.PLAYER_XP_TOTAL_TO_MAX == 400_000
        and config.PLAYER_XP_NEEDS[:19] == config.LEGACY_PLAYER_XP_NEEDS[:19]
        and sum(config.PLAYER_XP_NEEDS[:19]) == 68_189,
    )
    multipliers = [gambling.solo_multiplier("slot", value) for value in range(1, 65)]
    check(
        "اسلات 64 حالت را پوشش می‌دهد، سقفش ×10 و بازگشت نظریش 95.31٪ است",
        max(multipliers) == 10
        and abs(sum(multipliers) / 64 - 0.953125) < 1e-12
        and gambling.solo_multiplier("slot", 1) == 6
        and gambling.solo_multiplier("slot", 22) == 5
        and gambling.solo_multiplier("slot", 43) == 4,
    )
    rules = " ".join(str(spec.get("rule", "")) for spec in config.GAMBLE_DICE.values())
    check(
        "عددهای قوانین قمار لاتین‌اند و ضریب ×20 حذف شده",
        not any(ch in rules for ch in "۰۱۲۳۴۵۶۷۸۹") and "×20" not in rules,
    )
    check(
        "سود محصولات عادی آزمایشگاه کم و خروجی افسانه‌ای ثابت شده",
        config.LAB_PRODUCTS["crystal"]["sell"] == 6_000
        and config.LAB_PRODUCTS["crystal"]["time_seconds"] == 1_080
        and config.LAB_PRODUCTS["legendary"]["fixed_output"] is True,
    )


async def test_ttt(Session) -> None:
    async with Session() as session:
        creator = make_user(20001, cash=20_000)
        opponent = make_user(20002, cash=20_000)
        stranger = make_user(20003, cash=20_000)
        session.add_all([creator, opponent, stranger])
        await session.flush()
        match, why = await gambling.create_match(session, creator, -100, None, 2_000)
        await gambling.accept_match(session, match.id, opponent)
        await gambling.set_match_rounds(session, match.id, creator, 1)
        await gambling.confirm_match(session, match.id, creator)
        await gambling.confirm_match(session, match.id, opponent)
        match.round_starter_id = match.turn_user_id = creator.id

        bad_stranger = await gambling.play_ttt(session, match.id, stranger, 0)
        await gambling.play_ttt(session, match.id, creator, 0)
        bad_turn = await gambling.play_ttt(session, match.id, creator, 2)
        occupied = await gambling.play_ttt(session, match.id, opponent, 0)
        await gambling.play_ttt(session, match.id, opponent, 1)
        await gambling.play_ttt(session, match.id, creator, 2)
        await gambling.play_ttt(session, match.id, opponent, 3)
        await gambling.play_ttt(session, match.id, creator, 4)
        await gambling.play_ttt(session, match.id, opponent, 5)
        final = await gambling.play_ttt(session, match.id, creator, 6)
        moves = list((await session.execute(
            select(GambleTicTacToeMove).where(GambleTicTacToeMove.match_id == match.id)
            .order_by(GambleTicTacToeMove.move_no)
        )).scalars())

        check(
            "دوز غریبه، خارج نوبت و خانه پر را بدون تغییر رد می‌کند",
            bad_stranger["reason"] == "stranger"
            and bad_turn["reason"] == "turn"
            and occupied["reason"] == "occupied",
        )
        check(
            "مهره چهارم دقیقاً قدیمی‌ترین مهره همان بازیکن را پاک می‌کند",
            final["removed"] == 0 and match.board_state[0] == "."
            and moves[-1].removed_cell == 0,
            f"board={match.board_state}, removed={final.get('removed')}",
        )
        check(
            "برد بعد از حذف/جای‌گذاری شناسایی و صندوق یک‌بار تسویه می‌شود",
            final["finished"] and match.status == "finished" and creator.cash == 22_000
            and opponent.cash == 18_000 and match.creator_escrow == match.opponent_escrow == 0,
        )
        await session.commit()

    async with Session() as session:
        creator = make_user(20004, cash=10_000)
        opponent = make_user(20005, cash=10_000)
        session.add_all([creator, opponent])
        await session.flush()
        match, _ = await gambling.create_match(session, creator, -101, None, 1_000)
        await gambling.accept_match(session, match.id, opponent)
        await gambling.set_match_rounds(session, match.id, creator, 1)
        await gambling.confirm_match(session, match.id, creator)
        await gambling.confirm_match(session, match.id, opponent)
        match.expires_at = now_utc() - timedelta(seconds=1)
        events = await gambling.sweep_expired(session)
        check(
            "بی‌فعالیتی دوز همیشه سهم هر دو نفر را کامل پس می‌دهد",
            events[-1]["kind"] == "match_refund" and creator.cash == opponent.cash == 10_000
            and match.status == "expired",
        )


async def test_lab(Session) -> None:
    async with Session() as session:
        user = make_user(21001, cash=100_000, level=30)
        user.lab_level = 4
        session.add(user)
        await session.flush()
        worker = LabWorker(user_id=user.id, worker_key="basic")
        scientist = LabWorker(user_id=user.id, worker_key="scientist")
        session.add_all([worker, scientist])
        await session.flush()
        await lab.add_material(session, user.id, "mat_a", 20)
        await lab.add_material(session, user.id, "mat_d", 30)

        ok, message = await lab.start_production(session, user, worker.id, "crystal")
        check(
            "دستمزد آزمایشگاه اول کار کم و کار ماندگار زمان‌بندی می‌شود",
            ok and user.cash == 98_000 and worker.job_upkeep_paid
            and worker.job_started_at is not None and "همین الان" in message,
        )
        worker.busy_until = now_utc() - timedelta(seconds=1)
        events = await lab.settle_due_productions(session, user.id)
        products = await lab.get_products(session, user.id)
        again = await lab.settle_due_productions(session, user.id)
        check(
            "پایان تولید محصول را خودکار انبار و کارگر را مستقل از فروش آزاد می‌کند",
            products.get("crystal") == 3 and worker.busy_until is None
            and len(events) == 1 and not again,
        )
        receipt = (await session.execute(select(LabCompletionEvent))).scalar_one()
        check(
            "رسید اعلان پایان تولید ماندگار و متنش مرتبط است",
            receipt.qty == 3 and receipt.notified_at is None
            and "کریستال" in lab.completion_message(receipt) and "دوباره آزاده" in lab.completion_message(receipt),
        )
        quote_ok, quote = await lab.production_quote(session, user, scientist.id, "legendary")
        check("دانشمند هم از محصول افسانه‌ای فقط 1 خروجی می‌دهد", quote_ok and quote["output"] == 1)


async def test_lab_notification_job(Session) -> None:
    async with Session() as session:
        user = make_user(21501)
        session.add(user)
        await session.flush()
        session.add(LabCompletionEvent(
            user_id=user.id, worker_key="basic", product_key="crystal", qty=3,
        ))
        await session.commit()

    @asynccontextmanager
    async def local_scope():
        async with Session() as session:
            yield session

    class Bot:
        def __init__(self):
            self.messages = []

        async def send_message(self, chat_id, text, **kwargs):
            self.messages.append((chat_id, text, kwargs))
            return SimpleNamespace(message_id=1)

    bot = Bot()
    with patch("handlers.jobs.session_scope", local_scope):
        await jobs_handler.lab_completion_job(SimpleNamespace(bot=bot))
    async with Session() as session:
        event = (await session.execute(select(LabCompletionEvent).where(
            LabCompletionEvent.user_id == user.id,
        ))).scalar_one()
        check(
            "جاب پایان تولید پیام را می‌فرستد و رسید را فقط بعد موفقیت notified می‌کند",
            len(bot.messages) == 1 and bot.messages[0][0] == user.telegram_id
            and "کریستال" in bot.messages[0][1] and event.notify_attempts == 1
            and event.notified_at is not None,
        )


async def test_market_and_boss(Session) -> None:
    async with Session() as session:
        seller = make_user(22001, cash=1_000)
        buyer = make_user(22002, cash=50_000)
        seller.boss_fragments = 10
        session.add_all([seller, buyer])
        await session.flush()
        ok, listing = await market.create_listing(session, seller, "fragment", 4, 20_000)
        status, info = await market.buy_listing(session, buyer, listing.id)
        check(
            "فرگمنت در مارکت ثبت، خرید و اتمیک منتقل می‌شود",
            ok and status == "ok" and info["item"] == "fragment"
            and seller.boss_fragments == 6 and buyer.boss_fragments == 4
            and seller.cash == 21_000 and buyer.cash == 30_000,
        )
        _, expiring = await market.create_listing(session, seller, "fragment", 2, 5_000)
        expiring.created_at = now_utc() - timedelta(hours=config.MARKET_TTL_HOURS + 1)
        await session.flush()
        swept = await market.sweep_expired(session)
        await session.flush()
        check(
            "فرگمنت آگهی منقضی بدون گم‌شدن به فروشنده برمی‌گردد",
            swept == 1 and seller.boss_fragments == 6 and await market.get_listing(session, expiring.id) is None,
        )

        top = make_user(22003)
        second = make_user(22004)
        third = make_user(22005)
        session.add_all([top, second, third])
        await session.flush()
        chat_id = -22000
        boss.BOSSES[chat_id] = {
            "key": "marlo", "tier": "common", "hp": 0, "max_hp": 6000,
            "expires_at": now_utc() + timedelta(minutes=1),
            "damages": {top.id: 300, second.id: 200, third.id: 100},
            "names": {top.id: "top", second.id: "second", third.id: "third"},
            "message_id": None,
        }
        with (
            patch("services.boss.random.random", side_effect=[0.01, 1.0]),
            patch("services.boss.random.choices", return_value=[(top.id, 300)]),
            patch("services.boss.random.randint", return_value=1),
        ):
            reward = await boss._settle(session, chat_id, top.id)
        check(
            "هر باس حداکثر یک دراپ کمیاب فرگمنت می‌دهد",
            reward["total_fragments"] == 1 and top.boss_fragments == 1
            and second.boss_fragments == 0 and third.boss_fragments == 0,
        )


async def test_migrations(Session) -> None:
    async with Session() as session:
        low = make_user(23001, level=15, xp=500)
        capped = make_user(23002, level=20, xp=50_000)
        maxed = make_user(23003, level=30, xp=123)
        armor_only = make_user(23004, level=20)
        armor_only.equipped_armor = "gods"
        armor_merge = make_user(23005, level=20)
        armor_merge.equipped_armor = "gods"
        duel_creator = make_user(23006, cash=9_000, level=20)
        duel_opponent = make_user(23007, cash=9_000, level=20)
        session.add_all([low, capped, maxed, armor_only, armor_merge, duel_creator, duel_opponent])
        await session.flush()
        legacy_match = GambleMatch(
            chat_id=-23000, creator_id=duel_creator.id, opponent_id=duel_opponent.id,
            bet_per_player=1_000, emoji="🎲", game_kind="legacy_dice", rounds_total=1,
            creator_confirmed=True, opponent_confirmed=True,
            creator_escrow=1_000, opponent_escrow=1_000, status="active",
            expires_at=now_utc() + timedelta(minutes=5),
        )
        session.add(legacy_match)
        await session.flush()
        session.add_all([
            InventoryItem(user_id=armor_only.id, item_key="gods", level=3, durability=192),
            InventoryItem(user_id=armor_merge.id, item_key="gods", level=2, durability=None),
            InventoryItem(user_id=armor_merge.id, item_key="demigod", level=1, durability=0),
        ])
        await session.flush()
        armor_stats = await compat_migrations.migrate_legacy_gods_armor(session)
        xp_stats = await compat_migrations.migrate_player_xp_400k(session)
        duel_stats = await compat_migrations.retire_legacy_duels(session)
        armor_again = await compat_migrations.migrate_legacy_gods_armor(session)
        xp_again = await compat_migrations.migrate_player_xp_400k(session)
        duel_again = await compat_migrations.retire_legacy_duels(session)
        await session.flush()

        armor_row = (await session.execute(select(InventoryItem).where(
            InventoryItem.user_id == armor_only.id,
            InventoryItem.item_key == "demigod",
        ))).scalar_one()
        merged_rows = list((await session.execute(select(InventoryItem).where(
            InventoryItem.user_id == armor_merge.id,
        ))).scalars())
        check(
            "زره خدایان legacy به نیمه‌خدایان با دوام نسبی و equip درست تبدیل می‌شود",
            armor_stats["converted"] == 1 and armor_stats["merged"] == 1
            and armor_only.equipped_armor == armor_merge.equipped_armor == "demigod"
            and armor_row.level == 3 and 0 < armor_row.durability < users.armor_max_durability("demigod", 3)
            and len(merged_rows) == 1 and merged_rows[0].item_key == "demigod" and merged_rows[0].level == 2,
        )
        check(
            "XP سقف قدیمی حفظ و دقیق روی جدول 400k نگاشت می‌شود",
            low.level == 15 and low.xp == 500
            and capped.level == 22 and capped.xp == 9_000
            and maxed.level == 24 and maxed.xp == 25_901
            and xp_stats["old_cap_with_xp"] == 1,
            f"low={low.level}/{low.xp}, cap={capped.level}/{capped.xp}, max={maxed.level}/{maxed.xp}",
        )
        check(
            "دوئل تاسی باز نسخه قبل یک‌بار بسته و escrow کامل برمی‌گردد",
            duel_stats["matches"] == 1 and duel_stats["refunded"] == 2_000
            and duel_creator.cash == duel_opponent.cash == 10_000
            and legacy_match.status == "retired_refunded",
        )
        check(
            "مهاجرت زره، XP و دوئل قدیمی در اجرای دوم idempotent است",
            not armor_again["done"] and not xp_again["done"] and not duel_again["done"],
        )


def test_victim_message() -> None:
    text = _victim_text("Attacker", {
        "won": True,
        "steal": 5_000,
        "penalty": 0,
        "wood_loot": 7,
        "iron_loot": 3,
        "d_pow_disp": 100,
        "a_pow_disp": 120,
        "victim_xp": 2,
    })
    money_pos = text.index("💰")
    wood_pos = text.index("🪵")
    iron_pos = text.index("⛏️")
    check(
        "پیام قربانی زیر پول، چوب و آهن دزدیده‌شده را روشن نشان می‌دهد",
        money_pos < wood_pos < iron_pos and "7 چوب" in text and "3 آهن" in text,
    )


async def main() -> None:
    test_static_balance()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    await test_ttt(Session)
    await test_lab(Session)
    await test_lab_notification_job(Session)
    await test_market_and_boss(Session)
    await test_migrations(Session)
    test_victim_message()
    await engine.dispose()
    print(f"\n🎉 {PASSED} تست متمرکز بچ جدید پاس شد")


if __name__ == "__main__":
    asyncio.run(main())
