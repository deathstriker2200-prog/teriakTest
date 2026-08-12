"""سرویس کاربر: ثبت‌نام | انرژی | آیتم | لول‌آپ | مدال‌ها 🎖️"""

from datetime import timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import InventoryItem, Plot, User
from services.economy import xp_need
from utils import esc, fa_num, iran_today, iran_week_key, money, now_utc


async def get_or_create(session: AsyncSession, tg_user) -> tuple[User, bool]:
    """ثبت‌نام خودکار با اولین تعامل، یه زمین رایگان هم بهت میرسه + HP فول"""
    from services import battle as battle_svc

    user = await get_by_tg(session, tg_user.id)
    if user:
        # اسم/یوزرنیم ممکنه عوض شده باشه
        from services import bank as bank_svc
        user.username = tg_user.username
        user.first_name = tg_user.first_name
        user.last_seen_at = now_utc()
        battle_svc.ensure_hp(user)  # کاربرای قدیمی بدون HP
        ensure_skills(user)  # امتیاز مهارت پس‌دررو برای کاربرای قدیمی
        await bank_svc.ensure_bank_acc(session, user)  # کاربرای قدیمی بدون شماره حساب
        return user, False

    user = User(
        telegram_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
    )
    session.add(user)
    await session.flush()  # گرفتن id بدون کامیت
    user.last_seen_at = now_utc()
    # دیگه زمین اول هدیه داده نمیشه، خود بازیکن رایگان می‌خره تا قدم خرید زمین آنبوردینگ رو تجربه کنه
    from services import bank as bank_svc
    battle_svc.ensure_hp(user)  # HP شروع ۲۰۰
    await bank_svc.ensure_bank_acc(session, user)  # شماره حساب بانکی یکتا
    return user, True


async def get_by_tg(session: AsyncSession, telegram_id: int) -> User | None:
    q = select(User).where(User.telegram_id == telegram_id)
    return (await session.execute(q)).scalar_one_or_none()


async def wipe_account(session: AsyncSession, user: User) -> None:
    """
    ریست کامل اکانت به حالت روز اول (برای /clearacc ادمین)
    زمین‌ها، سگ‌ها، آیتم‌ها، بذرها، کارتل و همه آمار پاک میشه و یه زمین رایگان دوباره میدیم
    """
    from sqlalchemy import delete as sql_delete

    from models import Dog, SeedStock, TeamDaily, TeamMember, TeamRequest, Team

    # کارتل: رهبره → انحلال کامل | عضو ساده → حذف عضویت
    from services import teams as team_svc
    m = await team_svc.get_membership(session, user.id)
    if m:
        team = await session.get(Team, m.team_id)
        if m.role == "owner" and team:
            team_svc.TEAM_MINE_SESSIONS.pop(team.id, None)
            await session.execute(sql_delete(TeamRequest).where(TeamRequest.team_id == team.id))
            await session.execute(sql_delete(TeamDaily).where(TeamDaily.team_id == team.id))
            await session.delete(team)  # memberها با cascade پاک میشن
        else:
            await session.delete(m)
        await session.flush()

    for model in (Plot, InventoryItem, Dog, SeedStock):
        await session.execute(sql_delete(model).where(model.user_id == user.id))
    await session.flush()

    # برگشت به حالت روز اول
    user.level, user.xp = 1, 0
    user.cash = config.START_CASH
    user.energy = config.MAX_ENERGY
    user.energy_updated_at = now_utc()
    user.wins = user.losses = 0
    user.last_attack_at = user.last_mine_at = user.last_harvest_at = None
    user.feeds_used_today = 0
    user.feed_day = None
    user.bank_balance = 0
    user.bank_level = 1
    user.shelter_level = 0
    user.wood = user.iron = 0
    user.axe_level = user.pick_level = 1
    user.lumber_level = user.ironmill_level = 0
    user.company_at = None
    user.last_search_at = user.last_casino_at = None
    set_pending(user, None)
    user.shield_until = user.pv_attack_at = None
    user.dead_until = None
    user.dq_date = user.dq_data = None
    # آنبوردینگ هم برمی‌گرده روز اول: جایزه اولین‌ها و کارت مأموریت و تبریک پایانی، همه دوباره فعال میشن
    user.first_mine_at = user.first_plant_at = user.first_harvest_at = None
    user.first_plot_at = None
    user.onb_done_at = None
    user.medals = 0
    user.medals_day = 0
    user.medals_day_date = None
    user.medals_week = 0
    user.medals_week_id = None
    user.skill_points = 0
    for _k in config.SKILLS:
        setattr(user, f"skill_{_k}", 0)
    user.equipped_weapon = user.equipped_armor = None
    user.poison_until = None

    from services import battle as battle_svc
    # بعد ریست هم زمین هدیه نمیشه، مثل ثبت‌نام تازه خودش رایگان می‌خره
    # HP هم باید به مکس روز اول برگرده، ensure_hp فقط وقتی hp برابر None باشه ست می‌کنه و مقدار قدیمی رو نگه می‌داشت
    battle_svc.full_heal(user)


