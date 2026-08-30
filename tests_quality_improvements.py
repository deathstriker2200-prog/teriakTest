"""تست‌های هدفمند بسته بهبود کیفیت: لو دادن، بانک، کارتل و دوام زره."""

import asyncio
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from database import Base
from keyboards import keyboards as kb
from models import CartelWar, CartelWarQueue, InventoryItem, Team, TeamMember, User
from services import battle, cartelwar, combat, snitch, teams, users
from utils import now_utc

PASSED = 0


def check(name: str, condition: bool) -> None:
    global PASSED
    assert condition, f"❌ {name}"
    PASSED += 1
    print(f"✅ {name}")


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    check("سقف بانک روی ۵۰ میلیون و دو لول جدید تنظیم شده",
          config.BANK_MAX_LEVEL == 13 and config.BANK_CAPS[-2:] == [35_000_000, 50_000_000]
          and config.BANK_MIN_LEVELS[-2:] == [20, 25])
    check("گیت لو دادن دقیقاً لول ۱۰ است", config.SNITCH_MIN_LEVEL == 10)

    async with Session() as s:
        low = User(telegram_id=1001, first_name="low", level=9, cash=100_000)
        target = User(telegram_id=1002, first_name="target", level=20, cash=100_000)
        s.add_all([low, target])
        await s.flush()
        result = await snitch.snitch(s, low, target)
        check("لو دادن زیر لول ۱۰ بدون مصرف کولدان رد می‌شود",
              result["status"] == "level" and low.last_snitch_at is None)

        reporter = User(telegram_id=1003, first_name="reporter", level=10, cash=100_000)
        empty = User(telegram_id=1004, first_name="empty", level=20, cash=100_000)
        s.add_all([reporter, empty])
        await s.flush()
        result = await snitch.snitch(s, reporter, empty)
        check("گزارش انبار خالی، خود گزارش‌دهنده را زندانی و دروغگو می‌کند",
              result["status"] == "empty" and reporter.jailed_until > now_utc()
              and reporter.liar_until > now_utc() and abs(snitch.sell_mult(reporter) - 0.80) < 0.001)

    async with Session() as s:
        leaver = User(telegram_id=2001, first_name="leaver", level=20, cash=1_000_000)
        kicked = User(telegram_id=2002, first_name="kicked", level=20, cash=1_000_000)
        owner = User(telegram_id=2003, first_name="owner", level=20, cash=1_000_000)
        s.add_all([leaver, kicked, owner])
        await s.flush()
        team = Team(name="Alpha", name_norm="alpha", owner_id=owner.id, level=5,
                    created_at=now_utc() - timedelta(days=5))
        s.add(team)
        await s.flush()
        s.add_all([
            TeamMember(team_id=team.id, user_id=owner.id, role="owner"),
            TeamMember(team_id=team.id, user_id=leaver.id, role="member"),
        ])
        await s.flush()
        ok, _ = await teams.leave_team(s, leaver)
        left = teams.cartel_cooldown_left(leaver)
        teams.set_cartel_cooldown(kicked, "kick")
        kicked_left = teams.cartel_cooldown_left(kicked)
        check("ترک ۱۲ ساعت و اخراج ۳ ساعت محرومیت می‌دهد",
              ok and 43_190 <= left <= 43_200 and 10_790 <= kicked_left <= 10_800)
        ok_create, text = await teams.can_create_team(s, leaver)
        check("کولدان کارتل هم ساخت و هم عضویت دوباره را می‌بندد",
              not ok_create and "صبر" in text)

    async with Session() as s:
        wearer = User(telegram_id=3001, first_name="armor", level=30, cash=10_000_000,
                      equipped_armor="plasma")
        s.add(wearer)
        await s.flush()
        armor = InventoryItem(user_id=wearer.id, item_key="plasma", level=1, durability=None)
        s.add(armor)
        await s.flush()
        maximum = users.armor_max_durability("plasma", 1)
        wear = await users.damage_armor(s, wearer, "plasma", loss=2)
        cost = users.armor_repair_cost("plasma", 1, armor.durability)
        cash_before = wearer.cash
        repaired = await users.repair_armor(s, wearer, "plasma")
        second = await users.repair_armor(s, wearer, "plasma")
        check("زره قدیمی از HP کامل شروع می‌کند و استهلاک محدود دارد",
              maximum == 200 and wear["current"] == 198 and wear["loss"] == 2)
        check("هزینه تعمیر با خرابی محاسبه و دوبارکلیک بی‌اثر می‌شود",
              cost > 0 and repaired["status"] == "ok" and second["status"] == "full"
              and wearer.cash == cash_before - cost and armor.durability == maximum)

        broken = await users.damage_armor(s, wearer, "plasma", loss=maximum)
        usable = await users.get_item_levels(s, wearer.id)
        owned = await users.get_item_levels(s, wearer.id, include_broken=True)
        check("زره در HP صفر می‌شکند، از تن درمی‌آید و دیگر دفاع نمی‌دهد",
              broken["broken"] and wearer.equipped_armor == "" and "plasma" not in usable
              and owned.get("plasma") == 1)

    check("زره هزارچهره از هشت قابلیت قبلی انتخاب می‌کند",
          config.ARMORS["mimic"]["ability"]["kind"] == "mimic"
          and set(config.ARMOR_MIMIC_POOL) == {"plasma", "void", "neutron", "dragonbone",
                                                  "quantum", "celestial", "emperor", "gods"}
          and combat.roll_mimic_armor() in config.ARMOR_MIMIC_POOL)
    card = kb.gear_item_kb("arm", "plasma", False, False, False, 1,
                           can_repair=True, broken=True)
    check("کارت زره شکسته دکمه تعمیر کامل دارد",
          any(button.callback_data == "gear:rep:plasma" for row in card.inline_keyboard for button in row))

    async with Session() as s:
        old_owner = User(telegram_id=4001, first_name="old", level=30, cash=1_000_000)
        new_owner = User(telegram_id=4002, first_name="new", level=30, cash=1_000_000)
        s.add_all([old_owner, new_owner])
        await s.flush()
        team = Team(name="Transfer", name_norm="transfer", owner_id=old_owner.id, level=5,
                    created_at=now_utc() - timedelta(days=5))
        s.add(team)
        await s.flush()
        old_m = TeamMember(team_id=team.id, user_id=old_owner.id, role="owner")
        new_m = TeamMember(team_id=team.id, user_id=new_owner.id, role="member")
        s.add_all([old_m, new_m])
        await s.flush()
        ok, _, target = await teams.transfer_ownership(s, old_owner, new_m.id)
        check("انتقال مالکیت اتمیک است و مالک قبلی مدیر می‌شود",
              ok and target.id == new_owner.id and team.owner_id == new_owner.id
              and old_m.role == "admin" and new_m.role == "owner")

    async with Session() as s:
        leader1 = User(telegram_id=5001, first_name="L1", level=30, cash=1_000_000)
        leader2 = User(telegram_id=5002, first_name="L2", level=30, cash=1_000_000)
        s.add_all([leader1, leader2])
        await s.flush()
        t1 = Team(name="WarOne", name_norm="warone", owner_id=leader1.id, level=6,
                  created_at=now_utc() - timedelta(days=5))
        t2 = Team(name="WarTwo", name_norm="wartwo", owner_id=leader2.id, level=7,
                  created_at=now_utc() - timedelta(days=5))
        s.add_all([t1, t2])
        await s.flush()
        s.add_all([
            TeamMember(team_id=t1.id, user_id=leader1.id, role="owner",
                       joined_at=now_utc() - timedelta(days=2)),
            TeamMember(team_id=t2.id, user_id=leader2.id, role="owner",
                       joined_at=now_utc() - timedelta(days=2)),
        ])
        await s.flush()
        first = await cartelwar.join_random_queue(s, leader1, t1)
        second = await cartelwar.join_random_queue(s, leader2, t2)
        war = second.get("war")
        queues = list((await s.execute(select(CartelWarQueue))).scalars())
        check("دو کارتل داوطلب بدون قبول/رد به جنگ رندوم scheduled می‌شوند",
              first["status"] == "queued" and second["status"] == "matched"
              and isinstance(war, CartelWar) and war.status == "scheduled"
              and t1.pending_war_id == war.id and t2.pending_war_id == war.id
              and t1.daily_war_count == 1 and t2.daily_war_count == 1 and not queues)

    async with Session() as s:
        attacker = User(telegram_id=6001, first_name="attacker", level=30, cash=1_000_000,
                        energy=100, hp=500)
        defender = User(telegram_id=6002, first_name="defender", level=30, cash=1_000_000,
                        energy=100, hp=500, equipped_armor="mimic")
        s.add_all([attacker, defender])
        await s.flush()
        s.add(InventoryItem(user_id=defender.id, item_key="mimic", level=3, durability=None))
        await s.flush()
        with patch("services.combat.roll_mimic_armor", return_value="neutron"), \
                patch("services.battle.roll_damage", return_value=(30, False)), \
                patch("services.battle.random.random", return_value=0.99):
            hit = await battle.execute_hit(s, attacker, defender)
        row = await users.get_inventory_item(s, defender.id, "mimic")
        check("هزارچهره در نبرد HP قابلیت انتخابی را واقعی اجرا و HP زره را کم می‌کند",
              hit["ok"] and any("نوترونی" in line for line in hit.get("abil_lines", []))
              and row.durability < users.armor_max_durability("mimic", 3))

    await engine.dispose()
    print(f"\n🎉 {PASSED} تست هدفمند بسته بهبود کیفیت پاس شد")


if __name__ == "__main__":
    asyncio.run(main())
