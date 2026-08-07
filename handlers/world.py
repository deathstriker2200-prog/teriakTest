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
from services import casino as casino_svc
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
        "",
        "📦 آیتم‌ها",
        f"🌱 بذر: {fa_num(seeds_n)}",
        "",
        f"💵 نقدینگی: {money(user.cash)}",
        "",
    ]
    if cv:
        sd = config.SEEDS[cv["crop"]]
        lines.append(f"🚚 کاروان قاچاق رسیده و تا {fa_dur(smg.cv_left(cv))} دیگه جمع می‌کنه میره")
        lines.append(f"{sd.get('emoji', '🌱')} محصول موردنیاز: {sd['name']}")
        lines.append(f"📈 قیمت خرید {fa_num(cv['bonus'])}% بیشتر")
    else:
        lines.append(f"🚚 کاروان قاچاق هر {fa_num(config.SMUGGLER_INTERVAL_HOURS)} ساعت یک‌بار به شهر سر می‌زند و یکی از محصولات را با قیمت بالاتر خریداری می‌کند")
    if user.shelter_level < config.SHELTER_MAX_LEVEL:
        price = world_svc.shelter_price(user.shelter_level + 1)
        req = world_svc.shelter_upgrade_min_level(user.shelter_level + 1)
        lock = f" (سطح {fa_num(req)} می‌خواد)" if user.level < req else ""
        lines.append(f"\n⬆️ ارتقای بعدی: لول {fa_num(user.shelter_level + 1)} | {money(price)}{lock}")
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
        dq_done, dq_left, uname, tq = [], 0, "", None
        if ok:  # (راند ۱۵) کوئست روزانه و تیمی فروش منابع با تعداد واحد
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


# ═════════ قمارخانه 🎰 ═════════

def _casino_home_text(cash: int) -> str:
    games = "\n".join(f"{g['name']} → {g['desc']}" for g in casino_svc.GAMES.values())
    return (
        "<b>🎰 قمارخانه</b>\n\n"
        f"یه بازی هر {fa_num(config.CASINO_COOLDOWN_MINUTES)} دقیقه\n"
        f"💵 نقدینگی: {money(cash)}\n\n"
        f"{games}\n\n"
        "روی یه بازی بزن 🎲"
    )


