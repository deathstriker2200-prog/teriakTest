"""
انبار محصول 🎒 | ارسال محموله 📦 | کاروان قاچاق 🚚

بعد برداشت، محصول پول نمیشه و اول میاد تو انبار محصول (ProductStock)
بازیکن خودش تصمیم می‌گیره کی بفروشه: یا با محموله (زمان + ریسک توقیف) یا به کاروان قاچاق (فوری و گرون‌تر)
کاروان قاچاق هر چند ساعت یه بار خودکار میاد و یه محصول رو با بونس می‌خره
"""

import json
import random
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import GameMeta, ProductStock, Shipment, User
from utils import esc, fa_dur, fa_num, money, now_utc


# ═════════ انبار محصول 🌾 ═════════

def products_cap(shelter_level: int) -> int:
    """ظرفیت انبار برای هر محصول (مثل ظرفیت بذر و منابع): لول 1 از 10 تا شروع میشه و با هر لول بیشتر میشه"""
    return config.PRODUCT_CAP_PER_LEVEL * max(1, shelter_level or 0)


async def add_product(session: AsyncSession, user_id: int, crop: str, qty: int, value: int,
                      shelter_level: int = 0) -> tuple[int, int]:
    """
    اضافه کردن محصول به انبار با گیت ظرفیت هر محصول
    ارزش موقع برداشت روی هم جمع میشه و با تعدادش تناسب داره (کامیت با صدا‌کننده‌ست)
    خروجی: (تعداد اضافه‌شده, ارزش اضافه‌شده)، سرریز ظرفیت از بین میره و برنمی‌گرده
    """
    q = select(ProductStock).where(ProductStock.user_id == user_id, ProductStock.crop == crop)
    row = (await session.execute(q)).scalar_one_or_none()
    have = row.qty if row else 0
    room = max(0, products_cap(shelter_level) - have)
    added = min(qty, room)
    added_val = int(value * added / qty) if qty and added else 0
    if added:
        if row:
            row.qty += added
            row.value += added_val
        else:
            session.add(ProductStock(user_id=user_id, crop=crop, qty=added, value=added_val))
    return added, added_val


async def get_products(session: AsyncSession, user_id: int) -> dict[str, ProductStock]:
    """محصولات انبار کاربر به شکل دیکشنری: crop → ردیف"""
    q = select(ProductStock).where(ProductStock.user_id == user_id, ProductStock.qty > 0)
    return {row.crop: row for row in (await session.execute(q)).scalars()}


async def products_count(session: AsyncSession, user_id: int) -> int:
    """تعداد کل واحدهای محصول تو انبار (برای نمایش خلاصه)"""
    rows = await get_products(session, user_id)
    return sum(r.qty for r in rows.values())


def _take_value(row: ProductStock, qty: int) -> int:
    """ارزش تناسبی qty تا از ردیف انبار، و کم شدنش از ردیف (ردیف خالی پاک میشه نه اینجا)"""
    if qty >= row.qty:
        val = row.value
    else:
        val = int(row.value * qty / row.qty)
    row.value -= val
    row.qty -= qty
    return val


async def take_product(session: AsyncSession, user_id: int, crop: str, qty: int) -> int | None:
    """
    qty واحد محصول از انبار برمی‌داره و ارزش تناسبیش رو برمی‌گردونه
    موجودی ناکافی یا نبودن محصول → None
    """
    if qty <= 0:
        return None
    q = select(ProductStock).where(ProductStock.user_id == user_id, ProductStock.crop == crop)
    row = (await session.execute(q)).scalar_one_or_none()
    if not row or row.qty < qty:
        return None
    val = _take_value(row, qty)
    if row.qty <= 0:
        await session.delete(row)
    return val


# ═════════ ارسال محموله 📦 ═════════

def shipment_seconds() -> int:
    """زمان تحویل هر محموله (راند ۳۱، درخواست کارفرما): کاروان ساده و یکدست، ثابت و برابر برای همه"""
    return config.CARAVAN_BASE_SECONDS