async def search_users(session: AsyncSession, query: str) -> list[User]:
    """
    جستجوی کاربر برای /user ادمین
    آیدی عددی → دقیق | @یوزرنیم → اول مچ دقیق بعد جزئی | بخشی از اسم/یوزرنیم → جزئی
    """
    q = (query or "").strip()
    if not q:
        return []
    if q.lstrip("-").isdigit():
        u = await get_by_tg(session, int(q))
        return [u] if u else []

    norm = q.lstrip("@").lower()
    if not norm:
        return []

    exact = list((await session.execute(
        select(User).where(func.lower(User.username) == norm).limit(1)
    )).scalars())
    if exact:
        return exact

    qy = (
        select(User)
        .where(
            (func.lower(User.username).contains(norm))
            | (func.lower(User.first_name).contains(norm))
        )
        .limit(8)
    )
    return list((await session.execute(qy)).scalars())


def set_pending(user: User, action: str | None, value: str | None = None, chat_id: int | None = None) -> None:
    """اکشن معلق رو با زمان و چت شروع می‌ذاره (action=None یعنی پاک کردن)
    ورودی‌های معلق فقط تو همون چت جواب داده میشن و عددی‌ها ۶۰ ثانیه مهلت دارن"""
    user.pending_action = action
    user.pending_value = value
    user.pending_at = now_utc() if action else None
    user.pending_chat_id = chat_id if action else None


def display_name(user: User) -> str:
    """اسم نمایشی کاربر، ساده‌شده از فونت‌های تزئینی (درخواست کارفرما راند ۲۷)"""
    from utils import plain_name
    return plain_name(user.first_name or user.username or "") or "رفیق"


def title_of(user: User) -> tuple[str, str]:
    """(ایموجی, اسم) لقب کاربر بر اساس لولش، بالاترین ردیافی که لول >= حداقلشه
    لقب موقت «چاپلوس» (لو دادن، راند ۲۲؛ راند ۳۵ رینیم از خایه‌مال) تا وقتی فعاله جای لقب عادی رو می‌گیره"""
    if getattr(user, "khaye_until", None) and user.khaye_until > now_utc():
        return "🐀", "چاپلوس"
    emoji, name = "", ""
    for min_lv, e, n in config.TITLES:
        if (user.level or 1) >= min_lv:
            emoji, name = e, n
        else:
            break
    return emoji, name


def expected_skill_points(level: int) -> int:
    """مجموع امتیاز مهارتی که یه بازیکن تا این لول باید گرفته باشه (لول ۱۰ دو امتیاز و لول ۲۰ سه امتیاز میده)"""
    level = max(1, int(level or 1))
    return sum(config.SKILL_BONUS_LEVELS.get(k, config.SKILL_POINT_PER_LEVEL) for k in range(2, level + 1))


def ensure_skills(user: User) -> None:
    """امتیاز مهارت کاربرای قدیمی NULL‌ه، با امتیاز پس‌دررو به‌ازای هر لولی که داره مقداردهی میشه"""
    if user.skill_points is None:
        user.skill_points = expected_skill_points(user.level or 1)
    for key in config.SKILLS:
        if getattr(user, f"skill_{key}", None) is None:
            setattr(user, f"skill_{key}", 0)


def skill_level(user: User, key: str) -> int:
    """لول یه قابلیت مهارت، همیشه بین صفر و سقف"""
    return min(max(int(getattr(user, f"skill_{key}", 0) or 0), 0), config.SKILL_MAX_LEVEL)


