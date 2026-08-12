"""
بانک شخصی 🏦، «تریاکی بانک» با دکمه‌های واریز/برداشت | «تریاکی واریز 1200» | «تریاکی برداشت 1200»
پول بانک موقع حمله دزدیده نمیشه، واریز/برداشت با دکمه، مبلغ رو با پیام بعدی می‌پرسه
"""

from telegram import Update
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import chat_id_of, parts, respond, strip_bot_cmd
from keyboards import keyboards as kb
from services import users
from services import bank as bank_svc
from utils import bar, esc, fa_num, money, parse_amount


def _bank_text(user) -> str:
    cap = bank_svc.bank_capacity(user.bank_level)
    return (
        "<b>🏦 بانک شخصی</b>\n\n"
        f"💳 شماره بانک: <code>{user.bank_acc or ''}</code>\n"
        "<i>برای واریز به حسابت، همین شماره رو به طرف بده</i>\n\n"
        f"💰 موجودی بانک: {money(user.bank_balance)}\n"
        f"📦 ظرفیت {bar(user.bank_balance, cap)} {fa_num(user.bank_balance)}/{fa_num(cap)}\n"
        f"⭐ لول بانک {fa_num(user.bank_level)}\n\n"
        "🛡 پولی که تو بانکه موقع حمله دزدیده نمیشه، امنه\n\n"
        "💰 واریز با «تریاکی واریز 1200» یا «بانک واریز 1200»\n"
        "💸 برداشت با «تریاکی برداشت 1200» یا «بانک برداشت 1200»\n"
        "💳 انتقال با «انتقال 4000 E86YF2»"
    )


async def render_bank(update: Update, alert: str | None = None, extra: str | None = None) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.apply_energy_regen(user)
        text = _bank_text(user)
        if extra:
            text += f"\n\n{extra}"
        markup = kb.bank_kb(user)
        await s.commit()
    await respond(update, text, markup, alert=alert)


async def bank_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_bank(update)


# ───────── انتقال موجودی به حساب دیگه 💳 ─────────

async def bank_transfer_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه انتقال موجودی، شماره حساب مقصد رو با پیام بعدی می‌پرسه"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        if user.pending_action:
            alert = "⏳ اول کار قبلیتو تموم کن یا «لغو» بزن"
            await s.commit()
            return await render_bank(update, alert=alert)
        left = bank_svc.trf_cooldown_left(user)
        if left > 0:
            alert = f"⏳ تازه انتقال دادی، تا {fa_num(left)} ثانیه دیگه نمیتونی انتقال بدی"
            await s.commit()
            return await render_bank(update, alert=alert)
        users.set_pending(user, "trf_to", "", chat_id_of(update))
        await s.commit()
    await respond(
        update,
        "<b>💳 انتقال موجودی به حساب دیگه</b>\n\n"
        "به حساب کی میخوای پول واریز کنی؟\n"
        "شماره حسابشو همینجا بنویس و بفرست، مثلا: F8L6XS\n\n"
        "❌ اگر هم پشیمون شدی بنویس «لغو»",
    )


