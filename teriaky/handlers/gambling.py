# -*- coding: utf-8 -*-
"""UI قمارخانه: تاس رسمی تلگرام در تک‌نفره و مسابقه دونفره."""
from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import chat_id_of, respond
from keyboards import keyboards as kb
from models import GambleMatch, User
from services import gambling as gsvc, users
from utils import esc, fa_num, money, parse_amount


def _thread_id(update: Update) -> int | None:
    msg = update.effective_message
    return getattr(msg, "message_thread_id", None) if msg else None


def _bet_error(code: str, mode: str, cash: int = 0, cd: int = 0) -> str:
    lo = config.GAMBLE_SOLO_MIN_BET if mode == "solo" else config.GAMBLE_DUEL_MIN_BET
    hi = config.GAMBLE_SOLO_MAX_BET if mode == "solo" else config.GAMBLE_DUEL_MAX_BET
    return {
        "locked": f"🔒 قمارخانه از لول {fa_num(config.GAMBLE_MIN_LEVEL)} باز میشه",
        "low": f"کمترین شرط {money(lo)}ـه",
        "high": f"بیشترین شرط این حالت {money(hi)}ـه",
        "poor": f"💸 پولت به این شرط نمی‌رسه؛ نقدت {money(cash)}ـه",
        "cooldown": f"⏳ یکم دست نگه دار؛ {fa_num(cd)} ثانیه دیگه دوباره بازی کن",
        "busy": "🎮 یه بازی باز داری؛ اول همونو تموم کن",
        "bad_dice": "❌ این بازی پشتیبانی نمیشه",
    }.get(code, "❌ نشد؛ دوباره امتحان کن")


def hub_text(cash: int) -> str:
    return (
        "<b>🎰 قمارخانه تریاکی</b>\n\n"
        f"💵 نقدت: {money(cash)}\n\n"
        "کدوم مدل رو می‌خوای؟\n\n"
        "🤖 <b>تک‌نفره</b>\n"
        "تاس، دارت، بولینگ، بسکتبال، فوتبال، اسلات و بازی مین؛ هرکدوم بخش و قانون خودش رو داره.\n\n"
        "❌⭕ <b>دوز دونفره</b>\n"
        "تو گروه لابی دوز 3×3 بساز؛ هر نفر فقط 3 مهره فعال داره و مهره چهارم، قدیمی‌ترین مهره خودشو پاک می‌کنه.\n\n"
        "نتیجه بازی‌های متحرک تک‌نفره مستقیم از خود تلگرام میاد؛ عدد دستی توی کار نیس."
    )


def two_player_text(cash: int) -> str:
    return (
        "<b>⚔️ مسابقه دونفره</b>\n\n"
        f"💵 نقدت: {money(cash)}\n\n"
        "فعلاً اینجا فقط دوز 3×3 داریم؛ بازی رو انتخاب کن، بعد مبلغ شرط رو می‌فرستی.\n\n"
        "❌⭕ هر نفر فقط 3 مهره فعال داره؛ با مهره چهارم، قدیمی‌ترین مهره خودت پاک میشه.\n"
        "📍 ساخت لابی و شروع دوز فقط تو گروه انجام میشه."
    )


def solo_text(cash: int) -> str:
    return (
        "<b>🤖 بازی‌های تک‌نفره</b>\n\n"
        f"💵 نقدت: {money(cash)}\n\n"
        "هر بازی صفحه، حرکت و قانون برد خودش رو داره؛ یکی رو انتخاب کن.\n"
        f"محدوده شرط: {money(config.GAMBLE_SOLO_MIN_BET)} تا {money(config.GAMBLE_SOLO_MAX_BET)}"
    )


def solo_game_text(code: str, cash: int) -> str:
    spec = gsvc.dice_spec(code) or {}
    return (
        f"<b>{spec.get('emoji', '🎮')} {spec.get('name', 'بازی')}</b>\n\n"
        f"🎯 {spec.get('rule', '')}\n\n"
        f"💵 نقدت: {money(cash)}\n"
        f"💰 شرط: {money(config.GAMBLE_SOLO_MIN_BET)} تا {money(config.GAMBLE_SOLO_MAX_BET)}\n\n"
        "نتیجه حرکت رو خود تلگرام مشخص می‌کنه."
    )


