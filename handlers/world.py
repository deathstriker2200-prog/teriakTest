"""
سیستم‌های جهان: جستجو 🔍 | آب و هوا 🌦 | بازار سیاه 📈 | انبار 🏚 | قمارخانه 🎰 | کاروان 🚛
"""

from telegram import Update
from telegram.constants import ChatType
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import config
from services import resources as res_svc
from database import session_scope
from handlers.common import chat_id_of, parts, respond
from keyboards import keyboards as kb
from models import GroupActivity
from services import combat, dogs as dog_svc, farming, users
from services import smuggle as smg
from services import world as world_svc
from utils import bar, esc, fa_dur, fa_num, money, money_tp, now_utc


# ═════════ جستجو 🔍 ═════════

async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dq_done, dq_left, uname = [], 0, ""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.apply_energy_regen(user)
        dogs = await dog_svc.get_user_dogs(s, user.id)
        luck = 1.0  # شانس جستجو قبلاً از شخصیت سگ میومد، با حذف شخصیت برای همه خنثیه
        artis = users.artifact_keys(await users.get_item_keys(s, user.id))
        luck = max(luck, users.artifact_luck(artis))
        res = await world_svc.do_search(s, user, luck=luck)
        tq = None
        if res["status"] != "cooldown":
            from services import quests as dq_svc
            dq_done, dq_left = await dq_svc.track(s, user, "search")
            uname = users.display_name(user)
            from services import teams as team_svc
            tq = await team_svc.record_search(s, user)  # کوئست روزانه کارتل، جستجوی اعضا
        cash = user.cash
        await s.commit()

    if tq:
        from handlers.common import announce_notes
        await announce_notes(update, [tq])

    st = res["status"]
    if st == "cooldown":
        return await respond(update, world_svc.search_cooldown_text(res["left"]))

    o = res["outcome"]
    if st == "money":
        text = (
            "<b>🔍 جستجو</b>\n\n"
            f"{o['emoji']} {o['text']}، {money(res['amount'])} گیرت اومد\n\n"
            f"💵 نقدینگی: {money(cash)}"
        )
    elif st == "thief":
        text = (
            "<b>🔍 جستجو</b>\n\n"
            f"{o['emoji']} {o['text']}\n"
            f"💸 {money(res['lost'])} از جیبت رفت، نقدینگی: {money(cash)}"
        )
    else:
        seed_name = config.SEEDS[res["seed"]]["name"]
        tail = (
            "🌾 ولی انبار بذرت پر بود، افتاد زمین 😖"
            if res.get("full") else
            "رفت تو انبارت، بکارش یا نگهش دار 🌾"
        )
        text = (
            "<b>🔍 جستجو</b>\n\n"
            f"{o['emoji']} {o['text']} <b>({esc(seed_name)})</b>\n\n"
            f"{tail}"
        )
    if luck > 1:
        text += "\n\n🍀 سگ خوش‌شانست شانس خوبت رو بیشتر کرد"
    await respond(update, text, kb.home_kb())
    from handlers import dquests
    await dquests.announce_completed(update, uname, dq_done, dq_left)


# ═════════ آب و هوا 🌦 ═════════

async def weather_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        view = await world_svc.weather_view(s)
        key = view["key"]
        left = view["left"]
        await s.commit()

    w = view["w"]
    lines = [
        "<b>🌦 وضعیت آب و هوا</b>",
        "",
        f"{w['emoji']} {w['name']}",
        f"⏳ {fa_dur(left)} دیگه عوض میشه",
        "",
    ]
    if key == "normal":
        lines.append("افکت خاصی فعال نیست، هوا عادیه")
    else:
        lines.append("افکت‌های فعلی:")
        for b in view["effect_lines"]:
            lines.append(f"▫️ {b}")
    lines.append("")
    lines.append("🌦 سر ساعت‌های 6-12-18-24 به وقت ایران عوض میشه و شدت افکتش هم هر بار فرق می‌کنه، تو گروه‌های فعال اعلام میشه")
    await respond(update, "\n".join(lines), kb.home_kb())


