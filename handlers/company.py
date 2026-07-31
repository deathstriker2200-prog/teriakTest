"""🏭 شرکت: صفحه‌ی ساخت و ارتقای چوب‌بری و کارخانه آهن + تسویه تولید انباشته"""

from telegram import Update
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers.common import parts, respond
from keyboards import keyboards as kb
from services import company as company_svc
from services import users
from utils import esc, fa_num, money


async def render_company(update: Update, alert: str | None = None) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        got = await company_svc.settle(s, user)
        text = company_svc.company_text(user, got)
        markup = kb.company_kb(user)
        await s.commit()
    await respond(update, text, markup, alert=alert)


async def company_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_company(update)


async def company_action_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, action, key = parts(update)
    cfg = config.FACTORIES.get(key)
    if not cfg:
        return await render_company(update)

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        lv = company_svc.factory_level(user, key)
        if action == "build":
            tp, wood = company_svc.build_cost(key)
            title = f"🔨 ساخت {cfg['emoji']} {esc(cfg['name'])}"
            gain = "تولید تو انبار خودش جمع میشه و 12 ساعته پر میشه، با دکمه 📥 برداشت ببرش تو انبارت"
        else:
            tp, wood = company_svc.upgrade_cost(key, lv + 1)
            title = f"⬆️ ارتقای {cfg['emoji']} {esc(cfg['name'])}"
            gain = f"از لول {fa_num(lv)} به لول {fa_num(lv + 1)}"
        await s.commit()

    text = (
        f"<b>{title}</b>\n\n"
        f"{gain}\n"
        f"💸 تی‌پوینت {money(tp)}\n"
        f"🪵 چوب {fa_num(wood)}\n\n"
        "انجامش بدیم؟"
    )
    await respond(update, text, kb.company_confirm_kb(action, key))


async def company_action_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, action, key = parts(update)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        await company_svc.settle(s, user)
        if action == "build":
            _, alert = await company_svc.build(s, user, key)
        else:
            _, alert = await company_svc.upgrade(s, user, key)
        got = await company_svc.settle(s, user)
        text = company_svc.company_text(user, got)
        markup = kb.company_kb(user)
        await s.commit()
    await respond(update, text, markup, alert=alert)


async def company_collect_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """📥 برداشت تولید انبار کارخونه به انبار خود بازیکن"""
    _, _, key = parts(update)  # comp:col:<key>
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        await company_svc.settle(s, user)
        ok, alert = await company_svc.collect(s, user, key)
        got = await company_svc.settle(s, user)
        text = company_svc.company_text(user, got if (got["wood"] or got["iron"]) else None)
        markup = kb.company_kb(user)
        await s.commit()
    await respond(update, text, markup, alert=alert)


async def company_action_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await render_company(update)