def solo_confirm_text(code: str, bet: int, cash: int) -> str:
    spec = gsvc.dice_spec(code) or {}
    return (
        f"<b>{spec.get('emoji', '🎮')} {spec.get('name', 'بازی')}</b>\n\n"
        f"💰 شرط: {money(bet)}\n"
        f"🎯 {spec.get('rule', '')}\n"
        f"💵 نقدت: {money(cash)}\n\n"
        f"تأیید کنی، شرط قفل میشه و {spec.get('action', 'حرکت بازی')} با انیمیشن رسمی تلگرام انجام میشه."
    )


def solo_result_text(res: dict) -> str:
    if res["won"]:
        return (
            f"<b>🏆 بردی! {res['emoji']} {res['outcome']}</b>\n\n"
            f"🎁 ضریب این برد: ×{res['multiplier']:g}\n"
            f"💰 پرداخت: {money(res['payout'])}\n"
            f"📈 سود خالص: {money(res['net'])}\n"
            f"💵 نقدت: {money(res['cash'])}"
        )
    return (
        f"<b>💸 این دست باختی</b>\n\n"
        f"{res['emoji']} {res['outcome']}\n"
        f"شرط {money(res['bet'])} سوخت\n"
        f"💵 نقدت: {money(res['cash'])}"
    )


async def gambling_hub_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        if user.pending_action in ("gsolo", "gduel"):
            users.set_pending(user, None)
        level, cash = user.level, int(user.cash or 0)
        await s.commit()
    if level < config.GAMBLE_MIN_LEVEL:
        return await respond(update, f"🔒 قمارخانه از لول {fa_num(config.GAMBLE_MIN_LEVEL)} باز میشه")
    await respond(update, hub_text(cash), kb.gamble_hub_kb())


async def _start_solo_amount(update: Update, code: str) -> None:
    spec = gsvc.dice_spec(code)
    if not spec:
        return await respond(update, "❌ این بازی پیدا نشد")
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        if user.level < config.GAMBLE_MIN_LEVEL:
            await s.commit()
            return await respond(update, f"🔒 قمارخانه از لول {fa_num(config.GAMBLE_MIN_LEVEL)} باز میشه")
        users.set_pending(user, "gsolo", value=code, chat_id=chat_id_of(update))
        cash = int(user.cash or 0)
        await s.commit()
    await respond(
        update,
        f"<b>{spec['emoji']} شرط {spec['name']}</b>\n\n"
        f"یه مبلغ بین {money(config.GAMBLE_SOLO_MIN_BET)} تا {money(config.GAMBLE_SOLO_MAX_BET)} بفرست.\n"
        f"💵 نقدت: {money(cash)}\n\nبرای بی‌خیال‌شدن بنویس «لغو»",
        kb.gamble_back_kb(f"gm:game:{code}"),
    )


async def _start_duel_amount(update: Update) -> None:
    chat = update.effective_chat
    if chat is None or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return await respond(update, "❌⭕ دوز دونفره فقط تو گروه ساخته میشه؛ رباتو ببر گروه و همون‌جا قمارخانه رو باز کن")
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        if user.level < config.GAMBLE_MIN_LEVEL:
            await s.commit()
            return await respond(update, f"🔒 مسابقه از لول {fa_num(config.GAMBLE_MIN_LEVEL)} باز میشه")
        users.set_pending(user, "gduel", chat_id=chat.id)
        cash = int(user.cash or 0)
        await s.commit()
    await respond(
        update,
        "<b>❌⭕ ساخت دوز دونفره 3×3</b>\n\n"
        f"شرط هر نفر رو بین {money(config.GAMBLE_DUEL_MIN_BET)} تا {money(config.GAMBLE_DUEL_MAX_BET)} بفرست.\n"
        f"💵 نقدت: {money(cash)}\n\nبعدش لابی عمومی ساخته میشه و مدل سری رو انتخاب می‌کنی. برای لغو بنویس «لغو»",
        kb.gamble_back_kb("gm:duel"),
    )