def spend_skill_point(user: User, key: str) -> tuple[bool, str]:
    """
    خرج ۱ امتیاز مهارت برای بالا بردن یه قابلیت
    خروجی: (موفق, دلیل ناموفقی)، ناموفق: امتیاز نداره | مکسه
    """
    ensure_skills(user)
    if (user.skill_points or 0) < 1:
        return False, "🎖 امتیاز مهارت نداری، با هر لول‌آپ یه دونه می‌گیری"
    if skill_level(user, key) >= config.SKILL_MAX_LEVEL:
        return False, "👑 این قابلیت مکسه"
    user.skill_points -= 1
    setattr(user, f"skill_{key}", skill_level(user, key) + 1)
    return True, ""


def reset_skills(user: User) -> tuple[bool, str | int]:
    """
    ریست مهارت‌ها با هزینه، همه امتیازهای خرج‌شده برمی‌گردن
    خروجی: (موفق, تعداد امتیاز برگشته یا دلیل ناموفقی)
    """
    ensure_skills(user)
    if user.cash < config.SKILL_RESET_COST:
        return False, f"💸 ریست مهارت‌ها {fa_num(config.SKILL_RESET_COST)} تی‌پوینته و پولت کمه"
    back = sum(skill_level(user, k) for k in config.SKILLS)
    if back <= 0:
        return False, "🤷 هنوز امتیازی خرج نکردی که برگرده"
    user.cash -= config.SKILL_RESET_COST
    for key in config.SKILLS:
        setattr(user, f"skill_{key}", 0)
    user.skill_points += back
    return True, back


def apply_energy_regen(user: User) -> None:
    """
    ریجن تنبلی حذف شد، فقط سقف انرژی نگه داشته میشه
    شارژ انرژی با نبض دسته‌جمعی هر ۵ دقیقه (energy_pulse_job) انجام میشه
    سقف پویاست: پایه + 20 به ازای هر لول استقامت (راند ۱۵)
    """
    from services import energy as energy_svc
    cap = energy_svc.max_energy(user)
    if user.energy > cap:
        user.energy = cap
    if user.energy_updated_at is None:
        user.energy_updated_at = now_utc()


async def get_item_keys(session: AsyncSession, user_id: int) -> list[str]:
    q = select(InventoryItem.item_key).where(InventoryItem.user_id == user_id)
    return list((await session.execute(q)).scalars())


async def get_item_levels(session: AsyncSession, user_id: int) -> dict[str, int]:
    """کلید آیتم → لول ارتقاش (سلاح/زره)، پیش‌فرض ۱"""
    q = select(InventoryItem.item_key, InventoryItem.level).where(InventoryItem.user_id == user_id)
    return {k: lv or 1 for k, lv in (await session.execute(q)).all()}


# ───────── مهمات 🔫 (راند ۲۹، درخواست کارفرما) ─────────

async def get_ammo_map(session: AsyncSession, user_id: int) -> dict[str, int]:
    """کلید سلاح گرم → تیر باقی‌مونده (None یعنی خشاب پر و تو خروجی نمیاد)"""
    q = select(InventoryItem.item_key, InventoryItem.ammo).where(
        InventoryItem.user_id == user_id, InventoryItem.ammo.is_not(None))
    return {k: int(a) for k, a in (await session.execute(q)).all()}


async def consume_ammo(session: AsyncSession, user_id: int, key: str) -> int:
    """یه تیر از خشاب کم می‌کنه و باقی‌مونده رو برمی‌گردونه؛ تفنگ نباشه یا خالی باشه -1"""
    from services import combat as _cbt
    if not _cbt.is_gun(key):
        return -1
    row = (await session.execute(
        select(InventoryItem).where(InventoryItem.user_id == user_id,
                                    InventoryItem.item_key == key))).scalar_one_or_none()
    if row is None:
        return -1
    cur = _cbt.ammo_cap(key, row.level) if row.ammo is None else int(row.ammo or 0)
    if cur <= 0:
        return 0
    row.ammo = cur - 1
    return row.ammo


async def set_ammo_full(session: AsyncSession, user_id: int, key: str) -> None:
    """خشاب رو تا ظرفیت پر می‌کنه (ریلود)"""
    from services import combat as _cbt
    row = (await session.execute(
        select(InventoryItem).where(InventoryItem.user_id == user_id,
                                    InventoryItem.item_key == key))).scalar_one_or_none()
    if row is not None:
        row.ammo = _cbt.ammo_cap(key, row.level)


