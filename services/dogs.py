"""منطق سگ‌ها: خرید | غذا دادن | لول‌آپ | قدرت"""


from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import Dog, User
from services import users
from utils import fa_num, iran_today, money, normalize_fa, now_utc


def dog_xp_need(level: int) -> int:
    """xp لازم سگ برای رفتن از لول فعلی به بعدی"""
    return int(config.DOG_XP_BASE * (level ** config.DOG_XP_EXP))


def dog_attack(dog: Dog) -> int:
    """قدرت حمله سگ فقط از نژاد و لولش، سیستم شخصیت کامل حذف شده"""
    cfg = config.DOGS.get(dog.dog_key)
    if not cfg:
        return 0
    return cfg["attack"] + cfg["atk_per_level"] * max(0, dog.level - 1)


# ───────── ویژگی نژادها 🎖 (درصدی و مقیاس لول) ─────────

def trait_value(dog: Dog) -> float:
    """مقدار فعلی ویژگی نژاد سگ، از صفر تا max بر اساس لولش (مثل گرگ سیاه)"""
    tr = config.DOGS.get(dog.dog_key, {}).get("trait")
    if not tr:
        return 0.0
    ratio = min(1.0, dog.level / config.DOG_MAX_LEVEL)
    return ratio * tr["max"]


def _best_trait(dogs: list[Dog], kind: str) -> float:
    best = 0.0
    for d in dogs:
        tr = config.DOGS.get(d.dog_key, {}).get("trait")
        if tr and tr["kind"] == kind:
            best = max(best, trait_value(d))
    return best


def breed_cooldown_mult(dogs: list[Dog]) -> float:
    """پیتبول ⚡، کولدان حمله رو کم می‌کنه (بهترین اثر حساب میشه)"""
    return max(0.5, 1.0 - _best_trait(dogs, "cooldown"))


def battle_xp_mult(dogs: list[Dog]) -> float:
    """ژرمن شپرد 🎁، تجربه نبرد بیشتر"""
    return 1.0 + _best_trait(dogs, "xp")


def trait_atk_pct(dogs: list[Dog]) -> float:
    """کانگال 💥، درصد بونس قدرت حمله صاحبش"""
    return _best_trait(dogs, "attack")


def trait_def_pct(dogs: list[Dog]) -> float:
    """دوبرمن 🛡، درصد بونس دفاع صاحبش"""
    return _best_trait(dogs, "defense")


def trait_ability_lines(dog: Dog) -> list[str]:
    """
    خط ویژگی سگ با درصد فعلی لولش، مثل «🎖 ویژگی: کاهش کولدان حمله 5%»
    گرگ سیاه خط‌های قابلیت خودشو داره
    """
    if config.DOGS.get(dog.dog_key, {}).get("rare"):
        return rare_ability_lines(dog)
    tr = config.DOGS.get(dog.dog_key, {}).get("trait")
    if not tr:
        return []
    pct = round(trait_value(dog) * 100)
    # ایموجی ویژگی از کارت سگ‌های من پاک شد، فقط اسم و درصدش می‌مونه
    return [f"🎖 ویژگی: {tr['title']} {fa_num(pct)}%"]


async def add_battle_xp(dogs: list[Dog], amount: int) -> list[str]:
    """تجربه نبرد برای سگ‌ها، لول‌آپ قدرتشون رو می‌بره بالا"""
    notes: list[str] = []
    for d in dogs:
        d.xp += amount
        while d.level < config.DOG_MAX_LEVEL and d.xp >= dog_xp_need(d.level):
            d.xp -= dog_xp_need(d.level)
            d.level += 1
            notes.append(
                f"🆙 آفرین، {d.name} لول‌آپ شد و الان قدرتش {fa_num(dog_attack(d))} شد"
            )
    return notes


def find_dog_by_name(dogs: list[Dog], query: str):
    """پیدا کردن سگ از روی اسم (دقیق یا بخشی از اسم)"""
    q = normalize_fa(query)
    for d in dogs:
        if normalize_fa(d.name) == q:
            return d
    for d in dogs:
        if q in normalize_fa(d.name):
            return d
    return None


