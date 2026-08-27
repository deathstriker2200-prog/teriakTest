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
from utils import esc, fa_dur, fa_num, money, parse_amount


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
        "cooldown": f"⏳ یکم دست نگه دار؛ {fa_dur(cd)} دیگه دوباره بازی کن",
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
        "⚔️ <b>مسابقه دونفره</b>\n"
        "تو گروه لابی بساز، حریف بگیر و بازی رسمی تلگرام رو انتخاب کن.\n\n"
        "نتیجه همه بازی‌های متحرک مستقیم از خود تلگرام میاد؛ عدد دستی توی کار نیس."
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
        return await respond(update, "⚔️ مسابقه دونفره فقط تو گروه ساخته میشه؛ رباتو ببر گروه و همون‌جا قمارخانه رو باز کن")
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
        "<b>⚔️ ساخت مسابقه دونفره</b>\n\n"
        f"شرط هر نفر رو بین {money(config.GAMBLE_DUEL_MIN_BET)} تا {money(config.GAMBLE_DUEL_MAX_BET)} بفرست.\n"
        f"💵 نقدت: {money(cash)}\n\nبعدش لابی عمومی ساخته میشه. برای لغو بنویس «لغو»",
        kb.gamble_back_kb("gm:h"),
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
        f"<b>⚔️ لابی بازی رسمی #{fa_num(match_id)}</b>\n\n"
        f"👑 سازنده: {creator_name}\n"
        f"💰 شرط هر نفر: {money(bet)}\n"
        f"🏆 صندوق نهایی: {money(bet * 2)}\n\n"
        f"یه نفر تا {fa_dur(config.GAMBLE_LOBBY_SECONDS)} فرصت داره چالش رو قبول کنه.\n"
        "پول بعد از تأیید جداگانه هر دو نفر وارد صندوق میشه. هر مرحله ۱۰ دقیقه بی‌حرکت بمونه، بازی بسته و پول هر دو پس داده میشه."
    )


async def _match_view(session, match_id: int) -> tuple[object, dict] | tuple[None, dict]:
    row = await session.get(GambleMatch, match_id)
    if row is None:
        return None, {}
    creator = await session.get(User, row.creator_id)
    opponent = await session.get(User, row.opponent_id) if row.opponent_id else None
    rnd = await gsvc.current_round(session, row) if row.status == "active" else None
    return row, {
        "creator": creator, "opponent": opponent, "round": rnd,
        "creator_name": esc(users.display_name(creator)) if creator else "سازنده",
        "opponent_name": esc(users.display_name(opponent)) if opponent else "منتظر حریف",
    }


def _config_emoji_text(row, v: dict) -> str:
    return (
        f"<b>⚔️ مسابقه #{fa_num(row.id)}</b>\n\n"
        f"👑 {v['creator_name']}  VS  {v['opponent_name']}\n"
        f"💰 شرط هر نفر: {money(row.bet_per_player)}\n\n"
        "سازنده باید بازی رسمی تلگرام رو انتخاب کنه:"
    )


def _config_rounds_text(row, v: dict) -> str:
    spec = gsvc.dice_spec(gsvc.dice_code(row.emoji or "") or "") or {}
    return (
        f"<b>{row.emoji} {spec.get('name', 'بازی')} | تنظیم مسابقه #{fa_num(row.id)}</b>\n\n"
        f"👑 {v['creator_name']}  VS  {v['opponent_name']}\n"
        f"💰 شرط هر نفر: {money(row.bet_per_player)}\n\n"
        "حالا تعداد راند رو انتخاب کن؛ مسابقه به شکل best-of برگزار میشه:"
    )


def _confirm_text(row, v: dict) -> str:
    c = "✅" if row.creator_confirmed else "⏳"
    o = "✅" if row.opponent_confirmed else "⏳"
    spec = gsvc.dice_spec(gsvc.dice_code(row.emoji or "") or "") or {}
    return (
        f"<b>{row.emoji} تأیید {spec.get('name', 'مسابقه')} #{fa_num(row.id)}</b>\n\n"
        f"💰 شرط هر نفر: {money(row.bet_per_player)}\n"
        f"🏆 صندوق: {money(row.bet_per_player * 2)}\n"
        f"🎮 تعداد: best-of-{fa_num(row.rounds_total)}\n\n"
        f"{c} {v['creator_name']}\n{o} {v['opponent_name']}\n\n"
        "هر نفر تأیید کنه سهم خودش همون لحظه امانت میشه. هر مرحله ۱۰ دقیقه ادامه پیدا نکنه، بازی بسته و سهم هر دو کامل پس داده میشه."
    )


