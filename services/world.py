"""
سیستم‌های جهان بازی: آب و هوا 🌦 | بازار سیاه 📈 | جستجو 🔍 | قمارخانه 🎰
یورش پلیس 🚔 | کاروان 🚛 | فعالیت گروه‌ها

همه state ها یا توی game_meta هستن (آب و هوا/بازار، با ری‌استارت می‌مونن)
یا توی حافظه (کاروان، مثل کنده‌کاری کارتلی، زودگذره)
"""

import random
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import GameMeta, GroupActivity, GroupPlayer, Plot, SeedSale, SeedStock, User
from services import economy
from services.farming import get_stock, add_seed_stock, try_add_seed
from services.users import add_xp
from utils import esc, fa_dur, fa_num, money, now_iran, now_utc


# ═════════ فعالیت گروه‌ها ═════════

# کش حافظه‌ای نشانه‌گذاری پلیرای گروه: (گروه, کاربر) → آخرین ثبت، که هر پیام کوئری نزنه
_PLAYER_MARK: dict[tuple[int, int], datetime] = {}
_PLAYER_MARK_REFRESH = timedelta(hours=1)
_PLAYER_MARK_CAP = 5000


async def touch_group(session: AsyncSession, chat_id: int, title: str | None = None, user_tg: int | None = None) -> None:
    """
    آپدیت آخرین فعالیت گروه، موجب میشه گروه تو لیست اعلان آب و هوا و کاروان بمونه
    فقط صدا‌کننده دستورهاست (چت عادی ملت حساب نمیشه)، اسم گروه و شمارنده «دستورهای» ساعت
    جاری ایران (msgs_hour) و دیده‌شدن پلیراش هم برای آمار ادمین نگه داشته میشه
    """
    ir = now_iran()
    bucket = f"{ir.date().isoformat()}-{ir.hour:02d}"
    row = await session.get(GroupActivity, chat_id)
    if row:
        row.last_active_at = now_utc()
    else:
        row = GroupActivity(chat_id=chat_id)
        session.add(row)
    if title:
        row.title = title[:128]
    if row.hour_key != bucket:
        row.hour_key = bucket
        row.msgs_hour = 1
    else:
        row.msgs_hour = (row.msgs_hour or 0) + 1

    # دیده‌شدن پلیر تو این گروه، برای شمارش «تعداد پلیرای هر گروه» تو آمار ادمین
    if user_tg is not None:
        key = (chat_id, user_tg)
        last = _PLAYER_MARK.get(key)
        now = now_utc()
        if last is None or now - last >= _PLAYER_MARK_REFRESH:
            if len(_PLAYER_MARK) >= _PLAYER_MARK_CAP:
                _PLAYER_MARK.clear()  # GC کش، لیک نده
            _PLAYER_MARK[key] = now
            prow = await session.get(GroupPlayer, (chat_id, user_tg))
            if prow:
                prow.last_active_at = now
            else:
                session.add(GroupPlayer(chat_id=chat_id, user_tg=user_tg))


async def active_group_ids(session: AsyncSession, hours: float) -> list[int]:
    """گروه‌های فعال تو x ساعت اخیر"""
    limit = now_utc() - timedelta(hours=hours)
    q = select(GroupActivity.chat_id).where(GroupActivity.last_active_at >= limit)
    return list((await session.execute(q)).scalars())


# ═════════ متا ═════════

async def _meta(session: AsyncSession, key: str) -> str | None:
    row = await session.get(GameMeta, key)
    return row.value if row else None


