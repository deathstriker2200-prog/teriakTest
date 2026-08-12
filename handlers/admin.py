"""
پنل ادمین، دادن پول و XP به خودت + مدیریت کاربرا
/user @silktoch یا /user 123456789 یا /user بخشی‌از‌اسم → پیدا کردن و دیدن پروفایل و پول/XP دادن
/addtp [آیدی عددی] [مبلغ] | /addxp [آیدی عددی] [مقدار] → دادن مستقیم
/addseed [آیدی عددی] [اسم محصول] [تعداد] → دادن محصول برای تست ارسال محموله
به غریبه‌ها کاملاً بی‌صداس
"""

import asyncio
import time

from telegram import Update
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import chat_id_of, parts, respond
from keyboards import keyboards as kb
from services import economy, users
from services import forcejoin as fj_svc
from services import teams as team_svc
from services import world as world_svc
from utils import esc, fa_num, jalali_str, money, now_utc, parse_amount


def _is_admin(update: Update) -> bool:
    return bool(update.effective_user) and update.effective_user.id in config.ADMIN_IDS


def _panel_text(user, extra: str | None = None) -> str:
    text = (
        "<b>👑 پنل ادمین</b>\n\n"
        f"💵 {money(user.cash)}\n"
        f"⭐ لول {fa_num(user.level)} | ✨ {fa_num(user.xp)} از {fa_num(economy.xp_need(user.level))}\n\n"
        "چی بر داری؟\n\n"
        "<b>دستورهای مدیریتی:</b>\n"
        "👤 <code>/user @username</code> یا <code>/user 123456789</code> یا بخشی از اسم، پیداش کن، پروفایلش رو ببین و از همونجا پول/XP بده\n"
        "💵 <code>/addtp 123456789 5000</code>، واریز مستقیم تی‌پوینت\n"
        "✨ <code>/addxp 123456789 100</code>، دادن مستقیم تجربه\n"
        "💎 <code>/addgem 123456789 50</code>، دادن مستقیم جم\n"
        "🏴 <code>/addxpgroup اسم کارتل 500</code>، دادن مستقیم XP به یه کارتل (آیدی عددی کارتل هم قبوله)\n"
        "💸 <code>/detp 123456789 5000</code> و <code>/dexp 123456789 100</code>، کم کردن مستقیم سکه و تجربه\n"
        "🌿 <code>/addseed 123456789 ماری جوانا 3</code>، دادن محصول به خودت یا بقیه برای تست محموله (ارزش هر دونه = قیمت پایه فروش)\n"
        "🧨 <code>/clearacc 123456789</code> یا یوزرنیم یا اسم، ریست کامل اکانت به حالت روز اول (با تاییدیه)\n"
        "🔧 /botdown و /botup، خاموش و روشن کلی ربات (مد تعمیر)\n"
        "👻 /hideboard، نامرئی شدن از همه لیدربردها (دوباره بزنی برمی‌گرده)\n"
        "📣 «پیام همگانی» از دکمه پایین، پیامت فوروارد یا ارسال میشه به گروه‌ها | پی‌وی‌ها | همه\n"
        "🔄 /update، به‌روزرسانی فوری وضعیت بازی: لود دوباره کانفیگ، رول بازار، بازخوانی ظرفیت کارتل‌ها و ریست کش‌ها (آب‌وهوا دست نمی‌خوره)\n"
        "💾 /backup و /upload_backup، بک‌آپ و ری‌استور\n"
        "🔌 /botoff و /boton توی گروه، خاموش و روشن کردن ربات فقط تو همون گروه"
    )
    if extra:
        text += f"\n\n{extra}"
    return text


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return  # ادمین به پلیرهای عادی واکنش نشون نمیده

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        text = _panel_text(user)
        await s.commit()

    await respond(update, text, kb.admin_kb())


# ───────── پیام همگانی 📣 ─────────

async def broadcast_scope_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """انتخاب دامنه پیام همگانی → بعدش مد ارسال پرسیده میشه"""
    if not _is_admin(update):
        await update.callback_query.answer()
        return
    p = parts(update)  # bcs:scope:src_chat:src_msg
    scope, src_chat, src_msg = p[1], p[2], p[3]
    label = {"g": "👥 فقط گروه‌ها", "p": "👤 فقط پی‌وی‌ها", "a": "📣 همه"}.get(scope, "📣 همه")
    text = (
        "<b>📣 پیام همگانی</b>\n\n"
        f"🎯 دامنه: {label}\n\n"
        "چطور بره؟\n"
        "📤 فوروارد، با تگ فوروارد از طرف تو\n"
        "✉️ ارسال، از طرف خود ربات و بدون تگ"
    )
    await respond(update, text, kb.broadcast_mode_kb(scope, src_chat, src_msg))


async def broadcast_mode_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """شروع ارسال تو بک‌گراند، گزارش پیشرفت و نتیجه همینجا ادیت میشه"""
    if not _is_admin(update):
        await update.callback_query.answer()
        return
    p = parts(update)  # bcm:mode:scope:src_chat:src_msg
    mode, scope, src_chat, src_msg = p[1], p[2], int(p[3]), int(p[4])
    chat = update.effective_chat
    msg = update.callback_query.message
    await respond(update, "<b>📣 پیام همگانی</b>\n\n⏳ دارم می‌فرستم، تموم شد گزارش همینجا میاد")
    asyncio.create_task(broadcast_run(
        context.bot, chat.id, msg.message_id, mode, scope, src_chat, src_msg,
    ))


