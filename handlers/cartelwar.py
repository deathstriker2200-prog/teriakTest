"""
جنگ کارتل‌ها ⚔️🏴 — هندلر

دستور متنی: «کارتل وار [نام کارتل هدف]» — فقط رهبر کارتل، تو پی‌وی یا گروه کار می‌کنه
درخواست به پی‌وی رهبر هدف میره (✅ قبول / ❌ رد)، پذیرش → ۳۰ دقیقه بعد فعال میشه
پنل وار از داخل «کارتل من» با دکمه ⚔️ وار در دسترسه (فقط وقتی وضعیت active باشه)
"""

from telegram import Update
from telegram.ext import ContextTypes

from database import session_scope
from handlers.common import parts, respond, strip_bot_cmd
from keyboards import keyboards as kb
from models import CartelWar, Team, User
from services import cartelwar as cw_svc
from services import teams as team_svc
from services import users
from utils import esc, fa_dur, fa_num, money

SEP = "━━━━━━━━━━━━━━"


# ───────── متن‌ها ─────────

def _no_target_text() -> str:
    return (
        "🤔 <b>اینجوری کار نمی‌کنه</b>\n\n"
        "برای شروع جنگ باید اسم کارتل هدف رو هم بنویسی\n\n"
        "مثال: «کارتل وار فوتبالیست‌ها»"
    )


def _team_not_found_text(name: str) -> str:
    return f"🤷 کارتلی به اسم «{esc(name)}» وجود نداره"


def _request_sent_text(defender_name: str) -> str:
    return (
        f"🚨 <b>درخواست جنگ ارسال شد</b>\n\n"
        f"🏴 به کارتل «{esc(defender_name)}» فرستاده شد\n"
        f"⏳ منتظر پاسخ رهبرشون باش، مهلت یک ساعت"
    )


def _request_received_text(attacker_name: str) -> str:
    return (
        f"⚔️ <b>درخواست جنگ</b>\n\n"
        f"کارتل «{esc(attacker_name)}» شما را به جنگ دعوت کرده\n\n"
        f"⏳ مهلت پاسخ: یک ساعت\n"
        f"در صورت پذیرش، جنگ ۳۰ دقیقه بعد آغاز می‌شود"
    )


def _prep_text(a_name: str, d_name: str) -> str:
    return (
        f"⚔️ <b>نبرد در راه است</b>\n\n"
        f"🏴 {esc(a_name)} VS 🏴 {esc(d_name)}\n\n"
        f"⏳ جنگ تا ۳۰ دقیقه دیگر آغاز می‌شود\n"
        f"🔥 خودتان را برای نبرد آماده کنید"
    )


def _war_started_text(a_name: str, d_name: str) -> str:
    return (
        f"🔥 <b>جنگ آغاز شد</b>\n\n"
        f"🏴 {esc(a_name)} ⚔️ {esc(d_name)}\n\n"
        f"برای شرکت در نبرد وارد بخش «کارتل من» و سپس «جنگ کارتل‌ها» شوید\n"
        f"⏱️ مدت نبرد: ۶ ساعت\n\n"
        f"🔥 سرنوشت جنگ در دستان شماست"
    )


def _war_finished_text(data: dict) -> str:
    war: CartelWar = data["war"]
    a_team: Team | None = data["attacker_team"]
    d_team: Team | None = data["defender_team"]
    winner: Team | None = data["winner_team"]
    a_name = a_team.name if a_team else "؟"
    d_name = d_team.name if d_team else "؟"

    if data["draw"] or winner is None:
        head = "🤝 <b>جنگ کارتل‌ها با تساوی به پایان رسید</b>"
        result_line = "⚔️ هیچ‌کدام از کارتل‌ها پیروز نشدند"
        reward_block = ""
    else:
        head = "🏳️ <b>پایان جنگ کارتل‌ها</b>"
        result_line = f"🏆 کارتل «{esc(winner.name)}» پیروز شد"
        reward_block = (
            f"\n\n{SEP}\n\n"
            f"🎁 <b>پاداش اعضای تیم برنده</b>\n"
            f"• {money(50_000)}\n"
            f"• ۵۰۰ XP کارتل\n"
            f"• ۳۰۰ XP شخصی\n"
            f"• یک 🎖 مدال افتخار جنگ\n\n"
            f"🏆 کارتل {esc(winner.name)} حالا {fa_num(winner.war_trophies)} پیروزی جنگی داره"
        )

    return (
        f"{head}\n\n"
        f"{result_line}\n\n"
        f"{SEP}\n\n"
        f"📊 <b>نتیجه نهایی</b>\n"
        f"🏴 {esc(a_name)} → {fa_num(war.attacker_xp)} XP\n"
        f"🏴 {esc(d_name)} → {fa_num(war.defender_xp)} XP"
        f"{reward_block}"
    )


