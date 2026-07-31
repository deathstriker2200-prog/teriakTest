"""ثبت خودکار کاربران دیده‌شده، گروه -4 هندلرها، قبل از گیت و همه دستورها"""

from telegram import Update
from telegram.ext import ContextTypes

from database import session_scope
from services import seen as seen_svc


async def track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    هر پیامی که ربات می‌بینه فرستنده‌اش ثبت میشه (بیشتر برای حمله با @یوزرنیم تو گروه)
    هیچ خروجی برای کاربر نداره و هیچ‌وقت خطا نمی‌ندازه که جریان بقیه هندلرها نشکنه
    """
    try:
        user = update.effective_user
        if user is None:
            return
        async with session_scope() as s:
            await seen_svc.remember(s, user)
            await s.commit()
    except Exception:
        return