async def _meta_set(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(GameMeta, key)
    if row:
        row.value = value
    else:
        session.add(GameMeta(key=key, value=value))


# ═════════ آب و هوا 🌦 ═════════

def weather_of(key: str) -> dict:
    return config.WEATHERS.get(key) or config.WEATHERS["normal"]


_IRAN_OFFSET = timedelta(hours=3, minutes=30)


def _next_weather_boundary(now) -> object:
    """
    مرز بعدی تغییر آب و هوا به UTC، هوا سر ساعت‌های ایرانی WEATHER_BOUNDARY_HOURS (۲۴، ۶، ۱۲ و ۱۸) عوض میشه
    """
    ir = now + _IRAN_OFFSET
    for h in config.WEATHER_BOUNDARY_HOURS:
        cand = ir.replace(hour=h, minute=0, second=0, microsecond=0)
        if cand > ir:
            return cand - _IRAN_OFFSET
    first = config.WEATHER_BOUNDARY_HOURS[0]
    cand = (ir.replace(hour=first, minute=0, second=0, microsecond=0) + timedelta(days=1))
    return cand - _IRAN_OFFSET


def _effect_emoji(line: str) -> str:
    """ایموجی خط افکت اعلان آب و هوا بر اساس موضوعش"""
    if "رشد" in line:
        return "🌱"
    if "دفاع" in line:
        return "🛡"
    if "حمله" in line:
        return "⚔️"
    if "فروش" in line:
        return "💰"
    return "⭐"


def _weather_pct(key: str, pct: int | None) -> int:
    """درصد افکت؛ اگه رولی در کار نباشه (هوای ست‌شده قبل از نسخه پویا) پایه کانفیگ میاد"""
    if pct is not None:
        return pct
    return int(weather_of(key).get("base", 0))


def _weather_lines(key: str, field: str, pct: int | None) -> list[str]:
    """قالب‌های announce/effects با درصد واقعی همین رول پر میشن"""
    p = _weather_pct(key, pct)
    return [t.format(p=p) for t in weather_of(key).get(field, [])]


def weather_announce_text(key: str, pct: int | None = None, left: int | None = None) -> str:
    """پیام اعلان آب و هوای جدید برای گروه‌ها، افکت با درصد همین رول و مهلت واقعی تا مرز بعدی"""
    w = weather_of(key)
    span = fa_dur(left) if left else f"{fa_num(config.WEATHER_ROLL_SECONDS // 3600)} ساعت"
    lines = ["<b>🌦 وضعیت آب و هوای جدید</b>", ""]
    if key == "normal":
        lines.append("🏙️ هوای محله صافِ صاف شد الان دیگه هیچ افکت خاصی فعال نیست")
    else:
        lines.append(f"{w['emoji']} {w['name']} آغاز شد")
        for b in _weather_lines(key, "announce", pct):
            lines.append(f"{_effect_emoji(b)} {b}، تا {span} آینده")
    return "\n".join(lines)


async def ensure_weather(session: AsyncSession, force: bool = False) -> tuple[str, object | None]:
    """
    آب و هوای فعلی رو بگیر، اگه زمانش گذشته بود همینجا رول کن (تنبل، رول‌بک‌پروف)
    force=True یعنی فوراً رول کن حتی اگه زمانش نرسیده (کامند /update ادمین)
    خروجی: (کلید, رکورد جدید اگه همین لحظه رول شده وگرنه None)
    """
    until_raw = await _meta(session, "weather_until")
    cur_key = await _meta(session, "weather_key") or "normal"
    now = now_utc()

    until = None
    if until_raw:
        try:
            from datetime import datetime as _dt
            until = _dt.fromisoformat(until_raw)
        except ValueError:
            until = None

    if cur_key in config.WEATHERS and until and until > now and not force:
        return cur_key, None

    # درصد رول قبلی، برای تنظیم تایمر زمین‌های در حال رشد لازمه
    old_pct_raw = await _meta(session, "weather_pct")
    old_pct = int(old_pct_raw) if old_pct_raw is not None else None

    # رول جدید
    if random.random() < config.WEATHER_NORMAL_CHANCE:
        key = "normal"
    else:
        specials = [k for k in config.WEATHERS if k != "normal"]
        key = random.choice(specials)

    # شدت افکت این رول: سه‌گوش حول پایه با مود زیر پایه، بعد اثر شلوغی محله، بعد کلمپ
    pct: int | None = None
    if key != "normal":
        base = int(weather_of(key).get("base", 0))
        f = random.triangular(config.WEATHER_ROLL_MIN_F, config.WEATHER_ROLL_MAX_F, config.WEATHER_ROLL_MODE_F)
        act = await _active_players_24h(session)
        crowd = 1.0 + config.WEATHER_ACTIVE_WEIGHT * max(
            -1.0, min(1.0, (act - config.WEATHER_ACTIVE_REF) / max(1, config.WEATHER_ACTIVE_REF))
        )
        pct = int(round(base * f * crowd))
        pct = max(config.WEATHER_MIN_PCT, min(config.WEATHER_MAX_PCT, pct))

    # رول بعدی سر ساعت‌های ایرانی ۲۴/۶/۱۲/۱۸ میفته نه ۶ ساعت بعد از این لحظه
    new_until = _next_weather_boundary(now)
    await _meta_set(session, "weather_key", key)
    await _meta_set(session, "weather_until", new_until.isoformat())
    await _meta_set(session, "weather_pct", str(pct or 0))
    # افکت هوای جدید همون لحظه روی محصول‌های در حال رشد هم اعمال میشه
    await apply_growth_rescale(session, cur_key, key, old_pct, pct)
    return key, {"key": key, "until": new_until, "pct": pct or 0}


async def apply_growth_rescale(
    session: AsyncSession, old_key: str, new_key: str,
    old_pct: int | None = None, new_pct: int | None = None,
) -> int:
    """
    با عوض شدن آب و هوا، تایمر زمین‌های در حال رشد بر اساس سرعت جدید تنظیم میشه
    کار باقی‌مونده ثابت می‌مونه، فقط سرعتش با هوای جدید حساب میشه
    خروجی: تعداد زمین‌هایی که تایمرشون عوض شد
    """
    old_speed = weather_grow_speed(old_key, old_pct)
    new_speed = weather_grow_speed(new_key, new_pct)
    if old_speed <= 0 or new_speed <= 0 or old_speed == new_speed:
        return 0
    mult = old_speed / new_speed
    now = now_utc()
    q = select(Plot).where(Plot.status == "growing", Plot.ready_at.isnot(None))
    changed = 0
    for p in (await session.execute(q)).scalars():
        left = (p.ready_at - now).total_seconds()
        if left <= 0:
            continue
        p.ready_at = now + timedelta(seconds=max(5, int(left * mult)))
        changed += 1
    return changed


async def current_weather(session: AsyncSession) -> tuple[str, int]:
    """(کلید آب و هوا, ثانیه مونده)، برای نمایش و افکت‌ها"""
    key, _ = await ensure_weather(session)
    until_raw = await _meta(session, "weather_until")
    from datetime import datetime as _dt
    try:
        left = int((_dt.fromisoformat(until_raw) - now_utc()).total_seconds()) if until_raw else 0
    except ValueError:
        left = 0
    return key, max(0, left)


async def weather_state(session: AsyncSession) -> tuple[str, int | None, int]:
    """
    (کلید هوای فعلی، درصد رول فعلی اگه ویژه‌ست وگرنه None، ثانیه مونده)
    None یعنی یا هوا عادیه یا از دوره قبل از شدت پویا مونده، در این حالت پایه کانفیگ اعمال میشه
    """
    key, left = await current_weather(session)
    if key == "normal":
        return key, None, left
    raw = await _meta(session, "weather_pct")
    return key, (int(raw) if raw is not None else None), left


def weather_grow_speed(key: str, pct: int | None = None) -> float:
    """ضریب سرعت رشد: باران +p% | گرما p%− | سرما +p% زمان، p درصد همین روله (نه ثابت)"""
    w = weather_of(key)
    p = _weather_pct(key, pct)
    if w.get("kind") == "speed":
        return 1.0 + w.get("sign", 1) * p / 100.0
    if w.get("kind") == "time":
        return 1.0 / (1.0 + p / 100.0)
    return 1.0


def weather_sell_mult(key: str, pct: int | None = None) -> float:
    """ضریب قیمت فروش (جشن برداشت +p%)"""
    w = weather_of(key)
    if w.get("kind") == "sell":
        return 1.0 + _weather_pct(key, pct) / 100.0
    return 1.0


def weather_combat_mods(key: str, pct: int | None = None) -> tuple[float, float]:
    """(اصلاح حمله, اصلاح دفاع)، طوفان حمله p%− | مه دفاع p%+"""
    w = weather_of(key)
    p = w.get("sign", 1) * _weather_pct(key, pct) / 100.0
    if w.get("kind") == "atk":
        return p, 0.0
    if w.get("kind") == "def":
        return 0.0, p
    return 0.0, 0.0


async def weather_view(session: AsyncSession) -> dict:
    """دیتای بخش «وضعیت آب و هوا» با درصدهای رندرشده همین رول"""
    key, pct, left = await weather_state(session)
    w = weather_of(key)
    return {"key": key, "w": w, "left": left, "pct": pct, "effect_lines": _weather_lines(key, "effects", pct)}


# ═════════ بازار سیاه 📈 (پویا بر پایه عرضه و تقاضای واقعی) ═════════

def _parse_market(raw: str | None) -> dict[str, float]:
    """
    رشته متا «seed:mult,...» به نقشه ضریب قیمت هر محصول
    فرمت جدید همیشه اعشاریه (مثل 1.0300) و فرمت خیلی قدیمی درصد صحیح بود، اینجا سازگار ترجمه میشه
    """
    out: dict[str, float] = {}
    if not raw:
        return out
    for chunk in raw.split(","):
        if ":" in chunk:
            k, v = chunk.split(":", 1)
            try:
                if "." in v or "e" in v.lower():
                    out[k] = float(v)
                else:  # رول قدیمی درصدی صحیح بود، به ضریب قیمت ترجمش می‌کنیم
                    out[k] = 1.0 + int(v) / 100.0
            except ValueError:
                continue
    return out


async def record_sale(session: AsyncSession, seed_key: str, qty: int = 1) -> None:
    """
    ثبت یه فروش واقعی محصول برای حساب عرضه بازار، فقط ردیف اضافه می‌کنه (کامیت با صدا‌کننده‌ست)
    هر از چندگاهی ردیف‌های قدیمی پاک میشن تا جدول همیشه سبک بمونه
    """
    if seed_key not in config.SEEDS:  # چوب/آهن دیگه ثبت نمیشن، قیمتشون دیگه به فروش ربطی نداره
        return
    session.add(SeedSale(seed_key=seed_key, qty=qty, at=now_utc()))
    if random.random() < config.ACTION_LOG_PRUNE_CHANCE:
        cutoff = now_utc() - timedelta(hours=config.MARKET_SALE_KEEP_HOURS)
        await session.execute(delete(SeedSale).where(SeedSale.at < cutoff))


async def _active_players_24h(session: AsyncSession) -> int:
    """تعداد بازیکنای فعال ۲۴ ساعت اخیر، مبنای تقاضای بازار"""
    day_ago = now_utc() - timedelta(hours=24)
    return (await session.execute(
        select(func.count(User.id)).where(User.last_seen_at >= day_ago)
    )).scalar() or 0


async def _sales_24h(session: AsyncSession) -> dict[str, int]:
    """فروش واقعی ۲۴ ساعت اخیر به تفکیک محصول، SUM گروه‌بندی‌شده مستقیم توی SQL"""
    day_ago = now_utc() - timedelta(hours=24)
    rows = (await session.execute(
        select(SeedSale.seed_key, func.coalesce(func.sum(SeedSale.qty), 0))
        .where(SeedSale.at >= day_ago)
        .group_by(SeedSale.seed_key)
    )).all()
    return {key: int(total) for key, total in rows}


def _next_market_mult(old: float, sold: int, demand: float,
                      lo_mult: float | None = None, hi_mult: float | None = None,
                      sat_max: float | None = None) -> float:
    """
    ضریب بعدی یه محصول: حرکت شانسی دور و بر MARKET_MAX_STEP_CHANGE بر اساس نسبت عرضه به تقاضا
    اشباع فروش هرچی سنگین‌تر باشه افت تندتر میشه تا چک کردن بازار به‌صرفه،
    سقف و کف واقعی هر رول هم دور و بر ±25% جابه‌جا میشن (جیتر کانفیگ) تا عددها قفلِ دقیق نمونن
    """
    demand = max(1.0, demand)
    ratio = sold / demand
    mult = old
    step = config.MARKET_MAX_STEP_CHANGE * random.uniform(1.0, 1.6)  # هر رول بزرگی حرکت فرق می‌کنه
    if ratio < 1.0:  # عرضه کمتر از تقاضا، کمیابی و گرون شدن
        mult += step
    elif ratio > 1.0:  # اشباع بازار، ارزون شدن؛ فروش خیلی زیاد ریزش رو عمیق‌تر می‌کنه
        depth = min(sat_max or config.MARKET_SELL_SATURATION_MAX, ratio)
        mult -= step * depth
    mult *= 1.0 + random.uniform(-config.MARKET_RANDOM_NOISE, config.MARKET_RANDOM_NOISE)
    jit = config.MARKET_BAND_JITTER
    hi = (hi_mult or config.MARKET_MAX_PRICE_MULTIPLIER) + random.uniform(-jit, jit)
    lo = (lo_mult or config.MARKET_MIN_PRICE_MULTIPLIER) + random.uniform(-jit, jit)
    return min(hi, max(lo, mult))


async def ensure_market(session: AsyncSession, force: bool = False) -> bool:
    """
    اگه زمان بازار گذشته بود یه حرکت قیمت بزن، خروجی True یعنی همین لحظه رول شد
    force=True یعنی فوراً رول کن حتی اگه زمانش نرسیده (کامند /update ادمین)
    """
    until_raw = await _meta(session, "market_until")
    from datetime import datetime as _dt
    try:
        until = _dt.fromisoformat(until_raw) if until_raw else None
    except ValueError:
        until = None

    if until and until > now_utc() and not force:
        return False

    old = _parse_market(await _meta(session, "market"))
    active_n = await _active_players_24h(session)
    demand = max(1.0, active_n * config.MARKET_DEMAND_PER_ACTIVE_PLAYER)
    sales = await _sales_24h(session)

    parts = []
    for key in config.SEEDS:  # همه محصولات از روز اول تو بازارن، حتی افسانه‌ای‌ها و قفل‌های لول
        mult = _next_market_mult(old.get(key, 1.0), sales.get(key, 0), demand)
        parts.append(f"{key}:{mult:.4f}")
    # راند جدید: چوب و آهن دیگه به فروش/عرضه‌وتقاضا کاری ندارن، هر رول قیمتشون کاملاً شانسیه تو بازه ثابت
    for key in ("wood", "iron"):
        lo, hi = config.RES_PRICE_RANGE[key]
        price = random.randint(lo, hi)
        base = config.RES_SELL_PRICES[key]
        mult = price / base
        parts.append(f"{key}:{mult:.4f}")
    await _meta_set(session, "market", ",".join(parts))
    await _meta_set(session, "market_until", (now_utc() + timedelta(seconds=config.MARKET_ROLL_SECONDS)).isoformat())
    return True


async def market_mults(session: AsyncSession) -> tuple[dict[str, float], int]:
    """(ضریب قیمت فعلی هر محصول, ثانیه مونده تا حرکت بعدی بازار)"""
    await ensure_market(session)
    mults = _parse_market(await _meta(session, "market"))
    from datetime import datetime as _dt
    raw = await _meta(session, "market_until")
    try:
        left = int((_dt.fromisoformat(raw) - now_utc()).total_seconds()) if raw else 0
    except ValueError:
        left = 0
    return mults, max(0, left)


def market_mult(mults: dict[str, float], seed_key: str) -> float:
    """ضریب قیمت بازار یه محصول، نبود یعنی دقیقا قیمت پایه"""
    return mults.get(seed_key, 1.0)


def market_view_text(mults: dict[str, float], left: int) -> str:
    """
    متن بخش «وضعیت بازار سیاه» (راند ۳۱، قالب دقیق کارفرما): راهنمای کامل + کارت هر محصول با جداکننده
    همه محصولات از روز اول با قیمتشون دیده میشن، محدودیت لول فقط رو خرید و کاشته نه دیدن قیمت
    """
    def _lead_emoji(name: str) -> str:
        # اسم بذرهای افسانه‌ای ایموجی تهشونه («بذر جهنم 🔥»)، تو قالب کارفرما اول اسم میان
        head, _, tail = name.rpartition(" ")
        if tail and not any("آ" <= c <= "ی" for c in tail):
            return f"{tail} {head}" if head else tail
        return name

    roll_h = max(1, config.MARKET_ROLL_SECONDS // 3600)
    sections = [
        "\n".join([
            "<b>📈 وضعیت بازار سیاه</b>",
            "",
            "💡 قیمت فروش هر محصول توسط بازیکن‌ها تعیین می‌شود",
            "",
            "- هر فروش روی قیمت اثر می‌گذارد",
            "- اگر محصول کمیاب شود، قیمتش بالا می‌رود",
            "- اگر بازار اشباع شود، قیمتش پایین می‌آید",
            "- فروش سنگین یک محصول می‌تواند باعث افت سریع قیمت شود",
            "- قبل از کاشت حتماً بازار را بررسی کن گاهی محصول ارزان‌تر سود بیشتری می‌دهد",
            "",
            "راهنمای وضعیت قیمت‌ها:",
            "",
            "- 📈 بالاتر از قیمت پایه",
            "- 📉 پایین‌تر از قیمت پایه",
            "- ⚖️ نزدیک قیمت پایه",
            "",
            f"⏱️ قیمت‌ها هر {fa_num(roll_h)} ساعت یک‌بار نوسان کوچکی دارند",
        ])
    ]

    def _pct(mult: float) -> float:
        pct = round((mult - 1.0) * 100, 1)
        return 0.0 if abs(pct) < 0.05 else pct

    for key, sd in config.SEEDS.items():
        mult = mults.get(key, 1.0)
        pct = _pct(mult)
        cur = int(sd["sell"] * mult)
        trend = "📈" if pct > 0 else ("📉" if pct < 0 else "⚖️")
        trend_line = f"{trend} {pct:+.1f}%" if pct != 0 else f"{trend} نزدیک قیمت پایه"
        emoji = sd.get("emoji")
        disp = f"{emoji} {sd['name']}" if emoji else _lead_emoji(sd["name"])  # افسانه‌ای‌ها ایموجیشون اول اسم بیاد (قالب کارفرما)
        sections.append("\n".join([
            disp,
            "",
            trend_line,
            "",
            f"💰 قیمت فعلی: {money(cur)}",
            "",
            f"📦 قیمت پایه: {money(sd['sell'])}",
        ]))

    # راند جدید: چوب و آهن قیمتشون کاملاً شانسیه، هر رول یه عدد تصادفی تو بازه ثابت خودشون میگیرن
    res_lines = ["🪵⛏️ بازار منابع", "", "قیمت چوب و آهن هر رول کاملاً شانسی جابه‌جا میشه:", ""]
    for key in ("wood", "iron"):
        mult = mults.get(key, 1.0)
        cur = int(config.RES_SELL_PRICES[key] * mult)
        nm = "چوب" if key == "wood" else "آهن"
        em = "🪵" if key == "wood" else "⛏️"
        lo, hi = config.RES_PRICE_RANGE[key]
        res_lines.append(f'- {em} {nm}: "{fa_num(cur)} تی‌پوینت" 🎲 (بازه {fa_num(lo)} تا {fa_num(hi)})')
    sections.append("\n".join(res_lines))
    sections.append(f'⏳ حرکت بعدی بازار: "{fa_dur(left)} دیگر"')
    return "\n\n---\n\n".join(sections)


# ═════════ کیفیت محصول ⭐ ═════════

def roll_quality(q5_bonus: float = 0.0) -> dict:
    """قرعه کیفیت برداشت (فقط برای تجربه)، بونس q5 از لول زمین میاد و شانس ⭐⭐⭐⭐⭐ رو بالا می‌بره (بقیه به‌تناسب کوچیک میشن)"""
    p5 = min(1.0, config.QUALITY_TIERS[-1]["chance"] + q5_bonus)
    scale = (1.0 - p5) / (1.0 - config.QUALITY_TIERS[-1]["chance"])
    r = random.random()
    acc = 0.0
    for t in config.QUALITY_TIERS:
        chance = p5 if t["stars"] == 5 else t["chance"] * scale
        acc += chance
        if r < acc:
            return t
    return config.QUALITY_TIERS[-1]


def quality_stars(tier: dict) -> str:
    return "⭐" * tier["stars"]


# ═════════ جستجو 🔍 ═════════

def search_cooldown_left(user: User) -> int:
    if not user.last_search_at:
        return 0
    cd = config.SEARCH_COOLDOWN_MINUTES * 60
    left = cd - (now_utc() - user.last_search_at).total_seconds()
    return max(0, int(left))


async def do_search(session: AsyncSession, user: User, luck: float = 1.0) -> dict:
    """
    اجرای جستجو، نتیجه کاملاً تصادفی با شانس‌های مستقل
    شانس جستجو: وزن نتایج خوب رو زیاد و دزد رو کم می‌کنه
    خروجی دیکشنری با status: cooldown | money | seed_* | thief
    """
    left = search_cooldown_left(user)
    if left:
        return {"status": "cooldown", "left": left}

    # استخر بذرها با گیت لول فیلتر میشه (درخواست کارفرما):
    # کوکائین لول 3+ | جهنم/ابلیس لول 5+ | جهش‌یافته لول 8+، نتیجه با استخر خالی وزنش صفر میشه
    pools: dict[str, list[str]] = {}
    for o in config.SEARCH_OUTCOMES:
        if "pool" in o:
            pools[o["key"]] = [k for k in o["pool"] if economy.seed_drop_allowed(k, user.level)]

    # وزن‌ها با اثر شانس
    weights = []
    for o in config.SEARCH_OUTCOMES:
        w = o["chance"]
        if "pool" in o and not pools[o["key"]]:
            w = 0.0  # لول برای هیچ بذر این نتیجه کمه، اصلاً نمیفته
        elif o["key"] == "thief" and luck > 1:
            w /= luck
        elif o["key"] != "thief" and luck > 1:
            w *= luck
        weights.append(w)

    outcome = random.choices(config.SEARCH_OUTCOMES, weights=weights, k=1)[0]
    user.last_search_at = now_utc()

    if outcome["key"] == "money":
        amount = random.randint(outcome["min"], outcome["max"])
        user.cash += amount
        from services import tracklog as tl
        await tl.bump_search(session, user.id, amount)  # لاگ ردیابی ادمین
        return {"status": "money", "amount": amount, "outcome": outcome}

    if outcome["key"] == "thief":
        lost = int(user.cash * random.uniform(outcome["pct_min"], outcome["pct_max"]))
        user.cash = max(0, user.cash - lost)
        from services import tracklog as tl
        await tl.bump_search(session, user.id, -lost)  # لاگ ردیابی ادمین، منفی
        return {"status": "thief", "lost": lost, "outcome": outcome}

    # بذرها (انبار پر باشه نمی‌ره توش، درخواست کارفرما راند ۹)
    seed_key = random.choice(pools[outcome["key"]])
    taken = await try_add_seed(session, user, seed_key, 1)
    if not taken:
        return {"status": outcome["key"], "seed": seed_key, "outcome": outcome, "full": True}
    return {"status": outcome["key"], "seed": seed_key, "outcome": outcome}


# ═════════ پناهگاه 🏚 ═════════

def shelter_price(level: int) -> int:
    """هزینه ارتقا به لول level (۱..۱۰)"""
    return config.SHELTER_PRICES[min(max(level, 1), config.SHELTER_MAX_LEVEL) - 1]


def shelter_raid_cut(level: int) -> float:
    """کاهش خسارت یورش، هر لول ۵%"""
    return min(0.9, config.SHELTER_RAID_CUT_PER_LEVEL * level)


def shelter_dodge_chance(level: int) -> float:
    """شانس فرار کامل از یورش، هر لول ۴%"""
    return min(0.5, config.SHELTER_DODGE_PER_LEVEL * level)


def seed_storage_cap(user: User) -> int:
    """ظرفیت انبار هر بذر، پناهگاه بالاتر، محل نگهداری بیشتر"""
    return config.SHELTER_SEED_CAP_BASE + config.SHELTER_SEED_CAP_PER_LEVEL * user.shelter_level


def shelter_upgrade_min_level(target_level: int) -> int:
    """لول بازیکن لازم برای ارتقای پناهگاه به لول target_level (۱..۱۰)"""
    idx = min(max(target_level, 1), config.SHELTER_MAX_LEVEL) - 1
    return config.SHELTER_UPGRADE_MIN_LEVELS[idx]


async def upgrade_shelter(session: AsyncSession, user: User) -> tuple[bool, str]:
    """ارتقای پناهگاه از جیب"""
    if user.shelter_level >= config.SHELTER_MAX_LEVEL:
        return False, "⭐ انبارت مکس لوله"
    next_level = user.shelter_level + 1
    req = shelter_upgrade_min_level(next_level)
    if user.level < req:
        return False, f"🔒 ارتقا به لول {fa_num(next_level)} سطح {fa_num(req)} می‌خواد"
    price = shelter_price(next_level)
    if user.cash < price:
        return False, f"❌ ارتقا {money(price)} هزینه داره و پولت کمه"
    user.cash -= price
    user.shelter_level = next_level
    return True, (
        f"🏚 انبارت رفت رو لول {fa_num(next_level)}\n"
        f"📦 ظرفیت انبار هر بذر {fa_num(seed_storage_cap(user))} تا شد"
    )


# ═════════ یورش پلیس 🚔 ═════════

async def police_wave(session: AsyncSession) -> list[dict]:
    """
    موج یورش، برای هر بازیکن فعال ۲۴ ساعت اخیر که انبار محصول داره
    خروجی: لیست [{user, lost(dict seed→count), dodged}] برای اطلاع‌رسانی
    """
    limit = now_utc() - timedelta(hours=config.POLICE_ACTIVITY_HOURS)
    q = select(User).where(User.last_seen_at >= limit)
    users_ = list((await session.execute(q)).scalars())

    out: list[dict] = []
    for u in users_:
        stock = await get_stock(session, u.id)
        total = sum(stock.values())
        if total <= 0:
            continue
        if random.random() >= config.POLICE_RAID_CHANCE:
            continue

        if u.shelter_level and random.random() < shelter_dodge_chance(u.shelter_level):
            out.append({"user": u, "lost": {}, "dodged": True})
            continue

        cut = shelter_raid_cut(u.shelter_level)
        eff_pct = config.POLICE_DESTROY_PCT * (1 - cut)
        lost: dict[str, int] = {}
        q2 = select(SeedStock).where(SeedStock.user_id == u.id, SeedStock.count > 0)
        for row in (await session.execute(q2)).scalars():
            n = int(row.count * eff_pct + 0.5)
            if n > 0:
                row.count -= n
                lost[row.seed_key] = n
        out.append({"user": u, "lost": lost, "dodged": False})
    return out


def police_report_text(rec: dict) -> str:
    """پیام یورش برای خود بازیکن"""
    u = rec["user"]
    if rec["dodged"]:
        return (
            "<b>🚔 موج پلیس اومد ولی رد شد</b>\n\n"
            "🏚 انبارت کاری کرد که چیزی پیدا نکنن 😮‍💨\n"
            "محله امنه، به کارت ادامه بده"
        )
    lost = rec["lost"]
    total = sum(lost.values())
    lines = ["<b>🚔 یورش پلیس!</b>", ""]
    if total <= 0:
        lines.append("پلیس اومد ولی چیز مهمی گیرش نیومد 😅")
    else:
        lines.append("🚨 مأمورا یه سری از محصولات انبارتو نابود کردن:")
        for k, n in lost.items():
            nm = config.SEEDS.get(k, {}).get("name", k)
            lines.append(f"▫️ {nm} ×{fa_num(n)}")
        if u.shelter_level:
            lines.append("")
            lines.append(f"🏚 بدون انبار لول {fa_num(u.shelter_level)} ضررت بیشتر بود")
        lines.append("💡 انبارتو ارتقا بده تا یورش‌های بعدی کمتر ضرر بزنه")
    return "\n".join(lines)


def search_cooldown_text(left_seconds: float) -> str:
    """متن کولدان جستجو، فقط همون خط کولدان (تبلیغ ته پیام به درخواست کارفرما حذف شد)"""
    return (
        f"⏳ هر {fa_num(config.SEARCH_COOLDOWN_MINUTES)} دقیقه یک بار میتونی جستجو بزنی، {fa_dur(left_seconds)} دیگه برگرد"
    )


# ═════════ کاروان 🚛 (درون حافظه) ═════════

# chat_id → {hp, max_hp, started_at, expires_at, damages: {user_id: dmg}, names: {user_id: name}, message_id}
CARAVANS: dict[int, dict] = {}
# (chat_id, user_id) → last hit datetime
CARAVAN_HITS: dict[tuple[int, int], object] = {}
# (chat_id, user_tg) → آخرین کلیک روی دکمه ضربه، برای دیبانس اسپم
CARAVAN_CLICKS: dict[tuple[int, int], object] = {}


def caravan_click_spam(chat_id: int, user_tg: int) -> bool:
    """کلیک تندتند زیر چند ثانیه اسپمه و بی‌صدا نادیده گرفته میشه (جواب خالی)"""
    key = (chat_id, user_tg)
    now = now_utc()
    last = CARAVAN_CLICKS.get(key)
    CARAVAN_CLICKS[key] = now
    return bool(last and (now - last).total_seconds() < config.CARAVAN_HIT_DEBOUNCE_SECONDS)


def caravan_spawn(chat_id: int) -> dict:
    """اسپون کاروان جدید با HP از تیِرها"""
    hp = random.choice(config.CARAVAN_HP_TIERS)
    cv = {
        "hp": hp,
        "max_hp": hp,
        "expires_at": now_utc() + timedelta(minutes=config.CARAVAN_LIFETIME_MINUTES),
        "damages": {},
        "names": {},
        "message_id": None,
    }
    CARAVANS[chat_id] = cv
    return cv


def caravan_active(chat_id: int) -> dict | None:
    cv = CARAVANS.get(chat_id)
    if cv and cv["expires_at"] > now_utc() and cv["hp"] > 0:
        return cv
    return None


def caravan_hit_left(chat_id: int, user_id: int) -> int:
    """ثانیه مونده از کولدان ضربه (هر ۱ دقیقه)"""
    last = CARAVAN_HITS.get((chat_id, user_id))
    if not last:
        return 0
    left = config.CARAVAN_HIT_COOLDOWN_SECONDS - (now_utc() - last).total_seconds()
    return max(0, int(left))


def caravan_loot_key() -> str:
    """قرعه بذر جایزه نهایی کاروان"""
    r = random.random()
    acc = 0.0
    for loot in config.CARAVAN_LOOT:
        acc += loot["chance"]
        if r < acc:
            return random.choice(loot["pool"])
    return random.choice(config.CARAVAN_LOOT[0]["pool"])


async def caravan_attack(session: AsyncSession, chat_id: int, user: User, dmg: int) -> dict:
    """
    ضربه به کاروان، دمیج = قدرت حمله بازیکن
    هر ضربه جایزه نقدی و XP همون لحظه میده
    خروجی: {status: none|cooldown|hit|killed, ...}
    """
    cv = caravan_active(chat_id)
    if not cv:
        return {"status": "none"}

    left = caravan_hit_left(chat_id, user.id)
    if left:
        return {"status": "cooldown", "left": left}

    CARAVAN_HITS[(chat_id, user.id)] = now_utc()
    dmg = max(1, dmg)
    # دمیج هر ضربه ثابت نیس، حول قدرت حمله بالا‌پایین می‌چرخه
    swing = config.CARAVAN_DMG_VARIANCE
    dmg = max(1, round(dmg * random.uniform(1 - swing, 1 + swing)))
    cv["hp"] -= dmg
    cv["damages"][user.id] = cv["damages"].get(user.id, 0) + dmg
    name = user.first_name or user.username or "؟"
    cv["names"][user.id] = name

    cash_gain = dmg * config.CARAVAN_MONEY_PER_DMG
    user.cash += cash_gain
    notes = add_xp(user, config.CARAVAN_HIT_XP)
    from services import teams as team_svc
    notes += await team_svc.add_team_xp(session, user, config.CARAVAN_HIT_XP)

    res = {
        "status": "hit",
        "dmg": dmg,
        "cash": cash_gain,
        "hp_left": max(0, cv["hp"]),
        "max_hp": cv["max_hp"],
        "notes": notes,
    }

    if cv["hp"] <= 0:
        res["status"] = "killed"
        res["rewards"] = await _caravan_settle(session, chat_id, killed=True)
    return res


async def caravan_expire(session: AsyncSession, chat_id: int) -> dict | None:
    """تایم کاروان تموم شده، اگه فعال بود تسویه جزئی کن"""
    cv = CARAVANS.get(chat_id)
    if not cv or cv["expires_at"] > now_utc() or cv["hp"] <= 0:
        return None
    rewards = await _caravan_settle(session, chat_id, killed=False)
    return {"rewards": rewards}


async def _caravan_settle(session: AsyncSession, chat_id: int, killed: bool) -> list[dict]:
    """
    تسویه کاروان: فقط 5 نفر برتر دمیج جایزه می‌گیرن (اسکناس + جایزه ویژه بذر)
    نفر اول موقع غارت 3 تا جایزه ویژه می‌گیره و پاداش نقدیش 3 برابره
    خروجی: [{user_id, name, dmg, seeds(list[str]), top(bool), money}]
    """
    cv = CARAVANS.pop(chat_id, None)
    if not cv:
        return []

    damages = cv["damages"]
    if not damages:
        return []

    # 💎 جم کاروان: فقط موقع غارت کامل (کشتن کاروان)، به همه ضربه‌زنا بین ۵ تا ۵۰ (راند ۲۷، درخواست کارفرما)
    gem_gains: dict[int, int] = {}
    if killed:
        for uid in damages:
            g = random.randint(config.GEM_DROP_MIN, config.GEM_DROP_MAX)
            gu = await session.get(User, uid)
            if gu is not None:
                gu.gems = (gu.gems or 0) + g
                gem_gains[uid] = g

    ranked = sorted(damages.items(), key=lambda kv: -kv[1])[: config.CARAVAN_TOP_REWARDS]
    out: list[dict] = []
    for idx, (uid, dmg) in enumerate(ranked):
        user = await session.get(User, uid)
        if not user:
            continue
        is_top = idx == 0

        # جایزه ویژه (بذر): غارت کامل رتبه‌بندی ثابت داره (درخواست کارفرما: فقط نفر اول جهنم/ابلیس، حداکثر ۱ بذر)
        if killed:
            if idx == 0:
                plan = [random.choice(["jahannam", "eblis"])]
            elif idx == 2:
                plan = ["cocaine"]
            else:
                plan = [caravan_loot_key()] if random.random() < 0.75 else []
        else:
            plan = ([random.choice(config.CARAVAN_LOOT[0]["pool"])]
                    if (is_top or random.random() < 0.4) else [])

        seed_names: list[str] = []
        full_seeds = 0
        for seed_key in plan:
            taken = await try_add_seed(session, user, seed_key, 1)  # انبار پر بذر رو نمی‌خوره (راند ۹)
            if taken:
                seed_names.append(config.SEEDS[seed_key]["name"])
            else:
                full_seeds += 1

        money_prize = dmg * config.CARAVAN_MONEY_PER_DMG * (3 if (killed and is_top) else 1)
        user.cash += money_prize

        out.append({
            "user_id": uid,
            "name": cv["names"].get(uid, "؟"),
            "dmg": dmg,
            "seeds": seed_names,
            "full_seeds": full_seeds,
            "top": is_top,
            "money": money_prize,
            "gems": gem_gains.get(uid, 0),
        })
    return out


def caravan_board_text(cv: dict) -> str:
    """
    متن برد کاروان برای گروه
    جدول دمیج از همون اول نمایش داده میشه و تایمر فقط پلکان 2 دقیقه‌ای (10-8-6-4-2)
    چون پیام هر 2 دقیقه ادیت میشه، ثانیه نمایش داده نمیشه
    """
    pct = max(0, cv["hp"]) / cv["max_hp"]
    filled = round(pct * 10)
    bar = "🟥" * filled + "⬜" * (10 - filled)
    left = max(0, int((cv["expires_at"] - now_utc()).total_seconds()))
    step = config.CARAVAN_BOARD_REFRESH_SECONDS
    # پلکان 2 دقیقه‌ای: 8 دقیقه و 6 ثانیه → 8 دقیقه، لحظه اسپون → 10 دقیقه
    left_min = max(1, round(left / step)) * (step // 60)

    lines = [
        "<b>🚛 کاروان وارد محله شد</b>",
        "",
        "❤️ جان کاروان",
        bar,
        f"{fa_num(max(0, cv['hp']))} / {fa_num(cv['max_hp'])}",
        "",
        f"⏳ {fa_num(left_min)} دقیقه تا خروج کاروان",
        "",
        f"🔄 این پیام هر {fa_num(step // 60)} دقیقه به‌روزرسانی میشه",
        "",
        "⚔️ هر بازیکن هر 1 دقیقه فقط یک بار می‌تونه حمله کنه",
        "💥 قدرت هر ضربه بر اساس قدرت حمله بازیکنه",
        f"🏆 فقط {fa_num(config.CARAVAN_TOP_REWARDS)} نفر برتر جایزه می‌گیرن",
        "",
        "📊 جدول دمیج",
    ]
    top = sorted(cv["damages"].items(), key=lambda kv: -kv[1])[: config.CARAVAN_TOP_REWARDS]
    if not top:
        lines.append("▫️ هنوز کسی به کاروان حمله نکرده")
        lines.append("اولین نفری باش که ضربه می‌زنه")
    else:
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, dmg) in enumerate(top):
            medal = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"{medal} {esc(str(cv['names'].get(uid, '؟')))}، {fa_num(dmg)} دمیج")
    return "\n".join(lines)


def caravan_result_text(cv: dict, res: dict) -> str:
    """متن نتیجه ضربه"""
    lines = [f"<b>⚔️ {fa_num(res['dmg'])} دمیج به کاروان</b>", ""]
    lines.append(f"💰 جایزه ضربه {money(res['cash'])} | ❤️ مونده {fa_num(res['hp_left'])}")
    if res["status"] == "killed":
        lines.append("")
        lines.append("💀 کاروان افتاد! جایزه‌ها تقسیم شد")
    return "\n".join(lines)


def caravan_end_text(rewards: list[dict], killed: bool) -> str:
    """متن پایان کاروان (غارت شده یا رد شده)، هر نفر: اسم/دمیج/پاداش/جایزه ویژه، فقط 5 نفر برتر"""
    if not rewards:
        return "<b>🚛 کاروان از محله رد شد</b>\n\nبدون اینکه کسی بهش برسه رفت 💨"
    head = "<b>💀 کاروان غارت شد</b>" if killed else "<b>🚛 کاروان از محله رد شد</b>"
    lines = [head, ""]
    for r in rewards:
        prize = "، ".join(r["seeds"]) if r["seeds"] else "هیچی"
        lines.append(f"{'🏆' if r['top'] else '▫️'} {esc(str(r['name']))}")
        lines.append(f"⚔️ دمیج: {fa_num(r['dmg'])}")
        lines.append(f"💰 پاداش: {fa_num(r['money'])}TP")
        lines.append(f"🎁 جایزه ویژه: {prize}")
        if r.get("gems"):
            lines.append(f"💎 جم: {fa_num(r['gems'])}")
        if r.get("full_seeds"):
            lines.append(f"🌾 انبار بذرت پر بود و {fa_num(r['full_seeds'])} بذر افتاد زمین 😖")
    lines.append("")
    if killed and rewards[0]["top"]:
        lines.append(f"🏆 نفر اول {esc(str(rewards[0]['name']))} بیشترین جایزه رو گرفت")
    lines.append(f"📢 فقط {fa_num(config.CARAVAN_TOP_REWARDS)} نفر برتر جایزه دریافت می‌کنن")
    return "\n".join(lines)
