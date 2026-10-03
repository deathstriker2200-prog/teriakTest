# -*- coding: utf-8 -*-
"""قمار تاسی رسمی تلگرام: تک‌نفره + لابی دونفره با escrow و تسویه ماندگار."""
from __future__ import annotations

import asyncio
import random
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import GambleMatch, GambleSoloRound, GambleTicTacToeMove, User
from services import actionlog, tracklog
from utils import now_utc

_ACTIVE_MATCH_STATES = ("waiting_opponent", "configuring", "confirming", "active")
_LOCKS: dict[str, asyncio.Lock] = {}


def lock_for(key: str | int) -> asyncio.Lock:
    """قفل درون‌پردازه برای جلوگیری از دوبارکلیک همزمان؛ وضعیت DB خط دفاع دوم است."""
    k = str(key)
    lock = _LOCKS.get(k)
    if lock is None:
        lock = _LOCKS[k] = asyncio.Lock()
    if len(_LOCKS) > 4000:
        for old in list(_LOCKS)[:2000]:
            if not _LOCKS[old].locked():
                _LOCKS.pop(old, None)
    return lock


def dice_spec(code: str) -> dict | None:
    return config.GAMBLE_DICE.get(code)


def dice_code(emoji: str) -> str | None:
    return config.GAMBLE_EMOJI_TO_KEY.get(emoji)


def valid_bet(user: User, bet: int, mode: str) -> tuple[bool, str]:
    if (user.level or 1) < config.GAMBLE_MIN_LEVEL:
        return False, "locked"
    lo = config.GAMBLE_SOLO_MIN_BET if mode == "solo" else config.GAMBLE_DUEL_MIN_BET
    hi = config.GAMBLE_SOLO_MAX_BET if mode == "solo" else config.GAMBLE_DUEL_MAX_BET
    if not isinstance(bet, int) or bet < lo:
        return False, "low"
    if bet > hi:
        return False, "high"
    if int(user.cash or 0) < bet:
        return False, "poor"
    return True, ""


def cooldown_left(user: User) -> int:
    if not user.last_casino_at:
        return 0
    left = config.GAMBLE_COOLDOWN_SECONDS - int((now_utc() - user.last_casino_at).total_seconds())
    return max(0, left)


