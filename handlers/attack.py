"""حمله پی‌وی کلاسیک ⚔️: دکمه 🎯 هدف شانسی → پیش‌نمایش قربانی → یا میزنیش یا هدف دیگه می‌گیری
هدف دیگه هزینه‌داره (با لول جست‌وجوگر از 25 تا 1000 تی‌پوینت) و هر حمله 1 دقیقه کولدان داره
قربانی سپر ۶ ساعته داشته باشه مهاجم انتخاب داره: با پول بشکنه یا بی‌خیال
بعد حمله، به قربانی تو پی‌وی خبر حمله می‌رسه که چقدر دزدیده شد و چه تجربه کمی گرفت
راند ۱۲ قدرت کل (حمله + دفاع) با بوست‌های نقش‌محور | راند ۱۳/۱۷: اختلاف تا ۵۰ شانسی با برتری قوی‌تر و هدف‌های دیده‌شده تا ۲۰ نشون بعدی تکرار نمیشن
نبرد HP فقط توی گروه‌ها با دستورهای جنگ انجام میشه، اینجا سیستم جداست"""

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import parts, respond
from keyboards import keyboards as kb
from models import User
from services import pvattack, users
from utils import esc, fa_dur, fa_num, money

# ───────── متن‌ها ─────────

PV_PANEL_TEXT = (
    "<b>⚔️ حمله پی‌وی</b>\n\n"
    "🎯 با شروع حمله، یک بازیکن نزدیک به سطح خودت به‌صورت شانسی پیدا میشه\n\n"
    "👀 قبل از حمله می‌تونی پیش‌نمایش حریف رو ببینی؛ اگر مناسب نبود، امکان تغییر هدف داری\n\n"
    "🕵️ با جاسوسی، اطلاعات بیشتری از حریف مثل مقدار پول و قدرت کلیش به دست میاری\n\n"
    "💪 نتیجه نبرد بر اساس قدرت کلی (قدرت حمله + قدرت دفاع) محاسبه میشه؛ بازیکنی که قدرت بیشتری داشته باشه، پیروز میشه\n\n"
    "🛡️ بعد از هر حمله، حریف برای مدتی وارد حالت محافظت میشه و امکان حمله دوباره بهش وجود نداره\n\n"
    "⚔️ توجه: نبردهای واقعی همراه با سیستم HP فقط داخل گروه‌ها فعال هستند"
)

NO_TARGET_TEXT = "😴 هدفی حوالی لولت پیدا نشد"

NO_OTHER_TARGET_ALERT = "فعلا هدفی جز این در حوالی لولت پیدا نمیشه"


async def pv_panel(update: Update, alert: str | None = None) -> None:
    """پنل حمله پی‌وی، فقط یه دکمه هدف شانسی داره"""
    await respond(update, PV_PANEL_TEXT, kb.pv_attack_kb(), alert=alert)


async def attack_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, alert: str | None = None) -> None:
    """دکمه ⚔️ حمله منو و دستور /attack | تو پی‌وی پنل باز میشه، تو گروه راهنمای نبرد گروهی"""
    chat = update.effective_chat
    if chat is not None and chat.type != ChatType.PRIVATE:
        from handlers.battle import ATTACK_GUIDE_TEXT
        return await respond(update, ATTACK_GUIDE_TEXT, kb.home_kb(), alert=alert)
    await pv_panel(update, alert=alert)


async def _target_view(s, user: User, victim: User) -> tuple[str, object]:
    """متن و کیبورد پیش‌نمایش هدف، قدرت کل طرف فقط با دکمه جاسوسی (هزینه‌دار) لو میره"""
    name = users.display_name(victim)
    text = (
        "<b>🎯 هدف پیدا شد</b>\n\n"
        f"👤 {esc(name)}\n"
        f"⭐ لول {fa_num(victim.level)}\n"
        f"⚡ هزینه حمله {fa_num(config.PV_ATTACK_ENERGY_COST)} انرژی\n\n"
        "🕵 با جاسوسی جیب و قدرت کل طرف لو میره\n"
        "می‌زنیش یا یه هدف دیگه می‌خوای؟"
    )
    spy_c = pvattack.spy_cost(user.level)
    return text, kb.pv_target_kb(victim.id, pvattack.reroll_cost(user.level), spy_c)


