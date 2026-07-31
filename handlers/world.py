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
            tq = await team_svc.record_search(s, user)  # کوئست روزانه تیم، جستجوی اعضا
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
        text = (
            "<b>🔍 جستجو</b>\n\n"
            f"{o['emoji']} {o['text']} <b>({esc(seed_name)})</b>\n\n"
            "رفت تو انبارت، بکارش یا نگهش دار 🌾"
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


# ═════════ انبار 🏚 ═════════

async def _shelter_text(session, user) -> str:
    cap = world_svc.seed_storage_cap(user)
    wcap, icap = res_svc.wood_cap(user), res_svc.iron_cap(user)
    stock = await farming.get_stock(session, user.id)
    lines = [
        "<b>🏚 انبار</b>",
        "",
        f"⭐ لول {fa_num(user.shelter_level)}" + (f" از {fa_num(config.SHELTER_MAX_LEVEL)}" if user.shelter_level else "، هنوز نداری"),
        "",
        f"📦 ظرفیت انبار هر بذر {fa_num(cap)} تا",
        "",
        f"🪵 چوب {bar(user.wood, wcap)} {fa_num(user.wood)}/{fa_num(wcap)}",
        f"⛏️ آهن {bar(user.iron, icap)} {fa_num(user.iron)}/{fa_num(icap)}",
        "",  # فاصله بین منابع و بذرها که توهم نرن
    ]
    # بذرهای انبار هم مثل چوب و آهن با نوار پرشوندگی نشون داده میشن (۵ بذر پایه، افسانه‌ای‌ها نه)
    for key, sd in config.SEEDS.items():
        if sd.get("legendary"):
            continue
        cnt = stock.get(key, 0)
        lines.append(f"{sd['emoji']} {sd['name']} {bar(cnt, cap)} {fa_num(cnt)}/{fa_num(cap)}")
    lines += [
        "",
        "با ارتقا، ظرفیت بذر و چوب و آهن هم بیشتر میشه",
        "چوب و آهن اضافه رو هم می‌تونی از بخش فروش منابع بفروشی",
    ]
    if user.shelter_level < config.SHELTER_MAX_LEVEL:
        price = world_svc.shelter_price(user.shelter_level + 1)
        req = world_svc.shelter_upgrade_min_level(user.shelter_level + 1)
        lock = f" (سطح {fa_num(req)} می‌خواد)" if user.level < req else ""
        lines.append(f"\n⬆️ ارتقای بعدی: لول {fa_num(user.shelter_level + 1)} | {money(price)}{lock}")
    return "\n".join(lines)


# ═════════ فروش منابع 💰 (بخش مخفیگاه) ═════════

def _resource_sell_text(user) -> str:
    wood_price = res_svc.sell_price("wood")
    iron_price = res_svc.sell_price("iron")
    return "\n".join([
        "<b>💰 فروش منابع</b>",
        "",
        f"🪵 چوب {fa_num(user.wood)} تا داری: دونه‌ای {money(wood_price)}",
        f"⛏️ آهن {fa_num(user.iron)} تا داری: دونه‌ای {money(iron_price)}",
        "",
        "بنویس چی و چقدر می‌خوای بفروشی، مثلا «آهن 300» یا «چوب 200» (فقط چوب و آهن قابل فروش‌اند)",
        "بعدش مبلغشو می‌گیری و تایید می‌کنی",
        "",
        "❌ اگر هم پشیمون شدی بنویس «لغو»",
    ])


async def resource_sell_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.set_pending(user, "ressell", None, chat_id_of(update))
        text = _resource_sell_text(user)
        await s.commit()
    await respond(update, text, kb.sell_menu_kb())


async def sellres_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, res, amount = parts(update)
    name = "چوب" if res == "wood" else "آهن"
    emoji = "🪵" if res == "wood" else "⛏️"
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, err, total = res_svc.sell_resource(user, res, int(amount))
        cash = user.cash
        await s.commit()
    if not ok:
        return await respond(update, err, kb.sell_menu_kb())
    text = (
        f"<b>💰 {money(total)} گرفتی</b>\n\n"
        f"{emoji} {fa_num(int(amount))} {name} فروخته شد\n"
        f"💵 نقدینگی: {money(cash)}"
    )
    await respond(update, text, kb.sell_menu_kb())


async def sellres_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await shelter_cmd(update, context)


async def shelter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        text = await _shelter_text(s, user)
        markup = kb.shelter_kb(user)
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
        markup = kb.shelter_kb(user)
        cash = user.cash
        await s.commit()
    if ok:
        return await respond(
            update,
            text + f"\n\n{esc(msg)}\n💵 نقدینگی: {money(cash)}",
            markup, alert="🏚 انبار ارتقا پیدا کرد",
        )
    await respond(update, text, markup, alert=msg)


# ═════════ قمارخانه 🎰 ═════════

async def casino_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        level, cash = user.level, user.cash
        left = world_svc.casino_cooldown_left(user)
        await s.commit()

    if level < config.CASINO_MIN_LEVEL:
        return await respond(update, f"🔒 قمارخانه از لول {fa_num(config.CASINO_MIN_LEVEL)} باز میشه")
    if left:
        return await respond(update, f"⏳ هر {fa_num(config.CASINO_COOLDOWN_HOURS)} ساعت یه دست می‌تونی بازی کنی، {fa_dur(left)} مونده")

    text = (
        "<b>🎰 قمارخانه</b>\n\n"
        f"شانس برد {fa_num(int(config.CASINO_WIN_CHANCE * 100))}% | برد = {config.CASINO_WIN_MULT} برابر شرط\n"
        f"یه دست هر {fa_num(config.CASINO_COOLDOWN_HOURS)} ساعت\n"
        f"💵 نقدینگی: {money(cash)}\n\n"
        "میزتو انتخاب کن 🎲"
    )
    await respond(update, text, kb.casino_kb())


async def casino_bet_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bet = int(parts(update)[2])
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        cash = user.cash
        left = world_svc.casino_cooldown_left(user)
        await s.commit()

    if left:
        return await respond(update, f"⏳ {fa_dur(left)} دیگه می‌تونی بازی کنی")
    if cash < bet:
        return await respond(update, "❌ پولت به این میز نمی‌رسه")

    prize = int(bet * config.CASINO_WIN_MULT)
    text = (
        f"<b>🎰 میز {money(bet)}</b>\n\n"
        f"بردی → {money(prize)} جیبت میشه\n"
        f"باختی → {money(bet)} میره رو دیلر\n"
        f"شانس برد {fa_num(int(config.CASINO_WIN_CHANCE * 100))}%\n\n"
        "قماره ها، بازی کنیم؟"
    )
    await respond(update, text, kb.confirm_kb(f"cascf:{bet}"))


async def casino_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bet = int(parts(update)[1])
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        res = await world_svc.casino_play(s, user, bet)
        await s.commit()

    st = res["status"]
    if st == "cooldown":
        return await respond(update, f"⏳ {fa_dur(res['left'])} دیگه می‌تونی بازی کنی")
    if st == "poor":
        return await respond(update, "❌ پولت به این میز نمی‌رسه")
    if st == "locked":
        return await respond(update, f"🔒 قمارخانه از لول {fa_num(config.CASINO_MIN_LEVEL)} باز میشه")

    if st == "win":
        text = (
            "<b>🎰 زدی تو خال</b>\n\n"
            f"💰 {money(res['prize'])} برنده شدی\n\n"
            f"💵 موجودی فعلی\n{money(res['cash'])}\n\n"
            f"⏳ دست بعدی\n{fa_num(config.CASINO_COOLDOWN_HOURS)} ساعت دیگه"
        )
    else:
        text = (
            "<b>🎰 این دست شانس باهات یار نبود</b>\n\n"
            f"💸 {money(res['bet'])} رو باختی\n\n"
            f"💰 موجودی فعلی\n{money(res['cash'])}\n\n"
            f"⏳ دست بعدی\n{fa_num(config.CASINO_COOLDOWN_HOURS)} ساعت دیگه"
        )
    await respond(update, text, kb.home_kb())


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
        items = await users.get_item_keys(s, user.id)
        dogs = await dog_svc.get_user_dogs(s, user.id)
        atk, _ = combat.combat_stats(user, items, dogs)

        user_team = None
        from services import teams as team_svc
        user_team = await team_svc.get_team_of(s, user.id)
        if user_team:
            atk = int(atk * (1 + team_svc.atk_bonus(user_team)))

        res = await world_svc.caravan_attack(s, chat_id, user, atk)
        if res["status"] in ("hit", "killed"):
            tq = await team_svc.record_caravan(s, user)  # کوئست روزانه تیم، ضربه به کاروان
            if tq:
                res.setdefault("notes", []).append(tq)
        await s.commit()

    if res["status"] == "cooldown":
        await query.answer(f"⏳ {res['left']} ثانیه مونده", show_alert=True)
        return

    await query.answer(f"⚔️ {fa_num(res['dmg'])} دمیج، 💰 {fa_num(res['cash'])}TP", show_alert=True)

    # تبریک لول‌آپ (تجربه ضربه کاروان) پیام جدا تو همون گروه
    from handlers.common import announce_notes
    await announce_notes(update, res.get("notes"))

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
