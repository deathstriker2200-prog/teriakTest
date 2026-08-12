"""
دستورهای متنی فارسی، هم PV هم گروه، همه با پیشوند «تریاکی »
«تریاکی شاپ» «تریاکی پروفایل» «تریاکی خرید چاقو» «تریاکی خرید سگ دوبرمن» «تریاکی کاشت ماری جوانا»
«تریاکی واریز 1200» «تریاکی برداشت محصول» «تریاکی مزرعه» «تریاکی سگ‌های من» (نبرد گروهی توی handlers/battle.py)

⚠️ برای کار کردن تو گروه، Privacy Mode ربات باید توی BotFather خاموش باشه
"""

import re

from telegram import Update
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import chat_id_of, parts, respond, strip_bot_cmd
from handlers import dogs as dogs_h
from handlers import farm as farm_h
from handlers import profile as profile_h
from handlers import shop as shop_h
from keyboards import keyboards as kb
from services import dogs as dog_svc, farming, shop_svc, users
from utils import esc, fa_dur, fa_num, find_by_name, money, normalize_fa, parse_amount


# ───────── ابزار ─────────

def _match_arg(update: Update) -> str:
    """بخش بعد از فعل دستور، مثلا «چاقو» از «تریاکی خرید چاقو»"""
    text = strip_bot_cmd(update.message.text or "")
    m = re.match(r"^\S+\s+(.+)$", text)
    return m.group(1) if m else ""


# ───────── شاپ و پروفایل و مزرعه و سگ‌ها (متنی) ─────────

async def shop_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await shop_h.shop_cb(update, context)


async def profile_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await profile_h.profile_photo_cmd(update, context)


async def farm_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await farm_h.render_farm(update)


async def dogs_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await dogs_h.render_my_dogs(update)


# ───────── خرید متنی ─────────

async def buy_dog_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = _match_arg(update)
    dog_query = normalize_fa(query)
    if dog_query.startswith("سگ "):
        dog_query = dog_query[3:]

    key, dog, custom_name = dog_svc.parse_dog_query(dog_query)
    if not key:
        names = " | ".join(d["name"] for d in config.DOGS.values())
        return await respond(update, f"🤷 سگی با این اسم پیدا نشد\n\nموجودی:\n{names}")

    # اسم تو دستور نیومده، اول اسمش پرسیده میشه و بعد فاکتور میاد
    if not custom_name:
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            ok, alert = await dog_svc.hold_dog(s, user, key, chat_id_of(update))
            await s.commit()
        if not ok:
            return await respond(update, alert)
        return await respond(update, dogs_h.dog_name_question_text(dog))

    text = (
        f"<b>🐕 خرید {esc(dog['breed'])}</b>\n\n"
        f"🐾 نژاد {esc(dog['breed'])}\n"
        f"📛 اسم {esc(custom_name)}\n"
        f"💸 قیمت {money(dog['price'])}\n\n"
        "معامله‌ست؟"
    )
    await respond(update, text, kb.tx_confirm_kb("dog", key, update.effective_user.id, custom_name))


