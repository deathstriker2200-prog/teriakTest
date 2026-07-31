"""
سوئیچ خاموش/روشن ربات 🔌
۱) خاموشی کلی (/botdown) → همه پیام مارک تعمیر می‌گیرن، ادمین‌ها معافن
۲) خاموشی یه گروه (/botoff) → ربات فقط تو همون گروه هیچ واکنشی نداره
فلگ‌ها تو game_meta نگه داشته میشن تا ری‌استارت هم بمونن، با کش حافظه‌ای سبک
"""

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import GameMeta

# کش حافظه‌ای، هر چند ثانیه از دی‌بی تازه میشه تا هر پیام کوئری نزنه
_CACHE_TTL = 10.0
_cache: dict = {"global": False, "groups": set(), "at": 0.0}


def _fresh() -> bool:
    return time.monotonic() - _cache["at"] < _CACHE_TTL


def invalidate() -> None:
    """بعد از عوض شدن فلگ، کش رو باطل کن تا همون لحظه اثر کنه"""
    _cache["at"] = 0.0


async def _refresh(session: AsyncSession) -> None:
    rows = list((await session.execute(
        select(GameMeta).where(GameMeta.key.in_(["bot_down", "off_groups"]))
    )).scalars())
    kv = {r.key: r.value for r in rows}
    _cache["global"] = kv.get("bot_down") == "1"
    _cache["groups"] = {int(x) for x in (kv.get("off_groups") or "").split(",") if x.strip()}
    _cache["at"] = time.monotonic()


async def is_down(session: AsyncSession) -> bool:
    """ربات کلا خاموشه؟"""
    if not _fresh():
        await _refresh(session)
    return bool(_cache["global"])


async def group_off(session: AsyncSession, chat_id: int) -> bool:
    """ربات تو این گروه خاموشه؟"""
    if not _fresh():
        await _refresh(session)
    return chat_id in _cache["groups"]


async def off_group_ids(session: AsyncSession) -> set[int]:
    """لیست گروه‌های خاموش، برای فیلتر جاب‌ها (اعلان آب‌وهوا و کاروان)"""
    if not _fresh():
        await _refresh(session)
    return set(_cache["groups"])


async def _meta_set(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(GameMeta, key)
    if row:
        row.value = value
    else:
        session.add(GameMeta(key=key, value=value))


async def set_down(session: AsyncSession, on: bool) -> None:
    await _meta_set(session, "bot_down", "1" if on else "0")
    invalidate()


async def set_group_off(session: AsyncSession, chat_id: int, off: bool) -> None:
    ids = await off_group_ids(session)
    if off:
        ids.add(chat_id)
    else:
        ids.discard(chat_id)
    await _meta_set(session, "off_groups", ",".join(str(x) for x in sorted(ids)))
    invalidate()