async def consume_pending_bet(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, text: str) -> bool:
    """از pending.capture صدا زده می‌شود؛ True یعنی متن مصرف شد."""
    if action not in ("gsolo", "gduel"):
        return False
    if text.strip() == "لغو":
        async with session_scope() as s:
            user = await users.get_by_tg(s, update.effective_user.id)
            if user:
                users.set_pending(user, None)
                await s.commit()
        await update.effective_message.reply_html("باشه، بی‌خیال شرط شدیم 👌")
        return True
    amount = parse_amount(text)
    mode = "solo" if action == "gsolo" else "duel"
    async with session_scope() as s:
        user = await users.get_by_tg(s, update.effective_user.id)
        if user is None:
            return False
        if amount is None:
            await s.commit()
            await update.effective_message.reply_html("🤷 فقط مبلغ مثبت بفرست؛ مثلاً <code>5000</code>")
            return True
        ok, why = gsvc.valid_bet(user, amount, mode)
        if not ok:
            cash = int(user.cash or 0)
            await s.commit()
            await update.effective_message.reply_html(_bet_error(why, mode, cash))
            return True
        game_code = user.pending_value if mode == "solo" else None
        users.set_pending(user, None)
        if mode == "solo":
            spec = gsvc.dice_spec(game_code or "")
            if not spec:
                await s.commit()
                await update.effective_message.reply_html("❌ بازی انتخاب‌شده پیدا نشد؛ دوباره از قمارخانه انتخابش کن")
                return True
            cash = int(user.cash or 0)
            await s.commit()
            await update.effective_message.reply_html(
                solo_confirm_text(game_code, amount, cash),
                reply_markup=kb.gamble_solo_confirm_kb(game_code, amount, update.effective_user.id),
            )
            return True
        match, why = await gsvc.create_match(s, user, chat_id_of(update), _thread_id(update), amount)
        creator_name = esc(users.display_name(user))
        await s.commit()
    if not match:
        await update.effective_message.reply_html(_bet_error(why, mode, 0))
        return True
    sent = await update.effective_message.reply_html(
        _lobby_wait_text(match.id, creator_name, amount),
        reply_markup=kb.gamble_lobby_wait_kb(match.id),
    )
    async with session_scope() as s:
        await gsvc.bind_lobby_message(s, match.id, getattr(sent, "message_id", None))
        await s.commit()
    return True


def _lobby_wait_text(match_id: int, creator_name: str, bet: int) -> str:
    return (
        f"<b>❌⭕ لابی دوز #{fa_num(match_id)}</b>\n\n"
        f"👑 سازنده: {creator_name}\n"
        f"💰 شرط هر نفر: {money(bet)}\n"
        f"🏆 صندوق نهایی: {money(bet * 2)}\n"
        "🎮 برد: 3×3 با قانون 3 مهره فعال\n\n"
        "یه نفر تا 10 دقیقه فرصت داره چالش رو قبول کنه.\n"
        "بعد انتخاب مدل، هر دو نفر جدا شرط رو تأیید می‌کنن. هر مرحله 10 دقیقه بی‌حرکت بمونه، پول هر دو کامل پس داده میشه."
    )


async def _match_view(session, match_id: int) -> tuple[object, dict] | tuple[None, dict]:
    row = await session.get(GambleMatch, match_id)
    if row is None:
        return None, {}
    creator = await session.get(User, row.creator_id)
    opponent = await session.get(User, row.opponent_id) if row.opponent_id else None
    turn = await session.get(User, row.turn_user_id) if row.turn_user_id else None
    return row, {
        "creator": creator,
        "opponent": opponent,
        "turn": turn,
        "creator_name": esc(users.display_name(creator)) if creator else "سازنده",
        "opponent_name": esc(users.display_name(opponent)) if opponent else "منتظر حریف",
        "turn_name": esc(users.display_name(turn)) if turn else "—",
    }


def _mode_label(rounds: int | None) -> str:
    return {1: "تک‌دست سریع", 3: "دو برد از سه", 5: "سه برد از پنج"}.get(rounds, "انتخاب‌نشده")


def _config_mode_text(row, view: dict) -> str:
    return (
        f"<b>❌⭕ تنظیم دوز #{fa_num(row.id)}</b>\n\n"
        f"❌ {view['creator_name']}  VS  ⭕ {view['opponent_name']}\n"
        f"💰 شرط هر نفر: {money(row.bet_per_player)}\n\n"
        "سازنده مدل مسابقه رو انتخاب کنه؛ هر سه مدل قانون 3 مهره فعال دارن:"
    )


