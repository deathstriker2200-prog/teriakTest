"""🧪 رابط کامل آزمایشگاه: تایید ساخت/استخدام/اخراج/تولید و ارسال محموله."""

import config
from telegram import Update
from telegram.ext import ContextTypes

from database import session_scope
from handlers.common import chat_id_of, parts, respond
from keyboards import keyboards as kb
from services import lab as lab_svc
from services import users
from utils import fa_dur, fa_num, money


# ───────── صفحه اصلی ─────────

async def render_lab(update: Update, alert: str | None = None) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.apply_energy_regen(user)
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
    """هم دکمه منو و هم دستور «آزمایشگاه» به این صفحه می‌رسند."""
    await render_lab(update)


# ───────── ساخت و ارتقا ─────────

async def lab_build_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پیش‌فاکتور ساخت اولیه؛ ساخت فقط بعد از تایید انجام می‌شود."""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        locked = lab_svc.lab_locked(user)
        active = lab_svc.lab_active(user)
        level = user.level
        await s.commit()
    if active:
        return await render_lab(update, alert="🧪 آزمایشگاهت از قبل ساخته شده")
    if locked:
        return await render_lab(update, alert=f"🔒 آزمایشگاه از لول {fa_num(config.LAB_MIN_LEVEL)} باز میشه")
    text = (
        "<b>🧪 ساخت آزمایشگاه</b>\n\n"
        f"⭐ لول فعلی: {fa_num(level)}\n"
        "💸 هزینه ساخت: رایگان\n"
        f"📦 ظرفیت شروع هر محصول: {fa_num(config.LAB_WAREHOUSE_CAP_BY_LEVEL[0])}\n"
        f"🧴 ظرفیت شروع هر ماده: {fa_num(config.LAB_MATERIAL_CAP_BY_LEVEL[0])}\n\n"
        "آزمایشگاه رو بسازیم؟"
    )
    await respond(update, text, kb.confirm_kb("cf:lab:build"))


async def lab_build_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg = await lab_svc.build_lab(s, user)
        await s.commit()
    await render_lab(update, alert=msg)


async def lab_upgrade_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        if not lab_svc.lab_active(user):
            await s.commit()
            return await render_lab(update, alert="🧪 اول آزمایشگاه رو بساز")
        if lab_svc.lab_level(user) >= config.LAB_MAX_LEVEL:
            await s.commit()
            return await render_lab(update, alert="👑 آزمایشگاهت لول مکسه")
        cur = lab_svc.lab_level(user)
        tp, mats = lab_svc.lab_upgrade_cost(cur + 1)
        need_lvl = lab_svc.lab_upgrade_min_level(cur + 1)
        player_lvl = user.level or 1
        await s.commit()
    if player_lvl < need_lvl:
        return await render_lab(update, alert=f"🔒 ارتقا به لول {fa_num(cur + 1)} از لول بازیکن {fa_num(need_lvl)} باز میشه")
    mats_txt = " + ".join(
        f"{fa_num(v)} {config.LAB_MATERIALS[k]['emoji']} {config.LAB_MATERIALS[k]['name']}"
        for k, v in mats.items()
    )
    text = (
        f"<b>⬆️ ارتقای آزمایشگاه، لول {fa_num(cur)} ← {fa_num(cur + 1)}</b>\n\n"
        f"💸 هزینه: {money(tp)}\n"
        f"🧴 مواد لازم: {mats_txt}\n"
        f"📦 ظرفیت هر محصول: {fa_num(config.LAB_WAREHOUSE_CAP_BY_LEVEL[cur])}\n"
        f"🧪 ظرفیت هر ماده: {fa_num(config.LAB_MATERIAL_CAP_BY_LEVEL[cur])}\n\n"
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
    """نمایش تایید استخدام؛ هنوز پول کم نمی‌شود."""
    _, _, worker_key = parts(update)
    cfg = config.LAB_WORKERS.get(worker_key)
    if not cfg:
        return await render_lab(update, alert="❌ همچین کارگری نیست")
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        workers = await lab_svc.get_workers(s, user.id)
        active = lab_svc.lab_active(user)
        slots = lab_svc.worker_slots(user)
        level, cash = user.level, user.cash
        await s.commit()
    if not active:
        return await render_lab(update, alert="🧪 اول آزمایشگاه رو بساز")
    if level < cfg["min_level"]:
        return await lab_workers_cb(update, context)
    if len(workers) >= slots:
        return await render_lab(update, alert="👷 اسلات کارگرت پره")
    text = (
        f"<b>➕ استخدام {cfg['emoji']} {cfg['name']}</b>\n\n"
        f"⚡ سرعت: ×{cfg['speed_mult']:g}\n"
        f"📦 بازده: ×{cfg['yield_mult']:g}\n"
        f"💸 هزینه استخدام: {money(cfg['hire_cost'])}\n"
        f"🪙 دستمزد هر دور تولید: {money(cfg['upkeep'])}\n"
        f"💵 نقدینگی: {money(cash)}\n\n"
        "استخدامش کنیم؟"
    )
    await respond(update, text, kb.lab_hire_confirm_kb(worker_key))


async def lab_hire_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, _, worker_key = parts(update)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg = await lab_svc.hire_worker(s, user, worker_key)
        text = await lab_svc.lab_workers_text(s, user)
        workers = await lab_svc.get_workers(s, user.id)
        markup = kb.lab_workers_kb(user, workers)
        await s.commit()
    await respond(update, text, markup, alert=msg)


async def lab_fire_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, worker_id = parts(update)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        workers = await lab_svc.get_workers(s, user.id)
        worker = next((w for w in workers if w.id == int(worker_id)), None)
        await s.commit()
    if not worker:
        return await render_lab(update, alert="❌ این کارگر رو نداری")
    if worker.busy_until:
        return await render_lab(update, alert="⏳ کارگر وسط کاره یا تولید آماده‌اش تحویل نشده")
    cfg = config.LAB_WORKERS[worker.worker_key]
    await respond(
        update,
        f"<b>❌ اخراج {cfg['emoji']} {cfg['name']}</b>\n\nهزینه استخدام برنمی‌گرده. مطمئنی؟",
        kb.lab_fire_confirm_kb(worker.id),
    )


async def lab_fire_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, _, worker_id = parts(update)
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
    """انتخاب محصول → نمایش کارگرهای آزاد و سازگار."""
    _, _, product_key = parts(update)
    if product_key not in config.LAB_PRODUCTS:
        return await render_lab(update, alert="❌ همچین محصولی نیست")
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        await lab_svc.collect_all(s, user)
        if lab_svc.product_locked(user, product_key):
            await s.commit()
            return await render_lab(update, alert="🔒 این محصول هنوز باز نشده")
        workers = await lab_svc.get_workers(s, user.id)
        await s.commit()
    cfg = config.LAB_PRODUCTS[product_key]
    compatible = [
        w for w in workers
        if not w.busy_until and lab_svc.worker_rank(w.worker_key) >= lab_svc.worker_rank(cfg["min_worker"])
    ]
    if not compatible:
        return await respond(update, "👷 کارگر آزاد و مناسب این محصول نداری", kb.lab_products_kb(user))
    text = f"<b>{cfg['emoji']} {cfg['name']}</b>\n\nکدوم کارگر رو برای پیش‌فاکتور انتخاب می‌کنی؟"
    await respond(update, text, kb.lab_pick_worker_kb(product_key, compatible))


async def lab_start_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """انتخاب کارگر → کارت کامل مواد/زمان/خروجی/دستمزد → تایید نهایی."""
    _, _, worker_id, product_key = parts(update)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, quote = await lab_svc.production_quote(s, user, int(worker_id), product_key)
        await s.commit()
    if not ok:
        return await render_lab(update, alert=str(quote))
    cfg, wcfg = quote["product"], quote["worker_cfg"]
    mats = " + ".join(
        f"{fa_num(n)} {config.LAB_MATERIALS[k]['emoji']} {config.LAB_MATERIALS[k]['name']}"
        for k, n in quote["materials"].items()
    )
    value = quote["output"] * cfg["sell"]
    text = (
        f"<b>🧪 تایید تولید {cfg['emoji']} {cfg['name']}</b>\n\n"
        f"👷 کارگر: {wcfg['emoji']} {wcfg['name']}\n"
        f"🧴 مواد مصرفی: {mats}\n"
        f"⏱ زمان: {fa_dur(quote['seconds'])}\n"
        f"📦 خروجی: {fa_num(quote['output'])}\n"
        f"💰 ارزش محموله خروجی: {money(value)}\n"
        f"🪙 دستمزد موقع تحویل: {money(quote['upkeep'])}\n\n"
        "تولید رو شروع کنیم؟"
    )
    await respond(update, text, kb.lab_start_confirm_kb(int(worker_id), product_key))


async def lab_start_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, _, worker_id, product_key = parts(update)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg = await lab_svc.start_production(s, user, int(worker_id), product_key)
        await s.commit()
    await render_lab(update, alert=msg)


# ───────── تحویل، انبار و ارسال محموله ─────────

async def lab_collect_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_lab(update)


async def lab_warehouse_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        await lab_svc.collect_all(s, user)
        text = await lab_svc.lab_warehouse_text(s, user)
        stock = await lab_svc.get_products(s, user.id)
        from services import smuggle as smg
        free = max(0, config.SHIPMENT_MAX_ACTIVE - len(await smg.active_shipments(s, user.id)))
        markup = kb.lab_warehouse_kb(user, stock, free)
        await s.commit()
    await respond(update, text, markup)


async def lab_ship_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, product_key, qty_s = parts(update)
    qty = int(qty_s)
    cfg = config.LAB_PRODUCTS.get(product_key)
    if not cfg:
        return await render_lab(update, alert="❌ همچین محصولی نیست")
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        stock = await lab_svc.get_products(s, user.id)
        have = stock.get(product_key, 0)
        from services import smuggle as smg
        from services.snitch import sell_mult
        ongoing = await smg.active_shipments(s, user.id)
        mult = sell_mult(user)
        await s.commit()
    if qty <= 0 or have < qty:
        return await render_lab(update, alert="❌ این تعداد تو انبار آزمایشگاه نیست")
    if len(ongoing) >= config.SHIPMENT_MAX_ACTIVE:
        return await render_lab(update, alert="🚚 همه اسلات‌های محموله‌ات پره")
    gross = qty * cfg["sell"]
    shown = round(gross * mult)
    text = (
        f"<b>📦 ارسال محموله {cfg['emoji']} {cfg['name']}</b>\n\n"
        f"🔢 تعداد: {fa_num(qty)}\n"
        f"💰 ارزش محموله: {money(shown)}\n"
        f"⏱ زمان ارسال: {fa_dur(smg.shipment_seconds())}\n"
        f"🚔 احتمال توقیف: {fa_num(int(config.SHIPMENT_POLICE_CHANCE * 100))}%\n\n"
        "بعد از رسیدن محموله پولش واریز میشه. ارسالش کنیم؟"
    )
    await respond(update, text, kb.lab_ship_confirm_kb(product_key, qty))


async def lab_ship_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, _, product_key, qty_s = parts(update)
    qty = int(qty_s)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg, sh = await lab_svc.send_product_shipment(s, user, product_key, qty, chat_id_of(update))
        tq = None
        dq_done, dq_left, uname = [], 0, users.display_name(user)
        if ok:
            from services import quests as dq_svc, teams as team_svc
            dq_done, dq_left = await dq_svc.track(s, user, "shipment")
            tq = await team_svc.record_shipment(s, user)
        await s.commit()
    if not ok:
        return await render_lab(update, alert=msg)
    await lab_warehouse_cb(update, context)
    if tq or dq_done:
        from handlers.common import announce_notes
        await announce_notes(update, [tq])
        from handlers import dquests
        await dquests.announce_completed(update, uname, dq_done, dq_left)


# کال‌بک‌های قدیمی فروش مستقیم به‌جای پول‌دادن، کاربر را به مسیر امن محموله هدایت می‌کنند
async def lab_sell_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await lab_warehouse_cb(update, context)


async def lab_sell_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_lab(update, alert="📦 فروش مستقیم حذف شده؛ از انبار آزمایشگاه محموله بفرست")
