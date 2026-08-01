"""
منطق بانک شخصی 🏦
پولی که تو بانکه موقع حمله دزدیده نمیشه، ظرفیت بانک با لولش زیاد میشه
و هر لول بانک حداقل لول بازیکن خودشو می‌خواد
"""

import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import User
from services import users as users_svc
from utils import fa_num, money, now_utc


# ───────── فرمول‌ها ─────────

def bank_capacity(level: int) -> int:
    """ظرفیت بانک بر اساس لولش، جدول ثابت"""
    lv = min(max(level, 1), config.BANK_MAX_LEVEL)
    return config.BANK_CAPS[lv - 1]


def bank_upgrade_price(level: int) -> int:
    """هزینه ارتقا از لول فعلی به لول بعد، جدول رند قیمت"""
    lv = min(max(level, 1), config.BANK_MAX_LEVEL)
    return config.BANK_UPGRADE_PRICES[lv - 1]


def bank_min_level(level: int) -> int:
    """حداقل لول بازیکن برای داشتن این لول بانک"""
    lv = min(max(level, 1), config.BANK_MAX_LEVEL)
    return config.BANK_MIN_LEVELS[lv - 1]


# ───────── عملیات ─────────

async def deposit(session: AsyncSession, user: User, amount: int) -> tuple[bool, str]:
    """واریز از جیب به بانک، تا سقف ظرفیت"""
    if amount <= 0:
        return False, "❌ مبلغو درست بگو، مثلا «تریاکی واریز 1200»"
    if user.cash < amount:
        return False, f"❌ این همه پول نقد نداری، جیبت {money(user.cash)} داری"
    cap = bank_capacity(user.bank_level)
    if user.bank_balance + amount > cap:
        room = max(0, cap - user.bank_balance)
        if room <= 0:
            return False, "🏦 بانکت پره دیگه، اول ارتقاش بده «تریاکی بانک»"
        return False, f"🏦 ظرفیت بانکت تا {money(cap)} ـه، فقط {money(room)} جا داره"
    user.cash -= amount
    user.bank_balance += amount
    return True, f"🏦 {money(amount)} رفت تو بانک و جاش امنه، دور از هر دزدی 🛡"


async def withdraw(session: AsyncSession, user: User, amount: int) -> tuple[bool, str]:
    """برداشت از بانک به جیب"""
    if amount <= 0:
        return False, "❌ مبلغو درست بگو، مثلا «تریاکی برداشت 1200»"
    if user.bank_balance < amount:
        return False, f"❌ تو بانک این همه نداری، موجودیت {money(user.bank_balance)} ـه"
    user.bank_balance -= amount
    user.cash += amount
    return True, f"💸 {money(amount)} اومد تو جیبت"


async def upgrade_bank(session: AsyncSession, user: User) -> tuple[bool, str]:
    """ارتقای لول بانک، هر لول یه حداقل سطح بازیکن می‌خواد"""
    if user.bank_level >= config.BANK_MAX_LEVEL:
        return False, "⭐ بانکت مکس لوله"
    next_level = user.bank_level + 1
    req = bank_min_level(next_level)
    if user.level < req:
        return False, f"🔒 برای بانک لول {fa_num(next_level)} خودت باید لول {fa_num(req)} باشی"
    price = bank_upgrade_price(user.bank_level)
    if user.cash < price:
        return False, f"❌ ارتقا {money(price)} هزینه داره و پولت کمه"
    user.cash -= price
    user.bank_level = next_level
    return True, (
        f"⬆️ بانکت رفت رو لول {fa_num(next_level)}\n"
        f"🏦 ظرفیت جدید {money(bank_capacity(next_level))}"
    )

# ───────── شماره حساب و انتقال بانک به بانک 💳 ─────────

_ACC_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # بدون I O 0 1، خواناتر برای خواندن به هم


def _acc_candidate(telegram_id: int, attempt: int) -> str:
    """کد قطعی از تلگرام‌آی‌دی، همیشه یکی برای یک نفر (سید + تکرار)"""
    rng = random.Random((telegram_id * 2654435761 + attempt * 97) & 0xFFFFFFFF)
    return "".join(rng.choice(_ACC_ALPHABET) for _ in range(config.BANK_ACC_LENGTH))


async def ensure_bank_acc(session: AsyncSession, user: User) -> str:
    """شماره حساب کاربر رو بده، اگه نداره بساز (یکتا، ریترای در صورت برخورد)"""
    if user.bank_acc:
        return user.bank_acc
    for attempt in range(30):
        cand = _acc_candidate(user.telegram_id, attempt)
        q = select(User.id).where(User.bank_acc == cand, User.id != user.id)
        if (await session.execute(q)).scalar_one_or_none() is None:
            user.bank_acc = cand
            return cand
    return ""  # عملا غیرممکنه


async def get_by_bank_acc(session: AsyncSession, code: str) -> User | None:
    """پیدا کردن صاحب حساب با شماره حساب، ورودی نرمال میشه (بزرگ/سفید جداشده)"""
    norm = code.strip().upper().replace(" ", "").replace("‌", "")
    q = select(User).where(User.bank_acc == norm)
    return (await session.execute(q)).scalar_one_or_none()


def trf_cooldown_left(user: User) -> int:
    """ثانیه‌های باقی کولدان انتقال، صفر یعنی آزاده"""
    if user.last_trf_at is None:
        return 0
    left = config.TRF_COOLDOWN_SECONDS - int((now_utc() - user.last_trf_at).total_seconds())
    return max(0, left)


async def transfer_to(session: AsyncSession, sender: User, recipient: User, amount: int) -> tuple[bool, str]:
    """انتقال پول بانکی فرستنده به بانک گیرنده، با چک موجودی و ظرفیت مقصد (تو خطاها اسم گیرنده میاد)"""
    if recipient.id == sender.id:
        return False, "😅 به حساب خودت لازم نیس انتقال بدی، برداشت و واریز معمولی بزن"
    if amount <= 0:
        return False, "❌ مبلغو درست بگو، مثلا: 1200"
    if amount < config.TRF_MIN_AMOUNT:
        return False, f"❌ حداقل انتقال باید {money(config.TRF_MIN_AMOUNT)} باشه، بیشتر بگو"
    if amount > config.TRF_MAX_AMOUNT:
        return False, f"❌ حداکثر انتقال باید {money(config.TRF_MAX_AMOUNT)} باشه، کمتر بگو"
    left = trf_cooldown_left(sender)
    if left > 0:
        return False, f"⏳ تازه انتقال دادی، تا {fa_num(left)} ثانیه دیگه نمیتونی انتقال بدی"
    if sender.bank_balance < amount:
        return False, f"❌ تو بانک این همه نداری، موجودیت {money(sender.bank_balance)} ـه"
    name = users_svc.display_name(recipient)
    cap = bank_capacity(recipient.bank_level)
    room = max(0, cap - recipient.bank_balance)
    if amount > room:
        if room <= 0:
            return False, f"🏦 بانک «{name}» کاملاً پره، الان امکان واریز به حسابش نیست"
        return False, f"🏦 بانک «{name}» فقط {money(room)} جای خالی داره، کمتر بگو"
    sender.bank_balance -= amount
    recipient.bank_balance += amount
    sender.last_trf_at = now_utc()
    return True, f"💳 {money(amount)} به حساب «{name}» واریز شد"
