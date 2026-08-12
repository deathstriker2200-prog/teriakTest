"""
عضویت اجباری (فورس جوین) 🔒
کانال هدف و وضعیتش توی game_meta ذخیره میشه تا با ری‌استارت بمونه
ست و مدیریتش از پنل ادمینه، چک عضویت توی handlers/gate.py قبل از همه دستورها انجام میشه

معماری پرفورمنس (فاز جدید):
۱. ستینگ گیت تو کش حافظه با TTL کوتاهه، وقتی غیرفعاله هیچ کوئری و تلگرامی روی پیام‌ها نداریم
۲. وضعیت عضویت هر کاربر روی خودش کش میشه (ستون‌های fj_*)، عضو تازه‌چک تلگرام نمی‌خوره
۳. recheck رویدادمحوره (ChatMemberHandler توی gate.py) و فولبکش چک تنبل موقع پیام خود کاربره
۴. کش عضویت حافظه‌ای هم اضافه شده که مسیر پرتردد پیام فقط یه لوکاپ دیکشنری بشه
"""

import re
import time

from telegram.error import BadRequest, Forbidden

import config
from database import session_scope
from models import GameMeta, User
from utils import now_utc

_KEY_CHANNEL = "fj_channel"
_KEY_LINK = "fj_link"
_KEY_ON = "fj_on"

GATE_CB = "fj:check"


# ─────── ستینگ ───────

async def _get(session, key: str) -> str | None:
    row = await session.get(GameMeta, key)
    return row.value if row else None


async def _set(session, key: str, value: str) -> None:
    row = await session.get(GameMeta, key)
    if row:
        row.value = value
    else:
        session.add(GameMeta(key=key, value=value))


async def get_settings(session) -> dict:
    return {
        "channel": await _get(session, _KEY_CHANNEL),
        "link": await _get(session, _KEY_LINK),
        "on": (await _get(session, _KEY_ON)) == "1",
    }


async def is_active(session) -> bool:
    st = await get_settings(session)
    return bool(st["on"] and st["channel"])


# ─────── کش حافظه‌ای ستینگ (بدون session برای هر پیام) ───────
# مثل _MESSAGE_OWNERS توی handlers/common.py، وقتی گیت خاموشه مسیر پیام صفر I/O ـه

_SETTINGS_CACHE: dict = {"at": 0.0, "st": None}


async def get_settings_cached() -> dict:
    """ستینگ گیت با کش کوتاه، کش معتبر باشه هیچ sessionی باز نمیشه"""
    now = time.monotonic()
    if _SETTINGS_CACHE["st"] is not None and now - _SETTINGS_CACHE["at"] < config.FORCE_JOIN_CACHE_SECONDS:
        return _SETTINGS_CACHE["st"]
    async with session_scope() as s:
        st = await get_settings(s)
        await s.commit()
    _SETTINGS_CACHE.update(at=now, st=st)
    return st


def invalidate_settings() -> None:
    """تغییر ادمین (ست/پاک/تاگل) کش رو فوراً می‌پرونه که بدون تأخیر TTL اعمال بشه"""
    _SETTINGS_CACHE.update(at=0.0, st=None)


async def set_channel(session, channel: str, link: str) -> None:
    await _set(session, _KEY_CHANNEL, channel)
    await _set(session, _KEY_LINK, link)
    await _set(session, _KEY_ON, "1")
    invalidate_settings()


async def clear_channel(session) -> None:
    await _set(session, _KEY_CHANNEL, "")
    await _set(session, _KEY_LINK, "")
    await _set(session, _KEY_ON, "0")
    invalidate_settings()


async def set_enabled(session, on: bool) -> None:
    await _set(session, _KEY_ON, "1" if on else "0")
    invalidate_settings()


def parse_input(text: str) -> tuple[str, str] | None:
    """
    ورودی ادمین رو به (channel, link) تبدیل می‌کنه، فرمت بد = None
    فرم‌های قابل قبول: @username | https://t.me/username | -100xxxxxxxxxx + لینک دعوت
    """
    parts = text.strip().split()
    if not parts:
        return None
    first = parts[0]
    extra = parts[1] if len(parts) > 1 else ""

    if first.startswith("@") and re.fullmatch(r"@[A-Za-z0-9_]{4,64}", first):
        return first, f"https://t.me/{first[1:]}"

    m = re.fullmatch(r"(?:https?://)?t\.me/([A-Za-z0-9_]{4,64})/?", first)
    if m:
        return f"@{m.group(1)}", f"https://t.me/{m.group(1)}"

    if re.fullmatch(r"-100\d{8,16}", first):
        link = extra if "t.me/" in extra else ""
        return (first, link) if link else None

    return None


def _chat_ref(channel: str):
    if channel.lstrip("-").isdigit():
        return int(channel)
    return channel


# ─────── کش حافظه‌ای عضویت کاربر (مسیر پرتردد پیام فقط همینو چک می‌کنه) ───────

_MEMBER_CACHE: dict[int, tuple[float, bool]] = {}   # tg_id → (انقضا مونوتونیک، عضو؟)
_MEMBER_CAP = 3000                                  # سقف حافظه، قدیمی‌ترین‌ها پاک میشن


def member_cache_get(user_id: int) -> bool | None:
    """عضویت کش‌شده معتبر یا None (یعنی باید به منبع اصلی رفت)"""
    ent = _MEMBER_CACHE.get(user_id)
    if ent and ent[0] > time.monotonic():
        return ent[1]
    return None


