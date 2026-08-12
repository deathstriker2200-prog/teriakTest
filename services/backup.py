"""
بک‌آپ و ری‌استور دیتابیس (فقط ادمین)
/backup → اسنپ‌شات سالم فایل دی‌بی (SQLite) یا دامپ فشرده pg_dump (Postgres) رو می‌فرسته
/upload_backup → فایل رو می‌گیره و از روی محتواش (نه اسمش) نوعش رو تشخیص میده:
SQLite جایگزین فایلی میشه | دامپ Postgres بعد از بک‌آپ احتیاطی و خالی کردن اسکیمای public با psql ری‌لود میشه
راند ۳۴: اگه دیتابیس زنده Postgres باشه و فایل آپلودی SQLite قدیمی، به‌جای رد شدن دیتاش با زنده ادغام میشه
"""

import asyncio
import gzip
import logging
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, select

import config
import database

logger = logging.getLogger(__name__)

_MAGIC = b"SQLite format 3\x00"
_REQUIRED_TABLES = {"users"}


def backup_supported() -> bool:
    """دیتابیس فایلی SQLite ـه؟ (راند ۳۳: Postgres هم بک‌آپ می‌گیره، ولی با pg_dump نه جایگزینی فایل)"""
    return config.sqlite_path() is not None


async def create_snapshot() -> str:
    """
    ساخت اسنپ‌شات سالم از دیتابیس زنده با VACUUM INTO
    خروجی: مسیر فایل موقت، مسئولیت پاک کردنش با صدا کننده‌ست
    اگه VACUUM نشد، کپی خام فایل برمی‌گردونه
    """
    src = config.sqlite_path()
    if not src or not os.path.exists(src):
        raise FileNotFoundError("فایل دیتابیس پیدا نشد")

    fd, snapshot = tempfile.mkstemp(prefix="teriaky-backup-", suffix=".db")
    os.close(fd)

    ok = False
    try:
        async with database.engine.connect() as conn:
            await conn.exec_driver_sql(f"VACUUM INTO '{snapshot}'")
        ok = True
    except Exception:
        ok = False

    if not ok or not is_valid_backup_file(snapshot):
        # فالبک: کپی مستقیم فایل
        import shutil
        shutil.copyfile(src, snapshot)

    return snapshot


def is_valid_backup_file(path: str) -> bool:
    """اعتبارسنجی فایل: هدر SQLite + جدول users"""
    try:
        if os.path.getsize(path) < 100:
            return False
        with open(path, "rb") as f:
            if f.read(16) != _MAGIC:
                return False
        # باز کردن واقعی و چک جداول، فایل خراب اینجا می‌ترکه
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        finally:
            conn.close()
        tables = {r[0] for r in rows}
        return _REQUIRED_TABLES.issubset(tables)
    except (OSError, sqlite3.Error):
        return False


def _looks_like_pg_dump(sql: bytes) -> bool:
    """دمپ متنی Postgres ـه؟ هدر pg_dump یا دستورای استانداردش باشه و جدول users توش باشه"""
    head = sql[:65536].decode("utf-8", errors="ignore")
    if "PostgreSQL database dump" in head:
        return "users" in head or "CREATE TABLE" in head
    return "CREATE TABLE" in head and "users" in head


def _detect_backup_kind(data: bytes) -> tuple[str, bytes]:
    """
    تشخیص نوع بک‌آپ از روی محتوای فایل (نه اسمش، اسم ممکنه عوض شده باشه)
    خروجی: ("sqlite"|"pgdump"|"bad"، بایت‌های SQL برای دامپ‌ها)
    """
    if data[:16] == _MAGIC:
        return "sqlite", data
    if data[:2] == b"\x1f\x8b":  # gzip شده، دامپ SQL فشرده‌ست
        try:
            plain = gzip.decompress(data)
        except (OSError, EOFError):
            return "bad", data
        return ("pgdump", plain) if _looks_like_pg_dump(plain) else ("bad", data)
    return ("pgdump", data) if _looks_like_pg_dump(data) else ("bad", data)