async def broadcast_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لغو پیام همگانی"""
    if not _is_admin(update):
        await update.callback_query.answer()
        return
    await respond(update, "<b>😅 پیام همگانی بی‌خیال شد</b>")


async def broadcast_run(bot, admin_chat: int, admin_msg: int, mode: str, scope: str,
                        src_chat: int, src_msg: int) -> dict:
    """
    ارسال همگانی به هدف‌ها با مکث بین هر ارسال (نه ربات لگ می‌گیره نه تلگرام محدود می‌کنه)
    mode: f (فوروارد) | t (کپی بدون تگ) | scope: g (گروه) | p (پی‌وی) | a (همه)
    """
    from telegram.error import BadRequest, Forbidden

    from models import GroupActivity
    from models import User as _User

    async with session_scope() as s:
        from sqlalchemy import select as _sel
        groups = list((await s.execute(_sel(GroupActivity.chat_id))).scalars()) if scope in ("g", "a") else []
        pvs = list((await s.execute(_sel(_User.telegram_id))).scalars()) if scope in ("p", "a") else []
        await s.commit()

    targets = [("👥", c) for c in groups] + [("👤", c) for c in pvs]
    total = len(targets)
    scope_label = {"g": "👥 فقط گروه‌ها", "p": "👤 فقط پی‌وی‌ها", "a": "📣 گروه‌ها و پی‌وی‌ها"}.get(scope, "📣")
    ok = fail = 0

    async def _progress(i: int) -> None:
        try:
            await bot.edit_message_text(
                chat_id=admin_chat, message_id=admin_msg,
                text=f"<b>📣 پیام همگانی</b>\n\n⏳ {fa_num(i)} از {fa_num(total)} ارسال شد…",
                parse_mode="HTML",
            )
        except Exception:
            pass

    for i, (_, tgt) in enumerate(targets, 1):
        try:
            if mode == "f":
                await bot.forward_message(chat_id=tgt, from_chat_id=src_chat, message_id=src_msg)
            else:
                await bot.copy_message(chat_id=tgt, from_chat_id=src_chat, message_id=src_msg)
            ok += 1
        except (BadRequest, Forbidden):
            fail += 1
        except Exception:
            fail += 1
        if i % 15 == 0:
            await _progress(i)
        await asyncio.sleep(config.BROADCAST_DELAY_SECONDS)

    try:
        await bot.edit_message_text(
            chat_id=admin_chat, message_id=admin_msg,
            text=(
                "<b>✅ پیام همگانی تموم شد</b>\n\n"
                f"🎯 دامنه: {scope_label}\n"
                f"📤 موفق: {fa_num(ok)} | ❌ خطا: {fa_num(fail)}\n"
                f"📊 کل مقصدها: {fa_num(total)}"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass
    return {"ok": ok, "fail": fail, "total": total}


async def _user_card_text(session, target) -> str:
    """کارت پروفایل یه کاربر برای پنل ادمین (راند ۳۰: قدرت/جم/سلاح هم اضافه شد)"""
    from services import combat as cbt30, dogs as dogs30
    name = esc(users.display_name(target))
    uname = f"@{esc(target.username)}" if target.username else "بدون یوزرنیم"
    team = await team_svc.get_team_of(session, target.id)
    team_line = f"\n🏴 کارتل «{esc(team.name)}»" if team else ""
    joined = jalali_str(target.created_at) if target.created_at else "—"
    lvls30 = await users.get_item_levels(session, target.id)
    ammo30 = await users.get_ammo_map(session, target.id)
    dogs30l = await dogs30.get_user_dogs(session, target.id)
    atk30, dfn30 = cbt30.combat_stats(target, lvls30, dogs30l, ammo=ammo30)
    wkey30 = cbt30.weapon_choice(target, lvls30)
    akey30 = cbt30.armor_choice(target, lvls30)
    wname30 = esc((config.WEAPONS.get(wkey30) or {}).get("name", "👊 دست خالی")) if wkey30 else "👊 دست خالی"
    aname30 = esc((config.ARMORS.get(akey30) or {}).get("name", "🦺 بدون زره")) if akey30 else "🦺 بدون زره"
    return (
        f"<b>👤 {name}</b>\n\n"
        f"🆔 {uname} | <code>{target.telegram_id}</code>\n"
        f"⭐ لول {fa_num(target.level)} | ✨ {fa_num(target.xp)} از {fa_num(economy.xp_need(target.level))}\n"
        f"💵 نقدی {money(target.cash)}\n"
        f"💎 جم {fa_num(target.gems or 0)}\n"
        f"💪 حمله {fa_num(atk30)} | 🛡 دفاع {fa_num(dfn30)}\n"
        f"🔫 {wname30}\n"
        f"🦺 {aname30}\n"
        f"🏦 بانک {money(target.bank_balance)} (لول {fa_num(target.bank_level)})\n"
        f"🏚 انبار لول {fa_num(target.shelter_level)}{team_line}\n"
        f"✅ برد {fa_num(target.wins)} | ❌ باخت {fa_num(target.losses)}\n"
        f"🗓 عضو {joined}"
    )


# ───────── /user، پیدا کردن کاربر ─────────

async def user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return

    query = " ".join(context.args or []).strip()
    if not query:
        return await update.message.reply_html(
            "❌ فرم درست: <code>/user @username</code> یا <code>/user 123456789</code> یا <code>/user بخشی از اسم</code>"
        )

    async with session_scope() as s:
        found = await users.search_users(s, query)
        if not found:
            await s.commit()
            return await update.message.reply_html(f"🤷 کسی با «{esc(query)}» پیدا نشد")

        if len(found) == 1:
            target = found[0]
            text = await _user_card_text(s, target)
            tg_id = target.telegram_id
            await s.commit()
            return await update.message.reply_html(text, reply_markup=kb.admin_user_kb(tg_id))

        names = "\n".join(f"▫️ {esc(users.display_name(u))} | <code>{u.telegram_id}</code>" for u in found)
        await s.commit()

    await update.message.reply_html(
        f"<b>👥 {fa_num(len(found))} نفر پیدا شدن</b>\n\n{names}\n\nروش بزن تا کارتش رو ببینی 👇",
        reply_markup=kb.admin_users_kb(found),
    )


# ───────── /addtp و /addxp، دادن مستقیم ─────────

async def hideboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تاگل حالت نامرئی لیدربرد برای ادمین، دوباره بزنی برمی‌گرده"""
    if not _is_admin(update):
        return
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        user.lb_hidden = 0 if user.lb_hidden else 1
        hidden = bool(user.lb_hidden)
        await s.commit()
    if hidden:
        text = "👻 نامرئی شدی، دیگه تو لیدربردها دیده نمیشی\nبرای برگشت دوباره /hideboard بزن"
    else:
        text = "👀 برگشتی، از این به بعد تو لیدربردها دیده میشی"
    await update.message.reply_html(text)


