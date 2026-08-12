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
from services import economy
from utils import esc, fa_num, money


def _wname(key: str | None) -> str:
    if not key:
        return "👊 دست خالی"
    w = config.WEAPONS.get(key)
    if not w:
        return "👊 دست خالی"
    return w["name"] if w.get("gun") else f"🔪 {w['name']}"


def _gear_text(user, lvls: dict, tab: str, atk: int, dfn: int, ammo: dict | None = None) -> str:
    """متن صفحه تجهیزات: استت فعلی + تجهیزشده‌ها + قابلیت سلاح ویژه اگه داره"""
    wkey = combat.weapon_choice(user, lvls, ammo)
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
    if wkey and combat.is_gun(wkey):
        cap = combat.ammo_cap(wkey, lvls.get(wkey, 1) or 1)
        left = cap if ammo is None else ammo.get(wkey, cap)
        lines.append(f"🔋 مهمات: {fa_num(left)}/{fa_num(cap)}")
    abil = (config.WEAPONS.get(wkey) or {}).get("ability") if wkey else None
    if abil:
        lines.append("")
        lines.append(f"🎯 قابلیت ویژه: {config.WEAPON_ABILITY_TEXT.get(abil['kind'], '')}")
        lines.append("با ارتقای سلاح درصد قابلیت بیشتر میشه")
        lines.append("")
    lines.append(f"🦺 زره فعال: {esc(aname)}")
    lines.append("")
    lines.append("🔽 روی هر آیتم بزن تا کارتش باز شه")
    if not any(k in (config.WEAPONS if tab == "weap" else config.ARMORS) for k in lvls):
        lines.append("هنوز تو این بخش چیزی نداری، از فروشگاه بخر")
    return "\n".join(lines)


async def render_gear(update: Update, tab: str = "weap", alert: str | None = None) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        lvls = await users.get_item_levels(s, user.id)
        ammo = await users.get_ammo_map(s, user.id)
        dogs = await dog_svc.get_user_dogs(s, user.id)
        atk, dfn = combat.combat_stats(user, lvls, dogs, ammo=ammo)
        text = _gear_text(user, lvls, tab, atk, dfn, ammo)
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


def _gear_item_text(user, tab: str, key: str, lv: int, ammo_left: int | None) -> str | None:
    """متن کارت یه آیتم تجهیزات: مشخصات بالا، دکمه‌ها پایین (راند ۲۹، درخواست کارفرما)"""
    kind = "weap" if tab == "weap" else "arm"
    catalog = config.WEAPONS if kind == "weap" else config.ARMORS
    item = catalog.get(key)
    if not item:
        return None
    lv = max(1, lv or 1)
    stat_lbl = "💥 دمیج" if kind == "weap" else "🛡 دفاع"
    lines = [f"<b>{esc(item['name'])}</b>", "",
             f"<code>لول {fa_num(lv)}</code>",  # راند ۳۰ (درخواست کارفرما): لول آیتم بالای کارت تو باکس ساده
             "",
             f"{stat_lbl}: {fa_num(economy.gear_stat(kind, key, lv))}"]
    abil = item.get("ability")
    if abil:
        lines.append(f"🎯 قابلیت ویژه: {config.WEAPON_ABILITY_TEXT.get(abil['kind'], '')}")
    if combat.is_gun(key):
        cap = combat.ammo_cap(key, lv)
        left = cap if ammo_left is None else ammo_left
        lines.append(f"🔋 مهمات: {fa_num(left)}/{fa_num(cap)}")
        lines.append(f"💵 هر تیر: {money(combat.ammo_price(key))}")
    return "\n".join(lines)