async def casino_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """منوی بازی‌های قمارخانه (راند ۱۹: پنج بازی + تایم نیم‌ساعت، درخواست کارفرما)"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        level, cash = user.level, user.cash
        left = world_svc.casino_cooldown_left(user)
        await s.commit()

    if level < config.CASINO_MIN_LEVEL:
        return await respond(update, f"🔒 قمارخانه از لول {fa_num(config.CASINO_MIN_LEVEL)} باز میشه")
    if left:
        return await respond(update, f"⏳ هر {fa_num(config.CASINO_COOLDOWN_MINUTES)} دقیقه یه بازی می‌تونی، {fa_dur(left)} مونده")

    await respond(update, _casino_home_text(cash), kb.casino_games_kb())


def _casino_win_text(res: dict) -> str:
    name = casino_svc.GAMES[res["game"]]["name"]
    extra = ""
    if res.get("roll") is not None:
        extra = f"🎲 تاس {fa_num(res['roll'])} اومد\n"
    if res.get("seg") is not None:
        extra = f"🎡 گردونه روی ×{fa_num(res['seg'])} وایساد\n"
    return (
        f"<b>{name} | زدی تو خال</b>\n\n"
        f"{extra}"
        f"💰 {money(res['prize'])} برنده شدی (×{fa_num(res['mult'])})\n\n"
        f"💵 موجودی فعلی\n{money(res['cash'])}\n\n"
        f"⏳ بازی بعدی\n{fa_num(config.CASINO_COOLDOWN_MINUTES)} دقیقه دیگه"
    )


def _casino_lose_text(res: dict) -> str:
    name = casino_svc.GAMES[res["game"]]["name"]
    extra = ""
    if res.get("roll") is not None:
        extra = f"🎲 تاس {fa_num(res['roll'])} اومد\n"
    if res.get("seg") is not None:
        extra = "🎡 گردونه روی ۰ وایساد\n"
    if res.get("nxt") is not None:
        extra = f"🃏 کارت {casino_svc.card_name(res['nxt'])} اومد و حدست غلط بود\n"
    if res.get("level") is not None and res["game"] == "mines":
        extra = f"💣 لول {fa_num(res['level'])} بمب گرفتی\n"
    return (
        f"<b>{name} | این دست شانس باهات یار نبود</b>\n\n"
        f"{extra}"
        f"💸 {money(res['bet'])} رو باختی\n\n"
        f"💵 موجودی فعلی\n{money(res['cash'])}\n\n"
        f"⏳ بازی بعدی\n{fa_num(config.CASINO_COOLDOWN_MINUTES)} دقیقه دیگه"
    )


def _card_screen(res: dict, user_cash: int) -> tuple[str, object]:
    """صفحه جاری بازی کارت؛ دکمه بالا/پایین فقط اگه ممکن باشه"""
    card = res["card"]
    can_hi, can_lo = card < 14, card > 2
    mult = res["mult"]
    text = (
        "<b>🃏 کارت بالا/پایین</b>\n\n"
        f"🂠 کارت فعلی: <b>{casino_svc.card_name(card)}</b>\n"
        f"✖️ ضریب الان: ×{fa_num(mult)} → کش‌اوت = {money(int(res['bet'] * mult))}\n\n"
        "کارت بعدی بزرگتر میاد یا کوچیک‌تر؟"
    )
    return text, kb.casino_card_kb(can_hi, can_lo)


def _mines_screen(state: dict, user_cash: int) -> tuple[str, object]:
    lvl = state["level"]
    total = len(config.CASINO_MINES_LEVELS)
    nxt_p = config.CASINO_MINES_LEVELS[lvl][0] if lvl < total else 0
    mult = casino_svc.mines_cashout_mult(lvl)
    lines = [
        "<b>💣 مین</b>",
        "",
        f"🚩 لول {fa_num(lvl)} از {fa_num(total)}",
    ]
    if lvl:
        lines.append(f"💰 کش‌اوت الان: ×{fa_num(mult)} یعنی {money(int(state['bet'] * mult))}")
    lines += [
        "",
        f"هشدار لول بعد: شانس بمب {fa_num(int(nxt_p * 100))}%",
        "یکی از خونه‌ها بمبه، بقیش جایزه؛ هرچی جلوتر ضریب بیشتر و ریسک بیشتر",
    ]
    return "\n".join(lines), kb.casino_mines_kb(lvl)


async def casino_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """روتر همه دکمه‌های قمارخانه: csg:* و cf:csg:go / cl:csg:* (راند ۱۹)"""
    query = update.callback_query
    data = query.data
    if data.startswith("cl:"):
        data = "csg:home"
    elif data.startswith("cf:"):
        data = data[3:]
    if not data.startswith("csg:"):
        return
    parts = data.split(":")[1:]
    act = parts[0]

    if act == "home":
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            cash = user.cash
            await s.commit()
        return await respond(update, _casino_home_text(cash), kb.casino_games_kb())

    if act == "b":
        game = parts[1]
        g = casino_svc.GAMES.get(game)
        if not g:
            return
        text = (
            f"<b>{g['name']}</b>\n\n"
            f"{g['desc']}\n\n"
            "میزتو انتخاب کن 🎲"
        )
        return await respond(update, text, kb.casino_bets_kb(game))

    if act == "bet":
        game, bet = parts[1], int(parts[2])
        g = casino_svc.GAMES.get(game)
        if not g:
            return
        outs = {
            "simple": f"بردی → {money(int(bet * config.CASINO_WIN_MULT))} جیبت میشه",
            "dice": f"بردی → {money(int(bet * config.CASINO_DICE_MULT))} جیبت میشه",
            "wheel": "گردونه می‌چرخه و هر ضریبی وایسه همون میشه",
            "card": f"هر حدس درست ضریبت بزرگ‌تر میشه، سقفش {fa_num(config.CASINO_CARD_MAX_STEPS)} حدسه",
            "mines": f"{fa_num(len(config.CASINO_MINES_LEVELS))} لول داره، قبل بمب کش‌اوت کن",
        }
        text = (
            f"<b>{g['name']} | میز {money(bet)}</b>\n\n"
            f"{outs[game]}\n"
            f"باختی → {money(bet)} میره رو دیلر\n\n"
            "قماره ها، بازی کنیم؟"
        )
        return await respond(update, text, kb.confirm_kb(f"csg:go:{game}:{bet}"))

    if act == "go":
        game, bet = parts[1], int(parts[2])
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            res = await casino_svc.start(s, user, game, bet)
            cash = user.cash
            await s.commit()
        st = res["status"]
        if st == "cooldown":
            async with session_scope() as s2:
                user2, _ = await users.get_or_create(s2, update.effective_user)
                left = world_svc.casino_cooldown_left(user2)
            return await respond(update, f"⏳ {fa_dur(left)} دیگه می‌تونی بازی کنی")
        if st == "poor":
            return await respond(update, "❌ پولت به این میز نمی‌رسه")
        if st == "locked":
            return await respond(update, f"🔒 قمارخانه از لول {fa_num(config.CASINO_MIN_LEVEL)} باز میشه")
        if st in ("win", "lose"):
            txt = _casino_win_text(res) if st == "win" else _casino_lose_text(res)
            return await respond(update, txt, kb.home_kb())
        if st == "started" and res.get("card") is not None:
            txt, markup = _card_screen(res, cash)
            return await respond(update, txt, markup)
        if st == "started":
            txt, markup = _mines_screen(res, cash)
            return await respond(update, txt, markup)
        return await respond(update, "❌ این بازی الان در دسترس نیس")

    if act in ("hi", "lo"):
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            res = await casino_svc.card_step(s, user, act)
            cash = user.cash
            await s.commit()
        if res["status"] == "no_game":
            return await query.answer("⌛ این بازی تموم شده، از قمارخانه یه بازی تازه بزن", show_alert=True)
        if res["status"] in ("win", "lose"):
            txt = _casino_win_text(res) if res["status"] == "win" else _casino_lose_text(res)
            return await respond(update, txt, kb.home_kb())
        txt, markup = _card_screen(res, cash)
        return await respond(update, txt, markup)

    if act == "cell":
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            res = await casino_svc.mines_step(s, user)
            cash = user.cash
            await s.commit()
        if res["status"] == "no_game":
            return await query.answer("⌛ این بازی تموم شده، از قمارخانه یه بازی تازه بزن", show_alert=True)
        if res["status"] in ("win", "lose"):
            txt = _casino_win_text(res) if res["status"] == "win" else _casino_lose_text(res)
            return await respond(update, txt, kb.home_kb())
        txt, markup = _mines_screen(res, cash)
        return await respond(update, txt, markup)

    if act == "out":
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            res = await casino_svc.cash_out(s, user)
            await s.commit()
        if res["status"] == "no_game":
            return await query.answer("⌛ بازی فعالی نداری", show_alert=True)
        if res["prize"] == res["bet"]:
            txt = (
                f"<b>{casino_svc.GAMES[res['game']]['name']} | کش‌اوت سر جا</b>\n\n"
                f"هنوز جلو نرفته بودی، شرطت {money(res['bet'])} برگشت جیبت\n"
                f"💵 موجودی: {money(res['cash'])}"
            )
        else:
            auto_line = "خودکار تو آخرین مرحله | " if res.get("auto") else ""
            txt = (
                f"<b>{casino_svc.GAMES[res['game']]['name']} | 💰 کش‌اوت موفق</b>\n\n"
                f"{auto_line}×{fa_num(res['mult'])} اومدی بیرون\n"
                f"💰 {money(res['prize'])} جیبت شد\n\n"
                f"💵 موجودی فعلی\n{money(res['cash'])}\n\n"
                f"⏳ بازی بعدی\n{fa_num(config.CASINO_COOLDOWN_MINUTES)} دقیقه دیگه"
            )
        return await respond(update, txt, kb.home_kb())


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
        from services import teams as team_svc
        user_team = await team_svc.get_team_of(s, user.id)
        team_b = team_svc.atk_bonus(user_team) if user_team else 0.0
        atk, _ = combat.combat_stats(user, items, dogs, atk_extra=team_b)

        res = await world_svc.caravan_attack(s, chat_id, user, atk)
        dq_done, dq_left, uname = [], 0, ""
        if res["status"] in ("hit", "killed"):
            tq = await team_svc.record_caravan(s, user)  # کوئست روزانه تیم، ضربه به کاروان
            if tq:
                res.setdefault("notes", []).append(tq)
            from services import quests as dq_svc
            dq_done, dq_left = await dq_svc.track(s, user, "caravan")  # (راند ۱۵) کوئست روزانه ضربه کاروان
            uname = users.display_name(user)
        await s.commit()

    if res["status"] == "cooldown":
        await query.answer(f"⏳ {res['left']} ثانیه مونده", show_alert=True)
        return

    await query.answer(f"⚔️ {fa_num(res['dmg'])} دمیج، 💰 {fa_num(res['cash'])}TP", show_alert=True)

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