async def update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    🔄 /update، فقط ادمین: به‌روزرسانی فوری وضعیت بازی
    کانفیگ رو از روی فایل دوباره لود می‌کنه (تغییرای دستی سریع اعمال بشن)،
    بازار رو فورس رول می‌کنه، ظرفیت کارتل‌ها رو بازخوانی می‌کنه و کش‌های حافظه رو ریست
    آب‌وهوا دست‌نخورده می‌مونه و سر مرزهای ساعت ایران خودش عوض میشه
    """
    if not _is_admin(update):
        return  # غیرادمین کاملاً بی‌صدا

    import importlib

    from sqlalchemy import func as sa_func, select as sa_select
    from models import Team, TeamMember

    reload_ok = True
    try:
        importlib.reload(config)  # عددهای config.py بدون ری‌استارت اعمال بشن
    except Exception:
        reload_ok = False

    async with session_scope() as s:
        market_rolled = await world_svc.ensure_market(s, force=True)
        # سطح کارتل‌های قدیمی روی منحنی سخت‌تر بازنشانی میشه (فقط یه بار اجرا میشه)
        migrated_n = await team_svc.migrate_team_levels(s)
        # شخصیت سگ‌ها هم با همین آپدیت پاک میشه (سیستم شخصیت حذف شده)
        from models import Dog as _Dog
        from sqlalchemy import update as sa_update
        dogs_wiped = (await s.execute(
            sa_update(_Dog).where(_Dog.personality.isnot(None)).values(personality=None)
        )).rowcount or 0
        # زمین‌دارای قدیمی که قدم «اولین زمین» آنبوردینگشون گیر کرده، ثبت اولین زمین
        from models import Plot as _Plot, User as _User
        owner_ids = set((await s.execute(sa_select(_Plot.user_id))).scalars().all())
        plot_fixed = 0
        if owner_ids:
            q_stuck = sa_select(_User).where(_User.id.in_(owner_ids), _User.first_plot_at.is_(None))
            for u in (await s.execute(q_stuck)).scalars():
                u.first_plot_at = now_utc()
                plot_fixed += 1
        # امتیاز مهارتِ بازیکن‌هایی که هنوز هیچ امتیازی خرج نکردن به مقدار درست لولشون به‌روز میشه
        # (پس‌دررو: به‌ازای هر لولی که دارن، با بونوس لول ۱۰ و ۲۰)، خرج‌کرده‌ها سر جاشون می‌مونن
        q_sk = sa_select(_User).where(
            _User.skill_points.isnot(None),
            _User.skill_power == 0, _User.skill_speed == 0,
            _User.skill_defense == 0, _User.skill_loot == 0,
        )
        skills_fixed = 0
        for u in (await s.execute(q_sk)).scalars():
            expect = users.expected_skill_points(u.level or 1)
            if (u.skill_points or 0) != expect:
                u.skill_points = expect
                skills_fixed += 1
        # ظرفیت کارتل‌ها داینامیک از لول حساب میشه؛ اینجا بازخوانی و گزارش سرریز
        all_teams = (await s.execute(sa_select(Team))).scalars().all()
        over: list[tuple[str, int, int]] = []
        for t in all_teams:
            n = (await s.execute(sa_select(sa_func.count(TeamMember.id)).where(TeamMember.team_id == t.id))).scalar() or 0
            cap = team_svc.team_capacity(t)
            if n > cap:
                over.append((t.name, n, cap))
        # لقب‌ها ذخیره نمیشن و زنده از روی لول حساب میشن، با ریلود کانفیگ اسم جدید 💎 Teriaky Lord روی همه افتاده
        titled_n = (await s.execute(sa_select(sa_func.count(_User.id)))).scalar() or 0
        await s.commit()

    # کش‌های حافظه ریست بشن تا وضعیت‌های قدیمی (ستینگ گیت | عضویت کاربرا) تازه بشن
    fj_svc.invalidate_settings()
    fj_svc.invalidate_members()

    lines = [
        "<b>🔄 وضعیت بازی به‌روز شد</b>",
        "",
        "⚙️ کانفیگ دوباره لود شد" if reload_ok else "⚠️ لود دوباره کانفیگ خطا داد، مقادیر قبلی موندن",
        f"📈 بازار: {'رول فوری انجام شد و قیمت‌ها تازه حساب شدن' if market_rolled else 'بدون تغییر'}",
        f"👥 ظرفیت {fa_num(len(all_teams))} کارتل بازخوانی شد",
    ]
    if migrated_n:
        lines.append(f"⭐ سطح {fa_num(migrated_n)} کارتل روی منحنی سخت‌تر بازنشانی شد")
    else:
        lines.append("✅ سطح کارتل‌ها از قبل روی منحنی جدیده")
    if dogs_wiped:
        lines.append(f"🐕 شخصیت {fa_num(dogs_wiped)} سگ پاک شد (سیستم شخصیت حذف شده)")
    else:
        lines.append("🐕 سگ‌ها دیگه شخصیت ندارن")
    if plot_fixed:
        lines.append(f"🌱 آنبوردینگ زمین {fa_num(plot_fixed)} بازیکن گیرکرده فیکس شد")
    else:
        lines.append("🌱 آنبوردینگ زمین همه اوکیه")
    if skills_fixed:
        lines.append(f"🎖 امتیاز مهارت {fa_num(skills_fixed)} بازیکنِ خرجنکرده به مقدار درست لولشون به‌روز شد")
    else:
        lines.append("🎖 امتیاز مهارت‌ها از قبل به‌روزه")
    if over:
        lines.append(
            f"⚠️ {fa_num(len(over))} کارتل سرریز ظرفیت دارن: "
            + "، ".join(f"{name} ({fa_num(n)}/{fa_num(c)})" for name, n, c in over[:5])
        )
    else:
        lines.append("✅ هیچ کارتلی سرریز ظرفیت نیس")
    lines.append(f"🏅 لقب {fa_num(titled_n)} بازیکن به‌روزه (خودکار از روی لول، لول 20: 💎 Teriaky Lord)")
    lines.append("🧹 کش تنظیمات گیت و عضویت کاربرا ریست شد")
    lines.append("🌦 آب‌وهوا دست‌نخورده موند، سر مرزهای ساعت ایران عوض میشه")
    await update.message.reply_html("\n".join(lines))


async def addxpgroup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    ✨ /addxpgroup [اسم کارتل] [مقدار]، فقط ادمین: دادن مستقیم XP به یه کارتل
    اسم کارتل می‌تونه چندکلمه‌ای باشه، مقدار آخرین آرگومانه؛ با آیدی عددی کارتل هم کار می‌کنه
    """
    if not _is_admin(update):
        return
    args = context.args or []
    amount = parse_amount(args[-1]) if len(args) >= 2 else None
    if amount is None or amount <= 0:
        return await update.message.reply_html(
            "❌ فرم درست: <code>/addxpgroup اسم کارتل 500</code>\n"
            "اسم کارتل (چندکلمه‌ای هم اوکی) یا آیدی عددیش + مقدار xp آخرش"
        )

    from models import Team

    query = " ".join(args[:-1])
    async with session_scope() as s:
        team = None
        if query.isdigit():
            team = await s.get(Team, int(query))
        if team is None:
            team = await team_svc.get_team_by_name(s, query)
        if team is None:
            await s.commit()
            return await update.message.reply_html(f"🤷 کارتلی با اسم «{esc(query)}» پیدا نشد")
        notes = await team_svc.give_team_xp(s, team, int(amount))
        t_name, t_level, t_xp, t_cap = team.name, team.level or 1, team.xp or 0, team_svc.team_capacity(team)
        await s.commit()

    lines = [
        f"✨ <b>{fa_num(int(amount))}</b> XP به کارتل «{esc(t_name)}» دادی",
        "",
        f"⭐ لول کارتل الان {fa_num(t_level)} ـه (✨ {fa_num(t_xp)})",
        f"👥 ظرفیت اعضا {fa_num(t_cap)} نفر",
    ]
    await update.message.reply_html("\n".join(lines))
    # تبریک لول‌آپ کارتل (اگه لول‌آپ کرد) به‌صورت پیام جدا
    if notes:
        await update.message.reply_html("\n\n".join(notes))


