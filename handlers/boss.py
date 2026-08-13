"""
هندلرهای باس محله 👹 (راند ۲۳)
دکمه «ضربه به باس» تو گروه جمعیه (مثل کاروان) و مال همه‌ست
پنل ادمین: لیست باس‌ها با وضعیت عکس ✅/❌، تغییر عکس با پندینگ عکس، اسپان دستی تو گروه
ارسال کارت باس را همین‌جا نگه می‌داریم که جاب اسپون هم ازش استفاده کنه
"""

import logging

from telegram import Update
from telegram.constants import ChatType
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

import config
from database import session_scope
from keyboards import keyboards as kb
from models import User
from services import boss as boss_svc
from services import combat
from services import dogs as dog_svc
from services import users
from utils import esc, fa_num, money

logger = logging.getLogger("teriaky.boss")


async def send_boss_card(bot, chat_id: int, st: dict):
    """کارت باس رو می‌فرسته، عکس داشته باشه با عکس وگرنه متنی؛ پیام فرستاده‌شده یا None"""
    text = boss_svc.card_text(st)
    markup = kb.boss_kb()
    key = st["key"]
    try:
        if boss_svc.has_image(key):
            with open(boss_svc.image_path(key), "rb") as f:
                data = f.read()
            return await bot.send_photo(chat_id, photo=data, caption=text,
                                        parse_mode="HTML", reply_markup=markup)
        return await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
    except (BadRequest, Forbidden):
        return None
    except FileNotFoundError:
        try:
            return await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
        except (BadRequest, Forbidden):
            return None
    except Exception as e:
        logger.warning("boss card to %s failed: %s", chat_id, e)
        return None


async def edit_boss_board(bot, chat_id: int, message_id: int, st: dict) -> None:
    """برد زنده باس (نوار خون + برترین‌ها)، فقط با جاب دو دقیقه‌ای ادیت میشه (راند ۲۹)"""
    try:
        board = f"{boss_svc.card_text(st)}\n\n{boss_svc.board_text(st)}"
        await bot.edit_message_caption(
            chat_id=chat_id, message_id=message_id,
            caption=board, parse_mode="HTML", reply_markup=kb.boss_kb(),
        )
    except BadRequest as e:
        if "no caption" in str(e).lower() or "can't be edited" in str(e).lower():
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id,
                    text=board, parse_mode="HTML", reply_markup=kb.boss_kb(),
                )
            except BadRequest:
                pass
        elif "not modified" not in str(e).lower():
            raise


# ───────── ⚔️ دکمه ضربه به باس ─────────

async def boss_hit_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id if query.message else update.effective_chat.id

    if boss_svc.click_spam(chat_id, update.effective_user.id):
        await query.answer()
        return

    st0_key = ""
    st = boss_svc.active(chat_id)
    if not st:
        await query.answer("👹 باسی تو محله نیس، دیگه رفت", show_alert=True)
        return
    st0_key = st["key"]

    left = boss_svc.hit_left(chat_id, update.effective_user.id)
    if left:
        await query.answer(f"⏳ هر 1 دقیقه یه ضربه، {left} ثانیه مونده", show_alert=True)
        return

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        items = await users.get_item_levels(s, user.id)
        ammo = await users.get_ammo_map(s, user.id)  # راند ۲۹: تفنگ بی‌تیر تو دمیج باس حساب نیس
        dogs = await dog_svc.get_user_dogs(s, user.id)
        from services import teams as team_svc
        user_team = await team_svc.get_team_of(s, user.id)
        team_b = team_svc.atk_bonus(user_team) if user_team else 0.0
        atk, _ = combat.combat_stats(user, items, dogs, atk_extra=team_b, ammo=ammo)
        # هر ضربه یه تیر (درخواست کارفرما راند ۲۹) و جواب باس از دفاع زره کم میشه
        wkey = combat.weapon_choice(user, items, ammo)
        armor_def = combat.armor_defense(user, items)

        ammo_note = ""
        res = await boss_svc.attack(s, chat_id, user, atk, armor_def=armor_def)
        if res.get("status") in ("hit", "killed") and wkey:
            left_ammo = await users.consume_ammo(s, user.id, wkey)
            if left_ammo >= 0:
                cap = combat.ammo_cap(wkey, items.get(wkey, 1))
                ammo_note = f" | 🔫 {fa_num(left_ammo)}/{fa_num(cap)}"
        await s.commit()

        st = boss_svc.BOSSES.get(chat_id)

    if res["status"] == "cooldown":
        await query.answer(f"⏳ {res['left']} ثانیه مونده", show_alert=True)
        return

    await query.answer(
        f"⚔️ {fa_num(res['dmg'])} دمیج | 💰 {fa_num(res['cash'])}TP | 🩸 {fa_num(res['taken'])} خون رفت{ammo_note}",
        show_alert=True,
    )

    # تبریک لول‌آپ (تجربه ضربه باس) پیام جدا تو همون گروه
    from handlers.common import announce_notes
    await announce_notes(update, res.get("notes"))

    if res["status"] == "killed":
        # برد پاک میشه و پیام پایانی تازه ارسال میشه
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
        except BadRequest:
            pass
        await context.bot.send_message(
            chat_id, boss_svc.end_text(res.get("rewards", {}), res.get("key", st0_key)),
            parse_mode="HTML",
        )
    # برد بعد هر ضربه ادیت نمیشه؛ جاب هر ۲ دقیقه خودش تازه‌ش می‌کنه (راند ۲۹، مثل کاروان)