def slot_symbols(value: int) -> tuple[str, str, str]:
    """ترکیب تصویری اسلات تلگرام از مقدار رسمی ۱ تا ۶۴."""
    if value < 1 or value > 64:
        raise ValueError("invalid Telegram slot value")
    symbols = ("BAR", "🍇", "🍋", "7️⃣")
    raw = value - 1
    return symbols[raw % 4], symbols[(raw // 4) % 4], symbols[(raw // 16) % 4]


def solo_multiplier(code: str, value: int) -> float:
    spec = dice_spec(code)
    if not spec or value < 1 or value > int(spec["max"]):
        raise ValueError("invalid Telegram dice value")
    payouts = spec.get("payouts")
    if payouts is not None:
        return float(payouts.get(value, 0.0))
    return float(spec.get("payout", 0.0)) if value in spec.get("wins", ()) else 0.0


def solo_outcome(code: str, bet: int, value: int) -> tuple[bool, int]:
    multiplier = solo_multiplier(code, value)
    payout = int(round(bet * multiplier)) if multiplier else 0
    return multiplier > 0, payout


def outcome_text(code: str, value: int) -> str:
    """توضیح نتیجه بر اساس اتفاق واقعی انیمیشن، نه نمایش شانس عددی."""
    if code == "dice":
        return f"تاس روی {value} نشست"
    if code == "dart":
        if value == 6:
            return "دارت خورد وسط خال!"
        if value == 1:
            return "دارت به صفحه هم نخورد"
        return "دارت به صفحه خورد، ولی وسط خال نبود"
    if code == "bowl":
        if value == 6:
            return "استرایک! همه پین‌ها ریخت"
        if value == 1:
            return "توپ همه پین‌ها رو رد کرد"
        return "چندتا پین افتاد، ولی استرایک نشد"
    if code == "basket":
        return "توپ رفت تو سبد!" if value in (4, 5) else "پرتاب وارد سبد نشد"
    if code == "foot":
        return "شوت گل شد!" if value in (4, 5) else "شوت گل نشد"
    if code == "slot":
        symbols = slot_symbols(value)
        combo = " | ".join(symbols)
        mult = solo_multiplier(code, value)
        if value == 64:
            return f"{combo} — جک‌پات 777!"
        if len(set(symbols)) == 1:
            return f"{combo} — سه نماد یکسان، ضریب ×{mult:g}!"
        if symbols.count("7️⃣") == 2:
            return f"{combo} — دقیقاً دو تا 7، ضریب ×{mult:g}!"
        if symbols[0] == symbols[1] and symbols[0] != "7️⃣":
            return f"{combo} — دو نماد اول یکیه، ضریب ×{mult:g}!"
        return f"{combo} — ترکیب برنده نشد"
    raise ValueError("unsupported dice code")


async def _active_solo(session: AsyncSession, user_id: int) -> GambleSoloRound | None:
    q = select(GambleSoloRound).where(
        GambleSoloRound.user_id == user_id,
        GambleSoloRound.status.in_(("reserved", "rolled")),
    ).order_by(GambleSoloRound.id.desc()).limit(1)
    return (await session.execute(q)).scalar_one_or_none()


async def reserve_solo(
    session: AsyncSession, user: User, chat_id: int, thread_id: int | None,
    code: str, bet: int,
) -> tuple[GambleSoloRound | None, str]:
    spec = dice_spec(code)
    if not spec:
        return None, "bad_dice"
    ok, why = valid_bet(user, bet, "solo")
    if not ok:
        return None, why
    if cooldown_left(user):
        return None, "cooldown"
    if await _active_solo(session, user.id):
        return None, "busy"
    user.cash -= bet
    user.last_casino_at = now_utc()
    row = GambleSoloRound(
        user_id=user.id, chat_id=chat_id, thread_id=thread_id, emoji=spec["emoji"],
        bet=bet, status="reserved",
        expires_at=now_utc() + timedelta(seconds=config.GAMBLE_SOLO_RESERVE_SECONDS),
    )
    session.add(row)
    await session.flush()
    await actionlog.log(session, "casino")
    return row, ""


async def settle_solo(
    session: AsyncSession, round_id: int, value: int, dice_message_id: int | None,
) -> dict:
    row = await session.get(GambleSoloRound, round_id, with_for_update=True)
    if row is None:
        return {"ok": False, "reason": "missing"}
    if row.status == "settled":
        user = await session.get(User, row.user_id)
        code = dice_code(row.emoji)
        return {"ok": True, "duplicate": True, "won": row.payout > 0, "payout": row.payout,
                "bet": row.bet, "cash": user.cash if user else 0, "value": row.dice_value,
                "emoji": row.emoji, "code": code,
                "outcome": outcome_text(code, row.dice_value) if code and row.dice_value else ""}
    if row.status not in ("reserved", "rolled"):
        return {"ok": False, "reason": row.status}
    code = dice_code(row.emoji)
    if code is None:
        raise ValueError("unsupported stored dice emoji")
    multiplier = solo_multiplier(code, value)
    won, payout = solo_outcome(code, row.bet, value)
    user = await session.get(User, row.user_id, with_for_update=True)
    if user is None:
        row.status = "failed"
        return {"ok": False, "reason": "missing_user"}
    if payout:
        user.cash = int(user.cash or 0) + payout
    row.status = "settled"
    row.dice_value = value
    row.dice_message_id = dice_message_id
    row.payout = payout
    row.settled_at = now_utc()
    net = payout - row.bet
    await tracklog.bump_casino(session, user.id, won, net)
    return {"ok": True, "won": won, "payout": payout, "bet": row.bet,
            "net": net, "cash": user.cash, "value": value, "emoji": row.emoji,
            "code": code, "multiplier": multiplier, "outcome": outcome_text(code, value)}


async def refund_solo(session: AsyncSession, round_id: int, reason: str = "failed") -> dict:
    row = await session.get(GambleSoloRound, round_id, with_for_update=True)
    if row is None or row.status not in ("reserved", "rolled"):
        return {"ok": False, "reason": "closed"}
    user = await session.get(User, row.user_id, with_for_update=True)
    if user:
        user.cash = int(user.cash or 0) + row.bet
    row.status = "refunded"
    row.settled_at = now_utc()
    return {"ok": True, "bet": row.bet, "cash": user.cash if user else 0, "why": reason,
            "chat_id": row.chat_id}


async def _active_match_for(session: AsyncSession, user_id: int) -> GambleMatch | None:
    q = select(GambleMatch).where(
        GambleMatch.status.in_(_ACTIVE_MATCH_STATES),
        or_(GambleMatch.creator_id == user_id, GambleMatch.opponent_id == user_id),
    ).order_by(GambleMatch.id.desc()).limit(1)
    return (await session.execute(q)).scalar_one_or_none()


async def create_match(
    session: AsyncSession, creator: User, chat_id: int, thread_id: int | None, bet: int,
) -> tuple[GambleMatch | None, str]:
    """لابی عمومی دوز می‌سازد؛ پول تا تأیید نهایی کم نمی‌شود."""
    ok, why = valid_bet(creator, bet, "duel")
    if not ok:
        return None, why
    if await _active_match_for(session, creator.id):
        return None, "busy"
    now = now_utc()
    row = GambleMatch(
        chat_id=chat_id,
        thread_id=thread_id,
        creator_id=creator.id,
        bet_per_player=bet,
        game_kind="ttt3",
        board_state=".........",
        creator_moves="",
        opponent_moves="",
        status="waiting_opponent",
        expires_at=now + timedelta(seconds=config.GAMBLE_LOBBY_SECONDS),
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row, ""


async def bind_lobby_message(session: AsyncSession, match_id: int, message_id: int | None) -> None:
    row = await session.get(GambleMatch, match_id, with_for_update=True)
    if row and message_id:
        row.lobby_message_id = int(message_id)
        row.updated_at = now_utc()


async def accept_match(session: AsyncSession, match_id: int, player: User) -> tuple[GambleMatch | None, str]:
    row = await session.get(GambleMatch, match_id, with_for_update=True)
    if row is None or row.status != "waiting_opponent" or row.game_kind != "ttt3":
        return row, "closed"
    if row.expires_at < now_utc():
        row.status = "expired"
        return row, "expired"
    if row.creator_id == player.id:
        return row, "self"
    if (player.level or 1) < config.GAMBLE_MIN_LEVEL:
        return row, "locked"
    if int(player.cash or 0) < row.bet_per_player:
        return row, "poor"
    if await _active_match_for(session, player.id):
        return row, "busy"
    row.opponent_id = player.id
    row.status = "configuring"
    row.updated_at = now_utc()
    row.expires_at = now_utc() + timedelta(seconds=config.GAMBLE_CONFIG_SECONDS)
    return row, ""


async def set_match_rounds(
    session: AsyncSession, match_id: int, actor: User, rounds: int,
) -> tuple[GambleMatch | None, str]:
    """مدل سری دوز را سازنده انتخاب می‌کند: 1، 3 یا 5 دست."""
    row = await session.get(GambleMatch, match_id, with_for_update=True)
    if row is None or row.status != "configuring" or row.game_kind != "ttt3":
        return row, "closed"
    if row.creator_id != actor.id:
        return row, "owner"
    if rounds not in config.GAMBLE_DUEL_ROUNDS:
        return row, "bad_config"
    row.rounds_total = rounds
    row.status = "confirming"
    row.updated_at = now_utc()
    row.expires_at = now_utc() + timedelta(seconds=config.GAMBLE_CONFIRM_SECONDS)
    return row, ""


def role_of(row: GambleMatch, user_id: int) -> str | None:
    if row.creator_id == user_id:
        return "creator"
    if row.opponent_id == user_id:
        return "opponent"
    return None


def symbol_of(row: GambleMatch, user_id: int) -> str | None:
    role = role_of(row, user_id)
    return "X" if role == "creator" else "O" if role == "opponent" else None


def decode_moves(value: str | None) -> list[int]:
    if not value:
        return []
    out: list[int] = []
    for part in value.split(","):
        if part.isdigit() and 0 <= int(part) <= 8:
            out.append(int(part))
    return out[-config.GAMBLE_TTT_MAX_ACTIVE_PIECES:]


def encode_moves(moves: list[int]) -> str:
    return ",".join(str(v) for v in moves[-config.GAMBLE_TTT_MAX_ACTIVE_PIECES:])


def board_cells(row: GambleMatch) -> list[str]:
    raw = row.board_state or "........."
    if len(raw) != 9 or any(ch not in ".XO" for ch in raw):
        return list(".........")
    return list(raw)


def has_ttt_win(board: list[str], symbol: str) -> bool:
    wins = (
        (0, 1, 2), (3, 4, 5), (6, 7, 8),
        (0, 3, 6), (1, 4, 7), (2, 5, 8),
        (0, 4, 8), (2, 4, 6),
    )
    return any(all(board[i] == symbol for i in line) for line in wins)


def _other_id(row: GambleMatch, user_id: int) -> int:
    return int(row.opponent_id) if user_id == row.creator_id else row.creator_id


def _reset_round(row: GambleMatch, starter_id: int, *, advance: bool = True) -> None:
    if advance:
        row.current_round = int(row.current_round or 1) + 1
    row.board_state = "........."
    row.creator_moves = ""
    row.opponent_moves = ""
    row.moves_in_round = 0
    row.round_starter_id = starter_id
    row.turn_user_id = starter_id
    row.updated_at = now_utc()
    row.expires_at = now_utc() + timedelta(seconds=config.GAMBLE_ROUND_SECONDS)


async def confirm_match(
    session: AsyncSession, match_id: int, actor: User,
) -> tuple[GambleMatch | None, str, bool]:
    """سهم هر نفر هنگام تأیید امانت می‌شود؛ با تأیید دوم برد دوز ساخته می‌شود."""
    row = await session.get(GambleMatch, match_id, with_for_update=True)
    if (
        row is None or row.status != "confirming" or row.opponent_id is None
        or row.game_kind != "ttt3" or row.rounds_total not in config.GAMBLE_DUEL_ROUNDS
    ):
        return row, "closed", False
    role = role_of(row, actor.id)
    if not role:
        return row, "stranger", False
    if getattr(row, f"{role}_confirmed"):
        return row, "already", False
    if int(actor.cash or 0) < row.bet_per_player:
        return row, "poor", False
    actor.cash -= row.bet_per_player
    setattr(row, f"{role}_confirmed", True)
    setattr(row, f"{role}_escrow", row.bet_per_player)
    row.updated_at = now_utc()
    started = bool(row.creator_confirmed and row.opponent_confirmed)
    if started:
        row.status = "active"
        row.current_round = 1
        starter = random.choice((row.creator_id, int(row.opponent_id)))
        _reset_round(row, starter, advance=False)
        creator = await session.get(User, row.creator_id)
        opponent = await session.get(User, row.opponent_id)
        if creator:
            creator.last_casino_at = now_utc()
        if opponent:
            opponent.last_casino_at = now_utc()
        await actionlog.log(session, "casino")
    else:
        row.expires_at = now_utc() + timedelta(seconds=config.GAMBLE_CONFIRM_SECONDS)
    return row, "", started


async def _finish_match(session: AsyncSession, row: GambleMatch, winner_id: int) -> int:
    if row.payout_done:
        return 0
    pot = int(row.creator_escrow or 0) + int(row.opponent_escrow or 0)
    winner = await session.get(User, winner_id, with_for_update=True)
    if winner and pot:
        winner.cash = int(winner.cash or 0) + pot
    row.creator_escrow = row.opponent_escrow = 0
    row.winner_id = winner_id
    row.payout_done = True
    row.status = "finished"
    row.turn_user_id = None
    row.updated_at = now_utc()
    row.expires_at = now_utc()
    if winner:
        await tracklog.bump_casino(session, winner.id, True, row.bet_per_player)
    return pot


async def play_ttt(session: AsyncSession, match_id: int, actor: User, cell: int) -> dict:
    """یک حرکت قانونی دوز؛ حذف قدیمی‌ترین مهره و تسویه سری داخل همان تراکنش."""
    row = await session.get(GambleMatch, match_id, with_for_update=True)
    if row is None or row.status != "active" or row.game_kind != "ttt3":
        return {"ok": False, "reason": "closed", "match": row}
    role = role_of(row, actor.id)
    if role is None:
        return {"ok": False, "reason": "stranger", "match": row}
    if row.turn_user_id != actor.id:
        return {"ok": False, "reason": "turn", "match": row}
    if not isinstance(cell, int) or not 0 <= cell <= 8:
        return {"ok": False, "reason": "cell", "match": row}
    board = board_cells(row)
    if board[cell] != ".":
        return {"ok": False, "reason": "occupied", "match": row}

    symbol = "X" if role == "creator" else "O"
    attr = f"{role}_moves"
    moves = decode_moves(getattr(row, attr))
    removed: int | None = None
    if len(moves) >= config.GAMBLE_TTT_MAX_ACTIVE_PIECES:
        removed = moves.pop(0)
        if board[removed] == symbol:
            board[removed] = "."
    board[cell] = symbol
    moves.append(cell)
    setattr(row, attr, encode_moves(moves))
    row.board_state = "".join(board)
    row.moves_in_round = int(row.moves_in_round or 0) + 1
    row.updated_at = now_utc()

    session.add(GambleTicTacToeMove(
        match_id=row.id,
        round_no=row.current_round,
        move_no=row.moves_in_round,
        player_id=actor.id,
        cell=cell,
        removed_cell=removed,
    ))

    if has_ttt_win(board, symbol):
        if role == "creator":
            row.creator_score = int(row.creator_score or 0) + 1
        else:
            row.opponent_score = int(row.opponent_score or 0) + 1
        needed = int(row.rounds_total or 1) // 2 + 1
        if row.creator_score >= needed or row.opponent_score >= needed:
            payout = await _finish_match(session, row, actor.id)
            return {
                "ok": True, "round_won": True, "finished": True, "winner_id": actor.id,
                "payout": payout, "removed": removed, "match": row,
            }
        next_starter = _other_id(row, int(row.round_starter_id or actor.id))
        _reset_round(row, next_starter)
        return {
            "ok": True, "round_won": True, "finished": False, "winner_id": actor.id,
            "removed": removed, "match": row,
        }

    if row.moves_in_round >= config.GAMBLE_TTT_MAX_MOVES_PER_ROUND:
        next_starter = _other_id(row, int(row.round_starter_id or actor.id))
        _reset_round(row, next_starter)
        return {"ok": True, "draw": True, "removed": removed, "match": row}

    row.turn_user_id = _other_id(row, actor.id)
    row.expires_at = now_utc() + timedelta(seconds=config.GAMBLE_ROUND_SECONDS)
    return {"ok": True, "removed": removed, "match": row}


async def _refund_match(session: AsyncSession, row: GambleMatch, status: str) -> int:
    refunded = 0
    if row.creator_escrow:
        user = await session.get(User, row.creator_id, with_for_update=True)
        if user:
            user.cash = int(user.cash or 0) + int(row.creator_escrow)
            refunded += int(row.creator_escrow)
        row.creator_escrow = 0
    if row.opponent_escrow and row.opponent_id:
        user = await session.get(User, row.opponent_id, with_for_update=True)
        if user:
            user.cash = int(user.cash or 0) + int(row.opponent_escrow)
            refunded += int(row.opponent_escrow)
        row.opponent_escrow = 0
    row.status = status
    row.turn_user_id = None
    row.updated_at = now_utc()
    row.expires_at = now_utc()
    return refunded


async def cancel_match(
    session: AsyncSession, match_id: int, actor: User,
) -> tuple[GambleMatch | None, str, int]:
    row = await session.get(GambleMatch, match_id, with_for_update=True)
    if row is None or row.status not in ("waiting_opponent", "configuring", "confirming"):
        return row, "closed", 0
    if actor.id not in (row.creator_id, row.opponent_id):
        return row, "stranger", 0
    refunded = await _refund_match(session, row, "cancelled")
    return row, "", refunded


async def retire_legacy_active_matches(session: AsyncSession) -> tuple[int, int]:
    """بازی‌های دونفره تاسی باز نسخه قبل را یک‌بار با استرداد کامل می‌بندد."""
    # این تابع فقط پشت marker یک‌باره /update اجرا می‌شود؛ در لحظه ارتقا هر match باز، legacy است.
    # این کار waiting_opponentهای قدیمی را هم می‌گیرد که هنوز emoji انتخاب نکرده بودند.
    q = select(GambleMatch).where(
        GambleMatch.status.in_(_ACTIVE_MATCH_STATES),
    ).with_for_update()
    count = total = 0
    for row in (await session.execute(q)).scalars():
        total += await _refund_match(session, row, "retired_refunded")
        count += 1
    return count, total


async def sweep_expired(session: AsyncSession) -> list[dict]:
    """رزرو نیمه‌کاره و دوز بی‌حرکت را با استرداد کامل و idempotent می‌بندد."""
    now = now_utc()
    events: list[dict] = []
    qsolo = select(GambleSoloRound).where(
        GambleSoloRound.status.in_(("reserved", "rolled")),
        GambleSoloRound.expires_at <= now,
    ).with_for_update()
    for solo in (await session.execute(qsolo)).scalars():
        user = await session.get(User, solo.user_id, with_for_update=True)
        if user:
            user.cash = int(user.cash or 0) + solo.bet
        solo.status = "refunded"
        solo.settled_at = now
        events.append({"kind": "solo_refund", "chat_id": solo.chat_id, "bet": solo.bet})

    qmatch = select(GambleMatch).where(
        GambleMatch.status.in_(_ACTIVE_MATCH_STATES),
        GambleMatch.expires_at <= now,
    ).with_for_update()
    for row in (await session.execute(qmatch)).scalars():
        amount = await _refund_match(session, row, "expired")
        events.append({
            "kind": "match_refund",
            "chat_id": row.chat_id,
            "message_id": row.lobby_message_id,
            "match_id": row.id,
            "amount": amount,
        })
    return events