async def target_go_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🎯 هدف شانسی، یه قربانی پیدا می‌کنه و پیش‌نمایشش رو نشون میده"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.apply_energy_regen(user)

        cd = pvattack.cooldown_left(user)
        if cd:
            await s.commit()
            return await pv_panel(update, alert=f"⏳ {fa_num(cd)} ثانیه دیگه می‌تونی حمله کنی")

        victim = await pvattack.pick_random_target(s, user)
        if victim is None:
            await s.commit()
            return await respond(update, NO_TARGET_TEXT, kb.pv_attack_kb())

        pvattack.note_target_shown(user.telegram_id, victim.id)  # تا ۲۰ نشون بعدی تکرار نمیشه (راند ۱۳)
        text, markup = await _target_view(s, user, victim)
        await s.commit()
    await respond(update, text, markup)


async def target_next_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🎯 هدف دیگه، هزینه‌دار با لول | هدف فعلی رو کنار می‌ذاره و یه قربانی تازه میاره"""
    target_id = int(parts(update)[2])
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.apply_energy_regen(user)

        cur = await s.get(User, target_id)
        if cur is None:
            await s.commit()
            return await respond(update, NO_TARGET_TEXT, kb.pv_attack_kb())

        cost = pvattack.reroll_cost(user.level)
        if user.cash < cost:
            text, markup = await _target_view(s, user, cur)
            await s.commit()
            return await respond(update, text, markup, alert="💸 پولت برای هدف دیگه کمه")

        victim = await pvattack.pick_random_target(s, user, exclude_id=target_id)
        if victim is None:
            # هدف دیگه‌ای نیس، پولی هم کم نمیشه، همون پیش‌نمایش میمونه با یه الرت
            text, markup = await _target_view(s, user, cur)
            await s.commit()
            return await respond(update, text, markup, alert=NO_OTHER_TARGET_ALERT)

        user.cash -= cost
        pvattack.note_target_shown(user.telegram_id, victim.id)  # تا ۲۰ نشون بعدی تکرار نمیشه (راند ۱۳)
        text, markup = await _target_view(s, user, victim)
        await s.commit()
    await respond(update, text, markup)


async def target_spy_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🕵 جاسوسی، فقط پول و قدرت کل طرف لو میره (راند ۱۵: همیشه پولیه، حکم مقایسه هم حذف شد)"""
    target_id = int(parts(update)[2])
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        cur = await s.get(User, target_id)
        if cur is None:
            await s.commit()
            return await respond(update, NO_TARGET_TEXT, kb.pv_attack_kb())
        cost = pvattack.spy_cost(user.level)
        if user.cash < cost:
            text, markup = await _target_view(s, user, cur)
            await s.commit()
            return await respond(update, text, markup, alert="💸 پولت برای جاسوسی کمه")
        user.cash -= cost
        _a, _t, _info30 = await pvattack.total_powers(s, user, cur)
        cash = cur.cash
        name = users.display_name(cur)
        text, markup = await _target_view(s, user, cur)
        await s.commit()
    # قالب گزارش درخواست کارفرما (راند ۱۵): فقط دو خط دیتا، هیچ خط دیگه‌ای نمیاد
    alert = (
        f"🕵 گزارش جاسوسی از «{esc(name)}» به شرح زیر است\n\n"
        f"💰 پول: {money(cash)}\n"
        f"💪 قدرت کلی: {fa_num(_info30['t_display'])}"
    )
    await respond(update, text, markup, alert=alert)