def rename_dog(dogs: list[Dog], query: str, new_name: str) -> tuple[bool, str]:
    """تغییر اسم سگ با دستور «اسم سگ»، خروجی: (اوکی, پیام)"""
    dog = find_dog_by_name(dogs, query)
    if not dog:
        return False, "🤷 سگی با این اسم پیدا نکردم"
    others = [d for d in dogs if d.id != dog.id]
    ok, display, why = check_dog_name(others, new_name)
    if not ok:
        return False, why
    old = dog.name
    dog.name = display
    return True, f"🐕 اسم {old} شد «{display}»"


def rare_steal_bonus(dogs: list[Dog]) -> float:
    """غرامت بیشتر بهترین گرگ سیاه، تا RARE_DOG_STEAL_MAX (۱۰%) بر اساس لول"""
    best = 0.0
    for d in dogs:
        if config.DOGS.get(d.dog_key, {}).get("rare"):
            ratio = min(1.0, d.level / config.DOG_MAX_LEVEL)
            best = max(best, ratio * config.RARE_DOG_STEAL_MAX)
    return best


def rare_defense_cut(dogs: list[Dog]) -> float:
    """کاهش دفاع حریف توسط گرگ سیاه، تا RARE_DOG_DEF_CUT_MAX (۳۰%) بر اساس لول"""
    best = 0.0
    for d in dogs:
        if config.DOGS.get(d.dog_key, {}).get("rare"):
            ratio = min(1.0, d.level / config.DOG_MAX_LEVEL)
            best = max(best, ratio * config.RARE_DOG_DEF_CUT_MAX)
    return best


def rare_ability_lines(dog: Dog) -> list[str]:
    """متن قابلیت گرگ سیاه با اعداد مقیاس لولش، مثل «دفاع حریف رو 18% کاهش میده»"""
    if not config.DOGS.get(dog.dog_key, {}).get("rare"):
        return []
    ratio = min(1.0, dog.level / config.DOG_MAX_LEVEL)
    cut = round(ratio * config.RARE_DOG_DEF_CUT_MAX * 100)
    steal = round(ratio * config.RARE_DOG_STEAL_MAX * 100)
    return [
        f"🎖 دفاع حریف رو {fa_num(cut)}% کاهش میده",
        f"🪙 غرامت جنگی رو {fa_num(steal)}% افزایش میده",
    ]


async def get_user_dogs(session: AsyncSession, user_id: int) -> list[Dog]:
    q = select(Dog).where(Dog.user_id == user_id).order_by(Dog.id)
    return list((await session.execute(q)).scalars())


def _check_buyable(user: User, dogs: list[Dog], dog_key: str) -> tuple[bool, str]:
    """چک‌های مشترک خرید سگ (قبل از پرداخت)"""
    cfg = config.DOGS.get(dog_key)
    if not cfg:
        return False, "❌ همچین سگی نیس"
    if any(d.dog_key == dog_key for d in dogs):
        return False, f"تو نژاد {cfg['breed']} رو داری که"
    if len(dogs) >= config.MAX_DOGS:
        return False, f"🐕 بیشتر از {fa_num(config.MAX_DOGS)} سگ نمی‌تونی داشته باشی"
    if user.level < cfg["min_level"]:
        return False, f"🔒 لول {fa_num(cfg['min_level'])} می‌خواد"
    if user.cash < cfg["price"]:
        return False, "❌ تی‌پوینتت کافی نیس"
    return True, ""


def check_dog_name(dogs: list[Dog], name: str) -> tuple[bool, str, str]:
    """ولیدیشن اسم سگ، خروجی: (اوکی, اسم تمیز برای نمایش, دلیل رد)"""
    clean = normalize_fa(name)
    if not clean or len(clean) < 2:
        return False, "", "❌ اسم خیلی کوتاهه، یه اسم درست بفرست"
    display = " ".join(str(name).split())  # نیم‌فاصله‌های کاربر حفظ میشه
    if len(display) > 24:
        return False, "", "❌ اسم حداکثر 24 حرف می‌تونه باشه"
    if ":" in clean or "<" in clean or ">" in clean:
        return False, "", "❌ تو اسم کاراکتر عجیب نذار"
    if any(normalize_fa(d.name) == clean for d in dogs):
        return False, "", f"❌ یه سگ دیگه اسمش «{display}» ـه، یه اسم دیگه بفرست"
    return True, display, ""


