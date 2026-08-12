"""
منطق کارتل: ساخت | عضویت | ترک | آمار و بیو | کوئست روزانه گروهی | کنده‌کاری کارتلی (استخراج)
امتیاز کارتلی با برد حمله و برداشت جمع میشه | رقابت هفتگی با جایزه به ۳ کارتل اول
ساختمان حمله و دفاع کارتل رو رهبر با بانک کارتل آپگرید می‌کنه و بونسش به همه اعضاست
کنده‌کاری کارتلی: حداقل ۳ عضو | ۷۰% اعضا باید دستورشو بزنن تا پول بره تو خزانه کارتل
"""

import json
import math
import random
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import GameMeta, Team, TeamDaily, TeamMember, TeamRequest, User
from utils import fa_num, iran_day_start_utc, iran_today, iran_week_key, iran_week_start_utc, money, normalize_fa, now_utc

# ───────── سشن‌های کنده‌کاری کارتلی (درون حافظه، با ری‌استارت پاک میشن) ─────────
# team_id → {chat_id, message_id, members(set of user_id), needed, member_count, expires_at}
TEAM_MINE_SESSIONS: dict[int, dict] = {}


def _today() -> str:
    """شناسه روز کارتل: به وقت ایران، یعنی ریست کوئستا هر شب ساعت ۱۲ (راند ۲۲، درخواست کارفرما)"""
    return iran_today()


def team_name_norm(name: str) -> str:
    """یکدست‌سازی اسم کارتل برای مقایسه، بزرگی/کوچکی حروف لاتین فرقی نمی‌کنه (Master = master)"""
    return normalize_fa(name).lower()


# ───────── لول و ظرفیت کارتل ⭐ ─────────

def team_xp_need(level: int) -> int:
    """xp لازم کارتل برای رفتن از لول فعلی به بعدی"""
    return int(config.TEAM_XP_CURVE_BASE * (level ** config.TEAM_XP_CURVE_EXP))


def team_capacity(team) -> int:
    """ظرفیت اعضا بر اساس لول کارتل، جدول دستی کانفیگ: ۱۰ نفر شروع تا ۳۰ نفر لول ۱۰"""
    level = getattr(team, "level", 1) or 1
    idx = min(max(level, 1), len(config.TEAM_CAP_TABLE)) - 1
    return config.TEAM_CAP_TABLE[idx]


async def apply_team_xp(session: AsyncSession, team: Team, amount: int) -> list[str]:
    """
    دادن خام xp به یه کارتل مشخص + پردازش لول‌آپ‌ها
    خروجی: لیست پیام‌های تبریک لول‌آپ کارتل
    """
    if amount <= 0 or team is None:
        return []
    notes: list[str] = []
    team.xp = (team.xp or 0) + int(amount)
    while (team.level or 1) < config.TEAM_MAX_LEVEL and team.xp >= team_xp_need(team.level):
        team.xp -= team_xp_need(team.level)
        team.level += 1
        notes.append(
            f"🎉 <b>کارتل «{team.name}» لول {fa_num(team.level)} شد</b>\n\n"
            f"👥 ظرفیت اعضا شد {fa_num(team_capacity(team))} نفر\n"
            f"🏗 ساختمان‌ها تا لول {fa_num(team.level)} ارتقا پیدا می‌کنن"
        )
        if team.level >= config.TEAM_MAX_LEVEL:
            notes.append("👑 کارتلتون به مکس لول رسید")
    return notes


async def give_team_xp(session: AsyncSession, team: Team, amount: int) -> list[str]:
    """xp ادمینی به کارتل (/addxpgroup)، دقیقاً همون مقدار بدون ضریب سهم"""
    return await apply_team_xp(session, team, amount)


def _need_with_curve(base: int, exp: float, level: int) -> int:
    """xp لازم با یه منحنی دلخواه، فقط برای تبدیل منحنی قدیمی"""
    return int(base * (level ** exp))


async def migrate_team_levels(session: AsyncSession) -> int:
    """
    سطح کارتل‌های موجود رو از منحنی قدیمی (TEAM_XP_CURVE_MIGRATION_FROM) به منحنی فعلی تبدیل می‌کنه
    چون مجموع تجربه گرفته‌شده فقط از شمار لول‌های عبور‌کرده قدیمی + xp فعلی بازسازی میشه
    یه‌بارمصرفه؛ فلگ game_meta جلو اجرای دوباره رو می‌گیره، خروجی: تعداد کارتل‌های تبدیل‌شده
    """
    flag = await meta_get(session, "team_lvl_v2")
    if flag:
        return 0
    base_old, exp_old = config.TEAM_XP_CURVE_MIGRATION_FROM
    teams = list((await session.execute(select(Team))).scalars())
    changed = 0
    for t in teams:
        level = t.level or 1
        xp = t.xp or 0
        if level <= 1 and xp <= 0:
            continue
        total = xp
        for lv in range(1, level):
            total += _need_with_curve(base_old, exp_old, lv)
        t.level, t.xp = 1, 0
        # ری‌پلی لول‌آپ با منحنی جدید
        remaining = total
        while t.level < config.TEAM_MAX_LEVEL and remaining >= team_xp_need(t.level):
            remaining -= team_xp_need(t.level)
            t.level += 1
        t.xp = remaining
        changed += 1
    await meta_set(session, "team_lvl_v2", "1")
    return changed


async def add_team_xp(session: AsyncSession, user: User, amount: int) -> list[str]:
    """
    سهم کارتل از تجربه‌ای که هر عضو می‌گیره (کنده‌کاری | حمله | برداشت و…)
    خروجی: لیست پیام‌های تبریک لول‌آپ کارتل
    """
    if amount <= 0:
        return []
    team = await get_team_of(session, user.id)
    if not team:
        return []
    return await apply_team_xp(session, team, int(amount * config.TEAM_XP_SHARE))


# ───────── کوئری پایه ─────────

async def get_team_by_name(session: AsyncSession, name: str) -> Team | None:
    q = select(Team).where(Team.name_norm == team_name_norm(name))
    return (await session.execute(q)).scalar_one_or_none()


async def get_membership(session: AsyncSession, user_id: int) -> TeamMember | None:
    q = select(TeamMember).where(TeamMember.user_id == user_id)
    return (await session.execute(q)).scalar_one_or_none()


async def get_team_of(session: AsyncSession, user_id: int) -> Team | None:
    m = await get_membership(session, user_id)
    if not m:
        return None
    # lazy-load تو async ممنوعه، مستقیم می‌گیریم
    return await session.get(Team, m.team_id)


