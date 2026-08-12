"""
کارتل 🏴، ساخت (لول ۵) | درخواست عضویت (لول ۳، با تایید مدیران) | آمار با «کارتل [اسم]» | بیو | ترک/انحلال
کارتل هم لول داره، تجربه اعضا از کنده‌کاری و حمله و برداشت به کارتل هم میرسه (مکس لول ۱۰)
هر لول کارتل +۱۰ ظرفیت عضوه و لول ساختمان‌ها هم به لول کارتل وابسته‌ست
کوئست روزانه گروهی با «کارتل کوئست» | کنده‌کاری کارتلی با «کنده کاری کارتلی» (حداقل ۳ نفر، ۷۰% اعضا)
امتیاز کارتلی + لیدربرد هفتگی («کارتل لیدربرد») | ساختمان حمله/دفاع با آپگرید رهبر («کارتل ساختمان»)
بانک کارتل («کارتل بانک») + کمک مالی اعضا («کارتل واریز 1200») | لیست اعضا («کارتل عضویت»)
👑 مدیریت کارتل (فقط رهبر و مدیران): 📨 درخواست‌های عضویت (قبول/رد با دکمه یا «کارتل درخواست @یوزر قبول|رد»)
👢 اخراج عضو با سرچ آیدی/یوزرنیم/اسم (دکمه «کارتل کیک @یوزر») | «کارتل ادمین @یوزر» فقط رهبر
دستورهای کارتل با هر دو شکل «تریاکی کارتل ...» و «کارتل ...» کار می‌کنن
"""

import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from sqlalchemy import select

import config
from database import session_scope
from handlers.common import chat_id_of, has_prefix, parts, respond, strip_bot_cmd, strip_home
from keyboards import keyboards as kb
from models import Team, TeamMember, TeamRequest, User
from services import combat, dogs as dog_svc, teams, users
from utils import bar, esc, fa_dur, fa_num, jalali_str, money, money_tp, parse_amount


# ───────── متن‌ها ─────────

def _no_team_text() -> str:
    return (
        "<b>🏴 کارتل نداری</b>\n\n"
        f"👑 ساخت کارتل از لول {fa_num(config.TEAM_CREATE_MIN_LEVEL)} و با {money(config.TEAM_CREATE_COST)}، «ساخت کارتل» بزن و اسمشو بفرست\n"
        f"🤝 عضویت تو کارتل رفیقات از لول {fa_num(config.TEAM_JOIN_MIN_LEVEL)}، «جوین کارتل [اسم]»\n\n"
        "📜 کوئست‌های روزانه جمعی جایزه به همه میدن\n"
        "⛏ کنده‌کاری کارتلی هم پول میریزه تو خزانه\n\n"
        "🏆 «کارتل» رو بزن تا برترین کارتل‌ها رو ببینی"
    )


def _team_stats_text(data: dict) -> str:
    team = data["team"]
    created = jalali_str(team.created_at) if team.created_at else "-"

    lines = [f"<b>🏴 کارتل «{esc(team.name)}»</b>"]
    if team.bio:
        lines.append(f"📜 <i>{esc(team.bio)}</i>")
    lines.append("")
    lines.append(f"👑 رهبر: {esc(data['owner_name'])}")
    tlevel = team.level or 1
    if tlevel >= config.TEAM_MAX_LEVEL:
        lines.append(f"⭐️ لول {fa_num(tlevel)} 👑 مکس")
    else:
        need = teams.team_xp_need(tlevel)
        lines.append(f"⭐️ لول {fa_num(tlevel)} | ✨ {fa_num(team.xp or 0)}/{fa_num(need)}")
    lines.append(f"👥 اعضا: {fa_num(data['count'])}/{fa_num(teams.team_capacity(team))}")
    lines.append(f"🏦 خزانه: {money(team.bank)}")
    lines.append("")
    lines.append("<b>📊 آمار</b>")
    lines.append(f"🎖 مدال‌ها: {fa_num(data['medals']['all'])}")
    lines.append(f"⚔️ برد: {fa_num(data['wins'])} | ❌ باخت: {fa_num(data['losses'])}")
    lines.append(f"🎯 کشتار: {fa_num(team.total_kills)} | 🌾 برداشت: {fa_num(team.total_harvests)}")
    lines.append(f"📅 امروز: {fa_num(data['medals']['day'])} | این هفته: {fa_num(data['medals']['week'])}")
    lines.append("")
    lines.append("<b>🏗 ساختمان‌ها</b>")
    atk_pct = int(config.TEAM_ATK_BONUS_PER_LEVEL * (team.atk_bld or 0) * 100)
    def_pct = int(config.TEAM_DEF_BONUS_PER_LEVEL * (team.def_bld or 0) * 100)
    lines.append(f"⚔️ حمله: Lv.{fa_num(team.atk_bld or 0)} (+{fa_num(atk_pct)}%)")
    lines.append(f"🛡 دفاع: Lv.{fa_num(team.def_bld or 0)} (+{fa_num(def_pct)}%)")
    lines.append("")
    lines.append("<b>👥 اعضا</b>")

    by_id = {u.id: u for u in data["users"]}
    pairs = [(m, by_id.get(m.user_id)) for m in data["members"]]
    # اسم‌ها بر اساس لول، از بالا به پایین
    pairs.sort(key=lambda p: (-(p[1].level if p[1] else 0), -(p[1].wins if p[1] else 0)))
    shown = 0
    for m, u in pairs:
        if not u or shown >= 12:
            continue
        tag = {"owner": "👑", "admin": "🛡"}.get(m.role, "🔸")
        name = "👻 نامرئی" if u.lb_hidden else (u.first_name or u.username or "؟")
        temoji, tname = users.title_of(u)
        lines.append(f"{tag} {temoji} {esc(name)} <b>「{tname}」</b> | لول {fa_num(u.level)}")
        shown += 1
    if data["count"] > shown:
        lines.append(f"🔸 و {fa_num(data['count'] - shown)} نفر دیگه")

    lines.append("")
    lines.append("<b>🎯 کوئست‌های امروز</b>")
    lines.extend(_quest_lines(data["daily"], team.id, team.level or 1))
    lines.append("")
    lines.append(f"📅 تأسیس: {created}")
    return "\n".join(lines)


def _quest_lines(daily, team_id: int = 0, team_level: int = 1) -> list[str]:
    lines: list[str] = []
    for q in teams.daily_quests_view(daily, team_id, team_level):
        if q["done"]:
            lines.append(f"{q['emoji']} {esc(q['title'])} ✅ انجام شد")
        else:
            lines.append(f"{q['emoji']} {esc(q['title'])} ({fa_num(q['progress'])}/{fa_num(q['target'])})")
    return lines


def _quests_text(team, daily) -> str:
    # راند ۲۲ (درخواست کارفرما): صفحه کوئست فقط ۲ تا ۴ کوئست فعال همون روز، بدون لیست بلندبالای کلی
    picked = teams.daily_quests_view(daily, team.id, team.level or 1)
    lines = [f"<b>📜 کوئست‌های امروز کارتل «{esc(team.name)}»</b>", ""]
    lines.append(f"امروز {fa_num(len(picked))} کوئست فعاله، هر شب ساعت ۱۲ به وقت ایران از نو میشن")
    lines.append("")
    for q in picked:
        if q["done"]:
            state = "✅ کامل شد"
        else:
            state = f"{fa_num(q['progress'])} از {fa_num(q['target'])}"
        lines.append(f"{q['emoji']} <b>{esc(q['title'])}</b>")
        lines.append(f"پیشرفت: {state}")
        lines.append(f"🎁 جایزه: {money(q['reward'])} برای هر عضو")
        if q.get("bank_reward"):
            lines.append(f"🏦 بانک کارتل: {money(q['bank_reward'])}")
        lines.append(f"<i>{esc(q['desc'])}</i>")
        lines.append("")
    locked = teams.locked_quests_view(team.level or 1)
    if locked:
        lines.append(f"🔒 {fa_num(len(locked))} کوئست دیگه هم هست که با لول‌های بالاتر کارتل باز میشن")
        lines.append("")
    lines.append("🕛 ریست هر شب ۱۲، استعلام با «کارتل کوئست»")
    return "\n".join(lines)


