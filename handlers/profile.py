"""پروفایل، عکس تلگرام + کپشن فانتزی، دستور و دکمه هر دو همون متن"""

from sqlalchemy import func, select
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import strip_home
from keyboards import keyboards as kb
from models import Team, User
from services import combat, dogs as dog_svc, economy, farming, users
from utils import bar, esc, fa_num, jalali_str, money, short_name

# ───────── فرمت پروفایل ─────────

def _energy_cap(user) -> int:
    from services import energy as energy_svc
    return energy_svc.max_energy(user)


def _bar(user) -> str:
    # راند ۳۱ (باگ‌فیکس): سقف انرژی پویاست (استقامت هر لول +20)، نمایش هم از سقف خود کاربر حساب میشه
    from services import energy as energy_svc
    return bar(user.energy, energy_svc.max_energy(user))


async def _profile_caption(session, user) -> str:
    item_keys = await users.get_item_keys(session, user.id)
    lvls = await users.get_item_levels(session, user.id)
    user_dogs = await dog_svc.get_user_dogs(session, user.id)
    from services import teams as team_svc
    _tm = await team_svc.get_membership(session, user.id)
    _tb_atk = team_svc.atk_bonus(await session.get(Team, _tm.team_id)) if _tm else 0.0
    _tb_def = team_svc.def_bonus(await session.get(Team, _tm.team_id)) if _tm else 0.0
    _ammo30 = await users.get_ammo_map(session, user.id)  # راند ۳۰: تفنگ بی‌تیر قدرتش حساب نیس
    atk, dfn = combat.combat_stats(user, lvls, user_dogs, _tb_atk, _tb_def, ammo=_ammo30)  # راند ۳۰ (باگ کارفرما): لول ارتقا تو قدرت پروفایل حساب بشه
    # درصد بوستها همه additive یه‌جا (نژاد سگ + آرتیفکت + مهارت + ساختمان کارتل)، مثل 458(+20%)
    # سلاح و زره عدد ثابتن و توی درصد نمیان که عدد باگ نده
    atk_p, def_p = combat.combat_boost_pcts(user, item_keys, user_dogs, _tb_atk, _tb_def)
    atk_pct = round(atk_p * 100)
    dfn_pct = round(def_p * 100)
    atk_line = f"💪 حمله: {fa_num(atk)}" + (f"(+{fa_num(atk_pct)}%)" if atk_pct > 0 else "")
    dfn_line = f"🛡 دفاع: {fa_num(dfn)}" + (f"(+{fa_num(dfn_pct)}%)" if dfn_pct > 0 else "")
    plots = await farming.get_user_plots(session, user.id)

    growing = sum(1 for p in plots if p.current_status()[0] == "growing")
    ready = sum(1 for p in plots if p.current_status()[0] == "ready")

    # راند ۱۹ (باگ گزارش‌شده کارفرما): رتبه بر اساس مدال کلی درسته، نه پول نقد
    rank = await users.medal_rank(session, user, "all")
    total = (await session.execute(select(func.count(User.id)).where(User.lb_hidden == 0))).scalar_one()

    name = esc(short_name(users.display_name(user)))
    uname = f"@{esc(user.username)}" if user.username else "بدون یوزرنیم"
    temoji, tname = users.title_of(user)
    # تاریخ عضویت به شمسی
    joined = jalali_str(user.created_at) if user.created_at else "-"
    # سلاح و زره فعال (تجهیزشده یا بهترین انبار)
    wkey = combat.weapon_choice(user, lvls)
    if wkey:
        w = config.WEAPONS[wkey]
        weapon_line = f"🔫 {esc(w['name'])}" if w.get("gun") else f"🔪 {esc(w['name'])}"
    else:
        weapon_line = "👊 دست خالی"
    akey = combat.armor_choice(user, lvls)
    armor_line = f"🦺 {esc(config.ARMORS[akey]['name'])}" if akey else "🦺 بدون زره"
    # سگ فقط به تعداد نمایش داده میشه، نه اسم نه نژاد
    dog_line = f"🐕 سگ {fa_num(len(user_dogs))} عدد" if user_dogs else "🐕 بدون سگ"

    if user.level >= config.MAX_LEVEL:
        xp_line = f"🌟 لول {fa_num(config.MAX_LEVEL)} 👑 • ✨ {fa_num(user.xp)}"
    else:
        xp_line = f"🌟 لول {fa_num(user.level)} • ✨ {fa_num(user.xp)}/{fa_num(economy.xp_need(user.level))}"

    return (
        f"╭━━━━━━━━━━━━━━╮\n"
        f" 👤 {name}\n"
        f"╰━━━━━━━━━━━━━━╯\n"
        f"🆔 {uname}\n"
        f"🏅 {temoji} {tname}\n"
        f"{xp_line}\n"
        f"⚡️ انرژی {_bar(user)} {fa_num(user.energy)}/{fa_num(_energy_cap(user))}\n"
        f"🏆 رتبه {fa_num(rank)} از {fa_num(total)}\n"
        f"📅 عضویت: {joined}\n\n"
        f"<b>💰 دارایی</b>\n"
        f"🪙 {money(user.cash)}\n"
        f"💎 جم: {fa_num(user.gems or 0)}\n"
        f"🏦 بانک: {fa_num(user.bank_balance)}\n\n"
        f"<b>🏡 مزرعه</b>\n"
        f"🌱 زمین: {fa_num(len(plots))}\n"
        f"🌾 در حال رشد: {fa_num(growing)}\n"
        f"✅ آماده برداشت: {fa_num(ready)}\n\n"
        f"<b>🛡 تجهیزات</b>\n"
        f"{weapon_line}\n"
        f"{armor_line}\n"
        f"{dog_line}\n\n"
        f"<b>⚔️ آمار</b>\n"
        f"{atk_line}\n"
        f"{dfn_line}\n"
        f"🏋 قدرت کل: {fa_num(atk + dfn)}\n"
        f"✅ برد: {fa_num(user.wins)} | ❌ باخت: {fa_num(user.losses)}"
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

    # قاب ادیت نمیشه به عکس، پاک می‌کنیم و تازه می‌فرسکارتل
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
