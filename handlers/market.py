"""
هندلرهای مارکت بازیکن‌ها 🛒 (راند ۲۳، درخواست کارفرما)
دستور «مارکت»: خرید (لیست صفحه‌بندی‌شده + مرتب‌سازی قیمت + سرچ آیتم) و فروش (جنس ← تعداد ← قیمت ← تایید)
آگهی ۲۴ ساعت مهلت داره و نرفته برمی‌گرده دست فروشنده | خرید و فروش هر دو تاییدیه می‌خوان
همین‌جا دستور «هدیه قطعه افسانه‌ای N @یوزرنیم» هم هست (فعلاً فقط همین جنس قابل هدیه‌ست)
"""

import config
from database import session_scope
from keyboards import keyboards as kb
from services import market as mk_svc
from models import User
from services import seen as seen_svc, users
from telegram import Update
from telegram.ext import ContextTypes
from utils import esc, fa_dur, fa_num, money, now_utc
from datetime import timedelta

from handlers.common import chat_id_of, respond


# ───────── متن‌ها ─────────

def _home_text(n_open: int) -> str:
    # راند ۳۰ (متن قطعی کارفرما)
    return (
        "<b>🛒 مارکت تریاکی</b>\n\n"
        "اینجا بازیکن‌ها می‌تونن مستقیم با هم معامله کنن 🤝\n\n"
        "قابل فروش:\n"
        "🧩 قطعه افسانه‌ای\n"
        "🪵 چوب\n"
        "⛏️ آهن\n\n"
        f"📋 آگهی‌های فعال: {fa_num(n_open)}\n\n"
        f"⏳ هر آگهی تا {fa_num(config.MARKET_TTL_HOURS)} ساعت روی مارکت می‌مونه\n"
        "اگر فروش نره، آیتم‌ها خودکار و سالم به صاحبش برمی‌گردن 🔄"
    )


def _item_label(row, with_seller: bool = True) -> str:
    """لیبل ردیف آگهی: برای آگهی‌های خودم اسم فروشنده نمیاد (درخواست کارفرما راند ۲۷)"""
    it = config.MARKET_ITEMS[row.item]
    label = f"{it['name']} ×{fa_num(row.qty)} | {money(row.price)}"
    if with_seller:
        label += f" | {esc(row.seller_name)}"
    return label


def _buy_list_text(item: str | None, desc: bool, page: int, pages: int, n: int) -> str:
    # راند ۳۰ (متن قطعی کارفرما): هدر «مارکت» و فیلتر بدون ایموجی
    lines = ["<b>🛒 مارکت</b>", ""]
    if item:
        lines.append(f"🔍 فیلتر: {config.MARKET_ITEMS[item]['name'].split(' ', 1)[-1]}")
    lines.append("💰 مرتب‌سازی: " + ("گرون‌تر به ارزون‌تر" if desc else "ارزون‌تر به گرون‌تر"))
    lines.append("")
    if n:
        lines.append(f"📋 {fa_num(n)} آگهی بازه، صفحه {fa_num(page + 1)} از {fa_num(pages)}")
        lines.append("رو هر آگهی بزن تا فاکتورش بیاد بتونی تایید کنی")
    else:
        lines.append("فعلاً آگهی‌ای برای این بخش پیدا نشد 😅")
        lines.append("")
        lines.append("اگر دوست داری خودت آگهی ثبت کنی، از بخش «فروش» شروع کن 👇")
    return "\n".join(lines)


def _view_text(row) -> str:
    it = config.MARKET_ITEMS[row.item]
    return (
        f"<b>{it['name']}</b>\n\n"
        f"📦 تعداد: {fa_num(row.qty)}\n"
        f"💰 قیمت کل: {money(row.price)}\n"
        f"💸 دونه‌ای: {money(max(1, round(row.price / max(1, row.qty))))}\n\n"
        f"👤 فروشنده: {esc(row.seller_name)}\n\n"
        "خریدش می‌کنی؟"
    )


def _ttl_line(row) -> str:
    """زمان باقی‌مونده آگهی برای نمایش به خود فروشنده (راند ۲۶)"""
    left = (row.created_at + timedelta(hours=config.MARKET_TTL_HOURS)) - now_utc()
    secs = max(0, int(left.total_seconds()))
    return f"⏳ انقضای آگهی: {fa_dur(secs)} دیگه"