async def render_gear_item(update: Update, tab: str, key: str, alert: str | None = None) -> None:
    """کارت آیتم رو رندر می‌کنه (از دکمه gear:it یا برگشت از ریلود)"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        lvls = await users.get_item_levels(s, user.id)
        if key not in lvls:
            await s.commit()
            return await render_gear(update, tab, alert="❌ اینو نداری")
        ammo_left = await users.get_ammo(s, user.id, key)
        await s.commit()
    eq = user.equipped_weapon if tab == "weap" else user.equipped_armor
    text = _gear_item_text(user, tab, key, lvls.get(key, 1), ammo_left)
    if text is None:
        return await render_gear(update, tab)
    gun = combat.is_gun(key)
    lv_it = lvls.get(key, 1) or 1
    cap = combat.ammo_cap(key, lv_it) if gun else 0
    can_reload = gun and (cap if ammo_left is None else ammo_left) < cap
    await respond(update, text, kb.gear_item_kb(tab, key, eq == key, gun, can_reload, lv_it), alert=alert)


async def gear_item_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """باز کردن کارت یه سلاح یا زره از منوی تجهیزات (راند ۲۹)"""
    _, _, tab, key = parts(update)
    await update.callback_query.answer()
    await render_gear_item(update, tab, key)


async def gear_equip_card_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """انتخاب از داخل کارت آیتم: تجهیز + برگشت به همون کارت با تیک سبز"""
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
    await render_gear_item(update, tab, key, alert=f"✅ {item['name']} دستت شد")


def _reload_plan(user, lv: int, key: str, ammo_left: int | None) -> tuple[int, int, int, int]:
    """(ظرفیت، موجود، جای خالی، خرج پرکردن کامل) + اگه پول کم بود جای خالی قابل خرید جدا حساب میشه"""
    cap = combat.ammo_cap(key, max(1, lv or 1))
    left = cap if ammo_left is None else ammo_left
    need = max(0, cap - left)
    unit = combat.ammo_price(key)
    return cap, left, need, need * unit


def _reload_text(item: dict, cap: int, left: int, need: int, unit: int, cash: int) -> str:
    total = need * unit
    lines = [
        f"<b>🔫 ریلود {esc(item['name'])}</b>", "",
        f"🔋 خشاب: {fa_num(left)}/{fa_num(cap)}",
        f"🕳 جای خالی: {fa_num(need)} تیر",
        f"💵 قیمت هر تیر: {money(unit)}",
        f"💸 خرج ریلود: {money(total)}",
    ]
    if cash < total:
        afford = cash // unit
        lines.append(f"⚠️ پولت به {fa_num(max(0, afford))} تیر میرسه، همون‌قدر پر میشه")
    lines.append("")
    lines.append("تایید می‌کنی؟")
    return "\n".join(lines)


async def gear_reload_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """کارت تایید ریلود از داخل کارت آیتم: ظرفیت و قیمت و خرج کل رو نشون میده"""
    _, _, key = parts(update)
    item = config.WEAPONS.get(key)
    if not item or not combat.is_gun(key):
        await update.callback_query.answer("❌ این سلاح مهمات نمی‌خوره", show_alert=True)
        return
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        lv = (await users.get_item_levels(s, user.id)).get(key)
        if lv is None:
            await s.commit()
            return await render_gear(update, "weap", alert="❌ اینو نداری")
        ammo_left = await users.get_ammo(s, user.id, key)
        cap, left, need, total = _reload_plan(user, lv, key, ammo_left)
        cash = user.cash or 0
        await s.commit()
    if need <= 0:
        await update.callback_query.answer("🔋 خشابت پره رفیق", show_alert=True)
        return
    await update.callback_query.answer()
    await respond(update, _reload_text(item, cap, left, need, combat.ammo_price(key), cash),
                  kb.reload_confirm_kb(key, update.effective_user.id))


async def gear_reload_do_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """اجرای ریلود بعد تایید، فقط خودِ شروع‌کننده"""
    _, _, key, owner_id = parts(update)
    if update.effective_user.id != int(owner_id):
        await update.callback_query.answer()  # غریبه هیچ واکنشی نمی‌بینه
        return
    item = config.WEAPONS.get(key)
    if not item or not combat.is_gun(key):
        await update.callback_query.answer("❌ این سلاح مهمات نمی‌خوره", show_alert=True)
        return
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        lv = (await users.get_item_levels(s, user.id)).get(key)
        if lv is None:
            await s.commit()
            return await render_gear(update, "weap", alert="❌ اینو نداری")
        ammo_left = await users.get_ammo(s, user.id, key)
        cap, left, need, _ = _reload_plan(user, lv, key, ammo_left)
        unit = combat.ammo_price(key)
        afford = min(need, (user.cash or 0) // unit)
        if afford <= 0:
            await s.commit()
            await update.callback_query.answer("❌ پولت به یه تیر هم نمیرسه", show_alert=True)
            return
        user.cash -= afford * unit
        await users.set_ammo(s, user.id, key, (cap - need) + afford)
        await s.commit()
        alert = f"✅ {fa_num(afford)} تیر ریلود شد ({money(afford * unit)})"
    await update.callback_query.answer()
    await render_gear_item(update, "weap", key, alert=alert)


async def gear_reload_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لغو ریلود: برگشت به کارت آیتم"""
    _, _, key = parts(update)
    await update.callback_query.answer("❌ ریلود لغو شد")
    await render_gear_item(update, "weap", key)