async def bank_transfer_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تایید نهایی انتقال (دکمه ✅ فاکتور)، پول از بانک خودت به بانک طرف میره"""
    _, tgt, amt = parts(update)  # tbf:<telegram_id>:<amount>
    target_tg, amount = int(tgt), int(amt)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        target = await users.get_by_tg(s, target_tg)
        if target is None:
            await s.commit()
            return await render_bank(update, alert="❌ طرف پیدا نشد")
        ok, res = await bank_svc.transfer_to(s, user, target, amount)
        name = esc(users.display_name(target))
        sender_name = esc(users.display_name(user))
        bal, t_bal = user.bank_balance, target.bank_balance
        await s.commit()
    if not ok:
        return await render_bank(update, alert=res)
    # به گیرنده خبر بدیم، واسه فرستنده کارت بانک ادیت میشه
    bot = getattr(context, "bot", None)
    if bot is not None:
        try:
            from telegram.error import BadRequest, Forbidden
        except Exception:
            BadRequest = Forbidden = Exception
        try:
            await bot.send_message(
                target_tg,
                "<b>💳 یه انتقال به حسابت اومد</b>\n\n"
                f"💰 {money(amount)} از طرف «{sender_name}»\n"
                f"🏦 موجودی بانک: {money(t_bal)}",
                parse_mode="HTML",
            )
        except (BadRequest, Forbidden):
            pass
        except Exception:
            pass
    await render_bank(update, alert=f"✅ {res}", extra=f"💳 {res}")


# ───────── دستورهای متنی «واریز n» / «برداشت n» ─────────

async def _amount_cmd(update: Update, action: str, sample: str) -> int | None:
    """خواندن مبلغ از آخرین توکن عددی دستور («تریاکی واریز 1200» و «بانک واریز 1200» هر دو)، نامعتبر → راهنما و None"""
    txt = strip_bot_cmd(update.message.text or "")
    amount = None
    for tok in reversed(txt.split()):
        amount = parse_amount(tok)
        if amount is not None:
            break
    if amount is None:
        await respond(update, f"❌ مبلغو درست بگو، مثلا «{sample}»")
    return amount


async def deposit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    amount = await _amount_cmd(update, "dep", "تریاکی واریز 1200")
    if amount is None:
        return
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg = await bank_svc.deposit(s, user, amount)
        bal, cash = user.bank_balance, user.cash
        await s.commit()
    if not ok:
        return await respond(update, msg)
    await respond(
        update,
        f"<b>{esc(msg)}</b>\n\n🏦 موجودی بانک: {money(bal)}\n💵 نقدینگی: {money(cash)}",
    )


async def transfer_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«انتقال 4000 E86YF2»، بدون دکمه و مستقیم با شماره حساب، فاکتور نهایی با دکمه تایید میاد"""
    txt = strip_bot_cmd(update.message.text or "")
    amount = None
    code = None
    for tok in txt.split()[1:]:
        a = parse_amount(tok)
        if a is not None and amount is None:
            amount = a
        elif a is None and code is None:
            code = tok
    if amount is None or code is None:
        return await respond(update, "💳 این‌جوری بنویس: «انتقال 4000 E86YF2»\nیعنی اول مبلغ بعد شماره حساب طرف")

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        target = await bank_svc.get_by_bank_acc(s, code)
        if target is None:
            await s.commit()
            return await respond(update, "❌ همچین شماره حسابی پیدا نکردم، چک کن دوباره بنویس")
        if target.telegram_id == user.telegram_id:
            await s.commit()
            return await respond(update, "😅 به حساب خودت که لازم نیس انتقال بدی، برداشت عادی بزن")
        if amount < config.TRF_MIN_AMOUNT:
            await s.commit()
            return await respond(update, f"❌ حداقل انتقال باید {money(config.TRF_MIN_AMOUNT)} باشه، بیشتر بگو")
        if amount > config.TRF_MAX_AMOUNT:
            await s.commit()
            return await respond(update, f"❌ حداکثر انتقال باید {money(config.TRF_MAX_AMOUNT)} باشه، کمتر بگو")
        left = bank_svc.trf_cooldown_left(user)
        if left > 0:
            await s.commit()
            return await respond(update, f"⏳ تازه انتقال دادی، تا {fa_num(left)} ثانیه دیگه نمیتونی انتقال بدی")
        if amount > user.bank_balance:
            await s.commit()
            return await respond(update, f"❌ تو بانک این همه نداری، موجودیت {money(user.bank_balance)} ـه")
        tgt_name = esc(users.display_name(target))
        room = bank_svc.bank_capacity(target.bank_level) - target.bank_balance
        if room <= 0:
            await s.commit()
            return await respond(update, f"🏦 بانک «{tgt_name}» کاملاً پره، الان امکان واریز به حسابش نیست")
        if amount > room:
            await s.commit()
            return await respond(update, f"🏦 بانک «{tgt_name}» فقط {money(room)} جای خالی داره، کمتر بگو")
        bal_after = user.bank_balance - amount
        acc = target.bank_acc or ""
        await s.commit()

    await respond(
        update,
        "<b>💳 تاییدیه انتقال</b>\n\n"
        f"💸 مبلغ: {money(amount)}\n"
        f"🔢 شماره حساب: <code>{acc}</code>\n"
        f"👤 حساب به نام «{tgt_name}» هست\n\n"
        f"🏦 موجودی بانکت بعد انتقال: {money(bal_after)}\n\n"
        "از انتقال اطمینان داری؟",
        kb.confirm_kb(f"tbf:{target.telegram_id}:{amount}"),
    )