# ═════════ بازار سیاه 📈 ═════════

async def market_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        mults, left = await world_svc.market_mults(s)
        await s.commit()

    await respond(update, world_svc.market_view_text(mults, left), kb.home_kb())


# ═════════ انبار 🎒 ═════════

async def _shelter_text(session, user) -> str:
    """صفحه اصلی انبار، خلاصه هر سه دسته + وضعیت کاروان قاچاق + ارتقا"""
    products = await smg.get_products(session, user.id)
    p_kinds = sum(1 for r in products.values() if r.qty > 0)
    p_val = sum(r.value for r in products.values())
    stock = await farming.get_stock(session, user.id)
    seeds_n = sum(stock.values())
    cv = await smg.get_caravan(session)
    if user.shelter_level:
        lvl_line = f"⭐ لول انبار: {fa_num(user.shelter_level)}"
    else:
        lvl_line = "⭐ انبار هنوز نداری"
    if p_kinds:
        prod_lines = [f"🌾 محصولات: {fa_num(p_kinds)} قلم", f"💰 ارزش تقریبی: {money(p_val)}"]
    else:
        prod_lines = ["🌾 محصولات: خالی، اول از مزرعه برداشت کن"]
    lines = [
        "<b>🎒 انبار</b>",
        "",
        lvl_line,
        "",
        *prod_lines,
        "",
        "🧱 منابع",
        f"🪵 چوب: {fa_num(user.wood)}",
        f"⛏️ آهن: {fa_num(user.iron)}",
        f"{config.LEGENDARY_PART_NAME}: {fa_num(getattr(user, 'legendary_parts', 0) or 0)} (ساخت سلاح ویژه) [«مارکت» و هدیه هم میشه]",
        "",
        "📦 آیتم‌ها",
        f"🌱 بذر: {fa_num(seeds_n)}",
        "",
        f"💵 نقدینگی: {money(user.cash)}",
        "",
    ]
    if user.shelter_level < config.SHELTER_MAX_LEVEL:  # خط ارتقا قبل از جمله کاروان (قالب درخواستی کارفرما راند ۲۸)
        price = world_svc.shelter_price(user.shelter_level + 1)
        req = world_svc.shelter_upgrade_min_level(user.shelter_level + 1)
        lock = f" (سطح {fa_num(req)} می‌خواد)" if user.level < req else ""
        lines.append(f"⬆️ ارتقای بعدی: لول {fa_num(user.shelter_level + 1)} | {money(price)}{lock}")
        lines.append("")
    if cv:
        sd = config.SEEDS[cv["crop"]]
        lines.append(f"🚚 کاروان قاچاق رسیده و تا {fa_dur(smg.cv_left(cv))} دیگه جمع می‌کنه میره")
        lines.append(f"{sd.get('emoji', '🌱')} محصول موردنیاز: {sd['name']}")
        lines.append(f"📈 قیمت خرید {fa_num(cv['bonus'])}% بیشتر")
    else:
        lines.append(f"🚚 کاروان قاچاق هر {fa_num(config.SMUGGLER_INTERVAL_HOURS)} ساعت یک‌بار به شهر سر می‌زند و یکی از محصولات را با قیمت بالاتر خریداری می‌کند")
    return "\n".join(lines)


