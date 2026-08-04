"""
جاب‌های زمان‌دار بازی (JobQueue):
آب و هوا هر ۲ ساعت + اعلان به گروه‌های فعال ۲۴ ساعت اخیر (با مکث بین ارسال) 🌦
بازار سیاه هر ۴ ساعت 📈 | کاروان برای گروه‌های فعال ۲۴ ساعت اخیر 🚛 (بردش هر ۲ دقیقه رفرش میشه)
یورش پلیس فعلاً به درخواست کارفرما خاموشه (POLICE_ENABLED=False) 🚔
نبض انرژی هر ۵ دقیقه به همه کاربرا (یه کوئری دسته‌جمعی، بدون حلقه تک‌تک) ⚡
جاروی ورودی‌های معلق عددی هر چند ثانیه (مهلت ۶۰ ثانیه‌ای واریز/برداشت و خرید منابع) ⏳
جاروی بوست انرژی‌زا هر نیم دقیقه، پیام «اثر انرژی زا به پایان رسید» میره پی‌وی ⚡
پاکسازی اکانت غیرعضوهای عضویت اجباری (بعد از مهلت مثلاً ۴۸ ساعته) هر ساعت 🧹
"""

import asyncio
import logging
import random
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy import update as sql_update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

import config
from database import session_scope
from keyboards import keyboards as kb
from models import GroupActivity, TrackedUser, TrackedUserStats, User
from services import world as world_svc
from utils import now_utc

logger = logging.getLogger("teriaky.jobs")


async def _send(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, markup=None):
    """ارسال امن، پیام فرستاده‌شده رو برمی‌گردونه (گروه ریموو/بلاک None)"""
    try:
        return await context.bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
    except (BadRequest, Forbidden):
        return None
    except Exception as e:
        logger.warning("send to %s failed: %s", chat_id, e)
        return None


# ───────── آب و هوا 🌦 ─────────

async def weather_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    from services import power as power_svc
    async with session_scope() as s:
        key, rolled = await world_svc.ensure_weather(s)
        groups = await world_svc.active_group_ids(s, config.WEATHER_GROUP_ACTIVE_HOURS) if rolled else []
        offs = await power_svc.off_group_ids(s) if rolled else set()
        await s.commit()

    if not rolled:
        return
    left = max(0, int((rolled["until"] - world_svc.now_utc()).total_seconds())) if rolled.get("until") else None
    text = world_svc.weather_announce_text(key, rolled.get("pct"), left)
    for gid in groups:
        if gid in offs:
            continue  # گروه خاموشه (/botoff)
        await _send(context, gid, text)
        await asyncio.sleep(config.WEATHER_GROUP_SEND_DELAY)  # پخش یواش، تلگرام محدود نکنه


# ───────── بازار سیاه 📈 ─────────

async def market_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        await world_svc.ensure_market(s)
        await s.commit()


# ───────── نبض انرژی ⚡ ─────────

def _energy_pulse_stmt():
    """UPDATE دسته‌جمعی: min(انرژی + نبض, سقف) برای همه کاربرای زیر سقف
    سقف هر کاربر پویاست (راند ۱۵): MAX_ENERGY + per × لول استقامت، توی SQL خام حساب میشه"""
    from sqlalchemy import case
    per = int((config.SKILLS.get("stamina") or {}).get("per", 0))
    cap = config.MAX_ENERGY + per * User.skill_stamina
    return (
        sql_update(User)
        .where(User.energy < cap)
        .values(energy=case(
            (User.energy + config.ENERGY_PULSE_AMOUNT > cap, cap),
            else_=User.energy + config.ENERGY_PULSE_AMOUNT,
        ))
    )


async def energy_pulse_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """هر ۵ دقیقه ۲۰ انرژی به همه کاربرا، یه کوئری دسته‌جمعی که سرور سنگین نشه"""
    async with session_scope() as s:
        await s.execute(_energy_pulse_stmt())
        await s.commit()


# ───────── کاروان 🚛 ─────────

