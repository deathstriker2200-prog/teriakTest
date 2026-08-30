"""
جنگ کارتل‌ها ⚔️🏴 — جنگ کارتل به کارتل با حمله‌های پیاپی اعضا

جریان جدید: صف داوطلبانه دو رهبر → مچ تصادفی → scheduled (بدون قبول/رد) → active → finished.
وضعیت pending و قبول/رد فقط برای درخواست‌های قدیمیِ ساخته‌شده پیش از این تغییر نگه داشته شده‌اند.

قوانین کلیدی:
- فقط رهبر (owner) می‌تواند کارتل را وارد صف یا از آن خارج کند
- هر کارتل هر روز حداکثر CARTEL_WAR_DAILY_LIMIT تا وار قبول‌شده/انجام‌شده (pending_war_id قفلش می‌کنه)
- پیش‌نیاز ورود به جنگ (هم مهاجم هم مدافع): لول کارتل ≥ CARTEL_WAR_MIN_TEAM_LEVEL و سابقه ≥ CARTEL_WAR_MIN_TEAM_AGE_DAYS روز از تأسیس
- حمله وار کاملاً جدا از پی‌وی عادیه: بدون سپر | بدون انتقام | بدون زندان | بدون جاسوسی | کولدان شخصی مستقل
- هدف هر دور تصادفیه و قفله (اسم هر بار ظاهر شد عوض نمیشه)، تا حمله نکنی نمی‌تونی هدف دیگه بگیری؛ دور بعد (بعد کول‌دان) خودکار هدف تازه میاد
- برد/باخت حمله دقیقاً طبق همون قانون حمله پی‌وی کلاسیکه (pvattack.total_powers/decide_win): قدرت کل رقابتی، رول شانسی فقط تو بازه نزدیک
- برد: امتیاز نبرد (رنج کوچیک رندوم) میره برای کارتل خودِ مهاجم | باخت: امتیاز نبرد کم‌تر میره برای کارتل مدافع (پاداش دفاع موفق)
- «امتیاز نبرد» (war.attacker_xp/defender_xp) فقط برای همین وار و تعیین برنده‌ست؛ ربطی به تجربه‌ی لول کارتل (Team.xp) یا تجربه‌ی شخصی بازیکن (User.xp) نداره
- عضوی که کمتر از CARTEL_WAR_MIN_MEMBERSHIP_HOURS ساعته عضو کارتله نمی‌تونه بجنگه (چک هر بار قبل از حمله، حتی تو گروه)، و اگه وسط وار از کارتل خارج بشه دیگه اجازه حمله نداره
- همه ثبت‌ها با لاگ (WarAttackLog) و Unique Constraint کولدان، از شمارش دوبل جلوگیری می‌کنن
"""

import logging
import random
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import CartelWar, CartelWarQueue, Team, TeamMember, User, WarAttackCooldown, WarAttackLog
from services import economy, pvattack
from services import combat as combat_svc
from services import teams as team_svc
from services import users as user_svc
from utils import fa_num, iran_today, money, now_utc

logger = logging.getLogger("teriaky.cartelwar")

WarStatus = (
    "pending", "rejected", "expired", "scheduled", "active", "finished", "cancelled",
)


# ───────── بررسی‌های شروع وار ─────────

def team_war_requirements_met(team: Team) -> bool:
    """پیش‌نیاز ورود به جنگ (هم مهاجم هم مدافع): لول کارتل و سابقه تأسیس کافی باشه"""
    if (team.level or 1) < config.CARTEL_WAR_MIN_TEAM_LEVEL:
        return False
    if not team.created_at:
        return False
    age_days = (now_utc() - team.created_at).total_seconds() / 86400
    return age_days >= config.CARTEL_WAR_MIN_TEAM_AGE_DAYS


def _requirements_block() -> str:
    return (
        f"📋 نیازمندی:\n"
        f"⭐ کارتل سطح {fa_num(config.CARTEL_WAR_MIN_TEAM_LEVEL)}\n"
        f"⏳ حداقل {fa_num(config.CARTEL_WAR_MIN_TEAM_AGE_DAYS)} روز سابقه فعالیت"
    )