async def get_members(session: AsyncSession, team_id: int) -> list[TeamMember]:
    q = select(TeamMember).where(TeamMember.team_id == team_id).order_by(TeamMember.role, TeamMember.id)
    return list((await session.execute(q)).scalars())


async def member_count(session: AsyncSession, team_id: int) -> int:
    q = select(func.count(TeamMember.id)).where(TeamMember.team_id == team_id)
    return (await session.execute(q)).scalar_one()


# ───────── ساخت و عضویت و ترک ─────────

async def can_create_team(session: AsyncSession, user: User) -> tuple[bool, str]:
    """چک‌های قبل از پرسیدن اسم کارتل"""
    if user.level < config.TEAM_CREATE_MIN_LEVEL:
        return False, f"🔒 ساخت کارتل لول {fa_num(config.TEAM_CREATE_MIN_LEVEL)} می‌خواد"
    if await get_membership(session, user.id):
        return False, "🏴 عزیز خودت تو یه کارتلی نمی‌تونی توی کارتل دیگری عضو بشی، اول «ترک کارتل» رو بزن"
    if user.cash < config.TEAM_CREATE_COST:
        return False, f"❌ ساخت کارتل {money(config.TEAM_CREATE_COST)} هزینه داره و پولت کمه"
    return True, ""


def validate_team_name(name: str) -> tuple[bool, str, str]:
    """ولیدیشن اسم کارتل، خروجی: (اوکی, اسم تمیز, دلیل رد)"""
    clean = normalize_fa(name)
    if not clean or len(clean) < 2:
        return False, clean, "❌ اسم کارتل خیلی کوتاهه"
    if len(clean) > config.TEAM_NAME_MAX:
        return False, clean, f"❌ اسم کارتل حداکثر {fa_num(config.TEAM_NAME_MAX)} حرف می‌تونه باشه"
    if ":" in clean or "<" in clean or ">" in clean:
        return False, clean, "❌ تو اسم کارتل کاراکتر عجیب نذار"
    return True, clean, ""


async def create_team(session: AsyncSession, user: User, name: str) -> tuple[bool, str]:
    """ساخت کارتل با اسم انتخابی، هزینه همونجا کم میشه"""
    ok, alert = await can_create_team(session, user)
    if not ok:
        return False, alert

    ok_name, clean, why = validate_team_name(name)
    if not ok_name:
        return False, why

    if await get_team_by_name(session, clean):
        return False, f"🏴 کارتلی با اسم «{clean}» از قبل هست، یه اسم دیگه بردار"

    # اسم نمایشی همون چیزی میمونه که کاربر تایپ کرد (با نیم‌فاصله)، نسخه نرمال فقط برای یکتایی
    display = " ".join(str(name).split())
    user.cash -= config.TEAM_CREATE_COST
    team = Team(name=display, name_norm=team_name_norm(display), owner_id=user.id)
    session.add(team)
    await session.flush()
    session.add(TeamMember(team_id=team.id, user_id=user.id, role="owner", join_medals=user.medals or 0))
    return True, display


# ───────── نقش‌ها 👑 ─────────

def is_manager(m: TeamMember | None) -> bool:
    """رهبر یا مدیر کارتل؟ (ممیزی بخش 👑 مدیریت کارتل)"""
    return bool(m and m.role in ("owner", "admin"))


def can_kick(me: TeamMember, target: TeamMember) -> tuple[bool, str]:
    """قانون اخراج: رهبر هرکسی رو جز خودش، مدیر فقط عضو عادی رو"""
    if target.role == "owner":
        return False, "👑 رهبر که اخراج نمیشه 😅"
    if me.role != "owner" and target.role != "member":
        return False, "👑 اخراج مدیر فقط با رهبره"
    return True, ""


# ───────── درخواست عضویت 📨 ─────────

async def request_join(session: AsyncSession, user: User, name: str) -> tuple[bool, str]:
    """«جوین کارتل X» عضویت مستقیم نیس، فقط درخواست ثبت میشه تا مدیران تصمیم بگیرن"""
    if user.level < config.TEAM_JOIN_MIN_LEVEL:
        return False, f"🔒 عضویت تو کارتل لول {fa_num(config.TEAM_JOIN_MIN_LEVEL)} می‌خواد"
    if await get_membership(session, user.id):
        return False, "🏴 عزیز خودت تو یه کارتلی نمی‌تونی توی کارتل دیگری عضو بشی، اول «ترک کارتل» رو بزن"

    team = await get_team_by_name(session, name)
    if not team:
        return False, f"🤷 کارتلی با اسم «{normalize_fa(name)}» پیدا نشد"

    count = await member_count(session, team.id)
    if count >= team_capacity(team):
        return False, f"🏴 کارتل «{team.name}» پره"

    dup = await session.execute(
        select(TeamRequest).where(TeamRequest.team_id == team.id, TeamRequest.user_id == user.id)
    )
    if dup.scalar_one_or_none():
        return False, f"📨 درخواستت برای کارتل «{team.name}» از قبل تو صفه"

    session.add(TeamRequest(team_id=team.id, user_id=user.id))
    return True, team.name


async def get_requests(session: AsyncSession, team_id: int) -> list[tuple[TeamRequest, User]]:
    """درخواست‌های در انتظار کارتل به ترتیب ثبت، همراه خود کاربر"""
    q = (
        select(TeamRequest, User)
        .join(User, User.id == TeamRequest.user_id)
        .where(TeamRequest.team_id == team_id)
        .order_by(TeamRequest.id)
    )
    return [(r, u) for r, u in (await session.execute(q)).all()]


async def get_request(session: AsyncSession, req_id: int) -> tuple[TeamRequest, User] | None:
    q = (
        select(TeamRequest, User)
        .join(User, User.id == TeamRequest.user_id)
        .where(TeamRequest.id == req_id)
    )
    row = (await session.execute(q)).first()
    return (row[0], row[1]) if row else None


async def find_request_by_query(session: AsyncSession, team_id: int, query: str) -> tuple[TeamRequest, User] | None:
    """درخواست معلق رو با آیدی عددی یا @یوزرنیم پیدا کن (مچ جزئی یوزرنیم هم اوکیه)"""
    reqs = await get_requests(session, team_id)
    q = (query or "").strip()
    if q.lstrip("-").isdigit():
        tg = int(q)
        hits = [x for x in reqs if x[1].telegram_id == tg]
        return hits[0] if hits else None
    norm = q.lstrip("@").lower()
    if not norm:
        return None
    for r, u in reqs:
        if (u.username or "").lower() == norm:
            return (r, u)
    for r, u in reqs:
        if norm and norm in (u.username or "").lower():
            return (r, u)
    return None