def _mine_progress_text(res: dict) -> str:
    team = res["team"]
    joined, needed, m_count = res["joined"], res["needed"], res["member_count"]
    remaining = max(0, needed - joined)
    pct = int(config.TEAM_MINE_JOIN_PCT * 100)

    text = (
        f"<b>⛏ کنده‌کاری کارتلی، کارتل «{esc(team.name)}»</b>\n\n"
        f"لازمه {fa_num(pct)}% اعضا ({fa_num(needed)} نفر از {fa_num(m_count)}) دستور رو بزنن\n\n"
        f"{fa_num(joined)} نفر از {fa_num(m_count)} نفر به کنده‌کاری پیوستند\n"
    )
    if remaining:
        text += f"{fa_num(remaining)} نفر تا تکمیل کنده‌کاری\n"
        text += f"\n⏳ تا {fa_dur(config.TEAM_MINE_WINDOW_SECONDS)} دیگه فرصت\nبقیه اعضا هم بنویسن «کنده کاری کارتلی»"
    return text.rstrip()


def _mine_complete_text(res: dict) -> str:
    team = res["team"]
    return (
        "<b>✅ کنده‌کاری کارتلی کامل شد</b>\n\n"
        f"کارتل «{esc(team.name)}» ته کار رو گرفت 😈\n"
        f"💰 {money(res['reward'])} رفت تو خزانه کارتل\n"
        f"🏦 خزانه الان {money(res['bank'])} ـه\n\n"
        f"⏳ کنده‌کاری بعدی {fa_num(config.TEAM_MINE_COOLDOWN_MINUTES)} دقیقه دیگه"
    )


# ───────── کارتل من / آمار کارتل ─────────

async def render_my_team(update: Update, alert: str | None = None) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        membership = await teams.get_membership(s, user.id)
        team = await teams.get_team_of(s, user.id)
        if not membership or not team:
            await s.commit()
            return await respond(update, _no_team_text(), kb.team_no_kb(), alert=alert)

        data = await teams.team_stats_data(s, team)
        text = _team_stats_text(data)
        await s.commit()

    await respond(update, text, kb.team_kb(
        is_owner=membership.role == "owner",
        is_manager=teams.is_manager(membership),
    ), alert=alert)


async def team_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_my_team(update)


async def team_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«کارتل» «کارتل من» «کارتل [اسم]»، آمار کارتل با دستور خاص"""
    arg = ""
    raw_text = update.message.text or ""
    prefixed = has_prefix(raw_text)
    txt = strip_bot_cmd(raw_text)
    p = txt.split(None, 1)
    if len(p) > 1:
        arg = p[1].strip()

    if not arg:
        # بدون اسم، اگه کارتلی دارم مال خودم، وگرنه برترین‌ها
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            membership = await teams.get_membership(s, user.id)
            await s.commit()
        if membership:
            return await render_my_team(update)
        return await top_teams_text(update, context)

    if arg in ("من", "خودم"):
        return await render_my_team(update)

    if arg in ("اعضا", "عضو", "members"):
        return await team_members_text(update)

    if arg in ("چت", "chat"):
        return await team_chat_render(update)

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        team = await teams.get_team_by_name(s, arg)
        if not team:
            await s.commit()
            # «کارتل فلان» بی‌پیشوند که کارتلی پیدا نکنه گپ عادی حساب میشه، بی‌صدا رد
            if not prefixed:
                return
            return await respond(update, f"🤷 کارتلی با اسم «{esc(arg)}» پیدا نشد\n\nآمار هر کارتل با «کارتل [اسم]»، مثلا «کارتل فوتبالیست‌ها»")
        data = await teams.team_stats_data(s, team)
        text = _team_stats_text(data)
        await s.commit()

    await respond(update, text)


async def _announce_winners(context: ContextTypes.DEFAULT_TYPE, winners: list[dict]) -> None:
    """پیام خصوصی جایزه هفتگی به اعضای کارتل‌های برنده، بیشترین تلاش، بی‌صدا رد میشه"""
    if context is None or not winners:
        return
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    per_team: list[tuple[dict, list[int]]] = []
    async with session_scope() as s:
        for w in winners:
            tg_ids = await teams.member_telegram_ids(s, w["team"].id)
            per_team.append((w, tg_ids))
        await s.commit()

    for w, tg_ids in per_team:
        text = (
            f"<b>{medals[w['rank']]} کارتل «{esc(w['team'].name)}» مقام {fa_num(w['rank'])} هفته رو گرفت</b>\n\n"
            f"💎 با {fa_num(w['points'])} امتیاز هفتگی\n"
            f"🎁 {money(w['prize'])} به بانک کارتل واریز شد\n\n"
            "هفته جدید شروع شده، دوباره بجنگین 💪"
        )
        for tg in tg_ids:
            try:
                await context.bot.send_message(tg, text, parse_mode="HTML")
            except Exception:
                pass  # بلاک یا ریستارت، مهم نیس


_TEAM_TOP_TABS = [("day", "☀️ روزانه"), ("week", "📅 هفتگی"), ("all", "🌍 کلی")]

# نشان رتبه لیدربرد: سه تای اول مدال، بعدیشون عدد کی‌کپ
_RANK_BADGES = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}


def _team_rank_badge(i: int) -> str:
    return _RANK_BADGES.get(i, f"▫️ {fa_num(i)}")


async def top_teams_text(update: Update, context: ContextTypes.DEFAULT_TYPE, tab: str | None = None) -> None:
    """🏆 لیدربرد کارتل‌ها بر اساس جمع مدال‌های اعضا، تب روزانه/هفتگی/کلی با پیش‌فرض کلی («کارتل لیدربرد»)"""
    keys = [k for k, _ in _TEAM_TOP_TABS]
    titles = dict(_TEAM_TOP_TABS)
    if tab not in keys:
        tab = "all"  # پیش‌فرض رقابت کلی (راند ۱۰)، کاربر خودش با دکمه‌ها تب رو عوض می‌کنه

    async with session_scope() as s:
        winners = await teams.maybe_weekly_rollover(s)
        tops = await teams.top_teams_by_medals(s, tab, limit=config.RANK_LIMIT)
        last_week = await teams.meta_get(s, "last_week_result")
        await s.commit()

    if winners:
        await _announce_winners(context, winners)

    lines = ["<b>🏆 لیدربرد کارتل‌ها</b>", titles[tab], ""]
    if not tops:
        lines.append("هنوز هیچ کارتلی ساخته نشده\nاولیشو تو بساز 😎 «ساخت کارتل»")
    else:
        for i, (t, total, n) in enumerate(tops, 1):
            badge = _team_rank_badge(i)
            lines.append(f"{badge} [Lv.{t.level:02d}] │ {esc(t.name)} 🎖️ {fa_num(total)}")
        if tab == "week" or not last_week:
            p1, p2, p3 = (config.TEAM_WEEKLY_PRIZES.get(i, 0) for i in (1, 2, 3))
            lines.append("")
            lines.append(f"🏁 آخر هفته: 🥇 {money_tp(p1)} | 🥈 {money_tp(p2)} | 🥉 {money_tp(p3)}، به بانک کارتل")

    if last_week and tab != "week":
        lines.append("")
        lines.append("━━━━ 👑 قهرمانای هفته پیش ━━━━")
        lines.append(esc(last_week))

    lines.append("━━━━━━━━━━━━━━━━")
    lines.append("🎖️ مجموع مدال‌های اعضای کارتل")
    lines.append("💬 کارتل [نام کارتل] آمار هر کارتلی رو نشونت میده")
    text = "\n".join(lines)

    await respond(update, text, kb.team_top_kb(tab))


async def top_teams_tab_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تعویض تب لیدربرد کارتل‌ها، زدن رو دکمه تب فعلی هیچ واکنشی نداره (فقط لودینگ قطع میشه)"""
    _p, _t, cur, tgt = update.callback_query.data.split(":")
    if cur == tgt:
        await update.callback_query.answer()
        return
    await top_teams_text(update, context, tab=tgt)


