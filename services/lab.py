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
from models import LabMaterial, LabProduct, LabWorker, User
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


# ───────── انبار مواد اولیه ─────────

async def get_materials(session: AsyncSession, user_id: int) -> dict[str, int]:
    q = select(LabMaterial).where(LabMaterial.user_id == user_id)
    return {row.material_key: row.count for row in (await session.execute(q)).scalars()}


async def add_material(session: AsyncSession, user_id: int, material_key: str, amount: int) -> int:
    """واریز ماده اولیه با سقف انبار، خروجی: مقدار واقعی واریزشده"""
    if amount <= 0:
        return 0
    q = select(LabMaterial).where(LabMaterial.user_id == user_id, LabMaterial.material_key == material_key)
    row = (await session.execute(q)).scalar_one_or_none()
    cur = row.count if row else 0
    got = max(0, min(amount, config.LAB_MATERIAL_CAP - cur))
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


def material_room(material_key: str, stock: dict[str, int]) -> int:
    return max(0, config.LAB_MATERIAL_CAP - stock.get(material_key, 0))


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
    free = material_room(material_key, stock)
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
    if amount <= 0:
        return 0
    q = select(LabProduct).where(LabProduct.user_id == user_id, LabProduct.product_key == product_key)
    row = (await session.execute(q)).scalar_one_or_none()
    cur = row.count if row else 0
    got = max(0, min(amount, config.LAB_WAREHOUSE_CAP_PER_PRODUCT - cur))
    if got <= 0:
        return 0
    if row:
        row.count += got
    else:
        session.add(LabProduct(user_id=user_id, product_key=product_key, count=got))
    return got


async def sell_product(session: AsyncSession, user: User, product_key: str, amount: int) -> tuple[bool, str, int]:
    """فروش محصول تولیدشده به تی‌پوینت، طبق سیستم اقتصادی فعلی (خروجی: اوکی, پیام خطا, مبلغ)"""
    cfg = config.LAB_PRODUCTS.get(product_key)
    if not cfg:
        return False, "❌ همچین محصولی نیست", 0
    if amount <= 0:
        return False, "❌ تعدادشو درست بگو", 0
    q = select(LabProduct).where(LabProduct.user_id == user.id, LabProduct.product_key == product_key)
    row = (await session.execute(q)).scalar_one_or_none()
    if not row or row.count < amount:
        return False, "❌ این همه ازش تو انبار نداری", 0
    row.count -= amount
    total = amount * cfg["sell"]
    user.cash += total
    return True, "", total


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
    """تسویه‌ی همه‌ی کارگرهایی که کارشون تموم شده، محصول میره تو انبار (هزینه نگهداری کارگر همون‌جا کسر میشه)
    خروجی: لیست (product_key, مقدار دریافتی واقعی بعد سقف انبار) برای هرکدوم که چیزی تحویل داد"""
    workers = await get_workers(session, user.id)
    got = []
    for w in workers:
        wcfg = config.LAB_WORKERS[w.worker_key]
        done = _settle_worker(w)
        if done:
            pk, out = done
            user.cash = max(0, user.cash - wcfg["upkeep"])   # نگهداری کارگر، هر بار که یه دور تولید تموم میشه کسر میشه
            actual = await add_product(session, user.id, pk, out)
            if actual > 0:
                got.append((pk, actual))
    return got


async def start_production(session: AsyncSession, user: User, worker_id: int, product_key: str) -> tuple[bool, str]:
    cfg = config.LAB_PRODUCTS.get(product_key)
    if not cfg:
        return False, "❌ همچین محصولی نیست"
    if product_locked(user, product_key):
        return False, f"🔒 {cfg['emoji']} {cfg['name']} از لول آزمایشگاه {fa_num(cfg['unlock_lab_level'])} باز میشه"
    q = select(LabWorker).where(LabWorker.id == worker_id, LabWorker.user_id == user.id)
    w = (await session.execute(q)).scalar_one_or_none()
    if not w:
        return False, "❌ این کارگر رو نداری"
    if w.busy_until:
        return False, "👷 تمام کارگران در حال فعالیت هستند"
    if worker_rank(w.worker_key) < worker_rank(cfg["min_worker"]):
        need = config.LAB_WORKERS[cfg["min_worker"]]
        return False, f"🔒 این محصول حداقل {need['emoji']} {need['name']} می‌خواد"
    if not await _take_materials(session, user.id, cfg["materials"]):
        return False, "❌ مواد اولیه کافی نیست"
    wcfg = config.LAB_WORKERS[w.worker_key]
    seconds = max(1, round(cfg["time_seconds"] / wcfg["speed_mult"]))
    output = max(1, round(cfg["output"] * wcfg["yield_mult"]))
    w.busy_until = now_utc() + timedelta(seconds=seconds)
    w.job_product = product_key
    w.job_output = output
    return True, f"🧪 تولید {cfg['emoji']} {cfg['name']} با موفقیت شروع شد، {fa_dur(seconds)} دیگه آماده‌ست"


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
    products_unlocked = [config.LAB_PRODUCTS[k]["name"] for k in config.LAB_PRODUCT_ORDER
                          if not product_locked(user, k)]
    lines = [
        "🧪 <b>آزمایشگاه Teriaky</b>",
        "",
        f"▫️ سطح آزمایشگاه: {fa_num(lab_level(user))} / {fa_num(config.LAB_MAX_LEVEL)}",
        f"▫️ وضعیت تولید: {fa_num(busy_n)} کارگر مشغول، {fa_num(free_n)} آزاد",
        f"▫️ کارگران فعال: {fa_num(len(workers))} / {fa_num(worker_slots(user))}",
        f"▫️ ظرفیت تولید: {fa_num(worker_slots(user))} اسلات همزمان",
        f"▫️ محصولات قابل تولید: {', '.join(products_unlocked) if products_unlocked else '—'}",
    ]
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
            lines.append(f"{cfg['emoji']} {cfg['name']} — 🟢 مشغول ({pcfg.get('emoji', '')} {pcfg.get('name', '')}، {fa_dur(left)} مونده)")
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
        lines.append(f"🪙 هزینه استخدام: {money(cfg['hire_cost'])}  |  نگهداری: {money(cfg['upkeep'])}")
        if locked:
            lines.append(f"⭕️ بازگشایی در سطح {fa_num(cfg['min_level'])}")
    lines.append(SEP)
    return "\n".join(lines)


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
    """صفحه انبار محصولات: نام، مقدار، ارزش فروش، وضعیت Unlock"""
    lines = ["<b>📦 انبار محصولات</b>", ""]
    stock = await get_products(session, user.id)
    for key in config.LAB_PRODUCT_ORDER:
        cfg = config.LAB_PRODUCTS[key]
        locked = product_locked(user, key)
        qty = stock.get(key, 0)
        lines.append(SEP)
        name_line = f"🔒 {cfg['name']} (قفل)" if locked else f"{cfg['emoji']} {cfg['name']}"
        lines.append(name_line)
        if not locked:
            lines.append(f"▫️ مقدار موجود: {fa_num(qty)} / {fa_num(config.LAB_WAREHOUSE_CAP_PER_PRODUCT)}")
            lines.append(f"▫️ ارزش فروش: {money(cfg['sell'])} هر واحد")
    lines.append(SEP)
    return "\n".join(lines)
