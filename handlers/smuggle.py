"""
ارسال محموله 📦 و کاروان قاچاق 🚚

جریان محموله: 📦 ارسال محموله ← انتخاب محصول ← مقدار (10/25/50/همه یا تایپی) ← کارت تایید ← ارسال
کاروان قاچاق: هر چند ساعت خودکار میاد + اسپان دستی ادمین با «اسپان کاروان قاچاق» و «اسپان کاروان [محصول]» (با پسوند اختیاری «شانسی»)
"""

import asyncio
import random

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import chat_id_of, parts, respond, strip_bot_cmd
from keyboards import keyboards as kb
from services import onboarding as onb
from services import smuggle as smg, users
from utils import fa_dur, fa_num, money, normalize_fa


# ═════════ ارسال محموله 📦 ═════════

async def _ship_render(s, user) -> tuple[str, InlineKeyboardMarkup]:
    """متن و کیبورد صفحه ارسال محموله: محموله‌های آزاد + محصول‌های قابل ارسال + محموله‌های در راه"""
    products = await smg.get_products(s, user.id)
    ongoing = await smg.active_shipments(s, user.id)
    free = max(0, config.SHIPMENT_MAX_ACTIVE - len(ongoing))
    lines = [
        "<b>📦 ارسال محموله</b>",
        "",
        f"⏱ تحویل هر محموله: {fa_dur(smg.shipment_seconds())}",
        f"🚚 محموله آزاد: {fa_num(free)} از {fa_num(config.SHIPMENT_MAX_ACTIVE)}",
        "",
    ]
    have_any = any(r.qty > 0 for r in products.values())
    if not have_any:
        lines.append("انبارت خالیه، اول از مزرعه برداشت کن")
    else:
        lines.append("کدوم محصول رو می‌فرستی؟ روی محصولش بزن")
        for key, sd in config.SEEDS.items():
            row = products.get(key)
            if not row or row.qty <= 0:
                continue
            unit = int(row.value / row.qty)
            lines.append(f"▫️ {sd.get('emoji', '🌱')} {sd['name']} ×{fa_num(row.qty)}")
            lines.append(f"🪙 هر دونه تقریبی {money(unit)}")
    if free <= 0:
        lines += [
            "",
            f"🚚 هر {fa_num(config.SHIPMENT_MAX_ACTIVE)} محموله‌ات تو راهن، تا یدونه برسه نمی‌تونی جدید بفرستی",
        ]
    if ongoing:
        lines += ["", "🚚 محموله‌های در راه:"]
        for sh in ongoing:
            lines.append(smg.shipment_line(sh))
    return "\n".join(lines), kb.products_kb(products)


async def ship_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """صفحه ارسال محموله (sm:page)، دکمه خودش رو ردیف اول انبار داره"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        text, markup = await _ship_render(s, user)
        await s.commit()
    await respond(update, text, markup)


async def ship_qty_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """انتخاب مقدار ارسال برای یه محصول (sm:pick:<crop>)"""
    crop = parts(update)[2]
    sd = config.SEEDS.get(crop)
    if not sd:
        return await respond(update, "❌ همچین محصولی نیس")
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        row = (await smg.get_products(s, user.id)).get(crop)
        have = row.qty if row else 0
        unit = int(row.value / row.qty) if row else 0
        markup = kb.ship_qty_kb(crop, have)
        await s.commit()
    if have <= 0:
        return await respond(update, f"📦 {sd['name']} تو انبارت نداری", markup)
    cap = smg.products_cap(user.shelter_level or 0)
    text = (
        f"<b>📦 ارسال محموله | {sd.get('emoji', '🌱')} {sd['name']}</b>\n\n"
        f"📦 {fa_num(have)} تا تو انبارت داری (ظرفیت {fa_num(cap)})\n"
        f"💰 ارزش هر دونه ~{money(unit)}\n\n"
        "چقدر می‌فرستی؟\n"
        "یا «✏️ تعداد دلخواه» رو بزن و عددشو بنویس"
    )
    await respond(update, text, markup)


async def ship_confirm_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """کارت تایید ارسال محموله (sm:qty:<crop>:<n|all>)"""
    _, _, crop, n = parts(update)
    sd = config.SEEDS.get(crop)
    if not sd:
        return await respond(update, "❌ همچین محصولی نیس")
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        row = (await smg.get_products(s, user.id)).get(crop)
        have = row.qty if row else 0
        qty = have if n == "all" else int(n)
        ok = row is not None and 0 < qty <= have
        value = int(row.value * qty / row.qty) if ok else 0
        await s.commit()
    if not ok:
        return await respond(update, f"📦 {fa_num(qty)} تا {sd['name']} تو انبارت نداری")
    from services.snitch import sell_mult
    await respond(update, smg.shipment_confirm_text(crop, qty, value, sell_mult(user)), kb.ship_confirm_kb(crop, qty))


async def ship_ask_qty_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«✏️ تعداد دلخواه» تو صفحه ارسال محموله (sm:ask:<crop>)، تعداد رو با پیام می‌گیریم"""
    crop = parts(update)[2]
    sd = config.SEEDS.get(crop)
    if not sd:
        return await respond(update, "❌ همچین محصولی نیس")
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        row = (await smg.get_products(s, user.id)).get(crop)
        have = row.qty if row else 0
        if have > 0:
            users.set_pending(user, "smqty", crop, chat_id_of(update))
        markup = kb.ship_qty_kb(crop, have)
        await s.commit()
    if have <= 0:
        return await respond(update, f"📦 {sd['name']} تو انبارت نداری", markup)
    await respond(
        update,
        "<b>✏️ تعداد دلخواه ارسال</b>\n\n"
        f"🔢 چندتا {sd['name']} می‌فرستی؟ عددشو بنویس\n"
        f"ولی نه بیشتر از {fa_num(have)} تا\n\n"
        "❌ پشیمون شدی بنویس «لغو»",
        markup,
    )


