"""
ردیابی دوره‌ای بازیکن توسط ادمین 🕵️

«لاگ @یوزر» (فقط ادمین) کاربر رو فعال می‌کنه؛ از اون لحظه اکشن‌هاش روی یک ردیف
شمارنده‌ی تجمعی شمرده میشه و جاب هر ۱۰ دقیقه خلاصه رو به چت لاگ ادمین می‌فرسته و ریست می‌کنه
«توقف لاگ @یوزر» خاموشش می‌کنه و آمار جاری پاک میشه

چک «آیا این کاربر ردیابی میشه» روی کش حافظه‌ای _TRACKED انجام میشه (الگوی کش‌های forcejoin):
یک‌بار موقع استارت ربات از دیتابیس لود میشه، دستورهای ادمین لحظه‌ای سینکش می‌کنن و
جاب خلاصه هم هر دور ریفرشش می‌کنه تا نمونه‌های موازی هم بی‌خبر نمونن
نتیجه: برای کاربرای عادی (اکثریت) حتی یه کوئری اضافه هم نمیاد، فقط یه عضویت set تو حافظه‌ست
و فقط کاربرای ردیابی‌شونده یه خواندن PK و آپدیت ردیف تجمعی خودشون رو دارن
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import TrackedUser, TrackedUserStats, User
from utils import esc, fa_dur, fa_num, money, now_utc

logger = logging.getLogger("teriaky.tracklog")

# set حافظه‌ای user_id های درحال‌ردیابی، منبع حقیقت دیتابیسه و این فقط کش سریعه
_TRACKED: set[int] = set()

_INT_FIELDS = (
    "mine_count", "mine_tp", "mine_xp",
    "plant_count",
    "harvest_count", "harvest_tp", "harvest_xp",
    "sell_count", "sell_tp",
    "bat_hits", "bat_win", "bat_loss", "bat_tp", "bat_xp",
    "pv_count", "pv_win", "pv_loss", "pv_tp", "pv_xp",
    "casino_count", "casino_win", "casino_tp",
    "quest_count", "quest_tp", "quest_xp",
    "search_count", "search_tp",
)
_JSON_FIELDS = ("plant_seeds", "harvest_seeds", "sell_items")
# فیلدهایی که صفرنبودنشون یعنی دوره فعالیتی داشته (برای اسکیپ پیام خالی)
_COUNT_FIELDS = ("mine_count", "plant_count", "harvest_count", "sell_count",
                 "bat_hits", "bat_loss", "pv_count", "casino_count", "quest_count", "search_count")


def is_tracked(user_id: int) -> bool:
    """عضویت O(1) تو کش، تنها چکیه که سر راه اکشن‌های همه کاربراست"""
    return user_id in _TRACKED


async def refresh(session: AsyncSession) -> None:
    """لود کامل کش از دیتابیس (استارت ربات و هر دور جاب خلاصه)"""
    global _TRACKED
    ids = (await session.execute(
        select(TrackedUser.user_id).where(TrackedUser.active == True)  # noqa: E712
    )).scalars().all()
    _TRACKED = set(ids)


def _jget(txt: str | None) -> dict:
    try:
        return json.loads(txt or "{}")
    except (TypeError, ValueError):
        return {}


async def get_or_create_stats(session: AsyncSession, user_id: int) -> TrackedUserStats:
    """ردیف تجمعی کاربر، فقط برای ردیابی‌شونده‌ها صدا زده میشه پس سبک‌سازی لازم نیس"""
    st = await session.get(TrackedUserStats, user_id)
    if st is None:
        st = TrackedUserStats(user_id=user_id, period_start=now_utc())
        session.add(st)
        await session.flush()
    return st


def reset_stats_row(st: TrackedUserStats) -> None:
    """صفر کردن همه شمارنده‌ها و شروع دوره تازه"""
    for f in _INT_FIELDS:
        setattr(st, f, 0)
    for f in _JSON_FIELDS:
        setattr(st, f, "{}")
    st.period_start = now_utc()


def has_activity(st: TrackedUserStats | None) -> bool:
    return st is not None and any(getattr(st, f, 0) for f in _COUNT_FIELDS)


# ───────── شروع و توقف (دستورهای ادمین) ─────────

def _uname(target: User) -> str:
    return f"@{target.username}" if target.username else esc(target.first_name or "بدون‌یوزر")


async def start(session: AsyncSession, target: User) -> str:
    """فعال‌سازی ردیابی یه بازیکن، خروجی: متن تایید/اخطار برای ادمین"""
    uname = _uname(target)
    row = (await session.execute(
        select(TrackedUser).where(TrackedUser.user_id == target.id)
    )).scalar_one_or_none()
    if row and row.active:
        return (f"⚠️ {uname} همین الانم داره ردیابی میشه\n"
                f"خلاصه‌هاش هر {fa_num(config.TRACK_SUMMARY_SECONDS // 60)} دقیقه به چت لاگ میره")
    if row is None:
        row = TrackedUser(user_id=target.id)
        session.add(row)
    row.active = True
    row.started_at = now_utc()
    reset_stats_row(await get_or_create_stats(session, target.id))
    _TRACKED.add(target.id)
    text = (
        f"<b>🕵️ ردیابی {uname} شروع شد</b>\n\n"
        f"از همین لحظه اکشن‌هاش شمرده میشه و هر {fa_num(config.TRACK_SUMMARY_SECONDS // 60)} دقیقه خلاصه‌اش به چت لاگ میره\n"
        f"«توقف لاگ {uname}» هر وقت خواستی خاموشش می‌کنه"
    )
    if not config.ADMIN_LOG_CHAT_ID:
        text += "\n\n⚠️ ADMIN_LOG_CHAT_ID ست نشده، شمارش انجام میشه ولی خلاصه‌ای جایی ارسال نمیشه"
    logger.info("ردیابی %s (%s) توسط ادمین فعال شد", uname, target.id)
    return text


async def stop(session: AsyncSession, target: User) -> str:
    """خاموش کردن ردیابی + پاک شدن آمار جاری، خروجی: متن برای ادمین"""
    uname = _uname(target)
    row = (await session.execute(
        select(TrackedUser).where(TrackedUser.user_id == target.id)
    )).scalar_one_or_none()
    _TRACKED.discard(target.id)
    if not row or not row.active:
        return f"🤷 لاگی روی {uname} فعال نیس که بخوام خاموشش کنم"
    row.active = False
    st = await session.get(TrackedUserStats, target.id)
    if st is not None:
        await session.delete(st)  # آمار دوره جاری هم به درخواست کارفرما پاک میشه
    logger.info("ردیابی %s (%s) توسط ادمین متوقف شد", uname, target.id)
    return (f"<b>⏹ ردیابی {uname} متوقف شد</b>\n\n"
            "از این لحظه دیگه چیزی براش جمع یا ارسال نمیشه و آمار جاریش هم پاک شد")


# ───────── بامپ‌های تجمعی (از داخل سرویس‌های اکشن صدا زده میشن) ─────────

async def bump_mine(session: AsyncSession, user_id: int, tp: int, xp: int) -> None:
    if user_id not in _TRACKED:
        return
    st = await get_or_create_stats(session, user_id)
    st.mine_count += 1
    st.mine_tp += tp
    st.mine_xp += xp


async def bump_plant(session: AsyncSession, user_id: int, seed_key: str) -> None:
    if user_id not in _TRACKED:
        return
    st = await get_or_create_stats(session, user_id)
    st.plant_count += 1
    d = _jget(st.plant_seeds)
    d[seed_key] = d.get(seed_key, 0) + 1
    st.plant_seeds = json.dumps(d, ensure_ascii=False)


async def bump_harvest(session: AsyncSession, user_id: int, tp: int, xp: int,
                       n_harvests: int, seeds: dict[str, int]) -> None:
    if user_id not in _TRACKED or n_harvests <= 0:
        return
    st = await get_or_create_stats(session, user_id)
    st.harvest_count += n_harvests
    st.harvest_tp += tp
    st.harvest_xp += xp
    d = _jget(st.harvest_seeds)
    for k, n in seeds.items():
        d[k] = d.get(k, 0) + n
    st.harvest_seeds = json.dumps(d, ensure_ascii=False)


async def bump_sell(session: AsyncSession, user_id: int, items: dict[str, tuple[int, int]]) -> None:
    """فروش واقعی محصول (رسیدن محموله یا فروش به کاروان)، items: محصول ← (تعداد، تی‌پوینت)"""
    if user_id not in _TRACKED or not items:
        return
    st = await get_or_create_stats(session, user_id)
    st.sell_count += 1
    d = _jget(st.sell_items)
    for k, (qty, tp) in items.items():
        st.sell_tp += tp
        cur = d.get(k, [0, 0])
        d[k] = [cur[0] + qty, cur[1] + tp]
    st.sell_items = json.dumps(d, ensure_ascii=False)


async def bump_battle(session: AsyncSession, attacker_id: int, target_id: int,
                      steal: int, xp: int, killed: bool) -> None:
    """ضربه گروهی: مهاجم ضربه/غارت/تجربه (و برد با کشتن)، هدف فقط باخت موقع مردن"""
    if attacker_id in _TRACKED:
        st = await get_or_create_stats(session, attacker_id)
        st.bat_hits += 1
        st.bat_tp += steal
        st.bat_xp += xp
        if killed:
            st.bat_win += 1
    if killed and target_id in _TRACKED:
        st = await get_or_create_stats(session, target_id)
        st.bat_loss += 1


async def bump_pv(session: AsyncSession, attacker_id: int, won: bool, tp_net: int, xp: int) -> None:
    if attacker_id not in _TRACKED:
        return
    st = await get_or_create_stats(session, attacker_id)
    st.pv_count += 1
    st.pv_win += 1 if won else 0
    st.pv_loss += 0 if won else 1
    st.pv_tp += tp_net
    st.pv_xp += xp


async def bump_casino(session: AsyncSession, user_id: int, won: bool, tp_net: int) -> None:
    if user_id not in _TRACKED:
        return
    st = await get_or_create_stats(session, user_id)
    st.casino_count += 1
    st.casino_win += 1 if won else 0
    st.casino_tp += tp_net


async def bump_quest(session: AsyncSession, user_id: int, tp: int, xp: int) -> None:
    if user_id not in _TRACKED:
        return
    st = await get_or_create_stats(session, user_id)
    st.quest_count += 1
    st.quest_tp += tp
    st.quest_xp += xp


async def bump_search(session: AsyncSession, user_id: int, tp_net: int) -> None:
    if user_id not in _TRACKED:
        return
    st = await get_or_create_stats(session, user_id)
    st.search_count += 1
    st.search_tp += tp_net


# ───────── متن خلاصه دوره ─────────

def _seed_items(d: dict) -> str:
    out = []
    for k, n in d.items():
        sd = config.SEEDS.get(k) or {}
        out.append(f"{sd.get('emoji', '🌱')} {sd.get('name', k)} ×{fa_num(n)}")
    return "، ".join(out)


def summary_text(user: User, tr: TrackedUser, st: TrackedUserStats | None) -> str | None:
    """متن خلاصه دوره برای چت لاگ، بدون فعالیت هیچی برنمی‌گردونه (ضد اسپم خالی)"""
    if not has_activity(st):
        return None
    since = st.period_start or tr.started_at
    secs = max(0, int((now_utc() - since).total_seconds())) if since else 0
    uname = _uname(user)
    lines = [f"<b>🕵️ لاگ {uname}</b>", f"⏱ بازه: {fa_dur(secs)}", ""]
    tp_sum = 0
    xp_sum = 0

    if st.mine_count:
        tp_sum += st.mine_tp
        xp_sum += st.mine_xp
        lines.append(f"⛏ کنده‌کاری: {fa_num(st.mine_count)} بار | 💰 {money(st.mine_tp)} | ✨ {fa_num(st.mine_xp)} تجربه")

    plant = _jget(st.plant_seeds)
    if plant:
        lines.append(f"🌱 کاشت: {_seed_items(plant)}")

    if st.harvest_count:
        tp_sum += st.harvest_tp
        xp_sum += st.harvest_xp
        lines.append(f"🌾 برداشت: {fa_num(st.harvest_count)} بار | 💰 ارزش {money(st.harvest_tp)} | ✨ {fa_num(st.harvest_xp)} تجربه")
        hd = _jget(st.harvest_seeds)
        if hd:
            lines.append(f"▫️ {_seed_items(hd)}")

    if st.sell_count:
        tp_sum += st.sell_tp
        lines.append(f"🚚 فروش: {fa_num(st.sell_count)} بار | 💰 {money(st.sell_tp)}")
        sd_ = _jget(st.sell_items)
        if sd_:
            items = []
            for k, (qty, tp) in sd_.items():
                sd2 = config.SEEDS.get(k) or {}
                items.append(f"{sd2.get('emoji', '📦')} {sd2.get('name', k)} ×{fa_num(qty)} {money(tp)}")
            lines.append("▫️ " + "، ".join(items))

    if st.bat_hits or st.bat_loss:
        parts = [f"⚔️ نبرد: {fa_num(st.bat_hits)} ضربه"]
        if st.bat_win:
            parts.append(f"✅ {fa_num(st.bat_win)} برد")
        if st.bat_loss:
            parts.append(f"❌ {fa_num(st.bat_loss)} باخت")
        parts.append(f"💰 {money(st.bat_tp)}")
        parts.append(f"✨ {fa_num(st.bat_xp)} تجربه")
        lines.append(" | ".join(parts))
        tp_sum += st.bat_tp
        xp_sum += st.bat_xp

    if st.pv_count:
        tp_sum += st.pv_tp
        xp_sum += st.pv_xp
        lines.append(f"🔫 حمله پی‌وی: {fa_num(st.pv_count)} بار (✅ {fa_num(st.pv_win)} / ❌ {fa_num(st.pv_loss)})"
                     f" | 💰 خالص {money(st.pv_tp)} | ✨ {fa_num(st.pv_xp)} تجربه")

    if st.casino_count:
        tp_sum += st.casino_tp
        lines.append(f"🎰 قمارخانه: {fa_num(st.casino_count)} دست (✅ {fa_num(st.casino_win)}"
                     f" / ❌ {fa_num(st.casino_count - st.casino_win)}) | 💰 خالص {money(st.casino_tp)}")

    if st.quest_count:
        parts = [f"📋 کوئست روزانه: {fa_num(st.quest_count)} تا"]
        if st.quest_tp:
            parts.append(f"💰 {money(st.quest_tp)}")
        if st.quest_xp:
            parts.append(f"✨ {fa_num(st.quest_xp)} تجربه")
        lines.append(" | ".join(parts))
        tp_sum += st.quest_tp
        xp_sum += st.quest_xp

    if st.search_count:
        line = f"🔍 جستجو: {fa_num(st.search_count)} بار"
        tp_sum += st.search_tp
        if st.search_tp:
            line += f" | 💰 خالص {money(st.search_tp)}"
        lines.append(line)

    lines += ["", f"💰 خالص دوره: {money(tp_sum)} | ✨ {fa_num(xp_sum)} تجربه"]
    return "\n".join(lines)