async def buy_dog(
    session: AsyncSession, user: User, dog_key: str, custom_name: str | None = None
) -> tuple[bool, str]:
    """خرید سگ با اسم مشخص، بعد از تایید فاکتور، پول همینجا کم میشه و سگ ساخته میشه"""
    dogs = await get_user_dogs(session, user.id)
    ok, alert = _check_buyable(user, dogs, dog_key)
    if not ok:
        return False, alert

    cfg = config.DOGS[dog_key]
    ok_name, name, why = check_dog_name(dogs, custom_name or cfg["name"])
    if not ok_name:
        return False, why

    user.cash -= cfg["price"]
    session.add(Dog(
        user_id=user.id,
        dog_key=dog_key,
        name=name,
        breed=cfg["breed"],
    ))
    return True, (
        f"🐕 مبارکه، {name} رفیق جدیدت شد\n\n"
        f"باهوشه و به اسمش واکنش میده، کافیه بگی «تریاکی آمار {name}»\n\n"
        f"💵 نقدینگی: {money(user.cash)}"
    )


# ───────── فلو جدید خرید سگ: اول اسم می‌پرسه → فاکتور تایید → پرداخت ─────────

async def hold_dog(session: AsyncSession, user: User, dog_key: str, chat_id: int | None = None) -> tuple[bool, str]:
    """
    شروع فلو خرید سگ، فقط اکشن معلق می‌ذاره و اسم می‌خواد
    هیچ پولی اینجا کم نمیشه، پرداخت بعد از تایید فاکتوره (buy_dog)
    """
    if user.pending_action:
        return False, "⏳ اول کار قبلیتو تموم کن یا «لغو» بزن"

    dogs = await get_user_dogs(session, user.id)
    ok, alert = _check_buyable(user, dogs, dog_key)
    if not ok:
        return False, alert

    cfg = config.DOGS[dog_key]
    users.set_pending(user, "dogname", dog_key, chat_id)
    return True, f"🐕 اسم {cfg['breed']} چی باشه؟ اسمشو بفرست"


async def cancel_pending(session: AsyncSession, user: User) -> str:
    """لغو کار معلق، هر اکشنی پاک میشه (هیچکدوم هنوز پولی جابه‌جا نکردن)، راند ۱۱ جاافتاده‌ها مثل خرید بذر و محموله هم پوشش داده شدن"""
    action = user.pending_action
    if not action:
        return "🤷 کاری در جریان نیس که"

    users.set_pending(user, None)
    if action == "dogname":
        return "😅 خرید سگ لغو شد"
    if action == "ressell":
        return "باشه بیخیال فروش منابع شدیم"
    if action == "resbuy":
        return "باشه بیخیال خرید منابع شدیم"
    if action == "seedbuy":
        return "باشه بی‌خیال خرید بذر شدیم 🌱"
    if action in ("smqty", "smcqty"):
        return "باشه بی‌خیال ارسال محموله شدیم 🚚"
    return "😅 بی‌خیال شدیم"


def feeds_left(dog: Dog) -> int:
    """سهمیه غذای باقی‌مونده خودِ این سگ، هر روز ساعت ۱۲ شب (به‌وقت ایران) ریست میشه"""
    today = iran_today()
    if dog.feed_day != today:
        dog.feed_day = today
        dog.feeds_today = 0
    return max(0, config.DOG_FEED_PER_DAY - dog.feeds_today)


def full_text(dog: Dog) -> str:
    """متن سیر بودن یه سگ خاص"""
    return f"🍖 {dog.name} سیر شده"