async def ship_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ثبت ارسال محموله (sm:go:<crop>:<n>)، محصول از انبار کم میشه و محموله میفته تو راه"""
    _, _, crop, n = parts(update)
    qty = int(n)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, alert, sh = await smg.send_shipment(s, user, crop, qty, chat_id_of(update))
        ship_note, tq = None, None
        dq_done, dq_left, uname = [], 0, ""
        if ok:
            alert += f" | ⏱ {fa_dur(smg.shipment_seconds())} دیگه میرسه"
            text, markup = await _ship_render(s, user)
            ship_note = await onb.first_shipment(s, user)
            from services import quests as dq_svc  # (راند ۱۵) کوئست روزانه و کارتلی ارسال محموله
            from services import teams as team_svc
            dq_done, dq_left = await dq_svc.track(s, user, "shipment")
            uname = users.display_name(user)
            tq = await team_svc.record_shipment(s, user)
        else:
            text, markup = None, None
        await s.commit()
    if not ok:
        return await respond(update, alert)
    await respond(update, text, markup, alert=alert)
    if ship_note:
        await update.effective_message.reply_html(ship_note)
    if tq or dq_done:
        from handlers.common import announce_notes
        await announce_notes(update, [tq])
        from handlers import dquests
        await dquests.announce_completed(update, uname, dq_done, dq_left)


# ═════════ کاروان قاچاق 🚚 ═════════

async def caravan_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """صفحه کاروان قاچاق (smc:page)، فعال باشه فروش فوری داره"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        cv = await smg.get_caravan(s)
        have = 0
        unit = 0
        if cv:
            row = (await smg.get_products(s, user.id)).get(cv["crop"])
            have = row.qty if row else 0
            unit = await smg.caravan_unit_value(s, user.id, cv["crop"])
        from services.snitch import sell_mult as _sm
        text = smg.caravan_page_text(cv, have, unit, user.cash, _sm(user))
        markup = kb.smcaravan_kb(have if cv else 0)
        await s.commit()
    await respond(update, text, markup)


async def caravan_confirm_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """کارت تایید فروش به کاروان (smc:qty:<n|all>)"""
    n = parts(update)[2]
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        cv = await smg.get_caravan(s)
        row = (await smg.get_products(s, user.id)).get(cv["crop"]) if cv else None
        have = row.qty if row else 0
        qty = have if n == "all" else int(n)
        ok = cv is not None and row is not None and 0 < qty <= have
        from services.snitch import sell_mult as _smlx
        gain = round(int(row.value * qty / row.qty) * (1 + cv["bonus"] / 100) * _smlx(user)) if ok else 0
        await s.commit()
    if not cv:
        return await respond(update, "🚚 کاروان جمع کرد و رفت")
    if not ok:
        sd = config.SEEDS[cv["crop"]]
        return await respond(update, f"📦 {fa_num(qty)} تا {sd['name']} تو انبارت نداری")
    await respond(update, smg.caravan_confirm_text(cv, qty, gain), kb.smcaravan_confirm_kb(qty))


async def caravan_ask_qty_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«✏️ تعداد دلخواه» تو کاروان قاچاق (smc:ask)، تعداد رو با پیام می‌گیریم"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        cv = await smg.get_caravan(s)
        have = 0
        sd = config.SEEDS[cv["crop"]] if cv else None
        if cv:
            row = (await smg.get_products(s, user.id)).get(cv["crop"])
            have = row.qty if row else 0
            if have > 0:
                users.set_pending(user, "smcqty", cv["crop"], chat_id_of(update))
        await s.commit()
    if not cv:
        return await respond(update, "🚚 کاروان جمع کرد و رفت")
    if have <= 0:
        return await respond(update, f"📦 {sd['name']} تو انبارت نداری، اول از مزرعه برداشت کن")
    await respond(
        update,
        "<b>✏️ تعداد دلخواه فروش</b>\n\n"
        f"🔢 چندتا {sd['name']} به کاروان می‌فروشی؟ عددشو بنویس\n"
        f"ولی نه بیشتر از {fa_num(have)} تا\n\n"
        "❌ پشیمون شدی بنویس «لغو»",
    )


