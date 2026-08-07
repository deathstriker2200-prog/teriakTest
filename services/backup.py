"""
بک‌آپ و ری‌استور دیتابیس (فقط ادمین)، فایل SQLite کل اطلاعات بازیه
/backup → اسنپ‌شات سالم فایل دی‌بی رو می‌فرسته
/upload_backup → فایل رو می‌گیره، اعتبارسنجی می‌کنه و جایگزین می‌کنه (روی ولوم ذخیره میشه)
"""

import asyncio
import gzip
import logging
import os
import sqlite3
import tempfile
from datetime import datetime

import config
import database

logger = logging.getLogger(__name__)

_MAGIC = b"SQLite format 3\x00"
_REQUIRED_TABLES = {"users"}


def backup_supported() -> bool:
    """فقط روی SQLite معنی داره، PostgreSQL باشه بک‌آپ فایلی نداریم"""
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


async def restore_bytes(data: bytes) -> tuple[bool, str]:
    """
    جایگزین کردن کامل دیتابیس با فایل بک‌آپ
    موتور dispose میشه، فایل روی دیسک (ولوم) عوض میشه و موتور از نو ساخته میشه
    """
    db_path = config.sqlite_path()
    if not db_path:
        return False, "❌ دیتابیس SQLite نیس، بک‌آپ فایلی روش کار نمی‌کنه"

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