async def caravan_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    # ۱) کاروانهای منقضی رو تسویه کن، بردشون پاک میشه و پیام «رد شد» تازه میاد
    for chat_id in list(world_svc.CARAVANS.keys()):
        cv = world_svc.CARAVANS.get(chat_id)
        mid = cv.get("message_id") if cv else None
        async with session_scope() as s:
            res = await world_svc.caravan_expire(s, chat_id)
            await s.commit()
        if res is not None:
            if mid:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                except (BadRequest, Forbidden):
                    pass
            await _send(context, chat_id, world_svc.caravan_end_text(res["rewards"], killed=False))

    # ۲) اسپون جدید برای گروه‌های فعال ۲۴ ساعت اخیر (گروه‌های خاموش نه)
    from services import power as power_svc
    async with session_scope() as s:
        offs = await power_svc.off_group_ids(s)
        groups = [g for g in await world_svc.active_group_ids(s, config.CARAVAN_GROUP_ACTIVE_HOURS) if g not in offs]
        cooldown_limit = now_utc() - timedelta(hours=config.CARAVAN_GROUP_COOLDOWN_HOURS)
        spawns: list[int] = []
        for gid in groups:
            if world_svc.caravan_active(gid):
                continue
            row = await s.get(GroupActivity, gid)
            if row and row.last_caravan_at and row.last_caravan_at > cooldown_limit:
                continue
            # شانس هر تیک: CARAVAN_SPAWN_CHANCE در ساعت → تقسیم بر تعداد تیک هر ساعت
            per_tick = config.CARAVAN_SPAWN_CHANCE * (config.CARAVAN_TICK_SECONDS / 3600)
            if random.random() >= per_tick:
                continue
            if row:
                row.last_caravan_at = now_utc()
            else:
                s.add(GroupActivity(chat_id=gid, last_caravan_at=now_utc()))
            spawns.append(gid)
        await s.commit()

    for gid in spawns:
        cv = world_svc.caravan_spawn(gid)
        msg = await _send(context, gid, world_svc.caravan_board_text(cv), kb.caravan_kb())
        if msg:
            cv["message_id"] = msg.message_id


async def caravan_refresh_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """برد کاروان فقط با این تایمر رفرش میشه (نه بعد هر ضربه)، دمیج‌ها رو تازه می‌کنه"""
    for chat_id, cv in list(world_svc.CARAVANS.items()):
        if world_svc.caravan_active(chat_id) is None:
            continue
        mid = cv.get("message_id")
        if not mid:
            continue
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=mid,
                text=world_svc.caravan_board_text(cv), parse_mode="HTML",
                reply_markup=kb.caravan_kb(),
            )
        except BadRequest:
            pass
        except Exception as e:
            logger.debug("رفرش برد کاروان %s خطا: %s", chat_id, e)


# ───────── محموله‌های در راه 🚚 ─────────

async def shipment_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """محموله‌های رسیده تسویه میشن و نتیجه (سالم | توقیف | تأخیر) پی‌وی کاربر اطلاع میره"""
    from services import smuggle as smg
    async with session_scope() as s:
        events = await smg.process_due_shipments(s)
        await s.commit()
    for ev in events:
        await _send(context, ev.get("chat") or ev["tg"], ev["text"])  # چت مبدأ ارسال محموله (راند ۱۳)


# ───────── جاروی بوست انرژی‌زا ⚡ ─────────

async def boost_sweep_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """بوست حمله انرژی‌زای تموم‌شده جارو میشه و خبر پایان اثر به پی‌وی کاربر میره (راند ۱۳)"""
    from services import energy as energy_svc
    async with session_scope() as s:
        tgs = await energy_svc.process_expired_boosts(s)
        await s.commit()
    for tg_id in tgs:
        await _send(context, tg_id, "⚡ اثر انرژی‌زا به پایان رسید")


# ───────── کاروان قاچاق 🚚 ─────────

async def smuggler_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """اسپون/انقضای کاروان قاچاق، پیام اعلان کاروان رفتنی به «جمع کرد رفت» ادیت میشه"""
    from handlers import smuggle as smuggle_h
    from services import smuggle as smg
    async with session_scope() as s:
        spawned, expired = await smg.caravan_tick(s)
        await s.commit()
    if expired:
        text = smg.caravan_gone_text(expired)
        for chat_id, mid in expired.get("msgs", []):
            try:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=mid, text=text, parse_mode="HTML")
            except Exception:
                pass  # پیام پاک شده یا قدیمیه، مهم نیس
    if spawned:
        await smuggle_h.announce_caravan(context, spawned)


