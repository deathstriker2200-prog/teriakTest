"""اتصال دیتابیس — SQLAlchemy async روی SQLite (قابل سوییچ به PostgreSQL)"""

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

import config


class Base(DeclarativeBase):
    pass


engine = create_async_engine(config.DATABASE_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """ساخت جداول و ایندکس‌ها + مایگریشن سبک ستون‌های جدید روی دیتابیس قدیمی"""
    from models import models as _models  # noqa: F401  (ثبت مدل‌ها روی metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_columns)
        await conn.run_sync(_ensure_indexes)
        await conn.run_sync(_migrate_data)


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
        ("lumber_stock", "INTEGER NOT NULL DEFAULT 0"),
        ("ironmill_stock", "INTEGER NOT NULL DEFAULT 0"),
        ("last_seen_at", "DATETIME"),
        ("shield_until", "DATETIME"),
        ("pv_attack_at", "DATETIME"),
        ("last_spy_target_id", "INTEGER"),
        ("dq_date", "VARCHAR(10)"),
        ("dq_data", "VARCHAR(1024)"),
        ("hp", "INTEGER"),
        ("dead_until", "DATETIME"),
        ("wood", "INTEGER NOT NULL DEFAULT 0"),
        ("iron", "INTEGER NOT NULL DEFAULT 0"),
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
    ],
    "group_activity": [
        ("title", "VARCHAR(128)"),
        ("msgs_hour", "INTEGER NOT NULL DEFAULT 0"),
        ("hour_key", "VARCHAR(16)"),
    ],
        "inventory": [
        ("level", "INTEGER NOT NULL DEFAULT 1"),
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
    ],
    "team_members": [
        ("join_medals", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "team_daily": [
        ("qprog", "VARCHAR(256)"),
        ("qdone", "VARCHAR(128)"),
    ],
}

# ری‌نیم بذرها — ردیف‌های دیتابیس‌های قدیمی رو به کلید جدید منتقل می‌کنیم
_LEGACY_SEEDS = {"koka": "peyote", "ghat": "teriak"}


def _ensure_columns(sync_conn) -> None:
    """اگه دیتابیس قدیمی ستون جدید نداشت، با ALTER TABLE اضافه‌ش کن"""
    from sqlalchemy import text

    for table, cols in _NEW_COLUMNS.items():
        rows = sync_conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        existing = {r[1] for r in rows}
        for name, coltype in cols:
            if name not in existing:
                sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}"))


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
            pass  # جدول هنوز ساخته نشده باشه دفعه بعد ساخته میشه


def _migrate_data(sync_conn) -> None:
    """مایگریشن دیتا — بذرهای قدیمی (کوکا/قات) به کلیدهای جدید + سقف لول ۲۰"""
    from sqlalchemy import text

    for old, new in _LEGACY_SEEDS.items():
        try:
            sync_conn.execute(text("UPDATE seed_stock SET seed_key=:n WHERE seed_key=:o"), {"n": new, "o": old})
            sync_conn.execute(text("UPDATE plots SET crop=:n WHERE crop=:o"), {"n": new, "o": old})
        except Exception:
            pass  # جدول هنوز نیس یا خطای جزئی — مهم نیس

    # نبرد HP: لول‌های بالاتر از سقف برمی‌گردن روی مکس
    try:
        import config as _cfg
        sync_conn.execute(
            text("UPDATE users SET level=:cap WHERE level > :cap"), {"cap": _cfg.MAX_LEVEL}
        )
    except Exception:
        pass

    # حذف شلیک‌کن پلاسما: دارنده‌هاش گاتلینگ می‌گیرن (کسی که گاتلینگ داشته ردیف پلاسماش پاک میشه)
    try:
        sync_conn.execute(text(
            "DELETE FROM inventory WHERE item_key='plasma' "
            "AND user_id IN (SELECT user_id FROM inventory WHERE item_key='minigun')"
        ))
        sync_conn.execute(text("UPDATE inventory SET item_key='minigun' WHERE item_key='plasma'"))
    except Exception:
        pass

    # جستجوی تیم به بزرگی/کوچکی حروف حساس نباشه (تیم Master همون تیم master)
    try:
        sync_conn.execute(text("UPDATE teams SET name_norm = LOWER(name_norm)"))
    except Exception:
        pass

    # امتیاز مهارت پس‌دررو برای بازیکنای قدیمی: به تعداد (لول - ۱) امتیاز آزاد می‌گیرن
    try:
        sync_conn.execute(text(
            "UPDATE users SET skill_points = MAX(level - 1, 0) WHERE skill_points IS NULL"
        ))
    except Exception:
        pass


async def reload_engine(url: str | None = None) -> None:
    """
    موتور رو از نو می‌سازه — بعد از ری‌استور بک‌آپ استفاده میشه
    تا connectionهای قبلی روی فایل جدید سوار بشن
    """
    global engine, SessionLocal
    await engine.dispose()
    engine = create_async_engine(url or config.DATABASE_URL, echo=False, future=True)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await init_db()


@asynccontextmanager
async def session_scope():
    """اسکوپ session برای هندلرها — کامیت دستی لازم است"""
    async with SessionLocal() as session:
        yield session
