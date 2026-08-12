"""
سیم‌کشی هندلرها به اپلیکیشن، دستورهای متنی هم PV هم گروه جواب میدن

دستورهای متنی با پیشوند «تریاکی | تریاک | تی » میان، مثلا:
«تریاکی زمین» «تریاک شاپ» «تی حمله» «تریاکی کارتل پروفایل» «تریاکی کارتل بانک»
«کنده کاری» و «حمله» و دستورهای کارتل و شاپ و فروشگاه و خرید و کاشت و برداشت و لیدربرد و کوئست و هواشناسی بدون پیشوند هم کار می‌کنن

قفل مالکیت دکمه‌ها: پیام دکمه‌داری که از دستور یه نفر تو گروه ساخته شده
فقط خودش می‌تونه بزنه، بقیه هیچ واکنشی نمی‌بینن (handlers/common.owner_guard)
"""

import re

from telegram.ext import Application, CallbackQueryHandler, ChatMemberHandler, CommandHandler, MessageHandler, filters

import config

from handlers import admin, attack, backup, bank, battle, boss, common, company, dogs, dquests, energy, farm, gate, gear, market, mine, mines, pending, power, profile, rank, seen, shop, skills, smuggle, snitch, start, team, textcmd, world  # راند ۳۱: raid حذف شد

ZWNJ = "‌"
S = rf"[\s{ZWNJ}]"  # فاصله یا نیم‌فاصله
T = rf"^(?:تریاکی|تریاک|تی){S}+"   # پیشوند دستورها، هر سه شکل قبوله
TP = rf"^(?:(?:تریاکی|تریاک|تی){S}+)?"  # پیشوند اختیاری، برای دستورهای کارتل
TK = "(?:کارتل|تیم)"  # راند ۲۲: اسم رسمی کارتله، دستورهای قدیمی با «تیم» هم زنده‌ان (الیاس)
TKI = "(?:کارتلی?|تیمی?)"  # صفت با ی اختیاری: «کوئست کارتل» و «کوئست تیمی» هر دو

