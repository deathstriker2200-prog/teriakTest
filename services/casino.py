"""
قمارخانه «تریاکی» راند ۱۹: پنج بازی با درصدهایی که رو کاغذ همیشه ضررن (درخواست کارفرما)

🎲 شرط ساده: ۴۰% برد و ۱٫۸ برابر | EV 0.72
🎲 تاس دوبل: ۴۸% برد و ۲ برابر | EV 0.96
🎡 گردونه شانس: نواحی وزن‌دار ۰ تا ۵ برابر | EV حدود 0.84
🃏 کارت بالا/پایین: هر حدس درست ضریب = کسری از ضریب منصفانه واقعی | EV هر پله 0.85
💣 مین: هر لول شانس بمب و ضریب کش‌اوت از کانفیگ | EV هر لول زیر ۱ و هرچی جلوتر بدتر

حالت بازی‌های چندمرحله‌ای (کارت و مین) تو حافظه نگه‌داشته میشه، با TTL می‌سوزه
کولدان سر شروع بازی اعمال میشه، نه تهش | تمام عددها تو config.py
"""

import random

from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import User
from services import world as world_svc
from services import actionlog, tracklog
from utils import now_utc

# حالت بازی جاری هر کاربر: {"game": str, "bet": int, "started": datetime, ...}
_GAMES: dict[int, dict] = {}

GAMES = {
    "simple": {"name": "🎲 شرط ساده", "desc": f"40% برد | برد = {config.CASINO_WIN_MULT} برابر شرط"},
    "dice":   {"name": "🎲 تاس دوبل", "desc": "48% برد | برد = ۲ برابر شرط، وگرنه صفر"},
    "wheel":  {"name": "🎡 گردونه شانس", "desc": "چرخ با نواحی ۰ تا ۵ برابر، هرچی بیشتر کمیاب‌تر"},
    "card":   {"name": "🃏 کارت بالا/پایین", "desc": "حدس بزن کارت بعدی بزرگتره یا کوچیک‌تر، هر حدس درست ضریب میره بالا، هر لحظه می‌تونی کش‌اوت کنی"},
    "mines":  {"name": "💣 مین", "desc": "هر لول سه خونه داره، یکیش بمبه؛ هرچی جلوتر ضریب و ریسک بیشتر، هر لحظه می‌تونی کش‌اوت کنی"},
}

CARD_NAMES = {11: "J", 12: "Q", 13: "K", 14: "A"}


def card_name(v: int) -> str:
    return CARD_NAMES.get(v, str(v))


def _purge_stale(uid: int) -> dict | None:
    """حالت کاربر رو برمی‌داره، اگه کهنه شده بود حذفش می‌کنه"""
    g = _GAMES.get(uid)
    if g and (now_utc() - g["started"]).total_seconds() > config.CASINO_STATE_TTL:
        _GAMES.pop(uid, None)
        return None
    return g


def state_of(uid: int) -> dict | None:
    return _purge_stale(uid)


def _begin(user: User, game: str, bet: int) -> str:
    """چک‌های مشترک شروع، پیام خطا یا رشته خالی"""
    if user.level < config.CASINO_MIN_LEVEL:
        return "locked"
    if world_svc.casino_cooldown_left(user):
        return "cooldown"
    if bet not in config.CASINO_BETS:
        return "bad_bet"
    if _purge_stale(user.id) is not None:
        return "busy"
    if user.cash < bet:
        return "poor"
    return ""


async def start(session: AsyncSession, user: User, game: str, bet: int) -> dict:
    """شروع بازی: شرط همون اول کم میشه و کولدان می‌خوره؛ بازی‌های یه‌مرحله‌ای همینجا تموم میشن"""
    if game not in GAMES:
        return {"status": "bad_game"}
    bad = _begin(user, game, bet)
    if bad:
        return {"status": bad}

    user.cash -= bet
    user.last_casino_at = now_utc()
    await actionlog.log(session, "casino")  # آمار دست‌های قمارخانه پنل ادمین

    if game == "simple":
        if random.random() < config.CASINO_WIN_CHANCE:
            return await _settle(session, user, bet, config.CASINO_WIN_MULT, game)
        return await _bust(session, user, bet, game)

    if game == "dice":
        roll = random.randint(1, 6)
        if random.random() < config.CASINO_DICE_CHANCE:
            return await _settle(session, user, bet, float(config.CASINO_DICE_MULT), game, roll=roll)
        return await _bust(session, user, bet, game, roll=roll)

    if game == "wheel":
        mults, weights = zip(*config.CASINO_WHEEL)
        mult = random.choices(mults, weights=weights, k=1)[0]
        if mult > 0:
            return await _settle(session, user, bet, mult, game, seg=mult)
        return await _bust(session, user, bet, game, seg=0.0)

    # بازی‌های چندمرحله‌ای: حالت ذخیره میشه و رندر اول برمی‌گرده
    if game == "card":
        _GAMES[user.id] = {"game": "card", "bet": bet, "mult": 1.0, "card": random.randint(2, 14),
                           "steps": 0, "started": now_utc()}
        return {"status": "started", **{k: v for k, v in _GAMES[user.id].items() if k != "started"}}

    # mines: خونه بمب هر لول موقع رسیدن به اون لول کشیده میشه
    _GAMES[user.id] = {"game": "mines", "bet": bet, "level": 0, "started": now_utc()}
    return {"status": "started", "game": "mines", "bet": bet, "level": 0}