async def addtp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    args = context.args or []
    if len(args) < 2 or not args[0].lstrip("-").isdigit() or parse_amount(args[1]) is None:
        return await update.message.reply_html(
            "❌ فرم درست: <code>/addtp 123456789 5000</code>\n"
            "آیدی عددی طرف + مبلغ"
        )

    tg_id = int(args[0])
    amount = parse_amount(args[1])
    async with session_scope() as s:
        target = await users.get_by_tg(s, tg_id)
        if target is None:
            await s.commit()
            return await update.message.reply_html("❌ کاربری با این آیدی تو بازی نیس")
        target.cash += amount
        name = esc(users.display_name(target))
        cash = target.cash
        await s.commit()

    await update.message.reply_html(
        f"<b>💰 {money(amount)} واریز شد به {name}</b>\n\n"
        f"موجودی جدیدش {money(cash)}"
    )


async def addgem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """💎 /addgem <آیدی> <تعداد> جم می‌ده (راند ۲۷)"""
    if not _is_admin(update):
        return
    args = context.args or []
    if len(args) < 2 or not args[0].lstrip("-").isdigit() or not args[1].isdigit():
        return await update.message.reply_html(
            "❌ فرم درست: <code>/addgem 123456789 50</code>\n"
            "آیدی عددی طرف + تعداد جم"
        )

    tg_id = int(args[0])
    amount = int(args[1])
    async with session_scope() as s:
        target = await users.get_by_tg(s, tg_id)
        if target is None:
            await s.commit()
            return await update.message.reply_html("❌ کاربری با این آیدی تو بازی نیس")
        target.gems = (target.gems or 0) + amount
        name = esc(users.display_name(target))
        gems = target.gems
        await s.commit()

    await update.message.reply_html(
        f"<b>💎 {fa_num(amount)} جم واریز شد به {name}</b>\n\n"
        f"موجودی جدیدش 💎 {fa_num(gems)} جم"
    )


async def addxp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    args = context.args or []
    if len(args) < 2 or not args[0].lstrip("-").isdigit() or parse_amount(args[1]) is None:
        return await update.message.reply_html(
            "❌ فرم درست: <code>/addxp 123456789 100</code>\n"
            "آیدی عددی طرف + مقدار تجربه"
        )

    tg_id = int(args[0])
    amount = parse_amount(args[1])
    async with session_scope() as s:
        target = await users.get_by_tg(s, tg_id)
        if target is None:
            await s.commit()
            return await update.message.reply_html("❌ کاربری با این آیدی تو بازی نیس")
        notes = users.add_xp(target, amount)
        name = esc(users.display_name(target))
        level = target.level
        await s.commit()

    text = f"<b>✨ {fa_num(amount)} تجربه دادی به {name}</b>\n\n⭐ الان لول {fa_num(level)} ـه"
    await update.message.reply_html(text)
    # پیام تبریک لول‌آپ جدا میاد، قاطی گزارش ادمین نمیشه
    from handlers.common import announce_notes
    await announce_notes(update, notes)


# ───────── /addseed، دادن محصول برای تست ارسال محموله ─────────

_ADDSEED_ALIASES = {
    "ماری جوانا": "marijuana", "ماریجوانا": "marijuana", "ماری‌جوانا": "marijuana",
    "قارچ": "gharch", "پیوت": "peyote", "کراتوم": "kratom",
    "خشخاش": "khashkhash", "خشخاش سیاه": "khashkhash",
    "تریاک": "teriak", "کوکائین": "cocaine", "کوکایین": "cocaine",
    "جهنم": "jahannam", "بذر جهنم": "jahannam",
    "ابلیس": "eblis", "بذر ابلیس": "eblis",
    "جهش یافته": "mutant", "جهش‌یافته": "mutant", "موتانت": "mutant",
}


async def addseed_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🌿 /addseed [آیدی] [اسم محصول] [تعداد]، فقط ادمین | محصول با قیمت پایه میره انبار طرف"""
    if not _is_admin(update):
        return
    from utils import normalize_fa
    args = [normalize_fa(a) for a in (context.args or [])]
    qty = parse_amount(args[-1]) if args else None
    if len(args) < 3 or not args[0].lstrip("-").isdigit() or qty is None:
        return await update.message.reply_html(
            "❌ فرم درست: <code>/addseed 123456789 ماری جوانا 3</code>\n"
            "آیدی عددی طرف + اسم محصول + تعداد"
        )
    crop = _ADDSEED_ALIASES.get(" ".join(args[1:-1]).strip())
    if crop is None:
        return await update.message.reply_html(
            "🤷 این محصول رو نمی‌شناسم\n\n"
            + " | ".join(sd["name"] for sd in config.SEEDS.values())
        )

    tg_id = int(args[0])
    async with session_scope() as s:
        target = await users.get_by_tg(s, tg_id)
        if target is None:
            await s.commit()
            return await update.message.reply_html("❌ کاربری با این آیدی تو بازی نیس")
        from services import smuggle as smg_svc
        sd = config.SEEDS[crop]
        unit = economy.crop_yield(crop, 1, target.level)
        added, added_val = await smg_svc.add_product(
            s, target.id, crop, qty, unit * qty, target.shelter_level
        )
        name = esc(users.display_name(target))
        cap = smg_svc.products_cap(target.shelter_level or 0)
        await s.commit()
    lost = qty - added
    text = (
        f"<b>{sd.get('emoji', '🌱')} {fa_num(added)} تا {sd['name']} به {name} اضافه شد</b>\n\n"
        f"💰 ارزش هر دونه ~{money(unit)} | مجموع {money(added_val)}\n"
        f"📦 ظرفیت انبارش برای هر محصول {fa_num(cap)} تاست"
    )
    if lost:
        text += f"\n⚠️ انبارش پر بود، {fa_num(lost)} تا جا نداشت و نابود شد"
    await update.message.reply_html(text)


# ───────── ردیابی دوره‌ای بازیکن 🕵 (لاگ خلاصه هر ۱۰ دقیقه به چت لاگ) ─────────

async def tracklog_start_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«لاگ @یوزر» شروع ردیابی یه بازیکن تا خلاصه دوره‌ای به چت لاگ بره، فقط ادمین"""
    if not _is_admin(update):
        return
    from services import tracklog as tl
    query = (update.message.text or "").strip().split()[-1].lstrip("@").strip()
    if not query or query == "لاگ":
        return await respond(update, "🤷 این‌جوری بنویس: «لاگ @یوزرنیم» (آیدی عددی یا بخشی از اسم هم میشه)")
    async with session_scope() as s:
        found = await users.search_users(s, query)
        if not found:
            await s.commit()
            return await respond(update, "🤷 کسی با این مشخصات تو بازی پیدا نشد")
        msg = await tl.start(s, found[0])
        await s.commit()
    await respond(update, msg)