# ───────── ساخت کارتل ─────────

async def create_team_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, alert = await teams.can_create_team(s, user)
        if ok:
            if user.pending_action:
                ok, alert = False, "⏳ اول کار قبلیتو تموم کن یا «لغو» بزن"
            else:
                users.set_pending(user, "teamname", "", chat_id_of(update))
        await s.commit()

    if not ok:
        return await respond(update, alert)

    await respond(
        update,
        "<b>🏴 اسم کارتلت رو بفرست</b>\n\n"
        f"💸 ساخت کارتل {money(config.TEAM_CREATE_COST)} هزینه داره\n"
        "هر اسمی دوست داری همینجا بنویس و بفرست، مثلا «فوتبالیست‌ها»\n\n"
        "❌ اگر هم پشیمون شدی بنویس «لغو»",
    )


async def team_create_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تایید/رد ساخت کارتل بعد از اسم دادن (teamcf:ok/no:<tg>)، فقط خودش"""
    _, act, owner_tg = parts(update)
    if update.effective_user.id != int(owner_tg):
        await update.callback_query.answer()  # غریبه هیچ واکنشی نمی‌بینه
        return

    if act == "no":
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            if user.pending_action == "teamcf":
                users.set_pending(user, None)
            await s.commit()
        return await respond(update, "<b>😅 بی‌خیال شدیم</b>", kb.home_kb())

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        if user.pending_action != "teamcf" or not user.pending_value:
            await s.commit()
            return await respond(update, "⏳ این درخواست قدیمیه یا انجام شده، دوباره «ساخت کارتل» بزن")
        name = user.pending_value
        ok, res = await teams.create_team(s, user, name)
        users.set_pending(user, None)
        await s.commit()

    if not ok:
        return await respond(update, res)
    await respond(
        update,
        f"<b>🏴 کارتل «{esc(res)}» ساخته شد</b>\n\n"
        f"📜 کوئست‌های روزانه با «کارتل کوئست»\n"
        f"⛏ کنده‌کاری کارتلی با «کنده کاری کارتلی»\n"
        f"✏️ بیوی کارتل با «کارتل ست بیو [متن]»\n"
        f"📊 آمار کارتل با «کارتل من»\n\n"
        f"به رفقات بگو بنویسن «جوین کارتل {esc(res)}» و همینجا درخواستشون رو قبول کن 😈",
        kb.team_kb(is_owner=True, is_manager=True),
    )


# ───────── جوین کارتل ─────────

async def join_team_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = strip_bot_cmd(update.message.text or "")
    # «جوین کارتل فوتبالیست‌ها» یا «کارتل جوین فوتبالیست‌ها» (راند ۲۷)، اسم میتونه چندکلمه‌ای باشه
    m = re.match(r"^(?:جوین[\s‌]+(?:کارتل|تیم)|(?:کارتل|تیم)[\s‌]+جوین)[\s‌]+(.+)$", txt)
    arg = m.group(1) if m else ""

    if not arg:
        return await respond(update, "🤷 این‌جوری بنویس: «کارتل جوین [اسم کارتل]»")

    req_id = None
    owner_tg = None
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, res = await teams.request_join(s, user, arg)
        if ok:
            # آیدی درخواست و رهبر کارتل رو برای دی‌ام تأیید/رد پیدا کن
            team = await teams.get_team_by_name(s, arg)
            if team is not None:
                reqs = await teams.get_requests(s, team.id)
                for r, u in reqs:
                    if u.id == user.id:
                        req_id = r.id
                q_o = select(TeamMember).where(
                    TeamMember.team_id == team.id, TeamMember.role == "owner")
                own = (await s.execute(q_o)).scalars().first()
                if own is not None:
                    owner_u = await s.get(User, own.user_id)
                    if owner_u is not None:
                        owner_tg = owner_u.telegram_id
        await s.commit()

    if ok:
        text = (
            f"<b>📨 درخواست عضویت برای کارتل «{esc(res)}» ارسال شد</b>\n\n"
            "منتظر تأیید مدیران باش"
        )
        await respond(update, text)
        if req_id is not None and owner_tg:
            an = esc(users.display_name(update.effective_user))
            un = f" (@{update.effective_user.username})" if update.effective_user.username else ""
            await _dm(context, owner_tg,
                      "<b>📨 درخواست عضویت جدید</b>\n\n"
                      f"👤 «{an}»{un}\n"
                      f"🏴 می‌خواد بیاد تو کارتل «{esc(res)}»\n\n"
                      "با دکمه‌های پایین تایید یا ردش کن",
                      kb.team_join_request_kb(req_id))
        return
    await respond(update, res)


async def team_join_request_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌های ✅ قبول / ❌ رد تو دی‌ام رهبر برای درخواست عضویت (راند ۲۷)"""
    q = update.callback_query
    if q is None:
        return
    p2 = parts(update)
    act, req_id = p2[1], int(p2[2])
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        me = await teams.get_membership(s, user.id)
        row = await teams.get_request(s, req_id)
        valid = (row is not None and me is not None
                 and me.team_id == row[0].team_id and teams.is_manager(me))
        req = row[0] if row else None
        team = await s.get(Team, req.team_id) if req is not None else None
        team_name = team.name if team is not None else "؟"
        await s.commit()
    if row is None:
        try:
            await q.edit_message_text("🤷 این درخواست دیگه نیس، قبلاً رسیدگی شده")
        except Exception:
            pass
        return await q.answer()
    if not valid:
        # دکمه دی‌ام مال رهبر/مدیر همون کارتله؛ بقیه ساکت
        return await q.answer()
    req, target = row
    msg = await _resolve_request(update, context, req, target, team, accept=(act == "ok"))
    an = esc(users.display_name(target)) if target else "؟"
    try:
        await q.edit_message_text(
            f"<b>📨 درخواست عضویت «{an}» برای کارتل «{esc(team_name)}»</b>\n\n{msg}")
    except Exception:
        pass
    await q.answer()

async def leave_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        membership = await teams.get_membership(s, user.id)
        t = await teams.get_team_of(s, user.id)
        name = t.name if t else None
        role = membership.role if membership else None
        await s.commit()

    if not membership:
        return await respond(update, "🏴 اصلا تو کارتلی نیستی که", alert="🏴 تو کارتلی نیستی" if update.callback_query else None)
    if role == "owner":
        return await respond(
            update,
            "<b>👑 تو رهبر کارتلی</b>\n\nنمی‌تونی بری، باید کارتل رو منحل کنی\nاگه تصمیمت قطعیه «انحلال کارتل» رو بزن",
        )

    text = (
        f"<b>🚪 ترک کارتل «{esc(name)}»</b>\n\n"
        "مطمئنی می‌خوای بری؟"
    )
    await respond(update, text, kb.team_confirm_kb("leave", update.effective_user.id))