async def _restore_sqlite(data: bytes) -> tuple[bool, str]:
    """
    جایگزین کردن کامل دیتابیس با فایل بک‌آپ SQLite
    موتور dispose میشه، فایل روی دیسک (ولوم) عوض میشه و موتور از نو ساخته میشه
    """
    db_path = config.sqlite_path()
    if not db_path:
        return False, "❌ این فایل SQLite ـه ولی دیتابیس فعلی SQLite نیس؛ برای انتقال از migrate_to_postgres.py استفاده کن"

    fd, tmp = tempfile.mkstemp(prefix="teriaky-restore-", suffix=".db")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)

        if not is_valid_backup_file(tmp):
            return False, "❌ این فایل بک‌آپ سالم تریاکی نیس"

        await database.engine.dispose()
        os.replace(tmp, db_path)      # اتمی، رو ولوم ذخیره میشه
        tmp = ""
        await database.reload_engine()
        return True, "✅ بک‌آپ ری‌استور شد، همه اطلاعات مطابق فایله"
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


async def restore_bytes(data: bytes) -> tuple[bool, str]:
    """
    ری‌استور یکپارچه بک‌آپ (راند ۳۳): نوع فایل از روی محتواش تشخیص داده میشه، نه اسمش
    SQLite → مسیر فایلی | دامپ Postgres (gzip یا متن خام) → بک‌آپ احتیاطی + خالی کردن اسکیما + psql
    امضاش ثابته تا هندلرها بدون تغییر کار کنن
    """
    kind, payload = _detect_backup_kind(data)
    if kind == "sqlite":
        return await _restore_sqlite(payload)
    if kind == "pgdump":
        if not config.DATABASE_URL.startswith("postgresql"):
            return False, "❌ این فایل دامپ Postgres ـه ولی دیتابیس فعلی Postgres نیس"
        return await _restore_postgres(payload)
    return False, "❌ این فایل بک‌آپ سالم تریاکی نیس"


# ═════════ ری‌استور دامپ Postgres (راند ۳۳) ═════════

async def _pg_dump_bytes(dsn: str) -> bytes | None:
    """بک‌آپ احتیاطی زودگذر با pg_dump قبل از ری‌استور، که خالی کردن اسکیما خراب‌کاری نکنه"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pg_dump", dsn,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
    except (FileNotFoundError, asyncio.TimeoutError):
        return None
    if proc.returncode != 0:
        logger.warning("pg_dump برای بک‌آپ احتیاطی شکست خورد: %s", err.decode(errors="ignore")[:300])
        return None
    return out


async def _run_psql(dsn: str, *args: str, timeout: int = 300) -> tuple[int, str]:
    """اجرای psql (خام libpq DSN می‌خواد، درایور asyncpg نمی‌فهمه)، خروجی: (کد خروج، متن خطا)"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "psql", dsn, "-v", "ON_ERROR_STOP=1", *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except FileNotFoundError:
        return 127, "psql پیدا نشد"
    except asyncio.TimeoutError:
        return 124, "psql تایم‌اوت خورد"
    return proc.returncode, err.decode(errors="ignore")[:400]


async def _wipe_public_schema(dsn: str) -> tuple[int, str]:
    """خالی کردن کامل اسکیمای public، که دامپ رو پایگاه تمیز بشینه و جدول/کلید باقی‌مونده تداخل نده"""
    return await _run_psql(dsn, "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;")


async def _rollback_safety(dsn: str, safety: bytes) -> bool:
    """برگردوندن بک‌آپ احتیاطی بعد از شکست ری‌استور، همون ترتیب: خالی کردن اسکیما بعد psql"""
    fd, path = tempfile.mkstemp(prefix="teriaky-rollback-", suffix=".sql")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(safety)
        rc, _ = await _wipe_public_schema(dsn)
        if rc != 0:
            return False
        rc, _ = await _run_psql(dsn, "-f", path)
        return rc == 0
    finally:
        if os.path.exists(path):
            os.remove(path)