def not_eligible_target_text() -> str:
    """برای رهبر مهاجمی که می‌خواد به یه کارتل تازه‌کار وار بده"""
    return (
        f"🚫 <b>درخواست جنگ ارسال نشد</b>\n\n"
        f"🏴 این کارتل هنوز تازه‌تأسیسه و شرایط لازم برای شرکت در جنگ رو نداره\n\n"
        f"{_requirements_block()}\n\n"
        f"بعد از رسیدن به شرایط لازم، می‌تونید درخواست جنگ ارسال کنید ⚔️"
    )


def not_eligible_own_text() -> str:
    """برای رهبر کارتل تازه‌کار که خودش می‌خواد وار بفرسته"""
    return (
        f"🚫 <b>کارتل تو هنوز تازه‌تأسیسه</b>\n\n"
        f"برای ورود به جنگ‌های کارتل باید اول قوی‌تر بشی و تجربه بیشتری کسب کنی\n\n"
        f"📋 نیازمندی ورود به جنگ:\n"
        f"⭐ کارتل سطح {fa_num(config.CARTEL_WAR_MIN_TEAM_LEVEL)}\n"
        f"⏳ حداقل {fa_num(config.CARTEL_WAR_MIN_TEAM_AGE_DAYS)} روز سابقه فعالیت\n\n"
        f"بعد از رسیدن به این شرایط، می‌تونی وارد نبردهای کارتل‌ها بشی ⚔️"
    )


async def can_start_war(session: AsyncSession, attacker_team: Team) -> tuple[bool, str]:
    """رهبر کارتل مهاجم می‌تونه الان وار جدید بفرسته؟"""
    if not team_war_requirements_met(attacker_team):
        return False, not_eligible_own_text()

    if attacker_team.pending_war_id:
        war = await session.get(CartelWar, attacker_team.pending_war_id)
        logger.warning(
            "can_start_war: team_id=%s pending_war_id=%s war_found=%s war_status=%s",
            attacker_team.id, attacker_team.pending_war_id, bool(war), war.status if war else None,
        )
        if war and war.status in ("pending", "scheduled", "active"):
            return False, "🚫 <b>یه جنگ دیگه در جریانه</b>\n\nکارتلت الان یه جنگ فعال یا در انتظار داره، اول اونو تموم کن"
        # وار قدیمی تموم شده ولی قفل پاک نشده، خودمون پاکش می‌کنیم
        attacker_team.pending_war_id = None

    today = iran_today()
    if attacker_team.war_day == today and (attacker_team.daily_war_count or 0) >= config.CARTEL_WAR_DAILY_LIMIT:
        return False, (
            f"🚫 <b>سهمیه امروز تموم شده</b>\n\n"
            f"🏴 امروز {fa_num(config.CARTEL_WAR_DAILY_LIMIT)} جنگ بین‌کارتلی داشتید\n\n"
            f"⏳ فردا دوباره می‌تونید وارد جنگ بشید"
        )
    return True, ""


async def random_queue_row(session: AsyncSession, team_id: int) -> CartelWarQueue | None:
    return (await session.execute(select(CartelWarQueue).where(
        CartelWarQueue.team_id == team_id
    ))).scalar_one_or_none()


async def leave_random_queue(session: AsyncSession, team_id: int) -> bool:
    result = await session.execute(delete(CartelWarQueue).where(CartelWarQueue.team_id == team_id))
    return bool(result.rowcount)


