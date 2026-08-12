"""مزرعه: خرید زمین | کاشت بذر | برداشت هر ۲ دقیقه | آپگرید"""

from telegram import Update
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import parts, respond
from keyboards import keyboards as kb
from services import economy, farming, users
from utils import esc, fa_dur, fa_num, money, now_utc


# ───────── نمایش مزرعه ─────────

async def render_farm(update: Update, extra: str | None = None, alert: str | None = None) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.apply_energy_regen(user)

        plots = await farming.get_user_plots(s, user.id)
        ready_count = 0
        lines: list[str] = []

        for i, p in enumerate(plots, 1):
            state, left = p.current_status()
            seed_name = config.SEEDS.get(p.crop or "", {}).get("name", "؟")
            head = f"زمین {fa_num(i)} (لول {fa_num(p.level)})"
            if state == "building":
                lines.append(f"🔨 {head} | داره ساخته میشه، {fa_dur(left)} مونده")
            elif state == "empty":
                lines.append(f"▫️ {head} خالیه")
            elif state == "growing":
                lines.append(f"🌱 {head} | {esc(seed_name)} | {fa_dur(left)} مونده")
            else:
                ready_count += 1
                lines.append(f"✅ {head} | {esc(seed_name)} آماده برداشته")

        if not plots:
            lines.append("هنوز زمینی نداری")

        text = "<b>🌱 مزرعه من</b>\n\n" + "\n".join(lines)
        text += f"\n\n💵 نقدینگی: {money(user.cash)}"

        cd_left = farming.harvest_cooldown_left(user)
        if cd_left:
            text += f"\n⏳ برداشت بعدی {fa_dur(cd_left)} دیگه"
        elif ready_count:
            text += f"\n📦 {fa_num(ready_count)} تا آماده برداشته"

        from services import smuggle as smg
        p_n = await smg.products_count(s, user.id)
        if p_n:
            text += f"\n🎒 {fa_num(p_n)} محصول تو انبارته، از 🎒 انبار بخش 📦 ارسال محموله بفرستشون"

        next_price = economy.plot_price(len(plots))
        markup = kb.farm_kb(user, plots, next_price, ready_count)
        await s.commit()

    await respond(update, text, markup, alert=alert)


async def farm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_farm(update)


# ───────── خرید زمین ─────────

async def buy_plot_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        count = await farming.plots_count(s, user.id)
        price = economy.plot_price(count)
        gem_price = farming.plot_gem_price(count)
        req_level = economy.plot_required_level(count)
        cash = user.cash
        gems = user.gems or 0
        level = user.level
        await s.commit()

    if count >= config.MAX_PLOTS:
        return await render_farm(update, alert=f"🏡 به سقف {fa_num(config.MAX_PLOTS)} زمین رسیدی")
    if level < req_level:
        return await render_farm(update, alert=f"🔒 زمین شماره {fa_num(count + 1)} لول {fa_num(req_level)} می‌خواد")

    build = economy.plot_build_seconds(count)
    if gem_price > 0:
        text = (
            f"<b>🛒 خرید زمین شماره {fa_num(count + 1)}</b>\n\n"
            f"قیمتش 💎 {fa_num(gem_price)} جمه\n"
            f"الان 💎 {fa_num(gems)} جم داری\n"
            + (f"🔨 بعد خرید {fa_dur(build)} طول می‌کشه ساخته بشه\n" if build else "")
            + "\nمی‌خری؟"
        )
    else:
        text = (
            f"<b>🛒 خرید زمین شماره {fa_num(count + 1)}</b>\n\n"
            f"قیمتش {money(price)}\n"
            f"الان {money(cash)} داری\n"
            + (f"🔨 بعد خرید {fa_dur(build)} طول می‌کشه ساخته بشه\n" if build else "")
            + "\nمی‌خری؟"
        )
    await respond(update, text, kb.confirm_kb("cf:farm:buy"))


