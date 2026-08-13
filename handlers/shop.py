"""فروشگاه: سلاح | زره | ارتقای سلاح/زره | آرتیفکت | منابع | بذر | سگ | غذا
ظاهر همه بخش‌ها باکسی و تمیزه، سبز یعنی قابل خرید و قرمز یعنی قفل"""

from telegram import Update
from telegram.ext import ContextTypes

import config
from database import session_scope
from handlers import dogs as dogs_h
from handlers.common import chat_id_of, parts, respond
from keyboards import keyboards as kb
from services import combat, dogs as dog_svc, economy, farming, resources as res_svc, shop_svc, users
from utils import esc, fa_num, money, money_tp

SEP = "━━━━━━━━━━━━━━"


def _has_emoji(text: str) -> bool:
    """اسم آیتم خودش ایموجی داره؟ (مثل «کلت کمری 🔫») که دوباره پیشوندی نزنیم و جفت جفت نشه"""
    return any(ord(ch) >= 0x2500 for ch in text)


def _item_head(prefix: str, name: str) -> str:
    """سر خط آیتم: اگه اسمش خودش ایموجی داره همونو بذار، وگرنه ایموجی بخش رو پیشوند کن"""
    return name if _has_emoji(name) else f"{prefix} {name}"


def _status_line(user) -> str:
    """خط سطح و موجودی زیر سر تیتر همه بخش‌های فروشگاه"""
    return f"🌟 سطح: {fa_num(user.level)} | 💵 موجودی: {money_tp(user.cash)}"


# ───────── متن‌ها ─────────

def _sections_text(cash: int, level: int) -> str:
    """صفحه اولیه فروشگاه، خط سطح و موجودی زیر تیتر مثل بقیه بخش‌ها"""
    return (
        "<b>🛒 فروشگاه</b>\n"
        f"🌟 سطح: {fa_num(level)} | 💵 موجودی: {money_tp(cash)}\n\n"
        "🔫 سلاح‌ها، زره‌ها و ⬆️ ارتقاشون\n"
        "🎒 چوب و آهن\n"
        "🌱 بذر برای کشت توی زمینتون\n"
        "🐕 سگ‌ها و 🍖 غذاشون\n"
        "🧿 آرتیفکت‌های آخر بازی که بعد از لول 10 باز میشن"
    )


def _weap_home_text(user) -> str:
    """صفحه انتخاب دسته سلاح، هر دسته قفلش جداست"""
    lines = ["<b>🛒 فروشگاه</b>", _status_line(user), "", "🔫 سلاح‌ها", "", "روی بخش مورد نظر بزن", ""]
    for sec, sc in config.WEAPON_SECTIONS.items():
        keys = [k for k, w in config.WEAPONS.items() if w.get("sec", "cold") == sec]
        if not keys:
            continue
        minlvl = min(config.WEAPONS[k]["min_level"] for k in keys)
        first, last = config.WEAPONS[keys[0]]["name"], config.WEAPONS[keys[-1]]["name"]
        locked = user.level < minlvl
        head = f"🔒 {sc['emoji']} {sc['name']} (قفل)" if locked else f"{sc['emoji']} {sc['name']}"
        lines += [SEP, ""]
        lines.append(head)
        lines.append(f"▫️ از {first} تا {last}")
        if locked:
            lines.append(f"⭕️ بازگشایی در سطح {fa_num(minlvl)}")
        lines.append("")
    lines.append(SEP)
    return "\n".join(lines)


