"""نقطه ورود ربات تریاکی — اجرا: python bot.py"""

import logging

from telegram import BotCommand, Update
from telegram.ext import Application

import config
from database import init_db, session_scope
from handlers import register_handlers

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger("teriaky")


async def on_start(app: Application) -> None:
    from keyboards import keyboards

    config.ensure_sqlite_dir()   # اگه ولوم ریلوی تازه سوار شده پوشه رو بساز
    await init_db()

    # کش ردیابی بازیکن‌های ادمین (🕵️) یک‌بار اینجا از دیتابیس لود میشه، چک‌های اکشن بعدش فقط روی حافظه‌ان
    from services import tracklog
    async with session_scope() as _ts:
        await tracklog.refresh(_ts)
        await _ts.commit()

    me = await app.bot.get_me()
    keyboards.BOT_USERNAME = me.username or ""

    # کامندهای منوی «/» تلگرام — /botoff و /boton ته لیستن
    await app.bot.set_my_commands([
        BotCommand("start", "🎮 شروع بازی و منوی اصلی"),
        BotCommand("profile", "🏠 پروفایلت"),
        BotCommand("help", "📖 آموزشات بازی"),
        BotCommand("heal", "❤️ درمان و برگردوندن سلامت"),
        BotCommand("energy", "⚡ انرژی‌زا و برگشت انرژی"),
        BotCommand("shop", "🛒 فروشگاه"),
        BotCommand("botoff", "🔌 خاموش کردن ربات تو گروه (ادمین گروه)"),
        BotCommand("boton", "🔌 روشن کردن ربات تو گروه (ادمین گروه)"),
    ])

    logger.info("دیتابیس آماده شد ✅ | DB: %s", _safe_db())
    logger.info("یوزرنیم ربات: @%s | دکمه افزودن به گروه فعاله", keyboards.BOT_USERNAME)


async def on_error(update: object, context) -> None:
    """ته‌توری خطاها (راند ۳۵، درخواست کارفرما): اگه با وجود سینک اسکیما بازم کوئری ترکید
    (مثل OperationalError: no such column) اینجا با تریس‌بک کامل تو لاگ سرویس میفته، قابل دیدنه"""
    logger.exception("خطا تو پردازش آپدیت/جاب", exc_info=context.error)


def _safe_db() -> str:
    """مسیر دی‌بی برای لاگ — بدون لو دادن پسورد"""
    url = config.DATABASE_URL
    return url if "@" not in url else url.split("@", 1)[1]


def main() -> None:
    _dk = getattr(config, "DOTENV_KEYS", [])
    if _dk:
        print(f"⚙️ {len(_dk)} متغیر از فایل .env لود شد: {', '.join(sorted(_dk))}")
    else:
        print("ℹ️ فایل .env لود نشد (نیس یا خالی/همه‌ش قبلاً تو محیط بود) | فقط متغیرهای محیط")
    print(f"🔑 منبع توکن: {config.TOKEN_SOURCE}")
    if not config.BOT_TOKEN:
        raise SystemExit(
            "❌ توکن ربات پیدا نشد\n"
            "متغیر TERIAKY_TOKEN رو توی فایل .env کنار پروژه پر کن (یا: python3 teriaky_set.py TERIAKY_TOKEN <توکن>)، خودش خودکار خونده میشه"
        )

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(on_start)
        .build()
    )
    register_handlers(app)
    app.add_error_handler(on_error)   # راند ۳۵: خطاهای هندلر/جاب با تریس‌بک تو لاگ

    # زمان پردازش هر آپدیت (پیام/کالبک) ثبت میشه، برای آمار فنی پنل ادمین
    from handlers.common import proc_wrapper
    app.process_update = proc_wrapper(app.process_update)

    from handlers import jobs
    jobs.register_jobs(app)

    logger.info("ربات تریاکی اومد بالا 🤖")
    # راند ۳۵ (درخواست کارفرما): پیام‌هایی که موقع خاموشی انباشتن پاسخ داده نمیشن، نه فشار استارت نه پاسخ انبوه /start
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