async def reload_text_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور «ریلود»: کارت تایید ریلود تفنگ فعال، اگه سرد بود قوی‌ترین تفنگ انبار"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        lvls = await users.get_item_levels(s, user.id)
        key = user.equipped_weapon
        if not key or not combat.is_gun(key):
            key = None
            guns = [k for k in lvls if combat.is_gun(k)]
            if guns:
                order = list(config.WEAPONS.keys())
                key = sorted(guns, key=order.index)[-1]
        if not key:
            await s.commit()
            return await respond(update, "🤷 سلاح گرم نداری که بخوای ریلودش کنی، از فروشگاه تفنگ بخر")
        lv = lvls.get(key, 1)
        ammo_left = await users.get_ammo(s, user.id, key)
        cap, left, need, total = _reload_plan(user, lv, key, ammo_left)
        cash = user.cash or 0
        await s.commit()
    item = config.WEAPONS[key]
    if need <= 0:
        return await respond(update, f"🔋 خشاب {esc(item['name'])} پره ({fa_num(left)}/{fa_num(cap)})")
    await respond(update, _reload_text(item, cap, left, need, combat.ammo_price(key), cash),
                  kb.reload_confirm_kb(key, update.effective_user.id))

async def gear_item_upg_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """آپگرید از داخل کارت آیتم: اول قیمت و استت بعدی و پول لازم، بعد دکمه تایید (راند ۳۰، درخواست کارفرما)"""
    _, _, tab, key = parts(update)
    kind = "weap" if tab == "weap" else "arm"
    item = economy.gear_catalog(kind).get(key)
    if not item:
        return await render_gear(update, tab)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        lv = (await users.get_item_levels(s, user.id)).get(key)
        cash = user.cash or 0
        iron = user.iron or 0
        await s.commit()
    if lv is None:
        return await render_gear(update, tab, alert="❌ اینو نداری")
    if lv >= config.GEAR_UPG_MAX:
        await update.callback_query.answer("👑 لول مکسه", show_alert=True)
        return
    tp = economy.gear_upg_tp(kind, key, lv)
    iron_need = economy.gear_upg_iron(kind, key, lv)
    stat_name = "دمیج" if kind == "weap" else "دفاع"
    stat_emoji = "💥" if kind == "weap" else "🛡"
    text = (
        # راند ۳۱ (قالب دقیق کارفرما): لول ساده + «دمیج از X میشه Y» + دارایی دو خطی
        f"<b>⬆️ ارتقای {esc(item['name'])}</b>\n\n"
        f"لول {fa_num(lv)} ← لول {fa_num(lv + 1)}\n"
        f"{stat_emoji} {stat_name} از {fa_num(economy.gear_stat(kind, key, lv))} میشه {fa_num(economy.gear_stat(kind, key, lv + 1))}\n"
        f"💸 تی‌پوینت {money(tp)}\n"
        f"⛏️ آهن {fa_num(iron_need)}\n\n"
        f"💵 دارایی:\n"
        f"🪙 پول: {money(cash)}\n"
        f"⛏️ آهن: {fa_num(iron)}\n\n"
        "انجامش بدیم؟"
    )
    await respond(update, text, kb.gear_item_upg_kb(tab, key))