def _my_listings_text(rows) -> str:
    lines = ["<b>📋 آگهی‌های من</b>", ""]
    if not rows:
        # راند ۳۰ (متن قطعی کارفرما)
        lines.append("فعلاً هیچ آگهی فعالی نداری")
        lines.append("")
        lines.append("از بخش «🏷 فروش تو مارکت» اولین آگهی‌ت رو ثبت کن برای فروش 👇")
    else:
        for r in rows:
            it = config.MARKET_ITEMS[r.item]
            lines.append(f"{it['name']} ×{fa_num(r.qty)} | 💰 {money(r.price)}")
            lines.append(_ttl_line(r))
            lines.append("")
        lines.append("رو آگهی بزن تا لغوش کنی یا برگردی عقب")
    return "\n".join(lines).rstrip()


def _my_item_text(row) -> str:
    it = config.MARKET_ITEMS[row.item]
    return (
        f"<b>📋 آگهی من: {it['name']}</b>\n\n"
        f"📦 تعداد: {fa_num(row.qty)}\n"
        f"💰 قیمت کل: {money(row.price)}\n\n"
        f"{_ttl_line(row)}\n\n"
        "«لغو آگهی» بزنی جنس سالم برمی‌گرده تو انبارت"
    )


async def _n_open() -> int:
    async with session_scope() as s:
        n = await mk_svc.count_listings(s)
        await s.commit()
    return n


SELL_PICK_TEXT = (
    "<b>🏷 فروش تو مارکت</b>\n\n"
    "کدوم جنسو می‌خوای آگهی کنی؟ 🧩 قطعه افسانه‌ای، 🪵 چوب یا ⛏️ آهن\n"
    "بعد تعداد و قیمت کل رو ازت می‌پرسم و آخرش یه تاییدیه می‌گیری"
)


def _stock_line(user, item: str) -> str:
    it = config.MARKET_ITEMS[item]
    return f"{it['name']} الان {fa_num(mk_svc.qty_of(user, item))} تا داری"


# ───────── ورودی متنی ─────────

async def market_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        n_exp = await mk_svc.sweep_expired(s)
        n_open = await mk_svc.count_listings(s)
        await s.commit()
    return await respond(update, _home_text(n_open), kb.market_home_kb(n_open))


# ───────── روتر دکمه‌ها ─────────

