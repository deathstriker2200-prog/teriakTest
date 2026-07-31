"""
رجیستری کاربران دیده‌شده 👀
ربات هر پیامی رو که ببینه اینجا ثبت می‌کنه تا «حمله @یوزرنیم»
به کسایی که هنوز ربات رو استارت نکردن هم کار کنه
کش حافظه‌ای داره که روی هر پیام گروه دی‌بی نوشته نشه
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import SeenUser
from utils import now_utc

# کش زنده: tg_id → (username پایین‌آورده, first_name)، فقط برای رد کردن نوشتن تکراری
_CACHE: dict[int, tuple[str | None, str | None]] = {}

_REFRESH_AFTER = timedelta(hours=24)   # بعد این مدت دوباره به‌روزرسانی میشه


async def remember(session: AsyncSession, tg_user) -> None:
    """ثبت/به‌روزرسانی یه کاربر دیده‌شده، با کش تا نوشتن غیرضروری نداشته باشیم"""
    if tg_user is None:
        return
    tg_id = getattr(tg_user, "id", None)
    if tg_id is None:
        return
    username = getattr(tg_user, "username", None)
    first_name = getattr(tg_user, "first_name", None)
    uname = username.lower() if username else None

    if _CACHE.get(tg_id) == (uname, first_name):
        return

    row = await session.get(SeenUser, tg_id)
    if row:
        # اگه چیزی عوض نشده و تازه‌ست، فقط کش رو پر کن
        if (
            (row.username or None) == uname
            and row.first_name == first_name
            and row.updated_at
            and now_utc() - row.updated_at < _REFRESH_AFTER
        ):
            _CACHE[tg_id] = (uname, first_name)
            return
        row.username = uname
        row.first_name = first_name
        row.updated_at = now_utc()
    else:
        session.add(SeenUser(telegram_id=tg_id, username=uname, first_name=first_name))
    _CACHE[tg_id] = (uname, first_name)


async def find_by_username(session: AsyncSession, username: str) -> SeenUser | None:
    """پیدا کردن کاربر دیده‌شده با یوزرنیم (بدون @، حروف بزرگ مهم نیس)"""
    norm = (username or "").strip().lstrip("@").lower()
    if not norm:
        return None
    q = select(SeenUser).where(func.lower(SeenUser.username) == norm).limit(1)
    return (await session.execute(q)).scalar_one_or_none()


def cache_size() -> int:
    """اندازه کش، برای تست و مانیتورینگ"""
    return len(_CACHE)