async def buy_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = _match_arg(update)

    # سگ فقط با فرمت «خرید سگ ...»
    if normalize_fa(query).startswith("سگ"):
        return await buy_dog_text(update, context)

    # «خرید ماری جوانا 4»، عدد آخرش تعداد بذره (درخواست کارفرما، فقط بذر تعدادی خریده میشه)
    qty = 1
    m_qty = re.search(r"\s+([\d۰-۹]+)$", query.strip())
    if m_qty:
        _q = parse_amount(m_qty.group(1))
        if _q is not None and _q >= 1:
            probe = shop_svc.find_shop_item(query.strip()[:m_qty.start()].strip())
            if probe[1] and probe[0] == "seed":
                kind, key, item = probe
                qty = _q
                # راند ۲۹: خرید بذر چندتایی با دستور اول فاکتور و تاییدیه میاد (درخواست کارفرما)
                async with session_scope() as s:
                    user, _ = await users.get_or_create(s, update.effective_user)
                    unit = shop_svc.seed_unit_price(user, key)
                    cash = user.cash or 0
                    await s.commit()
                total = unit * qty
                text = (
                    f"<b>🧾 فاکتور خرید {item.get('emoji', '🌱')} {esc(item['name'])}</b>\n\n"
                    f"🔢 تعداد: {fa_num(qty)} بذر\n"
                    f"💸 قیمت هر بذر: {money(unit)}\n"
                    f"💰 جمع فاکتور: {money(total)}\n"
                    f"💵 نقدینگیت: {money(cash)}\n\n"
                    "معامله‌ست؟"
                )
                return await respond(update, text, kb.buyseed_confirm_kb(key, qty, update.effective_user.id))

    kind, key, item = shop_svc.find_shop_item(query)
    if not key:
        return await respond(update, "🤷 جنسی با این اسم پیدا نشد")

    emoji = shop_svc.KIND_EMOJI.get(kind, "🛒")
    extra = ""
    if kind == "weap":
        extra = f"📈 قدرت حمله +{fa_num(item['attack'])}\n"
    elif kind == "arm":
        extra = f"📈 دفاع +{fa_num(item['defense'])}\n"
        if item.get("legendary"):
            extra += f"👑 <i>{esc(item['desc'])}</i>\n"
    elif kind == "seed":
        extra = f"⏱ رشد {fa_num(item['grow_min'])} دقیقه\n💰 فروش {money(item['sell'])}\n"

    text = (
        f"<b>🧾 فاکتور خرید</b>\n\n"
        f"{emoji} {esc(item['name'])}\n"
        f"{extra}"
        f"💸 قیمت {money(item['price'])}\n\n"
        "معامله‌ست؟"
    )
    await respond(update, text, kb.tx_confirm_kb(kind, key, update.effective_user.id))


async def tx_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """اجرای تایید خرید دستور متنی، فقط خودِ صاحب دستور می‌تونه بزنه"""
    p = parts(update)
    kind, key, owner_id = p[1], p[2], p[3]
    dog_name = p[4] if len(p) > 4 else None  # اسم دلخواه سگ

    if update.effective_user.id != int(owner_id):
        await update.callback_query.answer()  # غریبه هیچ واکنشی نمی‌بینه
        return

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        _, alert = await shop_svc.purchase(s, user, kind, key, dog_name=dog_name)
        cash = user.cash
        from services import onboarding as onb
        chain = await onb.first_weapon(s, user, kind)  # راهنمای نبرد بعد خرید اولین سلاح
        congrats = await onb.maybe_congrats(s, user)  # تبریک پایان مأموریت، فقط یه بار
        await s.commit()

    text = f"<b>{esc(alert)}</b>\n\n💵 نقدینگی: {money(cash)}"
    if chain:
        text += f"\n\n{chain}"
    if congrats:
        text += f"\n\n{congrats}"
    await respond(update, text, kb.home_kb())


# ───────── کاشت متنی ─────────

