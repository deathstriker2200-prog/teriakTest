"""آنبوردینگ تازه‌کارها 🎯

جایزه اولین تجربه‌های کلیدی (کنده‌کاری | کاشت | برداشت) + زنجیره راهنمای قدم‌به‌قدم
کارت مأموریت شروع بالای منو برای لول‌های پایین، کاملاً مستقل از کوئست‌های روزانه‌ست
هدف اینه که تازه‌کار هیچ‌وقت نپرسه الان باید چیکار کنم
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import InventoryItem, Plot, User
from utils import fa_num, now_utc


# ───────── تیکه اول زنجیره 🎉 (جایزه‌های اولین تجربه) ─────────

async def first_mine(session: AsyncSession, user: User) -> str | None:
    """اولین کنده‌کاری موفق، جایزه میده و متن قدم بعدی رو برمی‌گردونه (کامیت با صدا‌کننده‌ست)"""
    if user.first_mine_at is not None:
        return None
    from utils import money
    user.first_mine_at = now_utc()
    user.cash += config.FIRST_MINE_BONUS
    return (
        "<b>🎉 عالی بود، اولین جایزه‌ات رو گرفتی</b>\n\n"
        f"💰 +{money(config.FIRST_MINE_BONUS)} جایزه اولین کنده‌کاری\n\n"
        "🎯 قدم بعد: یه زمین بخر\n"
        "از «🌱 مزرعه من» تو منوی اصلی یا با نوشتن «تریاکی زمین» یه زمین بگیر تا اولین بذرت رو بکاری\n"
        f"💵 نقدینگی: {money(user.cash)}"
    )


async def first_plant(session: AsyncSession, user: User) -> str | None:
    """اولین کاشت موفق، جایزه + راهنمای قدم بعدی (کامیت با صدا‌کننده‌ست)"""
    if user.first_plant_at is not None:
        return None
    from utils import money
    user.first_plant_at = now_utc()
    user.cash += config.FIRST_PLANT_BONUS
    return (
        "<b>🌱 کارت درسته، اولین بذرت کاشته شد</b>\n\n"
        f"💰 +{money(config.FIRST_PLANT_BONUS)} جایزه اولین کاشت\n\n"
        "🎯 قدم بعد: فقط صبر کن محصولت آماده بشه\n"
        "بعد با «تریاکی برداشت» منتقلش کن به انبار و از اونجا با محموله نقدش کن"
    )


async def first_harvest(session: AsyncSession, user: User) -> str | None:
    """
    اولین برداشت موفق، جایزه تی‌پوینت + یه بسته چوب و آهن شروع (کامیت با صدا‌کننده‌ست)
    چوب و آهن اینجا داده میشن تا بازیکن بدون تکیه به دراپ شانسی بتونه اولین سلاحش رو بخره
    """
    if user.first_harvest_at is not None:
        return None
    from utils import money
    user.first_harvest_at = now_utc()
    user.cash += config.FIRST_HARVEST_BONUS
    user.wood = (user.wood or 0) + config.FIRST_HARVEST_WOOD
    user.iron = (user.iron or 0) + config.FIRST_HARVEST_IRON
    return (
        "<b>💰 تبریک، الان وارد اقتصاد بازی شدی</b>\n\n"
        f"💵 +{money(config.FIRST_HARVEST_BONUS)} جایزه اولین برداشت\n"
        f"🪵 +{fa_num(config.FIRST_HARVEST_WOOD)} چوب و ⛏️ +{fa_num(config.FIRST_HARVEST_IRON)} آهن برای شروع\n\n"
        "🎯 قدم بعد: محصولت رو با محموله نقد کن\n"
        "تو 🎒 انبار روی 📦 ارسال محموله بزن، محصول و تعدادش رو انتخاب کن و بفرستش"
    )


async def first_shipment(session: AsyncSession, user: User) -> str | None:
    """اولین ارسال محموله موفق (قدم جدید زنجیره، درخواست کارفرما) | جایزه + راهنمای قدم بعدی (کامیت با صدا‌کننده‌ست)"""
    if user.first_shipment_at is not None:
        return None
    from utils import money
    user.first_shipment_at = now_utc()
    user.cash += config.FIRST_SHIPMENT_BONUS
    return (
        "<b>🚚 تبریک، اولین محموله‌ات راه افتاد</b>\n\n"
        f"💰 +{money(config.FIRST_SHIPMENT_BONUS)} جایزه اولین محموله\n\n"
        "🎯 قدم بعد: اولین سلاحت رو بخر\n"
        "از فروشگاه یه چاقو بگیر تا برای نبرد آماده بشی"
    )


async def first_plot(session: AsyncSession, user: User) -> str | None:
    """اولین خرید زمین موفق، جایزه + راهنمای قدم بعدی (کامیت با صدا‌کننده‌ست)"""
    if user.first_plot_at is not None:
        return None
    from utils import money
    user.first_plot_at = now_utc()
    user.cash += config.FIRST_PLOT_BONUS
    return (
        "<b>🏡 زمینت رو گرفتی، عالیه</b>\n\n"
        f"💰 +{money(config.FIRST_PLOT_BONUS)} جایزه اولین زمین\n\n"
        "🎯 قدم بعد: از «🛒 فروشگاه» یه بذر بخر و تو «🌱 مزرعه من» اولین محصولت رو بکار"
    )


async def first_weapon(session: AsyncSession, user: User, kind: str) -> str | None:
    """
    خرید اولین سلاح (نتیجه موفق purchase صدا زده میشه)
    جایزه نداره، فقط راهنمای قدم آخر زنجیره رو میده
    """
    if kind != "weap":
        return None
    n_weapons = (await session.execute(
        select(func.count(InventoryItem.id)).where(
            InventoryItem.user_id == user.id,
            InventoryItem.item_key.in_(list(config.WEAPONS)),
        )
    )).scalar() or 0
    if n_weapons != 1:  # سلاح اوله (سلاح‌ها فروخته نمیشن، شمارش فقط زیاد میشه)
        return None
    return (
        "<b>🔫 آماده نبردی</b>\n\n"
        "🎯 آخرین قدم: اولین حمله‌ات رو بزن\n"
        "تو گروه ریپلای بزن رو هرکی که می‌خوای و بنویس «حمله»\n"
        "یا تو پی‌وی با «تریاکی حمله» یه هدف پیدا کن و سیستم مبارزه رو تجربه کن"
    )


# ───────── تبریک پایان مأموریت شروع 🎉 ─────────

CONGRATS_TEXT = (
    "<b>🎉 تبریک، آموزش اولیه رو با موفقیت تموم کردی</b>\n\n"
    "حالا با تمام بخش‌های اصلی بازی آشنا شدی؛ وقتشه ربات رو به گروه خودت اضافه کنی "
    "و همراه دوستات رقابت، معامله و مبارزه رو شروع کنی\n"
    "🔥 بازی واقعی تازه از اینجا شروع میشه"
)


async def maybe_congrats(session: AsyncSession, user: User) -> str | None:
    """
    اگه همه مرحله‌های مأموریت شروع تازه‌کارم دیگه تیک خورده باشن و تبریک هنوز گفته نشده
    متن تبریک پایانی رو میده و علامتش رو می‌زنه که فقط یه بار بیاد (کامیت با صدا‌کننده‌ست)
    """
    if user.onb_done_at is not None:
        return None
    rows = await mission_rows(session, user)
    if not all(done for _, _, done in rows):
        return None
    user.onb_done_at = now_utc()
    return CONGRATS_TEXT


# ───────── کارت مأموریت شروع 🎯 ─────────

MISSION_DEFS: tuple[tuple[str, str], ...] = (
    ("mine", "اولین کنده‌کاری"),
    ("plot", "اولین خرید زمین"),
    ("plant", "اولین کاشت"),
    ("harvest", "اولین برداشت"),
    ("shipment", "اولین ارسال محموله"),
    ("weapon", "خرید اولین سلاح"),
    ("attack", "اولین حمله"),
)


async def mission_rows(session: AsyncSession, user: User) -> list[tuple[str, str, bool]]:
    """(کلید، لیبل، انجام‌شده) برای هر مرحله مأموریت شروع، چک‌ها با COUNT مستقیم توی SQL"""
    plots_n = (await session.execute(
        select(func.count(Plot.id)).where(Plot.user_id == user.id)
    )).scalar() or 0
    n_weapons = (await session.execute(
        select(func.count(InventoryItem.id)).where(
            InventoryItem.user_id == user.id,
            InventoryItem.item_key.in_(list(config.WEAPONS)),
        )
    )).scalar() or 0
    dones = {
        # زمین اول دیگه هدیه نیس، خود بازیکن رایگان می‌خره و همین خرید قدم مأموریته
        "mine": user.first_mine_at is not None,
        "plot": plots_n >= 1,
        "plant": user.first_plant_at is not None,
        "harvest": user.first_harvest_at is not None,
        "shipment": user.first_shipment_at is not None,
        "weapon": n_weapons >= 1,
        "attack": user.last_attack_at is not None or user.pv_attack_at is not None,
    }
    return [(key, label, dones[key]) for key, label in MISSION_DEFS]


async def menu_card(session: AsyncSession, user: User) -> str | None:
    """
    کارت مأموریت شروع برای بالای منوی اصلی
    فقط زیر لول راهنما میاد و بعد از کامل شدن همه مرحله‌ها محو میشه
    """
    if user.level >= config.MISSION_GUIDE_MAX_LEVEL:
        return None
    rows = await mission_rows(session, user)
    if all(done for _, _, done in rows):
        return None
    lines = ["🎯 <b>مأموریت فعلی</b>", ""]
    marked_next = False
    for _, label, done in rows:
        if done:
            mark = "✅"
        elif not marked_next:  # اولین مرحله انجام‌نشده، قدم فعلیه
            mark = "🔹"
            marked_next = True
        else:
            mark = "☐"
        lines.append(f"{mark} {label}")
    return "\n".join(lines)