async def buy_plot_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«تریاکی ساخت زمین» و «تریاکی خرید زمین» (راند ۳۵، درخواست کارفرما): همون کارت تایید خرید زمین با متن"""
    await buy_plot_confirm(update, context)


async def buy_plot_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    notes = []
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, alert = await farming.buy_plot(s, user)
        if ok:
            from services import onboarding as onb
            notes = [x for x in (await onb.first_plot(s, user), await onb.maybe_congrats(s, user)) if x]
        await s.commit()
    await render_farm(update, alert=alert)
    from handlers.common import announce_notes
    await announce_notes(update, notes)


# ───────── 💎 تسریع ساخت زمین (راند ۲۷) ─────────

async def speed_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """منوی تسریع ساخت زمین با جم: دقیقه | ۱ ساعت | کامل (نرخ جم رو GEM_PLOT_SPEED_MINUTES تنظیم می‌کنه)"""
    plot_id = int(parts(update)[2])
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        plot = await farming.get_plot(s, user.id, plot_id)
        gems = user.gems or 0
        left = 0
        if plot is not None and plot.built_at:
            left = max(0, int((plot.built_at - now_utc()).total_seconds()))
        await s.commit()
    if plot is None or not plot.built_at or left <= 0:
        return await render_farm(update, alert="🤷 این زمین تو کار ساخت نیس")
    spm = config.GEM_PLOT_SPEED_MINUTES
    hour_gems = max(1, 60 // spm)
    alert = (f"<b>💎 تسریع ساخت زمین</b>\n\n"
             f"⏳ {fa_dur(left)} مونده | 💎 {fa_num(gems)} جم داری\n"
             f"هر جم {fa_num(spm)} دقیقه جلو میندازه")
    await respond(update, alert, kb.plot_speed_kb(plot_id, hour_gems, spm))


async def speed_apply_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """اعمال تسریع: farm:spddo:<plot_id>:<gems> (جم صفر یعنی هرچی لازمه تا تموم بشه)"""
    pz = parts(update)
    plot_id, gems = int(pz[2]), int(pz[3])
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, alert = await farming.speedup_plot(s, user, plot_id, gems)
        await s.commit()
    await render_farm(update, alert=alert)


# ───────── کاشت ─────────

def _picker_text(stock: dict[str, int]) -> str:
    if any(v > 0 for v in stock.values()):
        return (
            "<b>🌱 چی بکاریم؟</b>\n\n"
            "بذرهات | ⏱ زمان رشد | 💰 درآمد برداشت\n\n"
            "یکی رو انتخاب کن"
        )
    return (
        "<b>🌾 انبار بذرت خالیه</b>\n\n"
        "از بخش 🌱 بذرهای شاپ بذر بخر\n"
        "یا تو گروه بنویس «تریاکی خرید ماری جوانا»"
    )


async def plant_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    plot_id = int(parts(update)[2])
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        plot = await farming.get_plot(s, user.id, plot_id)

        if not plot or plot.current_status()[0] != "empty":
            await s.commit()
            return await render_farm(update, alert="❌ این زمین الان خالی نیس")

        stock = await farming.get_stock(s, user.id)
        # تایم هر بذر دقیقاً همون تابع اجراست (آب‌وهوا + مهارت + لول تازه زمین) که عدد صفحه با واقعیت یکی بشه
        grow_times = {
            k: await farming.grow_seconds(s, user, plot, k)
            for k in stock if k in config.SEEDS and stock[k] > 0
        }
        markup = kb.seeds_kb(user, plot, stock, grow_times)
        text = _picker_text(stock)
        await s.commit()

    await respond(update, text, markup)


async def plant_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, plot_id, seed_key = parts(update)
    seed = config.SEEDS.get(seed_key)
    if not seed:
        return await render_farm(update, alert="❌ همچین بذری نیس")

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        plot = await farming.get_plot(s, user.id, int(plot_id))

        if not plot or plot.current_status()[0] != "empty":
            await s.commit()
            return await render_farm(update, alert="❌ این زمین الان خالی نیس")

        stock = await farming.get_stock(s, user.id)
        have = stock.get(seed_key, 0)
        yield_ = economy.crop_yield(seed_key, plot.level, user.level)
        grow = await farming.grow_seconds(s, user, plot, seed_key)  # زمان واقعی با آب‌وهوا و مهارت، مثل اجرا
        text = (
            f"<b>🌱 کاشت {esc(seed['name'])}</b>\n\n"
            f"🌾 {fa_num(have)} بذر داری و یدونه مصرف میشه\n"
            f"⏱ {fa_dur(grow)} دیگه آمادست\n"
            f"💰 برداشتش حدود {money(yield_)} میشه\n\n"
            "شروع کنیم؟"
        )
        markup = kb.confirm_kb(f"cf:plant:{plot.id}:{seed_key}")
        await s.commit()

    await respond(update, text, markup)


async def plant_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, plot_id, seed_key = parts(update)
    dq_done, dq_left, uname = [], 0, ""
    chain = None
    congrats = None
    tq = None
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        plot = await farming.get_plot(s, user.id, int(plot_id))
        if not plot:
            alert = "❌ همچین زمینی نداری"
        else:
            ok, alert = await farming.plant(s, user, plot, seed_key)
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
    await render_farm(update, alert=alert)
    from handlers.common import announce_notes
    await announce_notes(update, [x for x in (chain, congrats, tq) if x])
    from handlers import dquests
    await dquests.announce_completed(update, uname, dq_done, dq_left)


# ───────── دکمه 🔄 آپدیت، کولدان خیلی ریز برای جلوی اسپم ─────────

async def farm_refresh_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """فقط کلیک اول تو پنجره FARM_UPDATE_SECONDS اجرا میشه، بقیه پیام «آروم‌تر» می‌گیرن"""
    from handlers.common import throttle

    left = throttle("farm_rf", update.effective_user.id, config.FARM_UPDATE_SECONDS)
    if left:
        try:
            await update.callback_query.answer(
                f"⏳ یخورده آروم‌تر، {fa_num(int(left) + 1)} ثانیه دیگه بزن", show_alert=True
            )
        except Exception:
            pass
        return
    await render_farm(update)


# ───────── برداشت (همه آماده‌ها، کولدان ۲ دقیقه) ─────────

async def harvest_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dq_done, dq_left, uname = [], 0, ""
    notes: list[str] = []
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, alert, extra, dq, notes = await farming.harvest_all(s, user)
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
    await render_farm(update, extra=extra, alert=alert)
    # لول‌آپ به‌صورت پیام جدا میاد
    from handlers.common import announce_notes
    await announce_notes(update, notes)
    from handlers import dquests
    await dquests.announce_completed(update, uname, dq_done, dq_left)


# ───────── آپگرید ─────────

async def upgrade_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    plot_id = int(parts(update)[2])
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        plot = await farming.get_plot(s, user.id, plot_id)

        if not plot:
            await s.commit()
            return await render_farm(update, alert="❌ همچین زمینی نداری")
        if plot.level >= config.PLOT_MAX_LEVEL:
            await s.commit()
            return await render_farm(update, alert="⭐ این زمین مکس لوله")

        req_level = economy.plot_upgrade_required_level(plot.level)
        if user.level < req_level:
            await s.commit()
            return await render_farm(
                update,
                alert=f"🔒 آپگرید به لول {fa_num(plot.level + 1)} لول {fa_num(req_level)} می‌خواد",
            )

        plots = await farming.get_user_plots(s, user.id)
        plot_index = next((i for i, p in enumerate(plots, 1) if p.id == plot.id), 1)
        price = economy.upgrade_price(plot.level)
        wood = economy.upgrade_wood(plot.level)
        old_sp = economy.plot_speed_mult(plot.level)
        new_sp = economy.plot_speed_mult(plot.level + 1)
        text = (
            f"<b>⬆️ لول‌آپ زمین شماره {fa_num(plot_index)}</b>\n\n"
            f"از لول {fa_num(plot.level)} به {fa_num(plot.level + 1)}\n\n"
            f"💸 هزینه: {money(price)} + 🪵 {fa_num(wood)} چوب\n"
            f"⚡ سرعت رشد 40% بیشتر میشه (×{old_sp:.1f} ← ×{new_sp:.1f})\n"
            "با لول آپ کردن زمین شانس دریافت تعداد بیشتری بذر رو از محصولات داری\n\n"
            "انجامش بدیم؟"
        )
        markup = kb.confirm_kb(f"cf:farm:up:{plot.id}")
        await s.commit()

    await respond(update, text, markup)


async def upgrade_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    plot_id = int(parts(update)[3])
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        plot = await farming.get_plot(s, user.id, plot_id)
        if not plot:
            alert = "❌ همچین زمینی نداری"
        else:
            _, alert = await farming.upgrade_plot(s, user, plot)
        await s.commit()
    await render_farm(update, alert=alert)