async def disband_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        membership = await teams.get_membership(s, user.id)
        t = await teams.get_team_of(s, user.id)
        name = t.name if t else None
        bank = t.bank if t else 0
        role = membership.role if membership else None
        await s.commit()

    if role != "owner":
        return await respond(update, "👑 فقط رهبر می‌تونه کارتل رو منحل کنه")

    text = (
        f"<b>💥 انحلال کارتل «{esc(name)}»</b>\n\n"
        f"🏦 خزانه {money(bank)} می‌سوزه\n"
        "📊 آمار و کوئست‌ها پاک میشه\n"
        "👥 همه اعضا سرباز میشن\n\n"
        "مطمئنی؟ برگشتی نداره"
    )
    await respond(update, text, kb.team_confirm_kb("disband", update.effective_user.id))


async def team_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """اجرای ترک/انحلال، فقط صاحب دستور"""
    _, action, owner_tg = parts(update)

    if update.effective_user.id != int(owner_tg):
        await update.callback_query.answer()  # غریبه هیچ واکنشی نمی‌بینه
        return

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        if action == "leave":
            ok, res = await teams.leave_team(s, user)
            msg = f"🚪 از کارتل «{res}» خارج شدی" if ok else res
        elif action == "rename":
            new_name = (context.user_data or {}).pop("pending_team_rename", None)
            if new_name is None:
                ok, msg = False, "⏳ این تایید منقضی شده، «کارتل تغییر نام [اسم]» رو دوباره بزن"
            else:
                ok, msg = await teams.rename_team(s, user, new_name)
        else:
            ok, res = await teams.disband_team(s, user)
            msg = f"💥 کارتل «{res}» منحل شد، همه آزادن" if ok else res
        await s.commit()

    if not ok:
        return await respond(update, msg)

    await respond(update, f"<b>{esc(msg)}</b>", kb.home_kb())


# ───────── مخفی کردن کارتل از لیدربرد ─────────

async def hide_team_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """👻 «کارتل مخفی [اسم]»، فقط ادمین، تاگل نامرئی هر کارتل تو لیدربردها (بدون اسم، کارتل خودش)"""
    if update.effective_user.id not in config.ADMIN_IDS:
        return await respond(update, "🚫 مخفی کردن کارتل فقط دست ادمینه")
    txt = strip_bot_cmd(update.message.text or "")
    m = re.match(r"^کارتل[\s‌]+مخفی(?:[\s‌]+(.+))?$", txt)
    arg = (m.group(1) or "").strip() if m else ""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        _, msg = await teams.toggle_hidden(s, user, arg or None)
        await s.commit()
    await respond(update, msg)


# ───────── بیوی کارتل ─────────

async def set_bio_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = strip_bot_cmd(update.message.text or "")
    m = re.match(r"^کارتل[\s‌]+ست[\s‌]+بیو[\s‌]+(.+)$", txt)
    arg = m.group(1) if m else ""

    if not arg:
        return await respond(update, "✏️ این‌جوری بنویس: «کارتل ست بیو [متن]»")

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, res = await teams.set_bio(s, user, arg)
        await s.commit()

    if ok:
        return await respond(update, f"✏️ بیوی کارتل ست شد:\n<i>{esc(res)}</i>\n\nتو آمار کارتل با «کارتل من» نمایش داده میشه")
    await respond(update, res)


async def rename_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """✏️ «کارتل تغییر نام [اسم جدید]»، فقط رهبر، اول فاکتور و تایید میاد بعد اعمال میشه"""
    txt = strip_bot_cmd(update.message.text or "")
    m = re.match(r"^کارتل[\s‌]+تغییر[\s‌]+نام[\s‌]+(.+)$", txt)
    arg = m.group(1) if m else ""

    if not arg:
        return await respond(update, f"✏️ این‌جوری بنویس: «کارتل تغییر نام [اسم جدید]»، هزینش {money(config.TEAM_RENAME_COST)}ـه")

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, res = await teams.rename_precheck(s, user, arg)
        old_name = res[0].name if ok else None
        display = res[1] if ok else None
        await s.commit()

    if not ok:
        return await respond(update, res)

    # اسم جدید تا لحظه تایید اینجا پارک میشه، موقع اجرا دوباره ولیدیت میشه
    context.user_data["pending_team_rename"] = display
    text = (
        f"<b>✏️ تغییر نام کارتل</b>\n\n"
        f"اسم فعلی: «{esc(old_name)}»\n"
        f"اسم جدید: «{esc(display)}»\n"
        f"💸 هزینه: {money(config.TEAM_RENAME_COST)}\n\n"
        "مطمئنی؟"
    )
    await respond(update, text, kb.team_confirm_kb("rename", update.effective_user.id))


# ───────── کوئست ─────────

async def quests_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        team = await teams.get_team_of(s, user.id)
        if not team:
            await s.commit()
            return await respond(
                update,
                "<b>📜 کوئست‌های گروهی</b>\n\n"
                "کوئست‌ها مال کارتل‌ان، اول عضو یه کارتل شو\n"
                f"«جوین کارتل [اسم]» (لول {fa_num(config.TEAM_JOIN_MIN_LEVEL)}+) یا «ساخت کارتل» (لول {fa_num(config.TEAM_CREATE_MIN_LEVEL)}+)",
            )

        daily = await teams._daily(s, team.id)
        text = _quests_text(team, daily)
        await s.commit()

    await respond(update, text, kb.team_back_kb())


# ───────── کنده‌کاری کارتلی ─────────

async def _push_mine_state(update: Update, context: ContextTypes.DEFAULT_TYPE, res: dict) -> None:
    """نمایش وضعیت کنده‌کاری، تکست جدید می‌فرسته یا پیام قدیمی رو ادیت می‌کنه"""
    status = res["status"]

    if status == "no_team":
        return await respond(update, "🏴 کنده‌کاری کارتلی مال کارتل‌ست، اول عضو یه کارتل شو 😅", kb.team_no_kb())
    if status == "too_few":
        return await respond(update, "⛏ کنده‌کاری کارتلی حداقل 3 نفره می‌خواد، اول کارتلتو بزرگ کن 😅", kb.team_back_kb())
    if status == "cooldown":
        return await respond(update, f"⏳ کنده‌کاری کارتلی هر {fa_num(config.TEAM_MINE_COOLDOWN_MINUTES)} دقیقه یه باره، {fa_dur(res['left'])} مونده", kb.team_back_kb())

    if status == "completed":
        return await respond(update, _mine_complete_text(res), kb.team_back_kb())

    text = _mine_progress_text(res)
    if res.get("restart"):
        text = "⏰ دفعه قبل به " + fa_num(int(config.TEAM_MINE_JOIN_PCT * 100)) + "% نرسید، پایین دوباره استارتش کردیم 👇\n\n" + text

    if update.callback_query:
        return await respond(update, text, kb.team_mine_kb())

    # متنی: اگه پیام نمایش قبلی هست ادیتش کن وگرنه جدید بفرست و بایند کن
    team = res["team"]
    sess = teams.TEAM_MINE_SESSIONS.get(team.id)
    if res["status"] == "started" or not sess or not sess.get("message_id"):
        msg = await update.message.reply_html(text, reply_markup=kb.team_mine_kb())
        teams.bind_mine_message(team.id, msg.chat_id, msg.message_id)
        return

    # پیوستن توسط نفر بعدی، پیام قبلی رو ادیت کن + به خودش جواب کوتاه بده
    try:
        await context.bot.edit_message_text(
            chat_id=sess["chat_id"], message_id=sess["message_id"],
            text=text, parse_mode="HTML",
            reply_markup=strip_home(update, kb.team_mine_kb()),
        )
    except BadRequest:
        # پیام قبلی دیگه نیس، همینجا تازه بفرست و بایند کن
        msg = await update.message.reply_html(text)
        teams.bind_mine_message(team.id, msg.chat_id, msg.message_id)
        return

    joined, needed, m_count = res["joined"], res["needed"], res["member_count"]
    remaining = max(0, needed - joined)
    ack = f"✔ پیوستی، {fa_num(joined)} نفر از {fa_num(m_count)} نفره"
    if remaining:
        ack += f" | {fa_num(remaining)} نفر تا تکمیل"
    await update.message.reply_html(ack)