async def accept_request(session: AsyncSession, req: TeamRequest, target: User) -> tuple[bool, str]:
    """قبول درخواست: ظرفیت و تک‌کارتلی بودن دوباره چک میشه و عضو عادی میشه"""
    if await get_membership(session, target.id):
        await session.delete(req)
        return False, "👤 طرف الان تو کارتل دیگه‌ای عضو شد، درخواستش پاک شد"
    team = await session.get(Team, req.team_id)
    count = await member_count(session, req.team_id)
    if team is not None and count >= team_capacity(team):
        await session.delete(req)
        return False, "🏴 کارتل پر شده بود، درخواست پاک شد"
    session.add(TeamMember(team_id=req.team_id, user_id=target.id, role="member", join_medals=target.medals or 0))
    await session.delete(req)
    return True, ""


async def reject_request(session: AsyncSession, req: TeamRequest) -> None:
    await session.delete(req)


# ───────── عضوهای کارتل: سرچ فازی + ادمین ─────────

async def find_team_member(session: AsyncSession, team_id: int, query: str) -> tuple[TeamMember, User] | None:
    """
    نزدیک‌ترین عضو کارتل به کوئری
    آیدی عددی دقیق | @یوزرنیم دقیق بعد مچ جزئی | اسم دقیق بعد شروع‌شونده بعد بخشی از اسم
    """
    members = await get_members(session, team_id)
    uids = [m.user_id for m in members]
    if not uids:
        return None
    q_users = await session.execute(select(User).where(User.id.in_(uids)))
    by_id = {u.id: u for u in q_users.scalars()}
    pairs = [(m, by_id[m.user_id]) for m in members if m.user_id in by_id]

    q = (query or "").strip()
    if q.lstrip("-").isdigit():
        tg = int(q)
        hits = [p for p in pairs if p[1].telegram_id == tg]
        return hits[0] if hits else None

    norm = normalize_fa(q.lstrip("@")).lower()
    if not norm:
        return None
    exact = [p for p in pairs if (p[1].username or "").lower() == norm]
    if exact:
        return exact[0]
    exact_name = [p for p in pairs if normalize_fa(p[1].first_name or "").lower() == norm]
    if exact_name:
        return exact_name[0]
    pref = [p for p in pairs if (p[1].username or "").lower().startswith(norm)
            or normalize_fa(p[1].first_name or "").lower().startswith(norm)]
    if pref:
        return pref[0]
    part = [p for p in pairs if norm in (p[1].username or "").lower()
            or norm in normalize_fa(p[1].first_name or "").lower()]
    return part[0] if part else None


async def toggle_admin(session: AsyncSession, owner_user: User, query: str) -> tuple[bool, str, User | None, bool]:
    """مدیر کردن یا برداشتن مدیریت، فقط رهبر، (اوکی، دلیل، هدف، مدیر شد?)"""
    me = await get_membership(session, owner_user.id)
    if not me or me.role != "owner":
        return False, "👑 فقط رهبر می‌تونه مدیر بذاره", None, False
    hit = await find_team_member(session, me.team_id, query)
    if not hit:
        return False, "🤷 عضوی با این مشخصات تو کارتل پیدا نشد", None, False
    mrow, target = hit
    if mrow.role == "owner":
        return False, "👑 خودت رهبری دیگه 😅", None, False
    if mrow.role == "admin":
        mrow.role = "member"
        return True, "", target, False
    mrow.role = "admin"
    return True, "", target, True


async def leave_team(session: AsyncSession, user: User) -> tuple[bool, str]:
    """عضو عادی خارج میشه، رهبر نمی‌تونه بره مگر کارتل رو منحل کنه"""
    m = await get_membership(session, user.id)
    if not m:
        return False, "🏴 اصلا تو کارتلی نیستی که"
    if m.role == "owner":
        return False, "👑 تو رهبری، یا کارتل رو با «انحلال کارتل» منحل کن یا اول جانشین بذار ندارم 😅"
    team = await session.get(Team, m.team_id)
    name = team.name if team else "؟"
    await session.delete(m)
    return True, name


async def disband_team(session: AsyncSession, user: User) -> tuple[bool, str]:
    """انحلال توسط رهبر، خزانه و آمار نابود میشه"""
    m = await get_membership(session, user.id)
    if not m or m.role != "owner":
        return False, "👑 فقط رهبر می‌تونه کارتل رو منحل کنه"
    team = await session.get(Team, m.team_id)
    if not team:
        return False, "🤷 کارتلی نیس که"
    name = team.name
    TEAM_MINE_SESSIONS.pop(team.id, None)
    await session.execute(delete(TeamRequest).where(TeamRequest.team_id == team.id))  # درخواست‌های معلق هم پاک میشن
    await session.delete(team)  # memberها با cascade پاک میشن
    return True, name


async def set_bio(session: AsyncSession, user: User, bio: str) -> tuple[bool, str]:
    """ست کردن پروفایل/بیو کارتل، فقط رهبر، تو آمار کارتل نمایش داده میشه"""
    m = await get_membership(session, user.id)
    if not m or m.role != "owner":
        return False, "👑 فقط رهبر می‌تونه بیوی کارتل رو عوض کنه"
    clean = normalize_fa(bio)
    if not clean:
        return False, "❌ بیو خالی که نمیشه"
    display = " ".join(str(bio).split())
    if len(display) > config.TEAM_BIO_MAX:
        return False, f"❌ بیو حداکثر {fa_num(config.TEAM_BIO_MAX)} حرف"
    team = await session.get(Team, m.team_id)
    if not team:
        return False, "🤷 کارتلی نیس که"
    team.bio = display
    return True, display


# ───────── تغییر نام کارتل ✏️ ─────────

async def rename_precheck(session: AsyncSession, user: User, new_name: str) -> tuple[bool, object]:
    """
    ولیدیشن تغییر نام بدون اعمال، برای مرحله نمایش فاکتور و تایید
    موفق: (True, (کارتل، اسم نمایشی پاک‌شده)) | ناموفق: (False، دلیل)
    """
    m = await get_membership(session, user.id)
    if not m or m.role != "owner":
        return False, "👑 فقط رهبر می‌تونه اسم کارتل رو عوض کنه"
    ok_name, clean, why = validate_team_name(new_name)
    if not ok_name:
        return False, why
    team = await session.get(Team, m.team_id)
    if not team:
        return False, "🤷 کارتلی نیس که"
    if team_name_norm(team.name) == clean:
        return False, "😅 همین الانشم اسمش همینه"
    if await get_team_by_name(session, clean):
        return False, f"🏴 کارتلی با اسم «{clean}» از قبل هست، یه اسم دیگه بگو"

    cost = config.TEAM_RENAME_COST
    if user.cash < cost:
        return False, f"❌ تغییر نام {money(cost)} می‌خواد و {money(user.cash)} داری"

    display = " ".join(str(new_name).split())
    return True, (team, display)