async def plant_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = _match_arg(update)
    # راند ۲۰: «کاشت کوکائین 3» یعنی سه‌تا بذر سه‌تا زمین (درخواست کارفرما)
    count = 1
    m_cnt = re.match(r"^(.*?)\s+(\d+)$", query.strip())
    name_q = query
    if m_cnt:
        name_q, count = m_cnt.group(1), int(m_cnt.group(2))
    key, seed = find_by_name(config.SEEDS, name_q.strip())
    if not key:
        names = " | ".join(s["name"] for s in config.SEEDS.values())
        return await respond(update, f"🤷 محصولی با این اسم ندارم\n\nگزینه‌ها:\n{names}")

    dq_done, dq_left, uname = [], 0, ""
    chain = None
    congrats = None
    tq = None
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)

        plots = await farming.get_user_plots(s, user.id)
        empties = [p for p in plots if p.current_status()[0] == "empty"]
        empty = empties[0] if empties else None
        building = next((p for p in plots if p.current_status()[0] == "building"), None)

        if count > 1:
            stock = await farming.get_stock(s, user.id)
            have = stock.get(key, 0)
            planted20 = 0
            if not plots:
                msg = "🌱 زمینی نداری، اول از مزرعه زمین بخر"
            elif len(empties) < count:
                msg = (f"🌱 زمین کافی برای اینهمه بذر نداری\n"
                       f"{fa_num(count)} تا می‌خوای بکاری ولی فقط {fa_num(len(empties))} تا زمین خالیه")
            elif have < count:
                msg = (f"🌾 بذر کافی نداری\n"
                       f"الان {fa_num(have)} تا {seed['name']} داری ولی {fa_num(count)} تا می‌خوای بکاری")
            else:
                for plot20 in empties[:count]:
                    ok, msg = await farming.plant(s, user, plot20, key)
                    if not ok:
                        break
                    planted20 += 1
                    from services import quests as dq_svc
                    d20, l20 = await dq_svc.track(s, user, "plant")
                    dq_done += d20
                    dq_left = max(dq_left, l20)
                    uname = users.display_name(user)
                    if chain is None:
                        from services import onboarding as onb
                        chain = await onb.first_plant(s, user)
                        congrats = await onb.maybe_congrats(s, user)
                    from services import teams as team_svc
                    tq_one20 = await team_svc.record_plant(s, user)
                    if tq_one20 and tq_one20 != tq:
                        tq = (tq + "\n" + tq_one20) if tq else tq_one20
                if planted20:
                    msg = f"🌱 {seed['name']} ×{fa_num(planted20)} کاشته شد، همه شروع کردن رشد کردن 🌾"
        elif not plots:
            msg = "🌱 زمینی نداری، اول از مزرعه زمین بخر"
        elif empty is None:
            if building is not None:
                _, left = building.current_status()
                msg = f"🔨 زمین جدیدت داره ساخته میشه، {fa_dur(left)} دیگه می‌تونی بکاری"
            else:
                msg = "🌱 همه زمین‌هات پره صبر کن یدونه آماده بشه"
        else:
            ok, msg = await farming.plant(s, user, empty, key)
            if ok:
                from services import quests as dq_svc
                dq_done, dq_left = await dq_svc.track(s, user, "plant")
                uname = users.display_name(user)
                from services import onboarding as onb
                chain = await onb.first_plant(s, user)  # جایزه و راهنمای اولین کاشت
                congrats = await onb.maybe_congrats(s, user)  # تبریک پایان مأموریت، فقط یه بار
                from services import teams as team_svc
                tq = await team_svc.record_plant(s, user)  # کوئست کارتلی کاشت
        await s.commit()

    await respond(update, f"<b>🌱 کاشت</b>\n\n{esc(msg)}", kb.home_kb())
    from handlers.common import announce_notes
    await announce_notes(update, [x for x in (chain, congrats, tq) if x])
    from handlers import dquests
    await dquests.announce_completed(update, uname, dq_done, dq_left)


# ───────── برداشت متنی ─────────

async def harvest_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dq_done, dq_left, uname = [], 0, ""
    notes: list[str] = []
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg, extra, dq, notes = await farming.harvest_all(s, user)
        if ok:
            dq_done, dq_left = dq
            uname = users.display_name(user)
            from services import onboarding as onb
            chain = await onb.first_harvest(s, user)  # جایزه و راهنمای اولین برداشت
            if chain:
                notes.insert(0, chain)
            congrats = await onb.maybe_congrats(s, user)  # تبریک پایان مأموریت، فقط یه بار
            if congrats:
                notes.append(congrats)
        await s.commit()

    if not ok:
        return await respond(update, f"<b>📦 برداشت</b>\n\n{esc(msg)}", kb.home_kb())

    text = "<b>📦 برداشت</b>\n\n" + esc(extra or msg)
    await respond(update, text, kb.home_kb())
    # لول‌آپ و زنجیره آنبوردینگ به‌صورت پیام جدا میان تا متن برداشت شلوغ نشه
    from handlers.common import announce_notes
    await announce_notes(update, notes)
    from handlers import dquests
    await dquests.announce_completed(update, uname, dq_done, dq_left)


# ───────── حمله با ریپلای، به نبرد HP گروهی منتقل شد (handlers/battle.py) ─────────


async def tx_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لغو فاکتور/تایید متنی، فقط صاحبش"""
    _, owner_tg = parts(update)

    if update.effective_user.id != int(owner_tg):
        await update.callback_query.answer()  # غریبه هیچ واکنشی نمی‌بینه
        return
    await respond(update, "<b>😅 بی‌خیال شدیم</b>")