def member_cache_put(user_id: int, ok: bool, seconds: float) -> None:
    _MEMBER_CACHE[user_id] = (time.monotonic() + max(seconds, 1.0), ok)
    if len(_MEMBER_CACHE) > _MEMBER_CAP:  # GC نصفه مثل بقیه کش‌های پروژه
        stale = list(_MEMBER_CACHE.keys())[:-_MEMBER_CAP // 2]
        for k in stale:
            _MEMBER_CACHE.pop(k, None)


def member_cache_drop(user_id: int) -> None:
    _MEMBER_CACHE.pop(user_id, None)


def invalidate_members() -> None:
    """ریست کامل کش عضویت همه کاربرا، برای /update ادمین که وضعیت‌ها تازه بشن"""
    _MEMBER_CACHE.clear()


# ─────── چک عضویت ───────

async def is_member(bot, channel: str, user_id: int) -> bool:
    """عضویت کاربر توی کانال، هر خطایی یعنی عضو نیس (ربات باید ادمین کانال باشه)"""
    try:
        m = await bot.get_chat_member(_chat_ref(channel), user_id)
        return getattr(m, "status", "") in ("member", "administrator", "creator")
    except (BadRequest, Forbidden):
        return False
    except Exception:
        return False


async def apply_member_result(session, tg_id: int, ok: bool) -> None:
    """
    نتیجه یه چک واقعی رو روی ردیف کاربر ثبت می‌کنه
    fj_left_at فقط موقع اولین تشخیص لفت ست میشه که مهلت پاکسازی دقیق بمونه
    """
    from sqlalchemy import select
    q = select(User).where(User.telegram_id == tg_id)
    u = (await session.execute(q)).scalar_one_or_none()
    if u is None:
        return  # هنوز اکانت نساخته، چیزی برای ذخیره نیس، کش حافظه کفایت می‌کنه
    u.fj_member_status = 1 if ok else 0
    u.fj_checked_at = now_utc()
    if ok:
        u.fj_left_at = None
    elif u.fj_left_at is None:
        u.fj_left_at = now_utc()


async def membership_check(bot, channel: str, tg_id: int) -> bool:
    """چک واقعی به تلگرام + ثبت روی کاربر و کش حافظه، تنها نقطه‌ای که getChatMember می‌خوره"""
    ok = await is_member(bot, channel, tg_id)
    async with session_scope() as s:
        await apply_member_result(s, tg_id, ok)
        await s.commit()
    member_cache_put(tg_id, ok, config.FORCE_JOIN_RECHECK_SECONDS)
    return ok


async def resolve_member(bot, channel: str, tg_id: int) -> bool:
    """
    عضویت با کمترین هزینه برای مسیر پیام:
    کش حافظه → ردیف کاربر تا وقتی تازه‌ست → چک واقعی تلگرام (بار اول یا منقضی)
    غیرعضوی شناخته‌شده هیچ تلگرامی نمی‌خوره، برگشتش با «تایید عضویت» یا جوین دوباره‌ست
    """
    cached = member_cache_get(tg_id)
    if cached is not None:
        return cached
    from services import users as users_svc
    now = now_utc()
    fresh_ok, known_out, used = False, False, 0.0
    async with session_scope() as s:
        u = await users_svc.get_by_tg(s, tg_id)
        if u is not None:
            known_out = u.fj_member_status == 0
            if u.fj_member_status == 1 and u.fj_checked_at is not None:
                used = (now - u.fj_checked_at).total_seconds()
                fresh_ok = used < config.FORCE_JOIN_RECHECK_SECONDS
        await s.commit()
    if fresh_ok:  # عضوِ تازه‌چک‌شده، فولبک lazy لازم نیس، تلگرام صدا نمی‌زنیم
        member_cache_put(tg_id, True, config.FORCE_JOIN_RECHECK_SECONDS - used)
        return True
    if known_out:  # غیرعضوی ثابت‌شده، بدون تلگرام بلاک، برگشت فقط با تایید/جوین
        member_cache_put(tg_id, False, config.FORCE_JOIN_RECHECK_SECONDS)
        return False
    # بار اول یا چکش منقضی شده، همین الان که خودش پیام داده یه چک واقعی بزن
    return await membership_check(bot, channel, tg_id)


# ─────── رویدادهای chat_member (قطع و وصل لحظه‌ای بدون پیام کاربر) ───────

def same_channel(channel: str, chat_id: int, username: str | None) -> bool:
    """چتِ این آپدیت همون کانال ست‌شده‌ست؟ (آیدی عددی یا یوزرنیم)"""
    if channel.lstrip("-").isdigit():
        return int(channel) == chat_id
    return bool(username) and channel.lstrip("@").lower() == username.lower()


async def mark_left(tg_id: int) -> None:
    """لفت/کیک رویدادمحور، فوراً غیرعضو میشه و دسترسی پی‌وی‌اش از همون لحظه قطعه"""
    member_cache_put(tg_id, False, config.FORCE_JOIN_RECHECK_SECONDS)
    async with session_scope() as s:
        await apply_member_result(s, tg_id, False)
        await s.commit()


async def mark_joined(tg_id: int) -> None:
    """جوین رویدادمحور، فوراً عضو میشه، مهلت پاکسازی و گیتش صفر میشه"""
    member_cache_put(tg_id, True, config.FORCE_JOIN_RECHECK_SECONDS)
    async with session_scope() as s:
        await apply_member_result(s, tg_id, True)
        await s.commit()


# ─────── متن گیت ───────

def gate_text() -> str:
    return (
        "<b>🔒 عضویت اجباری</b>\n\n"
        "برای استفاده از ربات اول باید توی کانال زیر عضو بشی 📢\n\n"
        "عضو که شدی «✅ تایید عضویت» رو بزن تا ادامه همون دستورت برات اجرا بشه"
    )