def hunger_text(dog: Dog) -> str:
    """خط وضعیت گرسنگی یه سگ، «هنوز گرسنشه و Nتا غذای دیگه جا داره» یا «سیر شده»"""
    left = feeds_left(dog)
    if left > 0:
        return f"🍖 {dog.name} هنوز گرسنشه و {fa_num(left)}تا غذای دیگه جا داره"
    return full_text(dog)


async def feed_dog(session: AsyncSession, user: User, dog: Dog, food_key: str) -> tuple[bool, str, list[str]]:
    """
    غذا دادن به سگ، هزینه غذا همون لحظه از جیب میره
    خروجی: (موفق, پیام, لیست پیام‌های لول‌آپ)
    """
    food = config.DOG_FOODS.get(food_key)
    if not food:
        return False, "❌ همچین غذایی نیس", []

    if dog.user_id != user.id:
        return False, "❌ این سگ مال تو نیس", []
    if feeds_left(dog) <= 0:
        return False, full_text(dog), []
    if dog.level >= config.DOG_MAX_LEVEL:
        return False, f"⭐ {dog.name} مکس لوله", []
    if user.cash < food["price"]:
        return False, "❌ تی‌پوینتت کافی نیس", []

    user.cash -= food["price"]
    dog.feeds_today += 1
    dog.xp += food["xp"]

    notes: list[str] = []
    while dog.level < config.DOG_MAX_LEVEL and dog.xp >= dog_xp_need(dog.level):
        dog.xp -= dog_xp_need(dog.level)
        dog.level += 1
        notes.append(
            f"🆙 {dog.name} رفت رو لول {fa_num(dog.level)} و الان {fa_num(dog_attack(dog))} قدرت داره"
        )
    if dog.level >= config.DOG_MAX_LEVEL:
        dog.xp = 0

    msg = f"🍖 {dog.name} {food['name']} رو خورد و {fa_num(food['xp'])} تجربه گرفت"
    return True, msg, notes


async def release_dog(session: AsyncSession, user: User, dog: Dog) -> tuple[bool, str]:
    """رها کردن سگ، برگشتی نداره"""
    if dog.user_id != user.id:
        return False, "❌ این سگ مال تو نیس"
    name = dog.name
    await session.delete(dog)
    return True, f"🕊 {name} رو رها کردی، رفت دنبال زندگیش"


def find_my_dog(dogs: list[Dog], query: str) -> Dog | None:
    """پیدا کردن سگ کاربر با اسم، برای «آمار اصغر»"""
    q = normalize_fa(query)
    if not q:
        return None
    for d in dogs:
        if normalize_fa(d.name) == q:
            return d
    partial = [d for d in dogs if q in normalize_fa(d.name)]
    return partial[0] if len(partial) == 1 else None


def find_dog(query: str):
    """پیدا کردن سگ از کاتالوگ با نژاد، مثل «دوبرمن»"""
    q = normalize_fa(query)
    for key, d in config.DOGS.items():
        if normalize_fa(d["name"]) == q:
            return key, d
    for key, d in config.DOGS.items():
        if q and (q in normalize_fa(d["name"]) or q == normalize_fa(d["breed"])):
            return key, d
    return None, None


def parse_dog_query(query: str):
    """
    پارس «نژاد [اسم دلخواه]» برای خرید متنی
    خروجی: (key, cfg, custom_name یا None)
    مثال: «دوبرمن» → همون نژاد | «دوبرمن رکس» → نژاد دوبرمن با اسم رکس
    """
    q = normalize_fa(query)
    if not q:
        return None, None, None

    # مچ دقیق اسم پیش‌فرض
    for key, d in config.DOGS.items():
        if normalize_fa(d["name"]) == q:
            return key, d, None

    # نژاد + اسم دلخواه، نژادهای چندکلمه‌ای اول چک میشن
    for key, d in sorted(config.DOGS.items(), key=lambda kv: -len(kv[1]["breed"])):
        breed = normalize_fa(d["breed"])
        if q == breed:
            return key, d, None
        if q.startswith(breed + " "):
            custom = q[len(breed) + 1:].strip()
            return key, d, custom or None

    # مچ جزئی روی اسم
    key, cfg = find_dog(q)
    return key, cfg, None
