"""بخش ⭐️ مهارت: هر لول‌آپ یه امتیاز مهارت، ۵ قابلیت تا لول ۸، ریست با پول

قدرت (حمله بیشتر) | سرعت (کولدان حمله کمتر) | دفاع (دفاع بیشتر) | غارت (غارت بیشتر) | استقامت (سقف انرژی بیشتر، راند ۱۵)
ریست مهارت‌ها همه امتیازهای خرج‌شده رو برمی‌گردونه که دوباره انتخاب کنی
"""

from telegram import Update
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import parts, respond
from keyboards import keyboards as kb
from services import users
from utils import fa_num, money


def skills_text(user) -> str:
    """متن صفحه مهارت‌ها: امتیاز فعلی بالا، هر قابلیت یه بلاک با لول و درصد الان/بعدی"""
    users.ensure_skills(user)
    lines = [
        "<b>⭐️ مهارت‌ها</b>",
        "",
        f"🎖 امتیاز مهارت: {fa_num(user.skill_points or 0)}",
        "",
        "هر لول‌آپ یه امتیاز مهارت(جز لول 10 و 20) می‌گیری و هرکدوم از قابلیت‌ها رو تا لول 8 می‌تونی ببری بالا",
        "",
    ]
    for key, sk in config.SKILLS.items():
        lv = users.skill_level(user, key)
        is_energy = sk.get("kind") == "energy"  # استقامت درصدی نیس، عددیه (راند ۱۵)
        now_v = int(round(sk["per"] * lv * (1 if is_energy else 100)))
        lines.append(f"{sk['name']} | لول {fa_num(lv)} از {fa_num(config.SKILL_MAX_LEVEL)}")
        lines.append(f"▫️ {sk['desc']}")
        if lv >= config.SKILL_MAX_LEVEL:
            cur = f"+{fa_num(now_v)} انرژی" if is_energy else f"{fa_num(now_v)}%"
            lines.append(f"الان {cur} ، 👑 مکس")
        else:
            nxt_v = int(round(sk["per"] * (lv + 1) * (1 if is_energy else 100)))
            if is_energy:
                lines.append(f"الان +{fa_num(now_v)} انرژی ، بعدی +{fa_num(nxt_v)} انرژی")
            else:
                lines.append(f"الان {fa_num(now_v)}% ، بعدی {fa_num(nxt_v)}%")
        lines.append("")
    lines.append(f"♻️ ریست همه امتیازاتو برمی‌گردونه و مهارت‌ها صفر میشن ({money(config.SKILL_RESET_COST)})")
    return "\n".join(lines)


async def render_skills(update: Update, alert: str | None = None) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        text = skills_text(user)
        await s.commit()
    await respond(update, text, kb.skills_kb(user), alert=alert)
    # توجه: user بعد از کامیت expire نمیشه (expire_on_commit=False)، kb فقط تو حافظه‌ست


async def skills_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_skills(update)


async def skill_up_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """بالا بردن یه قابلیت با یه امتیاز مهارت"""
    key = parts(update)[2]
    if key not in config.SKILLS:
        return await render_skills(update, alert="🤷 همچین قابلیتی نیس")
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, why = users.spend_skill_point(user, key)
        text = skills_text(user)
        lv = users.skill_level(user, key)
        markup = kb.skills_kb(user)
        await s.commit()
    if not ok:
        return await respond(update, text, markup, alert=why)
    sk = config.SKILLS[key]
    await respond(update, text, markup, alert=f"✅ {sk['name']} رفت رو لول {fa_num(lv)}")


async def skill_reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تأییدیه ریست مهارت‌ها با هزینه"""
    back = 0
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.ensure_skills(user)
        back = sum(users.skill_level(user, k) for k in config.SKILLS)
        await s.commit()
    if back <= 0:
        return await render_skills(update, alert="🤷 هنوز امتیازی خرج نکردی که برگرده")
    text = (
        "<b>♻️ ریست مهارت‌ها</b>\n\n"
        f"🎖 {fa_num(back)} امتیاز برمی‌گرده و همه قابلیت‌ها صفر میشن\n"
        f"💸 هزینه‌ش {money(config.SKILL_RESET_COST)}\n\n"
        "مطمئنی؟"
    )
    await respond(update, text, kb.confirm_kb("cf:sk:reset"))


async def skill_reset_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """اجرای ریست، امتیازها برمی‌گردن به کیف کاربر"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, res = users.reset_skills(user)
        text = skills_text(user)
        markup = kb.skills_kb(user)
        await s.commit()
    if not ok:
        return await respond(update, text, markup, alert=str(res))
    await respond(update, text, markup, alert=f"♻️ مهارت‌ها ریست شدن و {fa_num(res)} امتیاز برگشت")
