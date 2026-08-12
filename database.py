"""اتصال دیتابیس — SQLAlchemy async روی SQLite (قابل سوییچ به PostgreSQL)"""

import asyncio
import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

import config

logger = logging.getLogger(__name__)

# راند ۳۵ (درخواست کارفرما): تا وقتی مهاجرت اسکیما تموم نشده هیچ سشنی (هندلر/جاب) باز نمیشه
_schema_ready = asyncio.Event()


class Base(DeclarativeBase):
    pass


engine = create_async_engine(config.DATABASE_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """ساخت جداول و ایندکس‌ها + مایگریشن سبک ستون‌های جدید روی دیتابیس قدیمی"""
    from models import models as _models  # noqa: F401  (ثبت مدل‌ها روی metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sync_model_columns)   # راند ۳۵: سینک خودکار ستون‌های همه مدل‌ها با دیتابیس واقعی
        await conn.run_sync(_ensure_columns)
        await conn.run_sync(_ensure_indexes)
        await conn.run_sync(_migrate_data)
    _schema_ready.set()  # از این لحظه هندلرها و جاب‌ها اجازه‌ی کوئری دارن


def _default_literal(col, is_sqlite: bool) -> str:
    """
    لیترال SQL مقدار پیش‌فرض امن برای ستون NOT NULLِ تازه‌اضافه‌شده (راند ۳۵)
    اولویت با default اسکالر مدله؛ کال‌بل‌ها (مثل now_utc) تو DDL نمیشن و به فالبک نوع برمی‌گردن
    """
    from sqlalchemy import Boolean, DateTime, Integer

    d = getattr(col, "default", None)
    arg = getattr(d, "arg", None) if d is not None else None
    if callable(arg):
        arg = None
    if arg is None:
        if isinstance(col.type, Boolean):
            return "0" if is_sqlite else "FALSE"
        if isinstance(col.type, Integer):
            return "0"
        if isinstance(col.type, DateTime):
            return "'1970-01-01 00:00:00'"   # نقطه صفر امن برای ستون تاریخ اجباریِ قدیمی‌نشان
        return "''"
    if isinstance(arg, bool):
        return ("1" if arg else "0") if is_sqlite else ("TRUE" if arg else "FALSE")
    if isinstance(arg, (int, float)):
        return str(arg)
    return "'" + str(arg).replace("'", "''") + "'"


def _sync_model_columns(sync_conn) -> None:
    """
    راند ۳۵ (درخواست کارفرما): سینک خودکار اسکیما — همه جدول‌ها و ستون‌های مدل فعلی با دیتابیس واقعی مقایسه میشن
    هر ستونی که مدل داره ولی دیتابیس نداره با ALTER TABLE اضافه میشه (nullable هم NULL، غیر nullable هم مقدار پیش‌فرض امن)
    idempotent ـه و فقط اضافه می‌کنه، هیچ‌وقت ستون یا دیتایی رو حذف نمی‌کنه
    لیست دستی _NEW_COLUMNS پایین می‌مونه ولی عملاً این تابع خودش همه چیو پوشش میده
    """
    from sqlalchemy import text

    is_sqlite = sync_conn.dialect.name == "sqlite"
    for table in Base.metadata.sorted_tables:
        if is_sqlite:
            rows = sync_conn.execute(text(f'PRAGMA table_info("{table.name}")')).fetchall()
            if not rows:
                continue   # جدول تازه ساخته شده با create_all، ستون‌هاش کامله
            existing = {r[1] for r in rows}
        else:
            rows = sync_conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name=:t AND table_schema='public'"),
                {"t": table.name},
            ).fetchall()
            existing = {r[0] for r in rows}
        for col in table.c:
            if col.name in existing:
                continue
            ddl_type = col.type.compile(dialect=sync_conn.dialect)
            if col.nullable or col.primary_key:
                sql = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl_type}'
            else:
                sql = (f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl_type}'
                       f' NOT NULL DEFAULT {_default_literal(col, is_sqlite)}')
            try:
                sync_conn.execute(text(sql))
                logger.warning("اسکیما قدیمی بود: ستون %s.%s خودکار به دیتابیس اضافه شد", table.name, col.name)
            except Exception:
                logger.exception("اضافه کردن خودکار ستون %s.%s به دیتابیس شکست خورد", table.name, col.name)