def _duel_roll_kb(row):
    return kb.gamble_duel_roll_kb(row.id, gsvc.dice_code(row.emoji or ""))


def _duel_result_label(code: str, value: int) -> str:
    return f"{gsvc.outcome_text(code, value)} — امتیاز رسمی {fa_num(value)}"


def _round_text(row, v: dict, note: str | None = None) -> str:
    rnd = v.get("round")
    cv = getattr(rnd, "creator_value", None)
    ov = getattr(rnd, "opponent_value", None)
    spec = gsvc.dice_spec(gsvc.dice_code(row.emoji or "") or "") or {}
    action = spec.get("action", "حرکت بازی")
    lines = [
        f"<b>{row.emoji} {spec.get('name', 'مسابقه')} #{fa_num(row.id)} | راند {fa_num(row.current_round)}</b>", "",
        f"🏁 امتیاز: {v['creator_name']} {fa_num(row.creator_score)} - {fa_num(row.opponent_score)} {v['opponent_name']}",
        f"👑 {v['creator_name']}: " + (f"{action} انجام شد؛ امتیاز {fa_num(cv)} ✅" if cv is not None else f"منتظر {action} ⏳"),
        f"⚔️ {v['opponent_name']}: " + (f"{action} انجام شد؛ امتیاز {fa_num(ov)} ✅" if ov is not None else f"منتظر {action} ⏳"),
    ]
    if note:
        lines += ["", note]
    lines += ["", "اگر تا ۱۰ دقیقه بازی ادامه پیدا نکنه، مسابقه بسته و پول هر دو کامل پس داده میشه."]
    return "\n".join(lines)


async def _edit_match(context, row, text: str, markup=None) -> None:
    if not row or not row.lobby_message_id:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=row.chat_id, message_id=row.lobby_message_id, text=text,
            parse_mode=ParseMode.HTML, reply_markup=markup,
        )
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            pass
    except TelegramError:
        pass


async def gambling_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    data = q.data or ""
    p = data.split(":")
    if data == "gm:h":
        return await gambling_hub_cmd(update, context)
    if data == "gm:solo":
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            if user.pending_action in ("gsolo", "gduel"):
                users.set_pending(user, None)
            cash, level = int(user.cash or 0), user.level
            await s.commit()
        if level < config.GAMBLE_MIN_LEVEL:
            return await q.answer(f"🔒 لول {config.GAMBLE_MIN_LEVEL} می‌خواد", show_alert=True)
        return await respond(update, solo_text(cash), kb.gamble_solo_kb())
    if len(p) == 3 and p[1] == "game" and gsvc.dice_spec(p[2]):
        code = p[2]
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            if user.pending_action in ("gsolo", "gduel"):
                users.set_pending(user, None)
            cash = int(user.cash or 0)
            await s.commit()
        return await respond(update, solo_game_text(code, cash), kb.gamble_game_kb(code))
    if len(p) == 3 and p[1] == "gb" and gsvc.dice_spec(p[2]):
        return await _start_solo_amount(update, p[2])
    if data == "gm:mine":
        from handlers import mines
        return await mines.mines_hub_cmd(update, context)
    if data == "gm:duel":
        return await _start_duel_amount(update)

    if len(p) == 5 and p[1] == "sr":
        code, bet_s, owner_s = p[2], p[3], p[4]
        if not bet_s.isdigit() or not owner_s.isdigit() or int(owner_s) != update.effective_user.id:
            return await q.answer()
        return await _solo_roll(update, context, code, int(bet_s))
    if len(p) == 4 and p[1] == "sc":
        code, bet_s = p[2], p[3]
        if not bet_s.isdigit() or not gsvc.dice_spec(code):
            return await q.answer()
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            cash = int(user.cash or 0)
            ok, why = gsvc.valid_bet(user, int(bet_s), "solo")
            await s.commit()
        if not ok:
            return await q.answer(_bet_error(why, "solo", cash), show_alert=True)
        return await respond(update, solo_confirm_text(code, int(bet_s), cash),
                             kb.gamble_solo_confirm_kb(code, int(bet_s), update.effective_user.id))

    if len(p) >= 3 and p[2].isdigit():
        match_id = int(p[2])
        async with gsvc.lock_for(f"match:{match_id}"):
            if p[1] == "da":
                return await _duel_accept(update, context, match_id)
            if p[1] == "de" and len(p) == 4:
                return await _duel_emoji(update, context, match_id, p[3])
            if p[1] == "dr" and len(p) == 4 and p[3].isdigit():
                return await _duel_rounds(update, context, match_id, int(p[3]))
            if p[1] == "dc":
                return await _duel_confirm(update, context, match_id)
            if p[1] == "roll":
                return await _duel_roll(update, context, match_id)
            if p[1] == "dx":
                return await _duel_cancel(update, context, match_id)
    await q.answer()


