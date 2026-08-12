"""بخش انرژی‌زا ⚡ (راند ۱۳، درخواست کارفرما): «تی انرژی» و /Energy

مثل بخش درمان: هر آیتم با یه کلیک خریده و همون لحظه خورده میشه، انبار نداره
صفحه‌ش شارژ فعلی انرژی و تایمر بوست فعال رو نشون میده (تایم بخشش مثل درمان)
بمب انرژی علاوه بر فول کردن، ۱۰ دقیقه قدرت حمله رو زیاد می‌کنه و آخرش پیام پایان اثر میره
"""

from telegram import Update
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import respond
from keyboards import keyboards as kb
from services import energy as energy_svc, users
from utils import fa_dur, fa_num


def _bomb_pct() -> int:
    """درصد بوست بمب انرژی به عدد صحیح، برای نمایش"""
    return int(round((config.ENERGY_DRINKS["bomb"]["boost"] or 0) * 100))


def energy_home_text(energy_now: int, boost_left_s: int, energy_cap: int) -> str:
    """صفحه انرژی‌زا: شارژ فعلی + تایمر بوست فعال، آیتم‌ها با قیمت و مقدار فقط روی دکمه‌ها میان"""
    lines = [
        "<b>⚡ تی انرژی</b>",
        "",
        "⚡ انرژی تو",
        f"{fa_num(energy_now)} از {fa_num(energy_cap)}",
    ]
    if boost_left_s:
        lines += [
            "",
            f"🔥 بوست انرژی‌زا فعاله: قدرت حمله +{fa_num(_bomb_pct())}%",
            f"⏱ {fa_dur(boost_left_s)} دیگه اثرش تموم میشه",
        ]
    lines += [
        "",
        "🥤 هر انرژی‌زا همون لحظه خریده و خورده میشه و تو انبار ذخیره نمیشه",
    ]
    return "\n".join(lines)


ENERGY_FULL_TEXT = (
    "⚡ انرژیت فوله\n"
    "فعلاً نیازی به انرژی‌زا نداری"
)


async def render_energy(update: Update, alert: str | None = None) -> None:
    """صفحه انرژی‌زا با وضعیت فعلی کاربر، هم پی‌وی هم گروه"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.apply_energy_regen(user)  # سقف انرژی حفظ بشه
        e_now = user.energy
        e_cap = energy_svc.max_energy(user)
        b_left = energy_svc.boost_left(user)
        await s.commit()
    if e_now >= e_cap and not b_left:
        return await respond(update, ENERGY_FULL_TEXT, kb.energy_kb(), alert=alert)
    await respond(update, energy_home_text(e_now, b_left, e_cap), kb.energy_kb(), alert=alert)


async def energy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«تی انرژی» و /Energy، صفحه انرژی‌زا رو باز می‌کنه"""
    await render_energy(update)


async def energy_buy_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """خرید و خوردن همون لحظه انرژی‌زا (en:buy:<key>)"""
    key = update.callback_query.data.split(":")[-1]
    dq_done, dq_left, uname, tq = [], 0, "", None
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        users.apply_energy_regen(user)
        ok, why, info = energy_svc.apply_drink(user, key)
        if ok:
            from services import quests as dq_svc
            dq_done, dq_left = await dq_svc.track(s, user, "drink")  # کوئست روزانه انرژی‌زا
            uname = users.display_name(user)
            from services import teams as team_svc
            tq = await team_svc.record_drink(s, user)  # کوئست کارتلی انرژی‌زا
        await s.commit()

    if not ok:
        if why == "full":
            return await render_energy(update, alert=ENERGY_FULL_TEXT.replace("\n", "، "))
        if why == "poor":
            return await render_energy(update, alert="💸 پولت برای این انرژی‌زا کمه")
        return await render_energy(update, alert="🤷 همچین انرژی‌زایی نداریم")

    if info["boosted"]:
        mins = config.ENERGY_BOOST_SECONDS // 60
        alert = (
            f"💣 بمب انرژی خوردی! انرژیت فول شد و "
            f"تا {fa_num(mins)} دقیقه قدرت حملت +{fa_num(_bomb_pct())}%"
        )
    else:
        alert = f"⚡ نوش جون، {fa_num(info['gain'])} انرژی شارژ شد"
    await render_energy(update, alert=alert)
    from handlers.common import announce_notes
    await announce_notes(update, [tq] if tq else [])
    from handlers import dquests
    await dquests.announce_completed(update, uname, dq_done, dq_left)