async def rename_team(session: AsyncSession, user: User, new_name: str) -> tuple[bool, str]:
    """
    تغییر نام کارتل توسط رهبر با پرداخت TEAM_RENAME_COST از جیب خودش
    دوباره از روی validate رد میشه چون بین تایید و اجرا وضعیت می‌تونه عوض بشه
    """
    ok, res = await rename_precheck(session, user, new_name)
    if not ok:
        return False, res
    team, display = res

    cost = config.TEAM_RENAME_COST
    user.cash -= cost
    old = team.name
    team.name = display
    team.name_norm = team_name_norm(display)  # ستون یکدست‌شده جستجو هم آپدیت میشه
    return True, f"✏️ اسم کارتل از «{old}» شد «{team.name}»\n💸 {money(cost)} هم از جیبت کم شد"


# ───────── آمار کارتل ─────────

async def team_stats_data(session: AsyncSession, team: Team) -> dict:
    """دیتای آمار کارتل برای نمایش"""
    members = await get_members(session, team.id)
    users: list[User] = []
    for m in members:
        u = await session.get(User, m.user_id)
        if u:
            users.append(u)

    daily = await _daily(session, team.id)
    owner_name = "؟"
    for m in members:
        if m.role == "owner":
            for u in users:
                if u.id == m.user_id:
                    owner_name = "👻 نامرئی" if u.lb_hidden else (u.first_name or u.username or "؟")
            break

    by_id = {u.id: u for u in users}
    medals_sum = {"all": 0, "week": 0, "day": 0}
    for m in members:
        u = by_id.get(m.user_id)
        if not u:
            continue
        medals_sum["all"] += _member_medals(m, u, "all")
        medals_sum["week"] += _member_medals(m, u, "week")
        medals_sum["day"] += _member_medals(m, u, "day")

    return {
        "team": team,
        "members": members,
        "users": users,
        "count": len(members),
        "owner_name": owner_name,
        "wins": sum(u.wins for u in users),
        "losses": sum(u.losses for u in users),
        "medals": medals_sum,
        "daily": daily,
    }


async def top_teams(session: AsyncSession, limit: int = 10) -> list[tuple[Team, int]]:
    """برترین کارتل‌ها بر اساس خزانه، کارتل‌هایی که رهبرشون نامرئیه (/hideboard) نمیان توی لیست"""
    q = (
        select(Team)
        .join(TeamMember, (TeamMember.team_id == Team.id) & (TeamMember.role == "owner"))
        .join(User, User.id == TeamMember.user_id)
        .where(User.lb_hidden == 0, Team.lb_hidden == 0)
        .order_by(Team.bank.desc(), Team.total_kills.desc())
        .limit(limit)
    )
    teams = list((await session.execute(q)).scalars())
    return [(t, await member_count(session, t.id)) for t in teams]


# ───────── کوئست روزانه ─────────

async def _daily(session: AsyncSession, team_id: int) -> TeamDaily:
    """ردیف امروز کارتل رو بگیر، اگه نبود بساز"""
    day = _today()
    q = select(TeamDaily).where(TeamDaily.team_id == team_id, TeamDaily.day == day)
    row = (await session.execute(q)).scalar_one_or_none()
    if not row:
        row = TeamDaily(team_id=team_id, day=day)
        session.add(row)
        await session.flush()
    return row


def _qprog(daily: TeamDaily) -> dict:
    """شمارنده‌های JSON کوئست (برای کلیدهای بدون ستون اختصاصی)"""
    try:
        d = json.loads(daily.qprog or "{}")
    except (ValueError, TypeError):
        return {}
    return d if isinstance(d, dict) else {}


def _qdone(daily: TeamDaily) -> list:
    """کلیدهای تکمیل‌شده JSON"""
    try:
        d = json.loads(daily.qdone or "[]")
    except (ValueError, TypeError):
        return []
    return d if isinstance(d, list) else []


def _quest_progress(daily: TeamDaily, key: str) -> tuple[int, bool]:
    if key == "kills":
        return daily.kills, bool(daily.kills_done)
    if key == "harvest":
        return daily.harvests, bool(daily.harvests_done)
    return int(_qprog(daily).get(key, 0)), key in _qdone(daily)


def _quest_mark_done(daily: TeamDaily, key: str) -> None:
    if key == "kills":
        daily.kills_done = 1
    elif key == "harvest":
        daily.harvests_done = 1
    else:
        done = _qdone(daily)
        if key not in done:
            done.append(key)
        daily.qdone = json.dumps(done, ensure_ascii=False)


def team_quest_scaled(quest: dict, team_level: int) -> dict | None:
    """
    کوئست مقیاس‌خورده با لول کارتل، None اگه کارتل به لولش نرسیده باشه
    هرچی لول کارتل بالاتر، هدف سخت‌تر و جایزه بزرگ‌تر
    """
    lvl = max(1, min(int(team_level or 1), config.TEAM_MAX_LEVEL))
    if lvl < quest.get("min_level", 1):
        return None
    steps = lvl - quest.get("min_level", 1)
    target = max(1, round(quest["target"] * (1 + config.TEAM_QUEST_TARGET_GROWTH * steps)))
    reward = round(quest["reward"] * (1 + config.TEAM_QUEST_REWARD_GROWTH * steps))
    bank = round(quest.get("bank_reward", 0) * (1 + config.TEAM_QUEST_REWARD_GROWTH * steps))
    return {
        **quest,
        "target": target,
        "reward": reward,
        "bank_reward": bank,
        "title": quest["title"].format(n=fa_num(target)),
    }