async def team_mine_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        res = await teams.team_mine_join(s, user)
        await s.commit()
    await _push_mine_state(update, context, res)


# ───────── ساختمان‌های کارتل («کارتل ساختمان» / «کارتل ساخت» + دکمه) ─────────

def _buildings_text(team) -> str:
    tlevel = team.level or 1

    def _line(kind_emoji: str, title: str, effect_emoji: str, level: int, per_level: float) -> list[str]:
        pct_now = int(per_level * level * 100)
        out = [f"{kind_emoji} <b>{title}</b>، لول {fa_num(level)}"]
        out.append(f"{effect_emoji} قدرت فعلی: +{fa_num(pct_now)}% برای تمام اعضا")
        if level >= config.TEAM_BUILDING_MAX_LEVEL:
            out.append("⭐ مکس لوله")
        elif level + 1 > tlevel:
            out.append(f"🔒 ارتقای بعدی پس از رسیدن کارتل به لول {fa_num(level + 1)}")
        else:
            cost = teams.building_cost(level + 1)
            pct_next = int(per_level * (level + 1) * 100)
            out.append(f"⬆️ ارتقا به لول {fa_num(level + 1)}: +{fa_num(pct_next)}%")
            out.append(f"💰 هزینه: {money(cost)}")
        return out

    lines = [f"<b>🏗 ساختمان‌های کارتل «{esc(team.name)}»</b>", ""]
    lines.append(f"⭐ لول کارتل: {fa_num(tlevel)}")
    lines.append("📌 لول هیچ ساختمانی نمی‌تواند از لول کارتل بالاتر برود")
    lines.append("")
    lines += _line("⚔️", "ساختمان حمله", "💥", team.atk_bld or 0, config.TEAM_ATK_BONUS_PER_LEVEL)
    lines.append("")
    lines += _line("🛡", "ساختمان دفاع", "🛡", team.def_bld or 0, config.TEAM_DEF_BONUS_PER_LEVEL)
    lines.append("")
    lines.append(f"🏦 موجودی بانک کارتل: {money(team.bank)}")
    lines.append("")
    lines.append("👑 فقط رهبر کارتل می‌تواند ساختمان‌ها را ارتقا دهد")
    lines.append("⚔️ «کارتل ارتقا حمله»")
    lines.append("🛡 «کارتل ارتقا دفاع»")
    lines.append("")
    lines.append("💸 اعضا می‌توانند با دستور زیر به بانک کارتل کمک مالی کنند:")
    lines.append("«کارتل واریز 1200»")
    return "\n".join(lines)


async def render_buildings(update: Update, alert: str | None = None, extra: str | None = None) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        membership = await teams.get_membership(s, user.id)
        team = await teams.get_team_of(s, user.id)
        if not membership or not team:
            await s.commit()
            return await respond(update, _no_team_text(), kb.team_no_kb(), alert=alert)
        text = _buildings_text(team)
        if extra:
            text += f"\n\n{extra}"
        markup = kb.team_bld_kb(team, membership.role == "owner", user.telegram_id)
        await s.commit()
    await respond(update, text, markup, alert=alert)


async def buildings_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_buildings(update)


async def buildings_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_buildings(update)


# ───────── لیست اعضا («کارتل عضویت») ─────────

async def roster_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        team = await teams.get_team_of(s, user.id)
        if not team:
            await s.commit()
            return await respond(update, _no_team_text(), kb.team_no_kb())
        data = await teams.team_stats_data(s, team)
        await s.commit()

    lines = [f"<b>👥 اعضای کارتل «{esc(team.name)}»، {fa_num(data['count'])} نفر</b>", ""]
    by_id = {u.id: u for u in data["users"]}
    # اسم‌ها بر اساس لول، از بالا به پایین (مساوی بود، برد بیشتر اول)
    pairs = [(m, by_id.get(m.user_id)) for m in data["members"]]
    pairs.sort(key=lambda p: (-(p[1].level if p[1] else 0), -(p[1].wins if p[1] else 0)))
    for m, u in pairs:
        if not u:
            continue
        tag = {"owner": "👑", "admin": "🛡"}.get(m.role, "🔸")
        name = esc(u.first_name or u.username or "؟")
        temoji, tname = users.title_of(u)
        lines.append(f"{tag} {temoji} {name} <b>「{tname}」</b> | لول {fa_num(u.level)} | ⚔️ {fa_num(u.wins)} برد")
    lines.append("")
    lines.append("آمار کامل کارتل با «کارتل پروفایل»")
    await respond(update, "\n".join(lines), kb.team_back_kb())


# ───────── بانک کارتل («کارتل بانک») ─────────

async def team_bank_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        team = await teams.get_team_of(s, user.id)
        if not team:
            await s.commit()
            return await respond(update, _no_team_text(), kb.team_no_kb())
        bank = team.bank
        name = team.name
        await s.commit()

    text = (
        f"<b>🏦 بانک کارتل «{esc(name)}»</b>\n\n"
        f"💰 موجودی: {money(bank)}\n\n"
        "پول بانک از کجا میاد:\n"
        "⛏ کنده‌کاری کارتلی | 🏆 جایزه هفتگی رقابت‌ها | 💰 واریز اعضا\n\n"
        "کجا خرج میشه:\n"
        "🏗 ارتقای ساختمان حمله و دفاع توسط رهبر\n\n"
        "💰 کمک مالی: «کارتل واریز 1200»"
    )
    await respond(update, text, kb.team_bank_kb())


# ───────── واریز به بانک کارتل («کارتل واریز 1200») ─────────

async def team_deposit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = strip_bot_cmd(update.message.text or "")
    m = re.match(r"^کارتل[\s‌]+واریز[\s‌]+(.+)$", txt)
    amount = parse_amount(m.group(1)) if m else None
    if amount is None:
        return await respond(update, "❌ مبلغو درست بگو، مثلا «کارتل واریز 1200»")

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg = await teams.team_deposit(s, user, amount)
        team = await teams.get_team_of(s, user.id)
        bank = team.bank if team else 0
        tq = None
        if ok:
            tq = await teams.record_team_deposit(s, user, amount)  # کوئست کارتلی واریز به بانک
        await s.commit()

    if not ok:
        return await respond(update, msg)
    await respond(update, f"<b>{esc(msg)}</b>\n\n🏦 موجودی بانک کارتل: {money(bank)}")
    if tq:
        from handlers.common import announce_notes
        await announce_notes(update, [tq])


# ───────── ارتقای ساختمان («کارتل ارتقا حمله/دفاع» + دکمه‌ها) ─────────