async def join_random_queue(session: AsyncSession, leader: User, team: Team) -> dict:
    """ورود به صف داوطلبانه و مچ تصادفی دو کارتل آماده؛ پس از مچ قبول/رد وجود ندارد."""
    ok, error = await can_start_war(session, team)
    if not ok:
        await leave_random_queue(session, team.id)
        return {"status": "blocked", "message": error}

    mine = await random_queue_row(session, team.id)
    if mine is None:
        mine = CartelWarQueue(team_id=team.id, leader_id=leader.id)
        session.add(mine)
        await session.flush()

    queued = list((await session.execute(
        select(CartelWarQueue).where(CartelWarQueue.team_id != team.id).with_for_update()
    )).scalars())
    candidates: list[tuple[CartelWarQueue, Team, int]] = []
    stale_ids: list[int] = []
    my_members = await team_svc.member_count(session, team.id)
    for row in queued:
        other = await session.get(Team, row.team_id)
        if other is None or other.owner_id != row.leader_id:
            stale_ids.append(row.id)
            continue
        other_ok, _ = await can_start_war(session, other)
        if not other_ok:
            stale_ids.append(row.id)
            continue
        candidates.append((row, other, await team_svc.member_count(session, other.id)))
    if stale_ids:
        await session.execute(delete(CartelWarQueue).where(CartelWarQueue.id.in_(stale_ids)))

    if not candidates:
        return {"status": "queued", "queue_id": mine.id}

    # اولویت با لول نزدیک و اختلاف حداکثر پنج عضو است؛ داخل گروه مناسب انتخاب تصادفی می‌ماند.
    close = [pair for pair in candidates
             if abs((pair[1].level or 1) - (team.level or 1)) <= 3
             and abs(pair[2] - my_members) <= 5]
    level_close = [pair for pair in candidates if abs((pair[1].level or 1) - (team.level or 1)) <= 3]
    pool = close or level_close or candidates
    other_row, other, _ = random.choice(pool)

    now = now_utc()
    war = CartelWar(
        attacker_cartel_id=team.id,
        defender_cartel_id=other.id,
        attacker_leader_id=leader.id,
        defender_leader_id=other.owner_id,
        status="pending",
        expires_at=now + timedelta(seconds=config.CARTEL_WAR_PREP_SECONDS),
    )
    session.add(war)
    await session.flush()
    team.pending_war_id = war.id
    other.pending_war_id = war.id
    await accept_war(session, war)  # مستقیم scheduled؛ مرحله قبول/رد حذف شده
    await session.delete(mine)
    await session.delete(other_row)
    return {"status": "matched", "war": war, "attacker": team, "defender": other}


async def start_war(session: AsyncSession, attacker_user: User, attacker_team: Team,
                     defender_team: Team) -> tuple[bool, str, CartelWar | None]:
    """ساخت درخواست وار جدید (وضعیت pending)، خروجی: (موفق, پیام خطا/موفقیت, شیء وار)"""
    if defender_team.id == attacker_team.id:
        return False, "🚫 <b>اینجوری نمیشه</b>\n\nنمی‌تونی به کارتل خودت درخواست وار بدی", None

    ok, err = await can_start_war(session, attacker_team)
    if not ok:
        return False, err, None

    if not team_war_requirements_met(defender_team):
        return False, not_eligible_target_text(), None

    if defender_team.pending_war_id:
        dwar = await session.get(CartelWar, defender_team.pending_war_id)
        if dwar and dwar.status in ("pending", "scheduled", "active"):
            return False, "🚫 <b>حریف درگیره</b>\n\nاون کارتل الان تو یه جنگ دیگه‌ست", None

    war = CartelWar(
        attacker_cartel_id=attacker_team.id,
        defender_cartel_id=defender_team.id,
        attacker_leader_id=attacker_user.id,
        defender_leader_id=defender_team.owner_id,
        status="pending",
        expires_at=now_utc() + timedelta(seconds=config.CARTEL_WAR_REQUEST_TIMEOUT_SECONDS),
    )
    session.add(war)
    await session.flush()  # war.id لازم داریم

    attacker_team.pending_war_id = war.id
    defender_team.pending_war_id = war.id
    return True, "", war


# ───────── پاسخ به درخواست ─────────

async def reject_war(session: AsyncSession, war: CartelWar) -> None:
    """رد درخواست — سهمیه روزانه مصرف نمیشه، هر دو قفل آزاد میشن"""
    war.status = "rejected"
    await _clear_pending(session, war)


async def expire_war(session: AsyncSession, war: CartelWar) -> None:
    """انقضای بی‌پاسخی — سهمیه مصرف نمیشه"""
    war.status = "expired"
    await _clear_pending(session, war)