async def tracklog_stop_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«توقف لاگ @یوزر» خاموش کردن ردیابی + پاک شدن آمار جاری، فقط ادمین"""
    if not _is_admin(update):
        return
    from services import tracklog as tl
    query = (update.message.text or "").strip().split()[-1].lstrip("@").strip()
    if not query or query in ("لاگ", "توقف"):
        return await respond(update, "🤷 این‌جوری بنویس: «توقف لاگ @یوزرنیم»")
    async with session_scope() as s:
        found = await users.search_users(s, query)
        if not found:
            await s.commit()
            return await respond(update, "🤷 کسی با این مشخصات تو بازی پیدا نشد")
        msg = await tl.stop(s, found[0])
        await s.commit()
    await respond(update, msg)

# ───────── /detp و /dexp، کم کردن مستقیم ─────────

async def detp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    args = context.args or []
    if len(args) < 2 or not args[0].lstrip("-").isdigit() or parse_amount(args[1]) is None:
        return await update.message.reply_html(
            "❌ فرم درست: <code>/detp 123456789 5000</code>\n"
            "آیدی عددی طرف + مبلغ"
        )

    tg_id = int(args[0])
    amount = parse_amount(args[1])
    async with session_scope() as s:
        target = await users.get_by_tg(s, tg_id)
        if target is None:
            await s.commit()
            return await update.message.reply_html("❌ کاربری با این آیدی تو بازی نیس")
        target.cash = max(0, target.cash - amount)
        name = esc(users.display_name(target))
        cash = target.cash
        await s.commit()

    await update.message.reply_html(
        f"<b>💸 {money(amount)} از {name} کم شد</b>\n\n"
        f"موجودی جدیدش {money(cash)}"
    )


async def dexp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    args = context.args or []
    if len(args) < 2 or not args[0].lstrip("-").isdigit() or parse_amount(args[1]) is None:
        return await update.message.reply_html(
            "❌ فرم درست: <code>/dexp 123456789 100</code>\n"
            "آیدی عددی طرف + مقدار تجربه"
        )

    tg_id = int(args[0])
    amount = parse_amount(args[1])
    async with session_scope() as s:
        target = await users.get_by_tg(s, tg_id)
        if target is None:
            await s.commit()
            return await update.message.reply_html("❌ کاربری با این آیدی تو بازی نیس")
        target.xp = max(0, target.xp - amount)
        name = esc(users.display_name(target))
        xp = target.xp
        await s.commit()

    await update.message.reply_html(
        f"<b>✨ {fa_num(amount)} تجربه از {name} کم شد</b>\n\n"
        f"⭐ الان ✨ {fa_num(xp)} تجربه داره"
    )


# ───────── /clearacc، ریست کامل اکانت ─────────

async def clearacc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return

    query = " ".join(context.args or []).strip()
    if not query:
        return await update.message.reply_html(
            "❌ فرم درست: <code>/clearacc 123456789</code> یا <code>/clearacc @username</code> یا بخشی از اسم"
        )

    async with session_scope() as s:
        found = await users.search_users(s, query)
        if not found:
            await s.commit()
            return await update.message.reply_html(f"🤷 کسی با «{esc(query)}» پیدا نشد")
        if len(found) > 1:
            names = "\n".join(f"▫️ {esc(users.display_name(u))} | <code>{u.telegram_id}</code>" for u in found)
            await s.commit()
            return await update.message.reply_html(
                f"<b>👥 {fa_num(len(found))} نفر پیدا شدن، دقیق‌تر بگو:</b>\n\n{names}"
            )
        target = found[0]
        name = esc(users.display_name(target))
        uname = f"@{esc(target.username)}" if target.username else "بدون یوزرنیم"
        tg_id = target.telegram_id
        level, cash = target.level, target.cash
        await s.commit()

    text = (
        "<b>🧨 ریست اکانت</b>\n\n"
        f"می‌خوای حساب «{name}» ({uname} | <code>{tg_id}</code>) رو کامل پاک کنی؟\n\n"
        f"⭐ لول {fa_num(level)} و 💵 {money(cash)} و همه زمین‌ها و سگ‌ها و آیتم‌هاش می‌پره\n"
        f"برمی‌گرده به حالت روز اول با {money(config.START_CASH)}\n\n"
        "انجامش بدیم؟"
    )
    await update.message.reply_html(text, reply_markup=kb.clearacc_confirm_kb(tg_id))


async def clearacc_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تایید/لغو ریست اکانت، فقط ادمین"""
    if not _is_admin(update):
        await update.callback_query.answer()
        return
    _, action, raw = parts(update)
    tg_id = int(raw)

    if action == "no":
        return await respond(update, "<b>😅 بی‌خیال ریست شدیم</b>\n\nاکانت دست نخورده موند", kb.admin_kb())

    async with session_scope() as s:
        target = await users.get_by_tg(s, tg_id)
        if target is None:
            await s.commit()
            return await respond(update, "❌ طرف دیگه تو بازی نیس", kb.admin_kb())
        name = esc(users.display_name(target))
        await users.wipe_account(s, target)
        await s.commit()

    await respond(
        update,
        f"<b>✅ اکانت «{name}» ریست شد</b>\n\n"
        f"همه چیش پاک شد، الان مثل روز اوله\n"
        f"💰 {money(config.START_CASH)} تو جیبشه",
        kb.admin_kb(),
    )
    # به خود طرف هم خبر بدیم، استارت کرده باشه
    try:
        await context.bot.send_message(
            tg_id,
            "<b>🔄 اکانتت ریست شد</b>\n\n"
            f"حسابت توسط مدیریت به حالت روز اول برگشت\n"
            f"💰 دوباره با {money(config.START_CASH)} شروع می‌کنی",
            parse_mode="HTML",
        )
    except Exception:
        pass