async def _building_confirm_payload(update: Update, kind: str) -> tuple[str, object] | None:
    """متن صفحه تایید ارتقا + کیبورد، یا پیام خطا"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        membership = await teams.get_membership(s, user.id)
        team = await teams.get_team_of(s, user.id)
        tg = user.telegram_id
        details = (membership, team)
        await s.commit()

    membership, team = details
    if not membership or not team:
        await respond(update, _no_team_text(), kb.team_no_kb())
        return None
    if membership.role != "owner":
        await respond(update, "👑 ارتقای ساختمان فقط با رهبر کارتله")
        return None

    title = "⚔️ ساختمان حمله" if kind == "atk" else "🛡 ساختمان دفاع"
    level = team.atk_bld if kind == "atk" else team.def_bld
    per = config.TEAM_ATK_BONUS_PER_LEVEL if kind == "atk" else config.TEAM_DEF_BONUS_PER_LEVEL
    if level >= config.TEAM_BUILDING_MAX_LEVEL:
        await respond(update, f"⭐ {title} مکس لوله")
        return None

    cost = teams.building_cost(level + 1)
    pct_next = int(per * (level + 1) * 100)
    effect = "قدرت حمله" if kind == "atk" else "دفاع"
    text = (
        f"<b>🏗 ارتقای {title}، لول {fa_num(level)} ← {fa_num(level + 1)}</b>\n\n"
        f"💸 هزینه {money(cost)} از بانک کارتل\n"
        f"📈 {effect} همه اعضا +{fa_num(pct_next)}% میشه\n"
        f"🏦 موجودی بانک کارتل: {money(team.bank)}\n\n"
        "انجامش بدیم؟"
    )
    return text, kb.team_bld_confirm_kb(kind, tg)


async def team_upgrade_text(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str | None = None) -> None:
    """«کارتل ارتقا حمله» / «کارتل ارتقا دفاع»، صفحه تایید"""
    if kind is None:
        kind = "atk" if "حمله" in (update.message.text or "") else "def"
    payload = await _building_confirm_payload(update, kind)
    if payload:
        await respond(update, payload[0], payload[1])


async def team_upgrade_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه ارتقا از صفحه ساختمان‌ها (tbup)، فقط خود رهبر"""
    _, kind, owner_tg = parts(update)
    if update.effective_user.id != int(owner_tg):
        await update.callback_query.answer()  # غریبه هیچ واکنشی نمی‌بینه
        return
    payload = await _building_confirm_payload(update, kind)
    if payload:
        await respond(update, payload[0], payload[1])


async def team_upgrade_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """اجرای ارتقا بعد از تایید (tbcf)، فقط خود رهبر"""
    _, kind, owner_tg = parts(update)
    if update.effective_user.id != int(owner_tg):
        await update.callback_query.answer()  # غریبه هیچ واکنشی نمی‌بینه
        return

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg = await teams.upgrade_building(s, user, kind)
        await s.commit()

    if ok:
        return await render_buildings(update, alert="🏗 ساختمان ارتقا پیدا کرد", extra=msg)
    await render_buildings(update, alert=msg)


async def team_profile_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«کارتل پروفایل»، همون آمار کامل کارتل خودم با لول ساختمان‌ها و قدرتشون"""
    await render_my_team(update)


# ───────── 👑 مدیریت کارتل (فقط رهبر و مدیران) ─────────

async def _dm(context, tg: int | None, text: str, markup=None) -> None:
    """پی‌وی خبر به کاربر، بلاک‌کرده یا استارت‌نکرده بی‌خیال (مارکاپ اختیاری)"""
    if not tg:
        return
    bot = getattr(context, "bot", None)
    if bot is None:
        return
    try:
        await bot.send_message(tg, text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception:
        pass


async def _require_manager(update: Update):
    """(کاربر, عضویت, کارتل) مدیر رو می‌ده، نبود پیام مناسب می‌فرسته و None برمی‌گرده"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        m = await teams.get_membership(s, user.id)
        team = await teams.get_team_of(s, user.id)
        await s.commit()
    if not m or not team:
        await respond(update, _no_team_text(), kb.team_no_kb())
        return None
    if not teams.is_manager(m):
        await render_my_team(update, alert="👑 این بخش فقط مال رهبر و مدیران کارتله")
        return None
    return user, m, team


async def render_manage(update: Update, alert: str | None = None) -> None:
    """صفحه 👑 مدیریت کارتل"""
    got = await _require_manager(update)
    if not got:
        return
    user, m, team = got
    async with session_scope() as s:
        n = len(await teams.get_requests(s, team.id))
    text = (
        f"<b>👑 مدیریت کارتل «{esc(team.name)}»</b>\n\n"
        f"📨 {fa_num(n)} درخواست عضویت تو صفه"
    )
    await respond(update, text, kb.team_manage_kb(), alert=alert)


async def team_manage_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_manage(update)


async def render_requests(update: Update, alert: str | None = None) -> None:
    """صفحه 📨 درخواست‌های عضویت با دکمه قبول/رد برای تک تک"""
    got = await _require_manager(update)
    if not got:
        return
    user, m, team = got
    async with session_scope() as s:
        reqs = await teams.get_requests(s, team.id)
        await s.commit()

    lines = ["<b>📨 درخواست‌های عضویت</b>", ""]
    if not reqs:
        lines.append("درخواستی تو صف نیس")
    else:
        for i, (r, u) in enumerate(reqs, 1):
            uname = f" | @{u.username}" if u.username else ""
            lines.append(f"{fa_num(i)}. 👤 {esc(users.display_name(u))}{uname}")
            items_i = await users.get_item_levels(s, u.id)
            dogs_i = await dog_svc.get_user_dogs(s, u.id)
            atk_i, dfn_i = combat.combat_stats(u, items_i, dogs_i)
            lines.append(
                f"⭐ لول {fa_num(u.level)} | 🎖 مدال {fa_num(u.medals)} | 💥 قدرت کل {fa_num(atk_i + dfn_i)}"
            )
        lines += [
            "",
            "با دکمه‌ها قبول یا ردشون کن",
            "یا با دستور: «کارتل درخواست @یوزر قبول» / «رد»",
        ]
    markup = kb.team_requests_kb([(r.id, users.display_name(u)) for r, u in reqs],
                                 update.effective_user.id if update.effective_user else 0)
    await respond(update, "\n".join(lines), markup, alert=alert)


async def team_requests_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_requests(update)


async def _resolve_request(update: Update, context, req, target, team, accept: bool) -> str:
    """قبول/رد درخواست + دی‌ام به کاربر، متن نتیجه برای اعلان/جواب مدیر برمی‌گرده"""
    tn = esc(team.name)
    an = esc(users.display_name(target))
    async with session_scope() as s:
        req = await s.get(TeamRequest, req.id)
        target = await users.get_by_tg(s, target.telegram_id) if target else None
        if req is None or target is None:
            await s.commit()
            return "🤷 این درخواست دیگه نیس (قبول یا رد شده)"
        if accept:
            ok, why = await teams.accept_request(s, req, target)
            await s.commit()
            if not ok:
                await _dm(context, target.telegram_id, f"<b>❌ درخواستت برای کارتل «{tn}» قبول نشد</b>")
                return why
        else:
            await teams.reject_request(s, req)
            await s.commit()
    if accept:
        await _dm(context, target.telegram_id,
                  f"<b>🎉 درخواستت برای کارتل «{tn}» قبول شد</b>\n\nخوش اومدی به کارتل 🏴")
        return f"✅ «{an}» عضو کارتل شد"
    await _dm(context, target.telegram_id, f"<b>❌ درخواستت برای کارتل «{tn}» رد شد</b>")
    return "❌ درخواست رد شد"