async def accept_war(session: AsyncSession, war: CartelWar) -> None:
    """پذیرش — سهمیه روزانه هر دو کارتل مصرف میشه، CARTEL_WAR_PREP_SECONDS دیگه شروع میشه"""
    now = now_utc()
    war.status = "scheduled"
    war.accepted_at = now
    war.starts_at = now + timedelta(seconds=config.CARTEL_WAR_PREP_SECONDS)

    today = iran_today()
    for team_id in (war.attacker_cartel_id, war.defender_cartel_id):
        team = await session.get(Team, team_id)
        if team:
            if team.war_day != today:
                team.daily_war_count = 0
            team.war_day = today
            team.daily_war_count = (team.daily_war_count or 0) + 1


async def _clear_pending(session: AsyncSession, war: CartelWar) -> None:
    for team_id in (war.attacker_cartel_id, war.defender_cartel_id):
        team = await session.get(Team, team_id)
        if team and team.pending_war_id == war.id:
            team.pending_war_id = None


# ───────── فعال‌سازی و پایان ─────────

async def activate_war(session: AsyncSession, war: CartelWar) -> None:
    """scheduled → active، مدت CARTEL_WAR_DURATION_SECONDS شروع میشه"""
    now = now_utc()
    war.status = "active"
    war.ends_at = now + timedelta(seconds=config.CARTEL_WAR_DURATION_SECONDS)


async def finish_war(session: AsyncSession, war: CartelWar) -> dict:
    """
    active → finished، برنده تعیین و پاداش‌ها اعمال میشه
    خروجی: دیکشنری خلاصه برای ساخت پیام پایان (به هندلر/جاب برمی‌گرده)
    """
    war.status = "finished"

    a_team = await session.get(Team, war.attacker_cartel_id)
    d_team = await session.get(Team, war.defender_cartel_id)

    winner_team, loser_team, draw = _resolve_winner_teams(war, a_team, d_team)

    for t in (a_team, d_team):
        if t:
            t.total_wars = (t.total_wars or 0) + 1
            if t.pending_war_id == war.id:
                t.pending_war_id = None

    if draw or winner_team is None:
        war.winner_cartel_id = None
    else:
        war.winner_cartel_id = winner_team.id
        winner_team.war_wins = (winner_team.war_wins or 0) + 1
        winner_team.war_trophies = (winner_team.war_trophies or 0) + 1
        if loser_team:
            loser_team.war_losses = (loser_team.war_losses or 0) + 1

        members = await team_svc.get_members(session, winner_team.id)
        for m in members:
            u = await session.get(User, m.user_id)
            if not u:
                continue
            u.cash = (u.cash or 0) + config.CARTEL_WAR_WIN_TP
            u.war_medals = (u.war_medals or 0) + config.CARTEL_WAR_WIN_MEDALS
            u.war_wins = (u.war_wins or 0) + 1
            winner_team.war_medals_total = (winner_team.war_medals_total or 0) + config.CARTEL_WAR_WIN_MEDALS
            user_svc.add_xp(u, config.CARTEL_WAR_WIN_USER_XP)  # سینکه، لول‌آپ رو خودش رو یوزر اعمال می‌کنه
        await team_svc.apply_team_xp(session, winner_team, config.CARTEL_WAR_WIN_TEAM_XP)

    return {
        "war": war,
        "attacker_team": a_team,
        "defender_team": d_team,
        "winner_team": winner_team,
        "loser_team": loser_team,
        "draw": draw,
    }


def _resolve_winner_teams(war: CartelWar, a_team: Team | None, d_team: Team | None) -> tuple[Team | None, Team | None, bool]:
    """
    برنده با War XP بیشتر؛ تساوی → حملات موفق بیشتر → شرکت‌کنندگان فعال بیشتر → draw
    خروجی: (کارتل برنده, کارتل بازنده, مساوی؟)
    """
    a_xp, d_xp = war.attacker_xp or 0, war.defender_xp or 0
    a_hits, d_hits = war.attacker_success_hits or 0, war.defender_success_hits or 0
    a_p, d_p = war.attacker_participants or 0, war.defender_participants or 0

    if a_xp != d_xp:
        return (a_team, d_team, False) if a_xp > d_xp else (d_team, a_team, False)
    if a_hits != d_hits:
        return (a_team, d_team, False) if a_hits > d_hits else (d_team, a_team, False)
    if a_p != d_p:
        return (a_team, d_team, False) if a_p > d_p else (d_team, a_team, False)
    return None, None, True