async def withdraw_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    amount = await _amount_cmd(update, "wd", "تریاکی برداشت 1200")
    if amount is None:
        return
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg = await bank_svc.withdraw(s, user, amount)
        bal, cash = user.bank_balance, user.cash
        await s.commit()
    if not ok:
        return await respond(update, msg)
    await respond(
        update,
        f"<b>{esc(msg)}</b>\n\n💵 نقدینگی: {money(cash)}\n🏦 موجودی بانک: {money(bal)}",
    )


# ───────── دکمه‌های واریز/برداشت، مبلغ با پیام بعدی ─────────

async def bank_ask_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه 💰 واریز / 💸 برداشت، اکشن معلق می‌ذاره و مبلغ می‌خواد (با دکمه آماده)"""
    action = update.callback_query.data.split(":")[1]  # dep | wd
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        if user.pending_action:
            alert = "⏳ اول کار قبلیتو تموم کن یا «لغو» بزن"
            await s.commit()
            return await render_bank(update, alert=alert)
        users.set_pending(
            user, "bankdep" if action == "dep" else "bankwd", "",
            chat_id_of(update),
        )
        await s.commit()

    if action == "dep":
        text = (
            "<b>💰 مبلغ واریز به بانک</b>\n\n"
            "چقد تی‌پوینت میخوای بزاری بانک؟\n"
            "عددشو همینجا بنویس و بفرست، مثلا: 1200\n"
            "یا اینکه از گزینه‌های زیر یکی رو انتخاب کن\n\n"
            "❌ اگر هم پشیمون شدی بنویس «لغو»"
        )
    else:
        text = (
            "<b>💰 مبلغ برداشت از بانک</b>\n\n"
            "چقد تی‌پوینت میخوای برداشت کنی؟\n"
            "عددشو همینجا بنویس و بفرست، مثلا: 1200\n"
            "یا اینکه از گزینه‌های زیر یکی رو انتخاب کن\n\n"
            "❌ اگر هم پشیمون شدی بنویس «لغو»"
        )
    await respond(update, text, kb.bank_amount_kb(action))


async def bank_quick_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌های آماده سوال بانک (کل موجودی | نصف موجودی)، کار معلق رو هم جمع می‌کنه"""
    _, action, which = parts(update)  # bankq:dep|wd : all|half
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        if user.pending_action in ("bankdep", "bankwd"):
            users.set_pending(user, None)

        if action == "dep":
            cap = bank_svc.bank_capacity(user.bank_level)
            amount = min(user.cash, max(0, cap - user.bank_balance))
            if amount <= 0:
                await s.commit()
                if user.bank_balance >= cap:
                    return await render_bank(update, alert="🏦 بانکت پره دیگه، اول ارتقاش بده")
                return await render_bank(update, alert="💵 نقدینگی نداری که واریز کنی")
            ok, res = await bank_svc.deposit(s, user, amount)
        else:
            amount = user.bank_balance if which == "all" else user.bank_balance // 2
            if amount <= 0:
                await s.commit()
                return await render_bank(update, alert="🏦 بانکت خالیه، چیزی برای برداشت نیس")
            ok, res = await bank_svc.withdraw(s, user, amount)

        bal, cash = user.bank_balance, user.cash
        await s.commit()

    if not ok:
        return await render_bank(update, alert=res)
    await render_bank(
        update, alert=res,
        extra=f"🏦 موجودی بانک: {money(bal)}\n💵 نقدینگی: {money(cash)}",
    )


# ───────── ارتقای بانک ─────────

async def bank_upgrade_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        if user.bank_level >= config.BANK_MAX_LEVEL:
            await s.commit()
            return await render_bank(update, alert="⭐ بانکت مکس لوله")
        price = bank_svc.bank_upgrade_price(user.bank_level)
        cap_now = bank_svc.bank_capacity(user.bank_level)
        cap_next = bank_svc.bank_capacity(user.bank_level + 1)
        level = user.bank_level
        await s.commit()

    text = (
        f"<b>⬆️ ارتقای بانک، از لول {fa_num(level)} به {fa_num(level + 1)}</b>\n\n"
        f"💸 هزینه {money(price)}\n"
        f"📦 ظرفیت {fa_num(cap_now)} ← {fa_num(cap_next)}\n\n"
        "انجامش بدیم؟"
    )
    await respond(update, text, kb.confirm_kb("cf:bank:up"))


async def bank_upgrade_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, msg = await bank_svc.upgrade_bank(s, user)
        await s.commit()
    if ok:
        return await render_bank(update, alert="⬆️ بانک ارتقا پیدا کرد", extra=msg)
    await render_bank(update, alert=msg)