async def get_ammo(session: AsyncSession, user_id: int, item_key: str) -> int | None:
    """مهمات فعلی یک سلاح (None یعنی خشاب پر)"""
    r = await session.execute(select(InventoryItem).where(
        InventoryItem.user_id == user_id, InventoryItem.item_key == item_key))
    it = r.scalars().first()
    return it.ammo if it else None


async def set_ammo(session: AsyncSession, user_id: int, item_key: str, left: int) -> bool:
    """ست‌کردن مستقیم مهمات یک سلاح"""
    r = await session.execute(select(InventoryItem).where(
        InventoryItem.user_id == user_id, InventoryItem.item_key == item_key))
    it = r.scalars().first()
    if not it:
        return False
    it.ammo = max(0, left)
    await session.commit()
    return True


def artifact_keys(item_keys: list[str] | dict) -> set[str]:
    """کلید آرتیفکت‌های مالک از روی کلیدهای انبار (arti_<key>)"""
    keys = item_keys.keys() if isinstance(item_keys, dict) else item_keys
    return {k[5:] for k in keys if k.startswith("arti_") and k[5:] in config.ARTIFACTS}


def artifact_atk_mult(artis: set[str]) -> float:
    return 1 + sum(config.ARTIFACTS[k].get("atk_mult", 0) for k in artis)


def artifact_def_mult(artis: set[str]) -> float:
    return 1 + sum(config.ARTIFACTS[k].get("def_mult", 0) for k in artis)


def artifact_xp_mult(artis: set[str]) -> float:
    return 1 + sum(config.ARTIFACTS[k].get("xp_mult", 0) for k in artis)


def artifact_steal_bonus(artis: set[str]) -> float:
    return sum(config.ARTIFACTS[k].get("steal_bonus", 0) for k in artis)


def artifact_luck(artis: set[str]) -> float:
    """شانس بهتر جستجو و شکار کمیاب، بهترین شبدر"""
    best = 1.0
    for k in artis:
        best = max(best, config.ARTIFACTS[k].get("luck", 1.0))
    return best


# ───────── مدال‌ها 🎖️ (هر تجربه‌ای = مدال، مبنای لیدربرد روزانه/هفتگی/کلی) ─────────

def award_medals(user: User, amount: int) -> None:
    """مدال = همون تجربه‌ای که کاربر می‌گیره، روزانه و هفتگی با مرز ایران ریست میشن"""
    if amount <= 0:
        return
    user.medals = (user.medals or 0) + amount

    today = iran_today()
    if user.medals_day_date != today:
        user.medals_day = 0
        user.medals_day_date = today
    user.medals_day += amount

    week = iran_week_key()
    if user.medals_week_id != week:
        user.medals_week = 0
        user.medals_week_id = week
    user.medals_week += amount


def medal_value(user: User, tab: str) -> int:
    """مدال موثر کاربر برای تب لیدربرد، سطلی کهنه صفر حساب میشه"""
    if tab == "day":
        return user.medals_day if user.medals_day_date == iran_today() else 0
    if tab == "week":
        return user.medals_week if user.medals_week_id == iran_week_key() else 0
    return user.medals or 0


def _medal_expr(tab: str):
    """عبارت SQL مدال موثر برای مرتب‌سازی، ستون کهنه صفر میشه"""
    if tab == "day":
        return case((User.medals_day_date == iran_today(), User.medals_day), else_=0)
    if tab == "week":
        return case((User.medals_week_id == iran_week_key(), User.medals_week), else_=0)
    return User.medals


async def top_by_medals(session: AsyncSession, tab: str, limit: int) -> list[User]:
    """تاپ کاربرا بر اساس مدال موثر تب، نامرئی‌های لیدربرد (ادمین) تو لیست نمیان"""
    q = (select(User).where(User.lb_hidden == 0)
         .order_by(_medal_expr(tab).desc(), User.medals.desc(), User.id).limit(limit))
    return list((await session.execute(q)).scalars())


async def medal_rank(session: AsyncSession, user: User, tab: str) -> int:
    """رتبه کاربر تو تب مدالی، بر اساس مقدار موثر؛ نامرئی‌ها تو شمارش رتبه حساب نمیشن"""
    mine = medal_value(user, tab)
    higher = (await session.execute(
        select(func.count(User.id)).where(_medal_expr(tab) > mine, User.lb_hidden == 0)
    )).scalar_one()
    return higher + 1


