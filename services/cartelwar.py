"""
جنگ کارتل‌ها ⚔️🏴 — جنگ کارتل به کارتل با حمله‌های پیاپی اعضا

جریان: pending (رهبر هدف پاسخ میده، مهلت ۱ ساعت) → scheduled (پذیرفته، ۳۰ دقیقه آماده‌سازی)
       → active (۶ ساعت، اعضا حمله می‌کنن) → finished (برنده با War XP بیشتر مشخص میشه)
       رد یا بی‌پاسخی: rejected / expired

قوانین کلیدی (درخواست کارفرما):
- فقط رهبر (owner) کارتل می‌تونه وار بفرسته یا قبول/رد کنه
- هر کارتل هر روز حداکثر CARTEL_WAR_DAILY_LIMIT تا وار قبول‌شده/انجام‌شده (pending_war_id قفلش می‌کنه)
- حمله وار کاملاً جدا از پی‌وی عادیه: بدون سپر | بدون انتقام | بدون زندان | کولدان شخصی ۵ دقیقه‌ای مستقل
- عضوی که کمتر از ۲۴ ساعته عضو کارتله نمی‌تونه بجنگه، و اگه وسط وار از کارتل خارج بشه دیگه اجازه حمله نداره
- XP و مدال حمله ثابته (بدون رندوم اضافه) که فارم بی‌نهایت ممکن نباشه؛ نتیجه حمله (برد/باخت) رندوم رقابتیه
- همه ثبت‌ها با لاگ (WarAttackLog) و Unique Constraint کولدان، از شمارش دوبل جلوگیری می‌کنن
"""

import logging
import random
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import CartelWar, Team, TeamMember, User, WarAttackCooldown, WarAttackLog
from services import combat
from services import dogs as dog_svc
from services import teams as team_svc
from services import users as user_svc
from utils import fa_num, iran_today, money, now_utc

logger = logging.getLogger("teriaky.cartelwar")

WarStatus = (
    "pending", "rejected", "expired", "scheduled", "active", "finished", "cancelled",
)


# ───────── بررسی‌های شروع وار ─────────

async def can_start_war(session: AsyncSession, attacker_team: Team) -> tuple[bool, str]:
    """رهبر کارتل مهاجم می‌تونه الان وار جدید بفرسته؟"""
    if attacker_team.pending_war_id:
        war = await session.get(CartelWar, attacker_team.pending_war_id)
        logger.warning(
            "can_start_war: team_id=%s pending_war_id=%s war_found=%s war_status=%s",
            attacker_team.id, attacker_team.pending_war_id, bool(war), war.status if war else None,
        )
        if war and war.status in ("pending", "scheduled", "active"):
            return False, "🚫 کارتلت الان یه جنگ فعال یا در انتظار داره، اول اونو تموم کن"
        # وار قدیمی تموم شده ولی قفل پاک نشده، خودمون پاکش می‌کنیم
        attacker_team.pending_war_id = None

    today = iran_today()
    if attacker_team.war_day == today and (attacker_team.daily_war_count or 0) >= config.CARTEL_WAR_DAILY_LIMIT:
        return False, (
            f"🚫 سهمیه امروز کارتلت تموم شده\n\n"
            f"🏴 امروز {fa_num(config.CARTEL_WAR_DAILY_LIMIT)} جنگ بین‌کارتلی داشتید\n\n"
            f"⏳ فردا دوباره می‌تونید وارد جنگ بشید"
        )
    return True, ""


async def start_war(session: AsyncSession, attacker_user: User, attacker_team: Team,
                     defender_team: Team) -> tuple[bool, str, CartelWar | None]:
    """ساخت درخواست وار جدید (وضعیت pending)، خروجی: (موفق, پیام خطا/موفقیت, شیء وار)"""
    if defender_team.id == attacker_team.id:
        return False, "🚫 نمی‌تونی به کارتل خودت درخواست وار بدی", None

    ok, err = await can_start_war(session, attacker_team)
    if not ok:
        return False, err, None

    if defender_team.pending_war_id:
        dwar = await session.get(CartelWar, defender_team.pending_war_id)
        if dwar and dwar.status in ("pending", "scheduled", "active"):
            return False, "🚫 اون کارتل الان تو یه جنگ دیگه‌ست", None

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
    """پذیرش — سهمیه روزانه هر دو کارتل مصرف میشه، ۳۰ دقیقه دیگه شروع میشه"""
    now = now_utc()
    war.status = "scheduled"
    war.accepted_at = now
    war.starts_at = now + timedelta(seconds=config.CARTEL_WAR_PREP_SECONDS)

    today = iran_today()
    for team_id in (war.attacker_cartel_id, war.defender_cartel_id):
        team = await session.get(Team, team_id)
        if team:
            team.war_day = today
            team.daily_war_count = (team.daily_war_count or 0) + 1


async def _clear_pending(session: AsyncSession, war: CartelWar) -> None:
    for team_id in (war.attacker_cartel_id, war.defender_cartel_id):
        team = await session.get(Team, team_id)
        if team and team.pending_war_id == war.id:
            team.pending_war_id = None


# ───────── فعال‌سازی و پایان ─────────

async def activate_war(session: AsyncSession, war: CartelWar) -> None:
    """scheduled → active، مدت ۶ ساعته شروع میشه"""
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


# ───────── انتخاب هدف ─────────