async def caravan_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """فروش فوری به کاروان قاچاق (smc:go:<n>)، پول همون لحظه میره رو حساب"""
    qty = int(parts(update)[2])
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, alert, gain = await smg.sell_to_caravan(s, user, qty)
        cv = await smg.get_caravan(s)
        have = 0
        unit = 0
        if cv:
            row = (await smg.get_products(s, user.id)).get(cv["crop"])
            have = row.qty if row else 0
            unit = await smg.caravan_unit_value(s, user.id, cv["crop"])
        from services.snitch import sell_mult as _sm
        text = smg.caravan_page_text(cv, have, unit, user.cash, _sm(user))
        markup = kb.smcaravan_kb(have if cv else 0)
        await s.commit()
    await respond(update, text, markup, alert=f"💰 {money(gain)} گرفتی" if ok else alert)


# ═════════ اسپان دستی کاروان قاچاق (ادمین) ═════════

# اسم محصول به کلید، با و بدون فاصله نوشته میشن (normalize کار رو ساده کرده)
_ADMIN_CROP_KEYS = {
    "کوکائین": "cocaine", "کوکایین": "cocaine",
    "تریاک": "teriak",
    "ماری جوانا": "marijuana", "ماریجوانا": "marijuana",
    "قارچ": "gharch",
    "پیوت": "peyote",
}


async def admin_spawn_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    «اسپان کاروان قاچاق» کاروان تصادفی | «اسپان کاروان کوکائین» کاروان اون محصول
    پسوند «شانسی» بونس رو تصادفی می‌کنه، بدونش بونس پیش‌فرض 45%ـه (فقط ادمین، به غریبه بی‌صدا)
    """
    if not update.effective_user or update.effective_user.id not in config.ADMIN_IDS:
        return

    body = normalize_fa(strip_bot_cmd(update.message.text or ""))
    rest = body.replace("اسپان کاروان", "", 1).strip()
    lucky = "شانسی" in rest.split()
    crop_name = " ".join(w for w in rest.split() if w != "شانسی").strip()

    if crop_name in ("", "قاچاق"):
        crop = random.choice(config.SMUGGLER_CROPS)  # «اسپان کاروان قاچاق» همیشه کاروان تصادفی میاره
    else:
        crop = _ADMIN_CROP_KEYS.get(crop_name)
        if crop is None:
            names = " | ".join(config.SEEDS[k]["name"] for k in config.SMUGGLER_ADMIN_CROPS)
            return await update.message.reply_html(
                f"🤷 این محصول رو نمی‌شناسم\n\nاسپان دستی اینا قبوله:\n{names}"
            )

    bonus = random.randint(config.SMUGGLER_BONUS_MIN, config.SMUGGLER_BONUS_MAX) if lucky else config.SMUGGLER_BONUS_DEFAULT
    async with session_scope() as s:
        cv = await smg.spawn_caravan(s, crop=crop, bonus=bonus)
        await s.commit()
    if not cv:
        return await update.message.reply_html("🚚 الان یه کاروان قاچاق فعاله، اول بذار جمع کنه بره")

    await update.message.reply_html(smg.caravan_announce_text(cv))
    await announce_caravan(context, cv)


async def announce_caravan(context: ContextTypes.DEFAULT_TYPE, cv: dict) -> None:
    """اعلان رسیدن کاروان به گروه‌های فعال (گروه خاموش نه)، پیام‌ها برای ادیت انقضا لیست میشن"""
    from services import power as power_svc
    from services import world as world_svc
    text = smg.caravan_announce_text(cv)
    sent: list[tuple[int, int]] = []
    async with session_scope() as s:
        offs = await power_svc.off_group_ids(s)
        groups = [g for g in await world_svc.active_group_ids(s, config.SMUGGLER_GROUP_ACTIVE_HOURS) if g not in offs]
    for gid in groups:
        try:
            msg = await context.bot.send_message(gid, text, parse_mode="HTML")
            if msg:
                sent.append((gid, msg.message_id))
        except Exception:
            pass
        await asyncio.sleep(config.WEATHER_GROUP_SEND_DELAY)  # پخش یواش، تلگرام محدود نکنه
    if sent:
        async with session_scope() as s:
            for gid, mid in sent:
                await smg.note_caravan_message(s, gid, mid)
            await s.commit()
