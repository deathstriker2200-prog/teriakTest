"""
🧪 آزمایشگاه (راند ۴۳، درخواست کارفرما)

از لول بازیکن ۱۵ با هزینه سنگین پول، چوب و آهن ساخته میشه
۴ لول (گیت بازیکن ۱۵/۲۰/۲۵/۳۰) | بازشدن کارگر با لول خود آزمایشگاه | ۷ محصول مرحله‌ای | ۴ ماده اولیه خیالی برای تولید

تولید کاملاً روی ستون busy_until هر کارگر زمان‌بندی میشه، ربطی به آنلاین بودن کاربر یا باز بودن صفحه نداره
همه قیمت‌ها و اعداد فقط تو config.py (LAB_*) و از اونجا قابل تنظیمن، اینجا هیچ عدد هاردکدی نیست
"""

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import LabCompletionEvent, LabMaterial, LabProduct, LabWorker, Shipment, User
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


def lab_build_cost() -> tuple[int, int, int]:
    """هزینه نهایی ساخت لول 1: تی‌پوینت، چوب، آهن."""
    return config.LAB_BUILD_COST


def lab_upgrade_cost(to_level: int) -> tuple[int, int, int]:
    """هزینه نهایی رفتن به لول 2..4: تی‌پوینت، چوب، آهن."""
    idx = min(max(to_level - 2, 0), len(config.LAB_UPGRADE_COST) - 1)
    return config.LAB_UPGRADE_COST[idx]


async def _lock_and_refresh_builder(session: AsyncSession, user: User) -> None:
    """ردیف کاربر را پیش از محاسبه هزینه قفل و موجودی‌های حساس را تازه می‌کند."""
    with session.no_autoflush:
        await session.execute(select(User.id).where(User.id == user.id).with_for_update())
    await session.refresh(user, ["level", "lab_level", "cash", "wood", "iron"])


def _missing_build_resource(user: User, cost: tuple[int, int, int]) -> str | None:
    tp, wood, iron = cost
    if int(user.cash or 0) < tp:
        return f"❌ برای این ساخت {money(tp)} تی‌پوینت لازم داری"
    if int(user.wood or 0) < wood:
        return f"❌ برای این ساخت {fa_num(wood)} چوب لازم داری"
    if int(user.iron or 0) < iron:
        return f"❌ برای این ساخت {fa_num(iron)} آهن لازم داری"
    return None


async def _charge_lab_level(
    session: AsyncSession,
    user: User,
    *,
    from_level: int,
    to_level: int,
    min_player_level: int,
    cost: tuple[int, int, int],
) -> bool:
    """برداشت اتمیک سه موجودی؛ درخواست هم‌زمان نمی‌تواند دوبار لول بدهد یا منفی کند."""
    tp, wood, iron = cost
    result = await session.execute(
        update(User)
        .where(
            User.id == user.id,
            User.lab_level == from_level,
            User.level >= min_player_level,
            User.cash >= tp,
            User.wood >= wood,
            User.iron >= iron,
        )
        .values(
            cash=User.cash - tp,
            wood=User.wood - wood,
            iron=User.iron - iron,
            lab_level=to_level,
        )
        .execution_options(synchronize_session=False)
    )
    if int(result.rowcount or 0) != 1:
        await session.refresh(user, ["level", "lab_level", "cash", "wood", "iron"])
        return False
    await session.refresh(user, ["level", "lab_level", "cash", "wood", "iron"])
    return True


async def build_lab(session: AsyncSession, user: User) -> tuple[bool, str]:
    """ساخت اتمیک لول 1 با هزینه تأییدشده پول، چوب و آهن."""
    await _lock_and_refresh_builder(session, user)
    if lab_locked(user):
        return False, f"🔒 آزمایشگاه از لول {fa_num(config.LAB_MIN_LEVEL)} باز میشه، فعلا لولت کمه"
    if lab_active(user):
        return False, "🧪 آزمایشگاهت از قبل ساخته شده"
    cost = lab_build_cost()
    missing = _missing_build_resource(user, cost)
    if missing:
        return False, missing
    if not await _charge_lab_level(
        session, user, from_level=0, to_level=1,
        min_player_level=config.LAB_MIN_LEVEL, cost=cost,
    ):
        return False, "❌ موجودی یا وضعیت آزمایشگاه عوض شد؛ دوباره امتحان کن"
    return True, "🧪 آزمایشگاه لول 1 ساخته شد! پول، چوب و آهن ساخت کامل پرداخت شد"