# ───────── شرکت‌پذیری اعضا ─────────

async def can_fight(session: AsyncSession, user: User, war: CartelWar) -> tuple[bool, str]:
    """آیا این کاربر می‌تونه تو این وار مشخص حمله کنه؟"""
    membership = await team_svc.get_membership(session, user.id)
    if not membership:
        return False, "🚫 دیگه عضو هیچ کارتلی نیستی"
    if membership.team_id not in (war.attacker_cartel_id, war.defender_cartel_id):
        return False, "🚫 کارتلت تو این جنگ نیست"
    joined_hours = (now_utc() - membership.joined_at).total_seconds() / 3600
    if joined_hours < config.CARTEL_WAR_MIN_MEMBERSHIP_HOURS:
        left_h = config.CARTEL_WAR_MIN_MEMBERSHIP_HOURS - joined_hours
        return False, f"🚫 هنوز {fa_num(round(left_h, 1))} ساعت مونده تا بتونی تو وار کارتلت شرکت کنی"
    return True, ""


def my_side_and_enemy(war: CartelWar, my_team_id: int) -> tuple[str, int] | None:
    """('attacker'|'defender', enemy_team_id) یا None اگه عضو هیچ‌کدوم نبود"""
    if my_team_id == war.attacker_cartel_id:
        return "attacker", war.defender_cartel_id
    if my_team_id == war.defender_cartel_id:
        return "defender", war.attacker_cartel_id
    return None


# ───────── کول‌دان حمله وار (مستقل از پی‌وی) ─────────

async def cooldown_left(session: AsyncSession, user_id: int, war_id: int) -> int:
    """ثانیه مونده تا حمله بعدی وار، صفر یعنی آماده‌ست"""
    q = select(WarAttackCooldown).where(
        WarAttackCooldown.user_id == user_id, WarAttackCooldown.war_id == war_id)
    row = (await session.execute(q)).scalar_one_or_none()
    if not row:
        return 0
    end = row.last_attack_at + timedelta(seconds=config.CARTEL_WAR_ATTACK_COOLDOWN_SECONDS)
    return max(0, int((end - now_utc()).total_seconds()))


async def _touch_cooldown(session: AsyncSession, user_id: int, war_id: int) -> None:
    q = select(WarAttackCooldown).where(
        WarAttackCooldown.user_id == user_id, WarAttackCooldown.war_id == war_id)
    row = (await session.execute(q)).scalar_one_or_none()
    now = now_utc()
    if row:
        row.last_attack_at = now
    else:
        session.add(WarAttackCooldown(user_id=user_id, war_id=war_id, last_attack_at=now))


# ───────── هدف قفل‌شده هر دور (بدون قابلیت تغییر — درخواست کارفرما) ─────────
# هر کاربر تو یه دور کول‌دان فقط یه هدف رندوم داره؛ با هر بار باز کردن پنل عوض نمیشه، فقط با حمله واقعی خالی و برای دور بعد از نو رندوم میشه

async def get_locked_target(session: AsyncSession, user_id: int, war_id: int) -> User | None:
    """هدف قفل‌شده‌ی این دور، اگه هنوز عضو معتبر کارتل حریفه؛ وگرنه None (باید هدف تازه گرفته بشه)"""
    q = select(WarAttackCooldown).where(
        WarAttackCooldown.user_id == user_id, WarAttackCooldown.war_id == war_id)
    row = (await session.execute(q)).scalar_one_or_none()
    if not row or not row.assigned_target_id:
        return None
    target = await session.get(User, row.assigned_target_id)
    if not target:
        return None
    tm = await team_svc.get_membership(session, target.id)
    if not tm:
        return None
    return target