def daily_quests(team_id: int, team_level: int, day: str | None = None) -> list[dict]:
    """
    کوئست‌های فعال امروز کارتل (راند ۲۲، درخواست کارفرما)
    هر روز بین ۲ تا ۴ تا از بین کوئست‌های بازشده اون لول شانسی انتخاب میشن و
    هدف و جایزه هرکدوم یه جیتر شانسی می‌خوره؛ قرعه با سید «روز ایران + آیدی کارتل»
    ثابته، یعنی کل اون روز برای همه اعضا همین کوئستا با همین عددها می‌مونن
    """
    lvl = max(1, min(int(team_level or 1), config.TEAM_MAX_LEVEL))
    pool = [q for q in config.TEAM_QUESTS if lvl >= q.get("min_level", 1)]
    if not pool:
        return []
    rng = random.Random(f"tq:{day or _today()}:{int(team_id)}")
    n = min(len(pool), rng.randint(config.TEAM_QUEST_DAILY_MIN, config.TEAM_QUEST_DAILY_MAX))
    jt = config.TEAM_QUEST_TARGET_JITTER
    jr = config.TEAM_QUEST_REWARD_JITTER
    out: list[dict] = []
    for q in rng.sample(pool, k=n):
        scaled = team_quest_scaled(q, lvl)
        target = max(1, round(scaled["target"] * (1 + rng.uniform(-jt, jt))))
        reward = max(1, round(scaled["reward"] * (1 + rng.uniform(-jr, jr))))
        bank = max(0, round(scaled.get("bank_reward", 0) * (1 + rng.uniform(-jr, jr))))
        out.append({
            **scaled,
            "target": target,
            "reward": reward,
            "bank_reward": bank,
            "title": q["title"].format(n=fa_num(target)),
        })
    return out


async def _record(session: AsyncSession, user: User, key: str, n: int) -> str | None:
    """
    ثبت پیشرفت کوئست + امتیاز کارتل، اگه سقف پر شد جایزه به همه اعضا میرسه
    خروجی: متن اعلان تکمیل کوئست یا None
    """
    await maybe_weekly_rollover(session)  # اول هفته جدید چک بشه

    team = await get_team_of(session, user.id)
    if not team:
        return None

    daily = await _daily(session, team.id)

    if key == "kills":
        daily.kills += n
        team.total_kills += n
        team.points += config.TEAM_POINT_KILL * n
        team.week_points += config.TEAM_POINT_KILL * n
    elif key == "harvest":
        daily.harvests += n
        team.total_harvests += n
        team.points += config.TEAM_POINT_HARVEST * n
        team.week_points += config.TEAM_POINT_HARVEST * n
    else:
        prog = _qprog(daily)
        prog[key] = int(prog.get(key, 0)) + n
        daily.qprog = json.dumps(prog, ensure_ascii=False)

    # راند ۲۲: جایزه فقط مال کوئست‌های فعال امروز کارتل، با عددهای شانسی همون روز
    active = {q["key"]: q for q in daily_quests(team.id, team.level or 1)}
    scaled = active.get(key)
    if scaled is None:
        return None  # این کوئست امروز برای کارتل فعال نیس
    progress, done = _quest_progress(daily, key)
    if progress >= scaled["target"] and not done:
        _quest_mark_done(daily, key)

        members = await get_members(session, team.id)
        for m in members:
            u = await session.get(User, m.user_id)
            if u:
                u.cash += scaled["reward"]

        bank_reward = scaled.get("bank_reward", 0)
        team.bank += bank_reward
        bank_line = f"\n🏦 و {money(bank_reward)} هم به بانک کارتل رسید" if bank_reward else ""

        # جایزه ویژه کارتلی: لول کارتل ۷ به بالا، با شانس کم یه بذر جهنم یا ابلیس به هر عضو میرسه
        legend_line = ""
        if (team.level or 1) >= config.TEAM_QUEST_LEGEND_MIN_LEVEL and random.random() < config.TEAM_QUEST_LEGEND_CHANCE:
            from services import farming as farm_svc
            for m in members:
                await farm_svc.add_seed_stock(session, m.user_id, random.choice(config.QUEST_LEGEND_SEEDS), 1)
            legend_line = "\n🍀 بخت باهاتون یار بود، یه بذر افسانه‌ای 🔥 یا 😈 هم به هر عضو رسید"

        return (
            f"🏴 کوئست {scaled['emoji']} «{scaled['title']}» کارتل «{team.name}» کامل شد!\n"
            f"🎁 {money(scaled['reward'])} به هر عضو کارتل رسید{bank_line}{legend_line}"
        )
    return None


async def record_kill(session: AsyncSession, user: User) -> str | None:
    """هر برد تو نبرد، با قلاب execute_hit توی services.battle صدا زده میشه"""
    return await _record(session, user, "kills", 1)


async def record_harvest(session: AsyncSession, user: User, n: int) -> str | None:
    """هر محصول برداشت‌شده، با قلاب harvest_all صدا زده میشه"""
    return await _record(session, user, "harvest", n)


async def record_mine(session: AsyncSession, user: User) -> str | None:
    """هر کنده‌کاری موفق عضو، با قلاب هندلر معدن صدا زده میشه"""
    return await _record(session, user, "mine", 1)


async def record_search(session, user: User) -> str | None:
    """هر جستجوی موفق عضو، با قلاب هندلر جستجو صدا زده میشه"""
    return await _record(session, user, "search", 1)


async def record_caravan(session, user: User) -> str | None:
    """هر ضربه عضو به کاروان، با قلاب هندلر کاروان صدا زده میشه"""
    return await _record(session, user, "caravan", 1)


async def record_plant(session, user: User, n: int = 1) -> str | None:
    """هر بذری که عضو می‌کاره، کوئست کارتلی کاشت"""
    return await _record(session, user, "plant", n)


async def record_feed(session, user: User) -> str | None:
    """هر بار غذا دادن به سگ، کوئست کارتلی غذا"""
    return await _record(session, user, "feed", 1)


async def record_team_deposit(session, user: User, amount: int) -> str | None:
    """هر واریز به بانک کارتل، کوئست کارتلی «واریز مجموع» با مبلغ"""
    return await _record(session, user, "depbank", amount)


async def record_drink(session, user: User) -> str | None:
    """هر انرژی‌زای خورده‌شده عضو، کوئست کارتلی نوشیدنی (راند ۱۵)"""
    return await _record(session, user, "drink", 1)


async def record_shipment(session, user: User) -> str | None:
    """هر محموله ارسالی عضو، کوئست کارتلی ارسال (راند ۱۵)"""
    return await _record(session, user, "shipment", 1)


async def record_sellres(session, user: User, n: int) -> str | None:
    """هر واحد چوب یا آهن فروخته‌شده عضو، کوئست کارتلی فروش منابع (راند ۱۵)"""
    return await _record(session, user, "sellres", n)


def quests_view(daily: TeamDaily, team_level: int = 1) -> list[dict]:
    """نمایش کوئست‌های باز برای لول کارتل با پیشرفت، برای متن استعلام"""
    out = []
    for q in config.TEAM_QUESTS:
        scaled = team_quest_scaled(q, team_level)
        if scaled is None:
            continue
        progress, done = _quest_progress(daily, q["key"])
        out.append({**scaled, "progress": min(progress, scaled["target"]), "done": done})
    return out


