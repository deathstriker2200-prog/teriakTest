"""تست‌های هدفمند قابلیت‌های قمار رسمی، اقتصاد ارتقا و موتور تجهیزات جدید.
اجرا: python tests_new_features.py
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from telegram.error import TelegramError

import config
import database
from database import Base
from handlers import gambling as gambling_handler
from handlers import gear as gear_handler
from models import GambleSoloRound, InventoryItem, User
from services import battle, combat, economy, gambling
from utils import now_utc


PASSED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    assert condition, f"❌ {name}: {detail}"
    PASSED += 1
    print(f"✅ {name}")


def new_user(tg_id: int, cash: int = 100_000, level: int = 30) -> User:
    return User(telegram_id=tg_id, username=f"u{tg_id}", first_name=f"U{tg_id}", cash=cash, level=level)


def test_config_and_source() -> None:
    expected = {
        "dice": ("🎲", 6), "dart": ("🎯", 6), "bowl": ("🎳", 6),
        "basket": ("🏀", 5), "foot": ("⚽", 5), "slot": ("🎰", 64),
    }
    check("شش ایموجی رسمی و بازه صحیح Telegram ثبت شده",
          {k: (v["emoji"], v["max"]) for k, v in config.GAMBLE_DICE.items()} == expected)
    check("برد و پرداخت تک‌نفره بر اساس اتفاق واقعی هر انیمیشن درسته",
          gambling.solo_outcome("dice", 10_000, 4) == (True, 18_000)
          and gambling.solo_outcome("basket", 10_000, 5) == (True, 22_500)
          and gambling.solo_outcome("foot", 10_000, 3) == (False, 0)
          and gambling.solo_outcome("dart", 10_000, 6) == (True, 54_000)
          and gambling.solo_outcome("bowl", 10_000, 5) == (False, 0)
          and gambling.solo_outcome("slot", 10_000, 64) == (True, 100_000)
          and gambling.solo_outcome("slot", 10_000, 48) == (True, 25_000)
          and gambling.solo_outcome("slot", 10_000, 17) == (True, 15_000)
          and gambling.solo_outcome("slot", 10_000, 50) == (False, 0))
    check("نتیجه‌ها با گل، سبد، خال، استرایک و ترکیب اسلات تعریف می‌شوند نه کسر شانس",
          "سبد" in gambling.outcome_text("basket", 5)
          and "گل شد" in gambling.outcome_text("foot", 4)
          and "وسط خال" in gambling.outcome_text("dart", 6)
          and "استرایک" in gambling.outcome_text("bowl", 6)
          and "جک‌پات" in gambling.outcome_text("slot", 64))
    check("هر مرحله دونفره دقیقاً ۱۰ دقیقه مهلت بی‌فعالیتی دارد",
          config.GAMBLE_LOBBY_SECONDS == config.GAMBLE_CONFIG_SECONDS == config.GAMBLE_CONFIRM_SECONDS
          == config.GAMBLE_ROUND_SECONDS == 600)

    src = Path(__file__).with_name("handlers").joinpath("gambling.py").read_text(encoding="utf-8")
    keyboard_src = Path(__file__).with_name("keyboards").joinpath("keyboards.py").read_text(encoding="utf-8")
    check("شش بازی تک‌نفره هرکدام بخش مستقل دارند و زیر یک دکمه تاس جمع نشده‌اند",
          all(f"gm:game:{code}" in keyboard_src for code in expected)
          and "gm:solo:bet" not in keyboard_src)
    check("بازی‌های متحرک تک‌نفره فقط send_dice رسمی صدا می‌زنند", src.count("context.bot.send_dice(") == 1)
    check("نتیجه انیمیشن فقط از message.dice.value خوانده می‌شود", src.count("message.dice.value") == 1)
    check("اعلام نتیجه تا پایان انیمیشن صبر می‌کند",
          src.count("await asyncio.sleep(config.GAMBLE_DICE_ANIMATION_SECONDS)") == 1
          and config.GAMBLE_DICE_ANIMATION_SECONDS >= 4)
    check("هندلر نتیجه انیمیشن را رندوم نمی‌سازد", "import random" not in src and "random.randint" not in src)

    guns = {k: v for k, v in config.WEAPONS.items() if v.get("gun")}
    check("همه تفنگ‌ها قابلیت معنی‌دار دارند", bool(guns) and all(v.get("ability", {}).get("kind") for v in guns.values()))
    specials = {k: v for k, v in config.ARMORS.items() if v.get("sec") == "special"}
    check("هر ده زره ویژه، شامل نیمه‌خدایان و هزارچهره، قابلیت مستقل دارند",
          len(specials) == 10 and len({v["ability"]["kind"] for v in specials.values()}) == 10)

    ratios = config.GEAR_UPG_TP_STEPS
    check("چهار آپگرید مجموعاً دقیقاً ۳.۵ برابر قیمت خرید است", abs(sum(ratios) - 3.5) < 1e-9)
    check("هزینه واقعی چهار آپگرید تجهیزات ۳.۵ برابر خرید می‌شود",
          all(sum(economy.gear_upg_tp(kind, key, lv) for lv in range(1, 5)) == round(item["price"] * 3.5)
              for kind, catalog in (("weap", config.WEAPONS), ("arm", config.ARMORS))
              for key, item in catalog.items()))
    check("قدرت اصلی قابلیت با لول رشد یا برای سقف دمیج بهتر می‌شود",
          economy.gear_ability_value(config.WEAPONS["ak47"]["ability"], "chance", 5)
          > economy.gear_ability_value(config.WEAPONS["ak47"]["ability"], "chance", 1)
          and economy.gear_ability_value(config.ARMORS["emperor"]["ability"], "damage_cap_pct", 5)
          < economy.gear_ability_value(config.ARMORS["emperor"]["ability"], "damage_cap_pct", 1))
    gear_card = gear_handler._gear_item_text(None, "weap", "ak47", 3, 10) or ""
    check("کارت تجهیز و هر دو کارت ارتقا مقدار قابلیت الان و بعد را نشان می‌دهند",
          "مقدار اصلی قابلیت در این لول" in gear_card
          and "مقدار اصلی قابلیت" in Path(__file__).with_name("handlers").joinpath("gear.py").read_text(encoding="utf-8")
          and "مقدار اصلی قابلیت" in Path(__file__).with_name("handlers").joinpath("shop.py").read_text(encoding="utf-8"))
    check("ستون suppression در مایگریشن سازگاری دیتابیس ثبت شده",
          '"suppressed_until", "DATETIME"' in Path(__file__).with_name("database.py").read_text(encoding="utf-8"))
    legacy_engine = create_engine("sqlite:///:memory:")
    with legacy_engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id BIGINT)"))
        database._sync_model_columns(conn)
        legacy_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
    legacy_engine.dispose()
    check("مهاجرت واقعی دیتابیس قدیمی suppressed_until را خودکار اضافه می‌کند", "suppressed_until" in legacy_cols)
    check("اثر مستقیم سلاح به باس و کاروان وصل شده و کنترل بازیکن حذف می‌شود",
          combat.pve_weapon_damage_bonus("rpg", 5) > 0
          and combat.pve_weapon_damage_bonus("ak47", 5) == 0
          and "pve_weapon_damage_bonus" in Path(__file__).with_name("handlers").joinpath("boss.py").read_text(encoding="utf-8")
          and "pve_weapon_damage_bonus" in Path(__file__).with_name("handlers").joinpath("world.py").read_text(encoding="utf-8"))
    poisoned = new_user(99901)
    poisoned.poison_until = now_utc() + timedelta(minutes=5)
    poison_atk, poison_def = combat.combat_boost_pcts(poisoned, {}, [])
    check("سم افعی در موتور مشترک همه مودهای بازیکنی حمله و دفاع را ۱۵٪ کم می‌کند",
          abs(poison_atk + config.POISON_CUT) < 1e-9 and abs(poison_def + config.POISON_CUT) < 1e-9)


async def test_gambling_service(Session) -> None:
    async with Session() as s:
        solo = new_user(10001, cash=50_000)
        refundee = new_user(10002, cash=50_000)
        creator = new_user(10003, cash=50_000)
        opponent = new_user(10004, cash=50_000)
        cancel_creator = new_user(10005, cash=50_000)
        cancel_opponent = new_user(10006, cash=50_000)
        s.add_all([solo, refundee, creator, opponent, cancel_creator, cancel_opponent])
        await s.flush()

        row, why = await gambling.reserve_solo(s, solo, -100, None, "dice", 10_000)
        check("رزرو تک‌نفره شرط را قبل sendDice کم می‌کند", row is not None and not why and solo.cash == 40_000)
        result = await gambling.settle_solo(s, row.id, 6, 7001)
        check("تسویه تک‌نفره برد را طبق ضریب رویداد می‌پردازد",
              result["ok"] and result["payout"] == 18_000 and solo.cash == 58_000)
        duplicate = await gambling.settle_solo(s, row.id, 1, 7002)
        check("تسویه تکراری پول دوباره تولید نمی‌کند",
              duplicate.get("duplicate") is True and solo.cash == 58_000 and duplicate["value"] == 6)

        row2, why2 = await gambling.reserve_solo(s, refundee, -100, None, "slot", 5_000)
        refunded = await gambling.refund_solo(s, row2.id, "send_failed")
        check("شکست ارسال تاس شرط تک‌نفره را کامل پس می‌دهد",
              not why2 and refunded["ok"] and refundee.cash == 50_000)

        match, why = await gambling.create_match(s, creator, -100, 77, 4_000)
        match, why_accept = await gambling.accept_match(s, match.id, opponent)
        _, why_owner = await gambling.set_match_rounds(s, match.id, opponent, 3)
        match, why_rounds = await gambling.set_match_rounds(s, match.id, creator, 3)
        check("لابی دوز فقط به سازنده اجازه انتخاب مدل سری می‌دهد",
              not why and not why_accept and why_owner == "owner" and not why_rounds)

        match, why_c, started_c = await gambling.confirm_match(s, match.id, creator)
        match, why_o, started_o = await gambling.confirm_match(s, match.id, opponent)
        await s.flush()
        # شروع تصادفی است؛ برای مسیر قطعی این تست، دست اول را سازنده شروع می‌کند.
        match.round_starter_id = match.turn_user_id = creator.id
        check("سهم هر نفر هنگام تأیید وارد escrow می‌شود و دوز با تأیید دوم شروع می‌شود",
              not why_c and not why_o and not started_c and started_o
              and creator.cash == 46_000 and opponent.cash == 46_000
              and match.creator_escrow == match.opponent_escrow == 4_000 and match.status == "active")

        await gambling.play_ttt(s, match.id, creator, 0)
        await gambling.play_ttt(s, match.id, opponent, 3)
        await gambling.play_ttt(s, match.id, creator, 1)
        await gambling.play_ttt(s, match.id, opponent, 4)
        win1 = await gambling.play_ttt(s, match.id, creator, 2)
        check("برد سه‌تایی دست اول را ثبت و دست دوم را با شروع‌کننده جابه‌جا باز می‌کند",
              win1["round_won"] and not win1["finished"] and match.creator_score == 1
              and match.turn_user_id == opponent.id and match.board_state == ".........")

        await gambling.play_ttt(s, match.id, opponent, 3)
        await gambling.play_ttt(s, match.id, creator, 0)
        await gambling.play_ttt(s, match.id, opponent, 4)
        await gambling.play_ttt(s, match.id, creator, 1)
        await gambling.play_ttt(s, match.id, opponent, 6)
        final = await gambling.play_ttt(s, match.id, creator, 2)
        check("دو برد از سه بعد دو برد تمام و کل صندوق یک‌بار به برنده منتقل می‌شود",
              final["finished"] is True and final["payout"] == 8_000
              and match.status == "finished" and match.payout_done and creator.cash == 54_000
              and opponent.cash == 46_000 and match.creator_escrow == match.opponent_escrow == 0)

        cm, _ = await gambling.create_match(s, cancel_creator, -200, None, 3_000)
        await gambling.accept_match(s, cm.id, cancel_opponent)
        await gambling.set_match_rounds(s, cm.id, cancel_creator, 1)
        await gambling.confirm_match(s, cm.id, cancel_creator)
        _, why_cancel, amount = await gambling.cancel_match(s, cm.id, cancel_opponent)
        check("لغو قبل شروع هر escrow تأییدشده را کامل پس می‌دهد",
              not why_cancel and amount == 3_000 and cancel_creator.cash == 50_000 and cm.status == "cancelled")
        await s.commit()

    # ریکاوری expiry را در تراکنش جدا تست می‌کنیم تا شبیه job واقعی باشد.
    async with Session() as s:
        c = new_user(10007, cash=20_000)
        o = new_user(10008, cash=20_000)
        s.add_all([c, o])
        await s.flush()
        m, _ = await gambling.create_match(s, c, -300, None, 2_000)
        await gambling.accept_match(s, m.id, o)
        await gambling.set_match_rounds(s, m.id, c, 1)
        await gambling.confirm_match(s, m.id, c)
        await gambling.confirm_match(s, m.id, o)
        m.expires_at = now_utc() - timedelta(seconds=1)
        events = await gambling.sweep_expired(s)
        check("راند منقضی بدون تاس هر دو escrow را پس می‌دهد",
              events[-1]["kind"] == "match_refund" and c.cash == 20_000 and o.cash == 20_000 and m.status == "expired")

        fc = new_user(10009, cash=20_000)
        fo = new_user(10010, cash=20_000)
        stale_solo = new_user(10011, cash=20_000)
        s.add_all([fc, fo, stale_solo])
        await s.flush()
        fm, _ = await gambling.create_match(s, fc, -301, None, 2_000)
        await gambling.accept_match(s, fm.id, fo)
        await gambling.set_match_rounds(s, fm.id, fc, 1)
        await gambling.confirm_match(s, fm.id, fc)
        await gambling.confirm_match(s, fm.id, fo)
        fm.turn_user_id = fc.id
        fm.round_starter_id = fc.id
        await gambling.play_ttt(s, fm.id, fc, 0)
        fm.expires_at = now_utc() - timedelta(seconds=1)
        sr, _ = await gambling.reserve_solo(s, stale_solo, -302, None, "slot", 2_000)
        sr.expires_at = now_utc() - timedelta(seconds=1)
        forfeit_events = await gambling.sweep_expired(s)
        kinds = {e["kind"] for e in forfeit_events}
        check("راند منقضی با حرکت فقط یک نفر هم بازی را می‌بندد و پول هر دو را پس می‌دهد",
              "match_refund" in kinds and "match_forfeit" not in kinds and fm.status == "expired"
              and fc.cash == 20_000 and fo.cash == 20_000)
        check("رزرو تک‌نفره نیمه‌کاره در sweep کامل برمی‌گردد",
              "solo_refund" in kinds and stale_solo.cash == 20_000 and sr.status == "refunded")
        await s.commit()


async def test_fake_telegram_bot(Session) -> None:
    """خود هندلر با Fake Bot: عدد برگردانده‌شده تلگرام ثبت می‌شود و خطای sendDice پول را پس می‌دهد."""
    async with Session() as s:
        winner = new_user(10501, cash=50_000)
        failed = new_user(10502, cash=50_000)
        s.add_all([winner, failed])
        await s.commit()

    @asynccontextmanager
    async def local_scope():
        async with Session() as s:
            yield s

    class Query:
        def __init__(self):
            self.answers = []

        async def answer(self, *args, **kwargs):
            self.answers.append((args, kwargs))

    class DiceBot:
        def __init__(self, value: int | None):
            self.value = value
            self.calls = []

        async def send_dice(self, **kwargs):
            self.calls.append(kwargs)
            if self.value is None:
                raise TelegramError("fake sendDice failure")
            return SimpleNamespace(dice=SimpleNamespace(value=self.value), message_id=88001)

    def fake_update(tg_id: int):
        return SimpleNamespace(
            effective_user=SimpleNamespace(id=tg_id, username=f"u{tg_id}", first_name="فیک", is_bot=False),
            effective_chat=SimpleNamespace(id=-500, type="supergroup"),
            effective_message=SimpleNamespace(message_thread_id=None),
            callback_query=Query(),
        )

    rendered: list[str] = []

    async def fake_respond(_update, text, *_args, **_kwargs):
        rendered.append(text)

    good_bot = DiceBot(6)
    with (patch("handlers.gambling.session_scope", local_scope),
          patch("handlers.gambling.respond", fake_respond),
          patch("handlers.gambling.asyncio.sleep", new=AsyncMock())):
        await gambling_handler._solo_roll(fake_update(10501), SimpleNamespace(bot=good_bot), "dice", 10_000)

    async with Session() as s:
        good_user = (await s.execute(select(User).where(User.telegram_id == 10501))).scalar_one()
        good_round = (await s.execute(select(GambleSoloRound).where(GambleSoloRound.user_id == good_user.id))).scalar_one()
        check("Fake Bot: هندلر دقیقاً dice.value برگشتی را ثبت و تسویه می‌کند",
              len(good_bot.calls) == 1 and good_bot.calls[0]["emoji"] == "🎲"
              and good_round.dice_value == 6 and good_round.dice_message_id == 88001
              and good_user.cash == 58_000 and any("تاس روی 6 نشست" in text for text in rendered))

    failed_bot = DiceBot(None)
    rendered.clear()
    with (patch("handlers.gambling.session_scope", local_scope),
          patch("handlers.gambling.respond", fake_respond),
          patch("handlers.gambling.asyncio.sleep", new=AsyncMock())):
        await gambling_handler._solo_roll(fake_update(10502), SimpleNamespace(bot=failed_bot), "dice", 10_000)

    async with Session() as s:
        failed_user = (await s.execute(select(User).where(User.telegram_id == 10502))).scalar_one()
        failed_round = (await s.execute(select(GambleSoloRound).where(GambleSoloRound.user_id == failed_user.id))).scalar_one()
        check("Fake Bot: خطای sendDice شرط را بدون کم‌وکاست refund می‌کند",
              failed_user.cash == 50_000 and failed_round.status == "refunded"
              and any("کامل برگشت" in text for text in rendered))


async def test_combat_engine(Session) -> None:
    async with Session() as s:
        poisoner = new_user(11001, level=20)
        suppressed = new_user(11002, level=20)
        victim1 = new_user(11003, level=20)
        victim2 = new_user(11004, level=20)
        god_target = new_user(11005, level=30)
        god_target.hp = 1
        s.add_all([poisoner, suppressed, victim1, victim2, god_target])
        await s.flush()
        s.add_all([
            InventoryItem(user_id=poisoner.id, item_key="viperx", level=5, ammo=10),
            InventoryItem(user_id=suppressed.id, item_key="ak47", level=5, ammo=10),
            InventoryItem(user_id=god_target.id, item_key="gods", level=5),
        ])
        poisoner.equipped_weapon = "viperx"
        suppressed.equipped_weapon = "ak47"
        god_target.equipped_armor = "gods"
        await s.flush()

        with patch("services.battle.random.random", return_value=0.0):
            poison_hit = await battle.execute_hit(s, poisoner, victim1)
            suppress_hit = await battle.execute_hit(s, suppressed, victim2)
        check("Viper-X در نبرد HP سم واقعی و زمان‌دار اعمال می‌کند",
              poison_hit["ok"] and victim1.poison_until is not None)
        check("AK در نبرد HP سرکوب واقعی و زمان‌دار اعمال می‌کند",
              suppress_hit["ok"] and victim2.suppressed_until is not None)

        # سلاح گرم ضعیف هم به خاطر حداقل دمیج، HP=1 را صفر می‌کند؛ زره خدایان باید همان لحظه احیا کند.
        attacker = new_user(11006, level=30)
        s.add(attacker)
        await s.flush()
        s.add(InventoryItem(user_id=attacker.id, item_key="colt", level=1, ammo=5))
        attacker.equipped_weapon = "colt"
        await s.flush()
        with patch("services.battle.random.random", return_value=0.99), patch("services.battle.roll_damage", return_value=(10, False)):
            revive_hit = await battle.execute_hit(s, attacker, god_target)
        check("اولین شارژ زره خدایان در نبرد HP با درصد لول خودش احیا می‌کند",
              revive_hit["ok"] and not revive_hit.get("killed") and god_target.hp > 0
              and god_target.gods_shield_charges == 1,
              f"result={revive_hit}, hp={god_target.hp}, charges={god_target.gods_shield_charges}")
        await s.rollback()


async def main() -> None:
    test_config_and_source()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    await test_gambling_service(Session)
    await test_fake_telegram_bot(Session)
    await test_combat_engine(Session)
    await engine.dispose()
    print(f"\n🎉 {PASSED} تست هدفمند قابلیت‌های جدید پاس شد")


if __name__ == "__main__":
    asyncio.run(main())
