"""پروفایل تصویری پویا با کارت طلایی/سرمه‌ای و fallback متنی امن."""

import asyncio
import io
import logging

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

logger = logging.getLogger(__name__)


# ───────── داده و فرمت پروفایل ─────────

def _energy_cap(user) -> int:
    from services import energy as energy_svc
    return energy_svc.max_energy(user)


def _bar(user) -> str:
    from services import energy as energy_svc
    return bar(user.energy, energy_svc.max_energy(user))


async def _profile_payload(session, user) -> dict:
    """یک snapshot ساده برای متن و تصویر؛ هیچ ORM object وارد thread رندر نمی‌شود."""
    item_keys = await users.get_item_keys(session, user.id)
    lvls = await users.get_item_levels(session, user.id)
    user_dogs = await dog_svc.get_user_dogs(session, user.id)

    from services import teams as team_svc
    membership = await team_svc.get_membership(session, user.id)
    team = await session.get(Team, membership.team_id) if membership else None
    team_atk = team_svc.atk_bonus(team) if team else 0.0
    team_def = team_svc.def_bonus(team) if team else 0.0

    ammo = await users.get_ammo_map(session, user.id)
    atk, dfn = combat.combat_stats(user, lvls, user_dogs, team_atk, team_def, ammo=ammo)
    atk_p, def_p = combat.combat_boost_pcts(user, item_keys, user_dogs, team_atk, team_def)

    plots = await farming.get_user_plots(session, user.id)
    growing = sum(1 for p in plots if p.current_status()[0] == "growing")
    ready = sum(1 for p in plots if p.current_status()[0] == "ready")

    rank = await users.medal_rank(session, user, "all")
    total = (await session.execute(select(func.count(User.id)).where(User.lb_hidden == 0))).scalar_one()

    title_emoji, title_name = users.title_of(user)
    wkey = combat.weapon_choice(user, lvls)
    if wkey:
        weapon = config.WEAPONS[wkey]
        weapon_line = f"🔫 {esc(weapon['name'])}" if weapon.get("gun") else f"🔪 {esc(weapon['name'])}"
    else:
        weapon_line = "👊 دست خالی"
    akey = combat.armor_choice(user, lvls)
    armor_line = f"🦺 {esc(config.ARMORS[akey]['name'])}" if akey else "🦺 بدون زره"

    best_dog = max(user_dogs, key=lambda dog: (int(dog.level or 1), int(dog.xp or 0), -int(dog.id or 0))) if user_dogs else None
    is_max = int(user.level or 1) >= config.MAX_LEVEL
    xp_need = 0 if is_max else economy.xp_need(user.level)

    return {
        "name": users.display_name(user),
        "short_name": short_name(users.display_name(user)),
        "username": f"@{user.username}" if user.username else "بدون یوزرنیم",
        "title": title_name,
        "title_emoji": title_emoji,
        "joined": jalali_str(user.created_at) if user.created_at else "-",
        "level": int(user.level or 1),
        "xp": int(user.xp or 0),
        "xp_need": int(xp_need or 0),
        "max_level": is_max,
        "energy": int(user.energy or 0),
        "energy_cap": _energy_cap(user),
        "cash": int(user.cash or 0),
        "gems": int(user.gems or 0),
        "bank": int(user.bank_balance or 0),
        "wood": int(user.wood or 0),
        "iron": int(user.iron or 0),
        "rank": int(rank or 0),
        "rank_total": int(total or 0),
        "attack": int(atk),
        "defense": int(dfn),
        "power": int(atk + dfn),
        "attack_pct": round(atk_p * 100),
        "defense_pct": round(def_p * 100),
        "wins": int(user.wins or 0),
        "losses": int(user.losses or 0),
        "plots": len(plots),
        "growing": growing,
        "ready": ready,
        "weapon_line": weapon_line,
        "armor_line": armor_line,
        "dog_count": len(user_dogs),
        "dog_name": best_dog.name if best_dog else "بدون سگ",
        "dog_breed": best_dog.breed if best_dog else "—",
        "dog_level": int(best_dog.level or 1) if best_dog else 0,
        "team_name": team.name if team else "بدون کارتل",
        "team_role": membership.role if membership else "",
    }