# ───────── دکمه‌های پنل (خودی + کارت کاربر) ─────────

async def admin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.callback_query.answer()
        return

    _, kind, value = parts(update)
    num = int(value)

    # ── برگشت به پنل ──
    if kind == "panel":
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            text = _panel_text(user)
            await s.commit()
        return await respond(update, text, kb.admin_kb())

    # ── 📊 آمار ربات ──
    if kind == "stats":
        text = await _stats_text(context.bot)
        # آخرین پیام آمار یادش می‌مونه تا جاب ساعتی خودکار ادیتش کنه
        _m = update.callback_query.message if update.callback_query else None
        _cid, _mid = getattr(_m, "chat_id", None), getattr(_m, "message_id", None)
        if _cid is not None and _mid is not None:
            await _remember_stats_msg(_cid, _mid)
        return await respond(update, text, kb.admin_stats_kb())

    # ── 📢 عضویت اجباری ──
    if kind == "fj":
        return await respond(update, await _fj_text(), await _fj_kb())

    if kind == "fjtog":
        async with session_scope() as s:
            st = await fj_svc.get_settings(s)
            await fj_svc.set_enabled(s, not st["on"])
            await s.commit()
        return await respond(update, await _fj_text(), await _fj_kb(),
                             alert="وضعیت عضویت اجباری عوض شد ✅")

    if kind == "fjdel":
        async with session_scope() as s:
            await fj_svc.clear_channel(s)
            await s.commit()
        return await respond(update, await _fj_text(), await _fj_kb(),
                             alert="کانل عضویت اجباری پاک شد 🗑")

    if kind == "fjset":
        async with session_scope() as s:
            me, _ = await users.get_or_create(s, update.effective_user)
            users.set_pending(me, "fjchan", None, chat_id_of(update))
            await s.commit()
        return await respond(
            update,
            "<b>🔗 ست کردن کانال عضویت اجباری</b>\n\n"
            "یوزرنیم یا لینک کانال رو بفرست، مثلا:\n"
            "▫️ <code>@mychannel</code>\n"
            "▫️ <code>https://t.me/mychannel</code>\n\n"
            "کانال خصوصی؟ آیدی عددی + لینک دعوت بفرست:\n"
            "▫️ <code>-1001234567890 https://t.me/+AbCdEfGh</code>\n\n"
            "⚠️ ربات باید توی کانال ادمین باشه تا بتونه عضویت رو چک کنه\n\n"
            "❌ اگر هم پشیمون شدی بنویس «لغو»",
        )

    # ── شروع فلو پیام همگانی، متن/مدیای بعدی ادمین میشه پیام ──
    if kind == "bcast":
        async with session_scope() as s:
            me, _ = await users.get_or_create(s, update.effective_user)
            users.set_pending(me, "bcast", None, chat_id_of(update))
            await s.commit()
        return await respond(
            update,
            "<b>📣 پیام همگانی</b>\n\n"
            "پیامتو بفرست، هر چی باشه (متن | عکس | ویدیو | فایل) همون می‌رسه به ملت\n\n"
            "❌ اگر هم پشیمون شدی بنویس «لغو»",
        )

    # ── کارت یه کاربر ──
    if kind == "u":
        async with session_scope() as s:
            target = await users.get_by_tg(s, num)
            if target is None:
                await s.commit()
                await update.callback_query.answer("❌ پیداش نکردم", show_alert=True)
                return
            text = await _user_card_text(s, target)
            await s.commit()
        return await respond(update, text, kb.admin_user_kb(num))

    # ── شروع فلو پول/XP دادن به کاربر، مبلغ رو با پیام بعدی می‌پرسیم ──
    if kind in ("gtp", "gxp"):
        async with session_scope() as s:
            target = await users.get_by_tg(s, num)
            me, _ = await users.get_or_create(s, update.effective_user)
            if target is None:
                await s.commit()
                return await respond(update, "❌ طرف پیدا نشد", kb.admin_kb())
            users.set_pending(
                me, "admtp" if kind == "gtp" else "admxp", str(num),
                chat_id_of(update),
            )
            name = esc(users.display_name(target))
            await s.commit()
        # قالب یکدست با سایر سوال‌های عددی (مثل بانک)
        if kind == "gtp":
            qtext = (
                f"<b>💰 هدیه تی‌پوینت به {name}</b>\n\n"
                "چقد تی‌پوینت میخوای بهش بدی؟\n"
                "عددشو همینجا بنویس و بفرست، مثلا: 5000\n\n"
                "❌ اگر هم پشیمون شدی بنویس «لغو»"
            )
        else:
            qtext = (
                f"<b>✨ هدیه تجربه به {name}</b>\n\n"
                "چند تا تجربه میخوای بهش بدی؟\n"
                "عددشو همینجا بنویس و بفرست، مثلا: 500\n\n"
                "❌ اگر هم پشیمون شدی بنویس «لغو»"
            )
        return await respond(update, qtext)

    # ── دادن به خودت (پنل کلاسیک) ──
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)

        if kind == "cash":
            user.cash += num
            alert = f"💵 {money(num)} اضافه شد"
            notes = None
        elif kind == "xp":
            notes = users.add_xp(user, num)
            alert = f"✨ {fa_num(num)} XP اضافه شد"
        else:
            alert = "❌ چیزی نیست که"
            notes = None

        text = _panel_text(user)
        await s.commit()

    await respond(update, text, kb.admin_kb(), alert=alert)
    # تبریک لول‌آپ پیام جداشو داره، قاطی پنل نمیشه
    from handlers.common import announce_notes
    await announce_notes(update, notes)


# ───────── 📊 آمار ربات ─────────

# کلید متا برای آدرس آخرین پیام آمار، تا جاب ساعتی خودکار ادیتش کنه
STATS_MSG_META_KEY = "admin_stats_msg"


async def _remember_stats_msg(chat_id: int, message_id: int) -> None:
    """آدرس آخرین پیام آمار رو تو متا نگه می‌داره (کامیت همینجاست)"""
    async with session_scope() as s:
        await team_svc.meta_set(s, STATS_MSG_META_KEY, f"{chat_id}:{message_id}")
        await s.commit()


