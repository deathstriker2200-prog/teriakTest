"""
گرفتن ورودی معلق کاربر، بعد از «خرید سگ» اسم سگ | بعد از «ساخت کارتل» اسم کارتل | فروش منابع
تو گروه -1 رجیستر میشه (قبل از دستورهای متنی) و اگه ورودی مال pending بود
با ApplicationHandlerStop بقیه هندلرها رو متوقف می‌کنه
"""

import re

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

import config
from database import session_scope
from keyboards import keyboards as kb
from services import bank as bank_svc
from services import dogs as dog_svc
from services import resources as res_svc
from services import smuggle as smg
from services import teams, users
from utils import esc, fa_num, money, money_tp, normalize_fa, parse_amount

# متن‌هایی که دستورن و نباید به‌عنوان اسم قورت داده بشن («لغو» جداگانه هندل میشه)
_KNOWN_TEXTS = {
    "شاپ", "فروشگاه", "shop", "پروفایل", "profile", "حمله", "برداشت", "برداشت محصول",
    "مزرعه", "زمین هام", "زمین‌ها", "زمین‌های من", "سگ‌های من", "سگهای من",
    "راهنما", "help", "کنده کاری", "کنده کاری کارتلی", "استخراج کارتلی",
    "کوئست", "کوئست کارتل", "کوئست کارتلی", "استعلام کوئست", "کارتل", "کارتل من", "ترک کارتل",
    "انحلال کارتل", "ساخت کارتل", "رتبه", "رتبه بندی", "بانک", "واریز", "مارکت", "هدیه",
    "غارت", "غارت محموله", "کارتل ساختمان", "کارتل ساختمان ها", "کارتل ساخت", "کارتل پروفایل", "کارتل عضویت",
    "کارتل لیدربرد", "کارتل چالش", "کارتل کوئست", "کارتل بانک", "کارتل واریز", "تاس",
    "جستجو", "جست و جو", "آب و هوا", "وضعیت آب و هوا", "وضعیت هوا", "وضعیت هواشناسی", "وضعیت بازار",
    "بازار سیاه", "بازار", "هواشناسی", "پناهگاه", "مخفیگاه", "شرکت", "کارخانه", "قمار", "قمارخانه", "زمین", "لیدربرد", "رتبه بندی",
}

_KNOWN_PREFIXES = ("خرید", "کاشت", "جوین", "آمار", "کارتل ", "ست بیو", "بیو ", "واریز ", "برداشت ", "اسم سگ", "شرکت", "مخفیگاه", "آپگرید", "بانک ", "انتقال ", "هدیه ")


async def _save_bosspic(update: Update, context: ContextTypes.DEFAULT_TYPE, boss_key: str) -> None:
    """ذخیره عکس باس روی سرور + تایید به ادمین (جدا از capture که رفرش سشن راحت باشه)"""
    msg = update.message
    boss = config.BOSS_BY_KEY.get(boss_key)
    if boss is None:
        await msg.reply_html("❌ همچین باسی پیدا نکردم، از پنل دوباره شروع کن")
        return
    import os
    from services import boss as boss_svc
    os.makedirs(config.BOSS_IMAGE_DIR, exist_ok=True)
    photo_file = await context.bot.get_file(msg.photo[-1].file_id)
    await photo_file.download_to_drive(boss_svc.image_path(boss_key))
    async with session_scope() as s:
        await boss_svc.remember_image(s, boss_key)
        await s.commit()
    await msg.reply_html(
        f"✅ عکس {boss['emoji']} <b>{esc(boss['name'])}</b> تغییر کرد و رفت روی سرور\n"
        "از این به بعد کارتش با همین عکس اعلان میشه"
    )