async def _restore_postgres(sql: bytes) -> tuple[bool, str]:
    """
    ری‌استور دامپ متنی Postgres (فرمت plain نه -Fc، پس با psql نه pg_restore)
    ترتیب امن: بک‌آپ احتیاطی pg_dump → نوشتن دامپ تو فایل موقت → خالی کردن اسکیمای public → psql -f
    بعدش چک سلامت جدول users و ساخت دوباره موتور؛ هرجا خطا بده سعی میشه از بک‌آپ احتیاطی برگرده
    """
    if not shutil.which("psql") or not shutil.which("pg_dump"):
        return False, "❌ psql یا pg_dump رو سرور نصب نیس (تو PATH نیس)، ری‌استور دامپ Postgres ممکن نیس"

    # psql آدرس خام libpq می‌خواد، اسم درایور asyncpg توش نباشه (مثل make_upload_payload)
    dsn = config.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)

    safety = await _pg_dump_bytes(dsn)
    if safety is None:
        return False, "❌ بک‌آپ احتیاطی با pg_dump ساخته نشد، ری‌استور انجام نشد (دیتابیس دست نخورده)"

    fd, incoming = tempfile.mkstemp(prefix="teriaky-restore-", suffix=".sql")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(sql)

        await database.engine.dispose()  # کانکشن بازی نمونه که DROP SCHEMA گیر نکنه
        rc, err = await _wipe_public_schema(dsn)
        if rc == 0:
            rc, err = await _run_psql(dsn, "-f", incoming)

        if rc != 0:
            rolled = await _rollback_safety(dsn, safety)
            await database.reload_engine()
            _lines = [ln for ln in err.strip().splitlines() if ln.strip()]
            tail = next((ln for ln in _lines if "ERROR" in ln), _lines[-1] if _lines else "خطای ناشناخته psql")
            if rolled:
                return False, f"❌ ری‌استور دامپ نشد ({tail[:120]}) و دیتابیس به نسخه قبلی خودش برگشت"
            return False, f"❌ ری‌استور دامپ نشد ({tail[:120]}) و برگردوندن خودکار هم خطا داد، دیتابیس ممکنه بین راه مونده باشه"

        # چک سلامت پایه قبل از بالا اومدن مجدد بات: جدول users باشه و کوئری بخوره
        rc2, _ = await _run_psql(dsn, "-tAc", "SELECT 1 FROM users LIMIT 1")
        if rc2 != 0:
            rolled = await _rollback_safety(dsn, safety)
            await database.reload_engine()
            if rolled:
                return False, "❌ دامپ اجرا شد ولی جدول users سالم نیس، دیتابیس به نسخه قبلی برگشت"
            return False, "❌ دامپ اجرا شد ولی جدول users سالم نیس و برگردوندن خودکار هم خطا داد، دیتابیس ممکنه بین راه مونده باشه"

        await database.reload_engine()  # کانکشن‌ها روی اسکیمای تازه سوار بشن + مهاجرت‌های سبک
        return True, "✅ بک‌آپ Postgres ری‌استور شد، همه اطلاعات مطابق فایله"
    finally:
        if os.path.exists(incoming):
            os.remove(incoming)


def dump_supported() -> bool:
    """از دیتابیس فعلی میشه فایل بک‌آپ ساخت؟ sqlite با اسنپ‌شات | postgres با pg_dump"""
    return backup_supported() or config.DATABASE_URL.startswith("postgresql")


