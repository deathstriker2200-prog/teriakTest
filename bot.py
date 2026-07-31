"""نقطه ورود ربات تریاکی — اجرا: python bot.py"""

import logging

from telegram import BotCommand, Update
from telegram.ext import Application

import config
from database import init_db
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

    me = await app.bot.get_me()
    keyboards.BOT_USERNAME = me.username or ""

    # کامندهای منوی «/» تلگرام — /botoff و /boton ته لیستن
    await app.bot.set_my_commands([
        BotCommand("start", "🎮 شروع بازی و منوی اصلی"),
        BotCommand("profile", "🏠 پروفایلت"),
        BotCommand("help", "📖 آموزشات بازی"),
        BotCommand("heal", "❤️ درمان و برگردوندن سلامت"),
        BotCommand("shop", "🛒 فروشگاه"),
        BotCommand("botoff", "🔌 خاموش کردن ربات تو گروه (ادمین گروه)"),
        BotCommand("boton", "🔌 روشن کردن ربات تو گروه (ادمین گروه)"),
    ])

    logger.info("دیتابیس آماده شد ✅ | DB: %s", _safe_db())
    logger.info("یوزرنیم ربات: @%s | دکمه افزودن به گروه فعاله", keyboards.BOT_USERNAME)


def _safe_db() -> str:
    """مسیر دی‌بی برای لاگ — بدون لو دادن پسورد"""
    url = config.DATABASE_URL
    return url if "@" not in url else url.split("@", 1)[1]


def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit(
            "❌ توکن ربات پیدا نشد\n"
            "متغیر محیطی TERIAKY_TOKEN رو تنظیم کن — نمونه توی .env.example هست"
        )

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(on_start)
        .build()
    )
    register_handlers(app)

    # زمان پردازش هر آپدیت (پیام/کالبک) ثبت میشه، برای آمار فنی پنل ادمین
    from handlers.common import proc_wrapper
    app.process_update = proc_wrapper(app.process_update)

    from handlers import jobs
    jobs.register_jobs(app)

    logger.info("ربات تریاکی اومد بالا 🤖")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