async def capture_bcast_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پیام همگانی: رسانه (عکس | ویدیو | فایل و… حتی با کپشن) هم ورودیه، capture اصلی فقط متن خالص رو می‌گیره"""
    msg = update.message
    if msg is None or msg.text:
        return  # متن خالص رو capture اصلی می‌گیره

    from handlers.common import chat_id_of
    chat_id = chat_id_of(update)

    # ── عکس باس (راند ۲۳): عکس فرستاده‌شده ادمین میشه عکس باس و میره روی سرور ──
    _is_bosspic = False
    _boss_key = ""
    if getattr(msg, "photo", None):
        async with session_scope() as s:
            user = await users.get_by_tg(s, update.effective_user.id)
            if (user is not None and user.pending_action == "bosspic"
                    and update.effective_user.id in config.ADMIN_IDS
                    and not (user.pending_chat_id is not None and chat_id is not None and chat_id != user.pending_chat_id)):
                _is_bosspic = True
                _boss_key = user.pending_value or ""
                users.set_pending(user, None)
                await s.commit()
    if _is_bosspic:
        await _save_bosspic(update, context, _boss_key)
        raise ApplicationHandlerStop()

    async with session_scope() as s:
        user = await users.get_by_tg(s, update.effective_user.id)
        if user is None or user.pending_action != "bcast":
            return
        if user.pending_chat_id is not None and chat_id is not None and chat_id != user.pending_chat_id:
            return
        if update.effective_user.id not in config.ADMIN_IDS:
            users.set_pending(user, None)
            await s.commit()
            return
        users.set_pending(user, None)
        await s.commit()

    await update.message.reply_html(
        "<b>📣 پیام همگانی</b>\n\nبه کی بفرستمش؟",
        reply_markup=kb.broadcast_scope_kb(chat_id if chat_id else 0, update.message.message_id),
    )
    raise ApplicationHandlerStop()


async def capture(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if not text or text.startswith("/"):
        return

    from handlers.common import chat_id_of
    chat = update.effective_chat
    chat_id = chat_id_of(update)
    is_group = chat is not None and chat.type in ("group", "supergroup")

    # فعالیت فقط با «دستور» سنجیده میشه، چت عادی ملت تو گروه حساب نمیشه:
    # پیشوند تریاکی/تریاک/تی، کلیدواژه‌های شناخته‌شده و «لغو» دستور حساب میشن
    norm = normalize_fa(text)
    is_cmd = (
        norm.startswith(("تریاکی ", "تریاک ", "تی "))
        or norm == "لغو"
        or norm in _KNOWN_TEXTS
        or norm.startswith(_KNOWN_PREFIXES)
    )
    if is_cmd:
        from handlers.common import note_cmd
        note_cmd()  # نرخ سراسری «میانگین دستور تو دقیقه» آمار ادمین، گروه و پی‌وی فرقی نداره

    async with session_scope() as s:
        # ردیابی فعالیت گروه فقط وقتی دستوره، برای اعلان آب و هوا و اسپون کاروان و آمار ادمین
        if is_group and is_cmd:
            from services import world as world_svc
            await world_svc.touch_group(
                s, chat.id, getattr(chat, "title", None), user_tg=update.effective_user.id
            )
            await s.commit()

        user = await users.get_by_tg(s, update.effective_user.id)
        if user is None or not user.pending_action:
            return

        # ورودی معلق فقط تو همون چتی جواب داده میشه که شروع شده، چت دیگه کاملاً بی‌صدا رد میشه
        if user.pending_chat_id is not None and chat_id is not None and chat_id != user.pending_chat_id:
            return

        if norm.startswith(("تریاکی ", "تریاک ", "تی ")):
            return  # دستور با پیشوند رو نباید به عنوان ورودی معلق قورت بدن
        # اما «تریاک»/«تریاکی»/«تی» تنهایی دستور نیستن و می‌تونن اسم کارتل یا سگ باشن
        if norm != "لغو" and (norm in _KNOWN_TEXTS or norm.startswith(_KNOWN_PREFIXES)):
            return  # دستوره، بذار بقیه هندلرها بگیرنش

        action = user.pending_action

        # ── چت کارتل (راند ۲۰): پیام طرف میره تو چت داخلی کارتلش ──
        if action == "teamchat":
            from services import teams as team_svc
            ok, msg = await team_svc.chat_post(s, user, text)
            users.set_pending(user, None)
            team = await team_svc.get_team_of(s, user.id)
            page = await team_svc.chat_page(s, team) if team else f"❌ {msg}"
            await s.commit()
            await update.message.reply_html(page, reply_markup=kb.team_chat_kb())
            raise ApplicationHandlerStop()

        # ── لغو ──
        if norm == "لغو":
            msg = await dog_svc.cancel_pending(s, user)
            await s.commit()
            await update.message.reply_html(f"<b>{esc(msg)}</b>")
            raise ApplicationHandlerStop()

        # ── اسم سگ بعد از «خرید سگ»، فاکتور نهایی با نژاد و اسم و قیمت میاد ──
        if action == "dogname":
            dog_key = user.pending_value or ""
            cfg = config.DOGS.get(dog_key)
            if not cfg:
                users.set_pending(user, None)
                await s.commit()
                await update.message.reply_html("❌ مشکلی پیش اومد، دوباره از شاپ شروع کن")
                raise ApplicationHandlerStop()

            dogs = await dog_svc.get_user_dogs(s, user.id)
            ok, display, why = dog_svc.check_dog_name(dogs, text)
            if not ok:
                await s.commit()
                await update.message.reply_html(why)  # pending می‌مونه تا اسم درست بفرسته
                raise ApplicationHandlerStop()

            users.set_pending(user, None)
            await s.commit()
            await update.message.reply_html(
                f"<b>🐕 خرید {esc(cfg['breed'])}</b>\n\n"
                f"🐾 نژاد {esc(cfg['breed'])}\n"
                f"📛 اسم {esc(display)}\n"
                f"💸 قیمت {money(cfg['price'])}\n\n"
                "معامله‌ست؟",
                reply_markup=kb.tx_confirm_kb("dog", dog_key, update.effective_user.id, display),
            )
            raise ApplicationHandlerStop()

        # ── سرچ عضو برای اخراج (بعد از دکمه 👢 اخراج عضو تو مدیریت کارتل) ──
        if action == "teamkick":
            users.set_pending(user, None)
            await s.commit()
            from handlers import team as team_h
            await team_h.kick_search_respond(update, context, text)
            raise ApplicationHandlerStop()

        # ── تعداد خرید دونه‌ای چوب/آهن از شاپ: فاکتور با تایید/لغو میاد ──
        if action == "resbuy":
            res_key = user.pending_value or ""
            info = config.RES_SHOP.get(res_key)
            if not info:
                users.set_pending(user, None)
                await s.commit()
                await update.message.reply_html("❌ مشکلی پیش اومد، دوباره از شاپ شروع کن")
                raise ApplicationHandlerStop()

            qty = parse_amount(text)
            if qty is None:
                await s.commit()
                await update.message.reply_html(
                    "❌ فقط یه عدد صحیح بفرست، مثلا: 24\n\n❌ اگر هم پشیمون شدی بنویس «لغو»"
                )
                raise ApplicationHandlerStop()

            users.set_pending(user, None)
            total = info["unit"] * qty
            await s.commit()
            await update.message.reply_html(
                f"<b>🧾 فاکتور خرید {info['emoji']} {info['name']}</b>\n\n"
                f"🔢 تعداد: {fa_num(qty)} دونه\n"
                f"💸 قیمت هر دونه: {money_tp(info['unit'])}\n"
                f"💰 جمع فاکتور: {money(total)}\n\n"
                "معامله‌ست؟",
                reply_markup=kb.buyres_confirm_kb(res_key, qty),
            )
            raise ApplicationHandlerStop()

        # ── تعداد دلخواه ارسال محموله (بعد از دکمه ✏️ تعداد دلخواه تو صفحه ارسال) ──
        if action == "smqty":
            crop = user.pending_value or ""
            if crop not in config.SEEDS:
                users.set_pending(user, None)
                await s.commit()
                await update.message.reply_html("❌ مشکلی پیش اومد، دوباره از محصولات شروع کن")
                raise ApplicationHandlerStop()
            qty = parse_amount(text)
            if qty is None or qty < 1:
                await s.commit()
                await update.message.reply_html(
                    "❌ فقط یه عدد صحیح بفرست، مثلا: 12\n\n❌ اگر هم پشیمون شدی بنویس «لغو»"
                )
                raise ApplicationHandlerStop()
            row = (await smg.get_products(s, user.id)).get(crop)
            have = row.qty if row else 0
            sd = config.SEEDS[crop]
            if qty > have:
                await s.commit()
                await update.message.reply_html(
                    f"📦 {fa_num(qty)} تا {sd['name']} تو انبارت نداری، فقط {fa_num(have)} تا داری\n\n"
                    "❌ اگر هم پشیمون شدی بنویس «لغو»"
                )
                raise ApplicationHandlerStop()
            users.set_pending(user, None)
            value = int(row.value * qty / row.qty)
            await s.commit()
            await update.message.reply_html(
                smg.shipment_confirm_text(crop, qty, value),
                reply_markup=kb.ship_confirm_kb(crop, qty),
            )
            raise ApplicationHandlerStop()

        # ── تعداد دلخواه فروش به کاروان قاچاق (بعد از دکمه ✏️ تعداد دلخواه) ──
        if action == "smcqty":
            cv = await smg.get_caravan(s)
            if not cv:
                users.set_pending(user, None)
                await s.commit()
                await update.message.reply_html("🚚 کاروان جمع کرد و رفت")
                raise ApplicationHandlerStop()
            qty = parse_amount(text)
            if qty is None or qty < 1:
                await s.commit()
                await update.message.reply_html(
                    "❌ فقط یه عدد صحیح بفرست، مثلا: 12\n\n❌ اگر هم پشیمون شدی بنویس «لغو»"
                )
                raise ApplicationHandlerStop()
            crop = cv["crop"]
            row = (await smg.get_products(s, user.id)).get(crop)
            have = row.qty if row else 0
            sd = config.SEEDS[crop]
            if qty > have:
                await s.commit()
                await update.message.reply_html(
                    f"📦 {fa_num(qty)} تا {sd['name']} تو انبارت نداری، فقط {fa_num(have)} تا داری\n\n"
                    "❌ اگر هم پشیمون شدی بنویس «لغو»"
                )
                raise ApplicationHandlerStop()
            users.set_pending(user, None)
            gain = round(int(row.value * qty / row.qty) * (1 + cv["bonus"] / 100))
            await s.commit()
            await update.message.reply_html(
                smg.caravan_confirm_text(cv, qty, gain),
                reply_markup=kb.smcaravan_confirm_kb(qty),
            )
            raise ApplicationHandlerStop()

        # ── تعداد بذر (بعد از زدن روی بذر تو شاپ)، مثل فلوی آهن و چوب ──
        if action == "seedbuy":
            seed_key = user.pending_value or ""
            info = config.SEEDS.get(seed_key)
            if not info or info.get("legendary"):
                users.set_pending(user, None)
                await s.commit()
                await update.message.reply_html("❌ مشکلی پیش اومد، دوباره از شاپ شروع کن")
                raise ApplicationHandlerStop()

            qty = parse_amount(text)
            if qty is None:
                await s.commit()
                await update.message.reply_html(
                    "❌ فقط یه عدد صحیح بفرست، مثلا: 5\n\n❌ اگر هم پشیمون شدی بنویس «لغو»"
                )
                raise ApplicationHandlerStop()

            users.set_pending(user, None)
            from services import shop_svc as shop_svc2
            unit = shop_svc2.seed_unit_price(user, seed_key)
            total = unit * qty
            await s.commit()
            await update.message.reply_html(
                f"<b>🧾 فاکتور خرید {info.get('emoji', '🌱')} {esc(info['name'])}</b>\n\n"
                f"🔢 تعداد: {fa_num(qty)} بذر\n"
                f"💸 قیمت هر بذر: {money_tp(unit)}\n"
                f"💰 جمع فاکتور: {money(total)}\n"
                f"⏱ رشد هرکدوم {fa_num(info['grow_min'])} دقیقه | فروش هرساقه {money_tp(info['sell'])}\n\n"
                "معامله‌ست؟",
                reply_markup=kb.buyseed_confirm_kb(seed_key, qty),
            )
            raise ApplicationHandlerStop()

        # ── پیام همگانی ادمین (📣 از پنل): هر پیامی، دامنه و مدش با دکمه انتخاب میشه ──
        if action == "bcast":
            if update.effective_user.id not in config.ADMIN_IDS:
                users.set_pending(user, None)
                await s.commit()
                return
            users.set_pending(user, None)
            await s.commit()
            await update.message.reply_html(
                "<b>📣 پیام همگانی</b>\n\nبه کی بفرستمش؟",
                reply_markup=kb.broadcast_scope_kb(chat_id if chat_id else 0, update.message.message_id),
            )
            raise ApplicationHandlerStop()

        # ── مبلغ واریز/برداشت بانک (بعد از دکمه‌های «بانک») ──
        # ── مارکت (راند ۲۳): تعداد آگهی فروش، بعد قیمت کل ──
        if action == "mkqty":
            from services import market as mk_svc
            qty = parse_amount(text)
            if qty is None or qty <= 0:
                await update.message.reply_html("❌ فقط یه عدد صحیح بفرست، مثلا: 24\n\n❌ اگر هم پشیمون شدی بنویس «لغو»")
                raise ApplicationHandlerStop()
            item23 = user.pending_value or ""
            it23 = config.MARKET_ITEMS.get(item23)
            if it23 is None:
                users.set_pending(user, None)
                await s.commit()
                await update.message.reply_html("❌ مشکلی پیش اومد، دوباره از «مارکت» شروع کن")
                raise ApplicationHandlerStop()
            have23 = mk_svc.qty_of(user, item23)
            if have23 < qty:
                await update.message.reply_html(
                    f"❌ {fa_num(qty)} تا {it23['name']} نداری که، موجودیت {fa_num(have23)} تاست\n\n"
                    "❌ اگر هم پشیمون شدی بنویس «لغو»"
                )
                raise ApplicationHandlerStop()
            users.set_pending(user, "mkprice", f"{item23}:{qty}")
            await s.commit()
            await update.message.reply_html(
                f"<b>🏷 آگهی {it23['name']} ×{fa_num(qty)}</b>\n\n"
                f"قیمت کل آگهی رو بگو (تی‌پوینت)، مثلا: 50000\n\n"
                "❌ اگر هم پشیمون شدی بنویس «لغو»"
            )
            raise ApplicationHandlerStop()

        if action == "mkprice":
            price = parse_amount(text)
            if price is None or price <= 0:
                await update.message.reply_html("❌ قیمت کل رو فقط عدد بفرست، مثلا: 50000\n\n❌ اگر هم پشیمون شدی بنویس «لغو»")
                raise ApplicationHandlerStop()
            pv23 = (user.pending_value or "").split(":")
            qty23 = int(pv23[1]) if len(pv23) > 1 and pv23[1].isdigit() else 0
            item23 = pv23[0] if len(pv23) > 1 else ""
            it23 = config.MARKET_ITEMS.get(item23)
            users.set_pending(user, None)
            await s.commit()
            if it23 is None or qty23 <= 0:
                await update.message.reply_html("❌ مشکلی پیش اومد، دوباره از «مارکت» شروع کن")
                raise ApplicationHandlerStop()
            await update.message.reply_html(
                # راند ۳۰ (متن قطعی کارفرما)
                f"<b>🏷 ثبت آگهی فروش</b>\n\n"
                f"{it23['name']} ×{fa_num(qty23)}\n"
                f"💰 قیمت: {money(price)}\n\n"
                "بعد از ثبت، آیتم‌ها از انبارت کم می‌شن و وارد مارکت می‌شن 🛒\n"
                f"⏳ اگر تا {fa_num(config.MARKET_TTL_HOURS)} ساعت فروش نرن، بدون هیچ مشکلی به انبارت برمی‌گردن\n\n"
                "آگهی ثبت بشه؟ 👇",
                reply_markup=kb.market_sell_confirm_kb(item23, qty23, price),
            )
            raise ApplicationHandlerStop()

        if action in ("bankdep", "bankwd"):
            amount = parse_amount(text)
            if amount is None:
                await update.message.reply_html("❌ فقط عددشو بفرست، مثلا: 1200\n\n❌ اگر هم پشیمون شدی بنویس «لغو»")
                raise ApplicationHandlerStop()

            users.set_pending(user, None)
            if action == "bankdep":
                ok, res = await bank_svc.deposit(s, user, amount)
            else:
                ok, res = await bank_svc.withdraw(s, user, amount)
            cash, bal = user.cash, user.bank_balance
            await s.commit()

            if ok:
                await update.message.reply_html(
                    f"<b>{esc(res)}</b>\n\n🏦 موجودی بانک: {money(bal)}\n💵 نقدینگی: {money(cash)}"
                )
            else:
                await update.message.reply_html(res)
            raise ApplicationHandlerStop()

        # ── انتقال بانکی: شماره حساب مقصد (بعد از دکمه 💳 انتقال موجودی) ──
        if action == "trf_to":
            target = await bank_svc.get_by_bank_acc(s, text)
            if target is not None and target.telegram_id == user.telegram_id:
                await update.message.reply_html(
                    "😅 به حساب خودت که لازم نیس انتقال بدی، برداشت عادی بزن\n"
                    "شماره حساب طرف مقصدو بفرست\n\n"
                    "❌ اگر هم پشیمون شدی بنویس «لغو»"
                )
                raise ApplicationHandlerStop()  # pending سر جاش، شماره درست بفرست
            if target is None:
                await update.message.reply_html(
                    "❌ همچین شماره حسابی پیدا نکردم، چک کن دوباره بفرست\n\n"
                    "❌ اگر هم پشیمون شدی بنویس «لغو»"
                )
                raise ApplicationHandlerStop()  # pending سر جاش
            users.set_pending(user, "trf_amt", str(target.telegram_id))
            tgt_name = esc(users.display_name(target))
            await s.commit()
            await update.message.reply_html(
                f"<b>💳 انتقال به حساب «{tgt_name}»</b>\n\n"
                f"چقد تی‌پوینت میخوای بهش واریز کنی؟\n"
                f"عددشو همینجا بنویس و بفرست، از {fa_num(config.TRF_MIN_AMOUNT)} تا {fa_num(config.TRF_MAX_AMOUNT)}، مثلا: 8000\n\n"
                "❌ اگر هم پشیمون شدی بنویس «لغو»"
            )
            raise ApplicationHandlerStop()

        # ── انتقال بانکی: مبلغ و فاکتور نهایی با اسم گیرنده ──
        if action == "trf_amt":
            amount = parse_amount(text)
            if amount is None:
                await update.message.reply_html(f"❌ فقط عددشو بفرست، مثلا: 8000\n\n❌ اگر هم پشیمون شدی بنویس «لغو»")
                raise ApplicationHandlerStop()
            target = await users.get_by_tg(s, int(user.pending_value or 0))
            if target is None:
                users.set_pending(user, None)
                await s.commit()
                await update.message.reply_html("❌ طرف پیدا نشد، از اول شروع کن")
                raise ApplicationHandlerStop()
            if amount < config.TRF_MIN_AMOUNT:
                await update.message.reply_html(
                    f"❌ حداقل انتقال باید {money(config.TRF_MIN_AMOUNT)} باشه، بیشتر بگو\n\n"
                    "❌ اگر هم پشیمون شدی بنویس «لغو»"
                )
                raise ApplicationHandlerStop()  # pending سر جاش تا بیشتر بفرسته
            if amount > config.TRF_MAX_AMOUNT:
                await update.message.reply_html(
                    f"❌ حداکثر انتقال باید {money(config.TRF_MAX_AMOUNT)} باشه، کمتر بگو\n\n"
                    "❌ اگر هم پشیمون شدی بنویس «لغو»"
                )
                raise ApplicationHandlerStop()  # pending سر جاش تا کمتر بفرسته
            left = bank_svc.trf_cooldown_left(user)
            if left > 0:
                users.set_pending(user, None)
                await s.commit()
                await update.message.reply_html(f"⏳ تازه انتقال دادی، تا {fa_num(left)} ثانیه دیگه نمیتونی انتقال بدی")
                raise ApplicationHandlerStop()
            if amount > user.bank_balance:
                await update.message.reply_html(
                    f"❌ تو بانک این همه نداری، موجودیت {money(user.bank_balance)} ـه\n"
                    "یه عدد کوچیک‌تر بفرست\n\n"
                    "❌ اگر هم پشیمون شدی بنویس «لغو»"
                )
                raise ApplicationHandlerStop()  # pending سر جاش تا کمتر بفرسته
            tgt_name0 = esc(users.display_name(target))
            cap_room = bank_svc.bank_capacity(target.bank_level) - target.bank_balance
            if amount > cap_room:
                if cap_room <= 0:
                    users.set_pending(user, None)
                    await s.commit()
                    await update.message.reply_html(f"🏦 بانک «{tgt_name0}» کاملاً پره، الان امکان واریز به حسابش نیست")
                    raise ApplicationHandlerStop()
                await update.message.reply_html(
                    f"🏦 بانک «{tgt_name0}» فقط {money(cap_room)} جای خالی داره، کمتر بگو\n\n"
                    "❌ اگر هم پشیمون شدی بنویس «لغو»"
                )
                raise ApplicationHandlerStop()
            users.set_pending(user, None)
            tgt_name = esc(users.display_name(target))
            bal_after = user.bank_balance - amount
            await s.commit()
            await update.message.reply_html(
                f"<b>💳 تاییدیه انتقال</b>\n\n"
                f"💸 مبلغ: {money(amount)}\n"
                f"🔢 شماره حساب: <code>{target.bank_acc or ''}</code>\n"
                f"👤 حساب به نام «{tgt_name}» هست\n\n"
                f"🏦 موجودی بانکت بعد انتقال: {money(bal_after)}\n\n"
                "از انتقال اطمینان داری؟",
                reply_markup=kb.confirm_kb(f"tbf:{target.telegram_id}:{amount}"),
            )
            raise ApplicationHandlerStop()

        # ── مبلغ هدیه ادمین به یه کاربر دیگه (از کارت /user) ──
        if action in ("admtp", "admxp"):
            if update.effective_user.id not in config.ADMIN_IDS:
                users.set_pending(user, None)
                await s.commit()
                return

            amount = parse_amount(text)
            if amount is None:
                await update.message.reply_html("❌ فقط عددشو بفرست، مثلا: 5000\n\n❌ اگر هم پشیمون شدی بنویس «لغو»")
                raise ApplicationHandlerStop()

            target_tg = int(user.pending_value or 0)
            target = await users.get_by_tg(s, target_tg)
            users.set_pending(user, None)
            if target is None:
                await s.commit()
                await update.message.reply_html("❌ طرف پیدا نشد")
                raise ApplicationHandlerStop()

            name = esc(users.display_name(target))
            if action == "admtp":
                target.cash += amount
                cash = target.cash
                await s.commit()
                await update.message.reply_html(
                    f"<b>💰 {money(amount)} واریز شد به {name}</b>\n\n"
                    f"موجودی جدیدش {money(cash)}"
                )
            else:
                notes = users.add_xp(target, amount)
                level = target.level
                await s.commit()
                out = f"<b>✨ {fa_num(amount)} تجربه دادی به {name}</b>\n\n⭐ الان لول {fa_num(level)} ـه"
                await update.message.reply_html(out)
                from handlers.common import announce_notes
                await announce_notes(update, notes)
            raise ApplicationHandlerStop()

        # ── کانال عضویت اجباری بعد از دکمه ست کردن (فقط ادمین) ──
        if action == "fjchan":
            if update.effective_user.id not in config.ADMIN_IDS:
                users.set_pending(user, None)
                await s.commit()
                return

            from services import forcejoin as fj_svc
            parsed = fj_svc.parse_input(text)
            if not parsed:
                await update.message.reply_html(
                    "❌ فرمت درست نیس، یوزرنیم یا لینک کانال رو بفرست\n"
                    "مثلا <code>@mychannel</code> یا <code>https://t.me/mychannel</code>\n"
                    "کانال خصوصی: <code>-1001234567890 https://t.me/+AbCdEfGh</code>\n\n"
                    "❌ اگر هم پشیمون شدی بنویس «لغو»",
                )
                raise ApplicationHandlerStop()

            channel, link = parsed
            await fj_svc.set_channel(s, channel, link)
            users.set_pending(user, None)
            await s.commit()
            await update.message.reply_html(
                f"<b>✅ عضویت اجباری فعال شد</b>\n\n"
                f"▫️ کانال: <code>{esc(channel)}</code>\n"
                f"▫️ لینک: {esc(link)}\n\n"
                "از این لحظه هر دستوری قبل از اجرا چک عضویت میشه\n"
                "⚠️ یادت نره ربات رو توی کانال ادمین کنی، وگر نه چک کار نمی‌کنه",
            )
            raise ApplicationHandlerStop()

        # ── فروش منابع از مخفیگاه (بعد از دکمه 💰 فروش منابع)، «آهن 300» یا «چوب 200» ──
        if action == "ressell":
            m = re.match(r"^(چوب|آهن)\s+(\S+)$", norm)
            amount = parse_amount(m.group(2)) if m else None
            res = None
            if m and amount is not None:
                res = "wood" if m.group(1) == "چوب" else "iron"

            help_txt = (
                "❌ فرمت درست نیس، اینجوری بنویس\n\n"
                "«آهن 300»\n«چوب 200»\n\n"
                "❌ اگر هم پشیمون شدی بنویس «لغو»"
            )
            if res is None:
                await update.message.reply_html(help_txt)  # pending می‌مونه تا درست بفرسته
                raise ApplicationHandlerStop()

            have = getattr(user, res, 0)
            name = "چوب" if res == "wood" else "آهن"
            emoji = "🪵" if res == "wood" else "⛏️"
            if amount > have:
                await update.message.reply_html(
                    f"❌ فقط {fa_num(have)} تا {name} داری، {fa_num(amount)} تا نمی‌تونی بفروشی\n\n"
                    "❌ اگر هم پشیمون شدی بنویس «لغو»"
                )  # pending می‌مونه تا عدد درست بفرسته
                raise ApplicationHandlerStop()

            from services import world as world_svc
            mults30, _ = await world_svc.market_mults(s)
            total = amount * res_svc.sell_price_market(mults30, res)  # راند ۳۰: با ضریب بازار سیاه
            users.set_pending(user, None)
            await s.commit()
            await update.message.reply_html(
                f"<b>💰 فروش {fa_num(amount)} تا {name}</b>\n\n"
                f"{emoji} قیمت فروشش میشه {money(total)}\n"
                f"💵 بعد فروش {money(user.cash + total)} داری\n\n"
                "می‌فروشیم؟",
                reply_markup=kb.sellres_confirm_kb(res, amount),
            )
            raise ApplicationHandlerStop()

        # ── اسم کارتل بعد از «ساخت کارتل»، فاکتور تایید ساخت میاد ──
        if action == "teamname":
            ok_name, clean, why = teams.validate_team_name(text)
            if not ok_name:
                await s.commit()
                await update.message.reply_html(why)  # pending می‌مونه تا اسم درست بفرسته
                raise ApplicationHandlerStop()
            if await teams.get_team_by_name(s, clean):
                await s.commit()
                await update.message.reply_html(f"🏴 کارتلی با اسم «{esc(clean)}» از قبل هست، یه اسم دیگه بفرست")
                raise ApplicationHandlerStop()

            display = " ".join(str(text).split())
            users.set_pending(user, "teamcf", display[:48], chat_id)
            await s.commit()
            await update.message.reply_html(
                f"<b>🏴 ساخت کارتل «{esc(display)}»</b>\n\n"
                f"💸 هزینه ساخت {money(config.TEAM_CREATE_COST)}\n"
                f"👑 تو رهبرش میشی و {fa_num(config.TEAM_CAP_TABLE[0])} نفر جا داره\n"
                "لول کارتل که با تجربه اعضا بره بالا جای اعضا بیشتر میشه\n\n"
                "می‌سازیمش؟",
                reply_markup=kb.team_create_confirm_kb(update.effective_user.id),
            )
            raise ApplicationHandlerStop()