async def _set_locked_target(session: AsyncSession, user_id: int, war_id: int, target_id: int | None) -> None:
    q = select(WarAttackCooldown).where(
        WarAttackCooldown.user_id == user_id, WarAttackCooldown.war_id == war_id)
    row = (await session.execute(q)).scalar_one_or_none()
    if row:
        row.assigned_target_id = target_id
    else:
        # این ردیف فقط برای قفل کردن هدفه، نه یه حمله واقعی — last_attack_at نباید «الان» باشه
        # وگرنه باگ می‌شه: با اولین باز کردن پیش‌نمایش (بدون زدن دکمه حمله) کول‌دان کاذب شروع میشه
        far_past = now_utc() - timedelta(seconds=config.CARTEL_WAR_ATTACK_COOLDOWN_SECONDS + 1)
        session.add(WarAttackCooldown(user_id=user_id, war_id=war_id, last_attack_at=far_past, assigned_target_id=target_id))


async def assign_or_get_target(session: AsyncSession, user_id: int, war_id: int, enemy_team_id: int) -> User | None:
    """هدف این دور رو برمی‌گردونه: اگه از قبل قفل شده همون رو، وگرنه یه هدف تصادفی تازه انتخاب و قفل می‌کنه"""
    locked = await get_locked_target(session, user_id, war_id)
    if locked:
        return locked
    target = await pick_random_target(session, enemy_team_id)
    if target:
        await _set_locked_target(session, user_id, war_id, target.id)
    return target


# ───────── انتخاب هدف ─────────

async def pick_random_target(session: AsyncSession, enemy_team_id: int) -> User | None:
    """یه عضو تصادفی کارتل حریف؛ آفلاین‌ها هم واجدن، فقط باید هنوز واقعاً عضو باشن"""
    q = select(TeamMember.user_id).where(TeamMember.team_id == enemy_team_id)
    ids = [row[0] for row in (await session.execute(q)).all()]
    if not ids:
        return None
    target_id = random.choice(ids)
    return await session.get(User, target_id)


# ───────── حمله وار ─────────