async def _shelter_cat_text(session, user, cat: str) -> str:
    """متن صفحه دسته‌بندی انبار: prod محصولات با نوار ظرفیت | res منابع | item آیتم‌ها"""
    if cat == "prod":
        products = await smg.get_products(session, user.id)
        cap = smg.products_cap(user.shelter_level or 0)
        total_val = sum(r.value for r in products.values() if r.qty > 0)
        lines = [
            "<b>🌾 محصولات</b>",
            "",
            "محصولای برداشت‌شده‌ات اینجان، هنوز نقد نشدن",
            "از بخش 📦 ارسال محموله یا 🚚 کاروان قاچاق بفروش و نقدشون کن",
            "",
            f"📦 ظرفیت انبار هر محصول {fa_num(cap)} تا (با ارتقای انبار بیشتر میشه)",
            "",
        ]
        if not products:
            lines.append("▫️ هنوز محصولی نداری، از مزرعه برداشت کن")
        else:
            lines.append(f"ارزش کل محصولات موجود تقریبا {money(total_val)}")
            lines.append("")
        for key, sd in config.SEEDS.items():
            row = products.get(key)
            if not row or row.qty <= 0:
                continue
            lines.append(f"{sd.get('emoji', '🌱')} {sd['name']} {bar(row.qty, cap)} {fa_num(row.qty)}/{fa_num(cap)}")
            lines.append(f"🪙 ارزش تقریبی {money(row.value)}")
        return "\n".join(lines)

    if cat == "res":
        wcap, icap = res_svc.wood_cap(user), res_svc.iron_cap(user)
        return "\n".join([
            "<b>🧱 منابع</b>",
            "",
            f"🪵 چوب {bar(user.wood, wcap)} {fa_num(user.wood)}/{fa_num(wcap)}",
            f"⛏️ آهن {bar(user.iron, icap)} {fa_num(user.iron)}/{fa_num(icap)}",
            "",
            "چوب و آهن اضافه رو میتونی از بخش فروش منابع بفروشی",
            "با ارتقای انبار ظرفیتشون بیشتر میشه",
        ])

    if cat == "item":
        cap = world_svc.seed_storage_cap(user)
        stock = await farming.get_stock(session, user.id)
        lines = [
            "<b>📦 آیتم‌ها</b>",
            "",
            f"📦 ظرفیت انبار هر نوع بذر: {fa_num(cap)}",
            "",
            "🌱 بذرها",
            "",
        ]
        # همه بذرهای پایه با نوار، حتی صفر (چیدمان درخواستی کارفرما)، افسانه‌ای‌ها جدا تهش
        for key, sd in config.SEEDS.items():
            if sd.get("legendary"):
                continue
            cnt = stock.get(key, 0)
            lines.append(f"{sd['emoji']} {sd['name']} {bar(cnt, cap)} {fa_num(cnt)}/{fa_num(cap)}")
        legend = [f"{sd.get('emoji', '✨')} {sd['name']} ×{fa_num(stock.get(key, 0))}"
                  for key, sd in config.SEEDS.items() if sd.get("legendary") and stock.get(key, 0) > 0]
        if legend:
            lines += ["", "✨ بذرهای افسانه‌ای:"] + legend
        return "\n".join(lines)

    return await _shelter_cat_text(session, user, "prod")  # دسته‌بندی فرمول‌ها حذف شده (درخواست کارفرما)


async def shelter_cat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cat = parts(update)[2]
    if cat not in ("prod", "res", "item"):
        return await shelter_cmd(update, context)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        text = await _shelter_cat_text(s, user, cat)
        if cat == "prod":
            markup = kb.shelter_back_kb()
        elif cat == "res":
            markup = kb.shelter_res_kb()
        else:
            markup = kb.shelter_back_kb()
        await s.commit()
    await respond(update, text, markup)


# ═════════ فروش منابع 💰 (بخش مخفیگاه) ═════════

def _resource_sell_text(user, mults: dict | None = None) -> str:
    # راند جدید: قیمت چوب و آهن دیگه به فروش ربطی نداره، هر رول بازار یه عدد کاملاً شانسی تو بازه ثابت خودشه
    wood_price = res_svc.sell_price_market(mults or {}, "wood")
    iron_price = res_svc.sell_price_market(mults or {}, "iron")
    return "\n".join([
        "<b>💰 فروش منابع</b>",
        "",
        f"🪵 چوب {fa_num(user.wood)} تا داری: دونه‌ای {money(wood_price)}",
        f"⛏️ آهن {fa_num(user.iron)} تا داری: دونه‌ای {money(iron_price)}",
        "",
        "قیمت چوب و آهن هر بار که بازار عوض میشه کاملاً شانسی تعیین میشه، فروش خودت روش اثری نداره",
        "بنویس چی و چقدر می‌خوای بفروشی، مثلا «آهن 300» یا «چوب 200» (فقط چوب و آهن قابل فروش‌اند)",
        "بعدش مبلغشو می‌گیری و تایید می‌کنی",
        "",
        "❌ اگر هم پشیمون شدی بنویس «لغو»",
    ])


