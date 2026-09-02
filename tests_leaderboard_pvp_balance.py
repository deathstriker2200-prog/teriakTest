"""رگرسیون دسته اصلاح XP/لیدربرد، فرگمنت، PvP کلاسیک، مسیر قمار، زره و بمب انرژی."""
from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from database import Base
from handlers.attack import _power_snapshot_lines, _victim_text
from handlers.energy import energy_home_text
from keyboards import keyboards as kb
from models import GameMeta, InventoryItem, User
from services import combat, compat_migrations, energy, pvattack, users
from utils import now_utc

PASS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS
    if not condition:
        raise AssertionError(f"FAIL: {name}" + (f" | {detail}" if detail else ""))
    PASS += 1
    print(f"PASS: {name}")


def test_static_balance_and_ui() -> None:
    check(
        "منحنی لول 30 دقیقاً 400,000 XP است",
        len(config.PLAYER_XP_NEEDS) == 29
        and sum(config.PLAYER_XP_NEEDS) == config.PLAYER_XP_TOTAL_TO_MAX == 400_000,
    )
    check(
        "جدول فرگمنت سلاح دقیقاً مقادیر مصوب است",
        config.SPECIAL_WEAPON_FRAGMENTS == {
            "oblivion": 12, "stormbringer": 18, "sunlance": 28,
            "dragonbreath": 38, "worldbreaker": 52, "judgment": 72,
        },
    )
    check(
        "جدول فرگمنت زره دقیقاً مقادیر مصوب است",
        config.SPECIAL_ARMOR_FRAGMENTS == {
            "neutron": 12, "demigod": 15, "dragonbone": 18, "quantum": 28,
            "celestial": 38, "emperor": 52, "gods": 72, "mimic": 90,
        },
    )
    check(
        "شانس باس ثابت و مقدار موفق دو برابر است",
        config.BOSS_FRAGMENT_DROP_CHANCE == {"common": 0.10, "epic": 0.30, "legendary": 0.65}
        and config.BOSS_FRAGMENT_DROP == {"common": (2, 2), "epic": (2, 4), "legendary": (4, 8)}
        and config.BOSS_FRAGMENT_TOP_N == 3,
    )
    check(
        "بمب انرژی 150,000، پانزده دقیقه و 30٪ است",
        config.ENERGY_DRINKS["bomb"]["price"] == 150_000
        and config.ENERGY_BOOST_SECONDS == 900
        and config.ENERGY_DRINKS["bomb"]["boost"] == 0.30
        and config.ENERGY_DRINKS["bomb"]["energy"] is None,
    )
    bomb_button = kb.energy_kb().inline_keyboard[3][0].text
    check(
        "دکمه فروشگاه بمب قیمت/مدت/بوست جدید را نشان می‌دهد",
        "150,000" in bomb_button and "15 دقیقه" in bomb_button and "30%" in bomb_button,
        bomb_button,
    )
    duel_button = kb.gamble_hub_kb().inline_keyboard[0][1]
    duel_menu = kb.gamble_two_player_kb()
    check(
        "دونفره اول به منوی میانی می‌رود و نه فرم شرط",
        duel_button.callback_data == "gm:duel"
        and duel_menu.inline_keyboard[0][0].callback_data == "gm:duel:t3",
    )
    check(
        "منوی میانی فعلاً فقط دوز 3×3 دارد",
        len(duel_menu.inline_keyboard) == 2
        and "دوز 3×3" in duel_menu.inline_keyboard[0][0].text,
    )
    gambling_source = Path("handlers/gambling.py").read_text()
    check(
        "شاخه callback دونفره منو را پیش از شروع مبلغ رندر می‌کند",
        'if data == "gm:duel":' in gambling_source
        and "kb.gamble_two_player_kb()" in gambling_source
        and 'if data == "gm:duel:t3":' in gambling_source,
    )
    rank_source = Path("handlers/rank.py").read_text()
    check(
        "متن لیدربرد global را XP کل و تب‌های زمانی را XP بازه معرفی می‌کند",
        '"all": "XP کل"' in rank_source and "مدال کلی همون XP کل عمرته" in rank_source,
    )