async def upgrade_lab(session: AsyncSession, user: User) -> tuple[bool, str]:
    await _lock_and_refresh_builder(session, user)
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
    cost = lab_upgrade_cost(cur + 1)
    missing = _missing_build_resource(user, cost)
    if missing:
        return False, missing
    if not await _charge_lab_level(
        session, user, from_level=cur, to_level=cur + 1,
        min_player_level=need_lvl, cost=cost,
    ):
        return False, "❌ موجودی یا وضعیت آزمایشگاه عوض شد؛ دوباره امتحان کن"
    return True, f"🧪 آزمایشگاه رفت رو لول {fa_num(cur + 1)}؛ هزینه ساخت کامل پرداخت شد"


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
    await _lock_and_refresh_builder(session, user)
    if not lab_active(user):
        return False, "🧪 اول باید آزمایشگاه رو بسازی"
    need_lab = int(cfg["unlock_lab_level"])
    if lab_level(user) < need_lab:
        return False, f"🔒 {cfg['emoji']} {cfg['name']} از لول آزمایشگاه {fa_num(need_lab)} باز میشه"
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


async def _deposit_completed_product(
    session: AsyncSession, user_id: int, product_key: str, amount: int,
) -> None:
    """واریز کامل خروجی رزروشده؛ تولید تمام‌شده هیچ‌وقت به‌خاطر سقف گم نمی‌شود."""
    row = (await session.execute(
        select(LabProduct).where(
            LabProduct.user_id == user_id,
            LabProduct.product_key == product_key,
        ).with_for_update()
    )).scalar_one_or_none()
    if row:
        row.count = int(row.count or 0) + amount
    else:
        session.add(LabProduct(user_id=user_id, product_key=product_key, count=amount))


async def settle_due_productions(
    session: AsyncSession, user_id: int | None = None,
) -> list[LabCompletionEvent]:
    """خروجی‌های رسیده را اتمیک انبار و کارگر را مستقل از اعلان آزاد می‌کند."""
    now = now_utc()
    q = select(LabWorker).where(
        LabWorker.busy_until.is_not(None),
        LabWorker.busy_until <= now,
    )
    if user_id is not None:
        q = q.where(LabWorker.user_id == user_id)
    q = q.order_by(LabWorker.id).with_for_update()
    completed: list[LabCompletionEvent] = []
    for w in (await session.execute(q)).scalars():
        product_key = w.job_product
        output = max(0, int(w.job_output or 0))
        if product_key in config.LAB_PRODUCTS and output > 0:
            await _deposit_completed_product(session, w.user_id, product_key, output)
            event = LabCompletionEvent(
                user_id=w.user_id,
                worker_key=w.worker_key,
                product_key=product_key,
                qty=output,
                completed_at=now,
            )
            session.add(event)
            completed.append(event)
        # کارهای legacy دستمزدشان هنگام شروع کم نشده؛ برای جلوگیری از قفل/دوبارکسر، رایگان تسویه می‌شوند.
        w.busy_until = None
        w.job_started_at = None
        w.job_product = None
        w.job_output = 0
        w.job_upkeep_paid = False
    await session.flush()
    return completed


async def collect_all(session: AsyncSession, user: User) -> list[tuple[str, int]]:
    """سازگاری دکمه‌های قدیمی؛ تحویل حالا خودکار و بدون وابستگی به فروش است."""
    events = await settle_due_productions(session, user.id)
    return [(e.product_key, e.qty) for e in events]