def _wsec_text(user, sec: str) -> str:
    """باکس هر سلاح یه دسته: نام | دمیج | آهن | قیمت | وضعیت (راند ۴۱: قالب زره ویژه هم همینه)"""
    sc = config.WEAPON_SECTIONS.get(sec) or config.WEAPON_SECTIONS["cold"]
    lines = [f"<b>{sc['emoji']} {sc['name']}</b>", _status_line(user), "", "برای خرید روی آیتم موردنظر بزن", ""]
    for key, w in config.WEAPONS.items():
        if w.get("sec", "cold") != sec:
            continue
        locked = user.level < w["min_level"]
        lines += [SEP, ""]
        lines.append(f"🔒 {w['name']} (قفل)" if locked else _item_head(sc["emoji"], w["name"]))
        lines.append("")
        lines.append(f"💥 دمیج: {fa_num(w['attack'])}")
        if w.get("ability"):
            lines.append(f"🎯 قابلیت: {config.WEAPON_ABILITY_TEXT.get(w['ability']['kind'], '')}")
            flavor = config.WEAPON_FLAVOR_TEXT.get(w["ability"]["kind"])
            if flavor:
                lines.append(f"▫️ {flavor}")
        lines.append("")
        cost23 = f"🪙 هزینه: ⛏️ {fa_num(w['iron'])} آهن + 💰 {money(w['price'])}"
        parts23 = config.SPECIAL_WEAPON_PARTS.get(key, 0)
        if parts23:
            have23 = int(getattr(user, "legendary_parts", 0) or 0)
            mark23 = "✅" if have23 >= parts23 else "❌"
            cost23 += f" + 🧩 {fa_num(parts23)} قطعه افسانه‌ای ({mark23} تو {fa_num(have23)} تا داری)"
        lines.append(cost23)
        if locked:
            lines.append(f"⭕️ بازگشایی در سطح {fa_num(w['min_level'])}")
        lines.append("")
    lines.append(SEP)
    return "\n".join(lines)


def _arm_home_text(user) -> str:
    """خانه بخش زره: دو دسته معمولی و ویژه (راند ۱۹ درخواست کارفرما)"""
    lines = ["<b>🛒 فروشگاه</b>", _status_line(user), "", "🛡 زره‌ها تو دو دسته‌ان", ""]
    for sec, sc in config.ARMOR_SECTIONS.items():
        keys = [k for k, a in config.ARMORS.items() if a.get("sec", "normal") == sec]
        if not keys:
            continue
        locked = all(user.level < config.ARMORS[k]["min_level"] for k in keys)
        first, last = config.ARMORS[keys[0]]["name"], config.ARMORS[keys[-1]]["name"]
        head = f"🔒 {sc['emoji']} {sc['name']} (قفل)" if locked else f"{sc['emoji']} {sc['name']}"
        lines.append(head)
        lines.append(f"▫️ از {first} تا {last}")
        if sc.get("desc"):
            lines.append(f"▫️ {sc['desc']}")
        lines.append("")
    lines.append(SEP)
    return "\n".join(lines)


def _arm_text(user, sec: str) -> str:
    """صفحه یه دسته زره: نام | دفاع | قابلیت ویژه | قیمت | وضعیت (راند ۱۹، قالب راند ۴۱)"""
    sc = config.ARMOR_SECTIONS.get(sec) or config.ARMOR_SECTIONS["normal"]
    lines = [f"<b>{sc['emoji']} {sc['name']}</b>", _status_line(user), "", "برای خرید روی آیتم موردنظر بزن", ""]
    for key, a in config.ARMORS.items():
        if a.get("sec", "normal") != sec:
            continue
        locked = user.level < a["min_level"]
        lines += [SEP, ""]
        lines.append(f"🔒 {a['name']} (قفل)" if locked else (a["name"] if _has_emoji(a["name"]) else f"🛡 {a['name']}"))
        lines.append("")
        lines.append(f"🛡 دفاع: {fa_num(a['defense'])}")
        if a.get("ability"):
            lines.append(f"🎯 قابلیت: {config.ARMOR_ABILITY_TEXT.get(a['ability']['kind'], '')}")
            flavor = config.ARMOR_FLAVOR_TEXT.get(a["ability"]["kind"])
            if flavor:
                lines.append(f"▫️ {flavor}")
        elif a.get("desc"):
            lines.append(f"▫️ {a['desc']}")
        lines.append("")
        cost_arm = f"💰 هزینه: {money(a['price'])}"
        parts_arm = config.SPECIAL_ARMOR_PARTS.get(key, 0)
        if parts_arm:
            have_arm = int(getattr(user, "legendary_parts", 0) or 0)
            mark_arm = "✅" if have_arm >= parts_arm else "❌"
            cost_arm += f" + 🧩 {fa_num(parts_arm)} قطعه افسانه‌ای ({mark_arm} تو {fa_num(have_arm)} تا داری)"
        lines.append(cost_arm)
        if locked:
            lines.append(f"⭕️ بازگشایی در سطح {fa_num(a['min_level'])}")
        lines.append("")
    lines.append(SEP)
    return "\n".join(lines)