# ───────── شروع وار: دستور متنی «کارتل وار [نام]» ─────────

async def cartel_war_start_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw_text = update.message.text or ""
    txt = strip_bot_cmd(raw_text)
    p = txt.split(None, 2)
    target_name = p[2].strip() if len(p) > 2 else ""
    if not target_name:
        return await respond(update, _no_target_text())

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        membership = await team_svc.get_membership(s, user.id)
        if not membership or membership.role != "owner":
            await s.commit()
            return await respond(update, "🚫 فقط رهبر کارتل می‌تونه جنگ راه بندازه")

        attacker_team = await team_svc.get_team_of(s, user.id)
        defender_team = await team_svc.get_team_by_name(s, target_name)
        if not defender_team:
            await s.commit()
            return await respond(update, _team_not_found_text(target_name))

        ok, err, war = await cw_svc.start_war(s, user, attacker_team, defender_team)
        if not ok:
            await s.commit()
            return await respond(update, err)

        defender_leader = await s.get(User, defender_team.owner_id)
        await s.commit()

    await respond(update, _request_sent_text(defender_team.name))

    if defender_leader:
        try:
            await context.bot.send_message(
                defender_leader.telegram_id,
                _request_received_text(attacker_team.name),
                parse_mode="HTML",
                reply_markup=kb.cartel_war_response_kb(war.id),
            )
        except Exception:
            pass  # راند ۲۲: ربات نتونست پیام بده، جریان وار متوقف نمیشه (خودش با انقضا هندل میشه)


# ───────── پاسخ رهبر هدف ─────────

async def war_accept_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    war_id = int(parts(update)[2])
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        war = await s.get(CartelWar, war_id)
        if not war or war.status != "pending":
            await s.commit()
            return await respond(update, "⌛ این درخواست دیگه معتبر نیست")
        if war.defender_leader_id != user.id:
            await s.commit()
            return await respond(update, "🚫 این درخواست مال تو نیست")

        await cw_svc.accept_war(s, war)
        a_team = await s.get(Team, war.attacker_cartel_id)
        d_team = await s.get(Team, war.defender_cartel_id)
        members_a = await team_svc.get_members(s, a_team.id)
        members_d = await team_svc.get_members(s, d_team.id)
        notify_users = []
        for m in list(members_a) + list(members_d):
            mu = await s.get(User, m.user_id)
            if mu:
                notify_users.append(mu.telegram_id)
        await s.commit()

    await respond(update, f"✅ پذیرفتی، جنگ با «{esc(a_team.name)}» تا ۳۰ دقیقه دیگه شروع میشه")

    prep_text = _prep_text(a_team.name, d_team.name)
    for tg_id in notify_users:
        try:
            await context.bot.send_message(tg_id, prep_text, parse_mode="HTML")
        except Exception:
            pass