def _profile_caption_from_payload(p: dict) -> str:
    atk_line = f"💪 حمله: {fa_num(p['attack'])}" + (
        f"(+{fa_num(p['attack_pct'])}%)" if p["attack_pct"] > 0 else ""
    )
    dfn_line = f"🛡 دفاع: {fa_num(p['defense'])}" + (
        f"(+{fa_num(p['defense_pct'])}%)" if p["defense_pct"] > 0 else ""
    )
    dog_line = f"🐕 سگ {fa_num(p['dog_count'])} عدد" if p["dog_count"] else "🐕 بدون سگ"
    if p["max_level"]:
        xp_line = f"🌟 لول {fa_num(config.MAX_LEVEL)} 👑 • ✨ {fa_num(p['xp'])}"
    else:
        xp_line = f"🌟 لول {fa_num(p['level'])} • ✨ {fa_num(p['xp'])}/{fa_num(p['xp_need'])}"

    # bar متنی fallback از مقادیر snapshot ساخته می‌شود تا در حالت خطای تصویر پروفایل کامل بماند.
    energy_bar = bar(p["energy"], p["energy_cap"])
    return (
        f"╭━━━━━━━━━━━━━━╮\n"
        f" 👤 {esc(p['short_name'])}\n"
        f"╰━━━━━━━━━━━━━━╯\n"
        f"🆔 {esc(p['username'])}\n"
        f"🏅 {p['title_emoji']} {esc(p['title'])}\n"
        f"{xp_line}\n"
        f"⚡️ انرژی {energy_bar} {fa_num(p['energy'])}/{fa_num(p['energy_cap'])}\n"
        f"🏆 رتبه {fa_num(p['rank'])} از {fa_num(p['rank_total'])}\n"
        f"📅 عضویت: {p['joined']}\n\n"
        f"<b>💰 دارایی</b>\n"
        f"🪙 {money(p['cash'])}\n"
        f"💎 جم: {fa_num(p['gems'])}\n"
        f"🏦 بانک: {fa_num(p['bank'])}\n\n"
        f"<b>🏡 مزرعه</b>\n"
        f"🌱 زمین: {fa_num(p['plots'])}\n"
        f"🌾 در حال رشد: {fa_num(p['growing'])}\n"
        f"✅ آماده برداشت: {fa_num(p['ready'])}\n\n"
        f"<b>🛡 تجهیزات</b>\n"
        f"{p['weapon_line']}\n"
        f"{p['armor_line']}\n"
        f"{dog_line}\n\n"
        f"<b>⚔️ آمار</b>\n"
        f"{atk_line}\n"
        f"{dfn_line}\n"
        f"🏋 قدرت کل: {fa_num(p['power'])}\n"
        f"✅ برد: {fa_num(p['wins'])} | ❌ باخت: {fa_num(p['losses'])}"
    )


def _card_caption(p: dict) -> str:
    """کپشن کوتاه؛ آمار اصلی داخل تصویر است و جزئیات فرعی اینجا می‌ماند."""
    return (
        f"<b>👑 پروفایل {esc(p['short_name'])}</b>\n"
        f"{p['weapon_line']}  |  {p['armor_line']}\n"
        f"🌱 زمین {fa_num(p['plots'])} | 🌾 در رشد {fa_num(p['growing'])} | ✅ آماده {fa_num(p['ready'])}"
    )


async def _profile_caption(session, user) -> str:
    """API قدیمی تست‌ها و fallback؛ متن کامل را حفظ می‌کند."""
    return _profile_caption_from_payload(await _profile_payload(session, user))


async def _send_profile(
    bot,
    chat_id: int,
    tg_id: int,
    full_caption: str,
    card_payload: dict,
    markup=None,
) -> None:
    """اول کارت لوگومحور؛ در هر خطای رندر، عکس تلگرام/متن قبلی fallback می‌شود."""
    try:
        from services.profile_card import render_profile_card

        rendered = await asyncio.to_thread(render_profile_card, card_payload)
        photo = io.BytesIO(rendered)
        photo.name = f"teriaky-profile-{tg_id}.jpg"
        await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=_card_caption(card_payload),
            parse_mode="HTML",
            reply_markup=markup,
        )
        return
    except Exception:
        logger.exception("ساخت/ارسال کارت تصویری پروفایل شکست خورد؛ fallback قدیمی اجرا شد")

    file_id = None
    try:
        photos = await bot.get_user_profile_photos(tg_id, limit=1)
        if photos and photos.total_count:
            file_id = photos.photos[0][-1].file_id
    except Exception:
        file_id = None

    if file_id:
        await bot.send_photo(
            chat_id=chat_id,
            photo=file_id,
            caption=full_caption,
            parse_mode="HTML",
            reply_markup=markup,
        )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=full_caption,
            parse_mode="HTML",
            reply_markup=markup,
        )


# ───────── دستور «پروفایل» / /profile ─────────

async def profile_photo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.apply_energy_regen(user)
        payload = await _profile_payload(s, user)
        caption = _profile_caption_from_payload(payload)
        tg_id = user.telegram_id
        await s.commit()

    await _send_profile(
        context.bot,
        update.effective_chat.id,
        tg_id,
        caption,
        payload,
        markup=None,
    )


# ───────── دکمه پروفایل تو منو ─────────

async def profile_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.apply_energy_regen(user)
        payload = await _profile_payload(s, user)
        caption = _profile_caption_from_payload(payload)
        tg_id = user.telegram_id
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        await s.commit()

    try:
        if query.message:
            await query.message.delete()
    except BadRequest:
        pass

    await _send_profile(
        context.bot,
        chat_id,
        tg_id,
        caption,
        payload,
        markup=strip_home(update, kb.profile_kb()),
    )


profile_cmd = profile_photo_cmd