async def pending_completion_events(session: AsyncSession) -> list[LabCompletionEvent]:
    """اعلان‌های ارسال‌نشده با سقف retry."""
    q = select(LabCompletionEvent).where(
        LabCompletionEvent.notified_at.is_(None),
        LabCompletionEvent.notify_attempts < config.LAB_COMPLETION_NOTIFY_MAX_ATTEMPTS,
    ).order_by(LabCompletionEvent.id).limit(200)
    return list((await session.execute(q)).scalars())


def completion_message(event: LabCompletionEvent) -> str:
    pcfg = config.LAB_PRODUCTS.get(event.product_key, {})
    wcfg = config.LAB_WORKERS.get(event.worker_key, {})
    return (
        f"✅ تولید {pcfg.get('emoji', '🧪')} {pcfg.get('name', 'محصول')} تموم شد؛ "
        f"{fa_num(event.qty)} تا رفت تو انبار و "
        f"{wcfg.get('emoji', '👷')} {wcfg.get('name', 'کارگر')} دوباره آزاده."
    )


async def production_quote(
    session: AsyncSession, user: User, worker_id: int, product_key: str,
) -> tuple[bool, str | dict]:
    """پیش‌فاکتور واحد برای صفحه تایید و اجرای نهایی؛ هیچ موجودی‌ای تغییر نمی‌دهد."""
    cfg = config.LAB_PRODUCTS.get(product_key)
    if not cfg:
        return False, "❌ همچین محصولی نیست"
    await settle_due_productions(session, user.id)
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
    wcfg = config.LAB_WORKERS[w.worker_key]
    worker_lab_level = int(wcfg["unlock_lab_level"])
    if lab_level(user) < worker_lab_level:
        return False, f"🔒 این کارگر از لول آزمایشگاه {fa_num(worker_lab_level)} قابل استفاده است"
    if worker_rank(w.worker_key) < worker_rank(cfg["min_worker"]):
        need = config.LAB_WORKERS[cfg["min_worker"]]
        return False, f"🔒 این محصول حداقل {need['emoji']} {need['name']} می‌خواد"

    stock = await get_materials(session, user.id)
    if any(stock.get(k, 0) < v for k, v in cfg["materials"].items()):
        return False, "❌ مواد اولیه کافی نیست"
    upkeep = int(wcfg["upkeep"])
    if int(user.cash or 0) < upkeep:
        return False, f"💸 برای شروع این دور {money(upkeep)} دستمزد کم داری"
    seconds = max(1, round(cfg["time_seconds"] / wcfg["speed_mult"]))
    output = int(cfg["output"]) if cfg.get("fixed_output") else max(1, round(cfg["output"] * wcfg["yield_mult"]))
    room = await product_room(session, user, product_key, reserve_jobs=True)
    if room < output:
        return False, f"📦 انبار آزمایشگاه جا نداره؛ برای این تولید {fa_num(output)} جا لازم داری ولی {fa_num(room)} جا خالیه"
    return True, {
        "worker": w,
        "worker_cfg": wcfg,
        "product": cfg,
        "seconds": seconds,
        "output": output,
        "upkeep": upkeep,
        "materials": dict(cfg["materials"]),
    }


