"""
کوئست‌های روزانه 📅، صفحه منوی اصلی + اعلان جایزه همونجایی که کاربر فعاله
متن تکمیل کوئست به‌محض انجام به همون چت میره، چه پیوی چه گروه
"""

from telegram import Update
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import respond
from keyboards import keyboards as kb
from services import quests as dq_svc
from services import users
from utils import bar, esc, fa_num


def quest_line(q: dict) -> str:
    """یه خط کوئست توی صفحه کوئست‌های روزانه، با پیشرفت و جایزه"""
    cfg = config.DAILY_QUESTS[q["kind"]]
    title = esc(dq_svc.quest_title(q))
    if q["done"]:
        return f"{cfg['emoji']} <s>{title}</s>\n✅ انجام شد، 🎁 {dq_svc.reward_text(q)} گرفتی"
    return (
        f"{cfg['emoji']} {title}\n"
        f"{bar(q['progress'], q['target'])} {fa_num(q['progress'])} از {fa_num(q['target'])}"
        f" | 🎁 جایزه: {dq_svc.reward_text(q)}"
    )


async def render_dquests(update: Update, alert: str | None = None) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        quests = await dq_svc.ensure_quests(s, user)
        left = dq_svc.remaining(quests)

        lines = ["<b>🎯 مأموریت‌های روزانه</b>", ""]
        for q in quests:
            lines.append(quest_line(q))
            lines.append("")
        if left:
            lines.append(f"💪 {fa_num(left)} کوئست مونده، جایزه‌شون همونجایی که داری بازی می‌کنی اعلام میشه")
        else:
            lines.append("🏆 همه کوئست‌های امروز رو درو کردی، دستت درد نکنه")
        lines.append("🕛 هر شب ساعت 12 ریست میشن و کوئستای جدید میان")
        text = "\n".join(lines)
        await s.commit()

    await respond(update, text, kb.dquests_kb(), alert=alert)


async def daily_quests_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_dquests(update)


# ───────── اعلان تکمیل کوئست، همونجایی که کاربر فعاله ─────────

async def announce_completed(update: Update, user_name: str, completed: list[dict], left: int) -> None:
    """
    متن جایزه کوئست تکمیل‌شده به همون چت میره
    آخریش تبریک ویژه داره چون دیگه کوئستی برای امروز نمونده
    """
    if not completed:
        return
    notes_all: list[str] = []
    for q in completed:
        title = esc(dq_svc.quest_title(q))
        reward = dq_svc.reward_text(q)
        if left <= 0:
            text = (
                "<b>📅 کوئست روزانه</b>\n\n"
                f"ایوللل {esc(user_name)} بهت تبریک میگم، امروز خیلی فعال بودی و همه کوئست‌ها رو درو کردی 🏆\n"
                f"🎁 جایزه: {reward}\n"
                "دیگه کوئستی برای امروز نمونده، فردا 12 شب کوئستای جدید میان"
            )
        else:
            text = (
                "<b>📅 کوئست روزانه</b>\n\n"
                f"آفرین {esc(user_name)} کوئست «{title}» رو تکمیل کردی\n"
                f"🎁 جایزه: {reward}\n"
                f"هنوز {fa_num(left)} کوئست دیگه مونده، به تلاشت ادامه بده 💪"
            )
        notes_all += q.get("notes") or []

    msg = update.effective_message
    if msg is not None:
        await msg.reply_html(text)
    # تبریک لول‌آپ جایزه تجربه، پیام جدا تو همون چت
    from handlers.common import announce_notes
    await announce_notes(update, notes_all)