async def target_back_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🔙 بازگشت به پنل حمله پی‌وی، سرچ تمومه و لیست دیده‌شده‌ها پاک میشه"""
    pvattack.clear_seen_targets(update.effective_user.id)
    await pv_panel(update)


def _victim_text(attacker_name: str, result: dict) -> str:
    """دی‌ام پی‌وی به قربانی: کی حمله کرد، چقدر دزدید/جریمه رفت، تجربه ناچیز"""
    name = esc(attacker_name)
    if result["won"]:
        head = f"⚔️ حریف «{name}» بهت حمله کرد و برد"
        money_line = (f"💰 {money(result['steal'])} ازت دزدید" if result["steal"]
                      else "💰 جیبت خالی بود، چیزی نتونست بدزده")
    else:
        head = f"🛡 حریف «{name}» بهت حمله کرد ولی دفاع کردی"
        money_line = (f"💵 {money(result['penalty'])} جریمه‌ش رسید دستت" if result["penalty"]
                      else "💸 جیبش خالی بود، جریمه‌ای گیرت نیومد")
    return (
        "<b>🚨 بهت حمله شد</b>\n\n"
        f"{head}\n"
        f"{money_line}\n"
        f"💪 قدرت کل تو {fa_num(result['d_pow_disp'])} ✕ طرف {fa_num(result['a_pow_disp'])}\n"
        f"✨ {fa_num(result['victim_xp'])} تجربه گرفتی\n\n"
        f"🛡 تا {fa_num(config.PV_ATTACK_SHIELD_SECONDS // 3600)} ساعت از حملات در امانی"
    )


async def _own_shield_view(update: Update, target_id: int, own_left: float, break_victim: bool) -> None:
    """تاییدیه شکستن سپر محافظتی خودی قبل از حمله، تا وقتی داری از حمله‌ها در امانی"""
    text = (
        "<b>🛡 سپر محافظتی داری</b>\n\n"
        f"تا {fa_dur(own_left)} دیگه از حمله‌ها در امانی\n"
        "اگه حمله کنی این سپر میشکنه و هرکسی می‌تونه بهت حمله کنه\n\n"
        "انجامش بدیم؟"
    )
    await respond(update, text, kb.pv_ownshield_kb(target_id, break_victim))


async def _run_attack(update: Update, context, target_id: int, break_shield: bool = False, own_shield_ok: bool = False) -> None:
    """حمله روی هدف پیش‌نمایش‌شده، با کولدان و تاییدیه شکستن سپر خودی/قربانی و دی‌ام قربانی"""
    dq_done, dq_left, uname = [], 0, ""
    congrats = None

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.apply_energy_regen(user)

        cd = pvattack.cooldown_left(user)
        if cd:
            await s.commit()
            return await pv_panel(update, alert=f"⏳ {fa_num(cd)} ثانیه دیگه می‌تونی حمله کنی")

        victim = await s.get(User, target_id)
        if victim is None or victim.lb_hidden:  # نامرئی‌های /hideboard هدف حمله نمیشن
            await s.commit()
            return await pv_panel(update, alert="🤷 هدف گم شد، یه هدف دیگه بگیر")

        # سپر محافظتی خود مهاجم، حمله یعنی شکستنش و اول باید تاییدش کنه
        own_sl = pvattack.shield_left(user)
        if own_sl and not own_shield_ok:
            await s.commit()
            return await _own_shield_view(update, target_id, own_sl, break_shield)
        if own_sl:
            user.shield_until = None

        name = users.display_name(victim)
        sl = pvattack.shield_left(victim)
        if sl and not break_shield:
            await s.commit()
            return await _shield_view_for(update, target_id, name)
        if sl:
            if user.cash < config.PV_ATTACK_SHIELD_BREAK_COST:
                await s.commit()
                return await _shield_view_for(update, target_id, name, alert="💸 پولت برای شکستن سپر کمه")
            user.cash -= config.PV_ATTACK_SHIELD_BREAK_COST
            victim.shield_until = None

        result = await pvattack.execute(s, user, victim)
        if result["ok"]:
            pvattack.clear_seen_targets(user.telegram_id)  # سرچ با حمله تموم شد، دور بعدی تازه (راند ۱۳)
        if not result["ok"]:
            await s.commit()
            reason = result["reason"]
            if reason == "no_ammo":
                return await pv_panel(update, alert="تیر نداری")  # راند ۳۷: پاپ‌آپ قطعی خشاب خالی
            if reason == "cooldown":
                return await pv_panel(update, alert=f"⏳ {fa_num(result['left'])} ثانیه دیگه می‌تونی حمله کنی")
            if reason == "energy":
                return await pv_panel(update, alert="⚡ انرژیت برای حمله کمه")
            return await pv_panel(update, alert="🤷 یه مشکلی پیش اومد، دوباره بزن")

        from services import quests as dq_svc
        dq_done, dq_left = await dq_svc.track(s, user, "attack")
        uname = users.display_name(user)
        from services import onboarding as onb
        congrats = await onb.maybe_congrats(s, user)  # تبریک پایان مأموریت، فقط یه بار
        victim_tg = victim.telegram_id
        victim_dm = _victim_text(uname, result)
        await s.commit()

    if result["won"]:
        if result["steal"]:
            loot_line = f"💰 {money(result['steal'])} از جیب «{esc(name)}» غارت کردی"
        else:
            loot_line = f"💰 جیب «{esc(name)}» خالی بود"
        text = (
            f"<b>⚔️ بردی!</b>\n\n"
            f"{loot_line}\n"
            f"💪 قدرت کل تو {fa_num(result['a_pow_disp'])} ✕ طرف {fa_num(result['d_pow_disp'])}\n"
            f"✨ {fa_num(result['xp'])} تجربه گرفتی"
        )
    else:
        if result["penalty"]:
            lose_line = f"💸 {money(result['penalty'])} ازت کم شد"
        else:
            lose_line = "💸 جیبت خالی بود، چیزی باخت ندادی"
        text = (
            f"<b>🛡 حریف «{esc(name)}» تونست دفاع کنه، باختی</b>\n\n"
            f"{lose_line}\n"
            f"💪 قدرت کل طرف {fa_num(result['d_pow_disp'])} ✕ تو {fa_num(result['a_pow_disp'])}\n"
            f"✨ {fa_num(result['xp'])} تجربه گرفتی"
        )

    # راند ۳۰ (درخواست کارفرما): غارت چوب و آهن از انبار طرف
    _wl, _il = result.get("wood_loot") or 0, result.get("iron_loot") or 0
    if result["won"] and (_wl or _il):
        _parts = []
        if _wl:
            _parts.append(f"🪵 {fa_num(_wl)} چوب")
        if _il:
            _parts.append(f"⛏️ {fa_num(_il)} آهن")
        text += "\n🏴‍☠️ از انبارش هم قاپیدی: " + " و ".join(_parts)

    # راند ۲۹: مهمات مونده تفنگ مهاجم آخر کارت نتیجه
    wkey = result.get("weapon")
    _al = result.get("ammo_left", -1)
    if wkey and _al is not None and _al >= 0:
        from services import combat
        wname = (config.WEAPONS.get(wkey) or {}).get("name", wkey)
        text += f"\n🔫 {esc(wname)}: {fa_num(_al)} تیر مونده"

    await respond(update, text, kb.pv_result_kb())
    from handlers.common import announce_notes
    notes_out = (result.get("notes") or []) + ([congrats] if congrats else [])
    await announce_notes(update, notes_out)
    from handlers import dquests
    await dquests.announce_completed(update, uname, dq_done, dq_left)

    # خبر حمله تو پی‌وی قربانی، ربات رو استارت نکرده یا بلاک کرده باشه بی‌خیال
    bot = getattr(context, "bot", None)
    if bot is not None:
        try:
            await bot.send_message(victim_tg, victim_dm, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def _shield_view_for(update: Update, target_id: int, victim_name: str, alert: str | None = None) -> None:
    """صفحه انتخاب شکستن سپر ۶ ساعته قربانی"""
    text = (
        f"<b>🛡 «{esc(victim_name)}» الان سپر داره</b>\n\n"
        f"بعد حمله قبلی {fa_num(config.PV_ATTACK_SHIELD_SECONDS // 3600)} ساعت مصونیت گرفته\n"
        f"💰 شکستنش {money(config.PV_ATTACK_SHIELD_BREAK_COST)} آب می‌خوره\n\n"
        "می‌زنی و می‌شکنیش یا بی‌خیال؟"
    )
    await respond(update, text, kb.pv_break_kb(target_id), alert=alert)


async def target_hit_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """⚔️ حمله روی هدف پیش‌نمایش‌شده"""
    await _run_attack(update, context, int(parts(update)[2]), break_shield=False)


async def target_break_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """💥 شکستن سپر قربانی با پول و اجرای حمله"""
    await _run_attack(update, context, int(parts(update)[2]), break_shield=True)


async def ownshield_hit_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """✅ تایید شکستن سپر خودی و اجرای حمله"""
    await _run_attack(update, context, int(parts(update)[2]), break_shield=False, own_shield_ok=True)


async def ownshield_break_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """✅ تایید شکستن سپر خودی + سپر قربانی و اجرای حمله"""
    await _run_attack(update, context, int(parts(update)[2]), break_shield=True, own_shield_ok=True)