def _confirm_text(row, view: dict) -> str:
    creator_state = "✅" if row.creator_confirmed else "⏳"
    opponent_state = "✅" if row.opponent_confirmed else "⏳"
    return (
        f"<b>❌⭕ تأیید دوز #{fa_num(row.id)}</b>\n\n"
        f"🎮 مدل: {_mode_label(row.rounds_total)}\n"
        f"💰 شرط هر نفر: {money(row.bet_per_player)}\n"
        f"🏆 صندوق: {money(row.bet_per_player * 2)}\n\n"
        f"{creator_state} {view['creator_name']}\n"
        f"{opponent_state} {view['opponent_name']}\n\n"
        "هر نفر تأیید کنه سهم خودش همون لحظه میره تو صندوق. 10 دقیقه بی‌حرکتی یعنی استرداد کامل هر دو نفر."
    )


def _board_text(row, view: dict, note: str | None = None) -> str:
    lines = [
        f"<b>❌⭕ دوز #{fa_num(row.id)} | دست {fa_num(row.current_round)}</b>",
        "",
        f"🎮 {_mode_label(row.rounds_total)}",
        f"🏁 {view['creator_name']}  {fa_num(row.creator_score)} - {fa_num(row.opponent_score)}  {view['opponent_name']}",
        f"❌ {view['creator_name']}  |  ⭕ {view['opponent_name']}",
    ]
    if row.status == "active":
        lines += [f"👉 نوبت: {view['turn_name']}"]
    if note:
        lines += ["", note]
    lines += [
        "",
        "هر نفر فقط 3 مهره فعال داره؛ مهره چهارم که بیاد، قدیمی‌ترین مهره خودش پاک میشه.",
        "❎ و 🔘 یعنی مهره‌ای که دفعه بعد نوبت حذفشه.",
    ]
    if row.status == "active":
        lines.append("⏳ هر حرکت قانونی تایمر 10 دقیقه‌ای رو از نو شروع می‌کنه.")
    return "\n".join(lines)


async def _edit_match(context, row, text: str, markup=None) -> None:
    if not row or not row.lobby_message_id:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=row.chat_id,
            message_id=row.lobby_message_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            pass
    except TelegramError:
        pass


async def gambling_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    parts_data = data.split(":")
    if data == "gm:h":
        return await gambling_hub_cmd(update, context)
    if data == "gm:solo":
        async with session_scope() as session:
            user, _ = await users.get_or_create(session, update.effective_user)
            if user.pending_action in ("gsolo", "gduel"):
                users.set_pending(user, None)
            cash, level = int(user.cash or 0), user.level
            await session.commit()
        if level < config.GAMBLE_MIN_LEVEL:
            return await query.answer(f"🔒 لول {config.GAMBLE_MIN_LEVEL} می‌خواد", show_alert=True)
        return await respond(update, solo_text(cash), kb.gamble_solo_kb())
    if len(parts_data) == 3 and parts_data[1] == "game" and gsvc.dice_spec(parts_data[2]):
        code = parts_data[2]
        async with session_scope() as session:
            user, _ = await users.get_or_create(session, update.effective_user)
            if user.pending_action in ("gsolo", "gduel"):
                users.set_pending(user, None)
            cash = int(user.cash or 0)
            await session.commit()
        return await respond(update, solo_game_text(code, cash), kb.gamble_game_kb(code))
    if len(parts_data) == 3 and parts_data[1] == "gb" and gsvc.dice_spec(parts_data[2]):
        return await _start_solo_amount(update, parts_data[2])
    if data == "gm:mine":
        from handlers import mines
        return await mines.mines_hub_cmd(update, context)
    if data == "gm:duel":
        async with session_scope() as session:
            user, _ = await users.get_or_create(session, update.effective_user)
            if user.pending_action in ("gsolo", "gduel"):
                users.set_pending(user, None)
            cash, level = int(user.cash or 0), int(user.level or 1)
            await session.commit()
        if level < config.GAMBLE_MIN_LEVEL:
            return await query.answer(f"🔒 لول {config.GAMBLE_MIN_LEVEL} می‌خواد", show_alert=True)
        return await respond(update, two_player_text(cash), kb.gamble_two_player_kb())
    if data == "gm:duel:t3":
        return await _start_duel_amount(update)

    if len(parts_data) == 5 and parts_data[1] == "sr":
        code, bet_s, owner_s = parts_data[2], parts_data[3], parts_data[4]
        if not bet_s.isdigit() or not owner_s.isdigit() or int(owner_s) != update.effective_user.id:
            return await query.answer()
        return await _solo_roll(update, context, code, int(bet_s))
    if len(parts_data) == 4 and parts_data[1] == "sc":
        code, bet_s = parts_data[2], parts_data[3]
        if not bet_s.isdigit() or not gsvc.dice_spec(code):
            return await query.answer()
        async with session_scope() as session:
            user, _ = await users.get_or_create(session, update.effective_user)
            cash = int(user.cash or 0)
            ok, why = gsvc.valid_bet(user, int(bet_s), "solo")
            await session.commit()
        if not ok:
            return await query.answer(_bet_error(why, "solo", cash), show_alert=True)
        return await respond(
            update,
            solo_confirm_text(code, int(bet_s), cash),
            kb.gamble_solo_confirm_kb(code, int(bet_s), update.effective_user.id),
        )

    if len(parts_data) >= 3 and parts_data[2].isdigit():
        match_id = int(parts_data[2])
        async with gsvc.lock_for(f"match:{match_id}"):
            if parts_data[1] == "da":
                return await _duel_accept(update, context, match_id)
            if parts_data[1] == "dr" and len(parts_data) == 4 and parts_data[3].isdigit():
                return await _duel_rounds(update, context, match_id, int(parts_data[3]))
            if parts_data[1] == "dc":
                return await _duel_confirm(update, context, match_id)
            if parts_data[1] == "tp" and len(parts_data) == 4 and parts_data[3].isdigit():
                return await _ttt_place(update, context, match_id, int(parts_data[3]))
            if parts_data[1] == "dx":
                return await _duel_cancel(update, context, match_id)
    await query.answer()