async def stats_autoedit_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    هر ۱ ساعت یه بار آخرین پیام آمار ادمین رو بی‌صدا ادیت می‌کنه
    سبکه، فقط یه خوندن متا + رندر + یه ادیت، اگه پیام پاک شده باشه بی‌صدا رد میشه
    """
    async with session_scope() as s:
        ref = await team_svc.meta_get(s, STATS_MSG_META_KEY)
        await s.commit()
    if not ref or ":" not in ref:
        return
    try:
        chat_id, message_id = (int(x) for x in ref.split(":", 1))
    except ValueError:
        return
    try:
        text = await _stats_text(context.bot)
        await context.bot.edit_message_text(
            text, chat_id=chat_id, message_id=message_id,
            parse_mode="HTML", reply_markup=kb.admin_stats_kb(),
        )
    except Exception:
        pass  # پیام پاک شده یا دسترسی نیس، دور بعد سر فرصت


async def _stats_text(bot=None) -> str:
    """آمار کلی ربات برای ادمین"""
    from datetime import timedelta

    from sqlalchemy import func, select

    from handlers.common import cmd_per_min, proc_avg_ms
    from models import ActionEvent, Dog, GroupActivity, Plot, Team, User
    from utils import now_utc

    async with session_scope() as s:
        hour_ago = now_utc() - timedelta(hours=1)
        day_ago = now_utc() - timedelta(hours=24)
        # آمار بازیکنان: فعال ۱ ساعته و ۲۴ ساعته و جدید + کل
        users_n = (await s.execute(select(func.count(User.id)))).scalar() or 0
        active_h = (await s.execute(
            select(func.count(User.id)).where(User.last_seen_at >= hour_ago)
        )).scalar() or 0
        active_d = (await s.execute(
            select(func.count(User.id)).where(User.last_seen_at >= day_ago)
        )).scalar() or 0
        new_d = (await s.execute(
            select(func.count(User.id)).where(User.created_at >= day_ago)
        )).scalar() or 0
        # راند ۱۹ (درخواست کارفرما): پلیرای جدید یک ساعت اخیر هم جدا
        new_h = (await s.execute(
            select(func.count(User.id)).where(User.created_at >= hour_ago)
        )).scalar() or 0
        groups_active_h = (await s.execute(
            select(func.count(GroupActivity.chat_id)).where(GroupActivity.last_active_at >= hour_ago)
        )).scalar() or 0
        groups_active_d = (await s.execute(
            select(func.count(GroupActivity.chat_id)).where(GroupActivity.last_active_at >= day_ago)
        )).scalar() or 0
        groups_n = (await s.execute(select(func.count(GroupActivity.chat_id)))).scalar() or 0
        # فعال‌ترین گروه‌های ساعت جاری ایران، با شمارنده دستورهای ساعتی که touch_group نگه می‌داره
        from utils import now_iran as _nir
        _ir = _nir()
        bucket = f"{_ir.date().isoformat()}-{_ir.hour:02d}"
        top_groups = list((await s.execute(
            select(GroupActivity).where(GroupActivity.hour_key == bucket)
            .order_by(GroupActivity.msgs_hour.desc()).limit(5)
        )).scalars())
        # تعداد پلیرای هر گروه (فعال ۲۴ ساعت اخیر اون گروه) برای جلوی اسم گروه‌های برتر
        from models import GroupPlayer
        gids = [g.chat_id for g in top_groups]
        players_in: dict[int, int] = {}
        if gids:
            pl_rows = (await s.execute(
                select(GroupPlayer.chat_id, func.count(GroupPlayer.user_tg))
                .where(GroupPlayer.chat_id.in_(gids), GroupPlayer.last_active_at >= hour_ago)
                .group_by(GroupPlayer.chat_id)
            )).all()
            players_in = {cid: int(n) for cid, n in pl_rows}

        cash_sum = (await s.execute(
            select(func.coalesce(func.sum(User.cash + User.bank_balance), 0))
        )).scalar() or 0
        bank_sum = (await s.execute(
            select(func.coalesce(func.sum(User.bank_balance), 0))
        )).scalar() or 0
        # فقط نقد دست بازیکن‌ها، برای بخش اقتصاد
        hands_sum = (await s.execute(
            select(func.coalesce(func.sum(User.cash), 0))
        )).scalar() or 0
        teams_n = (await s.execute(select(func.count(Team.id)))).scalar() or 0
        dogs_n = (await s.execute(select(func.count(Dog.id)))).scalar() or 0
        # فقط پلات‌هایی که واقعاً در حال رشدن (ready_at نگذشته)، فیلتر روی status ایندکس‌دار
        growing_n = (await s.execute(
            select(func.count(Plot.id)).where(
                Plot.status == "growing", Plot.ready_at > now_utc())
        )).scalar() or 0

        # ── فعالیت ۲۴ ساعت اخیر، COUNT گروه‌بندی‌شده روی ایندکس (action, at) ──
        ev_rows = (await s.execute(
            select(ActionEvent.action, func.count(ActionEvent.id))
            .where(ActionEvent.at >= day_ago)
            .group_by(ActionEvent.action)
        )).all()
        ev = {action: n for action, n in ev_rows}
        battle_n = int(ev.get("battle", 0))
        pv_n = int(ev.get("pvattack", 0))
        mine_n = int(ev.get("mine", 0))
        casino_n = int(ev.get("casino", 0))
        await s.commit()

    # ── فنی، پینگ API تلگرام با یه فراخوانی سبک (بدون bot، نامعلومه) ──
    ping_ms = None
    if bot is not None:
        try:
            t0 = time.monotonic()
            await bot.get_me()
            ping_ms = int((time.monotonic() - t0) * 1000)
        except Exception:
            ping_ms = None
    avg_proc_ms, proc_count = proc_avg_ms()

    # ── متن فنی: زمان پاسخ ربات = پینگ تلگرام + پردازش داخلی، چراغش از سر همین جمعه ──
    def _light(ms: float) -> str:
        if ms < config.PROC_LIGHT_GOOD_MS:
            return "🟢"
        if ms < config.PROC_LIGHT_WARN_MS:
            return "🟡"
        return "🔴"

    if ping_ms is not None and avg_proc_ms is not None:
        resp_ms = int(ping_ms + avg_proc_ms)
        resp_line = f"🚀 زمان پاسخ ربات: {fa_num(resp_ms)}ms {_light(resp_ms)}"
    else:
        resp_line = "🚀 زمان پاسخ ربات: ➖ نامعلوم"
    if ping_ms is None:
        ping_line = "📡 پینگ تلگرام: ➖ نامعلوم"
    else:
        ping_line = f"📡 پینگ تلگرام: {fa_num(ping_ms)}ms"
    if avg_proc_ms is None:
        proc_lines = ["⚙️ پردازش داخلی: هنوز نمونه‌ای نیس"]
    else:
        proc_lines = [
            f"⚙️ پردازش داخلی: {fa_num(avg_proc_ms)}ms",
            f"└ میانگین {fa_num(proc_count)} دستور اخیر",
        ]
    # نرخ دستورهای کاربرا رو پنجره اخیر (چت عادی تو گروه حساب نیس، فقط دستوره)
    rate_cmd, _cmd_n = cmd_per_min()
    if rate_cmd is None:
        cmd_line = "⌨️ میانگین دستور تو دقیقه: هنوز نمونه‌ای نیس"
    else:
        rate_txt = f"{rate_cmd:.1f}".rstrip("0").rstrip(".")
        cmd_line = f"⌨️ میانگین دستور تو دقیقه: {rate_txt}"

    # نرخ فعالیت: چند درصد بازیکن‌ها تو ۲۴ ساعت اخیر سر زدن
    rate = round(active_d * 100 / users_n) if users_n else 0
    attack_n = battle_n + pv_n
    actions_n = attack_n + mine_n + casino_n

    # قالب بخش‌بندی‌شده: عملکرد و بازیکنان بالا، اقتصاد و فعالیت وسط، گروه‌ها ته لیست
    lines = [
        "<b>📊 آمار زنده ربات</b>",
        "",
        "<b>⚡️ عملکرد</b>",
        resp_line,
        ping_line,
        *proc_lines,
        cmd_line,
        "",
        "<b>👥 بازیکنان</b>",
        f"⚡️ فعال ۱ ساعت اخیر: {fa_num(active_h)}",
        f"👤 فعال ۲۴ ساعت اخیر: {fa_num(active_d)}",
        f"🌱 جدید ۱ ساعت اخیر: {fa_num(new_h)}",
        f"🆕 جدید ۲۴ ساعت اخیر: {fa_num(new_d)}",
        f"🌍 کل بازیکنان: {fa_num(users_n)}",
        f"📈 نرخ فعالیت: %{fa_num(rate)}",
        "",
        "<b>🌍 وضعیت محله</b>",
        f"🏴 کارتل‌ها: {fa_num(teams_n)}",
        f"🐕 سگ‌ها: {fa_num(dogs_n)}",
        f"🌱 محصولات در حال رشد: {fa_num(growing_n)}",
        f"🚛 کاروان‌های فعال: {fa_num(len(world_svc.CARAVANS))}",
        "",
        "<b>💰 اقتصاد</b>",
        f"💵 تی‌پوینت کل: {fa_num(cash_sum)}",
        f"🏦 موجودی بانک: {fa_num(bank_sum)}",
        f"💸 دست بازیکنان: {fa_num(hands_sum)}",
        "",
        "<b>🔥 فعالیت ۲۴ ساعت اخیر</b>",
        f"⛏️ استخراج: {fa_num(mine_n)}",
        f"⚔️ حمله: {fa_num(attack_n)}",
        f"🎰 قمار: {fa_num(casino_n)}",
        f"📊 مجموع اکشن‌ها: {fa_num(actions_n)}",
        "",
        "<b>🏘 گروه‌ها</b>",
        f"🟢 فعال ۱ ساعت اخیر: {fa_num(groups_active_h)}",
        f"👥 فعال ۲۴ ساعت اخیر: {fa_num(groups_active_d)}",
        f"🌐 کل گروه‌ها: {fa_num(groups_n)}",
    ]
    if top_groups:
        # شمارنده ساعتی، «دستورهای» این ساعت گروهه نه همه پیام‌ها (فعالیت = دستور)
        # هر گروه دو خط: اسم | پلیرای فعال و تعداد دستورات ۱ ساعت اخیر (درخواست کارفرما)
        lines += ["", "<b>🏆 فعال‌ترین گروه‌های این ساعت</b>", ""]
        badges = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for i, g in enumerate(top_groups):
            gname = esc(g.title) if g.title else f"گروه {fa_num(g.chat_id)}"
            lines.append(f"{badges[i]} {gname}")
            lines.append(
                f"پلیرای فعال: {fa_num(players_in.get(g.chat_id, 0))}"
                f" | تعداد دستورات 1ساعت اخیر: {fa_num(g.msgs_hour or 0)}"
            )
    # 🖥 مصرف سرور (راند ۱۷، درخواست کارفرما) | روی غیرلینوکس سکشن اصلاً نمیاد
    from services import sysinfo as _sysinfo
    usage = _sysinfo.server_usage()
    if usage:
        lines += [
            "",
            "<b>🖥 سرور</b>",
            f"⚙️ CPU {fa_num(usage['cpu_pct'])}% | لود {usage['load1']:.2f} روی {fa_num(usage['cores'])} هسته",
            f"🧠 رم {usage['mem_used_gb']} از {usage['mem_total_gb']} گیگ ({fa_num(usage['mem_pct'])}%)",
            f"💽 دیسک {usage['disk_used_gb']} از {usage['disk_total_gb']} گیگ ({fa_num(usage['disk_pct'])}%)",
            f"⏱ آپتایم: {usage['uptime_fa']}",
        ]
    lines += [
        "",
        "⏱️ آمار زنده‌ست، با 🔃 به‌روزرسانی میشه",
    ]
    return "\n".join(lines)


# ───────── 📢 عضویت اجباری ─────────

async def _fj_text() -> str:
    async with session_scope() as s:
        st = await fj_svc.get_settings(s)
        await s.commit()
    st_link = st["link"] or ""
    if st["channel"]:
        state = "🟢 فعال" if st["on"] else "🔴 غیرفعال"
        return (
            "<b>📢 عضویت اجباری</b>\n\n"
            f"▫️ کانال: <code>{esc(st['channel'])}</code>\n"
            f"▫️ لینک: {esc(st_link)}\n"
            f"▫️ وضعیت: {state}\n\n"
            "هر دستوری که زده بشه اول عضویت کاربر چک میشه، "
            "عضو نباشه پیام گیت با دکمه عضویت و تایید می‌گیره\n\n"
            "⚠️ یادت نره ربات توی کانال ادمین باشه"
        )
    return (
        "<b>📢 عضویت اجباری</b>\n\n"
        "هنوز کانالی ست نشده\n\n"
        "با «🔗 ست کردن کانال» یوزرنیم یا لینک کانال رو بفرست، خاموش/روشنش هم می‌تونی کنی\n\n"
        "⚠️ ربات باید توی کانال ادمین باشه تا عضویت‌ها رو بتونه چک کنه"
    )


async def _fj_kb():
    async with session_scope() as s:
        st = await fj_svc.get_settings(s)
        await s.commit()
    return kb.admin_fj_kb(st)