async def team_request_resolve_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌های ✅ قبول و ❌ رد تو لیست 📨 درخواست‌های عضویت (قفل به بازکننده صفحه، غریبه ساکت)"""
    pz = parts(update)
    act, req_id = pz[1], int(pz[2])
    if len(pz) > 3 and update.callback_query is not None:
        try:
            if int(pz[3]) != update.effective_user.id:
                return await update.callback_query.answer()
        except (ValueError, TypeError):
            return await update.callback_query.answer()
    got = await _require_manager(update)
    if not got:
        return
    user, m, team = got
    async with session_scope() as s:
        row = await teams.get_request(s, req_id)
        if not row:
            await s.commit()
            return await render_requests(update, alert="🤷 این درخواست دیگه نیس (قبول یا رد شده)")
        req, target = row
        if req.team_id != team.id:
            await s.commit()
            return await render_my_team(update, alert="👑 این درخواست مال کارتل تو نیس")
        await s.commit()

    msg = await _resolve_request(update, context, req, target, team, accept=(act == "ok"))
    await render_requests(update, alert=msg)


async def team_request_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«کارتل درخواست @یوزر قبول|رد|اکسپت|ریجکت»، نسخه متنی دکمه‌ها"""
    txt = strip_bot_cmd(update.message.text or "")
    m2 = re.match(r"^کارتل[\s‌]+درخواست[\s‌]+(\S+)(?:[\s‌]+(قبول|رد|اکسپت|ریجکت))?$", txt)
    if not m2:
        return await respond(update, "🤷 این‌جوری بنویس: «کارتل درخواست @یوزر قبول» یا «کارتل درخواست @یوزر رد»")
    query, act = m2.group(1), m2.group(2)
    if not act:
        return await respond(update, "🤷 آخرش رو بگو: «قبول» یا «رد» (اکسپت و ریجکت هم جوابه)")
    accept = act in ("قبول", "اکسپت")

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        me = await teams.get_membership(s, user.id)
        team = await teams.get_team_of(s, user.id)
        if not me or not team or not teams.is_manager(me):
            await s.commit()
            return await respond(update, "👑 این بخش فقط مال رهبر و مدیران کارتله")
        row = await teams.find_request_by_query(s, me.team_id, query)
        if not row:
            await s.commit()
            return await respond(update, f"🤷 درخواستی از «{esc(query)}» تو صف نیس")
        req, target = row
        await s.commit()

    msg = await _resolve_request(update, context, req, target, team, accept)
    await respond(update, msg, kb.team_back_kb())


# ───────── 👢 اخراج عضو ─────────

KICK_PROMPT = (
    "👢 آیدی عددی یا @یوزرنیم یا بخشی از اسم عضو رو بفرست\n\n"
    "❌ اگر هم پشیمون شدی بنویس «لغو»"
)


async def team_kick_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه 👢 اخراج عضو تو مدیریت کارتل، ورودی بعدی کاربر سرچ میشه"""
    got = await _require_manager(update)
    if not got:
        return
    user, m, team = got
    async with session_scope() as s:
        u2 = await users.get_by_tg(s, user.telegram_id)
        users.set_pending(u2, "teamkick", None, chat_id_of(update))
        await s.commit()
    await respond(update, KICK_PROMPT)


async def kick_search_respond(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    """جستجوی عضو و نمایش صفحه تایید اخراج، مخاطب تایید فقط خود مدیره"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        me = await teams.get_membership(s, user.id)
        team = await teams.get_team_of(s, user.id)
        if not me or not team or not teams.is_manager(me):
            await s.commit()
            return await respond(update, "👑 این بخش فقط مال رهبر و مدیران کارتله")

        hit = await teams.find_team_member(s, me.team_id, query)
        if not hit:
            await s.commit()
            return await respond(update, "🤷 عضوی با این مشخصات تو کارتل پیدا نشد", kb.team_back_kb())
        mrow, target = hit
        okk, why = teams.can_kick(me, mrow)
        if not okk:
            await s.commit()
            return await respond(update, why, kb.team_back_kb())

        mid = mrow.id
        name = esc(users.display_name(target))
        uname = target.username
        lvl = target.level
        tg_id = target.telegram_id
        await s.commit()

    lines = [
        "<b>👤 عضو پیدا شد</b>", "",
        f"🏴 {name}",
        f"🆔 {fa_num(tg_id)}",
    ]
    if uname:
        lines.append(f"🔗 @{uname}")
    lines += [f"⭐ لول {fa_num(lvl)}", "", "واقعاً از کارتل اخراج شود؟"]
    await respond(update, "\n".join(lines), kb.kick_confirm_kb(mid, update.effective_user.id))


async def team_kick_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«کارتل کیک @یوزر»، اسم یا آیدی عددی هم جوابه"""
    txt = strip_bot_cmd(update.message.text or "")
    m2 = re.match(r"^کارتل[\s‌]+کیک[\s‌]+(.+)$", txt)
    if not m2:
        return await respond(update, "🤷 این‌جوری بنویس: «کارتل کیک @یوزر» (اسم یا آیدی هم میشه)")
    await kick_search_respond(update, context, m2.group(1))


async def team_kick_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """✅ اخراج از صفحه تایید (قفل به مدیرِ شروع‌کننده، غریبه ساکت)"""
    pz = parts(update)
    mid = int(pz[1])
    if len(pz) > 2 and update.callback_query is not None:
        try:
            if int(pz[2]) != update.effective_user.id:
                return await update.callback_query.answer()
        except (ValueError, TypeError):
            return await update.callback_query.answer()
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        me = await teams.get_membership(s, user.id)
        team = await teams.get_team_of(s, user.id)
        if not me or not team or not teams.is_manager(me):
            await s.commit()
            return await render_my_team(update, alert="👑 این بخش فقط مال رهبر و مدیران کارتله")

        mrow = await s.get(TeamMember, mid)
        if not mrow or mrow.team_id != me.team_id:
            await s.commit()
            return await render_manage(update, alert="🤷 عضو دیگه تو کارتل نیس")
        okk, why = teams.can_kick(me, mrow)
        target = await s.get(User, mrow.user_id)
        if not okk:
            await s.commit()
            return await render_manage(update, alert=why)

        target_tg = target.telegram_id if target else None
        name = esc(users.display_name(target)) if target else "؟"
        tname = esc(team.name)
        await s.delete(mrow)
        await s.commit()

    await _dm(context, target_tg, f"<b>👢 از کارتل «{tname}» اخراج شدی</b>")
    await render_manage(update, alert=f"👢 «{name}» از کارتل اخراج شد")


async def team_kick_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """❌ انصراف از اخراج، برگشت به مدیریت (قفل به مدیرِ شروع‌کننده، غریبه ساکت)"""
    pz = parts(update)
    if len(pz) > 1 and update.callback_query is not None:
        try:
            if int(pz[1]) != update.effective_user.id:
                return await update.callback_query.answer()
        except (ValueError, TypeError):
            return await update.callback_query.answer()
    await render_manage(update)


# ───────── 🛡 مدیر گذاشتن (فقط رهبر) ─────────

# ───────── «کارتل اد ادمین X» و «کارتل حذف ادمین X» با اسم جزئی + تأییدیه ─────────
# بخشی از اسم کافیه، حروف بزرگ/کوچیک فرقی نداره، قبل از اجرا تأیید می‌گیریم

async def team_admin_role_text(update: Update, context: ContextTypes.DEFAULT_TYPE, make_admin: bool) -> None:
    txt = strip_bot_cmd(update.message.text or "")
    m2 = re.match(r"^کارتل[\s‌]+(?:اد|حذف)[\s‌]+ادمین[\s‌]+(.+)$", txt)
    query = (m2.group(1) if m2 else "").strip()
    if not query:
        return await respond(update, "🤷 این‌جوری بنویس: «کارتل اد ادمین اسم عضو» یا «کارتل حذف ادمین اسم عضو»")

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        me = await teams.get_membership(s, user.id)
        if not me or me.role != "owner":
            await s.commit()
            return await respond(update, "👑 فقط رهبر می‌تونه مدیر بذاره یا برداره")
        hit = await teams.find_team_member(s, me.team_id, query)
        if not hit:
            await s.commit()
            return await respond(update, "🤷 عضوی با این مشخصات تو کارتل پیدا نشد، دقیق‌تر بنویس")
        mrow, target = hit
        if mrow.role == "owner":
            await s.commit()
            return await respond(update, "👑 خودت رهبری دیگه")
        if make_admin and mrow.role == "admin":
            await s.commit()
            return await respond(update, "🛡 همین الان مدیره")
        if not make_admin and mrow.role != "admin":
            await s.commit()
            return await respond(update, "👤 اصلا مدیر نیس که بخوای برداریش")
        member_id = mrow.id
        name = esc(users.display_name(target))
        team = await teams.get_team_of(s, user.id)
        tname = esc(team.name if team else "؟")
        await s.commit()

    verb = "🛡 مدیر کارتل کنم؟" if make_admin else "👤 مدیریتش رو بگیرم؟"
    text = (
        f"<b>{verb}</b>\n\n"
        f"👤 عضو پیدا شده: {name}\n"
        f"🏴 کارتل: «{tname}»\n\n"
        "مطمئنی؟"
    )
    await respond(update, text, kb.team_admin_confirm_kb(member_id, "add" if make_admin else "del", update.effective_user.id))


async def team_admin_add_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await team_admin_role_text(update, context, True)


async def team_admin_del_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await team_admin_role_text(update, context, False)


async def team_admin_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تأیید مدیر کردن/برداشتن بعد از پیدا شدن عضو با اسم جزئی (قفل به رهبرِ شروع‌کننده، غریبه ساکت)"""
    pz = parts(update)
    _, action, member_id = pz[0], pz[1], pz[2]
    if len(pz) > 3 and update.callback_query is not None:
        try:
            if int(pz[3]) != update.effective_user.id:
                return await update.callback_query.answer()
        except (ValueError, TypeError):
            return await update.callback_query.answer()
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        me = await teams.get_membership(s, user.id)
        mrow = await s.get(TeamMember, int(member_id))
        if not me or me.role != "owner" or not mrow or mrow.team_id != me.team_id:
            await s.commit()
            return await respond(update, "❌ این درخواست دیگه معتبر نیس", kb.team_back_kb())
        target = await s.get(User, mrow.user_id)
        name = esc(users.display_name(target)) if target else "؟"
        if mrow.role == "owner":
            await s.commit()
            return await respond(update, "❌ رهبر که نمیشه", kb.team_back_kb())
        if action == "add":
            if mrow.role == "admin":
                await s.commit()
                return await respond(update, "🛡 همین الان مدیره", kb.team_back_kb())
            mrow.role = "admin"
        else:
            if mrow.role != "admin":
                await s.commit()
                return await respond(update, "👤 اصلا مدیر نبود", kb.team_back_kb())
            mrow.role = "member"
        target_tg = target.telegram_id if target else None
        team = await teams.get_team_of(s, user.id)
        tname = esc(team.name if team else "؟")
        await s.commit()

    if action == "add":
        await _dm(context, target_tg, f"<b>🎉 تو کارتل «{tname}» مدیر شدی</b>\n\nبخش 👑 مدیریت کارتل برات بازه")
        return await respond(update, f"<b>🛡 «{name}» مدیر کارتل شد</b>", kb.team_back_kb())
    await _dm(context, target_tg, f"<b>👤 مدیریتت تو کارتل «{tname}» گرفته شد</b>")
    await respond(update, f"<b>👤 «{name}» دیگه مدیر نیس</b>", kb.team_back_kb())