async def start_production(session: AsyncSession, user: User, worker_id: int, product_key: str) -> tuple[bool, str]:
    ok, quote = await production_quote(session, user, worker_id, product_key)
    if not ok:
        return False, str(quote)
    if int(user.cash or 0) < quote["upkeep"]:
        return False, "💸 نقدینگیت برای دستمزد شروع کار کافی نیست"
    if not await _take_materials(session, user.id, quote["materials"]):
        return False, "❌ مواد اولیه کافی نیست؛ موجودی عوض شده، دوباره تلاش کن"
    user.cash -= quote["upkeep"]
    w = quote["worker"]
    started = now_utc()
    w.job_started_at = started
    w.busy_until = started + timedelta(seconds=quote["seconds"])
    w.job_product = product_key
    w.job_output = quote["output"]
    w.job_upkeep_paid = True
    cfg = quote["product"]
    return True, (
        f"🧪 تولید {cfg['emoji']} {cfg['name']} شروع شد، {fa_dur(quote['seconds'])} دیگه آماده‌ست\n"
        f"👷 {money(quote['upkeep'])} دستمزد همین الان حساب شد؛ بعد پایان، محصول خودکار میره انبار و کارگر آزاد میشه"
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
    lines = [
        "🧪 <b>آزمایشگاه Teriaky</b>",
        "",
        f"⭐ سطح: {fa_num(lab_level(user))} / {fa_num(config.LAB_MAX_LEVEL)}",
        f"👷 کارگرها: {fa_num(len(workers))} / {fa_num(worker_slots(user))}",
        f"🟢 آزاد: {fa_num(free_n)}  |  ⏳ مشغول: {fa_num(busy_n)}",
        f"🧴 سقف هر ماده: {fa_num(material_cap(user))}",
        f"📦 سقف هر محصول: {fa_num(warehouse_cap(user))}",
        "",
        "تولید که تموم بشه محصول خودکار میره انبار و کارگر همون لحظه دوباره آزاد میشه.",
    ]
    if lab_level(user) < config.LAB_MAX_LEVEL:
        to_level = lab_level(user) + 1
        need_lvl = lab_upgrade_min_level(to_level)
        tp, wood, iron = lab_upgrade_cost(to_level)
        lines += [
            "",
            f"⬆️ ساخت لول {fa_num(to_level)}: {money(tp)} + 🪵 {fa_num(wood)} + ⛏️ {fa_num(iron)}",
        ]
        if (getattr(user, "level", None) or 1) < need_lvl:
            lines.append(f"🔒 ارتقای بعدی از لول بازیکن {fa_num(need_lvl)} باز میشه")
    return "\n".join(lines)


async def lab_workers_text(session: AsyncSession, user: User) -> str:
    """صفحه جمع‌وجور کارگرها؛ وضعیت فعلی و کاتالوگ استخدام در یک جا."""
    workers = await get_workers(session, user.id)
    lines = [
        "<b>👷 کارگرهای آزمایشگاه</b>", "",
        f"اسلات پر: {fa_num(len(workers))} / {fa_num(worker_slots(user))}",
    ]
    if not workers:
        lines += ["", "هنوز کارگری نداری؛ از دکمه استخدام شروع کن."]
    else:
        lines += ["", "<b>وضعیت کارگرها</b>"]
        for w in workers:
            cfg = config.LAB_WORKERS[w.worker_key]
            if not w.busy_until and lab_level(user) < int(cfg["unlock_lab_level"]):
                state = f"🔒 تا آزمایشگاه لول {fa_num(cfg['unlock_lab_level'])}"
            elif not w.busy_until:
                state = "🟢 آزاد"
            else:
                pcfg = config.LAB_PRODUCTS.get(w.job_product, {})
                left = max(0, int((w.busy_until - now_utc()).total_seconds()))
                state = f"⏳ {pcfg.get('name', 'تولید')}؛ {fa_dur(left)} مونده"
            lines.append(f"{cfg['emoji']} {cfg['name']} — {state}")
    lines += ["", "<b>استخدام</b>"]
    for key in config.LAB_WORKER_ORDER:
        cfg = config.LAB_WORKERS[key]
        need_lab = int(cfg["unlock_lab_level"])
        if lab_level(user) < need_lab:
            lines.append(f"🔒 {cfg['name']} — آزمایشگاه لول {fa_num(need_lab)}")
        else:
            lines.append(
                f"{cfg['emoji']} {cfg['name']} — استخدام {money(cfg['hire_cost'])} | "
                f"دستمزد هر تولید {money(cfg['upkeep'])}"
            )
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
        if not w.busy_until and lab_level(user) < int(cfg["unlock_lab_level"]):
            lines.append(f"🔒 وضعیت: تا آزمایشگاه لول {fa_num(cfg['unlock_lab_level'])} قابل استفاده نیست")
        elif not w.busy_until:
            lines.append("⚪ وضعیت: آزاد")
        else:
            pcfg = config.LAB_PRODUCTS.get(w.job_product, {})
            left = max(0, int((w.busy_until - now_utc()).total_seconds()))
            if left:
                lines.append(f"🟢 در حال تولید {pcfg.get('name', '')} | {fa_dur(left)} مانده")
            else:
                lines.append("✅ زمان تولید رسیده؛ با جاب خودکار وارد انبار و کارگر آزاد می‌شود")
    lines += [SEP, "", f"اسلات پر: {fa_num(len(workers))} از {fa_num(worker_slots(user))}"]
    return "\n".join(lines)


async def lab_hire_catalog_text(session: AsyncSession, user: User) -> str:
    """فقط کاتالوگ استخدام کارگر جدید."""
    workers = await get_workers(session, user.id)
    lines = ["<b>➕ استخدام کارگر جدید</b>", "",
             f"اسلات آزاد: {fa_num(max(0, worker_slots(user) - len(workers)))} از {fa_num(worker_slots(user))}", ""]
    for key in config.LAB_WORKER_ORDER:
        cfg = config.LAB_WORKERS[key]
        need_lab = int(cfg["unlock_lab_level"])
        locked = lab_level(user) < need_lab
        lines += [SEP, f"{'🔒' if locked else cfg['emoji']} {cfg['name']}"]
        lines.append(f"⚡ سرعت ×{cfg['speed_mult']:g} | 📦 بازده ×{cfg['yield_mult']:g}")
        lines.append(f"💸 استخدام: {money(cfg['hire_cost'])} | 🪙 دستمزد: {money(cfg['upkeep'])}")
        if locked:
            lines.append(f"⭕️ از لول آزمایشگاه {fa_num(need_lab)} باز می‌شود")
    lines.append(SEP)
    return "\n".join(lines)


async def collection_report(session: AsyncSession, user: User) -> dict:
    """سازگاری callback قدیمی؛ تولیدهای رسیده را خودکار تسویه می‌کند."""
    got = await collect_all(session, user)
    return {"got": got, "waiting_pay": [], "waiting_room": [], "due": []}


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
    """نمای مرتب مواد و محصولات آماده آزمایشگاه."""
    from services import smuggle as smg

    materials = await get_materials(session, user.id)
    stock = await get_products(session, user.id)
    all_shipments = await smg.active_shipments(session, user.id)
    ongoing = [sh for sh in all_shipments if shipment_product_key(sh.crop)]
    free = max(0, config.SHIPMENT_MAX_ACTIVE - len(all_shipments))
    lines = [
        "<b>📦 انبار آزمایشگاه</b>", "",
        f"🧴 سقف هر ماده: {fa_num(material_cap(user))}",
        f"📦 سقف هر محصول: {fa_num(warehouse_cap(user))}",
        f"🚚 محموله آزاد: {fa_num(free)} / {fa_num(config.SHIPMENT_MAX_ACTIVE)}",
        "", "<b>🧴 مواد اولیه</b>",
    ]
    for key, cfg in config.LAB_MATERIALS.items():
        qty = int(materials.get(key, 0) or 0)
        lines.append(f"{cfg['emoji']} {cfg['name']}: {fa_num(qty)} / {fa_num(material_cap(user))}")

    lines += ["", "<b>📦 محصولات آماده</b>"]
    any_product = False
    total_value = 0
    for key in config.LAB_PRODUCT_ORDER:
        qty = int(stock.get(key, 0) or 0)
        if qty <= 0:
            continue
        any_product = True
        cfg = config.LAB_PRODUCTS[key]
        value = qty * int(cfg["sell"])
        total_value += value
        lines.append(
            f"{cfg['emoji']} {cfg['name']}: {fa_num(qty)} / {fa_num(warehouse_cap(user))}"
            f"  |  هر واحد {money(cfg['sell'])}  |  کل {money(value)}"
        )
    if not any_product:
        lines.append("فعلاً محصول آماده‌ای تو انبار نیست.")
    else:
        lines += ["", f"💰 ارزش تقریبی کل: {money(total_value)}"]
    lines += ["", "محصول‌ها فقط با محموله نقد میشن و ریسک پلیس سر جاشه."]
    if ongoing:
        lines += ["", "<b>🚚 محموله‌های آزمایشگاه در راه</b>"]
        lines.extend(smg.shipment_line(sh) for sh in ongoing)
    return "\n".join(lines)