async def market_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    seg = query.data.split(":")
    act = seg[1] if len(seg) > 1 else "h"
    a1 = seg[2] if len(seg) > 2 else "0"
    a2 = seg[3] if len(seg) > 3 else "a"

    if act == "noop":
        await query.answer()
        return

    if act == "h":
        async with session_scope() as s:
            await mk_svc.sweep_expired(s)
            n_open = await mk_svc.count_listings(s)
            await s.commit()
        return await respond(update, _home_text(n_open), kb.market_home_kb(n_open))

    # فیلتر سرچ: انتخاب آیتم
    if act == "f":
        desc = a1 == "e"
        return await respond(update, "🔍 <b>سرچ آیتم تو مارکت</b>\n\nدنبال کدوم جنسی؟", kb.market_filter_kb(desc))

    # لیست خرید با صفحه و مرتب‌سازی و فیلتر
    if act == "b":
        page = int(a1)
        desc = a2 == "e"
        flt = seg[4] if len(seg) > 4 and seg[4] != "x" else None
        async with session_scope() as s:
            await mk_svc.sweep_expired(s)
            rows, page, pages = await mk_svc.fetch_page(s, flt, page, desc)
            n = await mk_svc.count_listings(s, flt)
            kb_rows = [{"id": r.id, "label": _item_label(r)} for r in rows]
            text = _buy_list_text(flt, desc, page, pages, n)
            await s.commit()
        return await respond(update, text, kb.market_buy_kb(kb_rows, page, pages, desc, flt))

    # کارت یه آگهی + تایید خرید
    if act == "v":
        async with session_scope() as s:
            row = await mk_svc.get_listing(s, int(a1))
            if row is None:
                await s.commit()
                await query.answer("❌ این آگهی دیگه نیس، یا فروخته شده یا برگشته دست صاحبش", show_alert=True)
                return
            text = _view_text(row)
            await s.commit()
        return await respond(update, text, kb.market_listing_kb(int(a1)))

    # اجرای خرید بعد از تایید
    if act == "buy":
        async with session_scope() as s:
            me, _ = await users.get_or_create(s, update.effective_user)
            st, info = await mk_svc.buy_listing(s, me, int(a1))
            await s.commit()
        if st == "gone":
            await query.answer("❌ این آگهی دیگه نیس، دیر رسیدی", show_alert=True)
            async with session_scope() as s:
                n_open = await mk_svc.count_listings(s)
                await s.commit()
            return await respond(update, _home_text(n_open), kb.market_home_kb(n_open))
        if st == "own":
            return await query.answer("😅 آگهی خودته که، خریدن از خودت معنی نداره", show_alert=True)
        if st == "poor":
            return await query.answer(
                f"❌ پولت به این آگهی نمی‌رسه ({money(info['row'].price)})", show_alert=True)
        if st == "full":
            it_name = config.MARKET_ITEMS[info["row"].item]["name"]
            return await query.answer(
                f"🎒 انبارت جا نداره، {it_name} با «انبار» ظرفیتت رو بیشتر کن\n"
                f"({fa_num(info['have'])}/{fa_num(info['cap'])})",
                show_alert=True)
        it = config.MARKET_ITEMS[info["item"]]
        name = esc(users.display_name(me))
        await query.answer("✅ معامله انجام شد", show_alert=True)
        # راند ۲۶ (درخواست کارفرما): فروشنده تو پی‌وی خبر می‌گیره که جنسش فروخته
        seller_tg = None
        async with session_scope() as s2:
            su = await s2.get(User, info["seller_id"])
            seller_tg = su.telegram_id if su else None
            await s2.commit()
        if seller_tg:
            try:
                await context.bot.send_message(
                    seller_tg,
                    f"<b>🛒 جنست تو مارکت فروخته شد</b>\n\n"
                    f"آگهی: {it['name']} ×{fa_num(info['qty'])}\n"
                    f"قیمت: {money(info['price'])}\n"
                    f"خریدار: «{name}»\n\n"
                    f"💰 {money(info['price'])} واریز شد برات، حالشو ببر 😎",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        return await respond(
            update,
            # راند ۳۰ (متن قطعی کارفرما)، اسم‌ها با فونت خودشون خام میان
            f"<b>✅ خرید با موفقیت انجام شد</b>\n\n"
            f"{it['name']} ×{fa_num(info['qty'])} به انبار {name} اضافه شد\n"
            f"💸 {money(info['price'])} به حساب {esc(info['seller_name'])} واریز شد\n\n"
            "📩 فروشنده هم توی پی‌وی از فروش موفقش باخبر شد 🤝",
            kb.market_home_kb(0),
        )

    # شروع فروش: انتخاب جنس
    if act == "s":
        return await respond(update, SELL_PICK_TEXT, kb.market_sell_kb())

    # جنس انتخاب شد، تعداد رو با پیام بعدی می‌پرسیم
    if act == "si":
        item = a1
        if item not in config.MARKET_ITEMS:
            return
        async with session_scope() as s:
            me, _ = await users.get_or_create(s, update.effective_user)
            users.set_pending(me, "mkqty", item, chat_id_of(update))
            stock = _stock_line(me, item)
            await s.commit()
        it = config.MARKET_ITEMS[item]
        return await respond(
            update,
            f"<b>🏷 آگهی {it['name']}</b>\n\n"
            f"{stock}\n\n"
            "چند تا می‌خوای بفروشی؟ فقط عددشو بنویس، مثلا: 24\n\n"
            "❌ اگر هم پشیمون شدی بنویس «لغو»",
        )

    # تایید نهایی ثبت آگهی (از دکمه فاکتور)
    if act == "cfs":
        item, qty, price = a1, int(a2), int(seg[4])
        async with session_scope() as s:
            me, _ = await users.get_or_create(s, update.effective_user)
            ok, res = await mk_svc.create_listing(s, me, item, qty, price)
            await s.commit()
        it = config.MARKET_ITEMS.get(item, {"name": item})
        if not ok:
            if res == "nostock":
                return await query.answer(
                    f"❌ {fa_num(qty)} تا {it['name']} نداری، دوباره از اول با موجودی درست آگهی بساز",
                    show_alert=True,
                )
            return await query.answer(str(res), show_alert=True)
        async with session_scope() as s:
            n_open = await mk_svc.count_listings(s)
            await s.commit()
        return await respond(
            update,
            f"<b>✅ آگهیت ثبت شد</b>\n\n"
            f"{it['name']} ×{fa_num(qty)} به قیمت {money(price)}\n"
            f"⏳ تا {fa_num(config.MARKET_TTL_HOURS)} ساعت رو میزه، نرفته خودش سالم برمی‌گرده پیشت",
            kb.market_home_kb(n_open),
        )

    # لغو فاکتور فروش از دکمه
    if act == "cx":
        return await respond(update, "❌ آگهی لغو شد، جنست پیش خودت موند")

    # 📋 آگهی‌های من (راند ۲۶، درخواست کارفرما)
    if act == "my":
        async with session_scope() as s:
            me, _ = await users.get_or_create(s, update.effective_user)
            rows = await mk_svc.my_listings(s, me.id)
            kb_rows = [{"id": r.id, "label": _item_label(r, with_seller=False)} for r in rows]
            text = _my_listings_text(rows)
            await s.commit()
        return await respond(update, text, kb.market_my_kb(kb_rows))

    # کارت مدیریت یه آگهی خودم
    if act == "myv":
        async with session_scope() as s:
            me, _ = await users.get_or_create(s, update.effective_user)
            row = await mk_svc.get_listing(s, int(a1))
            if row is None or row.seller_id != me.id:
                await s.commit()
                return await query.answer("❌ این آگهی دیگه مال تو نیس", show_alert=True)
            text = _my_item_text(row)
            await s.commit()
        return await respond(update, text, kb.market_my_item_kb(int(a1)))

    # لغو آگهی خودم با استرداد جنس
    if act == "myx":
        async with session_scope() as s:
            me, _ = await users.get_or_create(s, update.effective_user)
            ok, row = await mk_svc.cancel_listing(s, me, int(a1))
            await s.commit()
        if not ok:
            return await query.answer("❌ این آگهی دیگه مال تو نیس", show_alert=True)
        it = config.MARKET_ITEMS[row.item]
        return await respond(
            update,
            f"<b>❌ آگهی لغو شد</b>\n\n"
            f"{it['name']} ×{fa_num(row.qty)} سالم برگشت تو انبارت",
            kb.market_home_kb(await _n_open()),
        )


# ───────── هدیه قطعه افسانه‌ای 🎁 ─────────

GIFT_GUIDE_TEXT = (
    "<b>🎁 هدیه قطعه افسانه‌ای</b>\n\n"
    "این‌جوری بنویس:\n"
    "«هدیه قطعه افسانه‌ای 1 @username»\n"
    "یا ریپلای روی پیام رفیقت: «هدیه قطعه افسانه‌ای 1»\n\n"
    "فعلاً فقط 🧩 قطعه افسانه‌ای قابل هدیه‌دادنه"
)

GIFT_NOT_FOUND_TEXT = (
    "🤷 این رفیقو پیدا نکردم\n"
    "روی پیامش ریپلای کن یا یوزرنیمشو بفرست (طرف هم باید ربات رو دیده باشه)"
)


async def _resolve_gift(update: Update, session):
    """هدف هدیه از ریپلای یا یوزرنیم یا آیدی عددی، باید اکانت ثبت‌شده داشته باشه"""
    reply = getattr(update.message, "reply_to_message", None)
    if reply and getattr(reply, "from_user", None):
        tg_id = getattr(reply.from_user, "id", None)
        if tg_id:
            return await users.get_by_tg(session, int(tg_id))
        return None
    words = (update.message.text or "").split()
    arg = words[-1].strip() if words else ""
    if arg.lstrip("-").isdigit():
        return await users.get_by_tg(session, int(arg))
    row = await seen_svc.find_by_username(session, arg)
    if row is None:
        return None
    return await users.get_by_tg(session, row.telegram_id)


async def gift_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import re
    from handlers.common import strip_bot_cmd

    text = strip_bot_cmd(update.message.text or "")
    m = re.search(r"هدیه\s+قطعه\s+افسانه‌ای\s+(\d+)", text)
    if not m:
        return await respond(update, GIFT_GUIDE_TEXT)
    n = int(m.group(1))

    async with session_scope() as s:
        me, _ = await users.get_or_create(s, update.effective_user)
        target = await _resolve_gift(update, s)
        if target is None:
            await s.commit()
            return await respond(update, GIFT_NOT_FOUND_TEXT)
        ok, why = await mk_svc.gift_parts(s, me, target, n)
        t_name = users.display_name(target)
        t_tg = target.telegram_id
        s_name = users.display_name(me)
        s_tg = me.telegram_id
        await s.commit()

    if not ok:
        return await respond(update, why)

    men = f'<a href="tg://user?id={t_tg}">{esc(t_name)}</a>'
    await respond(
        update,
        f"🎁 <b>هدیه رفت دست رفیقت</b>\n\n"
        f"🧩 قطعه افسانه‌ای ×{fa_num(n)} برای {men}\n"
        "بهش پیام دادم که هدیه از توئه 😉",
    )

    # خبر پی‌وی به گیرنده، مطابق متنی که کارفرما خواست
    smen = f'<a href="tg://user?id={s_tg}">{esc(s_name)}</a>'
    try:
        await context.bot.send_message(
            t_tg,
            f"دروددددد 👋 یه خبر خوبی دارم، {smen} برات هدیه فرستاد 🎁\n\n"
            f"کالا: {config.LEGENDARY_PART_NAME}\n"
            f"تعداد: {fa_num(n)}",
            parse_mode="HTML",
        )
    except Exception:
        pass