async def _solo_roll(update: Update, context, code: str, bet: int) -> None:
    q = update.callback_query
    uid = update.effective_user.id
    async with gsvc.lock_for(f"solo:{uid}"):
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            row, why = await gsvc.reserve_solo(s, user, chat_id_of(update), _thread_id(update), code, bet)
            cash, cd = int(user.cash or 0), gsvc.cooldown_left(user)
            await s.commit()
        if row is None:
            return await q.answer(_bet_error(why, "solo", cash, cd), show_alert=True)
        spec = gsvc.dice_spec(code) or {}
        await q.answer(f"{spec.get('emoji', '🎮')} {spec.get('action', 'حرکت بازی')} شروع شد...", show_alert=False)
        try:
            msg = await context.bot.send_dice(
                chat_id=chat_id_of(update), emoji=gsvc.dice_spec(code)["emoji"],
                message_thread_id=_thread_id(update),
            )
            value = int(msg.dice.value)
        except (TelegramError, AttributeError, TypeError, ValueError):
            async with session_scope() as s:
                await gsvc.refund_solo(s, row.id, "telegram_error")
                await s.commit()
            return await respond(update, f"❌ تلگرام حرکت بازی رو نفرستاد؛ شرط {money(bet)} کامل برگشت جیبت", kb.gamble_game_kb(code))
        await asyncio.sleep(config.GAMBLE_DICE_ANIMATION_SECONDS)
        async with session_scope() as s:
            res = await gsvc.settle_solo(s, row.id, value, getattr(msg, "message_id", None))
            await s.commit()
        if not res.get("ok"):
            return await respond(update, "❌ نتیجه ثبت نشد؛ جاب بازیابی شرطت رو سالم برمی‌گردونه")
        await respond(update, solo_result_text(res), kb.gamble_solo_result_kb(code, bet, uid))


async def _duel_accept(update, context, match_id: int) -> None:
    q = update.callback_query
    async with session_scope() as s:
        player, _ = await users.get_or_create(s, update.effective_user)
        row, why = await gsvc.accept_match(s, match_id, player)
        if row:
            view_row, v = await _match_view(s, match_id)
        else:
            view_row, v = None, {}
        await s.commit()
    if why:
        msg = {"self": "خودت نمی‌تونی حریف خودت شی 😄", "poor": "پولت به شرط این مسابقه نمی‌رسه",
               "busy": "یه مسابقه باز داری", "locked": f"لول {config.GAMBLE_MIN_LEVEL} می‌خواد",
               "expired": "وقت لابی تموم شده", "closed": "این لابی دیگه باز نیس"}.get(why, "نشد")
        return await q.answer(msg, show_alert=True)
    await q.answer("⚔️ چالش رو قبول کردی")
    await _edit_match(context, view_row, _config_emoji_text(view_row, v), kb.gamble_duel_emoji_kb(match_id))


async def _duel_emoji(update, context, match_id: int, code: str) -> None:
    q = update.callback_query
    async with session_scope() as s:
        actor, _ = await users.get_or_create(s, update.effective_user)
        row, why = await gsvc.set_match_emoji(s, match_id, actor, code)
        view_row, v = await _match_view(s, match_id) if row else (None, {})
        await s.commit()
    if why:
        return await q.answer("فقط سازنده می‌تونه تنظیم کنه" if why == "owner" else "این لابی بسته شده", show_alert=True)
    await q.answer()
    await _edit_match(context, view_row, _config_rounds_text(view_row, v), kb.gamble_duel_rounds_kb(match_id))


async def _duel_rounds(update, context, match_id: int, rounds: int) -> None:
    q = update.callback_query
    async with session_scope() as s:
        actor, _ = await users.get_or_create(s, update.effective_user)
        row, why = await gsvc.set_match_rounds(s, match_id, actor, rounds)
        view_row, v = await _match_view(s, match_id) if row else (None, {})
        await s.commit()
    if why:
        return await q.answer("فقط سازنده می‌تونه تنظیم کنه" if why == "owner" else "تنظیم نامعتبره", show_alert=True)
    await q.answer()
    await _edit_match(context, view_row, _confirm_text(view_row, v), kb.gamble_duel_confirm_kb(match_id))