async def war_reject_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    war_id = int(parts(update)[2])
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        war = await s.get(CartelWar, war_id)
        if not war or war.status != "pending":
            await s.commit()
            return await respond(update, "⌛ این درخواست دیگه معتبر نیست")
        if war.defender_leader_id != user.id:
            await s.commit()
            return await respond(update, "🚫 این درخواست مال تو نیست")

        await cw_svc.reject_war(s, war)
        a_team = await s.get(Team, war.attacker_cartel_id)
        attacker_leader = await s.get(User, war.attacker_leader_id)
        await s.commit()

    await respond(update, "❌ درخواست جنگ رد شد")
    if attacker_leader:
        try:
            await context.bot.send_message(
                attacker_leader.telegram_id,
                "❌ کارتل هدف درخواست جنگ شما را رد کرد",
            )
        except Exception:
            pass


async def _active_war_for(s, team_id: int) -> CartelWar | None:
    """وار active فعلی این کارتل، اگه بود"""
    from sqlalchemy import select
    q = select(CartelWar).where(
        CartelWar.status == "active",
        (CartelWar.attacker_cartel_id == team_id) | (CartelWar.defender_cartel_id == team_id),
    )
    return (await s.execute(q)).scalar_one_or_none()


def _no_active_war_text() -> str:
    return "😴 الان هیچ جنگ فعالی برای کارتلت نیست"


def _not_member_text() -> str:
    return "🚫 عضو هیچ کارتلی نیستی"


# ───────── ورودی پنل وار: متن خوش‌آمد، نه آمار ─────────

async def war_panel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه ⚔️ وار تو منوی کارتل من، فقط وقتی وار active باشه فعاله
    اولین چیزی که دیده میشه یه خوش‌آمد کوتاهه، نه آمار مستقیم"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        membership = await team_svc.get_membership(s, user.id)
        if not membership:
            await s.commit()
            return await respond(update, _not_member_text())

        war = await _active_war_for(s, membership.team_id)
        if not war:
            await s.commit()
            return await respond(update, _no_active_war_text())

        a_team = await s.get(Team, war.attacker_cartel_id)
        d_team = await s.get(Team, war.defender_cartel_id)
        cd = await cw_svc.cooldown_left(s, user.id, war.id)
        fit_ok, fit_err = await cw_svc.can_fight(s, user, war)
        await s.commit()

    can_attack = fit_ok and cd == 0
    text = _intro_text(a_team, d_team, cd, fit_err if not fit_ok else "")
    await respond(update, text, kb.cartel_war_panel_kb(can_attack=can_attack))


def _intro_text(a_team: Team, d_team: Team, cooldown: int, note: str) -> str:
    lines = [
        "⚔️ <b>جنگ کارتل‌ها</b>",
        "",
        f"🏴 {esc(a_team.name)} در برابر 🏴 {esc(d_team.name)}",
        "",
        "کارتلت الان درگیر یه جنگ فعاله، از اینجا می‌تونی حمله کنی یا وضعیت نبرد رو ببینی",
    ]
    if cooldown:
        lines.append(f"\n⏳ کول‌دان تو: {fa_dur(cooldown)}")
    elif note:
        lines.append(f"\n{note}")
    else:
        lines.append("\n✅ آماده حمله‌ای")
    return "\n".join(lines)


# ───────── آمار جنگ ─────────

def _panel_text(data: dict, cooldown: int, note: str) -> str:
    war: CartelWar = data["war"]
    a_team: Team = data["attacker_team"]
    d_team: Team = data["defender_team"]
    left = fa_dur(data["seconds_left"])
    cd_line = f"⏳ کول‌دان تو: {fa_dur(cooldown)}" if cooldown else "✅ آماده حمله‌ای"
    lines = [
        "📊 <b>آمار جنگ</b>",
        "",
        f"⚔️ {esc(a_team.name)} VS {esc(d_team.name)}",
        "",
        f"⭐ امتیاز جنگ: {fa_num(war.attacker_xp)} — {fa_num(war.defender_xp)}",
        f"🎯 حملات موفق: {fa_num(war.attacker_success_hits)} — {fa_num(war.defender_success_hits)}",
        f"⏳ زمان باقی‌مانده: {left}",
        "",
        cd_line,
    ]
    if note:
        lines.append(f"\n{note}")
    return "\n".join(lines)


