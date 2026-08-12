"""
بک‌آپ و ری‌استور دیتابیس (فقط ادمین)
/backup → اسنپ‌شات سالم فایل دی‌بی (SQLite) یا دامپ فشرده pg_dump (Postgres) رو می‌فرسته
/upload_backup → فایل رو می‌گیره و از روی محتواش (نه اسمش) نوعش رو تشخیص میده:
SQLite جایگزین فایلی میشه | دامپ Postgres بعد از بک‌آپ احتیاطی و خالی کردن اسکیمای public با psql ری‌لود میشه
"""

import asyncio
import gzip
import logging
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime

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