async def team_admin_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لغو کارت تایید ادمین (قفل به رهبرِ شروع‌کننده، غریبه ساکت)"""
    pz = parts(update)
    if len(pz) > 2 and update.callback_query is not None:
        try:
            if int(pz[2]) != update.effective_user.id:
                return await update.callback_query.answer()
        except (ValueError, TypeError):
            return await update.callback_query.answer()
    await respond(update, "❌ لغو شد", kb.team_back_kb())


async def team_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«کارتل ادمین @یوزر»، عضو عادی ↔ مدیر، فقط رهبر"""
    txt = strip_bot_cmd(update.message.text or "")
    m2 = re.match(r"^کارتل[\s‌]+ادمین[\s‌]+(.+)$", txt)
    if not m2:
        return await respond(update, "🤷 این‌جوری بنویس: «کارتل ادمین @یوزر»")
    query = m2.group(1)

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        team = await teams.get_team_of(s, user.id)
        ok, why, target, made = await teams.toggle_admin(s, user, query)
        if not ok:
            await s.commit()
            return await respond(update, why)
        target_tg = target.telegram_id
        name = esc(users.display_name(target))
        tname = esc(team.name if team else "؟")
        await s.commit()

    if made:
        await _dm(context, target_tg, f"<b>🎉 تو کارتل «{tname}» مدیر شدی</b>\n\nبخش 👑 مدیریت کارتل برات بازه")
        return await respond(
            update,
            f"<b>🛡 «{name}» مدیر کارتل شد</b>\n\nبه 📨 درخواست‌های عضویت و بخش مدیریت دسترسی داره",
            kb.team_back_kb(),
        )
    await _dm(context, target_tg, f"<b>👤 مدیریتت تو کارتل «{tname}» گرفته شد</b>")
    await respond(update, f"<b>👤 «{name}» دیگه مدیر نیس</b>", kb.team_back_kb())


# ═════════ 👥 اعضای کارتل (راند ۲۰، درخواست کارفرما) ═════════

async def team_members_text(update: Update) -> None:
    """«کارتل اعضا» لیست اعضا با نقش و یوزرنیم (راند ۲۲: آیدی عددی به درخواست کارفرما حذف شد)"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        m = await teams.get_membership(s, user.id)
        team = await teams.get_team_of(s, user.id)
        if not m or not team:
            await s.commit()
            return await respond(update, "🏴 اصلا تو کارتلی نیستی که")
        rows = (await s.execute(
            select(TeamMember, User).join(User, User.id == TeamMember.user_id)
            .where(TeamMember.team_id == team.id).order_by(TeamMember.joined_at)
        )).all()
        await s.commit()

    lines = [f"<b>👥 اعضای «{esc(team.name)}» ({fa_num(len(rows))})</b>", ""]
    for i, (mem, u) in enumerate(rows, 1):
        em = "👑" if mem.role == "owner" else ("⭐" if mem.role == "admin" else "👤")
        uname = f"@{esc(u.username)}" if u.username else "بدون یوزرنیم"
        lines.append(f"{fa_num(i)}. {em} {esc(users.display_name(u))} | {uname}")
    lines += ["", "با «کارتل چت» باهاشون حرف بزن 💬"]
    await respond(update, "\n".join(lines), kb.team_back_kb())


# ═════════ 💬 چت کارتل (راند ۲۰، درخواست کارفرما) ═════════

async def team_chat_render(update: Update, alert: str | None = None) -> None:
    """صفحه چت کارتل با دکمه ارسال پیام و بروزرسانی"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        team = await teams.get_team_of(s, user.id)
        if not team:
            await s.commit()
            return await respond(update, "🏴 اصلا تو کارتلی نیستی که چتشو ببی بینی")
        text = await teams.chat_page(s, team)
        await s.commit()
    await respond(update, text, kb.team_chat_kb(), alert=alert)


async def team_chat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌های چت کارتل: صفحه | ارسال | رفرش | برگشت"""
    act = parts(update)[1]
    if act == "back":
        return await render_my_team(update)
    if act in ("page", "ref"):
        return await team_chat_render(update)
    if act == "send":
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            team = await teams.get_team_of(s, user.id)
            if not team:
                await s.commit()
                return await respond(update, "🏴 اصلا تو کارتلی نیستی که")
            users.set_pending(user, "teamchat", None, chat_id_of(update))
            await s.commit()
        return await respond(
            update,
            "✉️ پیامتو همینجا بنویس و بفرست، میره تو چت کارتل\n«لغو» هم کنسلش می‌کنه",
        )