async def _solo_roll(update: Update, context, code: str, bet: int) -> None:
    query = update.callback_query
    uid = update.effective_user.id
    async with gsvc.lock_for(f"solo:{uid}"):
        async with session_scope() as session:
            user, _ = await users.get_or_create(session, update.effective_user)
            row, why = await gsvc.reserve_solo(
                session, user, chat_id_of(update), _thread_id(update), code, bet,
            )
            cash, cooldown = int(user.cash or 0), gsvc.cooldown_left(user)
            await session.commit()
        if row is None:
            return await query.answer(_bet_error(why, "solo", cash, cooldown), show_alert=True)
        spec = gsvc.dice_spec(code) or {}
        await query.answer(f"{spec.get('emoji', '🎮')} {spec.get('action', 'حرکت بازی')} شروع شد...")
        try:
            message = await context.bot.send_dice(
                chat_id=chat_id_of(update),
                emoji=gsvc.dice_spec(code)["emoji"],
                message_thread_id=_thread_id(update),
            )
            value = int(message.dice.value)
        except (TelegramError, AttributeError, TypeError, ValueError):
            async with session_scope() as session:
                await gsvc.refund_solo(session, row.id, "telegram_error")
                await session.commit()
            return await respond(
                update,
                f"❌ تلگرام حرکت بازی رو نفرستاد؛ شرط {money(bet)} کامل برگشت جیبت",
                kb.gamble_game_kb(code),
            )
        await asyncio.sleep(config.GAMBLE_DICE_ANIMATION_SECONDS)
        async with session_scope() as session:
            result = await gsvc.settle_solo(session, row.id, value, getattr(message, "message_id", None))
            await session.commit()
        if not result.get("ok"):
            return await respond(update, "❌ نتیجه ثبت نشد؛ جاب بازیابی شرطت رو سالم برمی‌گردونه")
        await respond(update, solo_result_text(result), kb.gamble_solo_result_kb(code, bet, uid))


async def _duel_accept(update, context, match_id: int) -> None:
    query = update.callback_query
    async with session_scope() as session:
        player, _ = await users.get_or_create(session, update.effective_user)
        row, why = await gsvc.accept_match(session, match_id, player)
        view_row, view = await _match_view(session, match_id) if row else (None, {})
        await session.commit()
    if why:
        message = {
            "self": "خودت نمی‌تونی حریف خودت شی 😄",
            "poor": "پولت به شرط این مسابقه نمی‌رسه",
            "busy": "یه مسابقه باز داری",
            "locked": f"لول {config.GAMBLE_MIN_LEVEL} می‌خواد",
            "expired": "وقت لابی تموم شده",
            "closed": "این لابی دیگه باز نیس",
        }.get(why, "نشد")
        return await query.answer(message, show_alert=True)
    await query.answer("❌⭕ چالش رو قبول کردی")
    await _edit_match(context, view_row, _config_mode_text(view_row, view), kb.gamble_ttt_modes_kb(match_id))