async def _settle(session: AsyncSession, user: User, bet: int, mult: float, game: str, **kw) -> dict:
    """برداشت با برد: جایزه واریز میشه و لاگ خالص برد"""
    prize = int(round(bet * mult))
    user.cash += prize
    await tracklog.bump_casino(session, user.id, True, prize - bet)  # لاگ ردیابی ادمین، خالص برد
    return {"status": "win", "game": game, "bet": bet, "mult": mult, "prize": prize, "cash": user.cash, **kw}


async def _bust(session: AsyncSession, user: User, bet: int, game: str, **kw) -> dict:
    await tracklog.bump_casino(session, user.id, False, -bet)  # لاگ ردیابی ادمین، شرط باخته‌شده
    return {"status": "lose", "game": game, "bet": bet, "prize": 0, "cash": user.cash, **kw}


# ───────── 🃏 کارت بالا/پایین ─────────

def card_step_mult(card: int, guess: str) -> float:
    """ضریب پله بعدی: کسری از ضریب منصفانه واقعی، با سقف | تساوی هم باخته"""
    if guess == "hi":
        p = (14 - card) / 12
    else:
        p = (card - 2) / 12
    if p <= 0:
        return 0.0
    return round(min(config.CASINO_CARD_STEP_CAP, config.CASINO_CARD_MARGIN / p), 2)


async def card_step(session: AsyncSession, user: User, guess: str) -> dict:
    g = _purge_stale(user.id)
    if not g or g["game"] != "card":
        return {"status": "no_game"}
    if guess not in ("hi", "lo"):
        return {"status": "bad_guess"}
    cur = g["card"]
    nxt = random.randint(2, 14)
    won = nxt > cur if guess == "hi" else nxt < cur
    g["card"] = nxt
    if not won:
        _GAMES.pop(user.id, None)
        res = await _bust(session, user, g["bet"], "card", cur=cur, nxt=nxt, guess=guess)
        return res
    g["steps"] += 1
    g["mult"] = round(g["mult"] * card_step_mult(cur, guess), 2)
    g["history"] = [*g.get("history", []), (cur, nxt, guess)]
    if g["steps"] >= config.CASINO_CARD_MAX_STEPS:
        return await cash_out(session, user, auto=True)
    return {"status": "next", "game": "card", "bet": g["bet"], "mult": g["mult"],
            "card": nxt, "steps": g["steps"],
            "hi_mult": round(g["mult"] * card_step_mult(nxt, "hi"), 2) if card_step_mult(nxt, "hi") else 0,
            "lo_mult": round(g["mult"] * card_step_mult(nxt, "lo"), 2) if card_step_mult(nxt, "lo") else 0}


# ───────── 💣 مین ─────────

def mines_cashout_mult(level: int) -> float:
    """ضریب کش‌اوت بعد از لول level (۰ یعنی هنوز نرفتی جلو و شرط دستته)"""
    if level <= 0:
        return 0.0
    return config.CASINO_MINES_LEVELS[level - 1][1]


async def mines_step(session: AsyncSession, user: User) -> dict:
    g = _purge_stale(user.id)
    if not g or g["game"] != "mines":
        return {"status": "no_game"}
    nxt_level = g["level"] + 1
    if nxt_level > len(config.CASINO_MINES_LEVELS):
        return await cash_out(session, user, auto=True)
    bomb_chance, _mult = config.CASINO_MINES_LEVELS[nxt_level - 1]
    if random.random() < bomb_chance:
        _GAMES.pop(user.id, None)
        return await _bust(session, user, g["bet"], "mines", level=nxt_level)
    g["level"] = nxt_level
    mult = mines_cashout_mult(nxt_level)
    done = nxt_level >= len(config.CASINO_MINES_LEVELS)
    if done:
        return await cash_out(session, user, auto=True)
    return {"status": "safe", "game": "mines", "bet": g["bet"], "level": nxt_level, "mult": mult}


# ───────── 💰 کش‌اوت ─────────

async def cash_out(session: AsyncSession, user: User, auto: bool = False) -> dict:
    g = _purge_stale(user.id)
    if not g:
        return {"status": "no_game"}
    _GAMES.pop(user.id, None)
    if g["game"] == "card":
        return await _settle(session, user, g["bet"], g["mult"], "card", auto=auto)
    mult = mines_cashout_mult(g["level"]) if g["level"] > 0 else 1.0  # هنوز جلو نرفتی، شرط برمی‌گرده
    return await _settle(session, user, g["bet"], mult, "mines", level=g["level"], auto=auto)