def roll_outcome() -> str:
    """قرعه سرنوشت محموله موقع ارسال: clean | police | delayed"""
    r = random.random()
    if r < config.SHIPMENT_POLICE_CHANCE:
        return "police"
    if r < config.SHIPMENT_POLICE_CHANCE + config.SHIPMENT_DELAY_CHANCE:
        return "delayed"
    return "clean"


def roll_seize_pct() -> int:
    """درصد ضبط پلیس از ارزش محموله (راند ۲۲): ده‌دهی 20 تا 80 با وزن‌های زنگوله‌ای کانفیگ"""
    pcts, weights = zip(*config.SHIPMENT_POLICE_SEIZE_TABLE)
    return random.choices(pcts, weights=weights, k=1)[0]


async def active_shipments(session: AsyncSession, user_id: int) -> list[Shipment]:
    q = (select(Shipment).where(Shipment.user_id == user_id)
         .order_by(Shipment.deliver_at))
    return list((await session.execute(q)).scalars())


def shipment_confirm_text(crop: str, qty: int, value: int, mult: float = 1.0) -> str:
    """کارت تایید ارسال محموله (راند ۳۱: کاروان ساده شد، زمان ثابت ۲۰ دقیقه)
    راند ۳۵: mult<1 یعنی لقب چاپلوس فعاله و درصدش از فروش کم میشه، اینجا هم خبرش میاد"""
    sd = config.SEEDS[crop]
    emoji = sd.get("emoji", "🌱")  # بذرهای افسانه‌ای ایموجی رشته‌ای ندارن، ایموجی تو اسمشونه
    return "\n".join([
        "<b>📦 ارسال محموله</b>",
        "",
        f"{emoji} {sd['name']} ×{fa_num(qty)}",
        "",
        "💰 ارزش محموله",
        money(value),
        *( [f"🏷 لقب چاپلوس: {fa_num(int(config.KHAYE_SELL_MALUS * 100))}% از فروشت کم میشه"] if mult < 1.0 else [] ),
        "",
        "⏱ زمان ارسال",
        fa_dur(shipment_seconds()),
        "",
        f"🚔 احتمال توقیف توسط پلیس: {fa_num(int(config.SHIPMENT_POLICE_CHANCE * 100))}%",
        "",
        "بعد رسیدن محموله پولش رو می‌گیری",
        "یه احتمال کم هم هست راننده مسیر رو عوض کنه و محموله با تأخیر برسه",
    ])


async def send_shipment(session: AsyncSession, user: User, crop: str, qty: int,
                        chat_id: int | None = None) -> tuple[bool, str, Shipment | None]:
    """ثبت ارسال محموله: محصول از انبار کم میشه و سرنوشت محموله همینجا رول میشه
    chat_id چتیه که ارسال از توش انجام شده و خبر رسیدن همونجا میره (راند ۱۳، درخواست کارفرما)"""
    if crop not in config.SEEDS:
        return False, "❌ همچین محصولی نیس", None
    ongoing = await active_shipments(session, user.id)
    if len(ongoing) >= config.SHIPMENT_MAX_ACTIVE:  # راند ۳۱: سقف ثابت ۵ محموله هم‌زمان برای همه
        return False, (
            f"🚚 هر {fa_num(config.SHIPMENT_MAX_ACTIVE)} محموله‌ات تو راهن\n"
            "تا یدونه برسه نمی‌تونی محموله جدید بفرستی"
        ), None
    value = await take_product(session, user.id, crop, qty)
    if value is None:
        sd = config.SEEDS[crop]
        return False, f"📦 {fa_num(qty)} تا {sd['name']} تو انبارت نداری", None

    outcome = roll_outcome()
    seize = roll_seize_pct() if outcome == "police" else None
    pay = value if seize is None else value - round(value * seize / 100)
    from services.snitch import sell_mult  # راند ۳۵: لقب چاپلوس، فروش کمتر دله میشه
    _mult = sell_mult(user)
    if _mult < 1.0:
        pay = round(pay * _mult)
    sh = Shipment(
        user_id=user.id, crop=crop, qty=qty, value=value, pay=pay,
        outcome=outcome, hops=0, chat_id=chat_id, seize_pct=seize,
        deliver_at=now_utc() + timedelta(seconds=shipment_seconds()),
    )
    session.add(sh)
    return True, "🚚 محموله راه افتاد", sh