async def test_xp_and_armor_migrations(Session) -> None:
    async with Session() as session:
        medal_source = User(
            telegram_id=10_001, first_name="Medal", level=1, xp=5, medals=400_000,
            medals_day=37, medals_week=44, cash=123_456,
            skill_points=2, skill_power=3,
        )
        level_source = User(
            telegram_id=10_002, first_name="Level", level=10, xp=55, medals=10,
            medals_day=7, medals_week=8, cash=654_321,
            skill_points=users.expected_skill_points(10),
        )
        under_merge = User(
            telegram_id=10_003, first_name="Merge", level=29, xp=0, medals=0,
            equipped_armor="gods",
        )
        eligible = User(
            telegram_id=10_004, first_name="Eligible", level=30, xp=0, medals=400_000,
            equipped_armor="gods",
        )
        under_convert = User(
            telegram_id=10_005, first_name="Convert", level=25, xp=0, medals=0,
            equipped_armor="gods",
        )
        session.add_all([medal_source, level_source, under_merge, eligible, under_convert])
        await session.flush()

        gods_max = users.armor_max_durability("gods", 3)
        demigod_max = users.armor_max_durability("demigod", 2)
        convert_max = users.armor_max_durability("gods", 2)
        source_gods = InventoryItem(
            user_id=under_merge.id, item_key="gods", level=3, durability=round(gods_max * 0.20),
        )
        existing_demigod = InventoryItem(
            user_id=under_merge.id, item_key="demigod", level=2, durability=round(demigod_max * 0.80),
        )
        eligible_gods = InventoryItem(
            user_id=eligible.id, item_key="gods", level=4, durability=None,
        )
        convert_gods = InventoryItem(
            user_id=under_convert.id, item_key="gods", level=2, durability=round(convert_max * 0.50),
        )
        session.add_all([source_gods, existing_demigod, eligible_gods, convert_gods])
        await session.commit()

    async with Session() as session:
        before_level_lifetime = users.lifetime_xp(10, 55, config.PLAYER_XP_NEEDS)
        xp_stats = await compat_migrations.sync_lifetime_xp_with_medals(session)
        armor_stats = await compat_migrations.migrate_underlevel_gods_armor(session)
        await session.commit()

        medal_source = await session.get(User, medal_source.id)
        level_source = await session.get(User, level_source.id)
        under_merge = await session.get(User, under_merge.id)
        eligible = await session.get(User, eligible.id)
        under_convert = await session.get(User, under_convert.id)

        check(
            "safe-max مدال بیشتر را بدون افت به لول 30 و residual صفر می‌برد",
            medal_source.medals == 400_000 and medal_source.level == 30 and medal_source.xp == 0,
        )
        check(
            "safe-max XP بازسازی‌شده بیشتر را canonical و مدال کلی می‌کند",
            level_source.medals == before_level_lifetime
            and users.lifetime_xp(level_source.level, level_source.xp, config.PLAYER_XP_NEEDS)
            == before_level_lifetime,
        )
        check(
            "daily و weekly در reconciliation دست‌نخورده می‌مانند",
            medal_source.medals_day == 37 and medal_source.medals_week == 44
            and level_source.medals_day == 7 and level_source.medals_week == 8,
        )
        expected = users.expected_skill_points(30)
        check(
            "فقط امتیاز مهارت واقعاً جاافتاده تکمیل می‌شود",
            medal_source.skill_points + medal_source.skill_power == expected
            and xp_stats["skill_points"] == expected - 5,
            f"points={medal_source.skill_points}, spent={medal_source.skill_power}, stats={xp_stats}",
        )
        check(
            "reconciliation هیچ پول level-up دوباره نمی‌دهد",
            medal_source.cash == 123_456 and level_source.cash == 654_321,
        )
        check(
            "آمار reconciliation هر دو منبع تاریخی را ثبت می‌کند",
            xp_stats["done"] and xp_stats["from_medals"] >= 1 and xp_stats["medals_raised"] >= 1,
            str(xp_stats),
        )

        merged = (await session.execute(select(InventoryItem).where(
            InventoryItem.user_id == under_merge.id,
            InventoryItem.item_key == "demigod",
        ))).scalar_one()
        merge_gods = (await session.execute(select(InventoryItem).where(
            InventoryItem.user_id == under_merge.id,
            InventoryItem.item_key == "gods",
        ))).scalar_one_or_none()
        final_max = users.armor_max_durability("demigod", 3)
        check(
            "Gods زیر 30 با duplicate merging، بهترین لول/نسبت دوام/equip حفظ می‌شود",
            merge_gods is None and merged.level == 3
            and abs(merged.durability / final_max - 0.80) < 0.02
            and under_merge.equipped_armor == "demigod"
            and armor_stats["merged"] == 1,
        )
        converted = (await session.execute(select(InventoryItem).where(
            InventoryItem.user_id == under_convert.id,
            InventoryItem.item_key == "demigod",
        ))).scalar_one()
        converted_max = users.armor_max_durability("demigod", 2)
        check(
            "Gods زیر 30 بدون duplicate با لول و دوام نسبی تبدیل می‌شود",
            converted.level == 2
            and abs(converted.durability / converted_max - 0.50) < 0.02
            and under_convert.equipped_armor == "demigod"
            and armor_stats["converted"] == 1,
        )
        eligible_row = (await session.execute(select(InventoryItem).where(
            InventoryItem.user_id == eligible.id,
            InventoryItem.item_key == "gods",
        ))).scalar_one_or_none()
        check(
            "صاحب نهایی لول 30 زره Gods را نگه می‌دارد",
            eligible_row is not None and eligible_row.level == 4 and eligible.equipped_armor == "gods",
        )
        markers = set((await session.execute(select(GameMeta.key))).scalars())
        check(
            "reconciliation و مهاجرت Gods هرکدام marker تازه و جدا دارند",
            {"xp_medals_lifetime_v1", "gods_underlevel_demigod_v1"} <= markers,
        )
        xp_again = await compat_migrations.sync_lifetime_xp_with_medals(session)
        armor_again = await compat_migrations.migrate_underlevel_gods_armor(session)
        check(
            "هر دو مهاجرت جدید idempotent هستند",
            not xp_again["done"] and not armor_again["done"],
        )