def _dog_text(user) -> str:
    """فقط ویژگی اصلی هر نژاد، بدون توضیح طولانی، قیمت با تی‌پوینت کامل"""
    lines = ["<b>🛒 فروشگاه</b>", _status_line(user), "", "🐕 سگ‌ها", "", "برای خرید روی سگ موردنظر بزن", ""]
    for key, d in config.DOGS.items():
        crown = "👑 " if d.get("rare") else ""
        lines += [SEP, ""]
        lines.append(f"{crown}🐕 {d['name']}")
        lines.append(d["trait_line"])
        lines.append(f"💰 {money(d['price'])}")
        lines.append("")
    lines.append(SEP)
    return "\n".join(lines)


def _arti_pct(a: dict) -> str:
    """درصد اثر آرتیفکت که جلو متنش نوشته میشه، ضریب اعشاری (مثل شانس ×۱٫۵) گِرد نمیشه"""
    for k in ("atk_mult", "def_mult", "xp_mult", "steal_bonus"):
        if k in a:
            return f"(+{fa_num(int(a[k] * 100))}%)"
    if "luck" in a:
        v = float(a["luck"])
        vtxt = fa_num(int(v)) if v.is_integer() else f"{v:g}"
        return f"(×{vtxt})"
    return ""


def _arti_text(user) -> str:
    lines = ["<b>🛒 فروشگاه</b>", _status_line(user), "", "🧿 آرتیفکت‌ها", "", "آیتم‌های کمیاب آخر بازی", ""]
    for key, a in config.ARTIFACTS.items():
        locked = user.level < config.ARTIFACT_MIN_LEVEL
        lines += [SEP, ""]
        lines.append(f"🔒 {a['emoji']} {a['name']} (قفل)" if locked else f"{a['emoji']} {a['name']}")
        pct = _arti_pct(a)
        lines.append(f"{a['line']} {pct}".rstrip())
        lines.append(f"💰 {money(a['price'])}")
        if locked:
            lines.append(f"⭕️ بازگشایی در سطح {fa_num(config.ARTIFACT_MIN_LEVEL)}")
        lines.append("")
    lines.append(SEP)
    return "\n".join(lines)


def _res_text(user) -> str:
    from services import resources as res_svc
    return "\n".join([
        "<b>🛒 فروشگاه</b>",
        _status_line(user),
        "",
        "🎒 منابع",
        "",
        f"🪵 چوب {fa_num(user.wood)} از {fa_num(res_svc.wood_cap(user))}",
        f"⛏️ آهن {fa_num(user.iron)} از {fa_num(res_svc.iron_cap(user))}",
        "",
        "چوب و آهن از کنده‌کاری، شاپ و کارخانه به دست میان",
        "خریدش گرونه ولی تولیدش می‌صرفه",
        "فروش منابع اضافه هم از بخش انبار انجام میشه",
        "برای خرید روی جنس موردنظر بزن و بگو چندتا می‌خوای",
    ])


