"""رگرسیون کارت تصویری پروفایل تریاکی."""
from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import Base
from handlers import profile as profile_handler
from models import Dog, Team, TeamMember, User
from services.profile_card import HEIGHT, WIDTH, render_profile_card, sanitize_text

PASS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS
    assert condition, f"FAIL: {name}" + (f" | {detail}" if detail else "")
    PASS += 1
    print(f"PASS: {name}")


def sample_payload(**changes) -> dict:
    data = {
        "name": "امیرعلی پادشاه مافیا",
        "short_name": "امیرعلی",
        "username": "@teriaky_king",
        "title": "Teriaky God",
        "title_emoji": "👑",
        "level": 27,
        "xp": 45_822,
        "xp_need": 60_000,
        "max_level": False,
        "cash": 987_654_321,
        "gems": 12_450,
        "bank": 50_000_000,
        "wood": 24_567,
        "iron": 18_990,
        "rank": 12,
        "rank_total": 4_821,
        "attack": 1_792,
        "defense": 1_538,
        "power": 3_330,
        "wins": 821,
        "losses": 93,
        "energy": 287,
        "energy_cap": 300,
        "team_name": "خاندان تریاکی",
        "team_role": "owner",
        "dog_name": "سلطان شب",
        "dog_breed": "گرگ سیاه",
        "dog_level": 5,
        "dog_count": 3,
        "plots": 4,
        "growing": 2,
        "ready": 1,
        "weapon_line": "🔫 کلاشنیکف",
        "armor_line": "🦺 زره پلاسمایی",
    }
    data.update(changes)
    return data


def test_renderer() -> None:
    payload = sample_payload(
        name="امیرعلی پادشاه مافیا با یک اسم خیلی خیلی طولانی 😎\nخراب",
        team_name="کارتل با یک اسم بیش از حد طولانی که باید داخل قاب جا شود",
        dog_name="سگ با اسم خیلی خیلی خیلی طولانی 🐕",
        cash=10**25,
        bank=10**28,
    )
    raw = render_profile_card(payload)
    image = Image.open(io.BytesIO(raw))
    check(
        "کارت پروفایل JPEG معتبر با ابعاد دقیق 1280×720 می‌سازد",
        image.format == "JPEG" and image.size == (WIDTH, HEIGHT) and len(raw) < 2_000_000,
        f"format={image.format}, size={image.size}, bytes={len(raw)}",
    )
    cleaned = sanitize_text(payload["name"], 32)
    check(
        "نام چندخطی/ایموجی پاک، محدود و با ellipsis داخل قاب نگه داشته می‌شود",
        "\n" not in cleaned and "😎" not in cleaned and len(cleaned) <= 32 and cleaned.endswith("…"),
        cleaned,
    )

    max_level = render_profile_card(sample_payload(
        name="کاربر",
        username="بدون یوزرنیم",
        max_level=True,
        level=30,
        xp=999_999,
        xp_need=0,
        team_name="بدون کارتل",
        team_role="",
        dog_name="بدون سگ",
        dog_breed="—",
        dog_level=0,
        dog_count=0,
    ))
    max_image = Image.open(io.BytesIO(max_level))
    check(
        "کارت لول مکس، بدون سگ و بدون کارتل هم بدون تقسیم بر صفر رندر می‌شود",
        max_image.size == (WIDTH, HEIGHT),
    )


async def test_payload(Session) -> None:
    async with Session() as session:
        user = User(
            telegram_id=61001,
            username="profile_user",
            first_name="بازیکن تست",
            level=10,
            xp=500,
            cash=123_000,
            gems=17,
            wood=44,
            iron=55,
            energy=80,
        )
        session.add(user)
        await session.flush()
        team = Team(name="کارتل تست", name_norm="کارتل تست", owner_id=user.id)
        session.add(team)
        await session.flush()
        session.add(TeamMember(team_id=team.id, user_id=user.id, role="admin"))
        session.add_all([
            Dog(user_id=user.id, dog_key="pitbull", name="کوچولو", breed="پیتبول", level=2, xp=900),
            Dog(user_id=user.id, dog_key="blackwolf", name="سلطان", breed="گرگ سیاه", level=5, xp=10),
        ])
        await session.flush()

        payload = await profile_handler._profile_payload(session, user)
        caption = profile_handler._profile_caption_from_payload(payload)
        check(
            "payload کارت، سگ قوی‌تر و نام/نقش کارتل را از دیتابیس می‌خواند",
            payload["dog_name"] == "سلطان" and payload["dog_breed"] == "گرگ سیاه"
            and payload["dog_level"] == 5 and payload["dog_count"] == 2
            and payload["team_name"] == "کارتل تست" and payload["team_role"] == "admin"
            and "بازیکن تست" in caption,
            str(payload),
        )


async def test_send_and_fallback() -> None:
    payload = sample_payload()
    bot = SimpleNamespace(
        send_photo=AsyncMock(),
        send_message=AsyncMock(),
        get_user_profile_photos=AsyncMock(return_value=SimpleNamespace(total_count=0, photos=[])),
    )
    await profile_handler._send_profile(bot, 1, 61001, "FULL", payload)
    sent = bot.send_photo.await_args.kwargs["photo"]
    sent.seek(0)
    image = Image.open(sent)
    check(
        "هندلر کارت تولیدشده را به‌عنوان عکس تلگرام با کپشن کوتاه می‌فرستد",
        image.size == (WIDTH, HEIGHT) and "پروفایل" in bot.send_photo.await_args.kwargs["caption"]
        and bot.send_message.await_count == 0,
    )

    fallback_bot = SimpleNamespace(
        send_photo=AsyncMock(),
        send_message=AsyncMock(),
        get_user_profile_photos=AsyncMock(return_value=SimpleNamespace(total_count=0, photos=[])),
    )
    with patch("services.profile_card.render_profile_card", side_effect=RuntimeError("renderer down")):
        await profile_handler._send_profile(fallback_bot, 1, 61001, "FULL PROFILE", payload)
    check(
        "شکست renderer پروفایل را از کار نمی‌اندازد و fallback متنی اجرا می‌شود",
        fallback_bot.send_message.await_count == 1
        and fallback_bot.send_message.await_args.kwargs["text"] == "FULL PROFILE",
    )


async def main() -> None:
    test_renderer()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    await test_payload(Session)
    await engine.dispose()
    await test_send_and_fallback()
    print(f"\n{PASS} profile card tests passed")


if __name__ == "__main__":
    asyncio.run(main())
