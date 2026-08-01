"""بخش 🛡 تجهیزات: انتخاب سلاح و زره فعال با دکمه + ورود به آپگرید تجهیزات

تجهیزشده با ✅ مشخصه، هر آیتم دیگه رو بزنی جایگزینش میشه
دست خالی هم میشه گرفت، آپگرید سلاح و زره هم از همین بخش میره
"""

from telegram import Update
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import parts, respond
from keyboards import keyboards as kb
from services import combat, dogs as dog_svc, users
from utils import esc, fa_num


def _wname(key: str | None) -> str:
    if not key:
        return "👊 دست خالی"
    w = config.WEAPONS.get(key)
    if not w:
        return "👊 دست خالی"
    return w["name"] if w.get("gun") else f"🔪 {w['name']}"


def _gear_text(user, lvls: dict, tab: str, atk: int, dfn: int) -> str:
    """متن صفحه تجهیزات: استت فعلی + تجهیزشده‌ها + قابلیت سلاح ویژه اگه داره"""
    wkey = combat.weapon_choice(user, lvls)
    akey = combat.armor_choice(user, lvls)
    wname = _wname(wkey)
    aname = config.ARMORS[akey]["name"] if akey else "🦺 بدون زره"
    lines = [
        "<b>🛡 تجهیزات</b>",
        "",
        f"💪 حمله: {fa_num(atk)} | 🛡 دفاع: {fa_num(dfn)}",
        "",
        f"🔫 سلاح فعال: {esc(wname)}",
    ]
    abil = (config.WEAPONS.get(wkey) or {}).get("ability") if wkey else None
    if abil:
        lines.append("")
        lines.append(f"🎯 قابلیت ویژه: {config.WEAPON_ABILITY_TEXT.get(abil['kind'], '')}")
        lines.append("با ارتقای سلاح درصد قابلیت بیشتر میشه")
        lines.append("")
    lines.append(f"🦺 زره فعال: {esc(aname)}")
    lines.append("")
    lines.append("🔽 روی هر آیتم بزن تا دستت بشه")
    if not any(k in (config.WEAPONS if tab == "weap" else config.ARMORS) for k in lvls):
        lines.append("هنوز تو این بخش چیزی نداری، از فروشگاه بخر")
    return "\n".join(lines)


async def render_gear(update: Update, tab: str = "weap", alert: str | None = None) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        lvls = await users.get_item_levels(s, user.id)
        dogs = await dog_svc.get_user_dogs(s, user.id)
        atk, dfn = combat.combat_stats(user, lvls, dogs)
        text = _gear_text(user, lvls, tab, atk, dfn)
        markup = kb.gear_kb(user, lvls, tab)
        await s.commit()
    await respond(update, text, markup, alert=alert)


async def gear_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_gear(update, "weap")


async def gear_tab_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tab = parts(update)[2]
    await render_gear(update, "arm" if tab == "arm" else "weap")


async def gear_equip_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تجهیز کردن یه سلاح یا زره از انبار"""
    _, _, tab, key = parts(update)
    catalog = config.WEAPONS if tab == "weap" else config.ARMORS
    item = catalog.get(key)
    if not item:
        return await render_gear(update, tab)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        lvls = await users.get_item_levels(s, user.id)
        if key not in lvls:
            await s.commit()
            return await render_gear(update, tab, alert="❌ اینو نداری")
        if tab == "weap":
            user.equipped_weapon = key
        else:
            user.equipped_armor = key
        await s.commit()
    await render_gear(update, tab, alert=f"✅ {item['name']} دستت شد")


async def gear_unequip_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """کنار گذاشتن تجهیز فعلی (دست خالی / بدون زره)"""
    tab = parts(update)[2]
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        if tab == "weap":
            user.equipped_weapon = None
        else:
            user.equipped_armor = None
        await s.commit()
    alert = "👊 دست خالی شدی" if tab == "weap" else "🦺 زره رو درآوردی"
    await render_gear(update, tab, alert=alert)


async def gear_upg_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ورود به بخش آپگرید تجهیزات"""
    text = (
        "<b>⬆️ آپگرید تجهیزات</b>\n\n"
        "کدوم رو می‌خوای ارتقا بدی؟\n"
        "هر آیتم تا لول 5 ارتقا داره و هر لول استتش بیشتر میشه، با تی‌پوینت و آهن"
    )
    await respond(update, text, kb.gear_upgrade_kb())