def shipment_line(sh: Shipment) -> str:
    """خط وضعیت یه محموله در راه برای صفحه محصولات"""
    sd = config.SEEDS.get(sh.crop, {})
    left = max(0, int((sh.deliver_at - now_utc()).total_seconds()))
    late = " | 🚛 مسیر عوض شده" if sh.hops else ""
    return f"▫️ {sd.get('emoji', '📦')} {sd.get('name', sh.crop)} ×{fa_num(sh.qty)} | ⏱ {fa_dur(left)} مونده{late}"


async def process_due_shipments(session: AsyncSession) -> list[dict]:
    """
    تسویه محموله‌های رسیده (تغییر مسیر اول پیام میده و یه دور تازه می‌چرخونه)
    فروش واقعی موقع رسیدن تو عرضه بازار ثبت میشه (کامیت با صدا‌کننده‌ست)
    خروجی: [{tg, text}] برای اطلاع‌رسانی پی‌وی
    """
    from services import world as world_svc
    q = select(Shipment).where(Shipment.deliver_at <= now_utc())
    due = list((await session.execute(q)).scalars())
    out: list[dict] = []
    for sh in due:
        user = await session.get(User, sh.user_id)
        if not user:
            await session.delete(sh)
            continue
        # منتشن لینک‌دار صاحب محموله (راند ۲۰، درخواست کارفرما)
        from services import users as users_svc
        men = f'<a href="tg://user?id={user.telegram_id}">{esc(users_svc.display_name(user))}</a>'

        sd = config.SEEDS.get(sh.crop, {})
        name = sd.get("name", sh.crop)
        emoji = sd.get("emoji", "📦")

        if sh.outcome == "delayed" and not sh.hops:
            sh.hops = 1
            sh.deliver_at = now_utc() + timedelta(seconds=shipment_seconds())
            out.append({
                "tg": user.telegram_id,
                "chat": sh.chat_id or user.telegram_id,  # خبر همونجا میره که کامیون راه افتاد (راند ۱۳)
                "text": (
                    "<b>🚛 راننده مسیر رو عوض کرد</b>\n\n"
                    f"⏱ محموله {emoji} {name} ×{fa_num(sh.qty)}\n"
                    f"با تأخیر میرسه، {fa_dur(shipment_seconds())} دیگه"
                ),
            })
            continue

        # راند ۳۱ (درخواست کارفرما): غارت محموله حذف شد، پرداخت کامل و بدون دخل‌تصرفه
        user.cash += sh.pay
        from services import tracklog as tl
        await tl.bump_sell(session, sh.user_id, {sh.crop: (sh.qty, sh.pay)})  # لاگ ردیابی ادمین
        await world_svc.record_sale(session, sh.crop, sh.qty)  # عرضه واقعی بازار پویا
        await session.delete(sh)
        if sh.outcome == "police":
            seized = sh.seize_pct or 50
            text = (
                f"<b>🚔 پلیس {fa_num(seized)}% ارزش محموله رو ضبط کرد</b>\n\n"
            f"👤 {men}\n"
                f"{emoji} {name} ×{fa_num(sh.qty)}\n"
                f"💰 فقط {fa_num(100 - seized)}% ارزش محموله پرداخت شد\n\n"
                f"💵 {money(sh.pay)} گرفتی"
            )
        elif sh.outcome == "delayed":
            text = (
                "<b>✅ محموله با تأخیر رسید</b>\n\n"
            f"👤 {men}\n"
                f"🚛 راننده مسیر رو عوض کرده بود ولی تحویل داده شد\n"
                f"{emoji} {name} ×{fa_num(sh.qty)} تحویل داده شد\n\n"
                f"💵 {money(sh.pay)} گرفتی"
            )
        else:
            text = (
                "<b>✅ محموله سالم رسید</b>\n\n"
            f"👤 {men}\n"
                f"{emoji} {name} ×{fa_num(sh.qty)} تحویل داده شد\n\n"
                f"💵 {money(sh.pay)} گرفتی"
            )
        out.append({"tg": user.telegram_id, "chat": sh.chat_id or user.telegram_id, "text": text})
    return out