# ── دستورهای متنی فارسی (PV و گروه) ──
# ترتیب مهمه: الگوهای اختصاصی بالاترن (مثلا «تریاکی کارتل بانک» قبل از «تریاکی کارتل [اسم]»)
# فرمت: (اسم، الگو، هندلر)، تست‌ها روی همین جدول پترن‌ها رو چک می‌کنن
TEXT_HANDLERS: list[tuple[str, str, object]] = [
    ("team_mine", rf"{TP}کنده{S}*کاری{S}*" + TKI + rf"!?$|{TP}استخراج{S}*" + TKI + rf"!?$", team.team_mine_text),
    ("mine_upg", rf"{TP}آپگرید{S}+کنده{S}*کاری!?$|{TP}کنده{S}*کاری{S}+آپگرید!?$|{TP}ابزار{S}*کنده{S}*کاری!?$", mine.mine_tools_cb),  # ارتقای ابزار، صفحه وضعیت ابزار
    ("mine", rf"^کنده[\s‌]*کاری!?$|{T}کنده{S}*کاری!?$", mine.mine_cmd),  # با و بدون پیشوند
    ("shop", rf"{TP}شاپ!?$|{TP}فروشگاه!?$", textcmd.shop_text),  # با و بدون پیشوند
    ("profile", rf"{T}پروفایل!?$", textcmd.profile_text),
    # نبرد HP گروهی، همه دستورهای جنگ با و بدون پیشوند (فقط تو گروه اجرا میشه)
    ("attack", rf"{TP}(?:حمله|شلیک|بنگ(?:{S}+بنگ)?|پیو(?:{S}+پیو)?)(?:{S}+\S+)?!?$", battle.attack_cmd),
    ("snitch", rf"{TP}لو{S}+دادن(?:{S}+\S+)?(?:!|؟)?$", snitch.snitch_cmd),
    ("bribe", rf"{TP}رشوه{S}+دادن!?$", snitch.bribe_text_cmd),  # راند ۲۸: آزادی زندانی با پرداخت رشوه
    ("reload", rf"{TP}ریلود!?$", gear.reload_text_cmd),  # راند ۲۹: کارت تایید ریلود مهمات
    ("market", rf"{TP}مارکت!?$", market.market_cmd),  # بازار بازیکن‌ها (راند ۲۳، جدا از بازار سیاه)
    ("giftpart", rf"{TP}هدیه{S}+قطعه{S}+افسانه‌ای(?:{S}+\d+)?(?:{S}+\S+)?(?:!|؟)?$", market.gift_cmd),
    ("heal", rf"{T}درمان!?$", battle.heal_cmd),
    ("energy", rf"{T}انرژی(?:{S}*زا)?!?$", energy.energy_cmd),
    ("harvest", rf"{TP}برداشت{S}*محصول!?$|{TP}برداشت!?$", textcmd.harvest_text),
    ("buy_dog", rf"{TP}خرید{S}+سگ{S}+(.+)$", textcmd.buy_dog_text),
    ("buy", rf"{TP}خرید{S}+(.+)$", textcmd.buy_text),
    ("plant", rf"{TP}کاشت{S}+(.+)$", textcmd.plant_text),
    ("mydogs", rf"{T}سگ{S}*های{S}*من!?$|{T}سگ{S}*هام!?$|{T}سگ{S}*ها!?$", textcmd.dogs_text),
    ("farm", rf"{TP}مزرعه!?$|{TP}زمین{S}*های{S}*من!?$|{TP}زمین{S}*هام!?$|{TP}زمین{S}*ها!?$|{TP}زمین!?$", textcmd.farm_text),
    ("rank", rf"{TP}رتبه!?$|{TP}رتبه{S}*بندی!?$|{TP}لیدربرد!?$|{TP}لیدر{S}*برد!?$", rank.rank_cb),
    ("dogstats", rf"{TP}[اآ]مار{S}+(.+)$", dogs.dog_stats_text),  # «آمار لوله‌کش» و «امار لوله‌کش»، با و بدون پیشوند
    ("stats", rf"{TP}[اآ]مار!?$", textcmd.profile_text),  # «آمار» و «امار» تنها، پروفایل باز میشه که بلوک آمار داره
    ("skills_txt", rf"{TP}مهارت(?:{S}*ها)?!?$", skills.skills_cb),  # «مهارت» منوی مهارت رو باز می‌کنه
    ("dquests_txt", rf"{TP}(?:ماموریت|مأموریت)(?:{S}*های?)?(?:{S}+روزانه)?!?$", dquests.daily_quests_cb),  # «ماموریت» و «مأموریت» بخش مأموریت‌های روزانه
    ("daily_alias", rf"{T}دیلی!?$", dquests.daily_quests_cb),  # راند ۳۵ (درخواست کارفرما): «تریاکی دیلی» صفحه ماموریت‌های روزانه
    ("plot_buy", rf"{T}ساخت{S}+زمین!?$|{T}خرید{S}+زمین!?$", farm.buy_plot_text),  # راند ۳۵: «تریاکی ساخت زمین» کارت تایید خرید
    # ── کارتل ──
    ("team_bld", rf"{TP}" + TK + rf"{S}+ساختمان(?:{S}*ها)?!?$|{TP}" + TK + rf"{S}+ساخت!?$", team.buildings_text),
    ("team_profile", rf"{TP}" + TK + rf"{S}+پروفایل!?$", team.team_profile_text),
    ("roster", rf"{TP}" + TK + rf"{S}+عضویت!?$", team.roster_text),
    ("team_top", rf"{TP}" + TK + rf"{S}+لیدربرد!?$|{TP}" + TK + rf"{S}+لیدر{S}*برد!?$", team.top_teams_text),
    ("team_quests", rf"{TP}" + TK + rf"{S}+(?:کوئست|چالش)!?$|{TP}کوئست{S}*" + TKI + rf"?!?$", team.quests_text),
    ("team_bank", rf"{TP}" + TK + rf"{S}+بانک!?$", team.team_bank_text),
    ("team_dep", rf"{TP}" + TK + rf"{S}+واریز(?:{S}+(.+))?!?$", team.team_deposit_text),
    ("team_up", rf"{TP}" + TK + rf"{S}+ارتقا{S}+(?:حمله|دفاع)!?$", team.team_upgrade_text),
    ("team_create", rf"{TP}ساخت{S}+" + TK + rf"!?$", team.create_team_text),
    ("team_join", rf"{TP}(?:جوین{S}+" + TK + rf"|{TK}{S}+جوین){S}+(.+)$", team.join_team_text),  # راند ۲۷: «کارتل جوین X» هم جوابه
    ("team_leave", rf"{TP}ترک{S}+" + TK + rf"!?$", team.leave_confirm),
    ("team_disband", rf"{TP}انحلال{S}+" + TK + rf"!?$", team.disband_confirm),
    ("team_bio", rf"{TP}" + TK + rf"{S}+ست{S}+بیو{S}+(.+)$", team.set_bio_text),
    ("team_hide", rf"{TP}" + TK + rf"{S}+مخفی(?:{S}+(.+))?!?$", team.hide_team_text),
    ("team_rename", rf"{TP}" + TK + rf"{S}+تغییر{S}+نام{S}+(.+)$", team.rename_text),
    ("team_req", rf"{TP}" + TK + rf"{S}+درخواست{S}+(\S+)(?:{S}+(قبول|رد|اکسپت|ریجکت))?!?$", team.team_request_text),
    ("team_kick", rf"{TP}" + TK + rf"{S}+کیک{S}+(.+)$", team.team_kick_text),
    ("team_admin_add", rf"{TP}" + TK + rf"{S}+اد{S}+ادمین{S}+(.+)$", team.team_admin_add_text),
    ("team_admin_del", rf"{TP}" + TK + rf"{S}+حذف{S}+ادمین{S}+(.+)$", team.team_admin_del_text),
    ("team_admin", rf"{TP}" + TK + rf"{S}+ادمین{S}+(.+)$", team.team_admin_text),
    ("quests", rf"{TP}کوئست!?$|{TP}استعلام{S}*کوئست!?$", dquests.daily_quests_cb),  # «کوئست» تنها فقط کوئست روزانه بازیکن
    ("team", rf"{TP}" + TK + rf"(?:{S}+(.+))?!?$", team.team_text),
    ("backup_menu", rf"{T}بک{S}*[اآ]پ!?$", backup.backup_menu_text),  # «تی بکاپ» منوی بک‌آپ، با الف ساده و مده‌دار
    ("backup_copy", rf"{T}کپی!?$", backup.backup_copy_text),  # «تی کپی» ساخت فوری بک‌آپ
    ("backup_cancel", rf"{T}لغو{S}*بک{S}*آپ!?$", backup.cancel_upload_text),
    # ── سیستم‌های جهان ──
    ("search", rf"{T}جستجو!?$|{T}جست{S}*و{S}*جو!?$", world.search_cmd),
    ("weather", rf"{TP}وضعیت{S}+آب{S}+و{S}+هوا!?$|{TP}آب{S}*و{S}*هوا!?$|{TP}وضعیت{S}+هواشناسی!?$|{TP}هواشناسی!?$|{TP}وضعیت{S}+هوا!?$", world.weather_cmd),
    ("market", rf"{TP}وضعیت{S}+بازار!?$|{TP}بازار{S}*سیاه!?$|{TP}بازار!?$", world.market_cmd),  # با و بدون پیشوند
    ("shelter", rf"{T}پناهگاه!?$|{T}مخفیگاه!?$|{TP}انبار!?$|{TP}انبار{S}+و{S}+پناهگاه!?$", world.shelter_cmd),  # «انبار» بدون پیشوند هم جواب میده
    ("company", rf"{TP}شرکت!?$|{TP}کارخانه!?$", company.company_cb),
    ("dogrename", rf"{T}اسم{S}+سگ{S}+(.+)$", dogs.dog_rename_text),
    ("casino_hub", rf"{T}قمارخانه!?$|{T}قمار!?$", mines.mines_hub_cmd),  # راند ۲۸: بازی مین، تاسی حذف شد
    ("mines", rf"{T}مین!?(?:{S}+[\d,٬]+)?$", mines.mines_text_cmd),  # راند ۲۸ دستور مستقیم با شرط
    # ── بانک شخصی، «بانک» بدون پیشوند هم باز میشه + دستورهای «بانک واریز/برداشت» و «انتقال n کد» ──
    ("banktrf", rf"{TP}انتقال{S}+(.+)$", bank.transfer_text),
    ("bankdep2", rf"{TP}بانک{S}+واریز{S}+(.+)$", bank.deposit_text),
    ("bankwd2", rf"{TP}بانک{S}+برداشت{S}+(.+)$", bank.withdraw_text),
    ("bankhome", rf"{TP}بانک!?$", bank.bank_cb),
    ("bankdep", rf"{T}واریز{S}+(.+)$", bank.deposit_text),
    ("bankwd", rf"{T}برداشت{S}+([0-9۰-۹٠-٩,٬]+)$", bank.withdraw_text),
    ("help", rf"{T}راهنما!?$|{T}آموزشات!?$", start.help_cmd),
    ("tracklog_stop", rf"{TP}توقف{S}+لاگ{S}+(.+)$", admin.tracklog_stop_text),  # توقف ردیابی بازیکن، فقط ادمین
    ("tracklog", rf"{TP}لاگ{S}+(.+)$", admin.tracklog_start_text),  # شروع ردیابی بازیکن، فقط ادمین
    ("caravan_spawn", rf"{T}اسپان{S}+کاروان!?$", world.caravan_spawn_cmd),  # فقط ادمین
    ("smuggler_spawn", rf"{T}اسپان{S}+کاروان{S}+(.+?)!?$", smuggle.admin_spawn_text),  # کاروان قاچاق، فقط ادمین
]


