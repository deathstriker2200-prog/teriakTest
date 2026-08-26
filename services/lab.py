"""
🧪 آزمایشگاه (راند ۴۳، درخواست کارفرما)

باز میشه از لول بازیکن ۱۵، بدون هیچ پیش‌نیاز جانبی — همون داخل صفحه لول ۱ میشه
۴ لول ارتقا (لول بازیکن ۲۰/۲۵/۳۰) | ۴ نوع کارگر | ۷ محصول با unlock مرحله‌ای | ۴ ماده اولیه (فقط Resource، بدون فرمول واقعی)

تولید کاملاً روی ستون busy_until هر کارگر زمان‌بندی میشه، ربطی به آنلاین بودن کاربر یا باز بودن صفحه نداره
همه قیمت‌ها و اعداد فقط تو config.py (LAB_*) و از اونجا قابل تنظیمن، اینجا هیچ عدد هاردکدی نیست
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import LabMaterial, LabProduct, LabWorker, Shipment, User
from utils import fa_dur, fa_num, money, now_utc

SEP = "━━━━━━━━━━━━━━"


# ───────── دسترسی پایه ─────────

def lab_locked(user: User) -> bool:
    return (getattr(user, "level", None) or 1) < config.LAB_MIN_LEVEL


def lab_level(user: User) -> int:
    return int(getattr(user, "lab_level", 0) or 0)


def lab_active(user: User) -> bool:
    """آزمایشگاه یعنی حداقل یه بار ساخته/باز شده (لول ۱+)"""
    return lab_level(user) >= 1


def _cap_for_level(table: list[int], level: int) -> int:
    idx = min(max(int(level or 1), 1), len(table)) - 1
    return int(table[idx])


def material_cap(user: User) -> int:
    """ظرفیت هر نوع ماده اولیه، متناسب با لول آزمایشگاه."""
    return _cap_for_level(config.LAB_MATERIAL_CAP_BY_LEVEL, lab_level(user) or 1)


def warehouse_cap(user: User) -> int:
    """ظرفیت هر نوع محصول در انبار داخلی آزمایشگاه."""
    return _cap_for_level(config.LAB_WAREHOUSE_CAP_BY_LEVEL, lab_level(user) or 1)


# ───────── انبار مواد اولیه ─────────

async def get_materials(session: AsyncSession, user_id: int) -> dict[str, int]:
    q = select(LabMaterial).where(LabMaterial.user_id == user_id)
    return {row.material_key: row.count for row in (await session.execute(q)).scalars()}


async def add_material(session: AsyncSession, user_id: int, material_key: str, amount: int) -> int:
    """واریز ماده اولیه با سقف متناسب با لول آزمایشگاه، خروجی مقدار واقعی واریزشده."""
    if amount <= 0 or material_key not in config.LAB_MATERIALS:
        return 0
    user = await session.get(User, user_id)
    if user is None:
        return 0
    q = select(LabMaterial).where(LabMaterial.user_id == user_id, LabMaterial.material_key == material_key)
    row = (await session.execute(q)).scalar_one_or_none()
    cur = row.count if row else 0
    got = max(0, min(amount, material_cap(user) - cur))
    if got <= 0:
        return 0
    if row:
        row.count += got
    else:
        session.add(LabMaterial(user_id=user_id, material_key=material_key, count=got))
    return got


async def _take_materials(session: AsyncSession, user_id: int, need: dict[str, int]) -> bool:
    """کم‌کردن چند ماده اولیه با هم، فقط وقتی همه‌شون کافی باشن (atomic)"""
    stock = await get_materials(session, user_id)
    if any(stock.get(k, 0) < v for k, v in need.items()):
        return False
    q = select(LabMaterial).where(LabMaterial.user_id == user_id, LabMaterial.material_key.in_(list(need)))
    rows = {r.material_key: r for r in (await session.execute(q)).scalars()}
    for k, v in need.items():
        rows[k].count -= v
    return True


def material_room(user: User, material_key: str, stock: dict[str, int]) -> int:
    return max(0, material_cap(user) - stock.get(material_key, 0))


async def purchase_material(session: AsyncSession, user: User, material_key: str, qty: int) -> tuple[bool, str]:
    """خرید دونه‌ای ماده اولیه از بخش شاپ، مثل خرید دونه‌ای چوب/آهن"""
    info = config.LAB_MATERIALS.get(material_key)
    if not info:
        return False, "❌ همچین جنسی نیس"
    qty = int(qty)
    if qty < 1:
        return False, "❌ تعداد باید حداقل ۱ باشه"
    total = info["unit"] * qty
    stock = await get_materials(session, user.id)
    free = material_room(user, material_key, stock)
    if qty > free:
        return False, (
            "❌ توی انبار آزمایشگاهت جای خالی برای اینهمه نداری\n"
            f"فقط جای {fa_num(free)} تا {info['name']} دیگه داره"
        )
    if user.cash < total:
        return False, f"❌ تی‌پوینتت کافی نیس، {money(total)} می‌خواد"
    user.cash -= total
    await add_material(session, user.id, material_key, qty)
    return True, f"✅ {fa_num(qty)} تا {info['emoji']} {info['name']} خریدی"


# ───────── انبار محصول تولیدشده ─────────

async def get_products(session: AsyncSession, user_id: int) -> dict[str, int]:
    q = select(LabProduct).where(LabProduct.user_id == user_id)
    return {row.product_key: row.count for row in (await session.execute(q)).scalars()}


async def add_product(session: AsyncSession, user_id: int, product_key: str, amount: int) -> int:
    """واریز محصول به انبار داخلی آزمایشگاه، بدون ردکردن سقف لول فعلی."""
    if amount <= 0 or product_key not in config.LAB_PRODUCTS:
        return 0
    user = await session.get(User, user_id)
    if user is None:
        return 0
    q = select(LabProduct).where(LabProduct.user_id == user_id, LabProduct.product_key == product_key)
    row = (await session.execute(q)).scalar_one_or_none()
    cur = row.count if row else 0
    got = max(0, min(amount, warehouse_cap(user) - cur))
    if got <= 0:
        return 0
    if row:
        row.count += got
    else:
        session.add(LabProduct(user_id=user_id, product_key=product_key, count=got))
    return got


async def product_room(session: AsyncSession, user: User, product_key: str, reserve_jobs: bool = False) -> int:
    """جای خالی محصول؛ reserve_jobs خروجی تولیدهای درراه هم رزرو حساب می‌کنه."""
    stock = await get_products(session, user.id)
    used = stock.get(product_key, 0)
    if reserve_jobs:
        workers = await get_workers(session, user.id)
        used += sum((w.job_output or 0) for w in workers if w.busy_until and w.job_product == product_key)
    return max(0, warehouse_cap(user) - used)


async def sell_product(session: AsyncSession, user: User, product_key: str, amount: int) -> tuple[bool, str, int]:
    """فروش مستقیم حذف شده؛ محصولات آزمایشگاه فقط با محموله نقد میشن."""
    return False, "📦 فروش مستقیم آزمایشگاه غیرفعاله؛ محصول رو با ارسال محموله بفرست", 0


def shipment_key(product_key: str) -> str:
    return f"lab_{product_key}"


def shipment_product_key(crop: str) -> str | None:
    if not crop.startswith("lab_"):
        return None
    key = crop[4:]
    return key if key in config.LAB_PRODUCTS else None


async def send_product_shipment(
    session: AsyncSession, user: User, product_key: str, amount: int,
    chat_id: int | None = None,
) -> tuple[bool, str, Shipment | None]:
    """محصول انبار داخلی آزمایشگاه را با همان سیستم محموله و ریسک پلیس ارسال می‌کند."""
    cfg = config.LAB_PRODUCTS.get(product_key)
    if not cfg:
        return False, "❌ همچین محصولی نیست", None
    amount = int(amount)
    if amount <= 0:
        return False, "❌ تعدادشو درست بگو", None

    from services import smuggle as smg
    ongoing = await smg.active_shipments(session, user.id)
    if len(ongoing) >= config.SHIPMENT_MAX_ACTIVE:
        return False, f"🚚 هر {fa_num(config.SHIPMENT_MAX_ACTIVE)} محموله‌ات تو راهن؛ اول صبر کن یکی برسه", None

    q = (select(LabProduct)
         .where(LabProduct.user_id == user.id, LabProduct.product_key == product_key)
         .with_for_update())
    row = (await session.execute(q)).scalar_one_or_none()
    if not row or row.count < amount:
        return False, f"📦 {fa_num(amount)} تا {cfg['name']} تو انبار آزمایشگاه نداری", None

    value = amount * cfg["sell"]
    outcome = smg.roll_outcome()
    seize = smg.roll_seize_pct() if outcome == "police" else None
    pay = value if seize is None else value - round(value * seize / 100)
    from services.snitch import sell_mult
    pay = round(pay * sell_mult(user))

    row.count -= amount
    sh = Shipment(
        user_id=user.id, crop=shipment_key(product_key), qty=amount,
        value=value, pay=pay, outcome=outcome, hops=0,
        chat_id=chat_id, seize_pct=seize,
        deliver_at=now_utc() + timedelta(seconds=smg.shipment_seconds()),
    )
    session.add(sh)
    return True, "🚚 محموله آزمایشگاه راه افتاد", sh


# ───────── ارتقای آزمایشگاه ─────────

def lab_upgrade_min_level(to_level: int) -> int:
    """حداقل لول بازیکن برای رسیدن آزمایشگاه به to_level (۲..۴)"""
    idx = min(max(to_level - 2, 0), len(config.LAB_UPGRADE_MIN_LEVELS) - 1)
    return config.LAB_UPGRADE_MIN_LEVELS[idx]


def lab_upgrade_cost(to_level: int) -> tuple[int, dict[str, int]]:
    idx = min(max(to_level - 2, 0), len(config.LAB_UPGRADE_COST) - 1)
    return config.LAB_UPGRADE_COST[idx]


async def build_lab(session: AsyncSession, user: User) -> tuple[bool, str]:
    """ساخت اولیه‌ی آزمایشگاه (لول ۰ → ۱)، بدون هیچ هزینه یا پیش‌نیاز جانبی، فقط لول بازیکن ۱۵ می‌خواد"""
    if lab_locked(user):
        return False, f"🔒 آزمایشگاه از لول {fa_num(config.LAB_MIN_LEVEL)} باز میشه، فعلا لولت کمه"
    if lab_active(user):
        return False, "🧪 آزمایشگاهت از قبل ساخته شده"
    user.lab_level = 1
    return True, "🧪 آزمایشگاهت ساخته شد! حالا یه کارگر استخدام کن و تولید رو شروع کن"


async def upgrade_lab(session: AsyncSession, user: User) -> tuple[bool, str]:
    if lab_locked(user) and lab_active(user):
        return False, f"🔒 آزمایشگاهت تا لول {fa_num(config.LAB_MIN_LEVEL)} قفله، لولت که رسید خودش باز میشه"
    if not lab_active(user):
        return False, "🧪 اول باید آزمایشگاه رو بسازی"
    cur = lab_level(user)
    if cur >= config.LAB_MAX_LEVEL:
        return False, "👑 آزمایشگاهت لول مکسه"
    need_lvl = lab_upgrade_min_level(cur + 1)
    if (getattr(user, "level", None) or 1) < need_lvl:
        return False, f"🔒 ارتقا به لول {fa_num(cur + 1)} از لول بازیکن {fa_num(need_lvl)} باز میشه"
    tp, mats = lab_upgrade_cost(cur + 1)
    if user.cash < tp:
        return False, "❌ تی‌پوینتت کافی نیس"
    if not await _take_materials(session, user.id, mats):
        need_txt = " + ".join(f"{fa_num(v)} {config.LAB_MATERIALS[k]['name']}" for k, v in mats.items())
        return False, f"🧴 مواد اولیه کافی نیست، این‌قدر می‌خواد: {need_txt}"
    user.cash -= tp
    user.lab_level = cur + 1
    return True, f"🧪 آزمایشگاه رفت رو لول {fa_num(cur + 1)}"


# ───────── کارگرها ─────────

async def get_workers(session: AsyncSession, user_id: int) -> list[LabWorker]:
    q = select(LabWorker).where(LabWorker.user_id == user_id).order_by(LabWorker.id)
    return list((await session.execute(q)).scalars())


def worker_slots(user: User) -> int:
    idx = min(max(lab_level(user) - 1, 0), len(config.LAB_WORKER_SLOTS) - 1)
    return config.LAB_WORKER_SLOTS[idx] if lab_active(user) else 0


async def hire_worker(session: AsyncSession, user: User, worker_key: str) -> tuple[bool, str]:
    cfg = config.LAB_WORKERS.get(worker_key)
    if not cfg:
        return False, "❌ همچین کارگری نیست"
    if not lab_active(user):
        return False, "🧪 اول باید آزمایشگاه رو بسازی"
    if (getattr(user, "level", None) or 1) < cfg["min_level"]:
        return False, f"🔒 {cfg['emoji']} {cfg['name']} از لول {fa_num(cfg['min_level'])} باز میشه"
    workers = await get_workers(session, user.id)
    if len(workers) >= worker_slots(user):
        return False, f"👷 اسلات کارگرت پره ({fa_num(worker_slots(user))} تا)، اول آزمایشگاه رو ارتقا بده"
    if user.cash < cfg["hire_cost"]:
        return False, "❌ تی‌پوینتت کافی نیس"
    user.cash -= cfg["hire_cost"]
    session.add(LabWorker(user_id=user.id, worker_key=worker_key))
    return True, f"{cfg['emoji']} {cfg['name']} استخدام شد"


async def fire_worker(session: AsyncSession, user: User, worker_id: int) -> tuple[bool, str]:
    q = select(LabWorker).where(LabWorker.id == worker_id, LabWorker.user_id == user.id)
    w = (await session.execute(q)).scalar_one_or_none()
    if not w:
        return False, "❌ این کارگر رو نداری"
    if w.busy_until:
        return False, "⏳ این کارگر وسط کاره، اول بذار تولیدش تموم بشه"
    cfg = config.LAB_WORKERS[w.worker_key]
    await session.delete(w)
    return True, f"{cfg['emoji']} {cfg['name']} اخراج شد"


def worker_rank(worker_key: str) -> int:
    """رتبه کارگر برای مقایسه حداقل‌نیاز محصول (ترتیب LAB_WORKER_ORDER)"""
    try:
        return config.LAB_WORKER_ORDER.index(worker_key)
    except ValueError:
        return -1


# ───────── تولید ─────────

def product_locked(user: User, product_key: str) -> bool:
    cfg = config.LAB_PRODUCTS[product_key]
    return lab_level(user) < cfg["unlock_lab_level"]


def _settle_worker(w: LabWorker) -> tuple[str, int] | None:
    """اگه کار کارگر تموم شده باشه، تسویه‌ش می‌کنه و (product_key, output) برمی‌گردونه، وگرنه None"""
    if w.busy_until and now_utc() >= w.busy_until:
        pk, out = w.job_product, w.job_output
        w.busy_until = None
        w.job_product = None
        w.job_output = 0
        return pk, out
    return None


async def collect_all(session: AsyncSession, user: User) -> list[tuple[str, int]]:
    """
    تولید آماده فقط وقتی تحویل میشه که دستمزد کامل و فضای انبار موجود باشه.
    در صورت کمبود پول/جا، کارگر و خروجی در حالت آماده می‌مونن؛ محصول دیگر گم نمی‌شود.
    """
    workers = await get_workers(session, user.id)
    got: list[tuple[str, int]] = []
    for w in workers:
        if not w.busy_until or now_utc() < w.busy_until or not w.job_product or w.job_output <= 0:
            continue
        wcfg = config.LAB_WORKERS[w.worker_key]
        upkeep = int(wcfg["upkeep"])
        if user.cash < upkeep:
            continue
        stock = await get_products(session, user.id)
        room = max(0, warehouse_cap(user) - stock.get(w.job_product, 0))
        if room < w.job_output:
            continue
        pk, out = w.job_product, w.job_output
        actual = await add_product(session, user.id, pk, out)
        if actual != out:
            continue
        user.cash -= upkeep
        w.busy_until = None
        w.job_product = None
        w.job_output = 0
        got.append((pk, actual))
    return got


async def production_quote(
    session: AsyncSession, user: User, worker_id: int, product_key: str,
) -> tuple[bool, str | dict]:
    """پیش‌فاکتور واحد برای صفحه تایید و اجرای نهایی؛ هیچ موجودی‌ای تغییر نمی‌دهد."""
    cfg = config.LAB_PRODUCTS.get(product_key)
    if not cfg:
        return False, "❌ همچین محصولی نیست"
    if not lab_active(user):
        return False, "🧪 اول باید آزمایشگاه رو بسازی"
    if product_locked(user, product_key):
        return False, f"🔒 {cfg['emoji']} {cfg['name']} از لول آزمایشگاه {fa_num(cfg['unlock_lab_level'])} باز میشه"
    q = (select(LabWorker)
         .where(LabWorker.id == worker_id, LabWorker.user_id == user.id)
         .with_for_update())
    w = (await session.execute(q)).scalar_one_or_none()
    if not w:
        return False, "❌ این کارگر رو نداری"
    if w.busy_until:
        return False, "👷 این کارگر هنوز مشغوله یا تولید آماده‌اش تحویل نشده"
    if worker_rank(w.worker_key) < worker_rank(cfg["min_worker"]):
        need = config.LAB_WORKERS[cfg["min_worker"]]
        return False, f"🔒 این محصول حداقل {need['emoji']} {need['name']} می‌خواد"

    stock = await get_materials(session, user.id)
    if any(stock.get(k, 0) < v for k, v in cfg["materials"].items()):
        return False, "❌ مواد اولیه کافی نیست"
    wcfg = config.LAB_WORKERS[w.worker_key]
    seconds = max(1, round(cfg["time_seconds"] / wcfg["speed_mult"]))
    output = max(1, round(cfg["output"] * wcfg["yield_mult"]))
    room = await product_room(session, user, product_key, reserve_jobs=True)
    if room < output:
        return False, f"📦 انبار آزمایشگاه جا نداره؛ برای این تولید {fa_num(output)} جا لازم داری ولی {fa_num(room)} جا خالیه"
    return True, {
        "worker": w,
        "worker_cfg": wcfg,
        "product": cfg,
        "seconds": seconds,
        "output": output,
        "upkeep": int(wcfg["upkeep"]),
        "materials": dict(cfg["materials"]),
    }


async def start_production(session: AsyncSession, user: User, worker_id: int, product_key: str) -> tuple[bool, str]:
    ok, quote = await production_quote(session, user, worker_id, product_key)
    if not ok:
        return False, str(quote)
    if not await _take_materials(session, user.id, quote["materials"]):
        return False, "❌ مواد اولیه کافی نیست؛ موجودی عوض شده، دوباره تلاش کن"
    w = quote["worker"]
    w.busy_until = now_utc() + timedelta(seconds=quote["seconds"])
    w.job_product = product_key
    w.job_output = quote["output"]
    cfg = quote["product"]
    return True, (
        f"🧪 تولید {cfg['emoji']} {cfg['name']} شروع شد، {fa_dur(quote['seconds'])} دیگه آماده‌ست\n"
        f"👷 موقع تحویل {money(quote['upkeep'])} دستمزد از نقدینگیت کم میشه"
    )


# ───────── متن‌های صفحه ─────────


async def lab_home_text(session: AsyncSession, user: User) -> str:
    if lab_locked(user) and not lab_active(user):
        return (
            "🧪 <b>آزمایشگاه Teriaky</b>\n\n"
            f"🔒 آزمایشگاه از لول {fa_num(config.LAB_MIN_LEVEL)} باز میشه\n"
            f"فعلاً لولت {fa_num(user.level)}ه، بیشتر بازی کن تا بازش کنی"
        )
    if not lab_active(user):
        return (
            "🧪 <b>آزمایشگاه Teriaky</b>\n\n"
            "آزمایشگاهت هنوز ساخته نشده\n"
            "برای شروع فقط کافیه دکمه‌ی ساخت رو بزنی، هیچ هزینه یا پیش‌نیاز دیگه‌ای نداره"
        )
    workers = await get_workers(session, user.id)
    busy_n = sum(1 for w in workers if w.busy_until)
    free_n = len(workers) - busy_n
    ready_n = sum(1 for w in workers if w.busy_until and w.busy_until <= now_utc())
    products_unlocked = [config.LAB_PRODUCTS[k]["name"] for k in config.LAB_PRODUCT_ORDER
                          if not product_locked(user, k)]
    lines = [
        "🧪 <b>آزمایشگاه Teriaky</b>",
        "",
        f"▫️ سطح آزمایشگاه: {fa_num(lab_level(user))} / {fa_num(config.LAB_MAX_LEVEL)}",
        f"▫️ وضعیت تولید: {fa_num(busy_n)} کارگر مشغول، {fa_num(free_n)} آزاد",
        f"▫️ کارگران فعال: {fa_num(len(workers))} / {fa_num(worker_slots(user))}",
        f"▫️ ظرفیت تولید: {fa_num(worker_slots(user))} اسلات همزمان",
        f"▫️ ظرفیت هر ماده: {fa_num(material_cap(user))}",
        f"▫️ ظرفیت هر محصول: {fa_num(warehouse_cap(user))}",
        f"▫️ محصولات قابل تولید: {', '.join(products_unlocked) if products_unlocked else '—'}",
    ]
    if ready_n:
        lines.append(f"\n🟠 {fa_num(ready_n)} تولید آماده تحویله؛ برای تحویل باید دستمزد و فضای انبار کافی داشته باشی")
    if lab_level(user) < config.LAB_MAX_LEVEL:
        need_lvl = lab_upgrade_min_level(lab_level(user) + 1)
        if (getattr(user, "level", None) or 1) < need_lvl:
            lines.append(f"\n⭕️ ارتقای بعدی از لول بازیکن {fa_num(need_lvl)} باز میشه")
    return "\n".join(lines)


async def lab_workers_text(session: AsyncSession, user: User) -> str:
    """صفحه کارگرها: لیست استخدام‌شده‌ها + کارگرهای قابل استخدام"""
    lines = ["<b>👷 کارگران آزمایشگاه</b>", ""]
    workers = await get_workers(session, user.id)
    if not workers:
        lines.append("هنوز هیچ کارگری استخدام نکردی")
    for w in workers:
        cfg = config.LAB_WORKERS[w.worker_key]
        if w.busy_until:
            pcfg = config.LAB_PRODUCTS.get(w.job_product, {})
            left = max(0, int((w.busy_until - now_utc()).total_seconds()))
            if left > 0:
                state = f"🟢 مشغول ({pcfg.get('emoji', '')} {pcfg.get('name', '')}، {fa_dur(left)} مونده)"
            elif user.cash < cfg["upkeep"]:
                state = f"🟠 آماده؛ منتظر {money(cfg['upkeep'])} دستمزد"
            else:
                state = "🟠 آماده تحویل؛ انبار را بررسی کن"
            lines.append(f"{cfg['emoji']} {cfg['name']} — {state}")
        else:
            lines.append(f"{cfg['emoji']} {cfg['name']} — ⚪ آزاد")
    lines.append("")
    lines.append(f"اسلات: {fa_num(len(workers))} / {fa_num(worker_slots(user))}")
    lines.append("")
    lines.append("برای استخدام روی کارگر موردنظر بزن")
    lines.append("")
    for key in config.LAB_WORKER_ORDER:
        cfg = config.LAB_WORKERS[key]
        locked = (getattr(user, "level", None) or 1) < cfg["min_level"]
        lines.append(SEP)
        lines.append(f"🔒 {cfg['name']} (قفل)" if locked else f"{cfg['emoji']} {cfg['name']}")
        lines.append(f"⚡ سرعت: ×{cfg['speed_mult']:g}  |  📦 بازده: ×{cfg['yield_mult']:g}")
        lines.append(f"🪙 هزینه استخدام: {money(cfg['hire_cost'])}  |  دستمزد هر دور: {money(cfg['upkeep'])}")
        if locked:
            lines.append(f"⭕️ بازگشایی در سطح {fa_num(cfg['min_level'])}")
    lines.append(SEP)
    return "\n".join(lines)


async def lab_employed_text(session: AsyncSession, user: User) -> str:
    """فقط کارگران استخدام‌شده، وضعیت و دستمزدشان."""
    workers = await get_workers(session, user.id)
    lines = ["<b>👷 کارگران استخدام‌شده</b>", ""]
    if not workers:
        lines.append("هنوز کارگری استخدام نکردی؛ از بخش «استخدام کارگر جدید» شروع کن")
    for w in workers:
        cfg = config.LAB_WORKERS[w.worker_key]
        lines.append(SEP)
        lines.append(f"{cfg['emoji']} {cfg['name']}")
        lines.append(f"🪙 دستمزد هر دور: {money(cfg['upkeep'])}")
        if not w.busy_until:
            lines.append("⚪ وضعیت: آزاد")
        else:
            pcfg = config.LAB_PRODUCTS.get(w.job_product, {})
            left = max(0, int((w.busy_until - now_utc()).total_seconds()))
            if left:
                lines.append(f"🟢 در حال تولید {pcfg.get('name', '')} | {fa_dur(left)} مانده")
            else:
                lines.append("🟠 تولید آماده تحویل است؛ دکمه «تحویل تولیدهای آماده» را بزن")
    lines += [SEP, "", f"اسلات پر: {fa_num(len(workers))} از {fa_num(worker_slots(user))}"]
    return "\n".join(lines)


async def lab_hire_catalog_text(session: AsyncSession, user: User) -> str:
    """فقط کاتالوگ استخدام کارگر جدید."""
    workers = await get_workers(session, user.id)
    lines = ["<b>➕ استخدام کارگر جدید</b>", "",
             f"اسلات آزاد: {fa_num(max(0, worker_slots(user) - len(workers)))} از {fa_num(worker_slots(user))}", ""]
    for key in config.LAB_WORKER_ORDER:
        cfg = config.LAB_WORKERS[key]
        locked = user.level < cfg["min_level"]
        lines += [SEP, f"{'🔒' if locked else cfg['emoji']} {cfg['name']}"]
        lines.append(f"⚡ سرعت ×{cfg['speed_mult']:g} | 📦 بازده ×{cfg['yield_mult']:g}")
        lines.append(f"💸 استخدام: {money(cfg['hire_cost'])} | 🪙 دستمزد: {money(cfg['upkeep'])}")
        if locked:
            lines.append(f"⭕️ از لول {fa_num(cfg['min_level'])} باز می‌شود")
    lines.append(SEP)
    return "\n".join(lines)


async def collection_report(session: AsyncSession, user: User) -> dict:
    """تحویل دستی و دلیل روشنِ تحویل‌نشدن تولیدهای آماده."""
    got = await collect_all(session, user)
    workers = await get_workers(session, user.id)
    due = [w for w in workers if w.busy_until and w.busy_until <= now_utc()]
    waiting_pay = []
    waiting_room = []
    stock = await get_products(session, user.id)
    for w in due:
        upkeep = config.LAB_WORKERS[w.worker_key]["upkeep"]
        if user.cash < upkeep:
            waiting_pay.append((w, upkeep))
        elif warehouse_cap(user) - stock.get(w.job_product, 0) < (w.job_output or 0):
            waiting_room.append(w)
    return {"got": got, "waiting_pay": waiting_pay, "waiting_room": waiting_room, "due": due}


async def lab_products_text(session: AsyncSession, user: User) -> str:
    """صفحه انتخاب محصول برای تولید"""
    lines = ["<b>🧪 تولید محصول</b>", "", "برای دیدن Recipe و شروع تولید روی محصول موردنظر بزن", ""]
    for key in config.LAB_PRODUCT_ORDER:
        cfg = config.LAB_PRODUCTS[key]
        locked = product_locked(user, key)
        lines.append(SEP)
        lines.append(f"🔒 {cfg['name']} (قفل)" if locked else f"{cfg['emoji']} {cfg['name']}")
        if locked:
            lines.append(f"⭕️ بازگشایی در لول آزمایشگاه {fa_num(cfg['unlock_lab_level'])}")
            continue
        mats_txt = " + ".join(f"{fa_num(v)} {config.LAB_MATERIALS[k]['emoji']}{config.LAB_MATERIALS[k]['name']}"
                              for k, v in cfg["materials"].items())
        need_w = config.LAB_WORKERS[cfg["min_worker"]]
        lines.append(f"🧴 مواد لازم: {mats_txt}")
        lines.append(f"⏱ مدت تولید پایه: {fa_dur(cfg['time_seconds'])}  |  📦 خروجی پایه: {fa_num(cfg['output'])}")
        lines.append(f"💰 ارزش فروش هر واحد: {money(cfg['sell'])}")
        lines.append(f"👷 حداقل کارگر: {need_w['emoji']} {need_w['name']}")
    lines.append(SEP)
    return "\n".join(lines)


async def lab_warehouse_text(session: AsyncSession, user: User) -> str:
    """انبار داخلی آزمایشگاه؛ فروش مستقیم ندارد و از همین‌جا محموله فرستاده می‌شود."""
    from services import smuggle as smg
    stock = await get_products(session, user.id)
    ongoing = [sh for sh in await smg.active_shipments(session, user.id) if shipment_product_key(sh.crop)]
    free = max(0, config.SHIPMENT_MAX_ACTIVE - len(await smg.active_shipments(session, user.id)))
    lines = [
        "<b>📦 انبار محصولات آزمایشگاه</b>", "",
        f"📦 ظرفیت هر محصول: {fa_num(warehouse_cap(user))}",
        f"🚚 اسلات محموله آزاد: {fa_num(free)} از {fa_num(config.SHIPMENT_MAX_ACTIVE)}", "",
        "محصولات فقط با ارسال محموله نقد میشن؛ تحویلش زمان و ریسک پلیس داره", "",
    ]
    for key in config.LAB_PRODUCT_ORDER:
        cfg = config.LAB_PRODUCTS[key]
        locked = product_locked(user, key)
        qty = stock.get(key, 0)
        lines.append(SEP)
        name_line = f"🔒 {cfg['name']} (قفل)" if locked else f"{cfg['emoji']} {cfg['name']}"
        lines.append(name_line)
        if not locked:
            lines.append(f"▫️ مقدار موجود: {fa_num(qty)} / {fa_num(warehouse_cap(user))}")
            lines.append(f"▫️ ارزش محموله: {money(cfg['sell'])} هر واحد")
    lines.append(SEP)
    if ongoing:
        lines += ["", "🚚 محموله‌های آزمایشگاه در راه:"]
        lines.extend(smg.shipment_line(sh) for sh in ongoing)
    return "\n".join(lines)