def add_xp(user: User, amount: int) -> list[str]:
    """
    اضافه کردن xp + مدیریت لول‌آپ، خروجی: لیست پیام‌های تبریک لول‌آپ
    جایزه هر لول: اسکناس + شارژ کامل انرژی + HP فول + لیست چیزایی که باز میشن
    بعد از لول مکس فقط تجربه جمع میشه و لول‌آپی اتفاق نمیفته
    هر xp که واریز میشه به همون اندازه مدال هم جمع میشه
    """
    from services import battle as battle_svc

    notes: list[str] = []
    user.xp += amount
    award_medals(user, amount)
    ensure_skills(user)  # کاربرای قدیمی مهارت پس‌دررو بگیرن

    while user.level < config.MAX_LEVEL and user.xp >= xp_need(user.level):
        user.xp -= xp_need(user.level)
        user.level += 1
        pts = config.SKILL_BONUS_LEVELS.get(user.level, config.SKILL_POINT_PER_LEVEL)
        user.skill_points = (user.skill_points or 0) + pts

        reward = config.LEVEL_CASH_REWARD * user.level
        user.cash += reward
        from services import energy as energy_svc
        user.energy = energy_svc.max_energy(user)  # لول‌آپ انرژی رو تا سقف پویای استقامتی فول می‌کنه
        user.energy_updated_at = now_utc()
        battle_svc.full_heal(user)  # لول‌آپ یعنی جان تازه

        # راند ۲۰: تبریک لول‌آپ با تگ لینک‌دار طرف، همون‌جور که کارفرما خواست (درخواست کارفرما)
        note = f"🎉 تبریک <a href=\"tg://user?id={user.telegram_id}\">{esc(display_name(user))}</a>، لولت رفت ({fa_num(user.level - 1)}←{fa_num(user.level)})"
        note += f"\n🎖 {fa_num(pts)} امتیاز مهارت گرفتی، برو تو «مهارت» خرجش کن"
        if user.level == config.MAX_LEVEL:
            note += "\n👑 لولت مکس شد، از این به بعد فقط تجربه جمع میشه"

        # چیزایی که با این لول باز میشن (اسمی که خودش ایموجی داره، مثل «کلت کمری 🔫»، پیشوند نمی‌گیره که جفت نشه)
        def _whead(name: str) -> str:
            return name if any(ord(c) >= 0x2500 for c in name) else f"🔪 {name}"

        unlocks: list[str] = []
        # بذرهای افسانه‌ای عمداً تو لیست نمیان، ملت فکر می‌کنن تو شاپ باز شدن در حالی که فقط از جستجو/کاروان پیداشون می‌کنن
        unlocks += [
            f"🌾 {c['name']}" for c in config.SEEDS.values()
            if c["min_level"] == user.level and not c.get("legendary")
        ]
        unlocks += [_whead(w["name"]) for w in config.WEAPONS.values() if w["min_level"] == user.level]
        unlocks += [f"🛡 {a['name']}" for a in config.ARMORS.values() if a["min_level"] == user.level]
        unlocks += [f"🐕 {d['name']}" for d in config.DOGS.values() if d["min_level"] == user.level]
        unlocks += [
            f"🗺 زمین شماره {fa_num(n)}"
            for n, p in config.PLOT_CATALOG.items() if p["min_level"] == user.level and n > 1
        ]
        if user.level == config.TEAM_JOIN_MIN_LEVEL:
            unlocks.append("🏴 عضویت تو کارتل")
        if user.level == config.TEAM_CREATE_MIN_LEVEL:
            unlocks.append("🏴 ساخت کارتل")
        if unlocks:
            note += "\n\n🔓 آیتم های جدید باز شدن\n\n" + "\n".join(unlocks)
        else:
            # بعضی لولا (مثل 9 و 17 و 19) آیتمی باز نمی‌کنن، بدون این خط متن لول‌آپ خالی به نظر می‌رسه
            note += "\n\n💪 این لول آیتم جدیدی باز نمیشه ولی قوی‌تر شدی، لول بعد پرخبره"

        notes.append(note)

    return notes