async def _duel_confirm(update, context, match_id: int) -> None:
    q = update.callback_query
    async with session_scope() as s:
        actor, _ = await users.get_or_create(s, update.effective_user)
        row, why, started = await gsvc.confirm_match(s, match_id, actor)
        await s.flush()
        view_row, v = await _match_view(s, match_id) if row else (None, {})
        await s.commit()
    if why:
        msg = {"poor": "پولت به شرط نمی‌رسه", "stranger": "این مسابقه مال تو نیس",
               "already": "قبلاً تأیید کردی", "closed": "مرحله تأیید بسته شده"}.get(why, "نشد")
        return await q.answer(msg, show_alert=True)
    await q.answer("✅ سهمت رفت تو صندوق" if not started else "🔥 مسابقه شروع شد")
    if started:
        await _edit_match(context, view_row, _round_text(view_row, v), _duel_roll_kb(view_row))
    else:
        await _edit_match(context, view_row, _confirm_text(view_row, v), kb.gamble_duel_confirm_kb(match_id))


async def _duel_roll(update, context, match_id: int) -> None:
    q = update.callback_query
    async with session_scope() as s:
        actor, _ = await users.get_or_create(s, update.effective_user)
        row, _rnd, why = await gsvc.check_roll(s, match_id, actor)
        emoji = row.emoji if row else None
        chat_id = row.chat_id if row else None
        thread_id = row.thread_id if row else None
        await s.commit()
    code = gsvc.dice_code(emoji or "") or ""
    spec = gsvc.dice_spec(code) or {}
    action = spec.get("action", "حرکت بازی")
    if why:
        msg = {"already": f"{action} این راندت رو انجام دادی", "stranger": "این مسابقه مال تو نیس",
               "closed": "مسابقه بسته شده"}.get(why, "راند آماده نیس")
        return await q.answer(msg, show_alert=True)
    await q.answer(f"{emoji or '🎮'} {action} شروع شد...")
    try:
        msg = await context.bot.send_dice(chat_id=chat_id, emoji=emoji, message_thread_id=thread_id)
        value = int(msg.dice.value)
    except (TelegramError, AttributeError, TypeError, ValueError):
        return await respond(update, f"❌ تلگرام {action} رو نفرستاد؛ دوباره دکمه رو بزن")
    await asyncio.sleep(config.GAMBLE_DICE_ANIMATION_SECONDS)
    async with session_scope() as s:
        actor = await users.get_by_tg(s, update.effective_user.id)
        res = await gsvc.record_roll(s, match_id, actor, value, getattr(msg, "message_id", None)) if actor else {"ok": False}
        view_row, v = await _match_view(s, match_id)
        winner = await s.get(User, view_row.winner_id) if view_row and view_row.winner_id else None
        await s.commit()
    if not res.get("ok"):
        return
    if not res.get("resolved"):
        note = (f"{esc(users.display_name(actor))}: {_duel_result_label(code, value)}؛ "
                f"منتظر {action} حریفیم.")
        return await _edit_match(context, view_row, _round_text(view_row, v, note), _duel_roll_kb(view_row))
    if res.get("tie"):
        note = f"🤝 امتیاز رسمی هر دو {fa_num(res['creator_value'])} شد؛ همین راند دوباره تکرار میشه."
        return await _edit_match(context, view_row, _round_text(view_row, v, note), _duel_roll_kb(view_row))
    if res.get("finished"):
        wname = esc(users.display_name(winner)) if winner else "برنده"
        text = (
            f"<b>🏆 {wname} مسابقه {spec.get('name', '')} #{fa_num(match_id)} رو برد!</b>\n\n"
            f"🎮 امتیاز حرکت آخر: {fa_num(res['creator_value'])} - {fa_num(res['opponent_value'])}\n"
            f"🏁 نتیجه نهایی: {fa_num(view_row.creator_score)} - {fa_num(view_row.opponent_score)}\n"
            f"💰 جایزه صندوق: {money(res['payout'])}"
        )
        return await _edit_match(context, view_row, text, kb.gamble_finished_kb())
    note = f"✅ امتیاز رسمی راند: {fa_num(res['creator_value'])} - {fa_num(res['opponent_value'])}"
    await _edit_match(context, view_row, _round_text(view_row, v, note), _duel_roll_kb(view_row))


async def _duel_cancel(update, context, match_id: int) -> None:
    q = update.callback_query
    async with session_scope() as s:
        actor, _ = await users.get_or_create(s, update.effective_user)
        row, why, refunded = await gsvc.cancel_match(s, match_id, actor)
        await s.commit()
    if why:
        return await q.answer("بعد شروع مسابقه دیگه لغو نداریم" if why == "closed" else "این مسابقه مال تو نیس", show_alert=True)
    await q.answer("مسابقه لغو شد")
    await _edit_match(context, row, f"<b>❌ مسابقه #{fa_num(match_id)} لغو شد</b>\n\n💰 {money(refunded)} از صندوق پس داده شد", kb.gamble_finished_kb())