async def attack(session: AsyncSession, attacker: User, war: CartelWar) -> dict:
    """
    یه حمله وار کامل: کولدان چک، هدف این دور (قفل‌شده یا تازه رندوم)، محاسبه نبرد طبق همون قاعده حمله پی‌وی
    (قدرت مهاجم/دفاع هدف، رول رندوم فقط تو بازه نزدیک)، ثبت لاگ و امتیاز نبرد/مدال/تی‌پوینت، آزاد کردن هدف برای دور بعد
    برد: امتیاز نبرد به کارتل خودِ مهاجم | باخت: امتیاز نبرد کم به کارتل مدافع (پاداش دفاع موفق) — بدون سپر و بدون جاسوسی
    خروجی دیکشنری: {ok, message, target, success, score_gained, medals_gained}
    """
    membership = await team_svc.get_membership(session, attacker.id)
    if not membership:
        return {"ok": False, "message": "🚫 دیگه عضو هیچ کارتلی نیستی"}

    side = my_side_and_enemy(war, membership.team_id)
    if side is None:
        return {"ok": False, "message": "🚫 کارتلت تو این جنگ نیست"}
    my_side, enemy_team_id = side

    fit_ok, fit_err = await can_fight(session, attacker, war)
    if not fit_ok:
        return {"ok": False, "message": fit_err}

    cd = await cooldown_left(session, attacker.id, war.id)
    if cd:
        return {"ok": False, "message": f"⏳ {fa_num(cd)} ثانیه دیگه می‌تونی دوباره حمله کنی", "cooldown": cd}

    # هدف این دور همون هدف قفل‌شده‌ست؛ قابلیت تغییرش نیست (درخواست کارفرما)
    target = await assign_or_get_target(session, attacker.id, war.id, enemy_team_id)
    if target is None:
        return {"ok": False, "message": "😴 هیچ عضوی تو کارتل حریف پیدا نشد"}
    if target.id == attacker.id:
        return {"ok": False, "message": "😅 هدف خودت شدی، یکی دیگه رو انتخاب کن"}

    # همون قاعده‌ی حمله پی‌وی: «قدرت کل» رقابتی، رول شانسی فقط تو بازه نزدیک، بدون سپر و بدون جاسوسی
    a_total, t_total, battle_info = await pvattack.total_powers(session, attacker, target)
    success = pvattack.decide_win(a_total, t_total)

    # تفنگ این حمله یک تیر مصرف می‌کند؛ سم/سرکوب و استهلاک زره روی بازیکن واقعی می‌مانند.
    ability_note = ""
    mimic_key = battle_info.get("mimic_armor_key")
    if mimic_key:
        ability_note += f"\n🎭 هزارچهره قدرت {config.ARMORS[mimic_key]['name']} رو گرفت"
    wear = await user_svc.damage_armor(session, target, battle_info.get("target_armor_key"))
    if wear and wear["loss"]:
        ability_note += (f"\n🛡 دوام زره هدف {fa_num(wear['loss'])} تا کم شد؛ "
                         f"{fa_num(wear['current'])}/{fa_num(wear['maximum'])}")
        if wear["broken"]:
            ability_note += "\n💔 زره هدف شکست و از تنش دراومد"
    a_levels = await user_svc.get_item_levels(session, attacker.id)
    a_ammo = await user_svc.get_ammo_map(session, attacker.id)
    wkey = combat_svc.weapon_choice(attacker, a_levels, a_ammo)
    if wkey and combat_svc.is_gun(wkey):
        await user_svc.consume_ammo(session, attacker.id, wkey)
    wabil = (config.WEAPONS.get(wkey) or {}).get("ability") if wkey else None
    wlvl = a_levels.get(wkey, 1) if wkey else 1
    if wabil and wabil.get("kind") == "poison" and random.random() < economy.gear_ability_value(wabil, "chance", wlvl):
        target.poison_until = now_utc() + timedelta(seconds=int(wabil.get("seconds", 600)))
        ability_note += "\n💀 قابلیت تفنگ: حریف مسموم شد"
    elif wabil and wabil.get("kind") == "suppress" and random.random() < economy.gear_ability_value(wabil, "chance", wlvl):
        target.suppressed_until = now_utc() + timedelta(seconds=int(wabil.get("seconds", 300)))
        ability_note += "\n🔻 قابلیت تفنگ: حمله حریف 5 دقیقه سرکوب شد"

    medals_gain = config.CARTEL_WAR_HIT_MEDALS if success else config.CARTEL_WAR_MISS_MEDALS
    tp_gain = config.CARTEL_WAR_HIT_TP if success else 0

    if success:
        # برد: امتیاز نبرد به کارتل خودِ مهاجم، تو یه بازه کوچیک رندومه که فارم یکنواخت نشه
        score_gain = random.randint(config.CARTEL_WAR_HIT_SCORE_MIN, config.CARTEL_WAR_HIT_SCORE_MAX)
        score_side = my_side
    else:
        # باخت: امتیاز کمی (پاداش دفاع موفق) میره برای کارتل مدافع، نه مهاجم
        score_gain = random.randint(config.CARTEL_WAR_DEFENSE_SCORE_MIN, config.CARTEL_WAR_DEFENSE_SCORE_MAX)
        score_side = "defender" if my_side == "attacker" else "attacker"

    # ضریب بالانس تیم کوچک‌تر روی امتیازیه که همون دور بهش می‌خوره سوار میشه
    balance_mult = await _balance_multiplier(session, war, score_side)
    score_gain_scaled = int(round(score_gain * balance_mult))

    if score_side == "attacker":
        war.attacker_xp = (war.attacker_xp or 0) + score_gain_scaled
    else:
        war.defender_xp = (war.defender_xp or 0) + score_gain_scaled
    if success:
        if my_side == "attacker":
            war.attacker_success_hits = (war.attacker_success_hits or 0) + 1
        else:
            war.defender_success_hits = (war.defender_success_hits or 0) + 1

    attacker.war_medals = (attacker.war_medals or 0) + medals_gain
    attacker.war_attacks = (attacker.war_attacks or 0) + 1
    if tp_gain:
        attacker.cash = (attacker.cash or 0) + tp_gain

    session.add(WarAttackLog(
        war_id=war.id, attacker_id=attacker.id, defender_id=target.id,
        success=success, xp_gained=score_gain_scaled, medals_gained=medals_gain,
    ))
    await _touch_cooldown(session, attacker.id, war.id)
    await _set_locked_target(session, attacker.id, war.id, None)  # هدف این دور تموم شد، دور بعد از نو رندوم میشه

    return {
        "ok": True,
        "success": success,
        "target": target,
        "score_gained": score_gain_scaled,
        "medals_gained": medals_gain,
        "tp_gained": tp_gain,
        "message": _attack_result_text(success, target, score_gain_scaled, medals_gain, tp_gain) + ability_note,
    }


