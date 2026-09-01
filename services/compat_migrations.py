"""مهاجرت‌های یک‌باره و قابل گزارش که عمداً فقط با /update اجرا می‌شوند."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import GameMeta, InventoryItem, User
from services import users


async def _already_done(session: AsyncSession, key: str) -> bool:
    return await session.get(GameMeta, key) is not None


async def _mark_done(session: AsyncSession, key: str, data: dict) -> None:
    session.add(GameMeta(key=key, value=json.dumps(data, ensure_ascii=False, separators=(",", ":"))))


async def migrate_legacy_gods_armor(session: AsyncSession) -> dict:
    """زره خدایان دارندگان سقف قدیمی لول 20 را امن به نوترونی تبدیل می‌کند."""
    marker = "gods20_neutron_v1"
    empty = {"done": False, "converted": 0, "merged": 0, "equipped": 0}
    if await _already_done(session, marker):
        return empty

    stats = {"done": True, "converted": 0, "merged": 0, "equipped": 0}
    rows = list((await session.execute(
        select(InventoryItem)
        .join(User, User.id == InventoryItem.user_id)
        .where(InventoryItem.item_key == "gods", User.level <= 20)
        .with_for_update()
    )).scalars())
    for source in rows:
        user = await session.get(User, source.user_id, with_for_update=True)
        if user is None:
            continue
        source_level = max(1, int(source.level or 1))
        source_max = users.armor_max_durability("gods", source_level)
        source_cur = users.armor_current_durability("gods", source_level, source.durability)
        source_ratio = source_cur / max(1, source_max)

        target = (await session.execute(
            select(InventoryItem).where(
                InventoryItem.user_id == source.user_id,
                InventoryItem.item_key == "neutron",
            ).with_for_update()
        )).scalar_one_or_none()
        if target is None:
            source.item_key = "neutron"
            target_max = users.armor_max_durability("neutron", source_level)
            source.durability = max(0, min(target_max, round(target_max * source_ratio)))
            stats["converted"] += 1
        else:
            target_level = max(1, int(target.level or 1))
            target_old_max = users.armor_max_durability("neutron", target_level)
            target_old_cur = users.armor_current_durability("neutron", target_level, target.durability)
            target_ratio = target_old_cur / max(1, target_old_max)
            target.level = max(source_level, target_level)
            target_new_max = users.armor_max_durability("neutron", target.level)
            best_ratio = max(source_ratio, target_ratio)
            target.durability = max(0, min(target_new_max, round(target_new_max * best_ratio)))
            await session.delete(source)
            stats["merged"] += 1
        if user.equipped_armor == "gods":
            user.equipped_armor = "neutron"
            stats["equipped"] += 1

    await _mark_done(session, marker, stats)
    return stats


async def migrate_player_xp_400k(session: AsyncSession) -> dict:
    """XP تاریخی را از منحنی قبلی بازسازی و روی جدول دقیق 400k نگاشت می‌کند."""
    marker = "player_xp_400k_v1"
    empty = {
        "done": False,
        "checked": 0,
        "raised": 0,
        "lowered": 0,
        "same": 0,
        "old_cap_with_xp": 0,
    }
    if await _already_done(session, marker):
        return empty
    if sum(config.PLAYER_XP_NEEDS) != config.PLAYER_XP_TOTAL_TO_MAX:
        raise RuntimeError("PLAYER_XP_NEEDS must total exactly 400,000")

    stats = dict(empty)
    stats["done"] = True
    rows = list((await session.execute(select(User).order_by(User.id).with_for_update())).scalars())
    for user in rows:
        old_level = min(max(1, int(user.level or 1)), config.MAX_LEVEL)
        old_residual = max(0, int(user.xp or 0))
        total = users.lifetime_xp(old_level, old_residual, config.LEGACY_PLAYER_XP_NEEDS)
        new_level, new_residual = users.level_from_lifetime_xp(total, config.PLAYER_XP_NEEDS)
        users.ensure_skills(user)
        if new_level > old_level:
            bonus = sum(
                config.SKILL_BONUS_LEVELS.get(level, config.SKILL_POINT_PER_LEVEL)
                for level in range(old_level + 1, new_level + 1)
            )
            user.skill_points = int(user.skill_points or 0) + bonus
            stats["raised"] += 1
        elif new_level < old_level:
            stats["lowered"] += 1
        else:
            stats["same"] += 1
        if old_level == 20 and old_residual > 0:
            stats["old_cap_with_xp"] += 1
        user.level = new_level
        user.xp = new_residual
        stats["checked"] += 1

    await _mark_done(session, marker, stats)
    return stats


async def retire_legacy_duels(session: AsyncSession) -> dict:
    """دوئل‌های sendDice باز نسخه قبل را دقیقاً یک بار refund می‌کند."""
    marker = "retire_duel_dice_v1"
    if await _already_done(session, marker):
        return {"done": False, "matches": 0, "refunded": 0}
    from services import gambling

    matches, refunded = await gambling.retire_legacy_active_matches(session)
    stats = {"done": True, "matches": matches, "refunded": refunded}
    await _mark_done(session, marker, stats)
    return stats