async def test_pvp_and_energy(Session) -> None:
    async with Session() as session:
        a = User(telegram_id=20_001, first_name="A", level=12, xp=0, medals=0, cash=200_000, energy=100)
        d = User(telegram_id=20_002, first_name="D", level=12, xp=0, medals=0, cash=200_000, energy=100)
        strong = User(telegram_id=20_003, first_name="S", level=13, xp=0, medals=0, cash=200_000, energy=100)
        session.add_all([a, d, strong])
        await session.commit()

        a_total, d_total, info = await pvattack.total_powers(session, a, d)
        d_rev, a_rev, reverse = await pvattack.total_powers(session, d, a)
        expected_a = combat.combat_stats(a, {}, [], 0.0, 0.0, ammo={})
        expected_d = combat.combat_stats(d, {}, [], 0.0, 0.0, ammo={})
        check(
            "قدرت PvP دقیقاً attack+defense فرمول پروفایل است",
            (info["a_attack"], info["a_defense"]) == expected_a
            and (info["t_attack"], info["t_defense"]) == expected_d
            and a_total == sum(expected_a) and d_total == sum(expected_d),
        )
        check(
            "فرمول با عوض‌شدن نقش مهاجم/مدافع کاملاً متقارن می‌ماند",
            a_total == a_rev and d_total == d_rev
            and info["a_attack"] == reverse["t_attack"]
            and info["t_defense"] == reverse["a_defense"],
        )
        check(
            "تساوی قطعی به مدافع می‌رسد",
            a_total == d_total and not pvattack.decide_win(a_total, d_total)
            and pvattack.close_win_chance(a_total, d_total) == 0.0,
        )
        tie_result = await pvattack.execute(session, a, d)
        check(
            "موتور واقعی execute هم در تساوی برد را به مدافع می‌دهد",
            tie_result["ok"] and not tie_result["won"]
            and tie_result["a_pow_disp"] == tie_result["d_pow_disp"],
        )
        strong_total, weak_total, _ = await pvattack.total_powers(session, strong, a)
        check(
            "قدرت بیشتر بدون هیچ رول همیشه می‌برد",
            strong_total > weak_total
            and all(pvattack.decide_win(strong_total, weak_total) for _ in range(100))
            and not any(pvattack.decide_win(weak_total, strong_total) for _ in range(100)),
        )

        snap_a = User(
            telegram_id=20_004, first_name="SnapA", level=30, xp=0, medals=400_000,
            cash=200_000, energy=100,
        )
        snap_d = User(
            telegram_id=20_005, first_name="SnapD", level=1, xp=0, medals=0,
            cash=200_000, energy=100, equipped_armor="jacket",
        )
        session.add_all([snap_a, snap_d])
        await session.flush()
        jacket_max = users.armor_max_durability("jacket", 1)
        jacket = InventoryItem(
            user_id=snap_d.id, item_key="jacket", level=1, durability=jacket_max,
        )
        session.add(jacket)
        await session.flush()
        pre_a, pre_d, pre_info = await pvattack.total_powers(session, snap_a, snap_d)
        combat_result = await pvattack.execute(session, snap_a, snap_d)
        await session.flush()
        check(
            "execute حمله/دفاع/کل را قبل از فرسایش زره snapshot می‌کند",
            combat_result["ok"] and combat_result["won"]
            and combat_result["a_attack"] == pre_info["a_attack"]
            and combat_result["a_defense"] == pre_info["a_defense"]
            and combat_result["d_attack"] == pre_info["t_attack"]
            and combat_result["d_defense"] == pre_info["t_defense"]
            and combat_result["a_pow_disp"] == pre_a
            and combat_result["d_pow_disp"] == pre_d
            and jacket.durability < jacket_max,
            f"result={combat_result}, durability={jacket.durability}/{jacket_max}",
        )

        result = {
            "won": True, "steal": 1_000, "penalty": 0, "wood_loot": 2, "iron_loot": 3,
            "victim_xp": 3, "a_attack": 111, "a_defense": 222,
            "d_attack": 333, "d_defense": 444, "a_pow_disp": 333, "d_pow_disp": 777,
        }
        victim_text = _victim_text("A", result)
        attacker_power = _power_snapshot_lines(result, viewer_is_attacker=True)
        check(
            "پیام قربانی snapshot حمله/دفاع/کل را با جهت درست نشان می‌دهد",
            "⚔️ حمله: تو 333 ✕ طرف 111" in victim_text
            and "🛡 دفاع: تو 444 ✕ طرف 222" in victim_text
            and "💪 قدرت کل: تو 777 ✕ طرف 333" in victim_text,
        )
        check(
            "پیام نتیجه مهاجم همان snapshot را با جهت برعکس نشان می‌دهد",
            "⚔️ حمله: تو 111 ✕ طرف 333" in attacker_power
            and "🛡 دفاع: تو 222 ✕ طرف 444" in attacker_power
            and "💪 قدرت کل: تو 333 ✕ طرف 777" in attacker_power,
        )
        attack_source = Path("handlers/attack.py").read_text()
        check(
            "جاسوسی attack/defense/total همان snapshot سرویس را مصرف می‌کند",
            all(token in attack_source for token in (
                "_info30['t_attack']", "_info30['t_defense']", "_info30['t_display']",
            )),
        )

        a.cash = 200_000
        a.energy = 1
        before = now_utc()
        ok, why, drink = energy.apply_drink(a, "bomb")
        left = int((a.boost_until - before).total_seconds()) if a.boost_until else 0
        check(
            "مصرف بمب 150,000 کم می‌کند، انرژی را فول و تایمر را 900 ثانیه می‌کند",
            ok and why == "ok" and drink["boosted"]
            and a.cash == 50_000 and a.energy == energy.max_energy(a)
            and 899 <= left <= 901,
            f"cash={a.cash}, energy={a.energy}, left={left}",
        )
        home = energy_home_text(a.energy, 899, energy.max_energy(a))
        check(
            "صفحه مصرف، بوست فعال 30٪ را نمایش می‌دهد",
            "+30%" in home and "بوست انرژی‌زا فعاله" in home,
        )


async def main() -> None:
    test_static_balance_and_ui()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    await test_xp_and_armor_migrations(Session)
    await test_pvp_and_energy(Session)
    await engine.dispose()
    print(f"\n{PASS} leaderboard/PvP balance tests passed")


if __name__ == "__main__":
    asyncio.run(main())
