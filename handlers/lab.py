"""
🧪 آزمایشگاه (راند ۴۳، درخواست کارفرما)

صفحه اصلی، ساخت/ارتقا، کارگرها (استخدام/اخراج)، تولید محصول (انتخاب محصول → انتخاب کارگر آزاد → شروع)،
تحویل تولیدهای تموم‌شده و فروش از انبار. همه‌ی منطق و اعداد تو services/lab.py و config.py ن.
"""

import config
from telegram import Update
from telegram.ext import ContextTypes

from database import session_scope
from handlers.common import parts, respond
from keyboards import keyboards as kb
from services import lab as lab_svc
from services import users
from utils import fa_num, money


# ───────── صفحه اصلی ─────────

async def render_lab(update: Update, alert: str | None = None) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.apply_energy_regen(user)
        # هر بار که صفحه باز میشه تولیدهای تموم‌شده خودکار تسویه میشن، بدون نیاز به دکمه جدا
        got = await lab_svc.collect_all(s, user)
        text = await lab_svc.lab_home_text(s, user)
        if got:
            parts_txt = " + ".join(
                f"{fa_num(amt)} {config.LAB_PRODUCTS[k]['emoji']} {config.LAB_PRODUCTS[k]['name']}"
                for k, amt in got
            )
            text += f"\n\n📥 تحویل داده شد: {parts_txt}"
        markup = kb.lab_home_kb(user)
        await s.commit()
    await respond(update, text, markup, alert=alert)


async def lab_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_lab(update)


async def lab_build_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg = await lab_svc.build_lab(s, user)
        await s.commit()
    await render_lab(update, alert=msg)


# ───────── ارتقای آزمایشگاه ─────────

async def lab_upgrade_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        if lab_svc.lab_level(user) >= config.LAB_MAX_LEVEL:
            await s.commit()
            return await render_lab(update, alert="👑 آزمایشگاهت لول مکسه")
        cur = lab_svc.lab_level(user)
        tp, mats = lab_svc.lab_upgrade_cost(cur + 1)
        need_lvl = lab_svc.lab_upgrade_min_level(cur + 1)
        player_lvl = getattr(user, "level", None) or 1
        await s.commit()
    if player_lvl < need_lvl:
        return await render_lab(update, alert=f"🔒 ارتقا به لول {fa_num(cur + 1)} از لول بازیکن {fa_num(need_lvl)} باز میشه")
    mats_txt = " + ".join(f"{fa_num(v)} {config.LAB_MATERIALS[k]['emoji']}{config.LAB_MATERIALS[k]['name']}"
                          for k, v in mats.items())
    text = (
        f"<b>⬆️ ارتقای آزمایشگاه، از لول {fa_num(cur)} به {fa_num(cur + 1)}</b>\n\n"
        f"💸 هزینه: {money(tp)}\n"
        f"🧴 مواد لازم: {mats_txt}\n\n"
        "انجامش بدیم؟"
    )
    await respond(update, text, kb.confirm_kb("cf:lab:up"))


async def lab_upgrade_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg = await lab_svc.upgrade_lab(s, user)
        await s.commit()
    await render_lab(update, alert=msg)


# ───────── کارگرها ─────────

async def lab_workers_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        await lab_svc.collect_all(s, user)
        text = await lab_svc.lab_workers_text(s, user)
        workers = await lab_svc.get_workers(s, user.id)
        markup = kb.lab_workers_kb(user, workers)
        await s.commit()
    await respond(update, text, markup)


async def lab_hire_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, worker_key = parts(update)  # lab:hire:<key>
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg = await lab_svc.hire_worker(s, user, worker_key)
        text = await lab_svc.lab_workers_text(s, user)
        workers = await lab_svc.get_workers(s, user.id)
        markup = kb.lab_workers_kb(user, workers)
        await s.commit()
    await respond(update, text, markup, alert=msg)


async def lab_fire_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, worker_id = parts(update)  # lab:fire:<id>
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg = await lab_svc.fire_worker(s, user, int(worker_id))
        text = await lab_svc.lab_workers_text(s, user)
        workers = await lab_svc.get_workers(s, user.id)
        markup = kb.lab_workers_kb(user, workers)
        await s.commit()
    await respond(update, text, markup, alert=msg)


# ───────── تولید محصول ─────────

async def lab_products_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        await lab_svc.collect_all(s, user)
        text = await lab_svc.lab_products_text(s, user)
        markup = kb.lab_products_kb(user)
        await s.commit()
    await respond(update, text, markup)


async def lab_start_pick_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه یه محصول تو صفحه تولید زده شد → لیست کارگرهای آزاد برای شروع"""
    _, _, product_key = parts(update)  # lab:start:<product_key>
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        if lab_svc.product_locked(user, product_key):
            await s.commit()
            return await render_lab(update, alert="🔒 این محصول هنوز باز نشده")
        workers = await lab_svc.get_workers(s, user.id)
        prod_markup = kb.lab_products_kb(user)
        await s.commit()
    cfg = config.LAB_PRODUCTS[product_key]
    free = [w for w in workers if not w.busy_until]
    if not free:
        return await respond(update, "👷 تمام کارگران در حال فعالیت هستند", prod_markup)
    text = f"<b>{cfg['emoji']} {cfg['name']}</b>\n\nکدوم کارگر شروع کنه؟"
    await respond(update, text, kb.lab_pick_worker_kb(product_key, workers))


async def lab_start_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, _, worker_id, product_key = parts(update)  # cf:lab:start:<worker_id>:<product_key>
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg = await lab_svc.start_production(s, user, int(worker_id), product_key)
        await s.commit()
    await render_lab(update, alert=msg)


# ───────── تحویل دستی + انبار/فروش ─────────

async def lab_collect_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_lab(update)


async def lab_warehouse_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        await lab_svc.collect_all(s, user)
        text = await lab_svc.lab_warehouse_text(s, user)
        stock = await lab_svc.get_products(s, user.id)
        markup = kb.lab_warehouse_kb(user, stock)
        await s.commit()
    await respond(update, text, markup)


async def lab_sell_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, product_key, qty = parts(update)  # lab:sell:<product_key>:<qty>
    qty = int(qty)
    cfg = config.LAB_PRODUCTS[product_key]
    total = qty * cfg["sell"]
    text = (
        f"<b>💰 فروش {cfg['emoji']} {cfg['name']}</b>\n\n"
        f"تعداد: {fa_num(qty)}\n"
        f"مبلغ کل: {money(total)}\n\n"
        "انجامش بدیم؟"
    )
    await respond(update, text, kb.lab_sell_confirm_kb(product_key, qty))


async def lab_sell_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, product_key, qty = parts(update)  # cf:lab:sell:<product_key>:<qty>
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg, total = await lab_svc.sell_product(s, user, product_key, int(qty))
        text = await lab_svc.lab_warehouse_text(s, user)
        stock = await lab_svc.get_products(s, user.id)
        markup = kb.lab_warehouse_kb(user, stock)
        await s.commit()
    alert = f"✅ {money(total)} فروخته شد" if ok else msg
    await respond(update, text, markup, alert=alert)