def _gear_up_text(kind: str, owned_lvls: dict[str, int], user) -> str:
    catalog = economy.gear_catalog(kind)
    emoji = "🔫" if kind == "weap" else "🛡"
    stat_emoji = "💥" if kind == "weap" else "🛡"
    stat_name = "دمیج" if kind == "weap" else "دفاع"
    items = [(k, lv) for k, lv in owned_lvls.items() if k in catalog]
    lines = [f"<b>⬆️ ارتقای {'سلاح' if kind == 'weap' else 'زره'}</b>", _status_line(user), ""]
    if not items:
        lines.append(f"اول یه {'سلاح' if kind == 'weap' else 'زره'} بخر")
        lines.append("هر آیتم تا لول 5 ارتقا داره و هر لول استتش بیشتر میشه")
        return "\n".join(lines)
    lines.append("هر ارتقا تی‌پوینت و آهن می‌خواد")
    lines.append("")
    for key, lv in sorted(items, key=lambda x: -x[1]):
        item = catalog[key]
        lines.append(SEP)
        lines.append("")
        lines.append(f"{_item_head(emoji, item['name'])} | لول {fa_num(lv)}")
        lines.append(f"{stat_emoji} {stat_name} {fa_num(economy.gear_stat(kind, key, lv))}")
        abil = item.get("ability")
        if abil and kind == "weap":
            pct_now = economy.gear_ability_pct_now(abil, lv)
            if pct_now:
                lines.append(f"🎯 قابلیت الان: {config.WEAPON_ABILITY_TEXT.get(abil['kind'], '')} | واقعی الان: {fa_num(int(round(pct_now * 100)))}%")
        if abil and kind == "arm":
            pct_now = economy.gear_ability_pct_now(abil, lv)
            if pct_now:
                lines.append(f"🎯 قابلیت الان: {config.ARMOR_ABILITY_TEXT.get(abil['kind'], '')} | واقعی الان: {fa_num(int(round(pct_now * 100)))}%")
        if lv >= config.GEAR_UPG_MAX:
            lines.append("👑 لول مکس")
        else:
            tp = economy.gear_upg_tp(kind, key, lv)
            iron = economy.gear_upg_iron(kind, key, lv)
            lines.append(f"⬆️ لول بعدی: {stat_name} {fa_num(economy.gear_stat(kind, key, lv + 1))}")
            if abil:
                pct_next = economy.gear_ability_pct_now(abil, lv + 1)
                if pct_next:
                    lines.append(f"⬆️ قابلیت بعد ارتقا: {fa_num(int(round(pct_next * 100)))}%")
            lines.append(f"🪙 هزینه: 💰 {money(tp)} + ⛏️ {fa_num(iron)} آهن")
            req = economy.gear_upg_min_level(lv)
            if user.level < req:
                lines.append(f"⭕️ بازگشایی در سطح {fa_num(req)}")
        lines.append("")
    lines.append(SEP)
    return "\n".join(lines)


async def _section_text(session, user, kind: str) -> str:
    if kind == "weap":
        return _weap_home_text(user)
    if kind.startswith("w") and kind[1:] in config.WEAPON_SECTIONS:
        return _wsec_text(user, kind[1:])
    if kind == "arm":
        return _arm_home_text(user)
    if kind.startswith("a") and kind[1:] in config.ARMOR_SECTIONS:
        return _arm_text(user, kind[1:])
    if kind == "arti":
        return _arti_text(user)
    if kind == "res":
        return _res_text(user)
    if kind in ("wup", "aup"):
        gkind = "weap" if kind == "wup" else "arm"
        lvls = {
            k: v for k, v in (await users.get_item_levels(session, user.id)).items()
            if k in economy.gear_catalog(gkind)
        }
        return _gear_up_text(gkind, lvls, user)
    if kind == "seed":
        stock = await farming.get_stock(session, user.id)
        have = "\n".join(
            f"🌾 {config.SEEDS[k]['name']} ×{fa_num(v)}"
            for k, v in stock.items() if v > 0
        )
        return (
            "<b>🌱 بذرها</b>\n"
            f"{_status_line(user)}\n\n"
            "صبر کن تا بذرها رشد کنن، بعدش برداشت کن\n\n"
            f"📦 انبارت:\n{have or '▫️ خالیه'}"
        )
    if kind == "dog":
        return _dog_text(user)
    if kind == "food":
        return (
            "<b>🍖 غذای سگ</b>\n"
            f"{_status_line(user)}\n\n"
            "غذا همون لحظه خریده و خورده میشه\n"
            "بنویس «تریاکی سگ‌های من» و دکمه 🍖 زیر سگت رو بزن"
        )
    return "❌ همچین بخشی نیس"


# ───────── نمایش ─────────

