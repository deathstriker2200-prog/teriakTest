"""
کیبوردهای اینلاین با استایل رنگی تلگرام
primary = آبی (اکشن‌های اصلی) | success = سبز (تایید) | danger = قرمز (لغو)

ساختار callback_data یکدسته: «بخش:اکشن:پارتامترها»
مسیر تایید اکشن‌های مهم با پیشوند cf: اجرا میشه | cl همیشه لغوه
تایید دستورهای متنی گروه با پیشوند txcf: و id کاربر، فقط خودش بتونه تایید کنه

menu:home | menu:profile | menu:farm | menu:shop | menu:attack | menu:rank | menu:dogs
farm:buy                    → cf:farm:buy
farm:plant:<plot_id>        → انتخاب بذر از انبار
farm:plant:<plot_id>:<seed> → cf:plant:<plot_id>:<seed>
farm:hv                     → برداشت همه آماده‌ها (کولدان ۲ دقیقه)
farm:up:<plot_id>           → cf:farm:up:<plot_id>
shop:sec:<kind>             → بخش‌های شاپ: weap | arm | seed | dog | food
shop:buy:<kind>:<key>       → cf:shop:buy:<kind>:<key>
txcf:<kind>:<key>:<tg_id>   → تایید خرید دستور متنی (فقط خودش)
dogs:feed:<dog_id>          → کارت آمار سگ با همان دکمه‌های غذا (cf:feed:<dog_id>:<food>)
heal:buy:<key>              → خرید و استفاده همون لحظه آیتم درمان
patt:go                     → 🎯 هدف شانسی پی‌وی، پیش‌نمایش قربانی → patt:hit:<user_id> حمله | patt:next:<user_id> هدف دیگه (هزینه‌دار) | patt:back بازگشت | patt:break:<user_id> شکستن سپر
menu:team | team:quests | team:mine | team:top | team:leave | team:disband
team:mng | team:req         → 👑 مدیریت کارتل (رهبر/مدیر) و لیست درخواست‌های عضویت
treq:<ok|no>:<req_id>       → قبول/رد درخواست عضویت توسط مدیر
team:kick | tkick:<member_id> | tkcl → جریان اخراج عضو (سرچ → تایید → اجرا)
tmcf:<leave|disband>:<tg_id> → تایید ترک/انحلال کارتل (فقط خودش)
dog:card:<dog_id>           → کارت آمار سگ (آمار [اسم])
noop:<context>              → دکمه‌های اطلاعاتی
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config
from models import Dog, Plot, User
from services import economy
from services.dogs import dog_xp_need
from utils import fa_dur, fa_num, money_tp, short_name

PRIMARY = "primary"
SUCCESS = "success"
DANGER = "danger"

# یوزرنیم ربات موقع استارت ست میشه، برای دکمه «افزودن به گروه»
BOT_USERNAME = ""


def _btn(text: str, data: str, style: str | None = PRIMARY) -> InlineKeyboardButton:
    """پیش‌فرض همه دکمه‌ها آبیه مگر اینکه سبز یا قرمز گفته شده باشه
    قفل‌ها (🔒) همیشه قرمزن، فقط دکمه‌های نمایشی بی‌کار (شماره زمین | تایمرها) بدون رنگ‌ان"""
    kwargs = {"callback_data": data}
    if style:
        kwargs["style"] = style
    return InlineKeyboardButton(text, **kwargs)


# ───────── عمومی ─────────

def main_menu_kb() -> InlineKeyboardMarkup:
    """چینش جدید منو (درخواست کارفرما): ترکیب ردیف‌های تکی و دوتایی و سه‌تایی"""
    rows = [
        [_btn("🌾 مزرعه من", "menu:farm", PRIMARY)],
        [_btn("🏪 فروشگاه", "menu:shop", PRIMARY),
         _btn("⚔️ حمله", "menu:attack", PRIMARY)],
        [_btn("🎒 انبار", "menu:shelter", PRIMARY),
         _btn("⛏️ کنده‌کاری", "menu:mine", PRIMARY)],
        [_btn("🏦 بانک", "menu:bank", PRIMARY)],
        [_btn("⭐️ مهارت", "menu:skills", PRIMARY),
         _btn("🛡 تجهیزات", "menu:gear", PRIMARY)],
        [_btn("🐕 سگ‌ها", "menu:dogs", PRIMARY),
         _btn("🎯 مأموریت", "menu:dquests", PRIMARY),
         _btn("🏢 شرکت", "menu:company", PRIMARY)],
        [_btn("🏆 رتبه‌بندی", "menu:rank", PRIMARY),
         _btn("📖 راهنما", "help:menu", PRIMARY),
         _btn("🚩 کارتل من", "menu:team", PRIMARY)],
    ]
    if BOT_USERNAME:
        rows.append([InlineKeyboardButton(
            "➕ افزودن به گروه",
            url=f"https://t.me/{BOT_USERNAME}?startgroup=true",
            style=PRIMARY,
        )])
    return InlineKeyboardMarkup(rows)


def home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("🏠 منوی اصلی", "menu:home", PRIMARY)]])


def confirm_kb(confirm_data: str) -> InlineKeyboardMarkup:
    """کیبورد تایید استاندارد، تایید سبز | لغو قرمز"""
    return InlineKeyboardMarkup([[
        _btn("✅ تایید", confirm_data, SUCCESS),
        _btn("❌ لغو", "cl", DANGER),
    ]])


def tx_confirm_kb(kind: str, key: str, tg_id: int, dog_name: str | None = None) -> InlineKeyboardMarkup:
    """تایید خرید دستور متنی، id کاربر داخل دیتا ست میشه که غریبه نتونه بزنه"""
    data = f"txcf:{kind}:{key}:{tg_id}"
    if dog_name:
        safe = dog_name.replace(":", " ").strip()[:12]  # سقف بایت callback_data
        if safe:
            data += f":{safe}"
    return InlineKeyboardMarkup([[
        _btn("✅ تایید", data, SUCCESS),
        _btn("❌ لغو", f"txcl:{tg_id}", DANGER),
    ]])


def admin_kb() -> InlineKeyboardMarkup:
    """پنل ادمین، پول/XP + آمار + عضویت اجباری"""
    return InlineKeyboardMarkup([
        [_btn("💵 +10,000 TP", "adm:cash:10000", SUCCESS),
         _btn("💵 +100,000 TP", "adm:cash:100000", SUCCESS)],
        [_btn("✨ +100 XP", "adm:xp:100", PRIMARY),
         _btn("✨ +1,000 XP", "adm:xp:1000", PRIMARY)],
        [_btn("📊 آمار ربات", "adm:stats:0", PRIMARY)],
        [_btn("📣 پیام همگانی", "adm:bcast:0", PRIMARY)],
        [_btn("📢 عضویت اجباری", "adm:fj:0", PRIMARY)],
        [_btn("👹 باس‌ها", "admb:l:0", PRIMARY)],
        [_btn("🗄 بکاپ تریاکی", "bk:menu", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


def backup_menu_kb(is_admin: bool) -> InlineKeyboardMarkup:
    """منوی بک‌آپ، آپلود فقط برای ادمینه چون ری‌استور خطرناکه"""
    rows = [[_btn("🗄 ساخت بکاپ", "bk:make", SUCCESS)]]
    if is_admin:
        rows.append([_btn("📤 آپلود بکاپ", "bk:up", PRIMARY)])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def admin_stats_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("🔃 رفرش", "adm:stats:0", PRIMARY)],
        [_btn("🔙 پنل ادمین", "adm:panel:0", PRIMARY)],
    ])


def admin_fj_kb(st: dict) -> InlineKeyboardMarkup:
    """کیبورد مدیریت عضویت اجباری بر اساس وضعیت فعلی"""
    rows: list[list[InlineKeyboardButton]] = []
    if st.get("channel"):
        rows.append([_btn(
            "⏸ غیرفعال کن" if st.get("on") else "▶️ فعال کن",
            "adm:fjtog:0", DANGER if st.get("on") else SUCCESS,
        )])
        rows.append([_btn("🗑 حذف کانال", "adm:fjdel:0", DANGER)])
    rows.append([_btn("🔗 ست کردن کانال", "adm:fjset:0", SUCCESS)])
    rows.append([_btn("🔙 پنل ادمین", "adm:panel:0", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def force_join_kb(link: str) -> InlineKeyboardMarkup:
    """دکمه‌های پیام گیت عضویت اجباری"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 عضویت در کانال", url=link)],
        [_btn("✅ تایید عضویت", "fj:check", SUCCESS)],
    ])