# ───────── 👹 پنل ادمین باس‌ها ─────────

def _admin_rows() -> list[tuple]:
    return [(b["key"], b["emoji"], b["name"], boss_svc.has_image(b["key"])) for b in config.BOSSES]


def _bosses_list_text() -> str:
    lines = ["<b>👹 باس‌های محله</b>", ""]
    for key, emoji, name, has_img in _admin_rows():
        boss = config.BOSS_BY_KEY[key]
        tier = config.BOSS_TIERS[boss["tier"]]
        mark = "✅" if has_img else "❌"
        line = (
            f"{mark} {emoji} <b>{esc(name)}</b> | {tier['emoji']} {tier['name']} | "
            f"💪 {fa_num(boss['hp'])} | 🎁 {money(boss['reward'])}"
        )
        lines.append(line)
    lines.append("")
    lines.append("✅ یعنی عکس داره | ❌ یعنی هنوز عکس نذاشتی")
    lines.append("رو هر باس بزن تا عکسشو عوض کنی یا دستی اسپانش کنی")
    return "\n".join(lines)


def _boss_view_text(key: str) -> str:
    boss = config.BOSS_BY_KEY[key]
    tier = config.BOSS_TIERS[boss["tier"]]
    has_img = boss_svc.has_image(key)
    return (
        f"<b>{boss['emoji']} {esc(boss['name'])} | {esc(boss['tag'])}</b>\n\n"
        f"{tier['emoji']} درجه: {tier['name']}\n"
        f"❤️ سلامتی: {fa_num(boss['hp'])} | ⚔️ قدرت: {fa_num(boss['dmg'])}\n"
        f"⚔️ سبک: {esc(boss['style'])} | 📍 {esc(boss['place'])}\n"
        f"⏳ موندگاری: {fa_num(boss['mins'])} دقیقه | 🎁 {money(boss['reward'])}\n"
        f"🖼 عکس: {'✅ داره' if has_img else '❌ نداره'}\n\n"
        "«تغییر عکس» رو بزن و بعد عکس جدید رو بفرست تا بره روی سرور"
    )


async def admin_boss_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not update.effective_user or update.effective_user.id not in config.ADMIN_IDS:
        await query.answer()
        return

    seg = query.data.split(":")
    act = seg[1] if len(seg) > 1 else "l"
    key = seg[2] if len(seg) > 2 else "0"

    # admb:l:0 → لیست باس‌ها
    if act == "l":
        from handlers.common import respond
        return await respond(update, _bosses_list_text(), kb.admin_bosses_kb(_admin_rows()))

    boss = config.BOSS_BY_KEY.get(key)
    if boss is None:
        await query.answer("❌ همچین باسی نیس", show_alert=True)
        return

    # admb:v:{key} → کارت یه باس
    if act == "v":
        from handlers.common import respond
        return await respond(update, _boss_view_text(key), kb.admin_boss_view_kb(key))

    # admb:p:{key} → شروع فلو تغییر عکس، عکس بعدی ادمین میشه عکس باس
    if act == "p":
        async with session_scope() as s:
            me, _ = await users.get_or_create(s, update.effective_user)
            from handlers.common import chat_id_of
            users.set_pending(me, "bosspic", key, chat_id_of(update))
            await s.commit()
        from handlers.common import respond
        return await respond(
            update,
            f"<b>🖼 عکس جدید {boss['emoji']} {esc(boss['name'])}</b>\n\n"
            "عکسشو همین‌جا بفرست تا بره روی سرور\n\n"
            "❌ اگر هم پشیمون شدی بنویس «لغو»",
        )

    # admb:s:{key} → اسپان دستی همین باس تو همون گروه
    if act == "s":
        chat = update.effective_chat
        if chat is None or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            await query.answer("📌 اسپان دستی باس فقط تو گروه جواب میده، پنل رو تو گروه باز کن", show_alert=True)
            return
        st = boss_svc.spawn(chat.id, dict(boss))
        msg = await send_boss_card(context.bot, chat.id, st)
        if msg:
            st["message_id"] = msg.message_id
        await query.answer(f"🚨 {boss['name']} اسپون شد", show_alert=True)
        return
