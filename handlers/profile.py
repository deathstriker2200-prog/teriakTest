"""پروفایل، عکس تلگرام + کپشن فانتزی، دستور و دکمه هر دو همون متن"""

from sqlalchemy import func, select
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import strip_home
from keyboards import keyboards as kb
from models import User
from services import combat, dogs as dog_svc, economy, farming, users
from utils import bar, esc, fa_num, jalali_str, money, short_name

# ───────── فرمت پروفایل ─────────

def _bar(energy: int) -> str:
    return bar(energy, config.MAX_ENERGY)


def _weapon_line(item_keys: list[str]) -> str:
    """خط سلاح پروفایل، اسلحه‌ها با 🔫 دور اسمشون، سردها با 🔪، دست خالی با 👊"""
    key = combat.best_weapon_key(item_keys)
    if not key:
        return "👊 دست خالی"
    w = config.WEAPONS[key]
    return f"🔫 {esc(w['name'])}" if w.get("gun") else f"🔪 {esc(w['name'])}"


def _xp_line(user) -> str:
    """خط لول و تجربه، بعد از مکس فقط تجربه جمع‌شده نوشته میشه"""
    if user.level >= config.MAX_LEVEL:
        return f"🌟 لول {fa_num(config.MAX_LEVEL)} 👑 - {fa_num(user.xp)} تجربه"
    return f"🌟 لول {fa_num(user.level)} - {fa_num(user.xp)}/{fa_num(economy.xp_need(user.level))} تجربه"


async def _profile_caption(session, user) -> str:
    item_keys = await users.get_item_keys(session, user.id)
    user_dogs = await dog_svc.get_user_dogs(session, user.id)
    atk, dfn = combat.combat_stats(user, item_keys, user_dogs)
    plots = await farming.get_user_plots(session, user.id)

    growing = sum(1 for p in plots if p.current_status()[0] == "growing")
    ready = sum(1 for p in plots if p.current_status()[0] == "ready")

    armor = combat.best_armor_name(item_keys) or "بدون زره"

    rank = (await session.execute(
        select(func.count(User.id)).where(User.cash > user.cash)
    )).scalar_one() + 1
    total = (await session.execute(select(func.count(User.id)))).scalar_one()

    name = esc(short_name(users.display_name(user)))
    uname = f"@{esc(user.username)}" if user.username else "بدون یوزرنیم"
    # تاریخ عضویت به شمسی
    joined = jalali_str(user.created_at) if user.created_at else "—"
    # سگ فقط به تعداد نمایش داده میشه، نه اسم نه نژاد
    dog_line = f"🐕 سگ {fa_num(len(user_dogs))} عدد" if user_dogs else "🐕 سگ نداری"

    return (
        f"╭━━━━━━━━━━━━━━╮\n"
        f"👤 {name}\n"
        f"╰━━━━━━━━━━━━━━╯\n"
        f"🆔 {uname}\n\n"
        f"{_xp_line(user)}\n"
        f"⚡ انرژی {_bar(user.energy)} {fa_num(user.energy)}/{fa_num(config.MAX_ENERGY)}\n"
        f"🏆 رتبه {fa_num(rank)} از {fa_num(total)} بازیکن\n"
        f"🗓 تاریخ عضویت {joined}\n\n"
        f"━━━━━━ 💰 دارایی ━━━━━━\n"
        f"🪙 {money(user.cash)}\n"
        f"🏦 بانک {money(user.bank_balance)}\n\n"
        f"━━━━━━ 🏗 اموال ━━━━━━\n"
        f"🌱 تعداد زمین‌ها {fa_num(len(plots))}\n"
        f"🌾 در حال رشد {fa_num(growing)}\n"
        f"✅ آماده برداشت {fa_num(ready)}\n\n"
        f"{_weapon_line(item_keys)}\n"
        f"🛡 {esc(armor)}\n"
        f"{dog_line}\n\n"
        f"━━━━━━ ⚔️ آمار جنگی ━━━━━━\n"
        f"💪 قدرت حمله {fa_num(atk)}\n"
        f"🛡 دفاع {fa_num(dfn)}\n"
        f"✅ برد {fa_num(user.wins)} | ❌ باخت {fa_num(user.losses)}"
    )


async def _send_profile(bot, chat_id: int, tg_id: int, caption: str, markup=None) -> None:
    """ارسال پروفایل با عکس تلگرام کاربر، اگه عکس نداشت متن ساده"""
    file_id = None
    try:
        photos = await bot.get_user_profile_photos(tg_id, limit=1)
        if photos and photos.total_count:
            file_id = photos.photos[0][-1].file_id  # بزرگ‌ترین سایز
    except Exception:
        file_id = None  # سلب دسترسی، میریم رو متن ساده

    if file_id:
        await bot.send_photo(
            chat_id=chat_id, photo=file_id,
            caption=caption, parse_mode="HTML", reply_markup=markup,
        )
    else:
        await bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML", reply_markup=markup)


# ───────── دستور «پروفایل» / /profile، خالص بدون هیچ متن یا دکمه زیرش ─────────

async def profile_photo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.apply_energy_regen(user)
        caption = await _profile_caption(s, user)
        tg_id = user.telegram_id
        await s.commit()

    await _send_profile(context.bot, update.effective_chat.id, tg_id, caption, markup=None)


# ───────── دکمه پروفایل تو منو، عکس + رفرش ─────────

async def profile_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.apply_energy_regen(user)
        caption = await _profile_caption(s, user)
        tg_id = user.telegram_id
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        await s.commit()

    # قاب ادیت نمیشه به عکس، پاک می‌کنیم و تازه می‌فرستیم
    try:
        if query.message:
            await query.message.delete()
    except BadRequest:
        pass

    await _send_profile(
        context.bot, chat_id, tg_id, caption,
        markup=strip_home(update, kb.profile_kb()),
    )


# /profile همون نسخه عکس‌دار، بدون دکمه و متن اضافی زیرش
profile_cmd = profile_photo_cmd