async def war_stats_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        membership = await team_svc.get_membership(s, user.id)
        if not membership:
            await s.commit()
            return await respond(update, _not_member_text())
        war = await _active_war_for(s, membership.team_id)
        if not war:
            await s.commit()
            return await respond(update, _no_active_war_text())
        data = await cw_svc.war_panel_data(s, war)
        await s.commit()

    text = _panel_text(data, 0, "")
    await respond(update, text, kb.cartel_war_back_kb())


async def war_board_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🏆 جدول نبرد: برترین کارتل‌ها بر اساس تروفی جنگی"""
    from sqlalchemy import select
    async with session_scope() as s:
        q = select(Team).order_by(Team.war_trophies.desc()).limit(10)
        top = list((await s.execute(q)).scalars())
        await s.commit()

    if not top:
        return await respond(update, "📭 هنوز هیچ کارتلی جنگی نبرده", kb.cartel_war_back_kb())

    lines = ["🏆 <b>جدول نبرد جنگ کارتل‌ها</b>", ""]
    for i, t in enumerate(top, 1):
        wr = cw_svc.win_rate(t)
        lines.append(
            f"{fa_num(i)}. {esc(t.name)} — 🏆 {fa_num(t.war_trophies)} | 📈 {fa_num(wr)}٪ | 🎖 {fa_num(t.war_medals_total)}"
        )
    await respond(update, "\n".join(lines), kb.cartel_war_back_kb())


# ───────── حمله وار ─────────

async def war_hit_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """⚔️ حمله تصادفی: یه عضو تصادفی کارتل حریف انتخاب و بهش حمله میشه"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        membership = await team_svc.get_membership(s, user.id)
        if not membership:
            await s.commit()
            return await respond(update, _not_member_text())
        war = await _active_war_for(s, membership.team_id)
        if not war:
            await s.commit()
            return await respond(update, _no_active_war_text())

        result = await cw_svc.attack(s, user, war)
        await s.commit()

    await respond(update, result["message"], kb.cartel_war_back_kb())


# ───────── انتخاب دستی هدف از بین اعضای کارتل حریف ─────────

async def war_targets_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🎯 لیست اعضای کارتل حریف، برای انتخاب دستی هدف حمله"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        membership = await team_svc.get_membership(s, user.id)
        if not membership:
            await s.commit()
            return await respond(update, _not_member_text())
        war = await _active_war_for(s, membership.team_id)
        if not war:
            await s.commit()
            return await respond(update, _no_active_war_text())

        side = cw_svc.my_side_and_enemy(war, membership.team_id)
        if side is None:
            await s.commit()
            return await respond(update, "🚫 کارتلت تو این جنگ نیست")
        _, enemy_team_id = side

        enemy_team = await s.get(Team, enemy_team_id)
        members = await cw_svc.list_enemy_members(s, enemy_team_id)
        members = [m for m in members if m.id != user.id]
        await s.commit()

    if not members:
        return await respond(update, "😴 هیچ عضوی تو کارتل حریف پیدا نشد", kb.cartel_war_back_kb())

    lines = [f"🎯 <b>اعضای کارتل «{esc(enemy_team.name)}»</b>", "", "یکی رو برای حمله انتخاب کن"]
    await respond(update, "\n".join(lines), kb.cartel_war_targets_kb(members))


async def war_hit_target_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """⚔️ حمله به یه عضو مشخص از کارتل حریف که از لیست انتخاب شده"""
    target_id = int(parts(update)[2])
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        membership = await team_svc.get_membership(s, user.id)
        if not membership:
            await s.commit()
            return await respond(update, _not_member_text())
        war = await _active_war_for(s, membership.team_id)
        if not war:
            await s.commit()
            return await respond(update, _no_active_war_text())

        target = await s.get(User, target_id)
        if not target:
            await s.commit()
            return await respond(update, "🤷 این بازیکن دیگه پیدا نمیشه", kb.cartel_war_back_kb())

        result = await cw_svc.attack(s, user, war, target=target)
        await s.commit()

    await respond(update, result["message"], kb.cartel_war_back_kb())