def daily_quests_view(daily: TeamDaily, team_id: int, team_level: int) -> list[dict]:
    """فقط کوئست‌های فعال امروز (۲ تا ۴ تا) با پیشرفت و وضعیت تکمیل (راند ۲۲، درخواست کارفرما)"""
    out = []
    for q in daily_quests(team_id, team_level):
        progress, done = _quest_progress(daily, q["key"])
        out.append({**q, "progress": min(progress, q["target"]), "done": done})
    return out


def locked_quests_view(team_level: int) -> list[dict]:
    """کوئست‌هایی که لول کارتل بهشون نرسیده، برای نمایش قفل‌شده تو استعلام"""
    lvl = max(1, int(team_level or 1))
    return [q for q in config.TEAM_QUESTS if lvl < q.get("min_level", 1)]


# ───────── کنده‌کاری کارتلی (استخراج) ─────────

def mine_needed(member_n: int) -> int:
    """تعداد نفرات لازم، سقف ۷۰% اعضا و حداقل ۳ نفر (کارتل زیر ۳ نفره نمی‌تونه استخراج کنه)"""
    return max(3, math.ceil(config.TEAM_MINE_JOIN_PCT * member_n))


async def team_mine_join(session: AsyncSession, user: User) -> dict:
    """
    پیوستن/استارت کنده‌کاری کارتلی با دستور متنی
    خروجی: دیکشنری وضعیت برای هندلر، status:
      no_team | cooldown | started | joined | already | completed | failed_expired_* (+ restart)
    """
    await maybe_weekly_rollover(session)

    team = await get_team_of(session, user.id)
    if not team:
        return {"status": "no_team"}

    m_count = await member_count(session, team.id)
    if m_count < 3:
        return {"status": "too_few", "team": team, "member_count": m_count}
    needed = mine_needed(m_count)
    now = now_utc()

    # پاکسازی سشن منقضی
    sess = TEAM_MINE_SESSIONS.get(team.id)
    expired_restart = False
    if sess and sess["expires_at"] < now:
        expired_restart = True
        TEAM_MINE_SESSIONS.pop(team.id, None)
        sess = None

    if not sess:
        # کولدان بعد از آخرین کنده‌کاری موفق
        if team.last_team_mine_at:
            cd = timedelta(minutes=config.TEAM_MINE_COOLDOWN_MINUTES)
            if now - team.last_team_mine_at < cd:
                left = int((cd - (now - team.last_team_mine_at)).total_seconds())
                return {"status": "cooldown", "left": left, "team": team}

        sess = {
            "members": set(),
            "needed": needed,
            "member_count": m_count,
            "expires_at": now + timedelta(seconds=config.TEAM_MINE_WINDOW_SECONDS),
            "chat_id": None,
            "message_id": None,
        }
        TEAM_MINE_SESSIONS[team.id] = sess

    if user.id in sess["members"]:
        return {
            "status": "already", "team": team,
            "joined": len(sess["members"]), "needed": sess["needed"],
            "member_count": sess["member_count"],
        }

    sess["members"].add(user.id)
    joined = len(sess["members"])
    result = {
        "team": team,
        "joined": joined,
        "needed": sess["needed"],
        "member_count": sess["member_count"],
        "expires_at": sess["expires_at"],
        "restart": expired_restart,
        "status": "started" if joined == 1 else "joined",
    }

    if joined >= sess["needed"]:
        # تکمیل، پول میره تو خزانه
        per = [random.randint(config.TEAM_MINE_PER_MIN, config.TEAM_MINE_PER_MAX) for _ in sess["members"]]
        total = sum(per)
        team.bank += total
        team.last_team_mine_at = now
        TEAM_MINE_SESSIONS.pop(team.id, None)
        result.update(status="completed", reward=total, bank=team.bank)

    return result


def bind_mine_message(team_id: int, chat_id: int, message_id: int) -> None:
    """آی‌دی پیام نمایش کنده‌کاری رو نگه می‌داریم که با هر پیوستن ادیتش کنیم"""
    sess = TEAM_MINE_SESSIONS.get(team_id)
    if sess:
        sess["chat_id"] = chat_id
        sess["message_id"] = message_id


# ───────── امتیاز کارتل و رقابت هفتگی 🏆 ─────────

def current_week_key() -> str:
    """کلید هفته جاری به‌وقت ایران (ISO)، مثل 2026-W30"""
    return iran_week_key()


async def meta_get(session: AsyncSession, key: str) -> str | None:
    row = await session.get(GameMeta, key)
    return row.value if row else None