async def make_upload_payload() -> tuple[bytes, str] | None:
    """
    فایل نهایی بک‌آپ برای ارسال تو تلگرام: (بایت‌ها، اسم فایل) یا None اگه نشد
    sqlite اسنپ‌شات VACUUM INTO می‌شه | postgres خروجی pg_dump فشرده (راند ۱۷، بک‌آپ خودکار روزانه)
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    if backup_supported():
        try:
            snap = await create_snapshot()
        except FileNotFoundError:
            return None
        with open(snap, "rb") as f:
            data = f.read()
        try:  # فایل موقت اسنپ‌شات رو پاک کن، دیسک پر نشه
            os.remove(snap)
        except OSError:
            pass
        return data, f"{config.BACKUP_NAME}-{stamp}.db"
    if config.DATABASE_URL.startswith("postgresql"):
        # pg_dump آدرس خام libpq می‌خواد، اسم درایور asyncpg توش نباشه
        dsn = config.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
        try:
            proc = await asyncio.create_subprocess_exec(
                "pg_dump", dsn,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
        except (FileNotFoundError, asyncio.TimeoutError) as e:
            logger.warning("pg_dump برای بک‌آپ روزانه در دسترس نیس یا تایم‌اوت خورد: %s", e)
            return None
        if proc.returncode != 0:
            logger.warning("pg_dump شکست خورد: %s", err.decode(errors="ignore")[:300])
            return None
        return gzip.compress(out), f"{config.BACKUP_NAME}-{stamp}.sql.gz"
    return None


# ═════════ ادغام فایل قدیمی SQLite با دیتابیس زنده Postgres (راند ۳۴) ═════════
# سناریو: دیتابیس زنده Postgres ـه ولی ادمین فایل ‎.db قدیمی آپلود می‌کنه
# به‌جای رد کردن، دیتاش با دیتابیس فعلی ادغام میشه (افزایشی، چیزی پاک نمیشه)

_IMPORT_CHUNK = 500   # اندازه هر بسته INSERT (مثل migrate_to_postgres)
_import_running = False


def merge_needed(data: bytes) -> bool:
    """ترکیب خاص راند ۳۴: دیتابیس زنده Postgres ـه و فایل آپلودی SQLite (بک‌آپ دوران قبل از مهاجرت)"""
    return config.DATABASE_URL.startswith("postgresql") and _detect_backup_kind(data)[0] == "sqlite"


def merge_running() -> bool:
    """همین الان یه ادغام تو حال اجراست؟ (دو ادغام همزمان شروع نمیشن)"""
    return _import_running


def _read_sqlite_snapshot(path: str, table_names: list) -> dict:
    """
    خواندن sync همه ردیف‌ها با sqlite3 استاندارد (از run_in_executor صدا زده میشه تا loop بلاک نشه)
    جدولی که تو فایل نیس کلیدش تو خروجی نمیاد؛ بقیه به شکل لیست دیکت {ستون: مقدار} برمی‌گردن
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        src_tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        out = {}
        for name in table_names:
            if name not in src_tables:
                continue
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{name}")')]
            rows = conn.execute(f'SELECT * FROM "{name}"').fetchall()
            out[name] = [dict(zip(cols, row)) for row in rows]
        return out
    finally:
        conn.close()


def _fallback_value(col):
    """
    ستونی که مدل فعلی داره ولی فایل قدیمی نداره با مقدار امن پر میشه (نه خطا)
    اولویت: nullable هم NULL | default خود مدل (اسکالر یا callable) | بولین False | عدد 0 | رشته خالی
    """
    if col.nullable:
        return None
    d = getattr(col, "default", None)
    if d is not None and d.arg is not None:
        if not callable(d.arg):
            return d.arg
        try:
            # SQLAlchemy کال‌بل‌های بدون آرگومان رو به wrap(ctx) می‌پیچونه، هر دو حالت پوشش داده میشه
            return d.arg(None)
        except TypeError:
            return d.arg()
    if isinstance(col.type, Boolean):
        return False
    if isinstance(col.type, Integer):
        return 0
    if isinstance(col.type, DateTime):
        from utils import now_utc
        return now_utc()
    return ""


