"""منطق مزرعه: خرید زمین | کاشت با بذر | برداشت با کولدان | آپگرید"""

import random
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import Plot, SeedStock, User
from services import economy, users
from utils import fa_dur, fa_num, money, money_tp, now_utc


# ───────── ابزار ─────────

async def get_user_plots(session: AsyncSession, user_id: int) -> list[Plot]:
    q = select(Plot).where(Plot.user_id == user_id).order_by(Plot.id)
    return list((await session.execute(q)).scalars())


async def get_plot(session: AsyncSession, user_id: int, plot_id: int) -> Plot | None:
    q = select(Plot).where(Plot.id == plot_id, Plot.user_id == user_id)
    return (await session.execute(q)).scalar_one_or_none()


async def plots_count(session: AsyncSession, user_id: int) -> int:
    q = select(func.count(Plot.id)).where(Plot.user_id == user_id)
    return (await session.execute(q)).scalar_one()


async def get_stock(session: AsyncSession, user_id: int) -> dict[str, int]:
    """انبار بذر کاربر به شکل دیکشنری: seed_key → تعداد"""
    q = select(SeedStock).where(SeedStock.user_id == user_id)
    return {row.seed_key: row.count for row in (await session.execute(q)).scalars()}


async def add_seed_stock(session: AsyncSession, user_id: int, seed_key: str, amount: int = 1) -> None:
    q = select(SeedStock).where(SeedStock.user_id == user_id, SeedStock.seed_key == seed_key)
    row = (await session.execute(q)).scalar_one_or_none()
    if row:
        row.count += amount
    else:
        session.add(SeedStock(user_id=user_id, seed_key=seed_key, count=amount))


def seed_room(user: User, stock: dict[str, int], seed_key: str) -> int:
    """جای خالی انبار برای یه بذر خاص (ظرفیت هر بذر با لول پناهگاه بیشتر میشه)"""
    cap = config.SHELTER_SEED_CAP_BASE + config.SHELTER_SEED_CAP_PER_LEVEL * user.shelter_level
    return max(0, cap - stock.get(seed_key, 0))


async def try_add_seed(session: AsyncSession, user: User, seed_key: str, amount: int = 1) -> int:
    """
    تا جایی که انبار جا داره بذر اضافه می‌کنه و تعداد واقعی اضافه‌شده رو برمی‌گردونه
    درخواست کارفرما راند ۹: جستجو/کاروان/کوئست نباید از ظرفیت انبار رد بشن
    """
    stock = await get_stock(session, user.id)
    take = min(amount, seed_room(user, stock, seed_key))
    if take > 0:
        await add_seed_stock(session, user.id, seed_key, take)
    return take


# ───────── خرید زمین (قیمت/زمان ساخت متفاوت برای هرکی + گیت لول) ─────────

def plot_gem_price(count: int) -> int:
    """قیمت جمی زمین شماره count+1 (صفر یعنی با تی‌پوینته)؛ فعلاً فقط زمین پنجم با جم فروخته میشه"""
    spec = config.PLOT_CATALOG.get(count + 1, {})
    return int(spec.get("gem_price", 0) or 0)


async def buy_plot(session: AsyncSession, user: User) -> tuple[bool, str]:
    count = await plots_count(session, user.id)
    if count >= config.MAX_PLOTS:
        return False, f"🏡 به سقف {fa_num(config.MAX_PLOTS)} زمین رسیدی"

    n = count + 1
    req_level = economy.plot_required_level(count)
    if user.level < req_level:
        return False, f"🔒 زمین شماره {fa_num(n)} لول {fa_num(req_level)} می‌خواد"

    build_sec = economy.plot_build_seconds(count)
    gem_price = plot_gem_price(count)
    if gem_price > 0:
        if (user.gems or 0) < gem_price:
            return False, f"❌ زمین شماره {fa_num(n)} با 💎 جم فروخته میشه؛ {fa_num(gem_price)} جم می‌خواد و تو {fa_num(user.gems or 0)} داری"
        user.gems -= gem_price
    else:
        price = economy.plot_price(count)
        if user.cash < price:
            return False, "❌ تی‌پوینتت کافی نیس"
        user.cash -= price

    built_at = None if build_sec <= 0 else now_utc() + timedelta(seconds=build_sec)
    session.add(Plot(user_id=user.id, built_at=built_at))

    if build_sec > 0:
        return True, f"🔨 زمین شماره {fa_num(n)} رفت تو کار ساخت، {fa_dur(build_sec)} دیگه تحویلت میشه"
    return True, f"🎉 زمین شماره {fa_num(n)} مالت شد"