# ── راند ۳۵ (درخواست کارفرما): ادمین ربات بدون پیشوند «تریاکی» هم می‌تونه دستور بده ──
_QUICK_RX: list | None = None


def _quick_pairs() -> list:
    """پترن‌های کامپایل‌شده TEXT_HANDLERS، یه‌بار ساخته و کش میشن"""
    global _QUICK_RX
    if _QUICK_RX is None:
        _QUICK_RX = [(re.compile(p), f) for _n, p, f in TEXT_HANDLERS]
    return _QUICK_RX


async def admin_quick(update, context) -> None:
    """
    ادمین ربات هر دستور متنی رو لازم نیس با «تریاکی» شروع کنه:
    «قمار» «دیلی» «انرژی» «لو دادن @x» و هرچی تو TEXT_HANDLERS هس
    برای کاربر عادی هیچ کاری نمی‌کنه؛ block=False ثبت میشه که جریان عادی خراب نشه
    و اگه متن بدون پیشوند خودش با یه پترن عمومی بخوره، دست‌نخورده ول میشه که دوبار اجرا نشه
    """
    user = update.effective_user
    msg = update.effective_message
    if not user or user.id not in config.ADMIN_IDS or not getattr(msg, "text", None):
        return
    text = msg.text.strip()
    pairs = _quick_pairs()
    for pat, _f in pairs:
        if pat.match(text):
            return  # خودش یه دستور معتبر بدون‌پیشونده، هندلر اصلیش می‌گیرتش
    prefixed = f"تریاکی {text}"
    for pat, func in pairs:
        if pat.match(prefixed):
            await func(update, context)
            return