# ───────── جاروی ورودی‌های معلق عددی ⏳ ─────────

_NUMERIC_PENDING = ("bankdep", "bankwd", "resbuy", "trf_to", "trf_amt")


async def pending_sweep_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    ورودی‌های معلق عددی (مبلغ بانک | تعداد خرید منابع) بعد از مهلت کانفیگ خودکار بی‌خیال میشن
    پیام بی‌خیالی به همون چتی می‌ره که کار شروع شده بود
    """
    from services import users as users_svc
    cutoff = now_utc() - timedelta(seconds=config.PENDING_TIMEOUT_SECONDS)
    expired: list[tuple[int, int]] = []
    async with session_scope() as s:
        q = select(User).where(
            User.pending_action.in_(_NUMERIC_PENDING),
            User.pending_at.isnot(None),
            User.pending_at <= cutoff,
        )
        for u in (await s.execute(q)).scalars():
            expired.append((u.telegram_id, u.pending_chat_id or u.telegram_id))
            users_svc.set_pending(u, None)
        await s.commit()
    for tg, chat in expired:
        await _send(context, chat, "به دلیل عدم پاسخ، عملیات رو بیخیال شدیم")
    if expired:
        logger.info("جاروی ورودی معلق: %d مورد منقضی شد", len(expired))


# ───────── یورش پلیس 🚔 (فعلاً غیرفعال) ─────────

async def police_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        records = await world_svc.police_wave(s)
        await s.commit()

    for rec in records:
        tg = rec["user"].telegram_id
        await _send(context, tg, world_svc.police_report_text(rec))


# ───────── پاکسازی اکانت غیرعضوهای مهلت‌گذشته 🧹 (عضویت اجباری) ─────────

async def fj_wipe_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    هر ساعت: غیرعضوهایی که بیشتر از FORCE_JOIN_WIPE_AFTER_HOURS لفت‌ان ریست میشن
    لفت لحظه‌ای فقط دسترسی پی‌وی رو می‌بره (گیت)، ریست واقعی با مهلت انجام میشه
    تا کسی که تصادفی لفت داده و برمی‌گرده اذیت نشه و کلاهبردارِ جوین-و-لفت هم نتونه سوءاستفاده کنه
    """
    from services import forcejoin as fj, users as users_svc
    st = await fj.get_settings_cached()
    if not (st["on"] and st["channel"]):
        return
    cutoff = now_utc() - timedelta(hours=config.FORCE_JOIN_WIPE_AFTER_HOURS)
    wiped: list[int] = []
    async with session_scope() as s:
        q = select(User).where(
            User.fj_member_status == 0,
            User.fj_left_at.isnot(None),
            User.fj_left_at <= cutoff,
        )
        for u in (await s.execute(q)).scalars():
            if u.telegram_id in config.ADMIN_IDS:
                continue  # ادمین‌ها از پاکسازی خارجن
            await users_svc.wipe_account(s, u)
            u.fj_member_status = u.fj_checked_at = u.fj_left_at = None
            wiped.append(u.telegram_id)
        await s.commit()
    for tg_id in wiped:
        fj.member_cache_drop(tg_id)
        await _send(context, tg_id,
                    "⚠️ حساب بازی‌ات ریست شد\n\n"
                    "چون خیلی وقته عضو کانال نیسی بازی از نو شروع میشه\n"
                    "برای برگشتن کافیه دوباره عضو بشی و /start رو بزنی")
    if wiped:
        logger.info("پاکسازی عضویت اجباری: %d اکانت غیرعضو ریست شد", len(wiped))


# ───────── ثبت جاب‌ها ─────────

# ───────── لاگ ردیابی بازیکن 🕵 (خلاصه دوره‌ای به چت لاگ ادمین) ─────────