async def render_section(update: Update, kind: str, alert: str | None = None) -> None:
    """رندر یه بخش شاپ، بدون تکیه بر callback_data"""
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        text = await _section_text(s, user, kind)

        item_keys = set(await users.get_item_keys(s, user.id))
        if kind == "weap":
            markup = kb.shop_weap_sections_kb(user)
        elif kind.startswith("w") and kind[1:] in config.WEAPON_SECTIONS:
            markup = kb.shop_weap_kb(user, item_keys, kind[1:])
        elif kind == "arm":
            markup = kb.shop_arm_sections_kb(user)
        elif kind.startswith("a") and kind[1:] in config.ARMOR_SECTIONS:
            markup = kb.shop_arm_kb(user, item_keys, kind[1:])
        elif kind == "seed":
            markup = kb.shop_seed_kb(user, await farming.get_stock(s, user.id))
        elif kind == "dog":
            user_dogs = await dog_svc.get_user_dogs(s, user.id)
            markup = kb.shop_dog_kb(user, {d.dog_key for d in user_dogs}, len(user_dogs))
        elif kind == "food":
            markup = kb.shop_food_kb()
        elif kind == "res":
            markup = kb.shop_res_kb()
        elif kind == "arti":
            markup = kb.shop_arti_kb(user, item_keys)
        elif kind in ("wup", "aup"):
            gkind = "weap" if kind == "wup" else "arm"
            lvls = {
                k: v for k, v in (await users.get_item_levels(s, user.id)).items()
                if k in economy.gear_catalog(gkind)
            }
            markup = kb.gear_up_kb(gkind, lvls, user)
        else:
            await s.commit()
            return await shop_cb(update, None)
        await s.commit()

    await respond(update, text, markup, alert=alert)


async def shop_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        text = _sections_text(user.cash, user.level)
        await s.commit()
    await respond(update, text, kb.shop_sections_kb())


async def section_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, alert: str | None = None) -> None:
    await render_section(update, parts(update)[2], alert=alert)


# ───────── خرید (اینلاین) ─────────

async def buy_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, kind, key = parts(update)

    # خرید دونه‌ای منابع: اول تعداد پرسیده میشه، بعد فاکتور با تایید/لغو
    if kind == "res":
        info = config.RES_SHOP.get(key)
        if not info:
            return await shop_cb(update, context)
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            users.set_pending(user, "resbuy", key, chat_id_of(update))
            await s.commit()
        text = (
            f"<b>🛒 خرید {info['emoji']} {info['name']}</b>\n\n"
            f"چندتا {info['name']} میخوای بخری؟\n"
            "عددشو همینجا بنویس و بفرست، مثلا: 24\n"
            f"💸 قیمت هر دونه {money_tp(info['unit'])}\n\n"
            "❌ اگر هم پشیمون شدی بنویس «لغو»"
        )
        return await respond(update, text)

    # خرید بذر هم مثل آهن و چوب، تعداد پرسیده میشه و فاکتور میاد (درخواست کارفرما)
    if kind == "seed":
        info = config.SEEDS.get(key)
        if not info or info.get("legendary"):
            return await shop_cb(update, context)
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            unit = shop_svc.seed_unit_price(user, key)
            users.set_pending(user, "seedbuy", key, chat_id_of(update))
            await s.commit()
        text = (
            f"<b>🛒 خرید {info.get('emoji', '🌱')} {esc(info['name'])}</b>\n\n"
            f"چندتا بذر {esc(info['name'])} میخوای بخری؟\n"
            "عددشو همینجا بنویس و بفرست، مثلا: 5\n"
            f"💸 قیمت هر بذر {money_tp(unit)}\n\n"
            "❌ اگر هم پشیمون شدی بنویس «لغو»"
        )
        return await respond(update, text)

    item = (shop_svc.CATALOGS.get(kind) or {}).get(key) or config.DOGS.get(key)
    if not item:
        return await shop_cb(update, context)

    # خرید سگ فاکتور نداره، اول اسمش پرسیده میشه و بعد فاکتور تایید میاد
    if kind == "dog":
        async with session_scope() as s:
            user, _ = await users.get_or_create(s, update.effective_user)
            ok, alert = await dog_svc.hold_dog(s, user, key)
            await s.commit()
        if not ok:
            return await render_section(update, kind, alert=alert)
        return await respond(update, dogs_h.dog_name_question_text(item))

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        cash, iron = user.cash, user.iron
        await s.commit()

    emoji = shop_svc.KIND_EMOJI.get(kind, "🛒")
    stat_lines = ""
    if kind == "weap":
        stat_lines = (
            f"💥 دمیج +{fa_num(item['attack'])}\n"
            f"⛏️ آهن {fa_num(item['iron'])} (الان {fa_num(iron)} تا داری)\n"
        )
    elif kind == "arm":
        stat_lines = f"🛡 دفاع +{fa_num(item['defense'])}\n"
    elif kind == "arti":
        stat_lines = f"{item['line']}\n"
    elif kind == "seed":
        stat_lines = (
            f"⏱ رشد {fa_num(item['grow_min'])} دقیقه\n"
            f"💰 فروش {money_tp(item['sell'])}\n"
        )

    text = (
        "<b>🧾 فاکتور خرید</b>\n\n"
        f"{esc(_item_head(emoji, item['name']))}\n"
        f"{stat_lines}"
        f"💸 قیمت {money(item['price'])}\n"
        f"💵 بعد خرید {money(max(0, cash - item['price']))} برات میمونه\n\n"
        "معامله‌ست؟"
    )
    await respond(update, text, kb.confirm_kb(f"cf:shop:buy:{kind}:{key}"))