def register_handlers(app: Application) -> None:
    fa_text = filters.TEXT & ~filters.COMMAND

    # ── گیت زندان لو دادن (راند ۲۲): زندانی هیچ دستور/دکمه‌ای نداره تا آزاد بشه ──
    # راند ۳۶ (باگ پروداکشن): PTB تو هر گروه فقط اولین هندلر مچ‌شده رو اجرا می‌کنه؛
    # گیت زندان تو گروه مشترک با power_gate همیشه پشت سرش قفل می‌شد و هیچ‌وقت اجرا نمی‌شد.
    # گروه مستقل -6 یعنی قبل از همه گیت‌های دیگه
    app.add_handler(MessageHandler(filters.ALL, power.jail_gate), group=-6)
    app.add_handler(CallbackQueryHandler(power.jail_gate), group=-6)

    # ── گیت خاموشی (/botdown کلی و /botoff گروهی)، قبل از همه چیز ──
    app.add_handler(MessageHandler(filters.ALL, power.power_gate), group=-5)
    app.add_handler(CallbackQueryHandler(power.power_gate), group=-5)

    # ── ثبت کاربران دیده‌شده (برای حمله با @یوزرنیم به غریبه‌ها)، بی‌صدا و قبل از همه ──
    app.add_handler(MessageHandler(filters.ALL, seen.track), group=-4)

    # ── گیت عضویت اجباری، قبل از همه هندلرها (غیرفعال که باشه کاملاً عبوریه) ──
    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, gate.gate_messages), group=-3)
    app.add_handler(CallbackQueryHandler(gate.gate_confirm, pattern=r"^fj:check$"), group=-3)
    app.add_handler(CallbackQueryHandler(gate.gate_callbacks), group=-3)
    # recheck رویدادمحور: لفت/کیک از کانال فوراً دسترسی رو قطع می‌کنه (بدون اینکه کاربر پیام بده)
    app.add_handler(ChatMemberHandler(gate.fj_member_event, ChatMemberHandler.CHAT_MEMBER), group=-3)

    # ── گارد مالکیت دکمه‌ها، قبل از همه کالبک‌ها (غریبه هیچ واکنشی نمی‌بینه) ──
    app.add_handler(CallbackQueryHandler(common.owner_guard), group=-2)

    # ── ورودی معلق (اسم سگ بعد خرید | اسم کارتل بعد ساخت)، قبل از همه دستورهای متنی ──
    app.add_handler(MessageHandler(fa_text, pending.capture), group=-1)
    # رسانه‌های همگانی (عکس/ویدیو/فایل) متن ندارن و به فیلتر متن نمی‌رسن، گیرنده جدا براشون لازمه
    app.add_handler(MessageHandler(filters.ALL & ~filters.TEXT & ~filters.COMMAND, pending.capture_bcast_media), group=-1)

    # ── دستورهای اسلشی ──
    app.add_handler(CommandHandler("start", start.start_cmd))
    app.add_handler(CommandHandler("profile", profile.profile_cmd))
    app.add_handler(CommandHandler("farm", farm.farm_cb))
    app.add_handler(CommandHandler("shop", shop.shop_cb))
    app.add_handler(CommandHandler("attack", attack.attack_cb))
    app.add_handler(CommandHandler("rank", rank.rank_cb))
    app.add_handler(CommandHandler("dogs", dogs.dogs_cb))
    app.add_handler(CommandHandler("mine", mine.mine_cmd))
    app.add_handler(CommandHandler("admin", admin.admin_cmd))
    app.add_handler(CommandHandler("help", start.help_cmd))
    app.add_handler(CommandHandler("heal", battle.heal_cmd))
    app.add_handler(CommandHandler("energy", energy.energy_cmd))
    app.add_handler(CommandHandler("backup", backup.backup_cmd))
    app.add_handler(CommandHandler("upload_backup", backup.upload_backup_cmd))
    app.add_handler(CommandHandler("user", admin.user_cmd))
    app.add_handler(CommandHandler("hideboard", admin.hideboard_cmd))
    app.add_handler(CommandHandler("update", admin.update_cmd))
    app.add_handler(CommandHandler("addxpgroup", admin.addxpgroup_cmd))
    app.add_handler(CommandHandler("addtp", admin.addtp_cmd))
    app.add_handler(CommandHandler("addgem", admin.addgem_cmd))  # راند ۲۷
    app.add_handler(CommandHandler("addxp", admin.addxp_cmd))
    app.add_handler(CommandHandler("addseed", admin.addseed_cmd))
    app.add_handler(CommandHandler("detp", admin.detp_cmd))
    app.add_handler(CommandHandler("dexp", admin.dexp_cmd))
    app.add_handler(CommandHandler("clearacc", admin.clearacc_cmd))
    # ── سوئیچ خاموش/روشن ──
    app.add_handler(CommandHandler("botdown", power.botdown_cmd))
    app.add_handler(CommandHandler("botup", power.botup_cmd))
    app.add_handler(CommandHandler("botoff", power.botoff_cmd))
    app.add_handler(CommandHandler("boton", power.boton_cmd))

    # ── اد شدن ربات به گروه، خودش متن خوش‌آمد می‌فرسته ──
    app.add_handler(ChatMemberHandler(start.bot_added, ChatMemberHandler.MY_CHAT_MEMBER))

    # ── دستورهای متنی فارسی (PV و گروه)، همه با پیشوند «تریاکی » به‌جز کنده کاری ──
    # رَپر dedup: ۵۰ تا از یه دستور پشت سر هم بفرستی فقط اولیش اجرا میشه
    for _name, pattern, func in TEXT_HANDLERS:
        app.add_handler(MessageHandler(fa_text & filters.Regex(pattern), common.text_dedup(func)))

    # ── راند ۳۵/۳۶: شرت‌کات ادمین (بدون پیشوند)، حتماً بعد از دستورهای متنی ثبت میشه ──
    # PTB تو هر گروه فقط اولین هندلر مچ‌شده رو اجرا می‌کنه؛ قبل از لوپ بودن یعنی بلع همه دستورها
    # (باگ پروداکشن راند ۳۶: «تریاکی کاشت» و رفقاش جواب نمی‌دادن). اینجوری فقط متن‌هایی که
    # هیچ دستوری نگرفتنشون به admin_quick میرسه و خودش هم متن معتبر رو دوباره اجرا نمی‌کنه
    app.add_handler(MessageHandler(fa_text, admin_quick, block=False))

    # ── فایل بک‌آپ (فقط بعد از /upload_backup و فقط ادمین) ──
    app.add_handler(MessageHandler(filters.ATTACHMENT & ~filters.COMMAND, backup.backup_doc))

    # ── منوی اصلی ──
    app.add_handler(CallbackQueryHandler(start.menu_cb, pattern=r"^menu:home$"))
    app.add_handler(CallbackQueryHandler(profile.profile_cb, pattern=r"^menu:profile$"))
    app.add_handler(CallbackQueryHandler(farm.farm_cb, pattern=r"^menu:farm$"))
    app.add_handler(CallbackQueryHandler(shop.shop_cb, pattern=r"^menu:shop$"))
    app.add_handler(CallbackQueryHandler(attack.attack_cb, pattern=r"^menu:attack$"))
    app.add_handler(CallbackQueryHandler(attack.target_go_cb, pattern=r"^patt:go$"))
    app.add_handler(CallbackQueryHandler(attack.target_hit_cb, pattern=r"^patt:hit:\d+$"))
    app.add_handler(CallbackQueryHandler(attack.target_next_cb, pattern=r"^patt:next:\d+$"))
    app.add_handler(CallbackQueryHandler(attack.target_spy_cb, pattern=r"^patt:spy:\d+$"))
    app.add_handler(CallbackQueryHandler(attack.target_back_cb, pattern=r"^patt:back$"))
    app.add_handler(CallbackQueryHandler(attack.target_break_cb, pattern=r"^patt:break:\d+$"))
    app.add_handler(CallbackQueryHandler(attack.ownshield_hit_cb, pattern=r"^patt:shcf:\d+$"))
    app.add_handler(CallbackQueryHandler(attack.ownshield_break_cb, pattern=r"^patt:shbr:\d+$"))
    app.add_handler(CallbackQueryHandler(rank.rank_cb, pattern=r"^menu:rank$"))
    app.add_handler(CallbackQueryHandler(rank.rank_tab_cb, pattern=r"^rank:tab:\w+:\w+$"))
    app.add_handler(CallbackQueryHandler(dogs.dogs_cb, pattern=r"^menu:dogs$"))
    app.add_handler(CallbackQueryHandler(team.team_cb, pattern=r"^menu:team$"))
    app.add_handler(CallbackQueryHandler(dquests.daily_quests_cb, pattern=r"^menu:dquests$"))
    app.add_handler(CallbackQueryHandler(mine.mine_home_cb, pattern=r"^menu:mine$"))
    app.add_handler(CallbackQueryHandler(company.company_cb, pattern=r"^menu:company$"))
    app.add_handler(CallbackQueryHandler(world.shelter_cmd, pattern=r"^menu:shelter$"))
    app.add_handler(CallbackQueryHandler(skills.skills_cb, pattern=r"^menu:skills$"))
    app.add_handler(CallbackQueryHandler(gear.gear_cb, pattern=r"^menu:gear$"))

    # ── مهارت (دکمه‌ها) ──
    app.add_handler(CallbackQueryHandler(skills.skill_up_cb, pattern=r"^sk:up:\w+$"))
    app.add_handler(CallbackQueryHandler(skills.skill_reset_confirm, pattern=r"^sk:reset$"))
    app.add_handler(CallbackQueryHandler(skills.skill_reset_execute, pattern=r"^cf:sk:reset$"))

    # ── تجهیزات (دکمه‌ها) ──
    app.add_handler(CallbackQueryHandler(gear.gear_tab_cb, pattern=r"^gear:tab:(?:weap|arm)$"))
    app.add_handler(CallbackQueryHandler(gear.gear_equip_cb, pattern=r"^gear:eq:(?:weap|arm):\w+$"))
    app.add_handler(CallbackQueryHandler(gear.gear_unequip_cb, pattern=r"^gear:un:(?:weap|arm)$"))
    app.add_handler(CallbackQueryHandler(gear.gear_upg_cb, pattern=r"^gear:upg$"))
    # راند ۲۹: کارت آیتم + انتخاب از کارت + ریلود مهمات با تاییدیه
    app.add_handler(CallbackQueryHandler(gear.gear_item_cb, pattern=r"^gear:it:(?:weap|arm):\w+$"))
    app.add_handler(CallbackQueryHandler(gear.gear_equip_card_cb, pattern=r"^gear:eqs:(?:weap|arm):\w+$"))
    app.add_handler(CallbackQueryHandler(gear.gear_reload_cb, pattern=r"^gear:rel:\w+$"))
    app.add_handler(CallbackQueryHandler(gear.gear_reload_do_cb, pattern=r"^gear:reldo:\w+:\d+$"))
    app.add_handler(CallbackQueryHandler(gear.gear_reload_cancel_cb, pattern=r"^gear:relcl:\w+$"))
    app.add_handler(CallbackQueryHandler(gear.gear_item_upg_cb, pattern=r"^gear:upgi:(?:weap|arm):\w+$"))  # راند ۳۰: آپگرید از داخل کارت

    # ── کنده‌کاری (دکمه‌ها) ──
    app.add_handler(CallbackQueryHandler(mine.mine_roll_cb, pattern=r"^mine:roll$"))
    app.add_handler(CallbackQueryHandler(mine.mine_tools_cb, pattern=r"^mine:tools$"))
    app.add_handler(CallbackQueryHandler(mine.mine_upg_confirm, pattern=r"^mine:upg:\w+$"))
    app.add_handler(CallbackQueryHandler(mine.mine_upg_execute, pattern=r"^cf:mine:upg:\w+$"))
    app.add_handler(CallbackQueryHandler(mine.mine_upg_cancel, pattern=r"^cl:mine:upg:\w+$"))

    # ── شرکت (دکمه‌ها) ──
    app.add_handler(CallbackQueryHandler(company.company_action_confirm, pattern=r"^comp:(?:build|upg):\w+$"))
    app.add_handler(CallbackQueryHandler(company.company_collect_execute, pattern=r"^comp:col:\w+$"))
    app.add_handler(CallbackQueryHandler(company.company_action_execute, pattern=r"^cf:comp:(?:build|upg):\w+$"))
    app.add_handler(CallbackQueryHandler(company.company_action_cancel, pattern=r"^cl:comp:(?:build|upg):\w+$"))

    # ── مزرعه ──
    app.add_handler(CallbackQueryHandler(farm.buy_plot_confirm, pattern=r"^farm:buy$"))
    app.add_handler(CallbackQueryHandler(farm.buy_plot_execute, pattern=r"^cf:farm:buy$"))
    app.add_handler(CallbackQueryHandler(farm.plant_picker, pattern=r"^farm:plant:\d+$"))
    app.add_handler(CallbackQueryHandler(farm.plant_confirm, pattern=r"^farm:plant:\d+:\w+$"))
    app.add_handler(CallbackQueryHandler(farm.plant_execute, pattern=r"^cf:plant:\d+:\w+$"))
    app.add_handler(CallbackQueryHandler(farm.harvest_cb, pattern=r"^farm:hv$"))
    app.add_handler(CallbackQueryHandler(farm.farm_refresh_cb, pattern=r"^farm:rf$"))
    app.add_handler(CallbackQueryHandler(farm.upgrade_confirm, pattern=r"^farm:up:\d+$"))
    app.add_handler(CallbackQueryHandler(farm.upgrade_execute, pattern=r"^cf:farm:up:\d+$"))
    app.add_handler(CallbackQueryHandler(farm.speed_menu_cb, pattern=r"^farm:spd:\d+$"))      # 💎 تسریع ساخت زمین (راند ۲۷)
    app.add_handler(CallbackQueryHandler(farm.speed_apply_cb, pattern=r"^farm:spddo:\d+:\d+$"))

    # ── فروشگاه ──
    app.add_handler(CallbackQueryHandler(shop.section_cb, pattern=r"^shop:sec:\w+$"))
    app.add_handler(CallbackQueryHandler(shop.buy_confirm, pattern=r"^shop:buy:\w+:\w+$"))
    app.add_handler(CallbackQueryHandler(shop.buy_execute, pattern=r"^cf:shop:buy:\w+:\w+$"))
    app.add_handler(CallbackQueryHandler(shop.gear_up_confirm, pattern=r"^gup:(?:weap|arm):\w+$"))
    app.add_handler(CallbackQueryHandler(shop.gear_up_execute, pattern=r"^cf:gup:(?:weap|arm):\w+$"))
    app.add_handler(CallbackQueryHandler(shop.gear_up_cancel, pattern=r"^cl:gup:(?:weap|arm)$"))
    app.add_handler(CallbackQueryHandler(shop.buyres_execute, pattern=r"^cf:shopres:\w+:\d+$"))
    app.add_handler(CallbackQueryHandler(shop.buyres_cancel, pattern=r"^cl:shopres$"))
    app.add_handler(CallbackQueryHandler(shop.buyseed_execute, pattern=r"^cf:shopseed:\w+:\d+(?::\d+)?$"))
    app.add_handler(CallbackQueryHandler(shop.buyseed_cancel, pattern=r"^cl:shopseed$"))

    # ── سگ‌ها ──
    app.add_handler(CallbackQueryHandler(dogs.feed_picker, pattern=r"^dogs:feed:\d+$"))
    app.add_handler(CallbackQueryHandler(dogs.feed_execute, pattern=r"^cf:feed:\d+:\w+$"))
    app.add_handler(CallbackQueryHandler(dogs.dog_card_cb, pattern=r"^dog:card:\d+$"))
    app.add_handler(CallbackQueryHandler(dogs.release_confirm, pattern=r"^dog:rel:\d+$"))
    app.add_handler(CallbackQueryHandler(dogs.release_execute, pattern=r"^relcf:\d+:\d+$"))

    # ── کارتل (دکمه‌ها) ──
    app.add_handler(CallbackQueryHandler(team.quests_text, pattern=r"^team:quests$"))
    app.add_handler(CallbackQueryHandler(team.team_mine_text, pattern=r"^team:mine$"))  # دکمه جمعی
    app.add_handler(CallbackQueryHandler(team.top_teams_text, pattern=r"^team:top$"))
    app.add_handler(CallbackQueryHandler(team.top_teams_tab_cb, pattern=r"^ttop:tab:\w+:\w+$"))
    app.add_handler(CallbackQueryHandler(team.leave_confirm, pattern=r"^team:leave$"))
    app.add_handler(CallbackQueryHandler(team.disband_confirm, pattern=r"^team:disband$"))
    app.add_handler(CallbackQueryHandler(team.team_confirm_cb, pattern=r"^tmcf:(?:leave|disband|rename):\d+$"))
    app.add_handler(CallbackQueryHandler(team.team_create_cb, pattern=r"^teamcf:(?:ok|no):\d+$"))
    app.add_handler(CallbackQueryHandler(team.team_manage_cb, pattern=r"^team:mng$"))
    app.add_handler(CallbackQueryHandler(team.team_requests_cb, pattern=r"^team:req$"))
    app.add_handler(CallbackQueryHandler(team.team_request_resolve_cb, pattern=r"^treq:(?:ok|no):\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(team.team_join_request_cb, pattern=r"^tjr:(?:ok|no):\d+$"))  # دی‌ام درخواست به رهبر (راند ۲۷)
    app.add_handler(CallbackQueryHandler(team.team_kick_cb, pattern=r"^team:kick$"))
    app.add_handler(CallbackQueryHandler(team.team_kick_execute, pattern=r"^tkick:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(team.team_kick_cancel, pattern=r"^tkcl:\d+$"))
    app.add_handler(CallbackQueryHandler(team.team_admin_confirm_cb, pattern=r"^tadm:(?:add|del):\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(team.team_admin_cancel_cb, pattern=r"^tadm:no:\d+$"))
    app.add_handler(CallbackQueryHandler(team.buildings_cb, pattern=r"^team:bld$"))
    app.add_handler(CallbackQueryHandler(team.team_bank_text, pattern=r"^team:bank$"))
    app.add_handler(CallbackQueryHandler(team.team_upgrade_cb, pattern=r"^tbup:(?:atk|def):\d+$"))
    app.add_handler(CallbackQueryHandler(team.team_upgrade_execute, pattern=r"^tbcf:(?:atk|def):\d+$"))

    # ── سیستم‌های جهان (دکمه‌ها) ──
    app.add_handler(CallbackQueryHandler(world.shelter_cat_cb, pattern=r"^shelter:cat:\w+$"))
    app.add_handler(CallbackQueryHandler(smuggle.ship_page, pattern=r"^sm:page$"))
    app.add_handler(CallbackQueryHandler(smuggle.ship_qty_page, pattern=r"^sm:pick:\w+$"))
    app.add_handler(CallbackQueryHandler(smuggle.ship_confirm_page, pattern=r"^sm:qty:\w+:(?:\d+|all)$"))
    app.add_handler(CallbackQueryHandler(smuggle.ship_execute, pattern=r"^sm:go:\w+:\d+$"))
    app.add_handler(CallbackQueryHandler(smuggle.ship_ask_qty_cb, pattern=r"^sm:ask:\w+$"))
    # راند ۲۹: تاییدیه رشوه زندان
    app.add_handler(CallbackQueryHandler(snitch.bribe_confirm_cb, pattern=r"^brcf:\d+$"))
    app.add_handler(CallbackQueryHandler(snitch.bribe_cancel_cb, pattern=r"^brcl:\d+$"))
    app.add_handler(CallbackQueryHandler(smuggle.caravan_page, pattern=r"^smc:page$"))
    app.add_handler(CallbackQueryHandler(smuggle.caravan_confirm_page, pattern=r"^smc:qty:(?:\d+|all)$"))
    app.add_handler(CallbackQueryHandler(smuggle.caravan_execute, pattern=r"^smc:go:\d+$"))
    app.add_handler(CallbackQueryHandler(smuggle.caravan_ask_qty_cb, pattern=r"^smc:ask$"))
    app.add_handler(CallbackQueryHandler(world.shelter_up_confirm, pattern=r"^shelter:up$"))
    app.add_handler(CallbackQueryHandler(world.shelter_up_execute, pattern=r"^cf:shelter:up$"))
    app.add_handler(CallbackQueryHandler(world.resource_sell_cb, pattern=r"^shelter:sell$"))
    app.add_handler(CallbackQueryHandler(world.sellres_execute, pattern=r"^cf:sellres:(?:wood|iron):\d+$"))
    app.add_handler(CallbackQueryHandler(world.sellres_cancel, pattern=r"^cl:sellres$"))
    app.add_handler(CallbackQueryHandler(mines.mines_cb, pattern=r"^mn:"))  # راند ۲۸ بازی مین
    app.add_handler(CallbackQueryHandler(team.team_chat_cb, pattern=r"^tc:(?:page|send|ref|back)$"))
    app.add_handler(CallbackQueryHandler(world.caravan_hit_cb, pattern=r"^cv:hit$"))  # دکمه جمعی
    app.add_handler(CallbackQueryHandler(boss.boss_hit_cb, pattern=r"^bsh:hit$"))     # دکمه جمعی باس (راند ۲۳)
    app.add_handler(CallbackQueryHandler(boss.admin_boss_cb, pattern=r"^admb:"))      # پنل ادمین باس‌ها
    app.add_handler(CallbackQueryHandler(market.market_cb, pattern=r"^mk:"))          # دکمه‌های مارکت

    # ── بانک شخصی (دکمه‌ها) ──
    app.add_handler(CallbackQueryHandler(bank.bank_cb, pattern=r"^menu:bank$"))
    app.add_handler(CallbackQueryHandler(bank.bank_ask_cb, pattern=r"^bank:(?:dep|wd)$"))
    app.add_handler(CallbackQueryHandler(bank.bank_quick_cb, pattern=r"^bankq:(?:dep|wd):(?:all|half)$"))
    app.add_handler(CallbackQueryHandler(bank.bank_transfer_start, pattern=r"^bank:tf$"))
    app.add_handler(CallbackQueryHandler(bank.bank_transfer_execute, pattern=r"^tbf:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(bank.bank_upgrade_confirm, pattern=r"^bank:up$"))
    app.add_handler(CallbackQueryHandler(bank.bank_upgrade_execute, pattern=r"^cf:bank:up$"))

    # ── نبرد HP گروهی + درمان ──
    app.add_handler(CallbackQueryHandler(battle.heal_buy_cb, pattern=r"^heal:buy:\w+$"))
    app.add_handler(CallbackQueryHandler(energy.energy_buy_cb, pattern=r"^en:buy:\w+$"))

    # ── آموزشات (هلپ دکمه‌دار) ──
    app.add_handler(CallbackQueryHandler(start.help_section_cb, pattern=r"^help:sec:\w+$"))
    app.add_handler(CallbackQueryHandler(start.help_menu_cb, pattern=r"^help:menu$"))

    # ── تایید دستورهای متنی (فقط خود کاربر، اسم سگ اختیاریه) ──
    app.add_handler(CallbackQueryHandler(textcmd.tx_confirm_cb, pattern=r"^txcf:\w+:\w+:\d+(?::.+)?$"))
    app.add_handler(CallbackQueryHandler(textcmd.tx_cancel_cb, pattern=r"^txcl:\d+$"))

    # ── ادمین ──
    app.add_handler(CallbackQueryHandler(admin.admin_cb, pattern=r"^adm:\w+:\d+$"))
    app.add_handler(CallbackQueryHandler(admin.clearacc_cb, pattern=r"^cacc:(?:ok|no):\d+$"))
    app.add_handler(CallbackQueryHandler(admin.broadcast_scope_cb, pattern=r"^bcs:[gpa]:-?\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(admin.broadcast_mode_cb, pattern=r"^bcm:[ft]:[gpa]:-?\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(admin.broadcast_cancel_cb, pattern=r"^bcc$"))

    # ── منوی بک‌آپ ──
    app.add_handler(CallbackQueryHandler(backup.backup_menu_cb, pattern=r"^bk:menu$"))
    app.add_handler(CallbackQueryHandler(backup.backup_make_cb, pattern=r"^bk:make$"))
    app.add_handler(CallbackQueryHandler(backup.backup_upload_cb, pattern=r"^bk:up$"))

    # ── عمومی ──
    app.add_handler(CallbackQueryHandler(start.cancel_cb, pattern=r"^cl$"))
    app.add_handler(CallbackQueryHandler(start.noop_cb, pattern=r"^noop:"))