async def _duel_rounds(update, context, match_id: int, rounds: int) -> None:
    query = update.callback_query
    async with session_scope() as session:
        actor, _ = await users.get_or_create(session, update.effective_user)
        row, why = await gsvc.set_match_rounds(session, match_id, actor, rounds)
        view_row, view = await _match_view(session, match_id) if row else (None, {})
        await session.commit()
    if why:
        return await query.answer(
            "فقط سازنده می‌تونه تنظیم کنه" if why == "owner" else "تنظیم نامعتبره",
            show_alert=True,
        )
    await query.answer()
    await _edit_match(context, view_row, _confirm_text(view_row, view), kb.gamble_duel_confirm_kb(match_id))


async def _duel_confirm(update, context, match_id: int) -> None:
    query = update.callback_query
    async with session_scope() as session:
        actor, _ = await users.get_or_create(session, update.effective_user)
        row, why, started = await gsvc.confirm_match(session, match_id, actor)
        await session.flush()
        view_row, view = await _match_view(session, match_id) if row else (None, {})
        await session.commit()
    if why:
        message = {
            "poor": "پولت به شرط نمی‌رسه",
            "stranger": "این مسابقه مال تو نیس",
            "already": "قبلاً تأیید کردی",
            "closed": "مرحله تأیید بسته شده",
        }.get(why, "نشد")
        return await query.answer(message, show_alert=True)
    await query.answer("✅ سهمت رفت تو صندوق" if not started else "🔥 دوز شروع شد")
    if started:
        await _edit_match(
            context,
            view_row,
            _board_text(view_row, view),
            kb.gamble_ttt_board_kb(view_row),
        )
    else:
        await _edit_match(context, view_row, _confirm_text(view_row, view), kb.gamble_duel_confirm_kb(match_id))


async def _ttt_place(update, context, match_id: int, cell: int) -> None:
    query = update.callback_query
    async with session_scope() as session:
        actor, _ = await users.get_or_create(session, update.effective_user)
        result = await gsvc.play_ttt(session, match_id, actor, cell)
        row, view = await _match_view(session, match_id)
        winner = await session.get(User, result.get("winner_id")) if result.get("winner_id") else None
        await session.commit()
    if not result.get("ok"):
        message = {
            "closed": "این دوز دیگه باز نیس",
            "stranger": "این بازی مال تو نیس",
            "turn": "الان نوبت تو نیست",
            "occupied": "این خونه پره؛ یه خونه خالی بزن",
            "cell": "خونه نامعتبره",
        }.get(result.get("reason"), "حرکت ثبت نشد")
        return await query.answer(message, show_alert=result.get("reason") != "occupied")

    await query.answer("مهره قدیمیت پاک شد و مهره جدید نشست" if result.get("removed") is not None else "حرکت ثبت شد")
    note = None
    if result.get("finished"):
        winner_name = esc(users.display_name(winner)) if winner else "برنده"
        note = f"🏆 {winner_name} سری رو برد و {money(result['payout'])} صندوق رو گرفت!"
        return await _edit_match(
            context,
            row,
            _board_text(row, view, note),
            kb.gamble_ttt_board_kb(row, finished=True),
        )
    if result.get("round_won"):
        winner_name = esc(users.display_name(winner)) if winner else "برنده"
        note = f"✅ {winner_name} این دست رو برد؛ دست بعدی شروع شد."
    elif result.get("draw"):
        note = "🤝 این دست بعد از 60 حرکت مساوی شد؛ یه برد تازه شروع شد."
    await _edit_match(context, row, _board_text(row, view, note), kb.gamble_ttt_board_kb(row))


async def _duel_cancel(update, context, match_id: int) -> None:
    query = update.callback_query
    async with session_scope() as session:
        actor, _ = await users.get_or_create(session, update.effective_user)
        row, why, refunded = await gsvc.cancel_match(session, match_id, actor)
        await session.commit()
    if why:
        return await query.answer(
            "بعد شروع مسابقه دیگه لغو نداره" if why == "closed" else "این مسابقه مال تو نیس",
            show_alert=True,
        )
    await query.answer("مسابقه لغو شد")
    await _edit_match(
        context,
        row,
        f"<b>❌ دوز #{fa_num(match_id)} لغو شد</b>\n\n💰 {money(refunded)} از صندوق پس داده شد",
        kb.gamble_finished_kb(),
    )