async def buy_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, _, kind, key = parts(update)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        _, alert = await shop_svc.purchase(s, user, kind, key)
        from services import onboarding as onb
        chain = await onb.first_weapon(s, user, kind)  # راهنمای نبرد بعد خرید اولین سلاح
        congrats = await onb.maybe_congrats(s, user)  # تبریک پایان مأموریت، فقط یه بار
        await s.commit()
    # اسلحه برمی‌گرده به دسته خودش (سرد | گرم | ویژه)
    if kind == "weap" and key in config.WEAPONS:
        kind = f"w{config.WEAPONS[key].get('sec', 'cold')}"
    # توجه: CallbackQuery تلگرام قابل تغییر نیس، به جای دست‌کاری data بخش رو مستقیم رندر می‌کنیم
    await render_section(update, kind, alert=alert)
    # زنجیره آنبوردینگ پیام جدا میاد تا فاکتور خرید شلوغ نشه
    from handlers.common import announce_notes
    await announce_notes(update, [x for x in (chain, congrats) if x])


# ───────── تایید فاکتور خرید دونه‌ای منابع (cf:shopres | cl:shopres) ─────────

async def buyres_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, res_key, qty_s = parts(update)
    info = config.RES_SHOP.get(res_key)
    if not info:
        return await shop_cb(update, context)
    qty = int(qty_s)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, out = await shop_svc.purchase_resource(s, user, res_key, qty)
        cur = user.wood if res_key == "wood" else user.iron
        cap = res_svc.wood_cap(user) if res_key == "wood" else res_svc.iron_cap(user)
        await s.commit()
    if not ok:
        return await respond(update, f"<b>{esc(out)}</b>", kb.shop_res_kb())
    text = (
        f"<b>✅ {esc(out)}</b>\n\n"
        f"{info['emoji']} موجودی انبارت: {fa_num(cur)} از {fa_num(cap)}"
    )
    await respond(update, text, kb.shop_res_kb())


async def buyres_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    return await render_section(update, "res", alert="❌ خرید لغو شد")


# ───────── تایید فاکتور خرید بذر با تعداد (cf:shopseed | cl:shopseed) ─────────

async def buyseed_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    p = parts(update)
    _, _, seed_key, qty_s = p[0], p[1], p[2], p[3]
    info = config.SEEDS.get(seed_key)
    if not info or info.get("legendary"):
        return await shop_cb(update, context)
    if len(p) > 4 and update.effective_user.id != int(p[4]):
        await update.callback_query.answer()  # فاکتور دستور متنی قفله به صاحبش، غریبه هیچی نمی‌بینه
        return
    qty = int(qty_s)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        ok, out = await shop_svc.purchase_seed(s, user, seed_key, qty)
        await s.commit()
    if not ok:
        return await render_section(update, "seed", alert=out)
    await render_section(update, "seed", alert=out)