async def speedup_plot(session: AsyncSession, user: User, plot_id: int, gems: int) -> tuple[bool, str]:
    """💎 تسریع ساخت زمین (راند ۲۷): هر جم GEM_PLOT_SPEED_MINUTES دقیقه جلو میندازه؛ gems=0 یعنی هرچی لازمه تا تموم بشه"""
    plot = await get_plot(session, user.id, plot_id)
    if plot is None or not plot.built_at:
        return False, "🤷 این زمین تو کار ساخت نیس"
    now = now_utc()
    left = int((plot.built_at - now).total_seconds())
    if left <= 0:
        return False, "✅ ساخت زمینت تموم شده، نیازی به تسریع نیس"
    step = config.GEM_PLOT_SPEED_MINUTES * 60
    need = max(1, -(-left // step))  # سقف تقسیم
    use = need if gems <= 0 else min(gems, need)
    if use < 1:
        return False, "🤷 انتخاب نامعتبره"
    if (user.gems or 0) < use:
        return False, f"💎 جم کم داری؛ {fa_num(use)} جم لازمه و تو {fa_num(user.gems or 0)} داری"
    user.gems -= use
    plot.built_at -= timedelta(seconds=use * step)
    if plot.built_at <= now:
        return True, f"🎉 با 💎 {fa_num(use)} جم ساخت زمینت همین الان تموم شد"
    left2 = int((plot.built_at - now).total_seconds())
    return True, f"⚡ با 💎 {fa_num(use)} جم {fa_dur(use * step)} جلو افتادی، {fa_dur(left2)} مونده"


# ───────── کاشت (مصرف بذر) ─────────

async def grow_seconds(session: AsyncSession, user: User, plot: Plot, seed_key: str) -> int:
    """
    زمان واقعی کاشت با همه ضریب‌ها (آب‌وهوا + مهارت سرعت)، دقیقاً همونی که plant ست می‌کنه
    صفحه تایید کاشت و خود اجرا از همین استفاده می‌کنن که زمان نمایش‌داده‌شده همیشه درست باشه
    """
    from services import world as world_svc
    from services import combat as combat_svc
    wkey, wpct, _ = await world_svc.weather_state(session)
    speed = world_svc.weather_grow_speed(wkey, wpct)
    speed *= 1 + combat_svc.skill_pct(user, "speed")  # مهارت ⚡ سرعت: هر لول ۲% کاشت تندتر
    return max(30, int(economy.crop_grow_seconds(seed_key, plot.level) / speed))


async def plant(session: AsyncSession, user: User, plot: Plot, seed_key: str) -> tuple[bool, str]:
    seed = config.SEEDS.get(seed_key)
    if not seed:
        return False, "❌ همچین بذری نیس"
    if plot.user_id != user.id:
        return False, "❌ این زمین مال تو نیس"
    state, left = plot.current_status()
    if state == "building":
        return False, f"🔨 زمینت هنوز داره ساخته میشه، {fa_dur(left)} مونده"
    if state != "empty":
        return False, "❌ این زمین الان خالی نیس"
    # کاشت هیچ گیت لولی نداره، هر بذری تو هر لولی کاشته میشه (قفل لول فقط روی خرید بذر از شاپه)
    stock = await get_stock(session, user.id)
    if stock.get(seed_key, 0) <= 0:
        return False, f"🌾 بذر {seed['name']} نداری، از بخش بذرهای شاپ بخرش"

    await add_seed_stock(session, user.id, seed_key, -1)
    from services import tracklog as tl
    await tl.bump_plant(session, user.id, seed_key)  # لاگ ردیابی ادمین

    seconds = await grow_seconds(session, user, plot, seed_key)
    plot.status = "growing"
    plot.crop = seed_key
    plot.planted_at = now_utc()
    plot.ready_at = now_utc() + timedelta(seconds=seconds)
    return True, f"🌱 {seed['name']} کاشته شد | {fa_dur(seconds)} دیگه آمادست"


# ───────── برداشت (همه آماده‌ها، هر ۲ دقیقه یه بار) ─────────

def apply_legendary_cap(seed_key: str, gain: int) -> int:
    """سقف فروش بذرهای افسانه‌ای بعد از همه ضریب‌ها روی کل سود هر برداشت، درخواست کارفرما: عادی‌ها بالای ۶۰,۰۰۰ نرن، جهش‌یافته سقف خودشو داره"""
    if not config.SEEDS[seed_key].get("legendary"):
        return gain
    cap = config.SEEDS[seed_key].get("cap", config.LEGENDARY_SELL_CAP)
    return min(gain, cap)

def harvest_cooldown_left(user: User) -> int:
    """ثانیه مونده از کولدان برداشت، زمان‌بندی برای هر کاربر جدا ذخیره میشه"""
    if not user.last_harvest_at:
        return 0
    left = config.HARVEST_COOLDOWN_SECONDS - (now_utc() - user.last_harvest_at).total_seconds()
    return max(0, int(left))


def harvest_qty_roll(plot_level: int, seed_key: str) -> int:
    """تعداد برداشت شانسی از جدول لول زمین (درخواست کارفرما): افسانه‌ای‌ها همیشه 1 تا، بقیه طبق شانس‌های لول زمین"""
    sd = config.SEEDS.get(seed_key) or {}
    if sd.get("legendary"):
        return 1
    table = config.HARVEST_QTY_CHANCES[min(max(plot_level, 1), config.PLOT_MAX_LEVEL)]
    r = random.random() * 100
    acc = 0.0
    for qty, pct in table:
        acc += pct
        if r < acc:
            return qty
    return table[-1][0]


async def harvest_all(session: AsyncSession, user: User) -> tuple[bool, str, str | None, tuple]:
    """
    برداشت همه زمین‌های آماده
    محصول پول نمیشه و میره تو انبار محصول، نقد کردن با محموله یا کاروان قاچاقه (services/smuggle)
    خروجی: (موفق, پیام کوتاه برای alert, متن اضافه برای نمایش توی مزرعه,
            جفت (کوئست‌های روزانه تکمیل‌شده, تعداد مونده), یادداشت‌های لول‌آپ)
    """
    left = harvest_cooldown_left(user)
    if left:
        return False, f"⏳ هر 2 دقیقه یه بار میشه برداشت کرد، {fa_dur(left)} مونده", None, ([], 0), []

    plots = await get_user_plots(session, user.id)
    ready = [p for p in plots if p.current_status()[0] == "ready"]
    if not ready:
        return False, "▫️ چیزی آماده برداشت نیس", None, ([], 0), []

    # افکت‌های جهان: رول تعداد برداشت + آب و هوا 🌦 + بازار سیاه 📈، شدت هوا همین رول
    from services import world as world_svc
    wkey, wpct, _ = await world_svc.weather_state(session)
    sell_mult = world_svc.weather_sell_mult(wkey, wpct)
    mults, _ = await world_svc.market_mults(session)

    total_gain = 0
    total_xp = 0
    total_units = 0
    n_harvests = 0
    harv_seeds: dict[str, int] = {}  # لاگ ردیابی ادمین: هر بذر چندتا برداشت شد
    item_lines: list[str] = []
    lost_lines: list[str] = []
    from services import smuggle as smg
    for p in ready:
        if p.crop not in config.SEEDS:
            # بذر قدیمی (از کاتالوگ حذف شده)، زمین خالی میشه بدون درآمد
            p.status = "empty"
            p.crop = None
            p.planted_at = None
            p.ready_at = None
            continue
        tier = world_svc.roll_quality(economy.plot_quality_bonus(p.level))
        # درخواست کارفرما: تعداد شانسی از جدول لول زمین، افسانه‌ای‌ها همیشه 1 تا | رول داخلی فقط تجربه رو تعیین می‌کنه
        qty = harvest_qty_roll(p.level, p.crop)
        base = economy.crop_yield(p.crop, p.level, user.level)
        mkt = world_svc.market_mult(mults, p.crop)
        gain = apply_legendary_cap(p.crop, int(base * sell_mult * mkt) * qty)
        # محصول بعد برداشت نقد نمیشه، تعدادی و با ارزش قفل‌شده همون لحظه میره تو انبار
        # فروش (محموله یا کاروان قاچاق) بعداً انجام میشه و عرضه بازار موقع فروش ثبت میشه
        # هر محصول ظرفیت انبار خودشو داره، سرریز از بین میره و به کاربر گزارش میشه
        added, added_val = await smg.add_product(session, user.id, p.crop, qty, gain, user.shelter_level)
        sd = config.SEEDS[p.crop]
        emoji = sd.get("emoji", "🌱")
        # راند ۴۰ (درخواست کارفرما): انبار پر بود و هیچی جا نشد → زمین برداشت نمیشه، سرجاش می‌مونه
        # تا وقتی جا باز بشه (دیگه برداشت خودکار پاک نمیشه که محصول الکی از بین نره)
        if added == 0 and qty > 0:
            lost_lines.append(f"⚠️ انبار {sd['name']} پره، این زمین برداشت نشد؛ اول انبارتو خالی کن")
            continue
        total_xp += economy.crop_xp(p.crop, tier["stars"])
        n_harvests += 1
        harv_seeds[p.crop] = harv_seeds.get(p.crop, 0) + qty
        total_gain += added_val
        total_units += added
        if added:
            item_lines.append(f"▫️ {emoji} {sd['name']} ×{fa_num(added)}")
        if added < qty:
            lost_lines.append(f"⚠️ انبار {sd['name']} پر بود، {fa_num(qty - added)} تا از بین رفت")
        p.status = "empty"
        p.crop = None
        p.planted_at = None
        p.ready_at = None

    if n_harvests == 0 and not item_lines and not lost_lines:
        return False, "▫️ چیزی آماده برداشت نیس", None, ([], 0), []

    user.last_harvest_at = now_utc()
    notes = users.add_xp(user, total_xp)
    from services import tracklog as tl
    await tl.bump_harvest(session, user.id, total_gain, total_xp, n_harvests, harv_seeds)  # لاگ ردیابی ادمین

    # قلاب کوئست کارتل، برداشت هر عضو حساب میشه
    from services import teams as team_svc
    notes += await team_svc.add_team_xp(session, user, total_xp)
    quest_msg = await team_svc.record_harvest(session, user, n_harvests)

    # قلاب کوئست روزانه، به تعداد زمین برداشت‌شده
    from services import quests as dq_svc
    dq = await dq_svc.track(session, user, "harvest", n_harvests)

    extra = "\n".join(item_lines + lost_lines)
    extra += "\n\n📦 محصول رفت تو انبار (🎒 انبار ← 🌾 محصولات)"
    extra += f"\n💰 ارزش برداشت تقریبا {money(total_gain)}، هنوز نقد نشده"
    extra += "\n🚚 برای نقد کردن: بخش «انبار» ارسال محموله یا فروش به کاروان قاچاق"
    if total_xp:
        extra += f"\n✨ {fa_num(total_xp)} تجربه"
    if wkey != "normal" and sell_mult != 1.0:
        w = world_svc.weather_of(wkey)
        extra += f"\n{w['emoji']} افکت {w['name']} روش حساب شد"
    if quest_msg:
        extra += "\n\n" + quest_msg
    # یادداشت‌های لول‌آپ جدا برمی‌گردن تا هندلر به‌صورت پیام مجزا بفرسته
    if total_units == 0:
        return True, "⚠️ انبارت پره، هیچی برداشت نشد", extra, dq, notes
    return True, f"🌾 {fa_num(total_units)} تا محصول برداشت کردی، رفت تو انبارت", extra, dq, notes


# ───────── آپگرید ─────────

async def upgrade_plot(session: AsyncSession, user: User, plot: Plot) -> tuple[bool, str]:
    if plot.user_id != user.id:
        return False, "❌ این زمین مال تو نیس"
    if plot.level >= config.PLOT_MAX_LEVEL:
        return False, "⭐ این زمین مکس لوله"

    req_level = economy.plot_upgrade_required_level(plot.level)
    if user.level < req_level:
        return False, f"🔒 آپگرید به لول {fa_num(plot.level + 1)} لول {fa_num(req_level)} می‌خواد"

    price = economy.upgrade_price(plot.level)
    wood = economy.upgrade_wood(plot.level)
    if user.cash < price:
        return False, "❌ تی‌پوینتت کافی نیس"
    if user.wood < wood:
        return False, f"🪵 {fa_num(wood)} چوب می‌خواد و {fa_num(user.wood)} تا داری"

    user.cash -= price
    user.wood -= wood
    plot.level += 1
    return True, f"⬆️ زمین رفت رو لول {fa_num(plot.level)}"