def clearacc_confirm_kb(tg_id: int) -> InlineKeyboardMarkup:
    """تایید ریست کامل اکانت (/clearacc)، فقط خود ادمین"""
    return InlineKeyboardMarkup([[
        _btn("✅ تایید، همه چیشو پاک کن", f"cacc:ok:{tg_id}", SUCCESS),
        _btn("❌ لغو", f"cacc:no:{tg_id}", DANGER),
    ]])


def admin_users_kb(users: list) -> InlineKeyboardMarkup:
    """لیست نتایج جستجوی /user، هرکدوم یه دکمه"""
    rows = []
    for u in users:
        name = u.first_name or u.username or f"کاربر {u.telegram_id}"
        rows.append([_btn(f"👤 {name} | {u.telegram_id}", f"adm:u:{u.telegram_id}", PRIMARY)])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def admin_user_kb(tg_id: int) -> InlineKeyboardMarkup:
    """دکمه‌های کارت کاربر تو پنل ادمین (gtp/gxp = دادن به اون کاربر)"""
    return InlineKeyboardMarkup([
        [_btn("💰 پول بده", f"adm:gtp:{tg_id}", SUCCESS)],
        [_btn("✨ XP بده", f"adm:gxp:{tg_id}", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


# ───────── آموزشات (هلپ دکمه‌دار) 📖 ─────────
# key → عنوان دکمه، متن کامل هر بخش تو handlers/start.py (HELP_SECTIONS)
HELP_MENU = [
    ("start",     "📖 شروع بازی"),
    ("battle",    "⚔️ نبرد"),
    ("mine",      "⛏ کنده‌کاری"),
    ("farm",      "🌱 مزرعه"),
    ("dogs",      "🐕 سگ‌ها"),
    ("company",   "🏭 شرکت"),
    ("shelter",   "🏚 انبار"),
    ("smuggle",   "🚚 محموله و کاروان"),
    ("team",      "👥 کارتل"),
    ("resources", "🎒 منابع"),
    ("shop",      "🛒 فروشگاه"),
    ("skills",    "⭐️ مهارت‌ها"),
    ("gear",      "🛡 تجهیزات"),
    ("titles",    "🏅 لقب‌ها"),
    ("casino",    "🎰 قمارخانه"),
    ("bank",      "🏦 بانک"),
    ("quests",    "📋 ماموریت روزانه"),
    ("misc",      "🧭 متفرقه"),
]


def help_menu_kb() -> InlineKeyboardMarkup:
    """منوی بخش‌های آموزشات، هر بخش یه دکمه + دکمه منوی اصلی تهش"""
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(HELP_MENU), 2):
        chunk = HELP_MENU[i:i + 2]
        rows.append([_btn(title, f"help:sec:{key}", PRIMARY) for key, title in chunk])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def help_back_kb() -> InlineKeyboardMarkup:
    """🔙 آموزشات، برگشت به منوی اصلی هلپ"""
    return InlineKeyboardMarkup([
        [_btn("🔙 آموزشات", "help:menu", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


# ───────── پروفایل ─────────

def profile_kb() -> InlineKeyboardMarkup:
    """کیبورد پروفایل، دکمه رفرش حذف شد چون کاربرد خاصی نداشت"""
    return InlineKeyboardMarkup([
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


# ───────── مزرعه ─────────

def farm_kb(user: User, plots: list[Plot], next_price: int, ready_count: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for i, plot in enumerate(plots, 1):
        state, left = plot.current_status()
        lvl_label = "👑 لول مکس" if plot.level >= config.PLOT_MAX_LEVEL else f"لول {fa_num(plot.level)}"
        rows.append([_btn(f"🗺 زمین {fa_num(i)} | {lvl_label}", f"noop:plot:{i}", None)])

        actions: list[InlineKeyboardButton] = []
        if state == "building":
            actions.append(_btn(f"🔨 ساخت: {fa_dur(left)}", "noop:build", None))
            actions.append(_btn("💎 تسریع", f"farm:spd:{plot.id}", SUCCESS))
        elif state == "empty":
            actions.append(_btn("🌱 کاشت", f"farm:plant:{plot.id}"))
        elif state == "growing":
            actions.append(_btn(f"⏳ {fa_dur(left)}", "noop:grow", None))
        else:
            actions.append(_btn("✅ آماده", "noop:ready", None))

        if state != "building":
            if plot.level < config.PLOT_MAX_LEVEL:
                up_req = economy.plot_upgrade_required_level(plot.level)
                if user.level >= up_req:
                    actions.append(_btn(f"⬆️ آپگرید | {money_tp(economy.upgrade_price(plot.level))}", f"farm:up:{plot.id}", PRIMARY))
                else:
                    actions.append(_btn(f"🔒 آپگرید | لول {fa_num(up_req)}", "noop:uplock", DANGER))
            else:
                actions.append(_btn("👑 لول مکس", "noop:maxplot", None))
        rows.append(actions)

    if ready_count:
        rows.append([_btn(f"📦 برداشت همه آماده‌ها ({fa_num(ready_count)})", "farm:hv", SUCCESS)])

    if len(plots) < config.MAX_PLOTS:
        req = economy.plot_required_level(len(plots))
        n_next = len(plots) + 1
        spec = config.PLOT_CATALOG.get(n_next, {})
        gem_price = int(spec.get("gem_price", 0) or 0)
        price_label = f"💎 {fa_num(gem_price)}" if gem_price > 0 else f"🪙 {money_tp(next_price)}"
        if user.level >= req:
            rows.append([_btn(
                f"🔨 ساخت زمین {fa_num(n_next)} | {price_label}",
                "farm:buy", PRIMARY,
            )])
        else:
            rows.append([_btn(
                f"🔒 ساخت زمین {fa_num(n_next)} | {price_label} | لول {fa_num(req)}",
                "noop:lock", DANGER,
            )])
    else:
        rows.append([_btn(f"🏡 هر {fa_num(config.MAX_PLOTS)} زمین رو داری", "noop:maxplots", None)])

    rows.append([_btn("🔄 آپدیت", "farm:rf", PRIMARY)])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def plot_speed_kb(plot_id: int, hour_gems: int, spm: int = 1) -> InlineKeyboardMarkup:
    """منوی 💎 تسریع ساخت زمین: دقیقه با ۱ جم (نرخ spm) | ۱ ساعت | کامل کردن"""
    return InlineKeyboardMarkup([
        [_btn(f"⚡ +{fa_num(spm)} دقیقه (۱ جم)", f"farm:spddo:{plot_id}:1", SUCCESS)],
        [_btn(f"⚡ +۱ ساعت ({fa_num(hour_gems)} جم)", f"farm:spddo:{plot_id}:{hour_gems}", SUCCESS)],
        [_btn("🚀 کامل کن", f"farm:spddo:{plot_id}:0", PRIMARY)],
        [_btn("🔙 مزرعه", "farm:rf", PRIMARY)],
    ])


def seeds_kb(user: User, plot: Plot, stock: dict[str, int],
             grow_times: dict[str, int] | None = None) -> InlineKeyboardMarkup:
    """
    انتخاب بذر از انبار برای کاشت روی زمین
    grow_times: زمان زنده هر بذر (آب‌وهوا + مهارت + لول زمین، مثل اجرای واقعی) | نباشه فقط لول زمین حساب میشه
    """
    rows: list[list[InlineKeyboardButton]] = []
    for key, seed in config.SEEDS.items():
        have = stock.get(key, 0)
        if have <= 0:
            continue
        secs = (grow_times or {}).get(key) or economy.crop_grow_seconds(key, plot.level)
        label = (
            f"{seed.get('emoji', '🌱')} {seed['name']} ×{fa_num(have)}"
            f" | ⏱ {fa_dur(secs)}"
            f" | 💰 {money_tp(economy.crop_yield(key, plot.level, user.level))}"
        )
        rows.append([_btn(label, f"farm:plant:{plot.id}:{key}")])
    rows.append([_btn("🌾 بذر ندارم | برم شاپ", "shop:sec:seed", PRIMARY)])
    rows.append([_btn("🔙 برگرد به مزرعه", "menu:farm", PRIMARY)])
    return InlineKeyboardMarkup(rows)


# ───────── فروشگاه ─────────

def shop_sections_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("🔫 سلاح‌ها", "shop:sec:weap", PRIMARY),
         _btn("🛡 زره‌ها", "shop:sec:arm", PRIMARY)],
        [_btn("🛡 تجهیزات و آپگرید", "menu:gear", PRIMARY)],
        [_btn("🧿 آرتیفکت", "shop:sec:arti", PRIMARY),
         _btn("🎒 منابع", "shop:sec:res", PRIMARY)],
        [_btn("🌱 بذرها", "shop:sec:seed", PRIMARY),
         _btn("🐕 سگ‌ها", "shop:sec:dog", PRIMARY)],
        [_btn("🍖 غذای سگ", "shop:sec:food", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


def shop_res_kb() -> InlineKeyboardMarkup:
    """بخش منابع شاپ، خرید دونه‌ای چوب و آهن | قیمت دونه تو دکمه‌ست"""
    rows = []
    for key, r in config.RES_SHOP.items():
        rows.append([_btn(
            f"{r['emoji']} {r['name']} | دونه {money_tp(r['unit'])}",
            f"shop:buy:res:{key}", SUCCESS,
        )])
    rows.append([_btn("🔙 بخش‌های شاپ", "menu:shop", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def shop_arti_kb(user: User, owned: set[str]) -> InlineKeyboardMarkup:
    """آرتیفکت‌های آخر بازی، سبز قابل خرید و قرمز قفل | قیمت تو دکمه نیس"""
    rows = []
    for key, a in config.ARTIFACTS.items():
        if f"arti_{key}" in owned:
            rows.append([_btn(f"✅ {a['emoji']} {a['name']}", "noop:own", None)])
        elif user.level < config.ARTIFACT_MIN_LEVEL:
            rows.append([_btn(
                f"🔒 {a['emoji']} {a['name']} به لول {fa_num(config.ARTIFACT_MIN_LEVEL)}",
                "noop:lock", DANGER,
            )])
        else:
            rows.append([_btn(
                f"{a['emoji']} {a['name']}",
                f"shop:buy:arti:{key}", SUCCESS,
            )])
    rows.append([_btn("🔙 بخش‌های شاپ", "menu:shop", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def skills_kb(user: User) -> InlineKeyboardMarkup:
    """کیبورد بخش مهارت، بالا بردن هر قابلیت ۱ امتیاز می‌خواد + دکمه ریست"""
    rows = []
    for key, sk in config.SKILLS.items():
        lv = min(max(int(getattr(user, f"skill_{key}", 0) or 0), 0), config.SKILL_MAX_LEVEL)
        if lv >= config.SKILL_MAX_LEVEL:
            rows.append([_btn(f"👑 {sk['name']} | لول مکس", "noop:maxskill", None)])
        else:
            rows.append([_btn(
                f"{sk['name']} | {fa_num(lv)} ← {fa_num(lv + 1)}",
                f"sk:up:{key}", SUCCESS,
            )])
    rows.append([_btn(f"♻️ ریست مهارت‌ها | {money_tp(config.SKILL_RESET_COST)}", "sk:reset", DANGER)])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def gear_kb(user: User, owned_lvls: dict[str, int], tab: str = "weap") -> InlineKeyboardMarkup:
    """کیبورد بخش تجهیزات: تب سلاح/زره + کارت هر آیتم (gear:it) + دست خالی + آپگرید"""
    is_w = tab == "weap"
    catalog = config.WEAPONS if is_w else config.ARMORS
    eq = user.equipped_weapon if is_w else user.equipped_armor
    rows = [[
        _btn("🔫 سلاح‌ها", "gear:tab:weap", SUCCESS if is_w else PRIMARY),
        _btn("🛡 زره‌ها", "gear:tab:arm", PRIMARY if is_w else SUCCESS),
    ]]
    order = list(catalog.keys())
    for key in sorted((k for k in owned_lvls if k in catalog), key=order.index):
        item = catalog[key]
        lv = owned_lvls.get(key, 1)
        lvtxt = f" +{fa_num(lv - 1)}" if lv and lv > 1 else ""
        if key == eq:
            rows.append([_btn(f"✅ {item['name']}{lvtxt}", f"gear:it:{tab}:{key}", None)])
        else:
            rows.append([_btn(f"🖐 {item['name']}{lvtxt}", f"gear:it:{tab}:{key}", SUCCESS)])
    if eq:
        rows.append([_btn(
            "👊 دست خالی" if is_w else "🦺 بدون زره",
            f"gear:un:{tab}", DANGER,
        )])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def gear_item_kb(tab: str, key: str, equipped: bool, is_gun: bool, can_reload: bool,
                 lv: int = 1) -> InlineKeyboardMarkup:
    """کارت یه آیتم تجهیزات: انتخاب/آپگرید همون آیتم/ریلود (راند ۳۰، درخواست کارفرما)"""
    rows: list[list[InlineKeyboardButton]] = []
    if equipped:
        rows.append([_btn("✅ انتخاب شده", "noop:own", None)])
    else:
        rows.append([_btn("🖐 انتخاب", f"gear:eqs:{tab}:{key}", SUCCESS)])
    if lv < config.GEAR_UPG_MAX:
        rows.append([_btn(f"⬆️ آپگرید به لول {fa_num(lv + 1)}", f"gear:upgi:{tab}:{key}", PRIMARY)])
    else:
        rows.append([_btn("👑 لول مکسه", "noop:own", None)])
    if is_gun and can_reload:
        rows.append([_btn("🔫 ریلود مهمات", f"gear:rel:{key}", PRIMARY)])
    rows.append([_btn("🔙 تجهیزات", "menu:gear", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def gear_item_upg_kb(tab: str, key: str) -> InlineKeyboardMarkup:
    """تایید آپگرید از داخل کارت آیتم: تایید سبز با فلوی قدیمی cf:gup + برگشت به کارت"""
    kind = "weap" if tab == "weap" else "arm"
    return InlineKeyboardMarkup([
        [_btn("✅ تایید", f"cf:gup:{kind}:{key}", SUCCESS)],
        [_btn("🔙 کارت آیتم", f"gear:it:{tab}:{key}", PRIMARY)],
    ])


def reload_confirm_kb(key: str, tg_id: int) -> InlineKeyboardMarkup:
    """تاییدیه ریلود مهمات، قفل به آیدی شروع‌کننده + برگشت به کارت با لغو"""
    return InlineKeyboardMarkup([[
        _btn("✅ تایید", f"gear:reldo:{key}:{tg_id}", SUCCESS),
        _btn("❌ لغو", f"gear:relcl:{key}", DANGER),
    ]])


def bribe_confirm_kb(tg_id: int) -> InlineKeyboardMarkup:
    """تاییدیه پرداخت رشوه زندان (راند ۲۹)، قفل به آیدی زندانی"""
    return InlineKeyboardMarkup([[
        _btn("✅ پرداخت رشوه", f"brcf:{tg_id}", SUCCESS),
        _btn("❌ لغو", f"brcl:{tg_id}", DANGER),
    ]])


def gear_upgrade_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع آپگرید تو بخش تجهیزات"""
    return InlineKeyboardMarkup([
        [_btn("⬆️ ارتقای سلاح", "shop:sec:wup", PRIMARY),
         _btn("⬆️ ارتقای زره", "shop:sec:aup", PRIMARY)],
        [_btn("🔙 تجهیزات", "menu:gear", PRIMARY)],
    ])


def buyseed_confirm_kb(seed_key: str, qty: int, tg_id: int = 0) -> InlineKeyboardMarkup:
    """تایید فاکتور خرید بذر با تعداد (مثل فلوی آهن و چوب)، tg_id>0 قفل به شروع‌کننده"""
    data = f"cf:shopseed:{seed_key}:{qty}"
    if tg_id:
        data += f":{tg_id}"
    return InlineKeyboardMarkup([[
        _btn("✅ تایید", data, SUCCESS),
        _btn("❌ لغو", "cl:shopseed", DANGER),
    ]])


def team_admin_confirm_kb(member_id: int, action: str, tg_id: int = 0) -> InlineKeyboardMarkup:
    """تاییدیه «کارتل اد ادمین» (add) و «کارتل حذف ادمین» (del)، قفل به آیدی رهبرِ شروع‌کننده"""
    return InlineKeyboardMarkup([[
        _btn("✅ تایید", f"tadm:{action}:{member_id}:{tg_id}", SUCCESS),
        _btn("❌ لغو", f"tadm:no:{tg_id}", DANGER),
    ]])


def gear_up_kb(kind: str, owned_lvls: dict[str, int], user: User) -> InlineKeyboardMarkup:
    """لیست آیتم‌های قابل ارتقا (فقط مال خودت)، با قیمت و لول بعدی"""
    from services import economy
    catalog = economy.gear_catalog(kind)
    emoji = "🔫" if kind == "weap" else "🛡"
    rows = []
    for key, lv in sorted(owned_lvls.items()):
        if key not in catalog:
            continue
        item = catalog[key]
        if lv >= config.GEAR_UPG_MAX:
            rows.append([_btn(f"👑 {item['name']} | لول مکس", "noop:maxgear", None)])
            continue
        req = economy.gear_upg_min_level(lv)
        if user.level < req:
            rows.append([_btn(
                f"🔒 {item['name']} به لول {fa_num(lv + 1)} | سطح {fa_num(req)} می‌خواد",
                "noop:lock", DANGER,
            )])
            continue
        rows.append([_btn(
            f"⬆️ {item['name']} به لول {fa_num(lv + 1)}",
            f"gup:{kind}:{key}", SUCCESS,
        )])
    rows.append([_btn("🔙 بخش‌های شاپ", "menu:shop", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def gear_up_confirm_kb(kind: str, key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _btn("✅ تایید", f"cf:gup:{kind}:{key}", SUCCESS),
        _btn("❌ لغو", f"cl:gup:{kind}", DANGER),
    ]])


def shop_weap_sections_kb(user: User) -> InlineKeyboardMarkup:
    """سه دسته سلاح سرد | گرم | ویژه، تا لول به سلاح‌های یه بخش نرسه قفل قرمزه"""
    rows = []
    for sec, sc in config.WEAPON_SECTIONS.items():
        keys = [k for k, w in config.WEAPONS.items() if w.get("sec", "cold") == sec]
        if not keys:
            continue
        minlvl = min(config.WEAPONS[k]["min_level"] for k in keys)
        if user.level < minlvl:
            rows.append([_btn(f"🔒 {sc['emoji']} {sc['name']} به لول {fa_num(minlvl)}", "noop:lock", DANGER)])
        else:
            rows.append([_btn(f"{sc['emoji']} {sc['name']}", f"shop:sec:w{sec}", SUCCESS)])
    rows.append([_btn("🛡 بخش تجهیزات", "menu:gear", PRIMARY)])
    rows.append([_btn("🔙 بخش‌های شاپ", "menu:shop", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def shop_weap_kb(user: User, owned: set[str], sec: str = "cold") -> InlineKeyboardMarkup:
    """دکمه فقط اسم سلاحه، قیمت تو باکس و فاکتور میاد | سبز یعنی قابل خرید و قرمز یعنی قفل"""
    rows = []
    for key, w in config.WEAPONS.items():
        if w.get("sec", "cold") != sec:
            continue
        if key in owned:
            rows.append([_btn(f"✅ {w['name']}", "noop:own", None)])
        elif user.level < w["min_level"]:
            rows.append([_btn(f"🔒 {w['name']} به لول {fa_num(w['min_level'])}", "noop:lock", DANGER)])
        else:
            rows.append([_btn(f"{w['name']}", f"shop:buy:weap:{key}", SUCCESS)])
    rows.append([_btn("🔙 سلاح‌ها", "shop:sec:weap", PRIMARY)])
    rows.append([_btn("🔙 بخش‌های شاپ", "menu:shop", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def shop_arm_sections_kb(user: User) -> InlineKeyboardMarkup:
    """دو دسته زره معمولی | ویژه (راند ۱۹)، تا لول به زره‌های یه بخش نرسه قفل قرمزه"""
    rows = []
    for sec, sc in config.ARMOR_SECTIONS.items():
        keys = [key for key, a in config.ARMORS.items() if a.get("sec", "normal") == sec]
        if not keys:
            continue
        minlvl = min(config.ARMORS[key]["min_level"] for key in keys)
        if user.level < minlvl:
            rows.append([_btn(f"🔒 {sc['emoji']} {sc['name']} به لول {fa_num(minlvl)}", "noop:lock", DANGER)])
        else:
            rows.append([_btn(f"{sc['emoji']} {sc['name']}", f"shop:sec:a{sec}", SUCCESS)])
    rows.append([_btn("🛡 بخش تجهیزات", "menu:gear", PRIMARY)])
    rows.append([_btn("🔙 بخش‌های شاپ", "menu:shop", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def shop_arm_kb(user: User, owned: set[str], sec: str = "normal") -> InlineKeyboardMarkup:
    rows = []
    for key, a in config.ARMORS.items():
        if a.get("sec", "normal") != sec:
            continue
        if key in owned:
            rows.append([_btn(f"✅ {a['name']}", "noop:own", None)])
        elif user.level < a["min_level"]:
            rows.append([_btn(f"🔒 {a['name']} به لول {fa_num(a['min_level'])}", "noop:lock", DANGER)])
        else:
            rows.append([_btn(f"{a['name']}", f"shop:buy:arm:{key}", SUCCESS)])
    rows.append([_btn("🔙 زره‌ها", "shop:sec:arm", PRIMARY)])
    rows.append([_btn("🔙 بخش‌های شاپ", "menu:shop", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def shop_seed_kb(user: User, stock: dict[str, int]) -> InlineKeyboardMarkup:
    rows = []
    for key, s in config.SEEDS.items():
        if s.get("legendary"):
            continue  # بذر افسانه‌ای تو شاپ نیس، فقط جستجو/کاروان
        if user.level < s["min_level"]:
            rows.append([_btn(f"🔒 {s['name']} به لول {fa_num(s['min_level'])}", "noop:lock", DANGER)])
        else:
            have = stock.get(key, 0)
            have_txt = f" | 📦 ×{fa_num(have)}" if have else ""
            rows.append([_btn(
                f"{s.get('emoji', '🌱')} {s['name']}{have_txt}",
                f"shop:buy:seed:{key}", SUCCESS,
            )])
    rows.append([_btn("🌱 مزرعه من", "menu:farm", PRIMARY)])
    rows.append([_btn("🔙 بخش‌های شاپ", "menu:shop", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def shop_dog_kb(user: User, owned_keys: set[str], dogs_count: int) -> InlineKeyboardMarkup:
    rows = []
    for key, d in config.DOGS.items():
        if key in owned_keys:
            rows.append([_btn(f"✅ {d['name']}", "noop:own", None)])
        elif user.level < d["min_level"]:
            rows.append([_btn(f"🔒 {d['name']} به لول {fa_num(d['min_level'])}", "noop:lock", DANGER)])
        else:
            crown = "👑 " if d.get("rare") else ""
            rows.append([_btn(
                f"{crown}🐕 {d['name']}",
                f"shop:buy:dog:{key}", SUCCESS,
            )])
    rows.append([_btn("🔙 بخش‌های شاپ", "menu:shop", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def shop_food_kb() -> InlineKeyboardMarkup:
    rows = []
    for key, f in config.DOG_FOODS.items():
        rows.append([_btn(
            f"{f['name']} | +{fa_num(f['xp'])} XP",
            "noop:feedinfo", None,
        )])
    rows.append([_btn("🔙 بخش‌های شاپ", "menu:shop", PRIMARY)])
    return InlineKeyboardMarkup(rows)


# ───────── سگ‌های من ─────────

def my_dogs_kb(dogs: list[Dog]) -> InlineKeyboardMarkup:
    rows = []
    for d in dogs:
        crown = "👑 " if d.cfg.get("rare") else ""
        rows.append([_btn(f"{crown}🐕 {d.name} | لول {fa_num(d.level)}", f"dog:card:{d.id}")])
        need = dog_xp_need(d.level)
        rows.append([_btn(f"🍖 غذا بده ({fa_num(d.xp)}/{fa_num(need)} XP)", f"dogs:feed:{d.id}", SUCCESS)])
    if len(dogs) < config.MAX_DOGS:
        rows.append([_btn("🛒 خرید سگ جدید", "shop:sec:dog", PRIMARY)])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def dog_card_kb(dog: Dog, feeds_left: int) -> InlineKeyboardMarkup:
    """کیبورد کارت آمار یه سگ، از همونجا میشه غذاش داد («آمار اصغر»)"""
    rows: list[list[InlineKeyboardButton]] = []
    if dog.level >= config.DOG_MAX_LEVEL:
        rows.append([_btn("👑 لول مکس", "noop:maxdog", None)])
    elif feeds_left > 0:
        for key, f in config.DOG_FOODS.items():
            rows.append([_btn(
                f"🍖 {f['name']} | +{fa_num(f['xp'])} XP | {money_tp(f['price'])}",
                f"cf:feed:{dog.id}:{key}", SUCCESS,
            )])
    else:
        rows.append([_btn("🍖 سیر شده", "noop:feedinfo", DANGER)])
    rows.append([_btn("🔙 سگ‌های من", "menu:dogs", PRIMARY),
                 _btn("🕊 رهاش کن", f"dog:rel:{dog.id}", DANGER)])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def release_confirm_kb(dog_id: int, tg_id: int) -> InlineKeyboardMarkup:
    """تایید رها کردن سگ، فقط صاحبش"""
    return InlineKeyboardMarkup([[
        _btn("✅ رهاش کن", f"relcf:{dog_id}:{tg_id}", SUCCESS),
        _btn("❌ لغو", f"txcl:{tg_id}", DANGER),
    ]])


def team_create_confirm_kb(tg_id: int) -> InlineKeyboardMarkup:
    """تایید ساخت کارتل بعد از اسم دادن، فقط خودش"""
    return InlineKeyboardMarkup([[
        _btn("✅ تایید", f"teamcf:ok:{tg_id}", SUCCESS),
        _btn("❌ لغو", f"teamcf:no:{tg_id}", DANGER),
    ]])



# ───────── درمان ❤️ ─────────

def pv_attack_kb() -> InlineKeyboardMarkup:
    """پنل حمله پی‌وی، فقط دکمه هدف شانسی"""
    return InlineKeyboardMarkup([
        [_btn("🎯 هدف شانسی", "patt:go", DANGER)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


def pv_result_kb() -> InlineKeyboardMarkup:
    """زیر نتیجه حمله پی‌وی، به‌جای هدف شانسی دکمه بازگشت به پنل حمله میاد"""
    return InlineKeyboardMarkup([
        [_btn("🔙 بازگشت", "patt:back", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


def pv_target_kb(target_id: int, reroll_cost: int, spy_cost: int) -> InlineKeyboardMarkup:
    """پیش‌نمایش هدف پی‌وی: حمله | جاسوسی پولی | هدف دیگه پولی | بازگشت"""
    spy_label = f"🕵 جاسوسی | 🪙 {money_tp(spy_cost)}"
    return InlineKeyboardMarkup([
        [_btn("⚔️ حمله", f"patt:hit:{target_id}", DANGER)],
        [_btn(spy_label, f"patt:spy:{target_id}", PRIMARY)],
        [_btn(f"🎯 هدف دیگه | 🪙 {money_tp(reroll_cost)}", f"patt:next:{target_id}", PRIMARY)],
        [_btn("🔙 بازگشت", "patt:back", PRIMARY)],
    ])


def pv_break_kb(target_id: int) -> InlineKeyboardMarkup:
    """قربانی سپر ۱۲ ساعته داره، یا با پول می‌شکنیش یا بی‌خیال میشی"""
    return InlineKeyboardMarkup([
        [_btn("💥 بشکن و حمله کن", f"patt:break:{target_id}", DANGER)],
        [_btn("🙅 بی‌خیال", "patt:back", PRIMARY)],
    ])


def pv_ownshield_kb(target_id: int, break_victim: bool = False) -> InlineKeyboardMarkup:
    """تاییدیه شکستن سپر محافظتی خودی قبل از حمله"""
    confirm = f"patt:shbr:{target_id}" if break_victim else f"patt:shcf:{target_id}"
    return InlineKeyboardMarkup([
        [_btn("✅ تایید، سپرمو بشکن و حمله کن", confirm, DANGER)],
        [_btn("❌ لغو، سپرم بمونه", "patt:back", PRIMARY)],
    ])


def heal_kb() -> InlineKeyboardMarkup:
    """کیبورد بخش درمان، هر آیتم با یه کلیک خریده و همون لحظه استفاده میشه"""
    rows: list[list[InlineKeyboardButton]] = []
    for key, it in config.HEAL_ITEMS.items():
        gain = "سلامت فول" if it["heal"] is None else f"سلامت +{fa_num(it['heal'])}"
        rows.append([_btn(
            f"{it['name']} | 🪙 {money_tp(it['price'])} | 🏥 {gain}",
            f"heal:buy:{key}", SUCCESS,
        )])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def energy_kb() -> InlineKeyboardMarkup:
    """کیبورد بخش انرژی‌زا ⚡، هر آیتم با یه کلیک خریده و همون لحظه خورده میشه"""
    pct = int(round((config.ENERGY_DRINKS["bomb"]["boost"] or 0) * 100))
    rows: list[list[InlineKeyboardButton]] = []
    for key, it in config.ENERGY_DRINKS.items():
        if it["energy"] is None:
            gain = f"⚡ فول + 🔥 {fa_num(pct)}% حمله"
        else:
            gain = f"⚡ انرژی +{fa_num(it['energy'])}"
        rows.append([_btn(
            f"{it['name']} | 🪙 {money_tp(it['price'])} | {gain}",
            f"en:buy:{key}", SUCCESS,
        )])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


# ───────── رتبه‌بندی ─────────

def rank_kb(tab: str) -> InlineKeyboardMarkup:
    """کیبورد لیدربرد، سه دکمه ثابت روزانه/هفتگی/کلی، هرکدوم مستقیم تب خودشو میارن
    کالبک هر دکمه تب فعلی رو هم داره تا زدن رو تب جاری هیچ واکنشی نده"""
    return InlineKeyboardMarkup([
        [_btn("📅 روزانه", f"rank:tab:{tab}:day", PRIMARY),
         _btn("🗓 هفتگی", f"rank:tab:{tab}:week", PRIMARY),
         _btn("🌍 کلی", f"rank:tab:{tab}:all", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


# ───────── کوئست‌های روزانه 📅 ─────────

def dquests_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("🔃 رفرش", "menu:dquests", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


# ───────── کارتل ─────────

def team_kb(is_owner: bool = False, is_manager: bool = False) -> InlineKeyboardMarkup:
    """کیبورد صفحه «کارتل من»، دکمه 👑 مدیریت کارتل فقط جلوی رهبر و مدیرانه"""
    rows: list[list[InlineKeyboardButton]] = [
        [_btn("📜 کوئست‌های امروز", "team:quests", PRIMARY),
         _btn("⛏ کنده‌کاری کارتلی", "team:mine", PRIMARY)],
        [_btn("🏗 ساختمان‌ها", "team:bld", PRIMARY),
         _btn("🏦 بانک کارتل", "team:bank", PRIMARY)],
        [_btn("🏆 لیدربرد", "team:top", PRIMARY)],
    ]
    rows.append([_btn("💬 چت کارتل", "tc:page", PRIMARY)])  # راند ۲۰
    if is_manager:
        rows.append([_btn("👑 مدیریت کارتل", "team:mng", PRIMARY)])
    if is_owner:
        rows.append([_btn("💥 انحلال کارتل", "team:disband", DANGER)])
    else:
        rows.append([_btn("🚪 ترک کارتل", "team:leave", PRIMARY)])
    # دکمه 🔃 رفرش عمداً حذف شده، کاربردی نداشت و فقط شلوغ می‌کرد
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def team_manage_kb() -> InlineKeyboardMarkup:
    """صفحه 👑 مدیریت کارتل، فقط رهبر و مدیران"""
    return InlineKeyboardMarkup([
        [_btn("📨 درخواست‌های عضویت", "team:req", PRIMARY)],
        [_btn("👢 اخراج عضو", "team:kick", DANGER)],
        [_btn("🔙 کارتل من", "menu:team", PRIMARY)],
    ])


def team_requests_kb(reqs: list[tuple[int, str]], tg_id: int = 0) -> InlineKeyboardMarkup:
    """لیست درخواست‌های عضویت، هر درخواست یه ردیف ✅ قبول و ❌ رد داره (قفل به آیدی بازکننده صفحه)"""
    rows: list[list[InlineKeyboardButton]] = []
    for rid, name in reqs[:10]:
        rows.append([
            _btn(f"✅ قبول {short_name(name)}", f"treq:ok:{rid}:{tg_id}", SUCCESS),
            _btn("❌ رد", f"treq:no:{rid}:{tg_id}", DANGER),
        ])
    rows.append([_btn("🔃 رفرش", "team:req", PRIMARY)])
    rows.append([_btn("🔙 مدیریت", "team:mng", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def kick_confirm_kb(member_id: int, tg_id: int = 0) -> InlineKeyboardMarkup:
    """تایید اخراج عضو کارتل (✅ اخراج / ❌ انصراف)، قفل به آیدی مدیرِ شروع‌کننده"""
    return InlineKeyboardMarkup([
        [_btn("✅ اخراج", f"tkick:{member_id}:{tg_id}", DANGER)],
        [_btn("❌ انصراف", f"tkcl:{tg_id}", PRIMARY)],
    ])


def team_join_request_kb(req_id: int) -> InlineKeyboardMarkup:
    """دکمه‌های دی‌ام درخواست عضویت به رهبر کارتل: قبول/رد همونجا (راند ۲۷)"""
    return InlineKeyboardMarkup([[
        _btn("✅ قبول", f"tjr:ok:{req_id}", SUCCESS),
        _btn("❌ رد", f"tjr:no:{req_id}", DANGER),
    ]])


def team_bld_kb(team, is_owner: bool, tg_id: int) -> InlineKeyboardMarkup:
    """کیبورد ساختمان‌های کارتل، ارتقا فقط برای رهبره"""
    rows: list[list[InlineKeyboardButton]] = []
    if is_owner:
        can_atk = team.atk_bld < config.TEAM_BUILDING_MAX_LEVEL
        can_def = team.def_bld < config.TEAM_BUILDING_MAX_LEVEL
        row: list[InlineKeyboardButton] = []
        if can_atk:
            row.append(_btn("⚔️ ارتقا حمله", f"tbup:atk:{tg_id}", SUCCESS))
        else:
            row.append(_btn("⚔️ حمله 👑 لول مکس", "noop:maxbld", None))
        if can_def:
            row.append(_btn("🛡 ارتقا دفاع", f"tbup:def:{tg_id}", SUCCESS))
        else:
            row.append(_btn("🛡 دفاع 👑 لول مکس", "noop:maxbld", None))
        if row:
            rows.append(row)
    rows.append([_btn("🔃 رفرش", "team:bld", PRIMARY)])
    rows.append([_btn("🔙 کارتل من", "menu:team", PRIMARY)])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def team_bld_confirm_kb(kind: str, tg_id: int) -> InlineKeyboardMarkup:
    """تایید ارتقای ساختمان، فقط خود رهبر می‌تونه بزنه"""
    return InlineKeyboardMarkup([[
        _btn("✅ تایید", f"tbcf:{kind}:{tg_id}", SUCCESS),
        _btn("❌ لغو", f"txcl:{tg_id}", DANGER),
    ]])


# ───────── بانک شخصی ─────────

def bank_amount_kb(action: str) -> InlineKeyboardMarkup:
    """دکمه‌های آماده سوال واریز/برداشت بانک، واریز فقط کل موجودی داره (تا سقف ظرفیت)"""
    if action == "dep":
        rows = [[_btn("💰 کل موجودی", "bankq:dep:all", SUCCESS)]]
    else:
        rows = [[_btn("💸 نصف موجودی", "bankq:wd:half", PRIMARY),
                 _btn("💰 کل موجودی", "bankq:wd:all", SUCCESS)]]
    return InlineKeyboardMarkup(rows)


def bank_kb(user: User) -> InlineKeyboardMarkup:
    """کیبورد بانک، واریز و برداشت مبلغ رو با پیام بعدی می‌پرسن"""
    from services.bank import bank_min_level, bank_upgrade_price

    rows: list[list[InlineKeyboardButton]] = [
        [_btn("💰 واریز", "bank:dep", SUCCESS),
         _btn("💸 برداشت", "bank:wd", DANGER)],
        [_btn("💳 انتقال موجودی", "bank:tf", PRIMARY)],
    ]
    if user.bank_level < config.BANK_MAX_LEVEL:
        price = bank_upgrade_price(user.bank_level)
        req = bank_min_level(user.bank_level + 1)
        if user.level < req:
            rows.append([_btn(
                f"🔒 ارتقای بانک | لول {fa_num(user.bank_level + 1)} | سطح {fa_num(req)} می‌خواد",
                "noop:banklock", DANGER,
            )])
        else:
            rows.append([_btn(
                f"⬆️ ارتقای بانک | لول {fa_num(user.bank_level + 1)} | {money_tp(price)}",
                "bank:up", PRIMARY,
            )])
    else:
        rows.append([_btn("🏦 بانک 👑 لول مکس", "noop:maxbank")])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def team_no_kb() -> InlineKeyboardMarkup:
    """کیبورد وقتی کارتل نداری"""
    return InlineKeyboardMarkup([
        [_btn("🏆 برترین کارتل‌ها", "team:top", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


def team_confirm_kb(action: str, tg_id: int) -> InlineKeyboardMarkup:
    """تایید اکشن کارتلی (ترک/انحلال)، فقط صاحب دستور می‌تونه بزنه"""
    return InlineKeyboardMarkup([[
        _btn("✅ تایید", f"tmcf:{action}:{tg_id}", SUCCESS),
        _btn("❌ لغو", f"txcl:{tg_id}", DANGER),
    ]])


# ───────── صفحات فرعی کارتل، برگشت به کارتل من + منوی اصلی ─────────

def team_back_kb(home: bool = True) -> InlineKeyboardMarkup:
    """🔙 کارتل من + 🏠 منوی اصلی (تو گروه home با strip_home برمی‌ره)"""
    rows = [[_btn("🔙 کارتل من", "menu:team", PRIMARY)]]
    if home:
        rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def team_top_kb(tab: str) -> InlineKeyboardMarkup:
    """کیبورد لیدربرد کارتل‌ها، سه دکمه ثابت روزانه/هفتگی/کلی، هرکدوم مستقیم تب خودشو میارن
    کالبک هر دکمه تب فعلی رو هم داره تا زدن رو تب جاری هیچ واکنشی نده"""
    return InlineKeyboardMarkup([
        [_btn("☀️ روزانه", f"ttop:tab:{tab}:day", PRIMARY),
         _btn("📅 هفتگی", f"ttop:tab:{tab}:week", PRIMARY),
         _btn("🌍 کلی", f"ttop:tab:{tab}:all", PRIMARY)],
        [_btn("🔙 کارتل من", "menu:team", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


def team_mine_kb() -> InlineKeyboardMarkup:
    """دکمه‌های کنده‌کاری کارتلی، جوین/رفرش + برگشت"""
    return InlineKeyboardMarkup([
        [_btn("⛏ میام استخراج", "team:mine", SUCCESS)],
        [_btn("🔙 کارتل من", "menu:team", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


def team_bank_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("💰 واریز به بانک کارتل | آموزش: «کارتل واریز 1200»", "noop:depinfo", PRIMARY)],
        [_btn("🔙 کارتل من", "menu:team", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


# ───────── انبار 🏚 ─────────

def mine_kb() -> InlineKeyboardMarkup:
    """دکمه‌های کنده‌کاری، وضعیت ابزار دیگه صفحه جدا نداره و همون صفحه اصلی نشون داده میشه"""
    return InlineKeyboardMarkup([
        [_btn("⛏ بکَن", "mine:roll", SUCCESS)],
        [_btn("🪓 ارتقای تبر", "mine:upg:axe", PRIMARY),
         _btn("⛏️ ارتقای کلنگ", "mine:upg:pick", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


def mine_up_confirm_kb(tool_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _btn("✅ تایید", f"cf:mine:upg:{tool_key}", SUCCESS),
        _btn("❌ لغو", f"cl:mine:upg:{tool_key}", DANGER),
    ]])


def company_kb(user: User) -> InlineKeyboardMarkup:
    """ساخت/ارتقای چوب‌بری و کارخانه آهن"""
    from services import company as company_svc
    rows: list[list[InlineKeyboardButton]] = []
    for key, cfg in config.FACTORIES.items():
        lv = company_svc.factory_level(user, key)
        if lv <= 0:
            rows.append([_btn(f"🔨ساخت {cfg['name']} {cfg['emoji']}", f"comp:build:{key}", SUCCESS)])
        else:
            stock = company_svc.factory_stock(user, key)
            if stock > 0:
                rows.append([_btn(f"📥 برداشت {cfg['emoji']} ({fa_num(stock)})", f"comp:col:{key}", PRIMARY)])
            if lv >= config.FACTORY_MAX_LEVEL:
                rows.append([_btn(f"👑 {cfg['emoji']} {cfg['name']} | لول مکس", "noop:maxfac")])
            else:
                rows.append([_btn(f"⬆️ ارتقای {cfg['name']} {cfg['emoji']}", f"comp:upg:{key}", SUCCESS)])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def company_confirm_kb(action: str, key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _btn("✅ تایید", f"cf:comp:{action}:{key}", SUCCESS),
        _btn("❌ لغو", f"cl:comp:{action}:{key}", DANGER),
    ]])


def shelter_kb(user: User, caravan_on: bool = False) -> InlineKeyboardMarkup:
    """کیبورد انبار با دسته‌بندی‌ها: محصولات | منابع | آیتم‌ها + کاروان قاچاق"""
    from services.world import shelter_price, shelter_upgrade_min_level
    rows: list[list[InlineKeyboardButton]] = [
        [_btn("🌾 محصولات", "shelter:cat:prod", PRIMARY),
         _btn("🧱 منابع", "shelter:cat:res", PRIMARY)],
        [_btn("📦 آیتم‌ها", "shelter:cat:item", PRIMARY)],
        [_btn("📦 ارسال محموله", "sm:page", PRIMARY)],
        [_btn("🚚 کاروان قاچاق" + (" 🟢 اینجاست" if caravan_on else ""), "smc:page", PRIMARY)],
    ]
    if user.shelter_level < config.SHELTER_MAX_LEVEL:
        price = shelter_price(user.shelter_level + 1)
        req = shelter_upgrade_min_level(user.shelter_level + 1)
        if user.level < req:
            rows.append([_btn(
                f"🔒 ارتقا | لول {fa_num(user.shelter_level + 1)} | سطح {fa_num(req)} می‌خواد",
                "noop:lock", DANGER,
            )])
        else:
            rows.append([_btn(
                f"⬆️ ارتقا | لول {fa_num(user.shelter_level + 1)} | {money_tp(price)}",
                "shelter:up", PRIMARY,
            )])
    else:
        rows.append([_btn("🏚 انبار 👑 لول مکس", "noop:maxshelter")])
    # فروش منابع رفت توی بخش 🧱 منابع (درخواست کارفرما)، صفحه اول خلوت شد
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def shelter_back_kb() -> InlineKeyboardMarkup:
    """ته صفحه‌های دسته‌بندی انبار"""
    return InlineKeyboardMarkup([
        [_btn("🎒 انبار", "menu:shelter", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


def shelter_res_kb() -> InlineKeyboardMarkup:
    """صفحه 🧱 منابع انبار، فروش منابع + برگشت"""
    return InlineKeyboardMarkup([
        [_btn("💰 فروش منابع", "shelter:sell", PRIMARY)],
        [_btn("🎒 انبار", "menu:shelter", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


def products_kb(products: dict) -> InlineKeyboardMarkup:
    """صفحه 📦 ارسال محموله: برای هر محصول موجود یه دکمه ارسال"""
    rows: list[list[InlineKeyboardButton]] = []
    for key, sd in config.SEEDS.items():
        row = products.get(key)
        if not row or row.qty <= 0:
            continue
        rows.append([_btn(
            f"📦 ارسال {sd.get('emoji', '🌱')} {sd['name']} ×{fa_num(row.qty)}",
            f"sm:pick:{key}", PRIMARY,
        )])
    rows.append([_btn("🎒 انبار", "menu:shelter", PRIMARY)])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def ship_qty_kb(crop: str, have: int) -> InlineKeyboardMarkup:
    """انتخاب مقدار ارسال محموله: دکمه‌های ۱۰/۲۵/۵۰ تا جایی که موجودی می‌رسه + همه"""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for n in config.SHIPMENT_QTY_CHOICES:
        if have >= n:
            row.append(_btn(fa_num(n), f"sm:qty:{crop}:{n}", PRIMARY))
    row.append(_btn("همه", f"sm:qty:{crop}:all", PRIMARY))
    rows.append(row)
    rows.append([_btn("✏️ تعداد دلخواه", f"sm:ask:{crop}", PRIMARY)])
    rows.append([_btn("🔙 ارسال محموله", "sm:page", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def ship_confirm_kb(crop: str, qty: int) -> InlineKeyboardMarkup:
    """تایید نهایی ارسال محموله"""
    return InlineKeyboardMarkup([
        [_btn("✅ ارسال محموله", f"sm:go:{crop}:{qty}", SUCCESS)],
        [_btn("❌ لغو", "sm:page", DANGER)],
    ])


def smcaravan_kb(have: int) -> InlineKeyboardMarkup:
    """دکمه‌های مقدار فروش به کاروان قاچاق"""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for n in config.SHIPMENT_QTY_CHOICES:
        if have >= n:
            row.append(_btn(fa_num(n), f"smc:qty:{n}", PRIMARY))
    if have > 0:
        row.append(_btn("همه", "smc:qty:all", PRIMARY))
    if row:
        rows.append(row)
    if have > 0:
        rows.append([_btn("✏️ تعداد دلخواه", "smc:ask", PRIMARY)])
    rows.append([_btn("🎒 انبار", "menu:shelter", PRIMARY)])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def smcaravan_confirm_kb(qty: int) -> InlineKeyboardMarkup:
    """تایید نهایی فروش به کاروان قاچاق"""
    return InlineKeyboardMarkup([
        [_btn("✅ فروش", f"smc:go:{qty}", SUCCESS)],
        [_btn("❌ لغو", "smc:page", DANGER)],
    ])


def sell_menu_kb() -> InlineKeyboardMarkup:
    """کیبورد ساده بخش فروش منابع، کار اصلی با دستور متنی انجام میشه"""
    return InlineKeyboardMarkup([
        [_btn("🏚 انبار", "menu:shelter", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


def sellres_confirm_kb(res: str, amount: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _btn("✅ تایید فروش", f"cf:sellres:{res}:{amount}", SUCCESS),
        _btn("❌ لغو", "cl:sellres", DANGER),
    ]])


def buyres_confirm_kb(res: str, qty: int) -> InlineKeyboardMarkup:
    """فاکتور خرید دونه‌ای چوب/آهن از شاپ، تایید یا لغو"""
    return InlineKeyboardMarkup([[
        _btn("✅ تایید خرید", f"cf:shopres:{res}:{qty}", SUCCESS),
        _btn("❌ لغو", "cl:shopres", DANGER),
    ]])


# ───────── بازی مین 💣 (راند ۲۸، جایگزین قمار تاسی حذف‌شده) ─────────

def mines_bets_kb() -> InlineKeyboardMarkup:
    """انتخاب میز شرط بازی مین"""
    rows = []
    for bet in config.MINES_BETS:
        rows.append([_btn(f"💣 میز {money_tp(bet)}", f"mn:b:{bet}", SUCCESS)])
    rows.append([_btn("🏠 منوی اصلی", "menu:home", PRIMARY)])
    return InlineKeyboardMarkup(rows)


def mines_board_kb(revealed: set, safe: int, payout: int) -> InlineKeyboardMarkup:
    """میز ۳×3 دست جاری: روشن‌شده‌ها ✅ بی‌اثرن؛ ردیف آخر برداشت (بعد یه امن) یا لغو"""
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            i = r * 3 + c
            if i in revealed:
                row.append(_btn("✅", "mn:noop", None))
            else:
                row.append(_btn("⬜", f"mn:p:{i}", PRIMARY))
        rows.append(row)
    if safe >= 1:
        rows.append([_btn(f"💰 برداشت {money_tp(payout)}", "mn:c", SUCCESS)])
    else:
        rows.append([_btn("❌ لغو و برگشت شرط", "mn:x", DANGER)])
    return InlineKeyboardMarkup(rows)


def mines_result_kb(revealed: set, bomb: int, bet: int) -> InlineKeyboardMarkup:
    """میز کامل‌نمای نتیجه: مین 💣، روشن‌شده‌ها ✅، بقیه ❌ + دکمه تکرار و برگشت"""
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            i = r * 3 + c
            if i == bomb:
                row.append(_btn("💣", "mn:noop", DANGER))
            elif i in revealed:
                row.append(_btn("✅", "mn:noop", None))
            else:
                row.append(_btn("❌", "mn:noop", None))
        rows.append(row)
    rows.append([
        _btn(f"🔁 همین میز ({money_tp(bet)})", f"mn:b:{bet}", SUCCESS),
        _btn("💣 قمارخانه", "mn:h", PRIMARY),
    ])
    return InlineKeyboardMarkup(rows)


# ───────── کاروان 🚛 ─────────

def caravan_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("⚔️ حمله به کاروان", "cv:hit", DANGER)]])

# ───────── باس محله 👹 (راند ۲۳) ─────────

def boss_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("⚔️ ضربه به باس", "bsh:hit", DANGER)]])


def admin_bosses_kb(rows) -> InlineKeyboardMarkup:
    """پنل ادمین: لیست باس‌ها با تیک و ضربدر عکس (rows = [(key, emoji, name, has_img)])"""
    out = []
    for key, emoji, name, has_img in rows:
        mark = "✅" if has_img else "❌"
        out.append([_btn(f"{mark} {emoji} {name}", f"admb:v:{key}", PRIMARY)])
    out.append([_btn("⬅️ برگشت به پنل ادمین", "adm:panel:0", PRIMARY)])
    return InlineKeyboardMarkup(out)


def admin_boss_view_kb(key: str) -> InlineKeyboardMarkup:
    """کارت یه باس تو پنل: عوض کردن عکس + اسپان همین چت"""
    return InlineKeyboardMarkup([
        [_btn("🖼 تغییر عکس", f"admb:p:{key}", SUCCESS),
         _btn("🚨 اسپان همین‌جا", f"admb:s:{key}", DANGER)],
        [_btn("⬅️ لیست باس‌ها", "admb:l:0", PRIMARY)],
    ])


# ───────── مارکت 🛒 (راند ۲۳) ─────────

def market_home_kb(n_open: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn(f"🛒 خرید از مارکت ({n_open} آگهی)", "mk:b:0:a", SUCCESS)],
        [_btn("🏷 فروش تو مارکت", "mk:s:0:a", PRIMARY)],
        [_btn("📋 آگهی‌های من", "mk:my:0:a", PRIMARY)],
        [_btn("🏠 منوی اصلی", "menu:home", PRIMARY)],
    ])


def market_my_kb(rows) -> InlineKeyboardMarkup:
    """لیست آگهی‌های خود کاربر، هر آگهی یه دکمه برای کارت مدیریتش"""
    out = [[_btn(r["label"], f"mk:myv:{r['id']}:a", PRIMARY)] for r in rows]
    out.append([_btn("🛒 برگشت به مارکت", "mk:h:0:a", PRIMARY)])
    return InlineKeyboardMarkup(out)


def market_my_item_kb(listing_id: int) -> InlineKeyboardMarkup:
    """کارت آگهی خودم: لغو آگهی (استرداد جنس) یا برگشت به لیست آگهی‌های من"""
    return InlineKeyboardMarkup([
        [_btn("❌ لغو آگهی و برگشت جنس", f"mk:myx:{listing_id}:a", DANGER)],
        [_btn("🔙 آگهی‌های من", "mk:my:0:a", PRIMARY)],
        [_btn("🛒 مارکت", "mk:h:0:a", PRIMARY)],
    ])


def market_buy_kb(rows, page: int, pages: int, desc: bool, item: str | None) -> InlineKeyboardMarkup:
    """لیست خرید: هر آگهی یه ردیف، پایینش مرتب‌سازی + سرچ + قبلی/بعدی + شماره صفحه"""
    out = []
    for r in rows:
        out.append([_btn(r["label"], f"mk:v:{r['id']}:a", PRIMARY)])
    sd = "e" if desc else "a"
    flt = item or "x"
    out.append([
        _btn("💰 گرون‌تر به ارزون‌تر" if not desc else "💰 ارزون‌تر به گرون‌تر",
             f"mk:b:0:{'a' if desc else 'e'}:{flt}", PRIMARY),
        _btn("🔍 سرچ آیتم", "mk:f:0:a", PRIMARY),
    ])
    nav = []
    if page > 0:
        nav.append(_btn("◀️ قبلی", f"mk:b:{page - 1}:{sd}:{flt}", PRIMARY))
    nav.append(_btn(f"📄 صفحه {page + 1}/{pages}", "mk:noop:0:a", PRIMARY))
    if page < pages - 1:
        nav.append(_btn("بعدی ▶️", f"mk:b:{page + 1}:{sd}:{flt}", PRIMARY))
    out.append(nav)
    out.append([_btn("🛒 برگشت به مارکت", "mk:h:0:a", PRIMARY)])
    return InlineKeyboardMarkup(out)


def market_filter_kb(desc: bool) -> InlineKeyboardMarkup:
    """انتخاب آیتم برای سرچ تو آگهی‌ها"""
    sd = "e" if desc else "a"
    return InlineKeyboardMarkup([
        [_btn("🧩 قطعه افسانه‌ای", f"mk:b:0:{sd}:part", PRIMARY)],
        [_btn("🪵 چوب", f"mk:b:0:{sd}:wood", PRIMARY),
         _btn("⛏️ آهن", f"mk:b:0:{sd}:iron", PRIMARY)],
        [_btn("📋 همه آگهی‌ها", f"mk:b:0:{sd}:x", SUCCESS)],
        [_btn("🛒 برگشت به مارکت", "mk:h:0:a", PRIMARY)],
    ])


def market_listing_kb(listing_id: int) -> InlineKeyboardMarkup:
    """کارت یه آگهی، تایید خرید"""
    return InlineKeyboardMarkup([
        [_btn("✅ تایید و خرید", f"mk:buy:{listing_id}:a", SUCCESS)],
        [_btn("❌ ولش کن", "mk:b:0:a", PRIMARY)],
    ])


def market_sell_kb() -> InlineKeyboardMarkup:
    """انتخاب جنس برای فروش"""
    return InlineKeyboardMarkup([
        [_btn("🧩 قطعه افسانه‌ای", "mk:si:part:a", PRIMARY)],
        [_btn("🪵 چوب", "mk:si:wood:a", PRIMARY),
         _btn("⛏️ آهن", "mk:si:iron:a", PRIMARY)],
        [_btn("🛒 برگشت به مارکت", "mk:h:0:a", PRIMARY)],
    ])


def market_sell_confirm_kb(item: str, qty: int, price: int) -> InlineKeyboardMarkup:
    """فاکتور نهایی فروش قبل از ثبت آگهی"""
    return InlineKeyboardMarkup([
        [_btn("✅ ثبت آگهی", f"mk:cfs:{item}:{qty}:{price}", SUCCESS)],
        [_btn("❌ لغو", "mk:cx:0:a", PRIMARY)],
    ])


# ───────── پیام همگانی ادمین 📣 ─────────

def broadcast_scope_kb(chat_id: int, msg_id: int) -> InlineKeyboardMarkup:
    """انتخاب دامنه پیام همگانی"""
    return InlineKeyboardMarkup([
        [_btn("👥 فقط گروه‌ها", f"bcs:g:{chat_id}:{msg_id}", PRIMARY)],
        [_btn("👤 فقط پی‌وی‌ها", f"bcs:p:{chat_id}:{msg_id}", PRIMARY)],
        [_btn("📣 همه", f"bcs:a:{chat_id}:{msg_id}", SUCCESS)],
        [_btn("❌ لغو", "bcc", DANGER)],
    ])


def broadcast_mode_kb(scope: str, chat_id: str, msg_id: str) -> InlineKeyboardMarkup:
    """انتخاب مد ارسال پیام همگانی، فوروارد با تگ یا ارسال از طرف خود ربات"""
    return InlineKeyboardMarkup([
        [_btn("📤 فوروارد", f"bcm:f:{scope}:{chat_id}:{msg_id}", PRIMARY)],
        [_btn("✉️ ارسال متن", f"bcm:t:{scope}:{chat_id}:{msg_id}", PRIMARY)],
        [_btn("❌ لغو", "bcc", DANGER)],
    ])


def team_chat_kb() -> InlineKeyboardMarkup:
    """راند ۲۰: ارسال پیام به چت کارتل + بروزرسانی + برگشت"""
    return InlineKeyboardMarkup([
        [_btn("✉️ ارسال پیام", "tc:send", SUCCESS)],
        [_btn("🔄 بروزرسانی", "tc:ref", PRIMARY),
         _btn("🔙 کارتل من", "tc:back", PRIMARY)],
    ])