async def buyseed_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    return await render_section(update, "seed", alert="❌ خرید لغو شد")


# ───────── ارتقای سلاح و زره ⬆️ ─────────

async def gear_up_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, kind, key = parts(update)
    catalog = economy.gear_catalog(kind)
    item = catalog.get(key)
    if not item:
        return await shop_cb(update, context)

    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        lv = (await users.get_item_levels(s, user.id)).get(key)
        await s.commit()

    if lv is None:
        return await render_section(update, "wup" if kind == "weap" else "aup", alert="❌ اینو نداری")
    if lv >= config.GEAR_UPG_MAX:
        return await render_section(update, "wup" if kind == "weap" else "aup", alert="👑 لول مکسه")

    tp = economy.gear_upg_tp(kind, key, lv)
    iron = economy.gear_upg_iron(kind, key, lv)
    stat_name = "دمیج" if kind == "weap" else "دفاع"
    stat_emoji = "💥" if kind == "weap" else "🛡"
    text = (
        f"<b>⬆️ ارتقای {esc(item['name'])}</b>\n\n"
        f"از لول {fa_num(lv)} به لول {fa_num(lv + 1)}\n"
        f"{stat_emoji} {stat_name} {fa_num(economy.gear_stat(kind, key, lv))} ← {fa_num(economy.gear_stat(kind, key, lv + 1))}\n"
        f"💸 تی‌پوینت {money(tp)}\n"
        f"⛏️ آهن {fa_num(iron)}\n\n"
        "انجامش بدیم؟"
    )
    await respond(update, text, kb.gear_up_confirm_kb(kind, key))


async def gear_up_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, kind, key = parts(update)
    async with session_scope() as s:
        user, _ = await users.get_or_create(s, update.effective_user)
        from models import InventoryItem
        from sqlalchemy import select
        q = select(InventoryItem).where(
            InventoryItem.user_id == user.id, InventoryItem.item_key == key
        )
        row = (await s.execute(q)).scalar_one_or_none()
        if not row:
            ok, alert = False, "❌ اینو نداری"
        elif row.level >= config.GEAR_UPG_MAX:
            ok, alert = False, "👑 لول مکسه"
        else:
            req = economy.gear_upg_min_level(row.level)
            tp = economy.gear_upg_tp(kind, key, row.level)
            iron = economy.gear_upg_iron(kind, key, row.level)
            if user.level < req:
                ok, alert = False, f"🔒 لول {fa_num(req)} می‌خواد"
            elif user.cash < tp:
                ok, alert = False, "❌ تی‌پوینتت کافی نیس"
            elif user.iron < iron:
                ok, alert = False, f"⛏️ {fa_num(iron)} آهن می‌خواد و {fa_num(user.iron)} تا داری"
            else:
                user.cash -= tp
                user.iron -= iron
                row.level += 1
                item = economy.gear_catalog(kind)[key]
                alert = f"⬆️ {item['name']} رفت رو لول {fa_num(row.level)}"
                # راند ۳۰ (باگ گزارش‌شده کارفرما): با آپگرید تفنگ خشاب تا ظرفیت جدید شارژ میشه
                from services import combat as _cbt30
                if kind == "weap" and _cbt30.is_gun(key):
                    row.ammo = _cbt30.ammo_cap(key, row.level)
                    alert += f" | 🔫 خشاب هم شارژ شد ({fa_num(row.ammo)} تیر)"
        await s.commit()
    # راند ۳۰ (درخواست کارفرما): بعد آپگرید برگرد رو کارت آیتم، نه منوی قدیمی ارتقا
    from handlers.gear import render_gear_item
    await render_gear_item(update, "weap" if kind == "weap" else "arm", key, alert=alert)


async def gear_up_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, kind = parts(update)
    await render_section(update, "wup" if kind == "weap" else "aup")