def _coerce_value(col, v):
    """
    تطبیق مقدار خوانده‌شده با sqlite3 خام به نوع ستون برای Postgres
    تو فایل SQLite تاریخ‌ها رشته‌ان و بولین‌ها 0/1 ان؛ asyncpg نوع دقیق می‌خواد
    """
    if v is None:
        return None
    if isinstance(col.type, Boolean) and not isinstance(v, bool):
        return bool(v)
    if isinstance(col.type, DateTime) and isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return _fallback_value(col)
    return v


def _import_row(table, row: dict) -> dict:
    """ساخت ردیف آماده درج: فقط ستون‌های مدل فعلی، مفقودی‌ها با مقدار امن، ستون اضافی فایل حذف میشه"""
    return {
        col.name: (_coerce_value(col, row[col.name]) if col.name in row else _fallback_value(col))
        for col in table.c
    }


async def _merge_sqlite_pg(data: bytes) -> tuple[bool, str]:
    """
    بدنه‌ی اصلی ادغام: دامپ احتیاطی pg_dump (روی دیسک می‌مونه و آدرسش اعلام میشه)،
    خواندن فایل تو executor، درج جدول‌به‌جدول با تراکنش مجزا (موفقیت‌های قبلی از دست نمیره)
    و آخرش سینک سکانس‌های Postgres با بیشترین id (تابع آماده‌ی migrate_to_postgres)
    """
    if not config.DATABASE_URL.startswith("postgresql"):
        return False, "❌ ادغام بک‌آپ SQLite فقط وقتی دیتابیس زنده Postgres ـه انجام میشه"
    if not shutil.which("pg_dump"):
        return False, "❌ pg_dump رو سرور نصب نیس (تو PATH نیس)، بدون بک‌آپ احتیاطی ادغام شروع نمیشه"

    dsn = config.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    safety = await _pg_dump_bytes(dsn)
    if safety is None:
        return False, "❌ بک‌آپ احتیاطی با pg_dump ساخته نشد، ادغام انجام نشد (دیتابیس دست نخورده)"

    fd, safety_path = tempfile.mkstemp(prefix="teriaky-preimport-", suffix=".sql")
    with os.fdopen(fd, "wb") as f:
        f.write(safety)

    fd, tmp = tempfile.mkstemp(prefix="teriaky-import-", suffix=".db")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)

        if not is_valid_backup_file(tmp):
            return (False,
                    "❌ این فایل بک‌آپ سالم تریاکی نیس (جدول users توش نیس)، چیزی دست نخورده\n"
                    f"💾 بک‌آپ احتیاطی دیتابیس فعلی: {safety_path}")

        from database import Base
        from models import models as _models  # noqa: F401  (ثبت جدول‌ها روی metadata)

        tables = Base.metadata.sorted_tables   # ترتیب وابستگی فارین‌کی: parent قبل از child
        loop = asyncio.get_running_loop()
        snapshot = await loop.run_in_executor(None, _read_sqlite_snapshot, tmp, [t.name for t in tables])

        lines = []
        missing = failed = total_new = 0
        for table in tables:
            rows = snapshot.get(table.name)
            if rows is None:
                missing += 1
                logger.info("ادغام: جدول %s تو فایل قدیمی نبود، رد شد", table.name)
                continue
            pks = [c.name for c in table.primary_key.columns]
            if not pks:
                continue
            fks = list(table.foreign_keys)
            try:
                async with database.engine.begin() as dc:   # هر جدول تراکنش خودش
                    existing = {
                        tuple(r) for r in
                        (await dc.execute(select(*[table.c[p] for p in pks]))).all()
                    }
                    parent_cache = {}
                    for fk in fks:   # کش pk والدها، ردیف یتیم (پدر ناموجود) کرش نده رد میشه
                        pt = fk.column.table.name
                        if pt not in parent_cache:
                            parent_cache[pt] = {r[0] for r in (await dc.execute(select(fk.column))).all()}
                    batch = []
                    ins = dup = orph = 0
                    for row in rows:
                        if tuple(row.get(pp) for pp in pks) in existing:
                            dup += 1
                            continue
                        if any(
                            row.get(fk.parent.name) is not None
                            and row.get(fk.parent.name) not in parent_cache[fk.column.table.name]
                            for fk in fks
                        ):
                            orph += 1
                            continue
                        batch.append(_import_row(table, row))
                        if len(batch) >= _IMPORT_CHUNK:
                            await dc.execute(table.insert(), batch)
                            ins += len(batch)
                            batch = []
                    if batch:
                        await dc.execute(table.insert(), batch)
                        ins += len(batch)
            except Exception as e:
                failed += 1
                logger.exception("ادغام جدول %s شکست خورد", table.name)
                lines.append(f"⚠️ {table.name}: درج نشد ({str(e)[:60]}) ولی تراکنش‌های قبلی سر جاشونن")
                continue
            if ins or dup or orph:
                seg = f"📦 {table.name}: {ins} ردیف جدید"
                if dup:
                    seg += f"، {dup} تکراری رد شد"
                if orph:
                    seg += f"، {orph} یتیم (پدر تو دیتابیس نبود) رد شد"
                lines.append(seg)
            total_new += ins

        from migrate_to_postgres import _sync_sequences as _sync_pg_sequences
        await _sync_pg_sequences(database.engine, tables)

        head = ("✅ ادغام فایل قدیمی SQLite با دیتابیس Postgres تموم شد" if not failed else
                "⚠️ ادغام انجام شد ولی یه سری جدول خطا داشتن، جزئیاتش پایینه")
        body = [head, "", *lines]
        if missing:
            body.append(f"⏭ {missing} جدول تو فایل قدیمی نبودن، رد شدن")
        body += [
            "",
            f"🔢 جمعاً {total_new} ردیف تازه به دیتابیس زنده اضافه شد (چیزی پاک یا بازنویسی نشد)",
            "🔧 سکانس‌های id با بیشترین مقدار هر جدول سینک شدن",
            f"💾 بک‌آپ احتیاطی کامل قبل از ادغام: {safety_path}",
        ]
        return failed == 0, "\n".join(body)
    except Exception as e:
        logger.exception("ادغام sqlite به postgres وسط کار شکست خورد")
        return (False,
                f"❌ ادغام وسط کار خطا خورد: {str(e)[:120]}\n"
                "جدول‌هایی که قبل از خطا موفق درج شده بودن سر جاشون موندن\n"
                f"💾 بک‌آپ احتیاطی کامل قبل از ادغام اینجاست، باهاش می‌تونی دستی برگردونی: {safety_path}")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


async def merge_sqlite_bytes(data: bytes, notify=None) -> tuple[bool, str]:
    """
    ورودی عمومی ادغام راند ۳۴ با قفل تک‌اجرایی
    متن نهایی رو به notify (کوروتین) هم میده تا هندلر بعد از تموم شدن کار جداگانه براش پیام بفرسته
    خروجی: (موفقیت کامل بودن، متن خلاصه)
    """
    global _import_running
    if _import_running:
        return False, "❌ یه ادغام دیگه الان تو حال اجراست، اول اون تموم شه"
    _import_running = True
    try:
        try:
            ok, msg = await _merge_sqlite_pg(data)
        except Exception as e:   # دفاع آخر: تسک پس‌زمینه هیچ‌وقت بی‌جواب نمونه
            logger.exception("ادغام sqlite به postgres خطای غیرمنتظره داد")
            ok, msg = False, f"❌ ادغام با خطای غیرمنتظره ول خورد: {str(e)[:120]}"
    finally:
        _import_running = False
    if notify is not None:
        try:
            await notify(msg)
        except Exception:
            pass   # چت ادمین در دسترس نبود، خلاصه تو لاگ هس
    return ok, msg