async def track_summary_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    from services import tracklog as tl
    if not config.ADMIN_LOG_CHAT_ID:  # چت لاگ ست نشده، فیچر عملاً خاموشه
        return
    async with session_scope() as s:
        await tl.refresh(s)  # کش حافظه هم که شده ریفرش، مثلاً نمونه موازی یوزری رو لاگ کرده باشه
        rows = (await s.execute(
            select(TrackedUser).where(TrackedUser.active == True)  # noqa: E712
        )).scalars().all()
        items: list[tuple[int, str]] = []
        for tr in rows:
            user = await s.get(User, tr.user_id)
            st = await s.get(TrackedUserStats, tr.user_id)
            txt = tl.summary_text(user, tr, st) if user else None
            if txt:  # بدون فعالیت تو بازه، چیزی نمی‌فرستیم (ضد اسپم خالی)
                items.append((tr.user_id, txt))
        await s.commit()

    sent: list[int] = []
    for uid, txt in items:
        if await _send(context, config.ADMIN_LOG_CHAT_ID, txt):
            sent.append(uid)
    if sent:  # ریست فقط برای ارسال‌های موفق، ناامید دوره بعد دوباره تلاش می‌کنه
        async with session_scope() as s:
            for uid in sent:
                st = await s.get(TrackedUserStats, uid)
                if st is not None:
                    tl.reset_stats_row(st)
            await s.commit()


def register_jobs(app) -> None:
    """ثبت جاب‌های دوره‌ای روی JobQueue، بدون دیپندنسی جاب پاکش میشه"""
    jq = getattr(app, "job_queue", None)
    if jq is None:
        logger.warning("JobQueue available نیس، جاب‌های زمان‌دار غیرفعال شدن (python-telegram-bot[job-queue] نصب کن)")
        return

    jq.run_repeating(weather_job, interval=config.WEATHER_ROLL_SECONDS, first=60, name="weather")
    jq.run_repeating(market_job, interval=config.MARKET_ROLL_SECONDS, first=90, name="market")
    jq.run_repeating(caravan_job, interval=config.CARAVAN_TICK_SECONDS, first=30, name="caravan")
    jq.run_repeating(caravan_refresh_job, interval=config.CARAVAN_BOARD_REFRESH_SECONDS, first=60, name="caravan-board")
    jq.run_repeating(pending_sweep_job, interval=config.PENDING_SWEEP_SECONDS, first=45, name="pending-sweep")
    jq.run_repeating(shipment_job, interval=config.SHIPMENT_JOB_SECONDS, first=20, name="shipment")
    jq.run_repeating(boost_sweep_job, interval=config.ENERGY_BOOST_SWEEP_SECONDS, first=config.ENERGY_BOOST_SWEEP_SECONDS, name="boost-sweep")
    jq.run_repeating(smuggler_job, interval=config.SMUGGLER_TICK_SECONDS, first=40, name="smuggler")
    if config.POLICE_ENABLED:
        jq.run_repeating(police_job, interval=config.POLICE_ROLL_SECONDS, first=120, name="police")
    jq.run_repeating(energy_pulse_job, interval=config.ENERGY_PULSE_SECONDS, first=config.ENERGY_PULSE_SECONDS, name="energy-pulse")
    jq.run_repeating(fj_wipe_job, interval=config.FORCE_JOIN_WIPE_SCAN_SECONDS, first=300, name="fj-wipe")
    if config.ADMIN_LOG_CHAT_ID:
        jq.run_repeating(track_summary_job, interval=config.TRACK_SUMMARY_SECONDS,
                         first=config.TRACK_SUMMARY_SECONDS, name="track-summary")
    # ادیت خودکار آخرین پیام آمار ادمین، هر ۱ ساعت یه بار (سبک، فشار به سرور نمیاره)
    from handlers.admin import stats_autoedit_job
    jq.run_repeating(
        stats_autoedit_job,
        interval=config.STATS_AUTOEDIT_SECONDS, first=config.STATS_AUTOEDIT_SECONDS,
        name="stats-autoedit",
    )
    logger.info(
        "جاب‌های زمان‌دار فعال شدن: آب‌وهوا | بازار | کاروان | برد کاروان | جاروی ورودی معلق | محموله | جاروی بوست انرژی‌زا | کاروان قاچاق | نبض انرژی | پاکسازی غیرعضو | ادیت ساعتی آمار%s%s",
        " | پلیس" if config.POLICE_ENABLED else "",
        " | لاگ ردیابی بازیکن" if config.ADMIN_LOG_CHAT_ID else "",
    )