# ═════════ کاروان قاچاق 🚚 ═════════
# state سراسری رو game_meta (با ری‌استارت می‌مونه): crop + bonus + until + پیام‌های اعلان

async def _meta(session: AsyncSession, key: str) -> str | None:
    row = await session.get(GameMeta, key)
    return row.value if row else None


async def _meta_set(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(GameMeta, key)
    if row:
        row.value = value
    else:
        session.add(GameMeta(key=key, value=value))


def _parse_cv(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict) or d.get("crop") not in config.SEEDS:
        return None
    return d


def cv_left(cv: dict) -> int:
    """ثانیه مونده از حضور کاروان"""
    from datetime import datetime as _dt
    try:
        until = _dt.fromisoformat(cv["until"])
    except (KeyError, ValueError):
        return 0
    return max(0, int((until - now_utc()).total_seconds()))


async def get_caravan(session: AsyncSession) -> dict | None:
    """کاروان فعال قاچاق رو بگیر، منقضی‌شده همینجا پاک میشه"""
    cv = _parse_cv(await _meta(session, "smuggler"))
    if not cv:
        return None
    if cv_left(cv) <= 0:
        await _meta_set(session, "smuggler", "")
        return None
    return cv


async def spawn_caravan(session: AsyncSession, crop: str | None = None, bonus: int | None = None) -> dict | None:
    """
    اسپون کاروان قاچاق (خودکار یا دستی ادمین)
    crop=None یعنی شانسی از استخر خودکار | bonus=None یعنی شانسی تو بازه کانفیگ
    کاروان فعال باشه اسپون جدید نمیاد
    """
    if await get_caravan(session):
        return None
    crop = crop if crop in config.SEEDS else random.choice(config.SMUGGLER_CROPS)
    if bonus is None:
        bonus = random.randint(config.SMUGGLER_BONUS_MIN, config.SMUGGLER_BONUS_MAX)
    cv = {
        "crop": crop,
        "bonus": int(bonus),
        "until": (now_utc() + timedelta(minutes=config.SMUGGLER_LIFETIME_MINUTES)).isoformat(),
    }
    await _meta_set(session, "smuggler", json.dumps(cv, ensure_ascii=False))
    await _meta_set(session, "smuggler_last", now_utc().isoformat())
    await _meta_set(session, "smuggler_msgs", "[]")
    return cv


async def caravan_tick(session: AsyncSession) -> tuple[dict | None, dict | None]:
    """
    جاب دوره‌ای کاروان قاچاق
    خروجی: (کاروان تازه اسپون‌شده, کاروانی که همین لحظه منقضی شد)
    """
    cv = _parse_cv(await _meta(session, "smuggler"))
    expired: dict | None = None
    if cv and cv_left(cv) <= 0:
        expired = cv
        try:
            msgs = json.loads(await _meta(session, "smuggler_msgs") or "[]")
        except (ValueError, TypeError):
            msgs = []
        expired["msgs"] = msgs if isinstance(msgs, list) else []
        await _meta_set(session, "smuggler", "")
        cv = None
    if cv:
        return None, None

    last_raw = await _meta(session, "smuggler_last")
    from datetime import datetime as _dt
    try:
        last = _dt.fromisoformat(last_raw) if last_raw else None
    except ValueError:
        last = None
    due = last is None or (now_utc() - last) >= timedelta(hours=config.SMUGGLER_INTERVAL_HOURS)
    if not due:
        return None, expired
    spawned = await spawn_caravan(session)
    return spawned, expired


async def note_caravan_message(session: AsyncSession, chat_id: int, message_id: int) -> None:
    """پیام اعلان کاروان رو لیست کن تا موقع رفتن ادیت بشه (کامیت با صدا‌کننده‌ست)"""
    try:
        msgs = json.loads(await _meta(session, "smuggler_msgs") or "[]")
    except (ValueError, TypeError):
        msgs = []
    msgs.append([int(chat_id), int(message_id)])
    await _meta_set(session, "smuggler_msgs", json.dumps(msgs[-200:]))


async def pop_caravan_messages(session: AsyncSession) -> list[list[int]]:
    """لیست پیام‌های اعلان کاروان رو بده و پاک کن، برای ادیت «کاروان رفت»"""
    try:
        msgs = json.loads(await _meta(session, "smuggler_msgs") or "[]")
    except (ValueError, TypeError):
        msgs = []
    await _meta_set(session, "smuggler_msgs", "[]")
    return msgs if isinstance(msgs, list) else []


def caravan_announce_text(cv: dict) -> str:
    """اعلان رسیدن کاروان به گروه‌ها، قالب درخواستی کارفرما"""
    sd = config.SEEDS[cv["crop"]]
    emoji = sd.get("emoji", "🌱")
    return "\n".join([
        "<b>🚚 کاروان قاچاق رسید</b>",
        "",
        "⏳ مدت حضور",
        fa_dur(config.SMUGGLER_LIFETIME_MINUTES * 60),
        "",
        f"{emoji} محصول موردنیاز",
        sd["name"],
        "",
        "📈 قیمت خرید",
        f"{fa_num(cv['bonus'])}% بیشتر از قیمت بازار",
        "",
        "تو مدت حضورش می‌تونی محصول رو از انبارت بهش بفروشی",
        "پی‌وی ربات ← 🎒 انبار ← 🚚 کاروان قاچاق",
    ])


def caravan_gone_text(cv: dict) -> str:
    """ادیت پیام اعلان بعد از رفتن کاروان"""
    sd = config.SEEDS.get(cv.get("crop", ""), {})
    return (
        "<b>🚚 کاروان قاچاق حرکت کرد</b>\n\n"
        f"مشتری {sd.get('emoji', '📦')} {sd.get('name', 'محصول')} جمع کرد و رفت 💨\n"
        "کاروان بعدی چند ساعت دیگه سر می‌زنه"
    )


def caravan_page_text(cv: dict | None, have: int, unit_price: int, cash: int, mult: float = 1.0) -> str:
    """صفحه کاروان قاچاق تو انبار (راند ۳۵: mult<1 یعنی چاپلوس، قیمت نمایشی و دریافتی کمتره)"""
    if not cv:
        return "\n".join([
            "<b>🚚 کاروان قاچاق</b>",
            "",
            "فعلاً کاروانی تو محله نیس",
            f"هر {fa_num(config.SMUGGLER_INTERVAL_HOURS)} ساعت یه بار یه کاروان سر می‌زنه",
            "و یه محصول رو گرون‌تر از بازار می‌خره",
            "",
            "رسیدنش تو گروه‌های فعال اعلام میشه 📢",
        ])
    sd = config.SEEDS[cv["crop"]]
    emoji = sd.get("emoji", "🌱")
    price = round(unit_price * (1 + cv["bonus"] / 100) * mult) if unit_price else 0
    lines = [
        "<b>🚚 کاروان قاچاق</b>",
        "",
        f"⏳ {fa_dur(cv_left(cv))} دیگه جمع می‌کنه میره",
        f"{emoji} محصول موردنیاز: {sd['name']}",
        f"📈 قیمت خرید {fa_num(cv['bonus'])}% بیشتر",
        "",
    ]
    if have > 0:
        lines += [
            f"📦 تو انبارت {fa_num(have)} تا {sd['name']} داری",
            f"💰 قیمت کاروان برای هر دونه: {money(price)}",
            *( [f"🏷 لقب چاپلوس: {fa_num(int(config.KHAYE_SELL_MALUS * 100))}% از فروشت کم میشه"] if mult < 1.0 else [] ),
            "",
            "چقدر بفروشیم؟",
        ]
    else:
        lines += [
            f"📦 هیچ {sd['name']}ی تو انبارت نداری",
            "بذرش رو بکار تا برداشت بعد بتونی به کاروان بفروشی",
        ]
    lines.append("")
    lines.append(f"💵 نقدینگی: {money(cash)}")
    return "\n".join(lines)


def caravan_confirm_text(cv: dict, qty: int, gain: int) -> str:
    """کارت تایید فروش به کاروان"""
    sd = config.SEEDS[cv["crop"]]
    emoji = sd.get("emoji", "🌱")
    return "\n".join([
        "<b>🚚 فروش به کاروان قاچاق</b>",
        "",
        f"{emoji} {sd['name']} ×{fa_num(qty)}",
        "",
        "💰 دریافتی",
        money(gain),
        "",
        f"📈 با بونس {fa_num(cv['bonus'])}% کاروان",
        "فوری و سالم، بدون ریسک توقیف",
        "",
        "معامله‌ست؟",
    ])


async def sell_to_caravan(session: AsyncSession, user: User, qty: int) -> tuple[bool, str, int]:
    """
    فروش فوری محصول به کاروان قاچاق (بدون زمان ارسال و توقیف)
    فروش واقعی همون لحظه تو عرضه بازار ثبت میشه
    خروجی: (موفق, پیام, سود)
    """
    from services import world as world_svc
    cv = await get_caravan(session)
    if not cv:
        return False, "🚚 کاروان جمع کرد و رفت", 0
    sd = config.SEEDS[cv["crop"]]
    value = await take_product(session, user.id, cv["crop"], qty)
    if value is None:
        return False, f"📦 {fa_num(qty)} تا {sd['name']} تو انبارت نداری", 0
    gain = round(value * (1 + cv["bonus"] / 100))
    from services.snitch import sell_mult  # راند ۳۵: لقب چاپلوس، فروش کمتر دله میشه
    _mult = sell_mult(user)
    if _mult < 1.0:
        gain = round(gain * _mult)
    user.cash += gain
    from services import tracklog as tl
    await tl.bump_sell(session, user.id, {cv["crop"]: (qty, gain)})  # لاگ ردیابی ادمین
    await world_svc.record_sale(session, cv["crop"], qty)  # عرضه واقعی بازار پویا
    msg = (
        f"💰 {money(gain)} از کاروان گرفتی\n"
        f"{sd['emoji']} {fa_num(qty)} تا {sd['name']} با بونس {fa_num(cv['bonus'])}% فروختی"
    )
    if _mult < 1.0:
        msg += f"\n🏷 لقب چاپلوس: {fa_num(int(config.KHAYE_SELL_MALUS * 100))}% از فروش کم شد"
    return True, msg, gain


async def caravan_unit_value(session: AsyncSession, user_id: int, crop: str) -> int:
    """ارزش هر دونه محصول فعلی کاربر تو انبار (میانگین ردیف)، برای نمایش قیمت کاروان"""
    q = select(ProductStock).where(ProductStock.user_id == user_id, ProductStock.crop == crop)
    row = (await session.execute(q)).scalar_one_or_none()
    if not row or row.qty <= 0:
        return 0
    return int(row.value / row.qty)


def caravan_estimate(session_rows: dict[str, ProductStock], crop: str, bonus: int) -> int:
    """برآورد قیمت کاروان برای هر دونه از روی ردیف انبار، فقط برای نمایش"""
    row = session_rows.get(crop)
    if not row or row.qty <= 0:
        return 0
    return round(row.value / row.qty * (1 + bonus / 100))