async def meta_set(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(GameMeta, key)
    if row:
        row.value = value
    else:
        session.add(GameMeta(key=key, value=value))


async def top_teams_by_points(session: AsyncSession, limit: int = 10) -> list[tuple[Team, int]]:
    """لیدربرد کلی، بر اساس امتیاز کارتل | کارتل‌های مخفی («کارتل مخفی») نمیان"""
    q = select(Team).where(Team.lb_hidden == 0).order_by(Team.points.desc(), Team.total_kills.desc()).limit(limit)
    teams_ = list((await session.execute(q)).scalars())
    return [(t, await member_count(session, t.id)) for t in teams_]


async def top_teams_week(session: AsyncSession, limit: int = 10) -> list[tuple[Team, int]]:
    """رقابت این هفته، بر اساس امتیاز هفته | کارتل‌های مخفی («کارتل مخفی») نمیان"""
    q = select(Team).where(Team.lb_hidden == 0).order_by(Team.week_points.desc(), Team.points.desc()).limit(limit)
    teams_ = list((await session.execute(q)).scalars())
    return [(t, await member_count(session, t.id)) for t in teams_]


# ───────── مدال‌های کارتل 🎖️ (مبنای لیدربرد کارتل روزانه/هفتگی/کلی) ─────────
# کلی: همه مدال‌های اعضا | هفتگی/روزانه: فقط مدال‌هایی که تو بازه و بعد از عضویت جمع شده

def _member_medals(m: TeamMember, u: User, tab: str, week_id: str | None = None, day_id: str | None = None) -> int:
    """سهم مدالی یه عضو برای یه تب، استثنای جوین وسط بازه با baseline لحظه عضویت"""
    if tab == "day":
        did = day_id or iran_today()
        start = iran_day_start_utc() if day_id is None else _day_start_utc_for(did)
        fresh = u.medals_day if u.medals_day_date == did else 0
    elif tab == "week":
        wid = week_id or iran_week_key()
        start = iran_week_start_utc() if week_id is None else week_start_utc_for(wid)
        fresh = u.medals_week if u.medals_week_id == wid else 0
    else:
        return u.medals or 0
    if m.joined_at and m.joined_at > start:
        # وسط بازه اومده، فقط مدال‌هایی که بعد اومدنش و تو همون بازه گرفته
        return max(0, min((u.medals or 0) - (m.join_medals or 0), fresh))
    return fresh


def _day_start_utc_for(day_id: str) -> datetime:
    """شروع یه روز خاص به‌وقت ایران، برگردونده‌شده به UTC"""
    from datetime import datetime as _dt
    y, mo, d = (int(x) for x in day_id.split("-"))
    return _dt(y, mo, d) - timedelta(hours=3, minutes=30)


def week_start_utc_for(week_id: str) -> datetime:
    """شروع دوشنبه یه هفته ISO خاص به‌وقت ایران، برگردونده‌شده به UTC"""
    from datetime import date as _date, datetime as _dt
    y, w = (int(x) for x in week_id.replace("W", "").split("-") if x)
    d = _date.fromisocalendar(y, w, 1)
    return _dt(d.year, d.month, d.day) - timedelta(hours=3, minutes=30)


async def team_medal_sums(session: AsyncSession, team_id: int) -> dict:
    """جمع مدال‌های اعضای کارتل توی سه بازه کلی/هفته/امروز"""
    members = await get_members(session, team_id)
    out = {"all": 0, "week": 0, "day": 0}
    for m in members:
        u = await session.get(User, m.user_id)
        if not u:
            continue
        out["all"] += _member_medals(m, u, "all")
        out["week"] += _member_medals(m, u, "week")
        out["day"] += _member_medals(m, u, "day")
    return out


async def top_teams_by_medals(session: AsyncSession, tab: str, limit: int = 10,
                              week_id: str | None = None, day_id: str | None = None,
                              include_hidden: bool = False) -> list[tuple[Team, int, int]]:
    """برترین کارتل‌ها بر اساس مدال اعضا توی تب، خروجی: (کارتل، جمع مدال، تعداد اعضا)
    کارتل‌های مخفی از نمایش حذفن ولی برای جایزه هفتگی (include_hidden) حساب میشن"""
    q = select(Team) if include_hidden else select(Team).where(Team.lb_hidden == 0)
    all_teams = list((await session.execute(q)).scalars())
    scored: list[tuple[Team, int, int]] = []
    for t in all_teams:
        members = await get_members(session, t.id)
        total = 0
        for m in members:
            u = await session.get(User, m.user_id)
            if u:
                total += _member_medals(m, u, tab, week_id=week_id, day_id=day_id)
        scored.append((t, total, len(members)))
    scored.sort(key=lambda x: (-x[1], -x[2], x[0].id))
    return scored[:limit]


async def member_telegram_ids(session: AsyncSession, team_id: int) -> list[int]:
    """تلگرام‌آی‌دی اعضا، برای اطلاع‌رسانی جایزه هفتگی"""
    q = select(TeamMember.user_id).where(TeamMember.team_id == team_id)
    ids = list((await session.execute(q)).scalars())
    out: list[int] = []
    for uid in ids:
        u = await session.get(User, uid)
        if u:
            out.append(u.telegram_id)
    return out


async def maybe_weekly_rollover(session: AsyncSession) -> list[dict] | None:
    """
    رول‌اور رقابت هفتگی، اگه هفته (ISO) عوض شده باشه:
    به ۳ کارتل اولِ جمع مدال‌های هفته اعضا جایزه میرسه (به بانک کارتل) و امتیاز هفته همه ریست میشه
    خروجی: لیست برنده‌ها [{team, rank, prize, points}] یا None اگه هفته عوض نشده
    نتیجه هفته قبل هم تو game_meta ذخیره میشه تا تو «کارتل لیدربرد» نمایش داده بشه
    """
    wk = current_week_key()
    last = await meta_get(session, "week_key")
    if last == wk:
        return None
    if not last:
        # اولین اجرا، فقط کلید هفته رو ست کن و جایزه‌ای نده
        await meta_set(session, "week_key", wk)
        await session.flush()
        return None

    # رتبه‌بندی بر اساس مدال‌های هفته‌ای که تازه تموم شده (سطل‌های کاربرا هنوز کلید قدیمی دارن)
    scored = await top_teams_by_medals(session, "week", limit=3, week_id=last, include_hidden=True)
    winners = [(t, total) for t, total, _ in scored if total > 0][:3]

    medals_row = {1: "🥇", 2: "🥈", 3: "🥉"}
    out: list[dict] = []
    summary: list[str] = []
    for i, (t, total) in enumerate(winners, 1):
        prize = config.TEAM_WEEKLY_PRIZES.get(i, 0)
        t.bank += prize
        rec = {"team": t, "rank": i, "prize": prize, "points": total}
        out.append(rec)
        summary.append(
            f"{medals_row[i]} «{t.name}» با {fa_num(total)} مدال، {money(prize)} به بانک کارتل"
        )

    await session.execute(update(Team).values(week_points=0))
    await meta_set(session, "week_key", wk)
    # فقط وقتی برنده‌ای داشکارتل نتیجه رو به‌روز کن، نتیجه خالی قهرمانای قبلی رو نپوشونه
    if summary:
        await meta_set(session, "last_week_result", "\n".join(summary))
    await session.flush()
    return out


# ───────── ساختمان‌های کارتل 🏗 ─────────

def building_cost(level: int) -> int:
    """هزینه ارتقا به لول level (۱..۱۰)، جدول رند، گرونه چون همه کارتل جمعش می‌کنن"""
    lv = min(max(level, 1), config.TEAM_BUILDING_MAX_LEVEL)
    return config.TEAM_BUILDING_PRICES[lv - 1]


def atk_bonus(team: Team | None) -> float:
    """ضریب بونس حمله همه اعضا، مثلا ۰٫۰۹ برای ساختمان لول ۳"""
    if not team:
        return 0.0
    return config.TEAM_ATK_BONUS_PER_LEVEL * (team.atk_bld or 0)


def def_bonus(team: Team | None) -> float:
    """ضریب بونس دفاع همه اعضا"""
    if not team:
        return 0.0
    return config.TEAM_DEF_BONUS_PER_LEVEL * (team.def_bld or 0)


async def upgrade_building(session: AsyncSession, user: User, kind: str) -> tuple[bool, str]:
    """
    ارتقای ساختمان توسط رهبر، پولش از بانک کارتل میره
    kind: «atk» ساختمان حمله | «def» ساختمان دفاع
    """
    if kind not in ("atk", "def"):
        return False, "❌ همچین ساختمونی نیس"
    m = await get_membership(session, user.id)
    if not m:
        return False, "🏴 اصلا تو کارتلی نیستی که"
    if m.role != "owner":
        return False, "👑 ارتقای ساختمان فقط با رهبر کارتله"

    team = await session.get(Team, m.team_id)
    if not team:
        return False, "🤷 کارتلی نیس که"

    title = "⚔️ ساختمان حمله" if kind == "atk" else "🛡 ساختمان دفاع"
    level = team.atk_bld if kind == "atk" else team.def_bld
    if level >= config.TEAM_BUILDING_MAX_LEVEL:
        return False, f"⭐ {title} مکس لوله"

    # لول ساختمان نمی‌تونه از لول خود کارتل جلوتر بره
    team_level = team.level or 1
    if level + 1 > team_level:
        return False, (
            f"🔒 ارتقا به لول {fa_num(level + 1)} لول کارتل {fa_num(level + 1)} می‌خواد\n"
            f"الان کارتلتون لول {fa_num(team_level)} ـه، با تجربه اعضا لول کارتل بالا میره"
        )

    cost = building_cost(level + 1)
    if team.bank < cost:
        return False, (
            f"❌ ارتقا {money(cost)} می‌خواد ولی موجودی بانک کارتل {money(team.bank)} ـه\n"
            "اعضا با «کارتل واریز 1200» کمک کنن یا کنده‌کاری کارتلی بزنین"
        )

    team.bank -= cost
    if kind == "atk":
        team.atk_bld += 1
        bonus_pct = int(config.TEAM_ATK_BONUS_PER_LEVEL * team.atk_bld * 100)
        effect = f"+{fa_num(bonus_pct)}% قدرت حمله همه اعضا"
    else:
        team.def_bld += 1
        bonus_pct = int(config.TEAM_DEF_BONUS_PER_LEVEL * team.def_bld * 100)
        effect = f"+{fa_num(bonus_pct)}% دفاع همه اعضا"

    new_level = team.atk_bld if kind == "atk" else team.def_bld
    return True, f"🏗 {title} رفت رو لول {fa_num(new_level)}، {effect}"


async def toggle_hidden(session: AsyncSession, user: User, team_name: str | None = None) -> tuple[bool, str]:
    """«کارتل مخفی» فقط دست ادمینه، با اسم هر کارتلی و بدون اسم کارتل خود ادمین (دوباره بزنی برمی‌گرده)"""
    if team_name:
        team = await get_team_by_name(session, team_name)
        if not team:
            return False, f"❌ کارتلی به اسم «{team_name}» پیدا نکردم"
    else:
        team = await get_team_of(session, user.id)
        if not team:
            return False, "🏴 خودت تو کارتلی نیستی، با اسم بزن: «کارتل مخفی [اسم کارتل]»"
    team.lb_hidden = 0 if team.lb_hidden else 1
    if team.lb_hidden:
        return True, (
            f"👻 کارتل «{team.name}» نامرئی شد\n\n"
            "دیگه تو لیدربردهای کارتل دیده نمیشه\n"
            "برای برگشت دوباره «کارتل مخفی» رو بزن"
        )
    return True, f"👀 کارتل «{team.name}» برگشت تو لیدربردها"


async def team_deposit(session: AsyncSession, user: User, amount: int) -> tuple[bool, str]:
    """واریز کمک مالی عضو به بانک کارتل، «کارتل واریز 1200»"""
    if amount <= 0:
        return False, "❌ مبلغو درست بگو، مثلا «کارتل واریز 1200»"
    team = await get_team_of(session, user.id)
    if not team:
        return False, "🏴 تو کارتلی نیستی که بخوای بهش کمک کنی"
    if user.cash < amount:
        return False, f"❌ این همه پول نقد نداری، جیبت {money(user.cash)} داری"
    user.cash -= amount
    team.bank += amount
    return True, f"🏦 {money(amount)} به بانک کارتل «{team.name}» واریز شد، دستت درد نکنه رفیق 🙏"


# ═════════ چت داخلی کارتل 💬 (راند ۲۰، درخواست کارفرما) ═════════

_ROLE_EMOJI = {"owner": "👑", "admin": "⭐"}
_ROLE_FA = {"owner": "رهبر", "admin": "ادمین"}


async def chat_post(session: AsyncSession, user, text: str) -> tuple[bool, str]:
    """فرستادن پیام به چت کارتل | فقط اعضا، متن سقف ۳۰۰ کاراکتر، فقط آخرین N پیام نگه‌داشته میشه"""
    from models import TeamChatMessage
    from sqlalchemy import delete as sql_delete

    m = await get_membership(session, user.id)
    if not m:
        return False, "🏴 اصلا تو کارتلی نیستی که"
    text = (text or "").strip()
    if not text:
        return False, "✉️ یه چیزی بنویس تا تو چت بفرستم"
    text = text[:300]
    from services import users as users_svc
    session.add(TeamChatMessage(
        team_id=m.team_id, user_tg=user.telegram_id,
        name=users_svc.display_name(user)[:60], role=m.role or "member", text=text,
    ))
    await session.flush()
    keep = list((await session.execute(
        select(TeamChatMessage.id).where(TeamChatMessage.team_id == m.team_id)
        .order_by(TeamChatMessage.id.desc()).limit(config.TEAM_CHAT_HISTORY)
    )).scalars())
    if keep:
        await session.execute(
            sql_delete(TeamChatMessage).where(
                TeamChatMessage.team_id == m.team_id, TeamChatMessage.id.notin_(keep)
            )
        )
    return True, "به چت کارتل رفت"


async def chat_page(session: AsyncSession, team) -> str:
    """متن صفحه چت کارتل: آخرین پیام‌ها با ایموجی نقش فرستنده (راند ۲۰)"""
    from models import TeamChatMessage
    from utils import esc

    rows = list((await session.execute(
        select(TeamChatMessage).where(TeamChatMessage.team_id == team.id)
        .order_by(TeamChatMessage.id.desc()).limit(config.TEAM_CHAT_HISTORY)
    )).scalars())
    rows.reverse()  # از قدیمی به جدید مثل چت واقعی
    lines = [f"<b>💬 چت کارتل «{esc(team.name)}»</b>", ""]
    if not rows:
        lines.append("هنوز حرفی زده نشده، اولین نفر باش 🎤")
    for r in rows:
        role = r.role or "member"
        em = _ROLE_EMOJI.get(role, "👤")
        tag = f"({_ROLE_FA.get(role)})" if role in _ROLE_FA else ""
        lines.append(f"{em}‌ {esc(r.name)}{tag}: {esc(r.text)}")
    lines += ["", "✉️ برای فرستادن پیام دکمه «ارسال پیام» رو بزن"]
    return "\n".join(lines)
