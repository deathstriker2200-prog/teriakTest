"""رتبه‌بندی بازیکن‌ها بر اساس مدال 🎖️، سه دکمه ثابت روزانه/هفتگی/کلی بالای دکمه منو، باز کردنش مستقیم روی کلی می‌افته"""

from telegram import Update
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import respond
from keyboards import keyboards as kb
from services import users
from utils import esc, fa_num

_MEDALS = ["🥇", "🥈", "🥉"]
# نشان رتبه: سه تای اول مدال، بعدیشون عدد کی‌کپ
_RANK_BADGES = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}


def _rank_badge(i: int) -> str:
    return _RANK_BADGES.get(i, f"▫️ {fa_num(i)}")


TAB_TITLES = {"day": "📅 روزانه", "week": "🗓 هفتگی", "all": "🌍 کلی"}
TAB_ORDER = ["day", "week", "all"]


async def rank_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, tab: str | None = None) -> None:
    if tab not in TAB_ORDER:
        tab = "all"  # پیش‌فرض لیدربرد کلی (راند ۱۰)، کاربر خودش با دکمه‌ها تب رو عوض می‌کنه

    async with session_scope() as s:
        from sqlalchemy import func as _func, select as _select
        from models import User as _User

        me, _ = await users.get_or_create(s, update.effective_user)
        top = await users.top_by_medals(s, tab, config.RANK_LIMIT)
        my_rank = await users.medal_rank(s, me, tab)
        my_medals = users.medal_value(me, tab)
        # نامرئی‌ها نه تو لیستن نه تو جمع کل
        total = (await s.execute(
            _select(_func.count(_User.id)).where(_User.lb_hidden == 0)
        )).scalar_one()

        lines: list[str] = []
        for i, u in enumerate(top, 1):
            badge = _rank_badge(i)
            name = esc(users.display_name(u))
            me_mark = " 👈 تو" if u.id == me.id else ""
            temoji, tname = users.title_of(u)
            lines.append(f"{badge} {temoji} [Lv.{u.level:02d}] │ {name}{me_mark}")
            lines.append(f"<b>「{tname}」</b> 🎖️ {fa_num(users.medal_value(u, tab))}")

        if not lines:
            lines.append("هنوز کسی مدالی نگرفته 🤷")

        if getattr(me, "lb_hidden", 0):
            footer = "👻 تو نامرئی هستی و تو لیدربرد دیده نمیشی"
        else:
            footer = f"رتبه‌ات: {fa_num(my_rank)} از {fa_num(total)} (🎖️ {fa_num(my_medals)})"

        text = (
            f"<b>🏆 لیدربرد بازیکنا</b>\n{TAB_TITLES[tab]}\n\n"
            + "\n".join(lines)
            + "\n\n━━━━━━━━━━━━━━━━\n"
            + footer + "\n"
            + "🎖️ مدال‌ها از تجربه‌ای که می‌گیری جمع میشن"
        )
        await s.commit()

    await respond(update, text, kb.rank_kb(tab))


async def rank_tab_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تعویض تب لیدربرد، زدن رو دکمه تب فعلی هیچ واکنشی نداره (فقط لودینگ قطع میشه)"""
    _p, _t, cur, tgt = update.callback_query.data.split(":")
    if cur == tgt:
        await update.callback_query.answer()
        return
    await rank_cb(update, context, tab=tgt)