# ستون‌هایی که تو فازهای بعدی به جدول‌های موجود اضافه شدن
_NEW_COLUMNS = {
    "users": [
        ("last_harvest_at", "DATETIME"),
        ("feeds_used_today", "INTEGER NOT NULL DEFAULT 0"),
        ("feed_day", "VARCHAR(10)"),
        ("pending_action", "VARCHAR(16)"),
        ("pending_value", "VARCHAR(64)"),
        ("bank_acc", "VARCHAR(8)"),
        ("bank_balance", "INTEGER NOT NULL DEFAULT 0"),
        ("bank_level", "INTEGER NOT NULL DEFAULT 1"),
        ("shelter_level", "INTEGER NOT NULL DEFAULT 0"),
        ("last_search_at", "DATETIME"),
        ("last_casino_at", "DATETIME"),
        ("last_trf_at", "DATETIME"),
        ("last_snitch_at", "DATETIME"),
        ("snitch_count", "INTEGER NOT NULL DEFAULT 0"),
        ("snitch_window_at", "DATETIME"),
        ("khaye_until", "DATETIME"),
        ("gems", "INTEGER NOT NULL DEFAULT 0"),
        ("caravan_level", "INTEGER NOT NULL DEFAULT 1"),
        ("jailed_until", "DATETIME"),
        ("lumber_stock", "INTEGER NOT NULL DEFAULT 0"),
        ("ironmill_stock", "INTEGER NOT NULL DEFAULT 0"),
        ("last_seen_at", "DATETIME"),
        ("shield_until", "DATETIME"),
        ("pv_attack_at", "DATETIME"),
        ("dq_date", "VARCHAR(10)"),
        ("dq_data", "VARCHAR(1024)"),
        ("hp", "INTEGER"),
        ("dead_until", "DATETIME"),
        ("wood", "INTEGER NOT NULL DEFAULT 0"),
        ("iron", "INTEGER NOT NULL DEFAULT 0"),
        ("legendary_parts", "INTEGER NOT NULL DEFAULT 0"),
        ("axe_level", "INTEGER NOT NULL DEFAULT 1"),
        ("pick_level", "INTEGER NOT NULL DEFAULT 1"),
        ("lumber_level", "INTEGER NOT NULL DEFAULT 0"),
        ("ironmill_level", "INTEGER NOT NULL DEFAULT 0"),
        ("company_at", "DATETIME"),
        ("medals", "INTEGER NOT NULL DEFAULT 0"),
        ("medals_day", "INTEGER NOT NULL DEFAULT 0"),
        ("medals_day_date", "VARCHAR(10)"),
        ("medals_week", "INTEGER NOT NULL DEFAULT 0"),
        ("medals_week_id", "VARCHAR(10)"),
        ("fj_member_status", "INTEGER"),
        ("fj_checked_at", "DATETIME"),
        ("fj_left_at", "DATETIME"),
        ("first_mine_at", "DATETIME"),
        ("first_plant_at", "DATETIME"),
        ("first_harvest_at", "DATETIME"),
        ("first_shipment_at", "DATETIME"),
        ("first_plot_at", "DATETIME"),
        ("onb_done_at", "DATETIME"),
        ("lb_hidden", "INTEGER NOT NULL DEFAULT 0"),
        ("pending_at", "DATETIME"),
        ("pending_chat_id", "BIGINT"),
        ("skill_points", "INTEGER"),
        ("skill_power", "INTEGER NOT NULL DEFAULT 0"),
        ("skill_speed", "INTEGER NOT NULL DEFAULT 0"),
        ("skill_defense", "INTEGER NOT NULL DEFAULT 0"),
        ("skill_loot", "INTEGER NOT NULL DEFAULT 0"),
        ("equipped_weapon", "VARCHAR(32)"),
        ("equipped_armor", "VARCHAR(32)"),
        ("poison_until", "DATETIME"),
        ("last_heal_at", "DATETIME"),
        ("boost_until", "DATETIME"),
        ("skill_stamina", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "group_activity": [
        ("title", "VARCHAR(128)"),
        ("msgs_hour", "INTEGER NOT NULL DEFAULT 0"),
        ("hour_key", "VARCHAR(16)"),
    ],
                "inventory": [
            ("level", "INTEGER NOT NULL DEFAULT 1"),
            ("ammo", "INTEGER"),
        ],
"plots": [
        ("built_at", "DATETIME"),
    ],
    "dogs": [
        ("personality", "VARCHAR(16)"),
        ("feeds_today", "INTEGER NOT NULL DEFAULT 0"),
        ("feed_day", "VARCHAR(10)"),
    ],
    "teams": [
        ("points", "INTEGER NOT NULL DEFAULT 0"),
        ("week_points", "INTEGER NOT NULL DEFAULT 0"),
        ("atk_bld", "INTEGER NOT NULL DEFAULT 0"),
        ("def_bld", "INTEGER NOT NULL DEFAULT 0"),
        ("level", "INTEGER NOT NULL DEFAULT 1"),
        ("xp", "INTEGER NOT NULL DEFAULT 0"),
        ("lb_hidden", "INTEGER NOT NULL DEFAULT 0"),
        ("war_wins", "INTEGER NOT NULL DEFAULT 0"),
        ("war_losses", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "team_members": [
        ("join_medals", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "team_daily": [
        ("qprog", "VARCHAR(256)"),
        ("qdone", "VARCHAR(128)"),
    ],
    "shipments": [
        ("chat_id", "BIGINT"),
        ("seize_pct", "INTEGER"),
    ],
}

# ری‌نیم بذرها — ردیف‌های دیتابیس‌های قدیمی رو به کلید جدید منتقل می‌کنیم
_LEGACY_SEEDS = {"koka": "peyote", "ghat": "teriak"}


def _ensure_columns(sync_conn) -> None:
    """اگه دیتابیس قدیمی ستون جدید نداشت، با ALTER TABLE اضافه‌ش کن (فقط SQLite؛ تو Postgres اسکیما از create_all کامله)"""
    if sync_conn.dialect.name != "sqlite":
        return
    from sqlalchemy import text

    for table, cols in _NEW_COLUMNS.items():
        rows = sync_conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        existing = {r[1] for r in rows}
        for name, coltype in cols:
            if name not in existing:
                try:
                    sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}"))
                    logger.warning("ستون لگاسی %s.%s با _NEW_COLUMNS اضافه شد", table, name)
                except Exception:
                    logger.exception("ALTER TABLE لگاسی برای %s.%s شکست خورد", table, name)


# ایندکس‌هایی که بعداً برای سرعت کوئری‌های آمار پنل ادمین اضافه شدن
# روی جدول‌های دیتابیس قدیمی create_all ساخته نمیشن، پس اینجا یدونه‌ی IF NOT EXISTS دارن
_NEW_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_users_created_at ON users (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_users_last_seen_at ON users (last_seen_at)",
    "CREATE INDEX IF NOT EXISTS ix_plots_status ON plots (status)",
    "CREATE INDEX IF NOT EXISTS ix_action_events_action ON action_events (action)",
    "CREATE INDEX IF NOT EXISTS ix_action_events_at ON action_events (at)",
    "CREATE INDEX IF NOT EXISTS ix_action_events_action_at ON action_events (action, at)",
    "CREATE INDEX IF NOT EXISTS ix_seed_sales_seed_key ON seed_sales (seed_key)",
    "CREATE INDEX IF NOT EXISTS ix_seed_sales_at ON seed_sales (at)",
    "CREATE INDEX IF NOT EXISTS ix_seed_sales_seed_at ON seed_sales (seed_key, at)",
)


def _ensure_indexes(sync_conn) -> None:
    """ایندکس‌های جدید رو اگه روی دیتابیس قدیمی نیس بساز"""
    from sqlalchemy import text

    for ddl in _NEW_INDEXES:
        try:
            sync_conn.execute(text(ddl))
        except Exception:
            logger.debug("ساخت ایندکس %s رد شد (جدول هنوز نیس؟ دفعه بعد)", ddl[:60], exc_info=True)


def _migrate_data(sync_conn) -> None:
    """مایگریشن دیتا — بذرهای قدیمی (کوکا/قات) به کلیدهای جدید + سقف لول ۲۰"""
    from sqlalchemy import text

    for old, new in _LEGACY_SEEDS.items():
        try:
            sync_conn.execute(text("UPDATE seed_stock SET seed_key=:n WHERE seed_key=:o"), {"n": new, "o": old})
            sync_conn.execute(text("UPDATE plots SET crop=:n WHERE crop=:o"), {"n": new, "o": old})
        except Exception:
            logger.debug("مایگریشن بذرهای لگاسی رد شد (جدول هنوز نیس یا خطای جزئی)", exc_info=True)

    # راند ۲۸: لول کاروان از ۱ شروع میشه — شیفت یک‌باره کاربرای قدیمی (با پرچم game_meta، idempotent)
    try:
        done = sync_conn.execute(text("SELECT value FROM game_meta WHERE key='r28_caravan_shift'")).fetchone()
        if not done:
            sync_conn.execute(text("UPDATE users SET caravan_level = 5 WHERE caravan_level >= 4"))
            sync_conn.execute(text("UPDATE users SET caravan_level = caravan_level + 1 WHERE caravan_level BETWEEN 0 AND 3"))
            sync_conn.execute(text("INSERT INTO game_meta (key, value) VALUES ('r28_caravan_shift', '1')"))
    except Exception:
        logger.warning("شیفت لول کاروان راند ۲۸ اجرا نشد", exc_info=True)

    # راند ۳۱ (باگ‌فیکس انرژی): بک‌فیل ردیف‌های قدیمی که skill_stamina‌شون NULL مونده بود و نبض انرژی ردشون می‌کرد
    try:
        sync_conn.execute(text("UPDATE users SET skill_stamina = 0 WHERE skill_stamina IS NULL"))
    except Exception:
        logger.warning("بک‌فیل skill_stamina اجرا نشد", exc_info=True)

    # نبرد HP: لول‌های بالاتر از سقف برمی‌گردن روی مکس
    try:
        import config as _cfg
        sync_conn.execute(
            text("UPDATE users SET level=:cap WHERE level > :cap"), {"cap": _cfg.MAX_LEVEL}
        )
    except Exception:
        logger.warning("کلمپ لول به سقف اجرا نشد", exc_info=True)

    # حذف شلیک‌کن پلاسما: دارنده‌هاش گاتلینگ می‌گیرن (کسی که گاتلینگ داشته ردیف پلاسماش پاک میشه)
    try:
        sync_conn.execute(text(
            "DELETE FROM inventory WHERE item_key='plasma' "
            "AND user_id IN (SELECT user_id FROM inventory WHERE item_key='minigun')"
        ))
        sync_conn.execute(text("UPDATE inventory SET item_key='minigun' WHERE item_key='plasma'"))
    except Exception:
        logger.warning("حذف پلاسما از اینونتوری اجرا نشد", exc_info=True)

    # جستجوی کارتل به بزرگی/کوچکی حروف حساس نباشه (کارتل Master همون کارتل master)
    try:
        sync_conn.execute(text("UPDATE teams SET name_norm = LOWER(name_norm)"))
    except Exception:
        logger.warning("یکدست‌سازی name_norm تیم‌ها اجرا نشد", exc_info=True)

    # امتیاز مهارت پس‌دررو برای بازیکنای قدیمی: به تعداد (لول - ۱) امتیاز آزاد می‌گیرن
    try:
        # راند ۳۲ (درخواست کارفرما): GREATEST چون روی PostgreSQL ماکس تجمیعیه و ارور میداد
        # (روی SQLite این مهاجرت خنثی رد میشه و ensure_skills سمت پایتون NULL ها رو خودش پر می‌کنه)
        sync_conn.execute(text(
            "UPDATE users SET skill_points = GREATEST(level - 1, 0) WHERE skill_points IS NULL"
        ))
    except Exception:
        logger.debug("بک‌فیل skill_points روی این دایالکت پشتیبانی نمیشه (SQLite)، ensure_skills سمت پایتون جبران می‌کنه")


async def reload_engine(url: str | None = None) -> None:
    """
    موتور رو از نو می‌سازه — بعد از ری‌استور بک‌آپ استفاده میشه
    تا connectionهای قبلی روی فایل جدید سوار بشن
    """
    global engine, SessionLocal
    _schema_ready.clear()  # تا مهاجرت اسکیمای فایل/دامپ جدید تموم شه، سشن‌های جدید صبر می‌کنن (راند ۳۵)
    try:
        await engine.dispose()
        engine = create_async_engine(url or config.DATABASE_URL, echo=False, future=True)
        SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        await init_db()
    finally:
        _schema_ready.set()  # حتی اگه مهاجرت خطا داد، هیچ سشنی برای همیشه قفل نمی‌مونه


@asynccontextmanager
async def session_scope():
    """اسکوپ session برای هندلرها — کامیت دستی لازم است
    راند ۳۵: تا تموم شدن مهاجرت اسکیما (بوت یا ری‌استور) باز کردن سشن صبر می‌کنه، که کوئری با اسکیمای ناقص نره"""
    if not _schema_ready.is_set():
        try:
            await asyncio.wait_for(_schema_ready.wait(), timeout=60)
        except asyncio.TimeoutError:
            logger.error("گیت اسکیما ۶۰ ثانیه باز نشد؛ سشن بدون گیت باز میشه (مهاجرت هنوز جریان داره؟)")
    async with SessionLocal() as session:
        yield session