async def pick_random_target(session: AsyncSession, enemy_team_id: int) -> User | None:
    """یه عضو تصادفی کارتل حریف؛ آفلاین‌ها هم واجدن، فقط باید هنوز واقعاً عضو باشن"""
    q = select(TeamMember.user_id).where(TeamMember.team_id == enemy_team_id)
    ids = [row[0] for row in (await session.execute(q)).all()]
    if not ids:
        return None
    target_id = random.choice(ids)
    return await session.get(User, target_id)


async def list_enemy_members(session: AsyncSession, enemy_team_id: int) -> list[User]:
    """لیست همه اعضای کارتل حریف، برای انتخاب دستی هدف حمله"""
    q = select(TeamMember.user_id).where(TeamMember.team_id == enemy_team_id)
    ids = [row[0] for row in (await session.execute(q)).all()]
    members = []
    for uid in ids:
        u = await session.get(User, uid)
        if u:
            members.append(u)
    return members


# ───────── حمله وار ─────────

async def _user_power(session: AsyncSession, user: User) -> tuple[int, int]:
    """(حمله, دفاع) خام همون فرمول pvp معمول کاربر، بدون بوست‌های نقش‌محور پی‌وی (وار مستقیم استت خامه)"""
    items = await user_svc.get_item_levels(session, user.id)
    ammo = await user_svc.get_ammo_map(session, user.id)
    dogs = await dog_svc.get_user_dogs(session, user.id)
    return combat.combat_stats(user, items, dogs, ammo=ammo)


async def attack(session: AsyncSession, attacker: User, war: CartelWar,
                  target: User | None = None) -> dict:
    """
    یه حمله وار کامل: کولدان چک، هدف (تصادفی یا مشخص‌شده)، محاسبه نبرد، ثبت لاگ و XP/مدال/تی‌پوینت
    اگه target داده نشه یه عضو تصادفی از کارتل حریف انتخاب میشه
    خروجی دیکشنری: {ok, message, target, success, xp_gained, medals_gained}
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

    if target is not None:
        enemy_membership = await team_svc.get_membership(session, target.id)
        if not enemy_membership or enemy_membership.team_id != enemy_team_id:
            return {"ok": False, "message": "🚫 این بازیکن دیگه تو اون کارتل نیست، یه هدف دیگه انتخاب کن"}
    else:
        target = await pick_random_target(session, enemy_team_id)
        if target is None:
            return {"ok": False, "message": "😴 هیچ عضوی تو کارتل حریف پیدا نشد"}
    if target.id == attacker.id:
        return {"ok": False, "message": "😅 هدف خودت شدی، یکی دیگه رو انتخاب کن"}

    a_atk, _ = await _user_power(session, attacker)
    _, t_def = await _user_power(session, target)

    attack_score = a_atk * random.uniform(0.85, 1.15)
    defense_score = t_def * random.uniform(0.85, 1.15)
    success = attack_score > defense_score

    xp_gain = config.CARTEL_WAR_HIT_XP if success else config.CARTEL_WAR_MISS_XP
    medals_gain = config.CARTEL_WAR_HIT_MEDALS if success else config.CARTEL_WAR_MISS_MEDALS
    tp_gain = config.CARTEL_WAR_HIT_TP if success else 0

    # ضریب بالانس تیم کوچک‌تر روی XP کارتل سوار میشه
    balance_mult = await _balance_multiplier(session, war, my_side)
    xp_gain_scaled = int(round(xp_gain * balance_mult))

    if my_side == "attacker":
        war.attacker_xp = (war.attacker_xp or 0) + xp_gain_scaled
        if success:
            war.attacker_success_hits = (war.attacker_success_hits or 0) + 1
    else:
        war.defender_xp = (war.defender_xp or 0) + xp_gain_scaled
        if success:
            war.defender_success_hits = (war.defender_success_hits or 0) + 1

    attacker.war_medals = (attacker.war_medals or 0) + medals_gain
    attacker.war_attacks = (attacker.war_attacks or 0) + 1
    if tp_gain:
        attacker.cash = (attacker.cash or 0) + tp_gain

    session.add(WarAttackLog(
        war_id=war.id, attacker_id=attacker.id, defender_id=target.id,
        success=success, xp_gained=xp_gain_scaled, medals_gained=medals_gain,
    ))
    await _touch_cooldown(session, attacker.id, war.id)

    return {
        "ok": True,
        "success": success,
        "target": target,
        "xp_gained": xp_gain_scaled,
        "medals_gained": medals_gain,
        "tp_gained": tp_gain,
        "message": _attack_result_text(success, target, xp_gain_scaled, medals_gain, tp_gain),
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


def _attack_result_text(success: bool, target: User, xp: int, medals: int, tp: int) -> str:
    from services.users import display_name
    name = display_name(target)
    if success:
        return (
            f"🔥 <b>حمله موفق!</b>\n\n"
            f"🎯 هدف: {name}\n"
            f"⭐ +{fa_num(xp)} امتیاز جنگ برای کارتل\n"
            f"🎖 +{fa_num(medals)} مدال جنگ\n"
            f"💰 +{money(tp)} تی‌پوینت"
        )
    return (
        f"🛡 <b>حمله دفع شد</b>\n\n"
        f"🎯 هدف: {name}\n"
        f"⭐ +{fa_num(xp)} امتیاز جنگ برای کارتل (تلاش)\n"
        f"🎖 +{fa_num(medals)} مدال جنگ"
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
