"""
لاگ رویدادهای شمارشی برای آمار پنل ادمین 📊

نبرد گروهی | حمله پی‌وی | کنده‌کاری | قمارخانه هر بار موفق یه ردیف می‌خورن
شمارش‌های «۲۴ ساعت اخیر» مستقیم با COUNT روی ایندکس (action, at) حساب میشن
ردیف‌های قدیمی‌تر از ACTION_LOG_KEEP_HOURS موقع درج بعدی پاک میشن، کامیت با صدا‌کننده‌ست
"""

import random
from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import ActionEvent
from utils import now_utc

# تنوع‌های شناخته‌شده رویداد (هر جای جدید اضافه شد اول اینجا مستند بشه)
ACTIONS = ("battle", "pvattack", "mine", "casino")


async def log(session: AsyncSession, action: str) -> None:
    """
    ثبت یه رویداد موفق، فقط ردیف اضافه می‌کنه و کامیت نمی‌کنه
    هر از چندگاهی ردیف‌های قدیمی هم پاک میشن تا جدول همیشه کوچیک بمونه
    """
    if action not in ACTIONS:
        return
    session.add(ActionEvent(action=action, at=now_utc()))
    if random.random() < config.ACTION_LOG_PRUNE_CHANCE:
        cutoff = now_utc() - timedelta(hours=config.ACTION_LOG_KEEP_HOURS)
        await session.execute(delete(ActionEvent).where(ActionEvent.at < cutoff))