async def resource_sell_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from services import world as world_svc
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.set_pending(user, "ressell", None, chat_id_of(update))
        mults, _ = await world_svc.market_mults(s)
        text = _resource_sell_text(user, mults)
        await s.commit()
    await respond(update, text, kb.sell_menu_kb())


async def sellres_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, res, amount = parts(update)
    name = "چوب" if res == "wood" else "آهن"
    emoji = "🪵" if res == "wood" else "⛏️"
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        from services import world as world_svc
        mults30, _ = await world_svc.market_mults(s)
        ok, err, total = res_svc.sell_resource(user, res, int(amount), res_svc.sell_price_market(mults30, res))
        cash = user.cash
        dq_done, dq_left, uname, tq = [], 0, "", None
        if ok:  # (راند ۱۵) کوئست روزانه و کارتلی فروش منابع با تعداد واحد
            from services import quests as dq_svc
            from services import teams as team_svc
            dq_done, dq_left = await dq_svc.track(s, user, "sellres", int(amount))
            uname = users.display_name(user)
            tq = await team_svc.record_sellres(s, user, int(amount))
        await s.commit()
    if not ok:
        return await respond(update, err, kb.sell_menu_kb())
    text = (
        f"<b>💰 {money(total)} گرفتی</b>\n\n"
        f"{emoji} {fa_num(int(amount))} {name} فروخته شد\n"
        f"💵 نقدینگی: {money(cash)}"
    )
    await respond(update, text, kb.sell_menu_kb())
    if tq or dq_done:
        from handlers.common import announce_notes
        await announce_notes(update, [tq])
        from handlers import dquests
        await dquests.announce_completed(update, uname, dq_done, dq_left)


async def sellres_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await shelter_cmd(update, context)


async def shelter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        text = await _shelter_text(s, user)
        markup = kb.shelter_kb(user, caravan_on=bool(await smg.get_caravan(s)))
        await s.commit()
    await respond(update, text, markup)


async def shelter_up_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        if user.shelter_level >= config.SHELTER_MAX_LEVEL:
            await s.commit()
            return await shelter_cmd(update, None)
        price = world_svc.shelter_price(user.shelter_level + 1)
        level = user.shelter_level
        cash = user.cash
        await s.commit()

    text = (
        f"<b>🏚 ارتقای انبار، لول {fa_num(level)} ← {fa_num(level + 1)}</b>\n\n"
        f"💸 هزینه {money(price)}\n"
        f"💵 الان {money(cash)} داری\n\n"
        "انجامش بدیم؟"
    )
    await respond(update, text, kb.confirm_kb("cf:shelter:up"))


async def shelter_up_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg = await world_svc.upgrade_shelter(s, user)
        text = await _shelter_text(s, user)
        markup = kb.shelter_kb(user, caravan_on=bool(await smg.get_caravan(s)))
        cash = user.cash
        await s.commit()
    if ok:
        return await respond(
            update,
            text + f"\n\n{esc(msg)}\n💵 نقدینگی: {money(cash)}",
            markup, alert="🏚 انبار ارتقا پیدا کرد",
        )
    await respond(update, text, markup, alert=msg)


# ═════════ کاروان 🚛، دکمه حمله تو گروه ═════════