async def _balance_multiplier(session: AsyncSession, war: CartelWar, my_side: str) -> float:
    """ضریب بالانس تیم کوچک‌تر بر اساس اختلاف تعداد اعضای شرکت‌کننده (کسانی که حداقل یه لاگ حمله دارن)"""
    a_n = await _participant_count(session, war.id, war.attacker_cartel_id)
    d_n = await _participant_count(session, war.id, war.defender_cartel_id)
    war.attacker_participants, war.defender_participants = a_n, d_n

    my_n = a_n if my_side == "attacker" else d_n
    other_n = d_n if my_side == "attacker" else a_n
    if my_n >= other_n:
        return 1.0
    diff = other_n - my_n
    for cap, mult in config.CARTEL_WAR_BALANCE_TABLE:
        if diff <= cap:
            return mult
    return config.CARTEL_WAR_BALANCE_TABLE[-1][1]


async def _participant_count(session: AsyncSession, war_id: int, team_id: int) -> int:
    """چند نفر از این کارتل تو این وار حداقل یه حمله ثبت کردن"""
    q = select(WarAttackLog.attacker_id).join(
        TeamMember, TeamMember.user_id == WarAttackLog.attacker_id
    ).where(WarAttackLog.war_id == war_id, TeamMember.team_id == team_id).distinct()
    return len((await session.execute(q)).all())


def _attack_result_text(success: bool, target: User, score: int, medals: int, tp: int) -> str:
    from services.users import display_name
    name = display_name(target)
    if success:
        return (
            f"🔥 <b>حمله موفق بود</b>\n\n"
            f"🎯 هدف: {name}\n\n"
            f"🛡️ دفاع حریف جلوی حمله‌ت کم آورد، امتیاز نبرد به کارتلت رسید\n\n"
            f"⭐ +{fa_num(score)} امتیاز نبرد برای کارتل\n"
            f"🎖 +{fa_num(medals)} مدال جنگ\n"
            f"💰 +{money(tp)}"
        )
    # حمله ناموفق: دفاع هدف قوی‌تر بود، امتیاز نبرد (کم) به کارتل خودِ هدف می‌خوره، نه کارتل مهاجم
    return (
        f"🛡️ <b>حمله ناموفق بود</b>\n\n"
        f"🎯 هدف: {name}\n\n"
        f"⚔️ حمله‌ات نتونست سوراخی توی دفاع حریف پیدا کنه\n"
        f"⭐ +{fa_num(score)} امتیاز نبرد برای کارتل حریف بابت دفاع موفق\n"
        f"🎖️ +{fa_num(medals)} مدال جنگ بابت تلاش"
    )


# ───────── متن‌ها و آمار نمایشی ─────────

def win_rate(team: Team) -> float:
    total = team.total_wars or 0
    if total <= 0:
        return 0.0
    return round((team.war_wins or 0) / total * 100, 1)


async def war_panel_data(session: AsyncSession, war: CartelWar) -> dict:
    a_team = await session.get(Team, war.attacker_cartel_id)
    d_team = await session.get(Team, war.defender_cartel_id)
    left = max(0, int(((war.ends_at or now_utc()) - now_utc()).total_seconds())) if war.ends_at else 0
    return {
        "war": war, "attacker_team": a_team, "defender_team": d_team,
        "seconds_left": left,
    }