async def caravan_hit_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id if query.message else update.effective_chat.id

    # دیبانس: کلیک تندتند دکمه بی‌صدا جواب خالی می‌گیره تا اسپم سرور رو خسته نکنه
    if world_svc.caravan_click_spam(chat_id, update.effective_user.id):
        await query.answer()
        return

    cv = world_svc.caravan_active(chat_id)
    if not cv:
        await query.answer("🚛 کاروانی تو محله نیس", show_alert=True)
        return

    left = world_svc.caravan_hit_left(chat_id, update.effective_user.id)
    if left:
        await query.answer(f"⏳ هر 1 دقیقه یه ضربه، {left} ثانیه مونده", show_alert=True)
        return

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        items = await users.get_item_levels(s, user.id)
        ammo = await users.get_ammo_map(s, user.id)  # راند ۲۹: تفنگ بی‌تیر تو دمیج کاروان حساب نیس
        dogs = await dog_svc.get_user_dogs(s, user.id)
        from services import teams as team_svc
        user_team = await team_svc.get_team_of(s, user.id)
        team_b = team_svc.atk_bonus(user_team) if user_team else 0.0
        atk, _ = combat.combat_stats(user, items, dogs, atk_extra=team_b, ammo=ammo)
        # هر ضربه به کاروان یه تیر (درخواست کارفرما راند ۲۹)
        wkey_cv = combat.weapon_choice(user, items, ammo)
        ammo_note = ""
        if wkey_cv and combat.is_gun(wkey_cv):
            _left_am = await users.consume_ammo(s, user.id, wkey_cv)
            if _left_am >= 0:
                ammo_note = f"، 🔫 {fa_num(_left_am)}/{fa_num(combat.ammo_cap(wkey_cv, items.get(wkey_cv, 1)))}"

        res = await world_svc.caravan_attack(s, chat_id, user, atk)
        dq_done, dq_left, uname = [], 0, ""
        if res["status"] in ("hit", "killed"):
            tq = await team_svc.record_caravan(s, user)  # کوئست روزانه کارتل، ضربه به کاروان
            if tq:
                res.setdefault("notes", []).append(tq)
            from services import quests as dq_svc
            dq_done, dq_left = await dq_svc.track(s, user, "caravan")  # (راند ۱۵) کوئست روزانه ضربه کاروان
            uname = users.display_name(user)
        await s.commit()

    if res["status"] == "cooldown":
        await query.answer(f"⏳ {res['left']} ثانیه مونده", show_alert=True)
        return

    await query.answer(f"⚔️ {fa_num(res['dmg'])} دمیج، 💰 {fa_num(res['cash'])}TP{ammo_note}", show_alert=True)

    # تبریک لول‌آپ (تجربه ضربه کاروان) پیام جدا تو همون گروه
    from handlers.common import announce_notes
    await announce_notes(update, res.get("notes"))
    if dq_done:
        from handlers import dquests
        await dquests.announce_completed(update, uname, dq_done, dq_left)

    # برد کاروان بعد هر ضربه ادیت نمیشه، جاب 2 دقیقه‌ای خودش رفرشش می‌کنه

    if res["status"] == "killed":
        # غارت کامل، برد پاک میشه و پیام پایانی تازه ارسال میشه
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
        except BadRequest:
            pass
        end_text = world_svc.caravan_end_text(res.get("rewards", []), killed=True)
        await context.bot.send_message(chat_id, end_text, parse_mode="HTML")


# ═════════ اسپون دستی کاروان (ادمین) ═════════

async def caravan_spawn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«تی اسپان کاروان»، اسپون فوری کاروان توی همون گروه، فقط ادمین (به غریبه بی‌صدا)"""
    if not update.effective_user or update.effective_user.id not in config.ADMIN_IDS:
        return

    chat = update.effective_chat
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.message.reply_html("این دستور رو توی گروه بزن تا کاروان همونجا اسپون بشه 🚛")
        return

    if world_svc.caravan_active(chat.id):
        await update.message.reply_html("🚛 الان یه کاروان فعال توی محله‌ست، اول بذار تموم بشه")
        return

    cv = world_svc.caravan_spawn(chat.id)
    async with session_scope() as s:
        row = await s.get(GroupActivity, chat.id)
        if row:
            row.last_caravan_at = now_utc()
        else:
            s.add(GroupActivity(chat_id=chat.id, last_caravan_at=now_utc()))
        await s.commit()

    msg = await update.message.reply_html(
        world_svc.caravan_board_text(cv), reply_markup=kb.caravan_kb(),
    )
    if msg:
        cv["message_id"] = msg.message_id
