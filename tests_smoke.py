"""
اسموک‌تست آفلاین تریاکی، فاز ۲، بدون اتصال به تلگرام
اجرا:  python tests_smoke.py
"""

import asyncio
import os
import random
from datetime import timedelta
from types import SimpleNamespace

random.seed(7)

os.environ["TERIAKY_DB"] = "sqlite+aiosqlite:////tmp/teriaky_test.db"
os.environ["TERIAKY_ADMIN_IDS"] = "1001, 1003"
if os.path.exists("/tmp/teriaky_test.db"):
    os.remove("/tmp/teriaky_test.db")

import config  # noqa: E402
from database import init_db, session_scope  # noqa: E402
from models import Dog, GroupActivity, GroupPlayer, Plot, Team, TeamDaily, User  # noqa: E402
from services import (  # noqa: E402
    backup as backup_svc,
    bank as bank_svc,
    battle as battle_svc,
    combat,
    dogs as dog_svc,
    economy,
    farming,
    seen as seen_svc,
    shop_svc,
    teams as team_svc,
    users,
    world as world_svc,
)
from sqlalchemy import select  # noqa: E402
from handlers.common import strip_home  # noqa: E402
from utils import (  # noqa: E402
    fa_dur, fa_num, find_by_name, gregorian_to_jalali, iran_today, jalali_str,
    money, money_tp, normalize_fa, now_utc, parse_amount,
)

PASS = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    assert cond, f"❌ {name} | {detail}"
    PASS += 1
    print(f"✅ {name} {detail}")


def tg(uid, username=None, first_name=None):
    return SimpleNamespace(id=uid, username=username, first_name=first_name)


async def main() -> None:
    await init_db()

    # ═══ کاتالوگ‌ها ═══
    seed_lvls = [s["min_level"] for s in config.SEEDS.values() if not s.get("legendary")]
    check("ترتیب لول بذرهای عادی صعودیه", seed_lvls == sorted(seed_lvls), str(seed_lvls))
    check("ترتیب بذرها: ۷ عادی + جهنم و ابلیس و جهش‌یافته تو آخر",
          list(config.SEEDS.keys()) == ["marijuana", "gharch", "peyote", "kratom", "khashkhash", "teriak", "cocaine", "jahannam", "eblis", "mutant"],
          str(list(config.SEEDS.keys())))
    check("سلسله لول بذرهای عادی: ۱ و ۳ و ۴ و ۵ و ۷ و 10 و 14",
          [config.SEEDS[k]["min_level"] for k in ("marijuana", "gharch", "peyote", "kratom", "khashkhash", "teriak", "cocaine")]
          == [1, 3, 4, 5, 7, 10, 14],
          str([config.SEEDS[k]["min_level"] for k in config.SEEDS if not config.SEEDS[k].get("legendary")]))
    check("کلید بذرهای قدیمی عوض نشده (انبار و زمین بازیگرای قدیمی سالم می‌مونه)",
          all(k in config.SEEDS for k in ("marijuana", "gharch", "peyote", "teriak", "cocaine")))
    check("کراتوم و خشخاش سیاه بین پیوت و تریاک قرار گرفتن",
          config.SEEDS["peyote"]["price"] < config.SEEDS["kratom"]["price"] < config.SEEDS["khashkhash"]["price"] < config.SEEDS["teriak"]["price"]
          and config.SEEDS["peyote"]["sell"] < config.SEEDS["kratom"]["sell"] < config.SEEDS["khashkhash"]["sell"] < config.SEEDS["teriak"]["sell"])
    check("جهنم و ابلیس و جهش‌یافته افسانه‌ای‌ان و قیمت‌شون صفره (قابل خرید نیستن)",
          config.SEEDS["jahannam"].get("legendary") and config.SEEDS["eblis"].get("legendary") and config.SEEDS["mutant"].get("legendary")
          and config.SEEDS["jahannam"]["price"] == 0 and config.SEEDS["eblis"]["price"] == 0 and config.SEEDS["mutant"]["price"] == 0)
    check("بذر افسانه‌ای تو لیست شاپ نمیاد",
          "jahannam" not in shop_svc.shop_seeds() and "eblis" not in shop_svc.shop_seeds() and "mutant" not in shop_svc.shop_seeds())
    check("بذر جهش‌یافته از جهنم و ابلیس نایاب‌تره: فروش 150,000 و سقف خودش 200,000ـه",
          config.SEEDS["mutant"]["sell"] == 150000 and config.SEEDS["mutant"].get("cap") == 200000)
    _mrate = [o for o in config.SEARCH_OUTCOMES if o["key"] == "seed_mutant"]
    _cloot = [l for l in config.CARAVAN_LOOT if l["key"] == "mutant"]
    check("دراپ جهش‌یافته تو جستجو و کاروان خیلی کمه (۱٪، کمتر از ابلیس)",
          _mrate and _mrate[0]["chance"] == 0.01 and _cloot and _cloot[0]["chance"] == 0.01)
    check("جمع شانس جستجوها ۱ـه", abs(sum(o["chance"] for o in config.SEARCH_OUTCOMES) - 1.0) < 1e-9)
    check("جمع شانس لوت کاروان ۱ـه", abs(sum(l["chance"] for l in config.CARAVAN_LOOT) - 1.0) < 1e-9)
    check("قیمت فروش بذر ابلیس 50,000 و بذر جهنم 27,000ـه (بکم کوچیک از دوبرابر کوکائین)",
          config.SEEDS["eblis"]["sell"] == 50000 and config.SEEDS["jahannam"]["sell"] == 27000)
    _rates = {k: config.SEEDS[k]["sell"] / config.SEEDS[k]["grow_min"] for k in ("cocaine", "jahannam", "eblis")}
    check("سود هر دقیقه رشد: جهنم از کوکائین و ابلیس از جهنم بصرفه‌تره ولی فقط بکم",
          config.SEEDS["jahannam"]["grow_min"] == 45 and config.SEEDS["eblis"]["grow_min"] == 80
          and _rates["cocaine"] == 560 and _rates["jahannam"] == 600 and _rates["eblis"] == 625
          and 0 < _rates["jahannam"] - _rates["cocaine"] <= 50
          and 0 < _rates["eblis"] - _rates["jahannam"] <= 50,
          str({k: round(v, 1) for k, v in _rates.items()}))
    check("سقف فروش نهایی بذر افسانه‌ای 60,000ـه", config.LEGENDARY_SELL_CAP == 60000)

    # ── برداشت افسانه‌ای: با بهترین کیفیت و لول مکس هم از 60,000 رد نمیشه ──
    _orig_quality = world_svc.roll_quality
    world_svc.roll_quality = lambda bonus=0.0: config.QUALITY_TIERS[-1]  # ⭐⭐⭐⭐⭐ ×3
    async with session_scope() as s:
        lgu, _ = await users.get_or_create(s, tg(8842, "legcap", "سقفی"))
        lgu.level = 20
        await world_svc._meta_set(s, "weather_key", "normal")
        await world_svc._meta_set(s, "weather_until", (now_utc() + timedelta(seconds=7200)).isoformat())
        await world_svc._meta_set(s, "market", ",".join(f"{k}:0" for k in config.SEEDS))
        await world_svc._meta_set(s, "market_until", (now_utc() + timedelta(seconds=14400)).isoformat())
        lgp = Plot(user_id=lgu.id, status="growing")
        s.add(lgp)
        await s.flush()
        lgp.status, lgp.crop = "growing", "jahannam"
        lgp.planted_at = now_utc() - timedelta(hours=2)
        lgp.ready_at = now_utc() - timedelta(seconds=1)
        lg_cash = lgu.cash
        ok_lg, _a, _ex, _dq, _nn = await farming.harvest_all(s, lgu)
        check("فروش جهنم با بهترین کیفیت و لول مکس روی سقف 60,000 می‌ایسته",
              ok_lg and lgu.cash - lg_cash == 60000, str(lgu.cash - lg_cash))
        check("سقف فروش جهش‌یافته جدای خودشه و کوکائین سقف نداره",
              farming.apply_legendary_cap("mutant", 999999) == 200000
              and farming.apply_legendary_cap("jahannam", 999999) == 60000
              and farming.apply_legendary_cap("cocaine", 999999) == 999999)
        lgu.last_harvest_at = None
        lgp.status, lgp.crop = "growing", "cocaine"
        lgp.planted_at = now_utc() - timedelta(hours=1)
        lgp.ready_at = now_utc() - timedelta(seconds=1)
        lg_cash = lgu.cash
        ok_lg2, _a2, _ex2, _dq2, _nn2 = await farming.harvest_all(s, lgu)
        check("بذر غیرافسانه‌ای سقف نمی‌خوره (کوکائین ⭐5 لول 20 = 57,960)",
              ok_lg2 and lgu.cash - lg_cash == 57960, str(lgu.cash - lg_cash))
        await s.commit()
    world_svc.roll_quality = _orig_quality

    # ── بالانس آیتم‌های آخر بازی و زره‌ها ──
    check("زره‌های آخر بازی دفاعشون باف شده",
          config.ARMORS["legend"]["defense"] == 150 and config.ARMORS["titan"]["defense"] == 120
          and config.ARMORS["nano"]["defense"] == 90 and config.ARMORS["swat"]["defense"] == 52)
    check("پلاسما پاک شده و گاتلینگ و آرپی‌جی رفتن تو گرمی با یه لول زودتر",
          "plasma" not in config.WEAPONS
          and config.WEAPONS["minigun"]["sec"] == "hot" and config.WEAPONS["minigun"]["min_level"] == 12
          and config.WEAPONS["rpg"]["sec"] == "hot" and config.WEAPONS["rpg"]["min_level"] == 14
          and config.WEAPONS["minigun"]["price"] == 60000 and config.WEAPONS["rpg"]["price"] == 95000)
    check("پنج سلاح ویژه لول 16 تا 20 با دمیج برابر 250 و قابلیت",
          [(k, w["min_level"], w["attack"], w["sec"], w["ability"]["kind"]) for k, w in
           [(x, config.WEAPONS[x]) for x in ("viperx", "hellfire", "vampire", "shadowfang", "oblivion")]]
          == [("viperx", 16, 250, "special", "poison"),
              ("hellfire", 17, 250, "special", "hellfire"),
              ("vampire", 18, 250, "special", "vampire"),
              ("shadowfang", 19, 250, "special", "shadow"),
              ("oblivion", 20, 250, "special", "oblivion")])
    check("ترتیب قیمت و قدرت سلاح‌ها بعد از گرونی محفوظه",
          config.WEAPONS["minigun"]["price"] < config.WEAPONS["rpg"]["price"] < config.WEAPONS["viperx"]["price"]
          and config.WEAPONS["minigun"]["attack"] < config.WEAPONS["rpg"]["attack"] < config.WEAPONS["viperx"]["attack"]
          and config.WEAPONS["viperx"]["price"] < config.WEAPONS["hellfire"]["price"]
          < config.WEAPONS["vampire"]["price"] < config.WEAPONS["shadowfang"]["price"]
          < config.WEAPONS["oblivion"]["price"])

    legends = [k for k, a in config.ARMORS.items() if a.get("legendary")]
    check("فقط یه زره افسانه‌ای هست", legends == ["legend"])
    check("توضیح زره افسانه‌ای دقیق ست شده", "نصف مقدار سکه‌ای که دشمن از شما دریافت می‌کند از بین برود" in config.ARMORS["legend"]["desc"])

    rares = [k for k, d in config.DOGS.items() if d.get("rare")]
    check("فقط یه سگ کمیاب هست", len(rares) == 1, str(rares))

    check("قیمت و قدرت همه سلاح‌ها مثبته", all(w["price"] > 0 and w["attack"] > 0 for w in config.WEAPONS.values()))
    check("همه آیتم‌ها desc و min_level دارن",
          all(i.get("desc") and "min_level" in i for i in list(config.WEAPONS.values()) + list(config.ARMORS.values()) + list(config.SEEDS.values())))
    check("همه نژادها trait_line و min_level دارن",
          all(d.get("trait_line") and "min_level" in d for d in config.DOGS.values()))
    check("همه سلاح‌ها آهن خرید دارن", all(w.get("iron", 0) > 0 for w in config.WEAPONS.values()))

    # ═══ منحنی تجربه ═══
    needs = [economy.xp_need(l) for l in range(1, 21)]
    check("منحنی xp صعودیه", needs == sorted(needs), str(needs[:6]))
    diffs = [b - a for a, b in zip(needs, needs[1:])]
    check("سختی تدریجی زیاد میشه (محدب)", diffs == sorted(diffs), str(diffs[:6]))
    check("لول‌های اول سریعه", economy.xp_need(1) <= 60 and economy.xp_need(2) <= 180, f"1={economy.xp_need(1)} 2={economy.xp_need(2)}")

    # ═══ اقتصاد ═══
    prices = [economy.plot_price(i) for i in range(config.MAX_PLOTS)]
    check("قیمت زمین افزایشیه", all(a <= b for a, b in zip(prices, prices[1:])), str(prices))

    # ── کاتالوگ جدید زمین‌ها: ۱۰۰۰/۳۰ثانیه | ۱۰٬۰۰۰/۱۵دقیقه | ۲۰٬۰۰۰/۱ساعت | ۵۰٬۰۰۰/۱۲ساعت ──
    check("سقف زمین 5 تاست", config.MAX_PLOTS == 5)
    check("زمین اول رایگانه ولی ۱۰ ثانیه ساخت می‌خواد (قدم آموزشی)", config.PLOT_CATALOG[1]["price"] == 0 and config.PLOT_CATALOG[1]["build_sec"] == 10)
    check("زمین دوم ۱۰۰۰ و ۳۰ ثانیه",
          economy.plot_price(1) == 1000 and economy.plot_build_seconds(1) == 30,
          f"{economy.plot_price(1)}/{economy.plot_build_seconds(1)}")
    check("زمین سوم ۱۰٬۰۰۰ و ۱۵ دقیقه",
          economy.plot_price(2) == 10000 and economy.plot_build_seconds(2) == 900)
    check("زمین چهارم ۲۰٬۰۰۰ و ۱ ساعت",
          economy.plot_price(3) == 20000 and economy.plot_build_seconds(3) == 3600)
    check("زمین پنجم ۵۰٬۰۰۰ و ۱۲ ساعت",
          economy.plot_price(4) == 50000 and economy.plot_build_seconds(4) == 43200)
    check("گیت لول زمین‌ها هر کدوم مال خودشون",
          (economy.plot_required_level(0), economy.plot_required_level(1),
           economy.plot_required_level(2), economy.plot_required_level(3),
           economy.plot_required_level(4)) == (1, 5, 10, 15, 20),
          str([economy.plot_required_level(i) for i in range(5)]))

    # ── سلاح‌ها و زره‌های جدید ──
    check("17 تا سلاح داریم", len(config.WEAPONS) == 17, str(len(config.WEAPONS)))
    guns = sum(1 for w in config.WEAPONS.values() if w.get("gun"))
    check("هشت تفنگ اضافه شده", guns >= 8, str(guns))
    check("کلاش و آرپی‌جی هست", "ak47" in config.WEAPONS and "rpg" in config.WEAPONS)
    _k47, _ = find_by_name(config.WEAPONS, "کلاشنیکف")
    check("ak47 اسمش کلاشنیکفه و با اسم فارسی پیدا میشه",
          _k47 == "ak47" and config.WEAPONS["ak47"]["name"] == "کلاشنیکف 🔫")
    check("8 تا زره داریم", len(config.ARMORS) == 8, str(len(config.ARMORS)))
    check("کِولار و تیتانیومی هست", "kevlar" in config.ARMORS and "titan" in config.ARMORS)
    check("شوکر از کلت ضعیف‌تر و ارزون‌تره (اسلحه قوی‌تره)",
          config.WEAPONS["shocker"]["attack"] < config.WEAPONS["colt"]["attack"]
          and config.WEAPONS["shocker"]["price"] < config.WEAPONS["colt"]["price"])
    check("ترتیب نمایش سلاح‌ها از ضعیف به قویه (شوکر قبل کلت)",
          list(config.WEAPONS.keys()).index("shocker") < list(config.WEAPONS.keys()).index("colt"))
    w_sorted = sorted(config.WEAPONS.values(), key=lambda w: w["price"])
    check("قدرت سلاح با قیمت صعودیه (۵ تای ویژه برابرن، درخواست کارفرما)",
          all(a["attack"] <= b["attack"] for a, b in zip(w_sorted, w_sorted[1:])),
          str([(w["name"], w["price"], w["attack"]) for w in w_sorted][:5]))
    check("جز ویژه‌ها قدرت اکیداً صعودیه",
          all(a["attack"] < b["attack"] for a, b in zip(w_sorted, w_sorted[1:])
              if not (a.get("sec") == "special" and b.get("sec") == "special")))

    y1 = economy.crop_yield("teriak", 1, 1)
    y2 = economy.crop_yield("teriak", 2, 1)
    y3 = economy.crop_yield("teriak", 1, 11)
    check("لول زمین روی قیمت محصول اثر مستقیم نداره", y2 == y1, f"{y1}→{y2}")
    check("برداشت با لول کاربر بیشتره (۲% هر لول)", y3 > y1, f"{y1}→{y3}")
    check("لول زمین شانس محصول افسانه‌ای رو بیشتر می‌کنه",
          economy.plot_quality_bonus(1) == 0
          and abs(economy.plot_quality_bonus(6) - 5 * config.PLOT_Q5_PER_LEVEL) < 1e-9
          and config.PLOT_Q5_PER_LEVEL == 0.03)
    check("لول زمین هنوز رشد رو سریع‌تر می‌کنه",
          economy.plot_speed_mult(2) > economy.plot_speed_mult(1))

    rolls = [economy.mine_roll() for _ in range(20000)]
    low = sum(1 for r in rolls if r <= config.MINE_COMMON_MAX) / len(rolls)
    check("کنده‌کاری تو بازه ۱۰ تا ۱۵۰", min(rolls) >= 10 and max(rolls) <= 150)
    check("بازه پایین کنده‌کاری پرشانسه", 0.68 < low < 0.82, f"{low:.2f}")

    # ═══ مچ اسم فارسی ═══
    check("نرمال سازی فارسی", normalize_fa("دوبرمن  اصغر!") == "دوبرمن اصغر")
    k, _ = find_by_name(config.WEAPONS, "چاقو")
    check("«خرید چاقو» سلاح رو پیدا می‌کنه", k == "knife")
    kind, key, _ = shop_svc.find_shop_item("تریاک")
    check("«خرید تریاک» بذر رو پیدا می‌کنه", kind == "seed" and key == "teriak")
    dk, _ = dog_svc.find_dog("دوبرمن")
    check("«خرید سگ دوبرمن» نژاد رو پیدا می‌کنه", dk == "doberman")
    dk2, _ = dog_svc.find_dog("گرگ")
    check("مچ جزئی نژاد سگ", dk2 == "blackwolf")

    # ═══ فلو کاربر ═══
    async with session_scope() as s:
        u1, _ = await users.get_or_create(s, tg(1001, "ali", "علی"))
        u2, _ = await users.get_or_create(s, tg(1002, "sara", "سارا"))
        u3, _ = await users.get_or_create(s, tg(1003, "boss", "باس"))
        u3.level = 20

        # ── زمین اول دیگه هدیه نیس، خود بازیکن رایگان می‌خره (قدم آموزشی آنبوردینگ) ──
        free_plots = await farming.get_user_plots(s, u1.id)
        check("موقع ثبت‌نام زمین هدیه داده نمیشه، خودت باید بخری", len(free_plots) == 0, str(len(free_plots)))
        check("ثبت‌نام دوباره هم زمین نمیده",
              len(await farming.get_user_plots(s, (await users.get_or_create(s, tg(1001, "ali", "علی")))[0].id)) == 0)

        u1.cash = 100000  # شارژ حساب برای تست‌ها
        ok, msg = await farming.buy_plot(s, u1)
        check("زمین اول رایگان خریده میشه (صفر تی‌پوینت)", ok and u1.cash == 100000, msg)
        plots = await farming.get_user_plots(s, u1.id)
        check("یه زمین شد", len(plots) == 1)
        plot = plots[0]  # زمین اول برای کاشت تست‌ها
        check("زمین اول ۱۰ ثانیه ساخت می‌خواد", plot.built_at is not None, str(plot.built_at))
        st, left = plot.current_status()
        check("وضعیت «در حال ساخت» با زمان مونده، حداکثر ۱۰ ثانیه", st == "building" and 0 < left <= 10, f"{st}/{left}")
        ok, msg = await farming.plant(s, u1, plot, "teriak")
        check("کاشت روی زمین نیم‌ساخت رد میشه", not ok and "ساخته" in msg, msg)
        plot.built_at = now_utc() - timedelta(seconds=1)
        st, _ = plot.current_status()
        check("بعد تموم شدن ساخت استفاده میشه", st == "empty", st)

        check("زمین دوم زیر لول ۵ قفله", (await farming.buy_plot(s, u1))[0] is False or u1.level >= 5)
        u1.level = 10
        ok, msg = await farming.buy_plot(s, u1)
        check("خرید زمین دوم (۱۰۰۰ تی‌پوینت)", ok and u1.cash == 99000, msg)
        plots = await farming.get_user_plots(s, u1.id)
        check("دو تا زمین شد", len(plots) == 2)
        built_plot = plots[1]
        check("زمین خریدنی داره ساخته میشه", built_plot.built_at is not None, str(built_plot.built_at))
        built_plot.built_at = now_utc() - timedelta(seconds=1)  # ساختش تموم بشه برای تست‌های بعد

        u1.cash = 3000
        ok, msg = await shop_svc.purchase(s, u1, "seed", "teriak")
        check("خرید بذر تریاک", ok and u1.cash == 3000 - config.SEEDS["teriak"]["price"])
        stock = await farming.get_stock(s, u1.id)
        check("انبار بذر آپدیت شد", stock.get("teriak") == 1)

        ok, msg = await farming.plant(s, u1, plot, "teriak")
        check("کاشت با بذر", ok, msg)
        stock = await farming.get_stock(s, u1.id)
        check("بذر مصرف شد", stock.get("teriak") == 0)

        ok, msg = await farming.plant(s, u1, plot, "teriak")
        check("کاشت دوباره بدون بذر رد میشه", not ok)

        # ── برداشت و کولدان ۲ دقیقه ──
        # جهان رو قطعی کن: هوای عادی + بازار ثابت → فقط کیفیت ⭐ (1 تا 3 برابر) اثر داره
        await world_svc._meta_set(s, "weather_key", "normal")
        await world_svc._meta_set(s, "weather_until", (now_utc() + timedelta(seconds=7200)).isoformat())
        await world_svc._meta_set(s, "market", ",".join(f"{k}:0" for k in config.SEEDS))
        await world_svc._meta_set(s, "market_until", (now_utc() + timedelta(seconds=14400)).isoformat())

        plot.ready_at = now_utc() - timedelta(seconds=1)
        cash_before = u1.cash
        ok, alert, extra, (dq_d1, dq_l1), _notes = await farming.harvest_all(s, u1)
        gain_min = economy.crop_yield("teriak", 1, u1.level)
        check("برداشت موفق (بازه کیفیت ⭐ تا ⭐⭐⭐⭐⭐)",
              ok and cash_before + gain_min <= u1.cash <= cash_before + gain_min * 3,
              f"{u1.cash - cash_before} (پایه {gain_min})")
        check("پیام برداشت ستاره کیفیت داره", bool(extra) and "⭐" in extra and "💰 مجموع" in extra,
              (extra or "").replace("\n", " | ")[:130])

        # بذر جدید و کاشت مجدد برای تست کولدان
        await farming.add_seed_stock(s, u1.id, "teriak", 1)
        await farming.plant(s, u1, plot, "teriak")
        plot.ready_at = now_utc() - timedelta(seconds=1)
        ok, msg, _, _dq, _nn = await farming.harvest_all(s, u1)
        check("کولدان ۲ دقیقه برداشت جلوگیری می‌کنه", not ok and "2 دقیقه" in msg, msg)

        u1.last_harvest_at = now_utc() - timedelta(seconds=config.HARVEST_COOLDOWN_SECONDS + 5)
        ok, alert, extra, _dq2, _nn2 = await farming.harvest_all(s, u1)
        check("بعد از کولدان برداشت میشه", ok)

        # ── گیت لول فروشگاه ──
        u1.level = 1
        ok, msg = await shop_svc.purchase(s, u1, "weap", "viperx")
        check("سلاح قفل‌روی‌لول رد میشه", not ok and "لول" in msg)
        u1.cash = 500000
        u1.iron = 1000
        ok, msg = await shop_svc.purchase(s, u1, "weap", "deagle")
        u1.level = 5
        check("سلاح بالاتر از لول قفله", not ok)
        u1.level = 15
        u1.iron = 0
        ok, msg = await shop_svc.purchase(s, u1, "weap", "deagle")
        check("بدون آهن سلاح خریده نمیشه", not ok and "آهن" in msg, msg)
        u1.iron = 1000
        iron_b = u1.iron
        ok, msg = await shop_svc.purchase(s, u1, "weap", "deagle")
        check("با لول کافی خریده", ok)
        check("آهن سلاح از انبار کم شد", u1.iron == iron_b - config.WEAPONS["deagle"]["iron"], str(u1.iron))
        ok, msg = await shop_svc.purchase(s, u1, "weap", "deagle")
        check("خرید تکراری سلاح رد میشه", not ok)

        ok, msg = await shop_svc.purchase(s, u1, "arm", "legend")
        check("زره افسانه‌ای خریده", ok)

        # ── سگ‌ها (فلو جدید: اول اسم می‌پرسه → فاکتور تایید → اونجا پول کم میشه) ──
        cash_before = u1.cash
        ok, msg = await shop_svc.purchase(s, u1, "dog", "doberman")
        check("شروع فلو سگ و درخواست اسم", ok and "اسم" in msg, msg)
        check("هنوز پولی کم نشده و سگی ساخته نشده",
              u1.cash == cash_before
              and u1.pending_action == "dogname" and u1.pending_value == "doberman"
              and len(await dog_svc.get_user_dogs(s, u1.id)) == 0)
        check("خرید سگ دوم قبل اسم دادن بلاکه", (await shop_svc.purchase(s, u1, "dog", "blackwolf"))[0] is False)

        # ولیدیشن اسم سگ با check_dog_name (خطا pending رو نگه می‌داره)
        ok_n, disp, why = dog_svc.check_dog_name([], "ب")
        check("اسم خیلی کوتاه رد میشه", not ok_n and "کوتاه" in why, why)
        ok_n2, disp2, why2 = dog_svc.check_dog_name([], "اصغر:به")
        check("اسم با کاراکتر عجیب رد میشه", not ok_n2 and "کاراکتر" in why2, why2)
        ok_n3, disp3, _ = dog_svc.check_dog_name([], " اصغر ")
        check("اسم درست قبوله و تمیز برمی‌گرده", ok_n3 and disp3 == "اصغر", str(disp3))
        u1.pending_action = None
        u1.pending_value = None
        cash_before = u1.cash
        ok, msg = await dog_svc.buy_dog(s, u1, "doberman", custom_name="اصغر")
        check("اسم سگ بعد از تایید فاکتور ثبت شد و پول همونجا کم شد",
              ok and "اصغر" in msg and u1.cash == cash_before - config.DOGS["doberman"]["price"], msg)
        check("متن خرید سگ قالب جدیده: رفیق جدیدت شد + واکنش به اسم",
              "اصغر رفیق جدیدت شد" in msg and "باهوشه و به اسمش واکنش میده" in msg
              and "کافیه بگی «تریاکی آمار اصغر»" in msg, msg[:110])
        check("pending پاک شد", u1.pending_action is None and u1.pending_value is None)
        ok, msg = await dog_svc.buy_dog(s, u1, "doberman", custom_name="تکراری")
        check("نژاد تکراری از همونجا رد میشه", not ok, msg)
        ok, msg = await dog_svc.buy_dog(s, u1, "pitbull", custom_name="اصغر")
        check("اسم تکراری سگ رد میشه", not ok and "یه سگ دیگه" in msg, msg)

        # لغو وسط فلو، چون هنوز پولی کم نشده چیزی هم برنمی‌گرده
        cash_before = u1.cash
        ok, _ = await dog_svc.hold_dog(s, u1, "kangal")
        check("هولد کانگال بدون کسر پول", ok and u1.cash == cash_before)
        msg = await dog_svc.cancel_pending(s, u1)
        check("لغو خرید سگ فقط اکشن رو پاک می‌کنه",
              u1.cash == cash_before and u1.pending_action is None and "خرید سگ لغو شد" in msg, msg)

        ok, msg = await dog_svc.buy_dog(s, u1, "blackwolf", custom_name="شبح")
        check("گرگ سیاه با اسم شبح", ok and "شبح" in msg, msg)
        check("نژاد تکراری رد میشه", (await shop_svc.purchase(s, u1, "dog", "doberman"))[0] is False)
        nok, msg = await shop_svc.purchase(s, u1, "dog", "shepherd")
        check("حداکثر ۲ سگ، سومیش بلاکه", not nok and "2" in msg, msg)

        dogs = await dog_svc.get_user_dogs(s, u1.id)
        check("دو سگ ثبت شد با اسم دلخواه", {d.dog_key: d.name for d in dogs} == {"doberman": "اصغر", "blackwolf": "شبح"})
        check("پیدا کردن سگ با اسم برای «آمار اصغر»",
              dog_svc.find_my_dog(dogs, "اصغر").dog_key == "doberman"
              and dog_svc.find_my_dog(dogs, "شب").dog_key == "blackwolf"
              and dog_svc.find_my_dog(dogs, "ناشناس") is None)

        # ── قالب دقیق کارت آمار سگ ──
        from handlers import dogs as dogs_h
        dob_card = dogs_h._dog_card_text(u1, dogs[0])
        check("کارت آمار سگ قالب دقیق داره",
              all(x in dob_card for x in ["🐕 آمار", "🐾 نژاد", "⭐ لول", "✨تجربه", "💪 قدرت حمله", "🎖", "🍖 اصغر هنوز گرسنشه"])
              and ("▰" in dob_card or "▱" in dob_card), dob_card.replace("\n", " | ")[:140])
        check("کارت سگ دیگه شخصیت نداره و خط ویژگی بدون ایموجی خود ویژگی و با دو نقطه‌ست",
              "💫 شخصیت" not in dob_card and "شخصیت" not in dob_card
              and "🎖 ویژگی: دفاع بیشتر 1%" in dob_card,
              dob_card.replace("\n", " | ")[:200])
        check("آیتم سگ‌ها اسم‌شون فقط نژاده",
              all(config.DOGS[k]["name"] == config.DOGS[k]["breed"] for k in config.DOGS),
              str([d["name"] for d in config.DOGS.values()]))
        wolf = next(d for d in dogs if d.dog_key == "blackwolf")
        dob = next(d for d in dogs if d.dog_key == "doberman")
        check("سگ لول ۱ شروع می‌کنه", wolf.level == 1 and wolf.xp == 0)
        check("قدرت پایه سگ فقط از نژاد و لولش میاد (شخصیت حذف شده)",
              dog_svc.dog_attack(dob) == config.DOGS["doberman"]["attack"],
              str(dog_svc.dog_attack(dob)))
        check("دیگه هیچ سگی شخصیت نمی‌گیره (موقع خرید نول می‌مونه)",
              dob.personality is None and wolf.personality is None,
              f"{dob.personality}/{wolf.personality}")

        # ── غذا دادن ──
        u1.cash = 100000
        check("هر سگ روزی ۵ غذا داره", dog_svc.feeds_left(wolf) == config.DOG_FEED_PER_DAY)

        notes_all = []
        for _ in range(5):
            ok, msg, notes = await dog_svc.feed_dog(s, u1, wolf, "gold")
            assert ok, msg
            notes_all.extend(notes)
        check("۵ بار غذا اوکیه", True)
        check("ششمی رد میشه (سقف روزانه خود همون سگ)", dog_svc.feeds_left(wolf) == 0)
        ok, msg, _ = await dog_svc.feed_dog(s, u1, wolf, "gold")
        check("غذای ششم خطا میده با متن «سیر شده»", not ok and "سیر شده" in msg, msg)
        check("سهمیه سگ دیگه جداست (اصغر هنوز جا داره)", dog_svc.feeds_left(dob) == config.DOG_FEED_PER_DAY)

        xp_expect = 5 * config.DOG_FOODS["gold"]["xp"]
        check("xp سگ از غذا رفت بالا و لول‌آپ خورد", wolf.level > 1 and notes_all, f"lvl={wolf.level} xp={wolf.xp} ({xp_expect} داده بودیم)")

        atk_before = dog_svc.dog_attack(wolf)
        check("قدرت سگ با لول بیشتر میشه", atk_before > config.DOGS["blackwolf"]["attack"])

        # ریست سهمیه غذا ساعت ۱۲ شب به‌وقت ایران
        wolf.feed_day = "2000-01-01"
        check("فردا (به‌وقت ایران) سهم غذا ریست میشه", dog_svc.feeds_left(wolf) == config.DOG_FEED_PER_DAY)

        # ── استت نبرد با سگ و بونس لول آیتم ──
        keys = await users.get_item_keys(s, u1.id)
        u2.level = 5
        atk, dfn = combat.combat_stats(u1, keys, dogs)
        base_atk = config.ATK_BASE + config.ATK_PER_LEVEL * u1.level
        weap_eff = int(config.WEAPONS["deagle"]["attack"] * (1 + config.LEVEL_ITEM_BONUS * (u1.level - 1)))
        expected = base_atk + weap_eff + dog_svc.dog_attack(dob) + dog_svc.dog_attack(wolf)
        check("حمله = پایه + سلاح + سگ‌ها", atk == expected, f"{atk} vs {expected}")

        # ── بونس سرقت گرگ و نصف زره ──
        wolf.level = config.DOG_MAX_LEVEL
        bonus = dog_svc.rare_steal_bonus(dogs)
        check("غرامت گرگ در لول مکس ۱۰%ه", abs(bonus - config.RARE_DOG_STEAL_MAX) < 1e-9, f"{bonus:.2%}")
        wolf.level = 2
        check("بونس گرگ با لول کمتره", abs(dog_svc.rare_steal_bonus(dogs) - config.RARE_DOG_STEAL_MAX * 2 / config.DOG_MAX_LEVEL) < 1e-9)
        wolf.level = config.DOG_MAX_LEVEL
        check("کاهش دفاع گرگ تو لول مکس ۳۰%ه", abs(dog_svc.rare_defense_cut(dogs) - config.RARE_DOG_DEF_CUT_MAX) < 1e-9, f"{dog_svc.rare_defense_cut(dogs):.2%}")
        wolf.level = 2
        check("کاهش دفاع گرگ با لول کمتره", abs(dog_svc.rare_defense_cut(dogs) - 0.06) < 1e-9)
        check("بدون گرگ کاهش دفاع نیس", dog_svc.rare_defense_cut([]) == 0)
        check("غرامت گرگ ۱۰%ه نه ۱۵%", config.RARE_DOG_STEAL_MAX == 0.10)
        wolf.level = 6
        rl6 = dog_svc.rare_ability_lines(wolf)
        check("متن قابلیت گرگ با لول مقیاس میشه (تو لول 6 عدد 18 و 6)",
              "🎖 دفاع حریف رو 18% کاهش میده" in rl6 and "🪙 غرامت جنگی رو 6% افزایش میده" in rl6,
              str(rl6))
        wolf.level = 2

        # ── غارت هر ضربه: درصد بر اساس دمیج نسبت به HP کامل حریف ──
        st, _ = battle_svc.steal_for_hit(40, 200, 10000, [], [], [])
        check("غارت = سقف × دمیج نسبت به HP",
              st == int(10000 * config.BATTLE_STEAL_MAX_PCT * 40 / 200), str(st))
        check("دمیج کمتر غارت کمتر", battle_svc.steal_for_hit(10, 200, 10000, [], [], [])[0] < st)
        st_full, _ = battle_svc.steal_for_hit(200, 200, 10000, [], [], [])
        check("غارت با دمیج کامل به سقف 5% میرسه",
              st_full == int(10000 * config.BATTLE_STEAL_MAX_PCT), str(st_full))
        st_leg, meta_leg = battle_svc.steal_for_hit(200, 200, 10000, [], ["legend"], [])
        check("زره افسانه‌ای غارت رو نصف می‌کنه",
              meta_leg["halved"] and abs(st_leg * 2 - st_full) <= 1, f"{st_leg} vs {st_full}")
        check("جیب خالی غارتی نداره", battle_svc.steal_for_hit(50, 200, 0, [], [], [])[0] == 0)
        st_cap, meta_cap = battle_svc.steal_for_hit(200, 200, 10000, [wolf], [], [])
        check("بونس گرگ اعمال میشه ولی سقف 5% حفظه",
              meta_cap["bonus"] > 0 and st_cap <= int(10000 * config.BATTLE_STEAL_MAX_PCT), str(st_cap))
        check("کانفیگ سقف غارت ضربه 5%", config.BATTLE_STEAL_MAX_PCT == 0.05)

        # ── HP: شروع ۲۰۰، هر لول +۲۰، لول‌های ۱۰ و ۲۰ مایلستون +۳۰، لول ۲۰ → ۶۰۰ ──
        check("لول 1 با 200 HP شروع می‌کنه", battle_svc.max_hp(1) == 200)
        check("هر لول 20 HP بیشتر (لول‌های 10 و 20 +30) و لول 20 مکس 600ه",
              battle_svc.max_hp(20) == 600 and battle_svc.max_hp(10) == 390
              and all(battle_svc.max_hp(i) - battle_svc.max_hp(i - 1) == (30 if i in (10, 20) else 20)
                      for i in range(2, 21)))
        check("جدول HP تو کانفیگ ۲۰ رده داره", len(config.HP_TABLE) == 20)
        check("سقف لول بازی ۲۰ه", config.MAX_LEVEL == 20)

        # ── دمیج نبرد HP: واریانس ۳۰٪ و قانون زیادی‌قوتی (کریتیکال خاموش که بازه الکی نشکنه) ──
        random.seed(7)
        _old_crit = config.BATTLE_CRIT_CHANCE
        config.BATTLE_CRIT_CHANCE = 0.0
        try:
            dms = [battle_svc.roll_damage(150, 100, 200)[0] for _ in range(300)]
        finally:
            config.BATTLE_CRIT_CHANCE = _old_crit
        ratio = 150 / (150 + 100)
        pct_exp = config.BATTLE_DMG_PCT_MIN + (config.BATTLE_DMG_PCT_MAX - config.BATTLE_DMG_PCT_MIN) * ratio
        raw_exp = 200 * pct_exp
        v30 = config.BATTLE_DMG_VARIANCE
        check("دمیج همیشه تو بازه واریانس 30% نوسان داره",
              all(round(raw_exp * (1 - v30)) <= d <= round(raw_exp * (1 + v30)) for d in dms)
              and max(dms) > min(dms), f"{min(dms)}..{max(dms)} (خام {raw_exp:.1f})")
        check("دفاع به اندازه نسبت قانون بزرگ‌تر، هیچ دمیجی نمی‌خوره",
              battle_svc.roll_damage(10, int(10 * config.BATTLE_NO_DAMAGE_DEF_RATIO), 200)[0] == 0)
        check("کانفیگ دمیج درصدی مکس HP و نسبت و واریانس",
              config.BATTLE_DMG_VARIANCE == 0.30 and config.BATTLE_NO_DAMAGE_DEF_RATIO == 3.0
              and config.BATTLE_DMG_PCT_MIN == 0.005 and config.BATTLE_DMG_PCT_MAX == 0.04)
        random.seed(21)
        _oc2 = config.BATTLE_CRIT_CHANCE
        config.BATTLE_CRIT_CHANCE = 0.0
        try:
            dms_w = [battle_svc.roll_damage(80, 200, 400)[0] for _ in range(200)]
            dms_s = [battle_svc.roll_damage(200, 50, 400)[0] for _ in range(200)]
        finally:
            config.BATTLE_CRIT_CHANCE = _oc2
        check("دمیج بین کف و سقف درصدی مکس HP قربانی می‌چرخه و قوی‌تر بودن بیشتر می‌زنه",
              min(dms_w) >= round(400 * config.BATTLE_DMG_PCT_MIN * (1 - v30))
              and max(dms_s) <= round(400 * config.BATTLE_DMG_PCT_MAX * (1 + v30))
              and sum(dms_s) > sum(dms_w) * 2, f"{min(dms_w)}..{max(dms_s)}")

        # ── ضربه کامل نبرد HP (سرویس) ──
        from models import InventoryItem
        s.add(InventoryItem(user_id=u2.id, item_key="legend"))
        await s.flush()

        u1.energy = config.MAX_ENERGY
        u1.last_attack_at = None
        u2.cash = 50000
        u2.hp = battle_svc.max_hp(u2.level)
        u2.dead_until = None
        hp_b, cash_t = u2.hp, u2.cash
        res = await battle_svc.execute_hit(s, u1, u2)
        check("ضربه انجام شد و نتیجه کامله",
              res["ok"] and not res.get("nodmg") and res["dmg"] > 0, str(res))
        check("HP هدف به اندازه دمیج کم شد",
              u2.hp == hp_b - res["dmg"] and res["hp_now"] == u2.hp and res["hp_max"] == hp_b,
              f"{hp_b}->{u2.hp} dmg={res['dmg']}")
        check("غارت همون لحظه از جیب هدف کم شد",
              u2.cash == cash_t - res["steal"], f"{cash_t}->{u2.cash} steal={res['steal']}")
        check("تجربه همون لحظه داده شد", res["xp"] >= config.BATTLE_HIT_XP_BASE)
        check("تجربه حمله ۲۰% کمتر از نسخه قبلیه (پایه و ضریب دمیج و پی‌وی)",
              config.BATTLE_HIT_XP_BASE == 2.4 and config.BATTLE_HIT_XP_PER_DMG == 0.056
              and config.PV_ATTACK_WIN_XP == 20 and config.PV_ATTACK_LOSE_XP == 5
              and battle_svc.xp_for_hit(0) == 2 and battle_svc.xp_for_hit(100) == 8,
              f"{battle_svc.xp_for_hit(0)}/{battle_svc.xp_for_hit(100)}")

        # گرگ سیاه دفاع طرف رو خرد می‌کنه (مهاجم گرگ داره)
        check("گرگ سیاه دفاع طرف رو خرد می‌کنه", res["info"]["defcut"] > 0, str(res["info"]["defcut"]))

        # کولدان ۳۰ ثانیه فقط برای مهاجمه
        res_cd = await battle_svc.execute_hit(s, u1, u2)
        check("کولدان 30 ثانیه مهاجم فعاله",
              not res_cd["ok"] and res_cd["reason"] == "cooldown"
              and 0 < res_cd["left"] <= config.BATTLE_COOLDOWN_SECONDS, str(res_cd.get("left")))
        check("کانفیگ کولدان ۳۰ ثانیه", config.BATTLE_COOLDOWN_SECONDS == 30)
        u1.last_attack_at = now_utc() - timedelta(seconds=config.BATTLE_COOLDOWN_SECONDS + 1)
        u2.hp = battle_svc.max_hp(u2.level)
        res_ok2 = await battle_svc.execute_hit(s, u1, u2)
        check("بعد کولدان آزاده", res_ok2["ok"], str(res_ok2)[:80])

        # ── هیچ دمیجی وارد نمیشه وقتی حریف زیادی قویه ──
        w, _ = await users.get_or_create(s, tg(8860, "weakatt", "تازه‌کار"))
        d, _ = await users.get_or_create(s, tg(8861, "strongdef", "زره‌پوش"))
        d.level = 20
        d.hp = battle_svc.max_hp(20)
        s.add(InventoryItem(user_id=d.id, item_key="legend"))
        await s.flush()
        res_no = await battle_svc.execute_hit(s, w, d)
        check("حریف زیادی قوی هیچ دمیجی نمی‌خوره",
              res_no["ok"] and res_no.get("nodmg") and d.hp == battle_svc.max_hp(20), str(res_no)[:80])
        check("تلاش بی‌نتیجه هم انرژی و کولدان می‌سوزونه",
              w.energy < config.MAX_ENERGY and (await battle_svc.cooldown_left(s, w)) > 0)

        # ── شکست = ۱۰ دقیقه بیهوشی و زنده شدن خودکار با HP فول ──
        u1.energy = config.MAX_ENERGY
        u1.last_attack_at = None
        u2.hp = 1
        u2.dead_until = None
        w_b, l_b = u1.wins, u2.losses
        res_kill = await battle_svc.execute_hit(s, u1, u2)
        check("ضربه آخر حریف رو زمین زد", res_kill["ok"] and res_kill["killed"] and u2.hp == 0)
        check("شکست ۱۰ دقیقه بیهوشی میده",
              u2.dead_until is not None and 9 * 60 < battle_svc.dead_left(u2) <= 10 * 60,
              str(battle_svc.dead_left(u2)))
        check("کانفیگ بیهوشی ۶۰۰ ثانیه", config.BATTLE_DEAD_SECONDS == 600)
        check("برد و باخت فقط موقع شکست ثبت شد", u1.wins == w_b + 1 and u2.losses == l_b + 1)
        u1.energy = config.MAX_ENERGY
        u1.last_attack_at = None
        res_dead = await battle_svc.execute_hit(s, u1, u2)
        check("به بیهوش نمیشه حمله کرد",
              not res_dead["ok"] and res_dead["reason"] == "dead_target" and res_dead["left"] > 0)
        res_deadself = await battle_svc.execute_hit(s, u2, u1)
        check("بیهوش خودش هم نمی‌تونه حمله کنه",
              not res_deadself["ok"] and res_deadself["reason"] == "dead_self")
        u2.dead_until = now_utc() - timedelta(seconds=1)
        check("بعد پایان بیهوشی خودکار با HP فول زنده میشه",
              battle_svc.revive_if_due(u2) and u2.dead_until is None
              and u2.hp == battle_svc.max_hp(u2.level))

        # ── لول‌آپ بازیکن روی منحنی جدید ──
        lvl_before = u1.level
        notes = users.add_xp(u1, economy.xp_need(u1.level))
        check("لول‌آپ با منحنی Idle", u1.level == lvl_before + 1 and notes)

        await s.commit()

    # ═══ لول‌آپ تبریکی با جایزه (اسکناس + شارژ انرژی) ═══
    async with session_scope() as s:
        u2x = await users.get_by_tg(s, 1002)
        u2x.energy = 10
        cash_b, lvl_b = u2x.cash, u2x.level
        notes = users.add_xp(u2x, economy.xp_need(u2x.level))
        check("پیام تبریک لول‌آپ میاد", bool(notes) and "تبریک" in notes[0], notes[0][:60] if notes else "-")
        check("جایزه اسکناس لول‌آپ واریز شد",
              u2x.cash == cash_b + config.LEVEL_CASH_REWARD * u2x.level and u2x.level == lvl_b + 1,
              f"{u2x.cash - cash_b}")
        check("انرژی با لول‌آپ فول شارژ شد", u2x.energy == config.MAX_ENERGY)
        check("HP با لول‌آپ فول شد", u2x.hp == battle_svc.max_hp(u2x.level), str(u2x.hp))
        await s.commit()

    # ═══ متن دقیق کنده‌کاری (هندلر واقعی) ═══
    from handlers import mine as mine_h

    class _Msg(SimpleNamespace):
        async def reply_html(self, text, **k):
            self.calls.append(("reply", text, k))
            return self
        async def reply_document(self, document=None, filename=None, caption=None, **k):
            self.calls.append(("doc", caption, {"filename": filename}))
            return self

    def _text_update(txt, uid=7701, uname="miner", fname="ماینر"):
        msg = _Msg(text=txt, calls=[], chat_id=100)
        return SimpleNamespace(
            message=msg, effective_message=msg,
            effective_user=SimpleNamespace(id=uid, username=uname, first_name=fname),
            effective_chat=SimpleNamespace(type="private"), callback_query=None,
        )

    upd = _text_update("کنده کاری")
    await mine_h.mine_cmd(upd, None)
    mine_text = next(c[1] for c in upd.message.calls if "⛏️ کنده‌کاری" in c[1])
    check("متن کنده‌کاری قالب دقیق جدید داره",
          all(x in mine_text for x in ["⛏️ کنده‌کاری", "تی‌پوینت به دست آوردی", "تجربه گرفتی", "🪙 موجودی:",
                                       "خستت شده نیاز به 60ثانیه استراحت داری برای کنده کاری بعدی"]),
          mine_text.replace("\n", " | ")[:130])
    import re as _re_mine
    m_xp = _re_mine.search(r"✨ (\d+) تجربه گرفتی", mine_text)
    check("تجربه کنده‌کاری بین 1 تا 5 رندومه (شکار کمیاب تا دوبرابرش می‌کنه)",
          m_xp is not None and 1 <= int(m_xp.group(1)) <= config.MINE_XP_MAX * config.MINE_RARE_MULT,
          m_xp.group(0) if m_xp else "-")
    check("کانفیگ تجربه کنده‌کاری 1 تا 5",
          config.MINE_XP_MIN == 1 and config.MINE_XP_MAX == 5)
    upd2 = _text_update("کنده کاری")
    await mine_h.mine_cmd(upd2, None)
    cd_text = upd2.message.calls[-1][1]
    check("متن کولدان کنده‌کاری هم قالب جدیده",
          "⛏️ کنده‌کاری" in cd_text and "خستت شده نیاز به" in cd_text and "استراحت داری برای کنده کاری بعدی" in cd_text,
          cd_text.replace("\n", " | ")[:120])

    # ═══ هندلر pending، اسم سگ بعد از «خرید سگ» (قبل از فاکتور و پرداخت) ═══
    from handlers import pending as pending_h
    from handlers import textcmd as textcmd_h

    class _CBQ(SimpleNamespace):
        async def answer(self, *a, **k):
            self.calls.append(("answer", a, k))
        async def edit_message_text(self, text, **k):
            self.calls.append(("edit", text, k))

    def _cb_update(data, uid=7702, uname="pnd", fname="پندی"):
        q = _CBQ(data=data, message=SimpleNamespace(photo=None), calls=[])
        return SimpleNamespace(
            callback_query=q,
            effective_user=SimpleNamespace(id=uid, username=uname, first_name=fname),
            effective_chat=SimpleNamespace(type="private"),
        )

    upd = _text_update("رکس", uid=7702, uname="pnd", fname="پندی")
    await pending_h.capture(upd, None)
    check("بدون pending هیچ واکنشی نیس", not upd.message.calls)

    async with session_scope() as s:
        puser, _ = await users.get_or_create(s, tg(7702, "pnd", "پندی"))
        puser.level = 15
        puser.cash = 100000
        ok, _ = await dog_svc.hold_dog(s, puser, "pitbull")
        assert ok
        await s.commit()

    # اسم کوتاه خطا میده و pending سر جاش می‌مونه
    upd = _text_update("ب", uid=7702, uname="pnd", fname="پندی")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    async with session_scope() as s:
        puser = await users.get_by_tg(s, 7702)
        check("اسم کوتاه خطا میده و pending نمی‌پره",
              "کوتاه" in upd.message.calls[-1][1] and puser.pending_action == "dogname")

    # اسم درست → فاکتور خرید با نژاد، اسم و قیمت میاد (سگ هنوز ساخته نشده)
    async with session_scope() as s:
        puser = await users.get_by_tg(s, 7702)
        cash_before_name = puser.cash
    upd = _text_update("رکس", uid=7702, uname="pnd", fname="پندی")
    stopped = False
    try:
        await pending_h.capture(upd, None)
    except Exception as e:
        stopped = type(e).__name__ == "ApplicationHandlerStop"
    ftext, fmark = upd.message.calls[-1][1], upd.message.calls[-1][2].get("reply_markup")
    f_datas = [b.callback_data for row in fmark.inline_keyboard for b in row]
    check("فاکتور سگ بعد از اسم دادن میاد",
          stopped and all(x in ftext for x in ["🐕 خرید پیتبول", "🐾 نژاد پیتبول", "📛 اسم رکس", "💸 قیمت", "معامله‌ست؟"])
          and f_datas == ["txcf:dog:pitbull:7702:رکس", "txcl:7702"], ftext[:100])
    async with session_scope() as s:
        puser = await users.get_by_tg(s, 7702)
        pdogs = await dog_svc.get_user_dogs(s, puser.id)
        check("تا تایید فاکتور سگ ساخته نشده و پولی کم نشده",
              not pdogs and puser.pending_action is None and puser.cash == cash_before_name, str(puser.cash))

    # تایید فاکتور → اینجاس که پول کم میشه و سگ ساخته میشه
    updq = _cb_update("txcf:dog:pitbull:7702:رکس", uid=7702)
    await textcmd_h.tx_confirm_cb(updq, None)
    async with session_scope() as s:
        puser = await users.get_by_tg(s, 7702)
        pdogs = await dog_svc.get_user_dogs(s, puser.id)
        check("تایید فاکتور سگ رو داد و پول رو برداشت",
              len(pdogs) == 1 and pdogs[0].name == "رکس"
              and puser.cash == cash_before_name - config.DOGS["pitbull"]["price"],
              f"{puser.cash} (قبل {cash_before_name})")
        await s.commit()
    check("«آمار رکس» صداش می‌زنه", dog_svc.find_my_dog(pdogs, "رکس") is not None)

    # لغو وسط راه، چیزی از حساب کم نشده که برگرده
    async with session_scope() as s:
        puser = await users.get_by_tg(s, 7702)
        await dog_svc.hold_dog(s, puser, "doberman")
        cash_after_hold = puser.cash
        await s.commit()
    upd = _text_update("لغو", uid=7702, uname="pnd", fname="پندی")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    async with session_scope() as s:
        puser = await users.get_by_tg(s, 7702)
        check("لغو اسم سگ فقط اکشن رو پاک می‌کنه و پول دست نمی‌خوره",
              puser.pending_action is None and puser.cash == cash_after_hold
              and "خرید سگ لغو شد" in upd.message.calls[-1][1],
              str(upd.message.calls[-1][1]))

    # ═══ تیم: ساخت | جوین | بیو | آمار ═══
    async with session_scope() as s:
        o, _ = await users.get_or_create(s, tg(7705, "ownx", "رهبر"))
        m1, _ = await users.get_or_create(s, tg(7706, "mm1", "ممبر۱"))
        m2, _ = await users.get_or_create(s, tg(7707, "mm2", "ممبر۲"))
        o.level = 12
        o.cash = 60000
        m1.level = 4
        m2.level = 6

        ok, msg = await team_svc.can_create_team(s, o)
        check("لول ۱۲ و پول کافی می‌تونه بسازه", ok)
        o.level = 4
        check("زیر لول ۵ ساخت تیم بلاکه", (await team_svc.can_create_team(s, o))[0] is False)
        check("گیت ساخت تیم ۵ـه", config.TEAM_CREATE_MIN_LEVEL == 5)
        o.level = 12

        ok, name = await team_svc.create_team(s, o, "فوتبالیست‌ها")
        check("ساخت تیم فوتبالیست‌ها + هزینه کم شد",
              ok and name == "فوتبالیست‌ها" and o.cash == 60000 - config.TEAM_CREATE_COST, f"{name}/{o.cash}")
        check("عضو تیم ساخت دومی بلاکه", (await team_svc.create_team(s, o, "تیم دوم"))[0] is False)
        check("اسم تکراری بلاکه (حتی با فاصله عادی)",
              (await team_svc.create_team(s, m2, "فوتبالیست ها"))[0] is False)

        check("گیت لول عضویت تیم ۳ـه", config.TEAM_JOIN_MIN_LEVEL == 3)
        m1.level = 2
        check("زیر لول ۳ جوین بلاکه", (await team_svc.request_join(s, m1, "فوتبالیست‌ها"))[0] is False)
        m1.level = 3
        ok, name1 = await team_svc.request_join(s, m1, "فوتبالیست‌ها")
        check("جوین عضویت مستقیم نیس، درخواست ثبت میشه", ok and name1 == "فوتبالیست‌ها", str(name1))
        m1m = await team_svc.get_membership(s, m1.id)
        check("بعد درخواست هنوز عضو تیم نیس", m1m is None)
        ok, name2 = await team_svc.request_join(s, m2, "فوتبالیست ها")
        check("درخواست با فاصله عادی (نرمالایز اسم)", ok, str(name2))
        check("درخواست دوبل به همون تیم بلاکه", (await team_svc.request_join(s, m2, "فوتبالیست‌ها"))[0] is False)
        t0 = await team_svc.get_team_of(s, o.id)
        reqs = await team_svc.get_requests(s, t0.id)
        check("لیست درخواست‌ها دوتاست", len(reqs) == 2, str(len(reqs)))

        # قبول خلاف قوانین بدون مجوز نیس، خود سرویس عضویت و ظرفیت رو چک می‌کنه
        req1, u1_r = next(x for x in reqs if x[1].telegram_id == 7706)
        ok_acc, why_acc = await team_svc.accept_request(s, req1, u1_r)
        check("قبول درخواست ممبر۱ عضوش می‌کنه", ok_acc and (await team_svc.get_membership(s, m1.id)) is not None)
        req2, u2_r = next(x for x in reqs if x[1].telegram_id == 7707)
        ok_acc2, _ = await team_svc.accept_request(s, req2, u2_r)
        check("قبول درخواست ممبر۲ هم عضوش می‌کنه", ok_acc2 and (await team_svc.get_membership(s, m2.id)) is not None)
        reqs2 = await team_svc.get_requests(s, t0.id)
        check("بعد قبول صف خالیه", len(reqs2) == 0)

        check("بیو رو فقط رهبر می‌ذاره", (await team_svc.set_bio(s, o, "بهترین تیم محله 🏆"))[0] is True
              and (await team_svc.set_bio(s, m1, "x"))[0] is False)

        team = await team_svc.get_team_of(s, o.id)
        data = await team_svc.team_stats_data(s, team)
        check("آمار تیم: ۳ عضو و رهبر درست",
              data["count"] == 3 and data["owner_name"] == "رهبر" and team.bio == "بهترین تیم محله 🏆",
              f"{data['count']}/{data['owner_name']}")
        check("تیم تو پروفایل اسمش دیده میشه", team.name == "فوتبالیست‌ها")
        team_id = team.id
        check("ظرفیت تیم لول ۱ ده نفره", team_svc.team_capacity(team) == 10)
        check("جدول ظرفیت دقیقه: لول ۲ = ۱۲ و لول ۱۰ = ۳۰",
              team_svc.team_capacity(SimpleNamespace(level=2)) == 12
              and team_svc.team_capacity(SimpleNamespace(level=10)) == 30)
        check("جدول ظرفیت وسط‌ها: لول ۵ = ۱۸ و لول ۶ = ۲۱",
              team_svc.team_capacity(SimpleNamespace(level=5)) == 18
              and team_svc.team_capacity(SimpleNamespace(level=6)) == 21)
        check("بالاتر از جدول همون آخری می‌مونه",
              team_svc.team_capacity(SimpleNamespace(level=15)) == 30)
        check("تیم تازه لول ۱ و xp صفره", (team.level or 1) == 1 and (team.xp or 0) == 0)
        await s.commit()

    # ═══ 👑 مدیریت تیم: درخواست عضویت | قبول/رد | اخراج | ادمین ═══
    from handlers import team as team_h5
    from keyboards import keyboards as kb_t5

    class _TQ(SimpleNamespace):
        async def answer(self, *a, **k):
            self.calls.append(("answer", a, k))
        async def edit_message_text(self, text, **k):
            self.calls.append(("edit", text, k))

    def _tfake(data, uid):
        q = _TQ(data=data, message=SimpleNamespace(photo=None), calls=[])
        async def _qreply(text, **k):
            q.calls.append(("reply", text, k))
        q.message.reply_html = _qreply
        return SimpleNamespace(
            callback_query=q,
            effective_message=q.message,
            effective_user=SimpleNamespace(id=uid, username="x", first_name="ایکس"),
            effective_chat=SimpleNamespace(type="private"),
        )

    def _tgroup(txt, uid, uname, fname):
        msg = _Msg(text=txt, calls=[], chat_id=-8451, message_id=976)
        return SimpleNamespace(
            message=msg, effective_message=msg,
            effective_user=SimpleNamespace(id=uid, username=uname, first_name=fname),
            effective_chat=SimpleNamespace(type="supergroup", id=-8451), callback_query=None,
        )

    class _TBot:
        def __init__(self):
            self.sent = []
        async def send_message(self, chat_id, text, **k):
            self.sent.append((chat_id, text))

    tctx = SimpleNamespace(bot=_TBot())

    # ── سرچ فازی عضو داخل تیم ──
    async with session_scope() as s:
        k1, _ = await users.get_or_create(s, tg(7710, "vqur", "قربانی تیم"))
        k1.level = 5
        t0 = await team_svc.get_team_of(s, (await users.get_by_tg(s, 7705)).id)
        from models import TeamMember as _TM, TeamRequest as _TR
        s.add(_TM(team_id=t0.id, user_id=k1.id, role="member"))
        await s.commit()
        hit_id = await team_svc.find_team_member(s, t0.id, "7710")
        hit_un = await team_svc.find_team_member(s, t0.id, "@vqur")
        hit_name = await team_svc.find_team_member(s, t0.id, "قربانی")
        hit_part = await team_svc.find_team_member(s, t0.id, "ربان")
        check("سرچ عضو با آیدی و یوزرنیم و اسم و بخشی از اسم",
              all(h is not None and h[1].telegram_id == 7710 for h in (hit_id, hit_un, hit_name, hit_part)))
        check("سرچ مزخرف هیچی نمیاره", (await team_svc.find_team_member(s, t0.id, "xyznosuch")) is None)

        # ── قوانین اخراج و ادمین ──
        me_o = await team_svc.get_membership(s, (await users.get_by_tg(s, 7705)).id)
        t_m = await team_svc.get_membership(s, k1.id)
        okk, _ = team_svc.can_kick(me_o, t_m)
        check("رهبر می‌تونه عضو عادی رو اخراج کنه", okk)
        m_admin = await team_svc.get_membership(s, k1.id)
        m_admin.role = "admin"
        me2 = await team_svc.get_membership(s, (await users.get_by_tg(s, 7706)).id)
        me2.role = "admin"
        okk2, why2 = team_svc.can_kick(me2, m_admin)
        check("مدیر نمی‌تونه مدیر دیگه رو اخراج کنه", not okk2 and "رهبر" in why2)
        me2.role = "member"
        m_admin.role = "member"
        okk3, _ = team_svc.can_kick(me2, me_o)
        check("رهبر که اخراج نمیشه", not okk3)
        await s.commit()

    # ── کیبورد تیم: دکمه مدیریت فقط جلوی رهبر و مدیر ──
    kk_owner = kb_t5.team_kb(is_owner=True, is_manager=True)
    kk_member = kb_t5.team_kb()
    kk_admin = kb_t5.team_kb(is_manager=True)
    d_owner = [b.callback_data for row in kk_owner.inline_keyboard for b in row]
    d_member = [b.callback_data for row in kk_member.inline_keyboard for b in row]
    d_admin = [b.callback_data for row in kk_admin.inline_keyboard for b in row]
    check("دکمه 👑 مدیریت تیم فقط مال رهبر و مدیره",
          "team:mng" in d_owner and "team:mng" in d_admin
          and "team:mng" not in d_member and "team:disband" in d_owner and "team:leave" in d_admin)

    # ─«جوین تیم» پیام ثبت درخواست دقیق رو میده ──
    async with session_scope() as s:
        j1, _ = await users.get_or_create(s, tg(7712, "nwj1", "تازه‌کار۲"))
        j1.level = 3
        await s.commit()
    upd = _text_update("جوین تیم فوتبالیست‌ها", uid=7712, uname="nwj1", fname="تازه‌کار۲")
    await team_h5.join_team_text(upd, tctx)
    check("پیام ثبت درخواست عضویت دقیقه",
          upd.message.calls[-1][1] == "<b>📨 درخواست عضویت برای تیم «فوتبالیست‌ها» ارسال شد</b>\n\nمنتظر تأیید مدیران باش",
          upd.message.calls[-1][1][:80])

    # ── صفحه مدیریت و لیست درخواست‌ها ──
    upd = _tfake("team:mng", uid=7705)
    await team_h5.team_manage_cb(upd, tctx)
    mt = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    check("صفحه مدیریت تیم اسم تیم و شمار درخواست رو داره",
          "👑 مدیریت تیم «فوتبالیست‌ها»" in mt and "1 درخواست عضویت تو صفه" in mt, mt[:80])

    upd = _tfake("team:req", uid=7705)
    await team_h5.team_requests_cb(upd, tctx)
    rt5 = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    rkb5 = next((c[2].get("reply_markup") for c in upd.callback_query.calls if c[0] == "edit"), None)
    rdata5 = [b.callback_data for row in rkb5.inline_keyboard for b in row] if rkb5 else []
    async with session_scope() as s:
        t0 = await team_svc.get_team_of(s, (await users.get_by_tg(s, 7705)).id)
        rid12 = (await team_svc.get_requests(s, t0.id))[0][0].id
    check("لیست 📨 درخواست‌ها اسم و لول کاربر رو داره و دکمه قبول و رد",
          "تازه‌کار۲" in rt5 and "@nwj1" in rt5 and "لول 3" in rt5
          and f"treq:ok:{rid12}" in rdata5 and f"treq:no:{rid12}" in rdata5, rt5[:90])

    # ── عضو عادی نمی‌تونه صفحه مدیریت رو ببینه ──
    upd = _tfake("team:mng", uid=7706)
    await team_h5.team_manage_cb(upd, tctx)
    ans5 = next((c for c in upd.callback_query.calls if c[0] == "answer"), None)
    check("صفحه مدیریت برای عضو عادی قفله",
          ans5 is not None and ans5[1] and "فقط مال رهبر و مدیران" in str(ans5[1][0]), str(ans5)[:70])

    # ── قبول با دکمه: عضو میشه + دی‌ام به کاربر + الرت به مدیر ──
    nsent = len(tctx.bot.sent)
    upd = _tfake(f"treq:ok:{rid12}", uid=7705)
    await team_h5.team_request_resolve_cb(upd, tctx)
    ans5 = next((c for c in upd.callback_query.calls if c[0] == "answer"), None)
    async with session_scope() as s:
        m12 = await team_svc.get_membership(s, (await users.get_by_tg(s, 7712)).id)
    dm5 = tctx.bot.sent[-1] if tctx.bot.sent else (0, "")
    check("قبول با دکمه کاربر رو عضو می‌کنه و بهش دی‌ام میره",
          m12 is not None and len(tctx.bot.sent) == nsent + 1
          and dm5[0] == 7712 and "قبول شد" in dm5[1] and "فوتبالیست‌ها" in dm5[1]
          and ans5 is not None and ans5[1] and "عضو تیم شد" in str(ans5[1][0]), dm5[1][:70])

    # ── رد با دکمه: پاک میشه + دی‌ام رد ──
    async with session_scope() as s:
        j2, _ = await users.get_or_create(s, tg(7713, "nwj2", "ردشده"))
        j2.level = 3
        t0 = await team_svc.get_team_of(s, (await users.get_by_tg(s, 7705)).id)
        await team_svc.request_join(s, j2, "فوتبالیست‌ها")
        await s.commit()
        rid13 = (await team_svc.get_requests(s, t0.id))[0][0].id
    nsent = len(tctx.bot.sent)
    upd = _tfake(f"treq:no:{rid13}", uid=7705)
    await team_h5.team_request_resolve_cb(upd, tctx)
    dm5 = tctx.bot.sent[-1] if tctx.bot.sent else (0, "")
    async with session_scope() as s:
        m13 = await team_svc.get_membership(s, (await users.get_by_tg(s, 7713)).id)
        rq13 = await team_svc.get_requests(s, t0.id)
    check("رد با دکمه درخواست رو پاک می‌کنه و دی‌ام رد میره",
          m13 is None and len(rq13) == 0 and len(tctx.bot.sent) == nsent + 1
          and dm5[0] == 7713 and "رد شد" in dm5[1], dm5[1][:70])

    # ─«تیم درخواست @یوزر قبول» و قفل سطح دسترسی ──
    async with session_scope() as s:
        j3, _ = await users.get_or_create(s, tg(7714, "nwj3", "متنی"))
        j3.level = 3
        t0 = await team_svc.get_team_of(s, (await users.get_by_tg(s, 7705)).id)
        await team_svc.request_join(s, j3, "فوتبالیست‌ها")
        await s.commit()
    upd = _tgroup("تیم درخواست @nwj3 قبول", 7705, "ownx", "رهبر")
    await team_h5.team_request_text(upd, tctx)
    gtxt = upd.message.calls[-1][1]
    async with session_scope() as s:
        m14 = await team_svc.get_membership(s, (await users.get_by_tg(s, 7714)).id)
    check("تیم درخواست قبول متنی عضوش می‌کنه",
          m14 is not None and "عضو تیم شد" in gtxt, gtxt[:70])
    upd = _tgroup("تیم درخواست @nwj3 رد", 7706, "mm1", "ممبر۱")
    await team_h5.team_request_text(upd, tctx)
    check("عضو عادی دستور درخواست نداره",
          "فقط مال رهبر و مدیران تیمه" in upd.message.calls[-1][1])

    # ── ریجکت/اکسپت هم جوابه ──
    async with session_scope() as s:
        j4, _ = await users.get_or_create(s, tg(7716, "nwj4", "چهارم"))
        j4.level = 3
        t0 = await team_svc.get_team_of(s, (await users.get_by_tg(s, 7705)).id)
        await team_svc.request_join(s, j4, "فوتبالیست‌ها")
        await s.commit()
    nsent = len(tctx.bot.sent)
    upd = _tgroup("تیم درخواست @nwj4 ریجکت", 7705, "ownx", "رهبر")
    await team_h5.team_request_text(upd, tctx)
    check("ریجکت به زبان لاتین هم جوابه",
          "رد شد" in upd.message.calls[-1][1] and len(tctx.bot.sent) == nsent + 1)

    # ─«تیم کیک» صفحه تایید میاره و اجرا عضو رو حذف می‌کنه ──
    upd = _tgroup("تیم کیک @vqur", 7705, "ownx", "رهبر")
    await team_h5.team_kick_text(upd, tctx)
    ktxt = upd.message.calls[-1][1]
    kkb = upd.message.calls[-1][2].get("reply_markup")
    kd = [b.callback_data for row in kkb.inline_keyboard for b in row] if kkb else []
    async with session_scope() as s:
        t0 = await team_svc.get_team_of(s, (await users.get_by_tg(s, 7705)).id)
        mid10 = (await team_svc.get_membership(s, (await users.get_by_tg(s, 7710)).id)).id
    check("تیم کیک صفحه تایید عضو پیدا شد رو میده",
          "👤 عضو پیدا شد" in ktxt and "قربانی تیم" in ktxt and "واقعاً از تیم اخراج شود؟" in ktxt
          and kd == [f"tkick:{mid10}", "tkcl"], ktxt[:80])

    nsent = len(tctx.bot.sent)
    upd = _tfake(f"tkick:{mid10}", uid=7705)
    await team_h5.team_kick_execute(upd, tctx)
    ans5 = next((c for c in upd.callback_query.calls if c[0] == "answer"), None)
    async with session_scope() as s:
        m10 = await team_svc.get_membership(s, (await users.get_by_tg(s, 7710)).id)
    dm5 = tctx.bot.sent[-1] if tctx.bot.sent else (0, "")
    check("اخراج عضو حذفش می‌کنه و دی‌ام میره",
          m10 is None and len(tctx.bot.sent) == nsent + 1 and dm5[0] == 7710 and "اخراج شدی" in dm5[1]
          and ans5 is not None and ans5[1] and "اخراج شد" in str(ans5[1][0]), dm5[1][:60])

    # انصراف از اخراج برمی‌گردونه به صفحه مدیریت
    upd = _tfake("tkcl", uid=7705)
    await team_h5.team_kick_cancel(upd, tctx)
    rt5 = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    check("انصراف اخراج برمی‌گرده صفحه مدیریت", "👑 مدیریت تیم" in rt5, rt5[:60])

    # ── جریان pending دکمه 👢 اخراج عضو ──
    async with session_scope() as s:
        k2, _ = await users.get_or_create(s, tg(7715, "vqur2", "قربانی۲"))
        k2.level = 4
        t0 = await team_svc.get_team_of(s, (await users.get_by_tg(s, 7705)).id)
        s.add(_TM(team_id=t0.id, user_id=k2.id, role="member"))
        await s.commit()
    upd = _tfake("team:kick", uid=7705)
    await team_h5.team_kick_cb(upd, tctx)
    edit5 = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    check("دکمه اخراج عضو جست‌وجو می‌خواد", "آیدی عددی" in edit5 and "بخشی از اسم" in edit5, edit5[:80])

    from handlers import pending as pending_h5
    upd = _text_update("قربانی۲", uid=7705, uname="ownx", fname="رهبر")
    try:
        await pending_h5.capture(upd, tctx)
        _stopped = False
    except Exception:
        _stopped = True
    ctext = upd.message.calls[-1][1]
    async with session_scope() as s:
        o5 = await users.get_by_tg(s, 7705)
        pend5 = o5.pending_action
    check("pending اخراج با بخشی از اسم صفحه تایید رو میاره و pending پاک میشه",
          "👤 عضو پیدا شد" in ctext and "قربانی۲" in ctext and pend5 is None, ctext[:70])

    # مدیر نمی‌تونه مدیر رو اخراج کنه (رهبر می‌تونه)
    async with session_scope() as s:
        o_own = await users.get_by_tg(s, 7706)
        m_adm = await team_svc.get_membership(s, o_own.id)
        m_adm.role = "admin"
        o5 = await users.get_by_tg(s, 7715)
        m_t = await team_svc.get_membership(s, o5.id)
        m_t.role = "admin"
        await s.commit()
    upd = _tgroup("تیم کیک @vqur2", 7706, "mm1", "ممبر۱")
    await team_h5.team_kick_text(upd, tctx)
    check("مدیر نمی‌تونه مدیر دیگه رو اخراج کنه",
          "اخراج مدیر فقط با رهبره" in upd.message.calls[-1][1])
    async with session_scope() as s:
        m_adm = await team_svc.get_membership(s, (await users.get_by_tg(s, 7706)).id)
        m_adm.role = "member"
        m_t = await team_svc.get_membership(s, (await users.get_by_tg(s, 7715)).id)
        m_t.role = "member"
        await s.commit()

    # ─«تیم ادمین @یوزر» فقط با رهبره و رفت‌وبرگشته ──
    nsent = len(tctx.bot.sent)
    upd = _tgroup("تیم ادمین @mm1", 7705, "ownx", "رهبر")
    await team_h5.team_admin_text(upd, tctx)
    gtxt = upd.message.calls[-1][1]
    async with session_scope() as s:
        m_adm = await team_svc.get_membership(s, (await users.get_by_tg(s, 7706)).id)
    check("رهبر عضو رو مدیر می‌کنه و دی‌ام میره",
          m_adm is not None and m_adm.role == "admin" and "مدیر تیم شد" in gtxt
          and len(tctx.bot.sent) == nsent + 1 and tctx.bot.sent[-1][0] == 7706, gtxt[:60])
    upd = _tgroup("تیم ادمین @ownx", 7706, "mm1", "ممبر۱")
    await team_h5.team_admin_text(upd, tctx)
    check("مدیر نمی‌تونه مدیر بذاره (فقط رهبر)",
          "فقط رهبر می‌تونه مدیر بذاره" in upd.message.calls[-1][1])

    # مدیر تازه صفحه مدیریت رو می‌بینه
    upd = _tfake("team:mng", uid=7706)
    await team_h5.team_manage_cb(upd, tctx)
    rt5 = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    check("مدیر هم صفحه مدیریت رو می‌بینه", "👑 مدیریت تیم" in rt5, rt5[:50])

    # _tfake یوزرنیم ۷۷۰۶ رو x کرده بود، برش می‌گردونیم mm1
    async with session_scope() as s:
        (await users.get_by_tg(s, 7706)).username = "mm1"
        await s.commit()

    upd = _tgroup("تیم ادمین @mm1", 7705, "ownx", "رهبر")
    await team_h5.team_admin_text(upd, tctx)
    async with session_scope() as s:
        m_adm = await team_svc.get_membership(s, (await users.get_by_tg(s, 7706)).id)
    check("مدیریت گرفته هم میشه", m_adm is not None and m_adm.role == "member"
          and "دیگه مدیر نیس" in upd.message.calls[-1][1])

    # پاکسازی اعضای اضافه‌شده، تیم برای تست‌های بعدی دوباره ۳ نفره‌ست
    async with session_scope() as s:
        for tgid in (7712, 7714, 7715):
            u = await users.get_by_tg(s, tgid)
            m = await team_svc.get_membership(s, u.id)
            if m:
                await s.delete(m)
        await s.commit()
        t0 = await team_svc.get_team_of(s, (await users.get_by_tg(s, 7705)).id)
        n_back = await team_svc.member_count(s, t0.id)
        check("بعد تست مدیریت، تیم دوباره ۳ نفره‌ست", n_back == 3, str(n_back))

    # ═══ کوئست‌های روزانه گروهی ═══
    async with session_scope() as s:
        o = await users.get_by_tg(s, 7705)
        m1 = await users.get_by_tg(s, 7706)
        m2 = await users.get_by_tg(s, 7707)
        c1, c2, c3 = o.cash, m1.cash, m2.cash

        for i in range(24):
            r = await team_svc.record_kill(s, o if i % 2 == 0 else m1)
            assert r is None, i
        bank_qk = (await team_svc.get_team_of(s, o.id)).bank
        r = await team_svc.record_kill(s, m2)
        check("کوئست کشتن ۲۵ نفر با ضربه ۲۵ام کامل شد", r is not None and "کامل شد" in r, str(r)[:60])
        rw = config.TEAM_QUESTS[0]["reward"]
        check(f"جایزه {fa_num(rw)} تی‌پوینت به هر عضو رسید",
              o.cash == c1 + rw and m1.cash == c2 + rw and m2.cash == c3 + rw,
              f"{o.cash - c1}/{m1.cash - c2}/{m2.cash - c3}")
        check("جایزه بانک تیم کوئست کشتار رسید",
              (await team_svc.get_team_of(s, o.id)).bank == bank_qk + config.TEAM_QUESTS[0]["bank_reward"],
              f"{config.TEAM_QUESTS[0]['bank_reward']}")
        r = await team_svc.record_kill(s, o)
        check("کوئست یک روز دوباره جایزه نمیده", r is None)

        for i in range(9):
            r = await team_svc.record_harvest(s, m2 if i % 2 else o, 1)
            assert r is None, i
        bank_qh = (await team_svc.get_team_of(s, o.id)).bank
        r = await team_svc.record_harvest(s, m1, 1)
        rw2 = config.TEAM_QUESTS[1]["reward"]
        check("کوئست برداشت ۱۰ محصول کامل شد", r is not None and "برداشت" in r, str(r)[:60])
        check("جایزه برداشت هم به همه رسید", m1.cash == c2 + rw + rw2 and o.cash == c1 + rw + rw2)
        check("جایزه بانک تیم کوئست برداشت رسید",
              (await team_svc.get_team_of(s, o.id)).bank == bank_qh + config.TEAM_QUESTS[1]["bank_reward"])

        team = await team_svc.get_team_of(s, o.id)
        # ۲۶ برد (۲۵ کوئستی + ۱ تست «دوباره جایزه نمیده») + ۱۰ برداشت
        expected_pts = 26 * config.TEAM_POINT_KILL + 10 * config.TEAM_POINT_HARVEST
        check("امتیاز تیم با برد و برداشت جمع شد", team.points == expected_pts, str(team.points))
        check("امتیاز هفته هم همینه (قبل ریست)", team.week_points == expected_pts)

        daily = await team_svc._daily(s, team_id)
        check("استعلام کوئست هر دو رو done نشون میده",
              all(q["done"] for q in team_svc.quests_view(daily)),
          str(team_svc.quests_view(daily)))
        await s.commit()

        # هوک واقعی execute_hit → زمین زدن حریف روی کوئست کشتار تیم حساب میشه
        kills_b = (await team_svc._daily(s, team_id)).kills
        victim = await users.get_by_tg(s, 1002)
        # زره‌های تست‌های قبلیش رو برمی‌داریم که ضربه حتماً بخوره
        from models import InventoryItem as _Inv
        for vi in (await s.execute(select(_Inv).where(_Inv.user_id == victim.id))).scalars().all():
            await s.delete(vi)
        await s.flush()
        o.energy = config.MAX_ENERGY
        o.last_attack_at = None
        victim.hp = 1  # یه ضربه با زمین زدنش کافیه
        victim.dead_until = None
        res = await battle_svc.execute_hit(s, o, victim)
        assert res["ok"] and res.get("killed"), str(res)
        kills_a = (await team_svc._daily(s, team_id)).kills
        check("زمین زدن تو نبرد واقعی روی کوئست تیم حساب شد", kills_a == kills_b + 1, f"{kills_b}→{kills_a}")
        # قربانی رو سرپا میاریم که تست‌های بعدی به مشکل نخورن
        victim.dead_until = None
        victim.hp = battle_svc.max_hp(victim.level)
        await s.commit()

    # ═══ کنده‌کاری تیمی (استخراج، ۷۰% اعضا) ═══
    check("فرمول نیاز ۷۰% اعضا",
          [team_svc.mine_needed(m) for m in (1, 2, 3, 7, 10)] == [3, 3, 3, 5, 7],
          str([team_svc.mine_needed(m) for m in (1, 2, 3, 7, 10)]))

    async with session_scope() as s:
        solo, _ = await users.get_or_create(s, tg(7799, "solo", "سولو"))
        solo.level = 12
        solo.cash = 50000
        ok, _ = await team_svc.create_team(s, solo, "تنهایی‌ها")
        team_svc.TEAM_MINE_SESSIONS.clear()
        r = await team_svc.team_mine_join(s, solo)
        check("تیم زیر ۳ نفره نمی‌تونه استخراج کنه", r["status"] == "too_few", r["status"])
        await s.commit()

    async with session_scope() as s:
        o = await users.get_by_tg(s, 7705)
        m1 = await users.get_by_tg(s, 7706)
        m2 = await users.get_by_tg(s, 7707)
        team = await team_svc.get_team_of(s, o.id)
        bank_b = team.bank

        team_svc.TEAM_MINE_SESSIONS.clear()
        r1 = await team_svc.team_mine_join(s, o)
        check("استارت کنده‌کاری تیمی (نفر ۱ از ۳ لازم)",
              r1["status"] == "started" and r1["needed"] == 3 and r1["joined"] == 1, str(r1["status"]))
        r2 = await team_svc.team_mine_join(s, o)
        check("دوبار پیوستن همون نفر «قبلا پیوستی»", r2["status"] == "already")
        r3 = await team_svc.team_mine_join(s, m1)
        check("نفر دوم پیوست", r3["status"] == "joined" and r3["joined"] == 2)
        r4 = await team_svc.team_mine_join(s, m2)
        check("با نفر سوم تکمیل شد", r4["status"] == "completed", str(r4["status"]))
        check("جایزه رفت تو خزانه تیم",
              3 * config.TEAM_MINE_PER_MIN <= r4["reward"] <= 3 * config.TEAM_MINE_PER_MAX
              and team.bank == bank_b + r4["reward"] and r4["bank"] == team.bank,
              f"reward={r4['reward']}")
        r5 = await team_svc.team_mine_join(s, o)
        check("بعد تکمیل کولدان فعاله", r5["status"] == "cooldown" and r5["left"] > 0)
        await s.commit()

    # متن پیوستن دقیقاً مثل فرمول کاربر: «۷ نفر از ۸ نفر … ۱ نفر تا تکمیل»
    from handlers import team as team_h
    fake_res = {"team": SimpleNamespace(name="فوتبالیست‌ها"), "joined": 6, "needed": 7, "member_count": 7, "expires_at": now_utc()}
    ptxt = team_h._mine_progress_text(fake_res)
    check("متن «6 نفر از 7 نفر به کنده‌کاری پیوستند / 1 نفر تا تکمیل»",
          "6 نفر از 7 نفر به کنده‌کاری پیوستند" in ptxt and "1 نفر تا تکمیل کنده‌کاری" in ptxt, ptxt[:120])
    fake_done = {"team": SimpleNamespace(name="فوتبالیست‌ها"), "reward": 900, "bank": 2000}
    dtxt = team_h._mine_complete_text(fake_done)
    check("پیام پاداش بعد از تکمیل میاد", "کامل شد" in dtxt and "خزانه" in dtxt, dtxt[:80])

    # ═══ بانک تیم + ساختمان‌ها + امتیاز هفتگی ═══
    async with session_scope() as s:
        o = await users.get_by_tg(s, 7705)
        m1 = await users.get_by_tg(s, 7706)
        team = await team_svc.get_team_of(s, o.id)

        # هزینه ساختمان از جدول رند و تصاعدیه (25000 شروع)
        check("هزینه ساختمان تصاعدیه و رنده",
              [team_svc.building_cost(i) for i in (1, 2, 3)] == sorted([team_svc.building_cost(i) for i in (1, 2, 3)])
              and team_svc.building_cost(1) == config.TEAM_BUILDING_PRICES[0] == 25000
              and all(p % 1000 == 0 for p in config.TEAM_BUILDING_PRICES), str(config.TEAM_BUILDING_PRICES))

        # واریز کمک مالی به بانک تیم
        m1.cash = 1000
        ok, msg = await team_svc.team_deposit(s, m1, 1200)
        check("واریز بیشتر از جیب رد میشه", not ok)
        bank_b = team.bank
        ok, msg = await team_svc.team_deposit(s, m1, 400)
        check("«تیم واریز 1200»، واریز عضو به بانک تیم", ok and team.bank == bank_b + 400 and m1.cash == 600, msg)
        ok, msg = await team_svc.team_deposit(s, m1, 0)
        check("واریز صفر رد میشه", not ok)

        # ارتقا فقط با رهبره و پولش از بانک تیم میره
        ok, msg = await team_svc.upgrade_building(s, m1, "atk")
        check("ارتقا با غیر رهبر بلاکه", not ok and "رهبر" in msg, msg)
        team.bank = 100
        ok, msg = await team_svc.upgrade_building(s, o, "atk")
        check("بانک کم ارتقا رو رد می‌کنه", not ok and "بانک" in msg, msg)
        team.bank = 30000
        bank_b = team.bank
        ok, msg = await team_svc.upgrade_building(s, o, "atk")
        check("ارتقای ساختمان حمله به لول ۱",
              ok and team.atk_bld == 1 and team.bank == bank_b - team_svc.building_cost(1), msg)
        team.bank = 40000  # شارژ خزانه برای ارتقای بعدی
        ok, msg = await team_svc.upgrade_building(s, o, "def")
        check("ارتقای ساختمان دفاع هم کار می‌کنه", ok and team.def_bld == 1, msg)
        check("بونس ساختمان حمله",
              abs(team_svc.atk_bonus(team) - config.TEAM_ATK_BONUS_PER_LEVEL) < 1e-9)
        # متن پروفایل تیم: تاریخ شمسی + ساختمان‌ها هرکدوم خط خودشون
        st_text = team_h._team_stats_text(await team_svc.team_stats_data(s, team))
        check("تاریخ تأسیس تیم تو پروفایل تیم شمسیه",
              "📅 تأسیس: 14" in st_text, st_text.splitlines()[-3:].__str__()[:200])
        check("ساختمان حمله و دفاع تیم دو خط جدا با درصد",
              "⚔️ حمله: Lv.1 (+3%)" in st_text and "🛡 دفاع: Lv.1 (+3%)" in st_text,
              st_text.replace("\n", " | ")[:260])
        check("هدر و بخش‌های پروفایل تیم سر جاش",
              all(x in st_text for x in ["🏴 تیم «فوتبالیست‌ها»", "👑 رهبر:", "👥 اعضا: 3/10",
                                         "<b>📊 آمار</b>", "<b>🎯 کوئست‌های امروز</b>", "🏦 خزانه:"]),
              st_text[:120])
        tb = await team_svc.top_teams_by_points(s, 5)
        check("لیدربرد بر اساس امتیاز مرتبه", tb and tb[0][0].points >= tb[-1][0].points)

        await s.commit()

    # بونس ساختمان تو نبرد واقعی اعماله (tbuff تو نتیجه)
    async with session_scope() as s:
        o = await users.get_by_tg(s, 7705)
        victim = await users.get_by_tg(s, 1002)
        o.energy = config.MAX_ENERGY
        o.last_attack_at = None
        victim.hp = battle_svc.max_hp(victim.level)
        victim.dead_until = None
        res_t = await battle_svc.execute_hit(s, o, victim)
        check("بونس ساختمان حمله تو نتیجه نبرد اومد",
              res_t["ok"] and res_t["info"]["tbuff"] > 0, str(res_t["info"].get("tbuff")))
        # قربانی سرپا بمونه برای تست‌های بعدی
        victim.dead_until = None
        await s.commit()

    # رول‌اور هفتگی: ۳ تیم اول جایزه می‌گیرن و امتیاز هفته ریست میشه
    async with session_scope() as s:
        o = await users.get_by_tg(s, 7705)
        team = await team_svc.get_team_of(s, o.id)
        team.week_points = 7777
        bank_b = team.bank
        await team_svc.meta_set(s, "week_key", "2000-W01")  # شبیه‌سازی هفته قدیمی
        # سطل مدال هفتگی اعضا رو برای هفته تموم‌شده پر کن (مبنای جدید رتبه‌بندی رول‌اور)
        members = await team_svc.get_members(s, team.id)
        for m in members:
            mu = await s.get(User, m.user_id)
            mu.medals = 300
            m.join_medals = 0
            mu.medals_week = 100
            mu.medals_week_id = "2000-W01"
        winners = await team_svc.maybe_weekly_rollover(s)
        check("رول‌اور اجرا شد چون هفته عوض شده", winners is not None and len(winners) >= 1)
        check("قهرمان رتبه ۱ جایزه‌شو گرفت تو بانک تیم",
              winners[0]["rank"] == 1 and winners[0]["team"].name == "فوتبالیست‌ها"
              and team.bank == bank_b + config.TEAM_WEEKLY_PRIZES[1],
              f"{team.bank - bank_b}")
        check("رتبه‌بندی رول‌اور بر اساس مدال هفته اعضاست",
              winners[0]["points"] == 3 * 100, str(winners[0]["points"]))
        check("امتیاز هفته ریست شد", team.week_points == 0)
        check("هفته جدید ذخیره شد", (await team_svc.meta_get(s, "week_key")) == team_svc.current_week_key())
        check("نتیجه هفته پیش ذخیره شد", "فوتبالیست‌ها" in (await team_svc.meta_get(s, "last_week_result") or ""))
        again = await team_svc.maybe_weekly_rollover(s)
        check("تو همون هفته دوباره رول‌اور نمیشه", again is None)
        await s.commit()

    # ═══ ترک / انحلال ═══
    async with session_scope() as s:
        ok, name = await team_svc.leave_team(s, await users.get_by_tg(s, 7707))
        check("ممبر ترک می‌کنه", ok and name == "فوتبالیست‌ها", str(name))
        ok, msg = await team_svc.leave_team(s, await users.get_by_tg(s, 7705))
        check("رهبر نمی‌تونه ترک کنه", not ok, msg)
        ok, name = await team_svc.disband_team(s, await users.get_by_tg(s, 7705))
        check("انحلال توسط رهبر", ok and name == "فوتبالیست‌ها")
        check("تیم دیگه وجود نداره", await team_svc.get_team_by_name(s, "فوتبالیست‌ها") is None)
        m1x = await users.get_by_tg(s, 7706)
        check("عضوها آزاد شدن", await team_svc.get_team_of(s, m1x.id) is None)
        await s.commit()

    # ═══ اسم تیم با pending، بعد فاکتور تایید ساخت (فلو جدید «ساخت تیم») ═══
    async with session_scope() as s:
        o = await users.get_by_tg(s, 7705)
        o.pending_action = "teamname"
        await s.commit()
    upd = _text_update("فوتبالیست‌ها ۲", uid=7705, uname="ownx", fname="رهبر")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    tftext, tfmark = upd.message.calls[-1][1], upd.message.calls[-1][2].get("reply_markup")
    tf_datas = [b.callback_data for row in tfmark.inline_keyboard for b in row]
    async with session_scope() as s:
        t2 = await team_svc.get_team_by_name(s, "فوتبالیست‌ها ۲")
        o = await users.get_by_tg(s, 7705)
        check("فاکتور ساخت تیم بعد از اسم دادن میاد و تیم هنوز ساخته نشده",
              t2 is None and o.pending_action == "teamcf" and o.pending_value == "فوتبالیست‌ها ۲"
              and "ساخت تیم «فوتبالیست‌ها ۲»" in tftext
              and tf_datas == ["teamcf:ok:7705", "teamcf:no:7705"], str(tf_datas))
        await s.commit()

    # غریبه نمی‌تونه تایید کنه
    updq = _cb_update("teamcf:ok:7705", uid=9999, uname="frn", fname="غریبه")
    await team_h.team_create_cb(updq, None)
    async with session_scope() as s:
        o = await users.get_by_tg(s, 7705)
        check("تایید ساخت تیم توسط غریبه بلاکه",
              updq.callback_query.calls and updq.callback_query.calls[0][0] == "answer"
              and not any(c[0] == "edit" for c in updq.callback_query.calls)
              and await team_svc.get_team_by_name(s, "فوتبالیست‌ها ۲") is None
              and o.pending_action == "teamcf")

    # لغو فاکتور، pending پاک میشه و تیمی ساخته نمیشه
    updq = _cb_update("teamcf:no:7705", uid=7705, uname="ownx", fname="رهبر")
    await team_h.team_create_cb(updq, None)
    async with session_scope() as s:
        o = await users.get_by_tg(s, 7705)
        check("لغو فاکتور ساخت تیم",
              o.pending_action is None
              and await team_svc.get_team_by_name(s, "فوتبالیست‌ها ۲") is None)

    # دوباره اسم می‌دیم و این بار تایید، تیم ساخته میشه و پول کم میشه
    async with session_scope() as s:
        o = await users.get_by_tg(s, 7705)
        o.pending_action = "teamname"
        o.cash = 100000  # ساخت تیم ۵۰هزارتایی شده، پولشو شارژ می‌کنیم
        cash_t_before = o.cash
        await s.commit()
    upd = _text_update("فوتبالیست‌ها ۲", uid=7705, uname="ownx", fname="رهبر")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    updq = _cb_update("teamcf:ok:7705", uid=7705, uname="ownx", fname="رهبر")
    await team_h.team_create_cb(updq, None)
    ed_ok = next((c for c in updq.callback_query.calls if c[0] == "edit"), None)
    async with session_scope() as s:
        t2 = await team_svc.get_team_by_name(s, "فوتبالیست‌ها ۲")
        o = await users.get_by_tg(s, 7705)
        check("تایید فاکتور تیم رو ساخت و هزینه رو برداشت",
              t2 is not None and o.pending_action is None
              and o.cash == cash_t_before - config.TEAM_CREATE_COST
              and ed_ok is not None and "ساخته شد" in ed_ok[1],
              f"{o.cash} (قبل {cash_t_before})")
        await s.commit()

    # اسم تکراری تو pending رد میشه و pending سر جاش می‌مونه
    async with session_scope() as s:
        o = await users.get_by_tg(s, 7705)
        o.pending_action = "teamname"
        await s.commit()
    upd = _text_update("فوتبالیست‌ها ۲", uid=7705, uname="ownx", fname="رهبر")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    async with session_scope() as s:
        o = await users.get_by_tg(s, 7705)
        check("اسم تکراری تیم خطا میده و pending می‌مونه",
              "از قبل هست" in upd.message.calls[-1][1] and o.pending_action == "teamname",
              upd.message.calls[-1][1][:80])
        o.pending_action = None
        o.pending_value = None
        await s.commit()

    # ═══ کیبوردها ═══
    from keyboards import keyboards as kb
    from telegram import InlineKeyboardMarkup

    async with session_scope() as s:
        u1 = await users.get_by_tg(s, 1001)
        plots = await farming.get_user_plots(s, u1.id)
        stock = await farming.get_stock(s, u1.id)
        keys = await users.get_item_keys(s, u1.id)
        dogs = await dog_svc.get_user_dogs(s, u1.id)

        kbs = [
            kb.main_menu_kb(), kb.confirm_kb("cf:x"), kb.home_kb(), kb.profile_kb(),
            kb.farm_kb(u1, plots, economy.plot_price(len(plots)), 1),
            kb.seeds_kb(u1, plots[0], stock),
            kb.shop_sections_kb(),
            kb.shop_weap_kb(u1, set(keys)), kb.shop_arm_kb(u1, set(keys)),
            kb.shop_seed_kb(u1, stock), kb.shop_dog_kb(u1, {d.dog_key for d in dogs}, len(dogs)),
            kb.shop_food_kb(),
            kb.my_dogs_kb(dogs),
            kb.heal_kb(), kb.rank_kb("week"), kb.team_top_kb("week"), kb.mine_kb(),
            kb.tx_confirm_kb("weap", "knife", 123),
            kb.bank_kb(u1), kb.team_bld_kb(SimpleNamespace(atk_bld=1, def_bld=2), True, u1.telegram_id),
            kb.team_bld_confirm_kb("atk", u1.telegram_id),
            kb.shelter_kb(u1), kb.casino_kb(), kb.caravan_kb(),
            kb.team_back_kb(), kb.team_mine_kb(), kb.team_bank_kb(),
            kb.release_confirm_kb(dogs[0].id, 424242), kb.dog_card_kb(dogs[0], 3),
            kb.dquests_kb(), kb.team_create_confirm_kb(424242),
        ]
        for k in kbs:
            assert isinstance(k, InlineKeyboardMarkup)
            for row in k.inline_keyboard:
                for b in row:
                    assert b.callback_data is None or len(b.callback_data.encode()) <= 64, b.callback_data
                    assert b.style in (None, "primary", "success", "danger"), b.style
        check(f"{len(kbs)} کیبورد ولیدیت شدن", True)
        styled = sum(1 for k in kbs for r in k.inline_keyboard for b in r if b.style)
        check("دکمه‌های رنگی فعالن", styled >= 20, f"{styled}")

    # ═══ بانک شخصی 🏦 ═══
    check("پارس مبلغ فارسی و لاتین", parse_amount("۱۲۰۰") == 1200 and parse_amount("1,200") == 1200
          and parse_amount("الکی") is None and parse_amount("0") is None)
    check("ظرفیت بانک با لول رشد می‌کنه",
          bank_svc.bank_capacity(1) == config.BANK_CAPS[0]
          and bank_svc.bank_capacity(5) == config.BANK_CAPS[-1]
          and bank_svc.bank_capacity(3) > bank_svc.bank_capacity(1))
    check("ظرفیت بانک دقیقاً همون جدول ۲۰تا ۵۰۰هزار",
          [bank_svc.bank_capacity(i) for i in range(1, 6)] == [20000, 50000, 100000, 200000, 500000])
    check("هزینه ارتقای بانک از جدول میاد و تصاعدیه",
          [bank_svc.bank_upgrade_price(i) for i in range(1, 5)] == [25000, 50000, 100000, 200000])
    check("گیت لول داشتن هر لول بانک",
          [bank_svc.bank_min_level(i) for i in range(1, 6)] == config.BANK_MIN_LEVELS
          and bank_svc.bank_min_level(2) == 4 and bank_svc.bank_min_level(5) == 16)

    async with session_scope() as s:
        b, _ = await users.get_or_create(s, tg(7711, "bnk", "بانکدار"))
        b.cash = 10000
        b.level = 1

        ok, msg = await bank_svc.deposit(s, b, 3000)
        check("واریز به بانک", ok and b.bank_balance == 3000 and b.cash == 7000, msg)
        ok, msg = await bank_svc.deposit(s, b, 0)
        check("واریز صفر رد", not ok)
        ok, msg = await bank_svc.deposit(s, b, 99999)
        check("واریز بیشتر از جیب رد", not ok)

        ok, msg = await bank_svc.withdraw(s, b, 1000)
        check("برداشت از بانک", ok and b.bank_balance == 2000 and b.cash == 8000, msg)
        ok, msg = await bank_svc.withdraw(s, b, 99999)
        check("برداشت بیشتر از موجودی بانک رد", not ok)

        # ظرفیت لول ۱ = 20,000، پر کردنش و رد بیشترش
        b.cash = 100000
        ok, msg = await bank_svc.deposit(s, b, 18000)
        check("تا سقف ظرفیت واریز میشه", ok and b.bank_balance == 20000, f"{b.bank_balance}")
        ok, msg = await bank_svc.deposit(s, b, 1)
        check("بیشتر از ظرفیت رد میشه", not ok and "ظرفیت" in msg or "پر" in msg, msg)

        # ارتقای بانک به لول خودت گره خورده (لول ۲ بانک، لول ۴ بازیکن می‌خواد)
        ok, msg = await bank_svc.upgrade_bank(s, b)
        check("ارتقا بدون لول کافی رد (لول ۴ می‌خواد بره لول ۲)", not ok and "لول" in msg, msg)
        b.level = 4
        cash_b = b.cash
        ok, msg = await bank_svc.upgrade_bank(s, b)
        check("ارتقا با لول کافی انجام شد",
              ok and b.bank_level == 2 and b.cash == cash_b - bank_svc.bank_upgrade_price(1), msg)
        ok, msg = await bank_svc.deposit(s, b, 1)
        check("بعد ارتقا ظرفیت بیشتر شده", ok)
        await s.commit()

    # ═══ پروفایل: سگ به تعداد + بانک ═══
    from handlers import profile as profile_h
    async with session_scope() as s:
        u1 = await users.get_by_tg(s, 1001)  # ۲ سگ داره (اصغر و شبح)
        cap = await profile_h._profile_caption(s, u1)
        check("پروفایل سگ‌ها رو فقط به تعداد میگه",
              "🐕 سگ 2 عدد" in cap and "اصغر" not in cap and "شبح" not in cap, cap[:120])
        check("خط بانک تو پروفایل هست", "🏦 بانک" in cap)
        check("تایم ایران از پروفایل برداشته شد (تاریخ عضویت کافیه)",
              "🕰 تایم ایران" not in cap and "📅 عضویت: 14" in cap)
        check("یوزرنیم خط خودشو داره", "🆔 @ali" in cap)
        check("لقب تو پروفایل میاد",
              "🏅 " in cap and any(t[2] in cap for t in config.TITLES), cap[:200])
        check("بخش‌های پروفایل با تیتر بولد سر جاش",
              all(x in cap for x in ["<b>💰 دارایی</b>", "<b>🏡 مزرعه</b>", "<b>🛡 تجهیزات</b>", "<b>⚔️ آمار</b>"]),
              cap[:250])
        check("خط زمین‌ها تو پروفایل هست (قالب جدید)",
              "🌱 زمین: 2\n🌾 در حال رشد: 0\n✅ آماده برداشت: 0" in cap, cap[:250])
        u_b = await users.get_by_tg(s, 7711)
        cap2 = await profile_h._profile_caption(s, u_b)
        check("بدون سگ: «بدون سگ»", "🐕 بدون سگ" in cap2)
        await s.commit()

    # ═══ فلو pending بانک (دکمه واریز → مبلغ با پیام بعدی) ═══
    async with session_scope() as s:
        puser = await users.get_by_tg(s, 7702)
        puser.pending_action = "bankdep"
        puser.pending_value = ""
        await s.commit()
    upd = _text_update("۳۰۰۰", uid=7702, uname="pnd", fname="پندی")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    async with session_scope() as s:
        puser = await users.get_by_tg(s, 7702)
        check("مبلغ فارسی به بانک واریز شد", puser.bank_balance == 3000 and puser.pending_action is None,
              str(puser.bank_balance))
        puser.pending_action = "bankwd"
        await s.commit()
    upd = _text_update("1000", uid=7702, uname="pnd", fname="پندی")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    async with session_scope() as s:
        puser = await users.get_by_tg(s, 7702)
        check("برداشت pending هم کار می‌کنه", puser.bank_balance == 2000, str(puser.bank_balance))
        # لغو اکشن بانک
        puser.pending_action = "bankdep"
        await s.commit()
    upd = _text_update("لغو", uid=7702, uname="pnd", fname="پندی")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    async with session_scope() as s:
        puser = await users.get_by_tg(s, 7702)
        check("لغو اکشن بانک پاکش می‌کنه", puser.pending_action is None)
        await s.commit()

    # ═══ ادمین ═══
    check("پارس ادمین‌ها", 1001 in config.ADMIN_IDS and 1003 in config.ADMIN_IDS and 1002 not in config.ADMIN_IDS,
          str(sorted(config.ADMIN_IDS)))

    # ═══ فرمت متن‌های نبرد HP (قالب دقیق کاربر) ═══
    from handlers import battle as battle_h
    txt = battle_h.hit_text(
        {"ok": True, "nodmg": False, "killed": False, "dmg": 64, "hp_now": 136, "hp_max": 200,
         "steal": 5000, "meta": {}, "xp": 8, "notes": []},
        "سارا",
    )
    check("متن ضربه قالب دقیق جدید رو داره",
          "<b>💥 به حریف «سارا» حمله کردی</b>" in txt
          and "🩸 64 دمیج وارد شد" in txt
          and "❤️ سلامت حریف 136 از 200" in txt
          and "💰 5,000 تی‌پوینت غارت کردی" in txt
          and "✨ 8 تجربه گرفتی" in txt
          and "☠️" not in txt
          and txt.replace("\n\n", "␤") == (
              "<b>💥 به حریف «سارا» حمله کردی</b>␤"
              "🩸 64 دمیج وارد شد\n❤️ سلامت حریف 136 از 200␤"
              "💰 5,000 تی‌پوینت غارت کردی\n✨ 8 تجربه گرفتی"), txt.replace("\n", " | ")[:240])

    txt_k = battle_h.hit_text(
        {"ok": True, "nodmg": False, "killed": True, "dmg": 40, "hp_now": 0, "hp_max": 200,
         "steal": 1200, "meta": {}, "xp": 6, "notes": []},
        "ممد",
    )
    check("ضربه آخر بلوک پایان دوئل رو هم میاره",
          "🩸 40 دمیج وارد شد" in txt_k
          and "<b>☠️ حریف «ممد» شکست خورد</b>" in txt_k
          and "🏆 دوئل به پایان رسید" in txt_k, txt_k.replace("\n", " | ")[-200:])

    txt_z = battle_h.hit_text(
        {"ok": True, "nodmg": False, "killed": False, "dmg": 40, "hp_now": 60, "hp_max": 200,
         "steal": 0, "meta": {}, "xp": 6, "notes": []},
        "ممد",
    )
    check("جیب خالی خط خودشو داره", "💰 جیب حریف خالی بود" in txt_z)

    txt_n = battle_h.nodmg_text("زره‌پوش")
    check("متن زیادی‌قوتی قالب دقیق کاربر",
          txt_n == "🛡 حریف «زره‌پوش» برای تو زیادی قدرتمنده\n"
                   "فعلاً نمی‌تونی بهش آسیبی بزنی\n"
                   "اول تجهیزاتت رو ارتقا بده یا یه حریف ضعیف‌تر پیدا کن", txt_n)

    txt_ds = battle_h.dead_self_text(540)
    check("متن بیهوشی مهاجم قالب دقیق",
          txt_ds == "💀 هنوز حالت جا نیومده\n9 دقیقه دیگه دوباره آماده نبرد میشی", txt_ds)
    txt_dt = battle_h.dead_target_text("سارا", 130)
    check("متن حمله به بیهوش قالب دقیق",
          txt_dt == "💀 حریف «سارا» مرده و تا 3 دقیقه دیگه زنده نمیشه\nیه هدف دیگه پیدا کن", txt_dt)

    from handlers import attack as attack_h
    check("متن راهنمای حمله و پنل شانسی پی‌وی",
          "حمله | شلیک | بنگ | پیو" in battle_h.ATTACK_GUIDE_TEXT
          and "هدف شانسی" in attack_h.PV_PANEL_TEXT)

    # ═══ دکمه‌های قفل قرمز + افزودن به گروه ═══
    from keyboards import keyboards as kb2
    async with session_scope() as s:
        low = User(telegram_id=9001, username="low", first_name="تازه‌کار", level=1)
        s.add(low)
        await s.flush()
        weap_kb = kb2.shop_weap_kb(low, set())
        locked_styles = [b.style for row in weap_kb.inline_keyboard for b in row if b.callback_data == "noop:lock"]
        check("آیتم‌های قفل شاپ قرمزن", len(locked_styles) >= 3 and all(st == "danger" for st in locked_styles))

        dog_kb = kb2.shop_dog_kb(low, set(), 0)
        dog_locked = [b.style for row in dog_kb.inline_keyboard for b in row if b.callback_data == "noop:lock"]
        check("قفل سگ‌ها هم قرمزه", len(dog_locked) >= 3 and all(st == "danger" for st in dog_locked))

        # سگ‌های من از شاپ حذف شده
        all_shop_datas = [b.callback_data for k in (kb2.shop_sections_kb(), kb2.shop_food_kb(), dog_kb)
                          for row in k.inline_keyboard for b in row]
        check("سگ‌های من تو شاپ نیس", "menu:dogs" not in all_shop_datas)

        kb2.BOT_USERNAME = "teriaky_bot"
        mm = kb2.main_menu_kb()
        urls = [b.url for row in mm.inline_keyboard for b in row if b.url]
        check("دکمه افزودن به گروه", any("startgroup=true" in u for u in urls), str(urls))
        mmd = [b.callback_data for row in mm.inline_keyboard for b in row if b.callback_data]
        check("دکمه‌های کوئست‌های روزانه و راهنما تو منوی اصلی",
              "menu:dquests" in mmd and "help:menu" in mmd, str(mmd))

        txk = kb2.tx_confirm_kb("weap", "knife", 424242)
        datas = [b.callback_data for row in txk.inline_keyboard for b in row]
        check("کیبورد تایید متنی owner داره", datas == ["txcf:weap:knife:424242", "txcl:424242"], str(datas))

        hk = kb2.heal_kb()
        hdatas = [b.callback_data for row in hk.inline_keyboard for b in row]
        htexts = [b.text for row in hk.inline_keyboard for b in row]
        hstyles = [b.style for row in hk.inline_keyboard for b in row if b.callback_data.startswith("heal:buy:")]
        check("کیبورد درمان سه آیتم + هوم داره",
              hdatas == ["heal:buy:band", "heal:buy:kit", "heal:buy:box", "menu:home"]
              and "🩹 باند کوچک" in htexts[0] and "💉 کیت درمان" in htexts[1] and "🏥 جعبه کمک‌های اولیه" in htexts[2]
              and "سلامت فول" in htexts[2]
              and all(st == "success" for st in hstyles), str(htexts))
        check("دکمه‌های درمان قالب «اسم | قیمت TP | سلامت» رو دارن",
              htexts[0] == "🩹 باند کوچک | 🪙 400 TP | 🏥 سلامت +75"
              and htexts[1] == "💉 کیت درمان | 🪙 900 TP | 🏥 سلامت +150"
              and htexts[2] == "🏥 جعبه کمک‌های اولیه | 🪙 1,800 TP | 🏥 سلامت فول", str(htexts))
        check("کاتالوگ درمان سه آیتم و قیمت‌هاش تو کانفیگه",
              set(config.HEAL_ITEMS) == {"band", "kit", "box"}
              and config.HEAL_ITEMS["band"]["heal"] == 75
              and config.HEAL_ITEMS["kit"]["heal"] == 150
              and config.HEAL_ITEMS["box"]["heal"] is None
              and config.HEAL_ITEMS["band"]["price"] == 400
              and config.HEAL_ITEMS["kit"]["price"] == 900
              and config.HEAL_ITEMS["box"]["price"] == 1800)

    # ═══ کولدان کنده‌کاری ۱ دقیقه ═══
    check("کنده‌کاری ۶۰ ثانیه‌ایه", config.MINE_COOLDOWN_SECONDS == 60)

    # ═══ کانفیگ نبرد HP جدید و کوئست‌های روزانه ═══
    check("کانفیگ نبرد HP",
          config.BATTLE_COOLDOWN_SECONDS == 30 and config.BATTLE_DMG_VARIANCE == 0.30
          and config.BATTLE_STEAL_MAX_PCT == 0.05 and config.BATTLE_DEAD_SECONDS == 600
          and config.MAX_LEVEL == 20 and config.HP_TABLE[0] == 200 and config.HP_TABLE[-1] == 600)
    check("۶ کوئست روزانه با عنوان و عدد هدف",
          set(config.DAILY_QUESTS) == {"attack", "harvest", "mine", "plant", "search", "feed"}
          and config.DAILY_QUESTS["attack"]["target"] == 5
          and config.DAILY_QUESTS["harvest"]["target"] == 10
          and config.DAILY_QUESTS["mine"]["target"] == 20
          and config.DAILY_QUESTS["plant"]["target"] == 5
          and config.DAILY_QUESTS["search"]["target"] == 1
          and config.DAILY_QUESTS["feed"]["target"] == 3,
          str(list(config.DAILY_QUESTS)))
    check("عنوان کوئست‌ها با عدد هدف پر میشه",
          config.DAILY_QUESTS["mine"]["title"].format(n=20) == "20 بار کنده‌کاری")
    check("تعداد کوئست روزانه ۲ تا ۳",
          config.DAILY_QUEST_COUNT_MIN == 2 and config.DAILY_QUEST_COUNT_MAX == 3)
    check("وزن جایزه‌ها معقوله",
          config.DAILY_QUEST_TP_WEIGHT == 0.55 and config.DAILY_QUEST_XP_WEIGHT == 0.30)

    # ═══ اسم دلخواه سگ ═══
    k, d, custom = dog_svc.parse_dog_query("دوبرمن")
    check("پارس فقط نژاد (اسم آیتم‌ها نژاد خالصه)", k == "doberman" and custom is None)
    k, d, custom = dog_svc.parse_dog_query("دوبرمن اصغر")
    check("«دوبرمن اصغر» الان اسم دلخواه اصغر میشه", custom == "اصغر", str(custom))
    k, d, custom = dog_svc.parse_dog_query("دوبرمن رکس")
    check("پارس نژاد + اسم دلخواه", k == "doberman" and custom == "رکس", str(custom))
    k, d, custom = dog_svc.parse_dog_query("ژرمن شپرد هاجر")
    check("پارس نژاد دوکلمه‌ای + اسم", k == "shepherd" and custom == "هاجر", str(custom))
    k, d, custom = dog_svc.parse_dog_query("کانگال")
    check("پارس فقط نژاد", k == "kangal" and custom is None)

    tx_name_kb = kb2.tx_confirm_kb("dog", "doberman", 424242, "رکس")
    datas = [b.callback_data for row in tx_name_kb.inline_keyboard for b in row]
    check("اسم سگ تو callback میره", datas[0] == "txcf:dog:doberman:424242:رکس", str(datas))
    check("طول callback اوکیه", all(len(d.encode()) <= 64 for d in datas))

    # ═══ strip_home تو گروه ═══
    class _Chat(SimpleNamespace):
        pass
    from telegram import InlineKeyboardMarkup
    fake_upd = SimpleNamespace(effective_chat=_Chat(type="group"))
    markup = InlineKeyboardMarkup([
        [kb2._btn("الف", "x"), kb2._btn("ب", "y")],
        [kb2._btn("🏠 منوی اصلی", "menu:home")],
    ])
    stripped = strip_home(fake_upd, markup)
    check("منوی اصلی تو گروه برمی‌ره", stripped is not None and all(
        b.callback_data != "menu:home" for row in stripped.inline_keyboard for b in row))
    fake_upd_pv = SimpleNamespace(effective_chat=_Chat(type="private"))
    check("تو پیوی منو می‌مونه", strip_home(fake_upd_pv, markup) is markup)

    # ═══ بک‌آپ و ری‌استور (/backup و /upload_backup) ═══
    check("بک‌آپ روی SQLite پشتیبانی میشه", backup_svc.backup_supported() and config.sqlite_path() is not None)
    async with session_scope() as s:
        n_users_before = len(list((await s.execute(select(User))).scalars()))

    snap = await backup_svc.create_snapshot()
    check("اسنپ‌شات بک‌آپ ساخته شد و سالمه", os.path.exists(snap) and backup_svc.is_valid_backup_file(snap))
    with open(snap, "rb") as f:
        snap_bytes = f.read()
    os.remove(snap)

    ok, msg = await backup_svc.restore_bytes(b"this is definitely not a sqlite db")
    check("فایل الکی رد میشه", not ok, msg)

    ok, msg = await backup_svc.restore_bytes(bytes(300))
    check("فایل خرد شده هم رد میشه", not ok)

    # یه تغییر می‌دیم بعد ری‌استور می‌کنیم، باید برگرده سر جاش
    async with session_scope() as s:
        ghost, _ = await users.get_or_create(s, tg(999999, "ghost", "روح"))
        await s.commit()
    async with session_scope() as s:
        check("روح اضافه شد", await users.get_by_tg(s, 999999) is not None)

    ok, msg = await backup_svc.restore_bytes(snap_bytes)
    check("ری‌استور بک‌آپ موفق", ok, msg)
    async with session_scope() as s:
        n_after = len(list((await s.execute(select(User))).scalars()))
        ghost_gone = (await users.get_by_tg(s, 999999)) is None
    check("اطلاعات دقیقا مطابق فایل بک‌آپ شد (روح پاک شد)",
          n_after == n_users_before and ghost_gone, f"{n_after} vs {n_users_before}")

    # ═══ رگرسیون باگ تایید خرید (فلو واقعی هندلرها) ═══
    from handlers import shop as shop_h, textcmd as textcmd_h

    class _Q(SimpleNamespace):
        async def answer(self, *a, **k):
            self.calls.append(("answer", a, k))
        async def edit_message_text(self, text, **k):
            self.calls.append(("edit", text, k))

    def _fake_update(data, uid=6001):
        q = _Q(data=data, message=SimpleNamespace(photo=None), calls=[])
        async def _qreply(text, **k):
            q.calls.append(("reply", text, k))
        q.message.reply_html = _qreply
        return SimpleNamespace(
            callback_query=q,
            message=q.message,
            effective_message=q.message,
            effective_user=SimpleNamespace(id=uid, username="flow", first_name="فلو"),
            effective_chat=_Chat(type="private"),
        )

    # خرید اینلاین سلاح: فاکتور → تایید → باید جنس خورده بشه (قبلا اینجا کرش می‌کرد)
    async with session_scope() as s:
        flow, _ = await users.get_or_create(s, _fake_update("x").effective_user)
        flow.cash = 200000
        flow.level = 15
        flow.iron = 1000
        await s.commit()

    upd = _fake_update("shop:buy:weap:pipe")
    await shop_h.buy_confirm(upd, None)
    check("فاکتور خرید اینلاین ساخته شد", any(c[0] == "edit" for c in upd.callback_query.calls))

    upd = _fake_update("cf:shop:buy:weap:pipe")
    await shop_h.buy_execute(upd, None)
    async with session_scope() as s:
        flow = await users.get_by_tg(s, 6001)
        owns = await users.get_item_keys(s, flow.id)
    check("تایید خرید اینلاین کار می‌کنه (رگرسیون)", "pipe" in owns, str(owns))

    # خرید متنی سگ با اسم دلخواه
    upd = _fake_update("txcf:dog:pitbull:6001:رکسی")
    await textcmd_h.tx_confirm_cb(upd, None)
    async with session_scope() as s:
        flow = await users.get_by_tg(s, 6001)
        flow_dogs = await dog_svc.get_user_dogs(s, flow.id)
    check("سگ با اسم دلخواه خریده شد",
          len(flow_dogs) == 1 and flow_dogs[0].name == "رکسی" and flow_dogs[0].breed == "پیتبول",
          str([d.name for d in flow_dogs]))

    # غریبه نمی‌تونه فاکتور کسی رو تایید کنه
    upd = _fake_update("txcf:weap:knife:6001", uid=9999)
    await textcmd_h.tx_confirm_cb(upd, None)
    check("تایید فاکتور غریبه بلاکه", any(c[0] == "answer" for c in upd.callback_query.calls))

    # ═══ ایمپورت و رجیستر هندلرها ═══
    import handlers  # noqa
    from telegram.ext import Application
    app = Application.builder().token("123:test").build()
    handlers.register_handlers(app)
    total = sum(len(h) for h in app.handlers.values())
    check("همه هندلرها رجیستر شدن", total >= 60, f"{total}")

    from handlers import jobs as jobs_h  # noqa: E402
    jobs_h.register_jobs(app)
    check("جاب‌های زمان‌دار رجیستر شدن (آب‌وهوا|بازار|کاروان|برد کاروان|جاروی ورودی معلق|نبض انرژی|پاکسازی عضویت|ادیت ساعتی آمار)",
          app.job_queue is not None and len(app.job_queue.jobs()) == 8
          and {j.name for j in app.job_queue.jobs()} == {"weather", "market", "caravan", "caravan-board", "pending-sweep", "energy-pulse", "fj-wipe", "stats-autoedit"},
          str([j.name for j in (app.job_queue.jobs() if app.job_queue else [])]))

    # regex دستورهای متنی، از خود TEXT_HANDLERS رجیستری — پیشوند «تریاکی » اجباریه
    import re
    pats = {n: re.compile(p) for n, p, _ in handlers.TEXT_HANDLERS}

    check("پترن خرید با و بدون پیشوند",
          pats["buy"].match("تریاکی خرید چاقو").group(1) == "چاقو" and pats["buy"].match("خرید چاقو").group(1) == "چاقو")
    check("پترن خرید سگ با پیشوند", pats["buy_dog"].match("تریاکی خرید سگ دوبرمن").group(1) == "دوبرمن")
    check("پترن کاشت با پیشوند", pats["plant"].match("تریاکی کاشت تریاک").group(1) == "تریاک")
    check("«تریاکی آمار اصغر»", pats["dogstats"].match("تریاکی آمار اصغر").group(1) == "اصغر")
    check("«تریاکی واریز/برداشت 1200»", pats["bankdep"].match("تریاکی واریز 1200") and pats["bankwd"].match("تریاکی برداشت ۱۲۰۰"))
    check("«تریاکی برداشت محصول» به بانک نمیره", pats["bankwd"].match("تریاکی برداشت محصول") is None
          and pats["harvest"].match("تریاکی برداشت محصول") is not None)
    check("«تریاکی رتبه/لیدربرد»", pats["rank"].match("تریاکی رتبه") and pats["rank"].match("تریاکی لیدربرد"))
    check("«تریاکی وضعیت هوا» و خواهر برادراش",
          pats["weather"].match("تریاکی وضعیت هوا") and pats["weather"].match("تریاکی وضعیت هواشناسی")
          and pats["weather"].match("تریاکی وضعیت آب و هوا") and pats["weather"].match("تریاکی آب و هوا"))
    check("«تریاکی هواشناسی» هم مستقیم هوا رو میاره", pats["weather"].match("تریاکی هواشناسی"))
    check("«تریاکی بازار» هم مستقیم بازار رو میاره",
          pats["market"].match("تریاکی بازار") and pats["market"].match("تریاکی وضعیت بازار")
          and pats["market"].match("تریاکی بازار سیاه"))
    check("«تریاکی مزرعه» و «تریاکی سگ‌های من»", pats["farm"].match("تریاکی مزرعه") and pats["mydogs"].match("تریاکی سگ‌های من"))
    check("«تریاکی زمین» وصله ولی «زمین» لخت دیگه دستور نیس",
          pats["farm"].match("تریاکی زمین") is not None and pats["farm"].match("زمین") is None)

    # ─── سه پیشوند «تریاکی | تریاک | تی» برای همه دستورهای پیشوندی ───
    check("پیشوند «تریاک» (بدون ی) هم همه‌جا قبوله",
          pats["shop"].match("تریاک شاپ") and pats["farm"].match("تریاک زمین")
          and pats["buy"].match("تریاک خرید چاقو").group(1) == "چاقو"
          and pats["rank"].match("تریاک رتبه"))
    check("پیشوند «تی» هم همه‌جا قبوله",
          pats["shop"].match("تی شاپ") and pats["farm"].match("تی مزرعه")
          and pats["bankdep"].match("تی واریز 1200")
          and pats["weather"].match("تی هواشناسی"))

    # ─── «کنده کاری» و «حمله» با و بدون پیشوند ───
    check("«کنده کاری» لخت و پیشونددار هر دو",
          pats["mine"].match("کنده کاری") and pats["mine"].match("تریاکی کنده کاری")
          and pats["mine"].match("تریاک کنده کاری") and pats["mine"].match("تی کنده کاری"))
    check("«آپگرید کنده کاری» لخت و پیشونددار و جدا از خود ضربه",
          pats["mine_upg"].match("تی آپگرید کنده کاری") and pats["mine_upg"].match("آپگرید کنده کاری")
          and not pats["mine_upg"].match("کنده کاری"))
    check("«کنده کاری آپگرید» برعکسش هم همون صفحه رو میاره",
          pats["mine_upg"].match("تی کنده کاری آپگرید") and pats["mine_upg"].match("کنده کاری آپگرید")
          and pats["mine_upg"].match("تریاکی کنده کاری آپگرید")
          and not pats["mine_upg"].match("تی کنده کاری نآپگرید"))

    # ─── «تی بکاپ» و «تی کپی» ───
    check("«تی بکاپ» منوی بک‌آپ، لخت نه",
          pats["backup_menu"].match("تی بکاپ") and pats["backup_menu"].match("تریاکی بک‌آپ")
          and pats["backup_menu"].match("تی‌بکاپ") and not pats["backup_menu"].match("بکاپ"))
    check("«تی کپی» با نیم‌فاصله و هر سه پیشوند، لخت نه",
          pats["backup_copy"].match("تی کپی") and pats["backup_copy"].match("تی‌کپی")
          and pats["backup_copy"].match("تریاکی کپی") and pats["backup_copy"].match("تریاک کپی")
          and not pats["backup_copy"].match("کپی"))
    check("«حمله» لخت و پیشونددار هر دو",
          pats["attack"].match("حمله") and pats["attack"].match("تریاکی حمله")
          and pats["attack"].match("تریاک حمله") and pats["attack"].match("تی حمله"))

    # ─── دستورهای تیم با و بدون پیشوند ───
    check("تیم با اسم لخت و پیشونددار",
          pats["team"].match("تریاکی تیم فوتبالیست‌ها").group(1) == "فوتبالیست‌ها"
          and pats["team"].match("تیم فوتبالیست‌ها").group(1) == "فوتبالیست‌ها"
          and pats["team"].match("تیم").group(1) is None
          and pats["team"].match("تریاکی تیم من").group(1) == "من"
          and pats["team"].match("تیم من").group(1) == "من")
    check("«جوین تیم» لخت و پیشونددار با اسم چندکلمه‌ای",
          pats["team_join"].match("تریاکی جوین تیم فوتبالیست‌های ایران").group(1) == "فوتبالیست‌های ایران"
          and pats["team_join"].match("جوین تیم فوتبالیست‌ها").group(1) == "فوتبالیست‌ها")
    check("«ساخت تیم» لخت و پیشونددار",
          pats["team_create"].match("ساخت تیم") and pats["team_create"].match("تریاکی ساخت تیم"))
    check("«تیم ست بیو» فرم جدید، لخت و پیشونددار",
          pats["team_bio"].match("تیم ست بیو بهترینیم").group(1) == "بهترینیم"
          and pats["team_bio"].match("تریاکی تیم ست بیو بهترینیم").group(1) == "بهترینیم"
          and pats["team_bio"].match("تریاکی ست بیو تیم بهترینیم") is None)
    check("بقیه دستورهای تیم لخت و پیشونددار",
          pats["team_bld"].match("تیم ساختمان") and pats["team_bld"].match("تریاکی تیم ساخت")
          and pats["team_profile"].match("تیم پروفایل") and pats["roster"].match("تیم عضویت")
          and pats["team_top"].match("تیم لیدربرد") and pats["team_bank"].match("تیم بانک")
          and pats["team_up"].match("تیم ارتقا حمله") and pats["team_up"].match("تیم ارتقا دفاع")
          and pats["team_leave"].match("ترک تیم") and pats["team_disband"].match("انحلال تیم")
          and pats["team_quests"].match("تیم کوئست") and pats["quests"].match("کوئست")
          and pats["team_mine"].match("کنده کاری تیمی") and pats["team_mine"].match("تریاکی استخراج تیمی"))
    check("«تیم واریز» لخت و پیشونددار",
          pats["team_dep"].match("تیم واریز 1200").group(1) == "1200"
          and pats["team_dep"].match("تریاکی تیم واریز 1200").group(1) == "1200"
          and pats["team_dep"].match("تیم واریز").group(1) is None)

    check("شاپ و برداشت و خرید و کاشت و لیدربرد و کوئست و هواشناسی بدون پیشوند هم کار می‌کنن",
          pats["shop"].match("شاپ") and pats["shop"].match("فروشگاه")
          and pats["harvest"].match("برداشت") and pats["harvest"].match("برداشت محصول")
          and pats["buy_dog"].match("خرید سگ دوبرمن").group(1) == "دوبرمن"
          and pats["plant"].match("کاشت تریاک").group(1) == "تریاک"
          and pats["rank"].match("لیدربرد") and pats["rank"].match("رتبه بندی")
          and pats["weather"].match("هواشناسی"))
    check("«برداشت 1200» بدون پیشوند به محصول نمیره",
          pats["harvest"].match("برداشت 1200") is None)
    check("«کوئست تیمی» مال کوئست تیمه و «کوئست» تنها مال روزانه بازیکنه",
          pats["team_quests"].match("کوئست تیم") and pats["team_quests"].match("کوئست تیمی")
          and pats["team_quests"].match("تیم کوئست") and pats["quests"].match("کوئست تیم") is None)
    check("دستورهای معمولی هنوز پیشوند می‌خوان",
          not any(p.match(t) for t in ("زمین", "پناهگاه", "قمار", "جستجو", "راهنما", "مزرعه") for p in pats.values()))

    # ═══ سیستم‌های جهان: بذر افسانه‌ای | جستجو | کیفیت | آب‌وهوا | بازار | قمار | پناهگاه | پلیس | کاروان ═══

    # ── بذر افسانه‌ای تو شاپ خریدنی نیس حتی با لول و پول ──
    async with session_scope() as s:
        rich, _ = await users.get_or_create(s, tg(8801, "rich", "پولدار"))
        rich.level = 20
        rich.cash = 5000000
        for leg in ("jahannam", "eblis"):
            ok, msg = await shop_svc.purchase(s, rich, "seed", leg)
            check(f"خرید {leg} از شاپ رد میشه", not ok and "افسانه‌ای" in msg, msg)
        await s.commit()

    check("مولت بازار همون ضریب ذخیره‌شده‌ست و افسانه‌ای‌ها هم مولت خودشون رو دارن",
          world_svc.market_mult({"jahannam": 1.2}, "jahannam") == 1.2
          and world_svc.market_mult({"eblis": 0.8}, "eblis") == 0.8
          and world_svc.market_mult({}, "marijuana") == 1.0)
    check("ترجمه دیتای قدیمی درصدی بازار به ضریب جدید",
          abs(world_svc._parse_market("marijuana:-20,gharch:10")["marijuana"] - 0.8) < 1e-9
          and abs(world_svc._parse_market("marijuana:-20,gharch:10")["gharch"] - 1.1) < 1e-9)

    # ── جستجو 🔍 ──
    check("جمع شانس‌های جستجو ۱ه",
          abs(sum(o["chance"] for o in config.SEARCH_OUTCOMES) - 1.0) < 1e-9)
    async with session_scope() as s:
        su, _ = await users.get_or_create(s, tg(8802, "srch", "جستجوگر"))
        su.cash = 100000
        res = await world_svc.do_search(s, su, luck=1.0)
        check("جستجوی اول نتیجه داره",
              res["status"] in ("money", "seed_common", "seed_rare", "seed_hell", "seed_devil", "seed_mutant", "thief"),
              res["status"])
        res2 = await world_svc.do_search(s, su, luck=1.0)
        check("کولدان ۱۰ دقیقه جستجو فعاله",
              res2["status"] == "cooldown" and 0 < res2["left"] <= 600, str(res2.get("left")))
        await s.commit()

    async with session_scope() as s:
        su = await users.get_by_tg(s, 8802)
        counts: dict = {}
        money_bounds: list[int] = []
        for _ in range(3000):
            su.last_search_at = None
            su.cash = 100000
            r = await world_svc.do_search(s, su, luck=1.0)
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            if r["status"] == "money":
                money_bounds.append(r["amount"])
        check("همه نتیجه‌های جستجو دیده میشن (حتی جهش‌یافته با دراپ ۱٪)",
              all(counts.get(k) for k in ("money", "seed_common", "seed_rare", "seed_hell", "seed_devil", "seed_mutant", "thief")),
              str(counts))
        check("دراپ جهش‌یافته از ابلیس هم کمتره", counts.get("seed_mutant", 0) < counts.get("seed_devil", 0), str(counts))
        check("پول جستجو تو بازه ۱۰۰ تا ۷۰۰ه",
              min(money_bounds) >= 100 and max(money_bounds) <= 700,
              f"{min(money_bounds)}..{max(money_bounds)}")
        stock = await farming.get_stock(s, su.id)
        check("بذرهای جستجو رفتن تو انبار", sum(stock.values()) > 400, str(stock))

        counts_l: dict = {}
        for _ in range(3000):
            su.last_search_at = None
            su.cash = 100000
            r = await world_svc.do_search(s, su, luck=3.0)
            counts_l[r["status"]] = counts_l.get(r["status"], 0) + 1
        check("با سگ خوش‌شانس دزد خیلی کمتر میاد",
              counts_l.get("thief", 0) < counts.get("thief", 0) * 0.6,
              f"{counts.get('thief')} → {counts_l.get('thief')}")
        await s.commit()

    # ── کیفیت محصول ⭐ ──
    check("شانس کیفیت‌ها ۴۵/۳۰/۱۷/۷/۱ و جمع ۱",
          [t["chance"] for t in config.QUALITY_TIERS] == [0.45, 0.30, 0.17, 0.07, 0.01]
          and abs(sum(t["chance"] for t in config.QUALITY_TIERS) - 1.0) < 1e-9)
    random.seed(11)
    stars = [world_svc.roll_quality()["stars"] for _ in range(5000)]
    s1, s5 = stars.count(1) / len(stars), stars.count(5) / len(stars)
    check("توزیع کیفیت نزدیک ۴۵% و ۱%ه", 0.41 < s1 < 0.49 and 0.004 < s5 < 0.02,
          f"1⭐:{s1:.1%} 5⭐:{s5:.2%}")
    stars_b = [world_svc.roll_quality(0.5)["stars"] for _ in range(3000)]
    check("بونس شب مهتابی ⭐۵ رو خیلی بالا می‌بره", stars_b.count(5) / len(stars_b) > 0.4)
    check("ضریب قیمت کیفیت صعودیه", [t["mult"] for t in config.QUALITY_TIERS] == sorted(t["mult"] for t in config.QUALITY_TIERS))
    check("کیفیت بالاتر قیمت رو می‌بره بالا", config.QUALITY_TIERS[-1]["mult"] == 3.0)

    # ── آب و هوا 🌦 ──
    async with session_scope() as s:
        await world_svc._meta_set(s, "weather_until", "2000-01-01T00:00:00")
        key, rolled = await world_svc.ensure_weather(s)
        check("آب و هوای منقضی رول میشه", rolled is not None and key in config.WEATHERS, key)
        key2, left = await world_svc.current_weather(s)
        check("هوا تا رول بعد ثابته و تایمرش بین صفر و ۶ ساعته (مرز ساعت ایران)",
              key2 == key and 0 < left <= 21600, f"{key2}/{left}")
        check("باران رشد 30%+ | گرما 20%− | سرما زمان بیشتر",
              world_svc.weather_grow_speed("rain") == 1.30
              and world_svc.weather_grow_speed("heat") == 0.80
              and abs(world_svc.weather_grow_speed("frost") - 1 / 1.15) < 1e-9)
        check("طوفان حمله 10%−", world_svc.weather_combat_mods("storm") == (-0.10, 0.0))
        check("مه دفاع 20%+", world_svc.weather_combat_mods("fog") == (0.0, 0.20))
        check("جشن برداشت فروش 35%+ (پایه کمتر شده که سقف ۵۰ درصدی به‌ندرت دیده بشه)", world_svc.weather_sell_mult("fest") == 1.35)
        check("شب مهتابی ⭐۵ +10%", world_svc.weather_q5_bonus("moon") == 0.10)
        txtw = world_svc.weather_announce_text("rain")
        check("متن اعلان آب و هوا قالب داره",
              "🌦 وضعیت آب و هوای جدید" in txtw and "باران" in txtw and "آغاز شد" in txtw and "30%" in txtw,
              txtw.replace("\n", " | ")[:100])
        check("متن اعلان باران افکت کامل رو می‌گه",
              "🌱 سرعت رشد گیاه ها 30% افزایش پیدا کرد، تا 6 ساعت آینده" in txtw,
              txtw.replace("\n", " | ")[-120:])
        txth = world_svc.weather_announce_text("heat")
        check("متن اعلان گرما دقیقه",
              "☀️ گرمای شدید آغاز شد" in txth
              and "🌱 سرعت رشد گیاه ها 20% کاهش پیدا کرد، تا 6 ساعت آینده" in txth,
              txth.replace("\n", " | ")[:120])
        check("برگشت هوای عادی هم اعلام میشه",
              world_svc.weather_announce_text("normal") ==
              "<b>🌦 وضعیت آب و هوای جدید</b>\n\n🏙️ هوای محله صافِ صاف شد الان دیگه هیچ افکت خاصی فعال نیست")
        view = await world_svc.weather_view(s)
        check("ویوی آب و هوا ساخته میشه", view["key"] in config.WEATHERS and view["left"] > 0)
        await s.commit()

    # ── مرزهای رول هوا: ساعت ۲۴ و ۶ و ۱۲ و ۱۸ به‌وقت ایران، نه هر ۶ ساعت از لحظه رول ──
    from datetime import datetime as _dtw
    check("مرز بعدی هوا سر ساعت ۱۲ ایران میفته (UTC 03:00 ← UTC 08:30)",
          world_svc._next_weather_boundary(_dtw(2026, 7, 29, 3, 0)) == _dtw(2026, 7, 29, 8, 30))
    check("بعد از ساعت ۲۴ ایران مرز بعدی ۶ صبح روز بعده (UTC 21:00 ← روز بعد 02:30)",
          world_svc._next_weather_boundary(_dtw(2026, 7, 29, 21, 0)) == _dtw(2026, 7, 30, 2, 30))
    check("دقیقاً سر مرز، مرز بعدی میاد نه همون لحظه (UTC 02:30 ← UTC 08:30)",
          world_svc._next_weather_boundary(_dtw(2026, 7, 29, 2, 30)) == _dtw(2026, 7, 29, 8, 30))
    check("مرزهای کانفیگ دقیقاً ۲۴ و ۶ و ۱۲ و ۱۸ به‌وقت ایرانه",
          config.WEATHER_BOUNDARY_HOURS == (0, 6, 12, 18))
    span_left = 5 * 3600 + 20 * 60
    ann_left = world_svc.weather_announce_text("rain", 30, left=span_left)
    check("اعلان هوا با مهلت واقعی تا مرز بعدی (نه ۶ ساعت ثابت)",
          f"تا {fa_dur(span_left)} آینده" in ann_left and "تا 6 ساعت آینده" not in ann_left,
          ann_left.replace("\n", " | ")[-90:])

    # صفحه «وضعیت آب و هوا» با افکت‌های فعلی (متن هندلر واقعی)
    from handlers import world as world_h
    async with session_scope() as s:
        await world_svc._meta_set(s, "weather_key", "heat")
        await world_svc._meta_set(s, "weather_until", (now_utc() + timedelta(seconds=7200)).isoformat())
        await world_svc._meta_set(s, "weather_pct", "20")  # درصد این رول گرما، دیترمینیستیک برای متن
        await s.commit()
    upd = _text_update("تریاکی آب و هوا", uid=1001, uname="ali", fname="علی")
    await world_h.weather_cmd(upd, None)
    wtxt = upd.message.calls[-1][1]
    check("صفحه وضعیت آب و هوا قالب جدید داره",
          "<b>🌦 وضعیت آب و هوا</b>" in wtxt and "☀️ گرمای شدید" in wtxt
          and "دیگه عوض میشه" in wtxt and "افکت‌های فعلی:" in wtxt
          and "▫️ سرعت رشد منفی 20%" in wtxt
          and "سر ساعت‌های 6-12-18-24 به وقت ایران عوض میشه و شدت افکتش هم هر بار فرق می‌کنه، تو گروه‌های فعال اعلام میشه" in wtxt,
          wtxt.replace("\n", " | ")[:180])
    async with session_scope() as s:
        await world_svc._meta_set(s, "weather_key", "normal")
        await world_svc._meta_set(s, "weather_until", (now_utc() + timedelta(seconds=7200)).isoformat())
        await s.commit()
    upd = _text_update("تریاکی آب و هوا", uid=1001, uname="ali", fname="علی")
    await world_h.weather_cmd(upd, None)
    check("صفحه هوای عادی متن عادی بودن رو داره",
          "افکت خاصی فعال نیست، هوا عادیه" in upd.message.calls[-1][1])

    # ── rescale فوری تایمر زمین‌ها با عوض شدن هوا ──
    async with session_scope() as s:
        rsu, _ = await users.get_or_create(s, tg(8840, "resc", "رشدی"))
        rplot = Plot(user_id=rsu.id, status="empty")
        s.add(rplot)
        await s.flush()
        rplot.status = "growing"
        rplot.seed_key = "teriak"
        rplot.ready_at = now_utc() + timedelta(seconds=1000)
        await s.flush()
        changed = await world_svc.apply_growth_rescale(s, "heat", "normal")
        check("گرما→عادی تایمر رو کوتاه می‌کنه (سرعت میره بالا)",
              changed == 1 and abs((rplot.ready_at - now_utc()).total_seconds() - 1000 * 0.8) < 5,
              str((rplot.ready_at - now_utc()).total_seconds()))
        changed2 = await world_svc.apply_growth_rescale(s, "normal", "heat")
        check("عادی→گرما تایمر رو بلند می‌کنه",
              changed2 == 1 and abs((rplot.ready_at - now_utc()).total_seconds() - 1000) < 5,
              str((rplot.ready_at - now_utc()).total_seconds()))
        rplot.status = "empty"
        rplot.ready_at = None
        await s.flush()
        check("زمین خالی دست نمی‌خوره", await world_svc.apply_growth_rescale(s, "normal", "heat") == 0)
        # ادغام با رول هوا: هوا گرماست و منقضی شده → رول به عادی باید تایمر رو ریسکیل کنه
        rplot.status = "growing"
        rplot.ready_at = now_utc() + timedelta(seconds=1000)
        await world_svc._meta_set(s, "weather_key", "heat")
        await world_svc._meta_set(s, "weather_until", "2000-01-01T00:00:00")
        await world_svc._meta_set(s, "weather_pct", "20")  # درصد رول فعلی گرما، دیترمینیستیک برای ریسکیل
        old_nc = config.WEATHER_NORMAL_CHANCE
        config.WEATHER_NORMAL_CHANCE = 1.0
        try:
            key_r, rolled_r = await world_svc.ensure_weather(s)
        finally:
            config.WEATHER_NORMAL_CHANCE = old_nc
        check("رول هوا به عادی تایمر در حال رشد رو همون لحظه ریسکیل می‌کنه",
              key_r == "normal" and rolled_r is not None
              and abs((rplot.ready_at - now_utc()).total_seconds() - 1000 * 0.8) < 5,
              f"{key_r} {str((rplot.ready_at - now_utc()).total_seconds())}")
        rplot.status = "empty"
        rplot.ready_at = None
        await s.commit()

    # ── بازار سیاه 📈 ──
    async with session_scope() as s:
        await world_svc._meta_set(s, "market_until", "2000-01-01T00:00:00")
        rolled = await world_svc.ensure_market(s)
        check("بازار منقضی ری‌رول شد", rolled)
        mults, left = await world_svc.market_mults(s)
        check("همه محصولات از روز اول تو بازارن، حتی افسانه‌ای و قفل‌لولی‌ها",
              set(mults) == set(config.SEEDS), str(sorted(mults)))
        check("ضریب‌ها تو بازه کف و سقف جیتر‌دار کانفیگن (دور و بر ۰.۷۵ تا ۱.۲۵)",
              all(config.MARKET_MIN_PRICE_MULTIPLIER - config.MARKET_BAND_JITTER <= m
                  <= config.MARKET_MAX_PRICE_MULTIPLIER + config.MARKET_BAND_JITTER for m in mults.values()))
        check("افسانه‌ای‌ها هم مولت بازار می‌گیرن", "jahannam" in mults and "eblis" in mults)
        m = world_svc.market_mult(mults, "marijuana")
        check("مولت بازار همون ضریب ذخیره‌شده برمی‌گرده",
              abs(m - mults["marijuana"]) < 1e-9, f"{m} vs {mults['marijuana']}")
        # برای ثبات تست‌های بعدی: بازار صفر و هوا عادی
        await world_svc._meta_set(s, "market", ",".join(f"{k}:0" for k in config.SEEDS))
        await world_svc._meta_set(s, "market_until", (now_utc() + timedelta(seconds=14400)).isoformat())
        await world_svc._meta_set(s, "weather_key", "normal")
        await world_svc._meta_set(s, "weather_until", (now_utc() + timedelta(seconds=7200)).isoformat())
        await s.commit()

    # ── قمارخانه 🎰 ──
    async with session_scope() as s:
        cu, _ = await users.get_or_create(s, tg(8803, "casino", "قمارباز"))
        cu.level = 3
        cu.cash = 100000
        r = await world_svc.casino_play(s, cu, 1000)
        check("قمارخانه زیر لول ۷ قفله", r["status"] == "locked")
        cu.level = 10
        r = await world_svc.casino_play(s, cu, 1234)
        check("شرط خارج از میزها رد میشه", r["status"] == "bad_bet")
        r = await world_svc.casino_play(s, cu, 1000)
        check("دست اول قمار انجام شد", r["status"] in ("win", "lose"), r["status"])
        r2 = await world_svc.casino_play(s, cu, 1000)
        check("کولدان ۱۲ ساعت قمار فعاله",
              r2["status"] == "cooldown" and r2["left"] > 11 * 3600, str(r2.get("left")))
        check("برد قمار 1.8 برابر شرطه", config.CASINO_WIN_MULT == 1.8)

        # بلندمدت ضرر، ۳۰۰۰ دست شبیه‌سازی
        cu.cash = 10_000_000
        net0 = cu.cash
        wins = 0
        plays = 3000
        for _ in range(plays):
            cu.last_casino_at = None
            r = await world_svc.casino_play(s, cu, 1000)
            assert r["status"] in ("win", "lose")
            wins += r["status"] == "win"
        net = cu.cash - net0
        check("قمار تو بلندمدت سودده نیس (خالص منفی)", net < 0, f"net={net}")
        check("نرخ برد نزدیک ۴۰%ه", 0.35 < wins / plays < 0.45, f"{wins / plays:.1%}")
        await s.commit()

    # ── پناهگاه 🏚 ──
    check("قیمت پناهگاه صعودی و رنده",
          config.SHELTER_PRICES == sorted(config.SHELTER_PRICES)
          and all(p % 500 == 0 for p in config.SHELTER_PRICES), str(config.SHELTER_PRICES))
    check("هر لول پناهگاه ۵% خسارت کمتر و سقف ۹۰%",
          abs(world_svc.shelter_raid_cut(3) - 0.15) < 1e-9 and world_svc.shelter_raid_cut(40) == 0.9)
    check("هر لول ۴% شانس فرار و سقف ۵۰%",
          abs(world_svc.shelter_dodge_chance(5) - 0.20) < 1e-9 and world_svc.shelter_dodge_chance(40) == 0.5)

    async with session_scope() as s:
        sh, _ = await users.get_or_create(s, tg(8804, "shel", "پناهنده"))
        sh.cash = 100000
        check("ظرفیت پایه هر بذر ۵ تاست", world_svc.seed_storage_cap(sh) == 5)
        cash_b = sh.cash
        ok, msg = await world_svc.upgrade_shelter(s, sh)
        check("ارتقای پناهگاه انجام شد",
              ok and sh.shelter_level == 1 and sh.cash == cash_b - config.SHELTER_PRICES[0], msg)
        check("هر لول +۵ ظرفیت بذر", world_svc.seed_storage_cap(sh) == 10)
        sh.cash = 0
        ok, msg = await world_svc.upgrade_shelter(s, sh)
        check("ارتقا بدون پول رد", not ok)

        # سقف انبار بذر موقع خرید اعمال میشه
        sh.level = 20
        sh.cash = 100000
        await farming.add_seed_stock(s, sh.id, "teriak", world_svc.seed_storage_cap(sh))
        ok, msg = await shop_svc.purchase(s, sh, "seed", "teriak")
        check("خرید بیشتر از ظرفیت انبار رد میشه", not ok and "پر" in msg, msg)
        await s.commit()

    # ── یورش پلیس 🚔 ──
    async with session_scope() as s:
        act, _ = await users.get_or_create(s, tg(8805, "actv", "فعال"))
        inact, _ = await users.get_or_create(s, tg(8806, "inact", "دیر اومده"))
        inact.last_seen_at = now_utc() - timedelta(hours=48)
        await farming.add_seed_stock(s, act.id, "teriak", 10)
        await farming.add_seed_stock(s, inact.id, "teriak", 10)
        await s.flush()

        old_chance = config.POLICE_RAID_CHANCE
        config.POLICE_RAID_CHANCE = 1.0  # برای تست حتميش کن
        try:
            recs = await world_svc.police_wave(s)
        finally:
            config.POLICE_RAID_CHANCE = old_chance

        act_rec = next((r for r in recs if r["user"].id == act.id), None)
        inact_rec = next((r for r in recs if r["user"].id == inact.id), None)
        stock_act = await farming.get_stock(s, act.id)
        stock_inact = await farming.get_stock(s, inact.id)
        check("یورش ۳۰% انبار فعال رو نابود کرد",
              act_rec is not None and act_rec["lost"].get("teriak") == 3 and stock_act.get("teriak") == 7,
              f"lost={act_rec and act_rec['lost']} stock={stock_act}")
        check("غیرفعال ۲۴ ساعت اخیر هدف نیس", inact_rec is None and stock_inact.get("teriak") == 10)
        txtr = world_svc.police_report_text(act_rec)
        check("پیام یورش قالب داره",
              "🚔 یورش پلیس!" in txtr and "تریاک" in txtr and "انبار" in txtr,
              txtr.replace("\n", " | ")[:130])
        await s.commit()

    # ── فعالیت گروه ──
    async with session_scope() as s:
        await world_svc.touch_group(s, -100123)
        await world_svc.touch_group(s, -100123)  # بار دوم فقط زمان رو آپدیت می‌کنه
        gids = await world_svc.active_group_ids(s, 1)
        check("گروه فعال ۱ ساعت اخیر پیدا میشه", -100123 in gids)
        g = await s.get(GroupActivity, -100123)
        g.last_active_at = now_utc() - timedelta(hours=25)
        gids = await world_svc.active_group_ids(s, 24)
        check("گروه قدیمی از لیست ۲۴ ساعته خارج میشه", -100123 not in gids)
        # نشانه‌گذاری پلیرای گروه، برای «تعداد پلیرای هر گروه» تو آمار ادمین
        world_svc._PLAYER_MARK.clear()
        await world_svc.touch_group(s, -100123, user_tg=7357)
        await world_svc.touch_group(s, -100123, user_tg=7357)  # تو TTL فقط یه بار ثبت میشه
        await s.flush()
        gp = await s.get(GroupPlayer, (-100123, 7357))
        cnt_gp = len(list((await s.execute(
            select(GroupPlayer).where(GroupPlayer.chat_id == -100123))).scalars()))
        check("دیده‌شدن پلیر تو گروه ثبت میشه و تو یه ساعت دوباره ثبت نمیشه",
              gp is not None and cnt_gp >= 1, f"rows={cnt_gp}")
        t0 = gp.last_active_at
        await world_svc.touch_group(s, -100123, user_tg=7357)
        check("ثبت تکراری داخل TTL زمانش تازه نمیشه (کش حافظه)", gp.last_active_at == t0)
        await s.commit()

    # ── کاروان 🚛 ──
    world_svc.CARAVANS.clear()
    world_svc.CARAVAN_HITS.clear()
    async with session_scope() as s:
        atk1, _ = await users.get_or_create(s, tg(8807, "cv1", "کاروان‌زن"))
        atk2, _ = await users.get_or_create(s, tg(8808, "cv2", "هم‌دسته"))
        chat_id = 920001
        cv = world_svc.caravan_spawn(chat_id)
        check("کاروان با HP از تیِرها اسپون شد", cv["hp"] in config.CARAVAN_HP_TIERS, str(cv["hp"]))
        check("برد کاروان هدر داره", "🚛 کاروان وارد محله شد" in world_svc.caravan_board_text(cv))

        cash_b = atk1.cash
        r = await world_svc.caravan_attack(s, chat_id, atk1, 55)
        check("ضربه اول ثبت شد و جایزه نقدی داره",
              r["status"] == "hit" and atk1.cash == cash_b + r["dmg"] * config.CARAVAN_MONEY_PER_DMG
              and 44 <= r["dmg"] <= 66,
              str(r.get("status")))
        r = await world_svc.caravan_attack(s, chat_id, atk1, 55)
        check("کولدان ۱ دقیقه ضربه کاروان", r["status"] == "cooldown" and 0 < r["left"] <= 60)

        r2 = await world_svc.caravan_attack(s, chat_id, atk2, 60)
        check("نفر دوم هم می‌زنه", r2["status"] in ("hit", "killed"))

        world_svc.CARAVAN_HITS.pop((chat_id, atk1.id), None)
        r3 = await world_svc.caravan_attack(s, chat_id, atk1, 999999)
        check("کاروان افتاد", r3["status"] == "killed", str(r3.get("status")))
        rewards = r3.get("rewards", [])
        check("تسویه به شرکت‌کننده‌هاس و نفر اول مشخصه",
              len(rewards) == 2 and rewards[0]["top"] and rewards[0]["user_id"] == atk1.id,
              str([(x["user_id"], x["dmg"], x["top"]) for x in rewards]))
        check("نفر اول بذر جایزه ویژه گرفت", len(rewards[0]["seeds"]) >= 1, str(rewards[0]["seeds"]))
        check("برد کاروان بعد کیل پاک شد", world_svc.caravan_active(chat_id) is None)
        end_txt = world_svc.caravan_end_text(rewards, killed=True)
        check("متن پایان کاروان با قالب جدیده",
              "💀 کاروان غارت شد" in end_txt and "🏆" in end_txt
              and "⚔️ دمیج:" in end_txt and "💰 پاداش:" in end_txt and "🎁 جایزه ویژه:" in end_txt
              and f"🏆 نفر اول {rewards[0]['name']} بیشترین جایزه رو گرفت" in end_txt
              and "📢 فقط 5 نفر برتر جایزه دریافت می‌کنن" in end_txt, end_txt[:100])
        await s.commit()

    # ── کاروان 🚛: نکته آپدیت 2 دقیقه‌ای + متن رد شد + قانون 5 نفر برتر ──
    world_svc.CARAVANS.clear()
    world_svc.CARAVAN_HITS.clear()
    async with session_scope() as s:
        esc_u, _ = await users.get_or_create(s, tg(8830, "cvx", "دیررس"))
        esc_uid = esc_u.id
        await s.commit()
    cv_b = world_svc.caravan_spawn(940001)
    cv_b["damages"][esc_uid] = 40
    cv_b["names"][esc_uid] = "دیررس"
    btxt = world_svc.caravan_board_text(cv_b)
    check("برد کاروان قالب دقیق جدید رو داره (جان/تایمر/قوانین/جدول)",
          all(x in btxt for x in ["❤️ جان کاروان", "دقیقه تا خروج کاروان",
                                  "🔄 این پیام هر 2 دقیقه به‌روزرسانی میشه",
                                  "⚔️ هر بازیکن هر 1 دقیقه فقط یک بار می‌تونه حمله کنه",
                                  "💥 قدرت هر ضربه بر اساس قدرت حمله بازیکنه",
                                  "🏆 فقط 5 نفر برتر جایزه می‌گیرن",
                                  "📊 جدول دمیج"]), btxt[:80])
    cv_e = world_svc.caravan_spawn(940006)
    etxt = world_svc.caravan_board_text(cv_e)
    world_svc.CARAVANS.pop(940006, None)
    check("جدول دمیج از اول خالی هم نمایش داده میشه",
          "▫️ هنوز کسی به کاروان حمله نکرده" in etxt and "اولین نفری باش که ضربه می‌زنه" in etxt)
    cv_t8 = world_svc.caravan_spawn(940008)
    cv_t8["expires_at"] = now_utc() + timedelta(minutes=8, seconds=6)
    t8 = world_svc.caravan_board_text(cv_t8)
    cv_t10 = world_svc.caravan_spawn(940009)
    t10 = world_svc.caravan_board_text(cv_t10)
    world_svc.CARAVANS.pop(940008, None)
    world_svc.CARAVANS.pop(940009, None)
    check("تایمر پلکان 2 دقیقه‌ایه و ثانیه نشون نمیده (8:06→8 | 10:00→10)",
          "⏳ 8 دقیقه تا خروج کاروان" in t8 and "⏳ 10 دقیقه تا خروج کاروان" in t10
          and "ثانیه" not in t8, t8.split("\n")[6] if len(t8.split("\n")) > 6 else t8[:60])

    cv_b["expires_at"] = now_utc() - timedelta(seconds=5)
    async with session_scope() as s:
        res = await world_svc.caravan_expire(s, 940001)
        await s.commit()
    esc_txt = world_svc.caravan_end_text(res["rewards"], killed=False)
    check("متن رد شد هم همون قالبو داره با تیتر متفاوت",
          "🚛 کاروان از محله رد شد" in esc_txt and "⚔️ دمیج: 40" in esc_txt
          and "💰 پاداش:" in esc_txt and "🎁 جایزه ویژه:" in esc_txt
          and "📢 فقط 5 نفر برتر" in esc_txt and "🏆 نفر اول" not in esc_txt, esc_txt[:90])
    check("رد شد بدون هیچ ضربه‌ای متن ساده داره",
          "بدون اینکه کسی بهش برسه" in world_svc.caravan_end_text([], killed=False))

    # قانون 5 نفر برتر: 7 نفر بزنن فقط 5 تای اول جایزه می‌گیرن
    world_svc.CARAVANS.clear()
    cv_t = world_svc.caravan_spawn(940002)
    async with session_scope() as s:
        for i in range(7):
            tu, _ = await users.get_or_create(s, tg(8840 + i, f"top{i}", f"نفر{i}"))
            cv_t["damages"][tu.id] = 100 - i
            cv_t["names"][tu.id] = f"نفر{i}"
        await s.commit()
    cv_t["expires_at"] = now_utc() - timedelta(seconds=5)
    async with session_scope() as s:
        res = await world_svc.caravan_expire(s, 940002)
        await s.commit()
    check("فقط 5 نفر برتر جایزه تسویه می‌گیرن",
          res is not None and len(res["rewards"]) == 5
          and res["rewards"][0]["dmg"] == 100 and res["rewards"][-1]["dmg"] == 96,
          str(len(res["rewards"]) if res else "-"))

    # ── کاروان 🚛: کیل و انقضا با پیام واقعی، برد پاک میشه و پیام تازه میاد ──
    class _CvBot:
        def __init__(self):
            self.deleted = []
            self.sent = []
            self.edited = []

        async def delete_message(self, chat_id, message_id):
            self.deleted.append((chat_id, message_id))

        async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
            self.sent.append(text)
            return SimpleNamespace(message_id=len(self.sent))

        async def edit_message_text(self, chat_id, message_id, text, parse_mode=None, reply_markup=None):
            self.edited.append((chat_id, message_id, text))

    world_svc.CARAVANS.clear()
    world_svc.CARAVAN_HITS.clear()
    chat_k = 940003
    async with session_scope() as s:
        await users.get_or_create(s, tg(8831, "cvk", "غارتگر"))
        await s.commit()
    kcv = world_svc.caravan_spawn(chat_k)
    kcv["hp"] = 1
    kcv["message_id"] = 888
    botk = _CvBot()

    class _CvQ:
        def __init__(self, chat_id, mid):
            self.message = SimpleNamespace(chat_id=chat_id, message_id=mid)
            self.answers = []

        async def answer(self, text, show_alert=False):
            self.answers.append(text)

    upd_k = SimpleNamespace(
        callback_query=_CvQ(chat_k, 888),
        effective_user=tg(8831, "cvk", "غارتگر"),
        effective_chat=SimpleNamespace(id=chat_k, type="group"),
        message=None,
    )
    await world_h.caravan_hit_cb(upd_k, SimpleNamespace(bot=botk))
    check("کیل کاروان: برد پاک شد و «غارت شد» تازه اومد، ادیت بعد ضربه نداریم",
          (chat_k, 888) in botk.deleted
          and any("💀 کاروان غارت شد" in t for t in botk.sent)
          and any("🏆 نفر اول" in t for t in botk.sent)
          and not botk.edited, str(botk.sent[0][:60] if botk.sent else "-"))

    # انقضا: جاب تیک برد رو پاک می‌کنه و «رد شد» تازه می‌فرسته
    world_svc.CARAVANS.clear()
    world_svc.CARAVAN_HITS.clear()
    cvx = world_svc.caravan_spawn(940004)
    cvx["expires_at"] = now_utc() - timedelta(seconds=5)
    cvx["damages"][esc_uid] = 70
    cvx["names"][esc_uid] = "دیررس"
    cvx["message_id"] = 999
    botx = _CvBot()
    old_chance = config.CARAVAN_SPAWN_CHANCE
    config.CARAVAN_SPAWN_CHANCE = 0  # اسپون تصادفی تو تیک این تست خاموشه
    try:
        await jobs_h.caravan_job(SimpleNamespace(bot=botx))
    finally:
        config.CARAVAN_SPAWN_CHANCE = old_chance
    check("انقضای کاروان: برد پاک شد و «رد شد» تازه اومد",
          (940004, 999) in botx.deleted
          and any("🚛 کاروان از محله رد شد" in t for t in botx.sent)
          and any("⚔️ دمیج: 70" in t for t in botx.sent), str(botx.deleted))

    # تایمر رفرش: برد فعال هر 2 دقیقه ادیت میشه
    world_svc.CARAVANS.clear()
    world_svc.CARAVAN_HITS.clear()
    cvr = world_svc.caravan_spawn(940005)
    cvr["message_id"] = 4321
    cvr["damages"][esc_uid] = 33
    cvr["names"][esc_uid] = "دیررس"
    botr = _CvBot()
    await jobs_h.caravan_refresh_job(SimpleNamespace(bot=botr))
    check("تایمر 2 دقیقه‌ای برد کاروان رو با دمیج تازه ادیت می‌کنه",
          any(mid == 4321 and "📊 جدول دمیج" in t
              and "33 دمیج" in t for _, mid, t in botr.edited), str(botr.edited))
    world_svc.CARAVANS.clear()
    world_svc.CARAVAN_HITS.clear()

    # ═══ این دور: دمیج چرخان کاروان | اسپون دستی ادمین | عضویت اجباری 🔒 | آمار پنل ═══
    from telegram.error import BadRequest as _BR
    from telegram.ext import ApplicationHandlerStop as _AHS
    from handlers import gate as gate_h
    from services import forcejoin as fj_svc

    # ── دمیج کاروان دیگه ثابت نیس، ±20% می‌چرخه ──
    async with session_scope() as s:
        vu, _ = await users.get_or_create(s, tg(8862, "cvd", "چرخان"))
        await s.commit()
        world_svc.caravan_spawn(960001)
        world_svc.CARAVANS[960001]["hp"] = 10_000_000
        rolls = []
        for _ in range(80):
            world_svc.CARAVAN_HITS.clear()
            r = await world_svc.caravan_attack(s, 960001, vu, 100)
            rolls.append(r["dmg"])
        await s.commit()
    world_svc.CARAVANS.clear()
    world_svc.CARAVAN_HITS.clear()
    check("دمیج کاروان می‌چرخه و همیشه توی بازه ±20% می‌مونه",
          len(set(rolls)) >= 10 and all(80 <= d <= 120 for d in rolls),
          f"{min(rolls)} تا {max(rolls)}، {len(set(rolls))} مقدار متفاوت")

    # ── «تی اسپان کاروان» ادمین توی گروه اسپون می‌کنه ──
    class _SpawnChat(SimpleNamespace):
        def __init__(self, chat_id, uid):
            super().__init__(
                message=SimpleNamespace(calls=[], message_id=777),
                effective_user=SimpleNamespace(id=uid, username="adm1", first_name="ادمین", is_bot=False),
                effective_chat=SimpleNamespace(id=chat_id, type="group"),
            )

        async def _noop(self):
            return None

    sp_chat = 950001
    upd_sp = _SpawnChat(sp_chat, 1001)

    async def _reply(text, reply_markup=None, **kw):
        upd_sp.message.calls.append((text, reply_markup))
        return SimpleNamespace(message_id=777)
    upd_sp.message.reply_html = _reply
    await world_h.caravan_spawn_cmd(upd_sp, None)
    cvs = world_svc.caravan_active(sp_chat)
    check("«تی اسپان کاروان» کاروان آورد و بردش ثبت شد",
          cvs is not None and cvs["message_id"] == 777
          and upd_sp.message.calls and "🚛 کاروان وارد محله شد" in upd_sp.message.calls[0][0])
    await world_h.caravan_spawn_cmd(upd_sp, None)
    check("کاروان فعال که هست دوبل اسپون نمیشه", "کاروان فعال" in upd_sp.message.calls[-1][0])
    upd_sp.message.calls.clear()
    upd_no = _SpawnChat(sp_chat, 6001)
    upd_no.message.reply_html = _reply
    await world_h.caravan_spawn_cmd(upd_no, None)
    check("اسپان دستی توسط غیرادمین کاملاً بی‌صداس", not upd_sp.message.calls)
    world_svc.CARAVANS.clear()

    # ── سرویس عضویت اجباری: ست/خاموش/پاک ──
    check("فرمت‌های کانال درست پارس میشن",
          fj_svc.parse_input("@abc12345") == ("@abc12345", "https://t.me/abc12345")
          and fj_svc.parse_input("https://t.me/abc12345") == ("@abc12345", "https://t.me/abc12345")
          and fj_svc.parse_input("-1001234567890 https://t.me/+xyz") == ("-1001234567890", "https://t.me/+xyz")
          and fj_svc.parse_input("-1001234567890") is None
          and fj_svc.parse_input("سلام") is None)

    async with session_scope() as s:
        await fj_svc.set_channel(s, "@teriakytest", "https://t.me/teriakytest")
        await s.commit()
    async with session_scope() as s:
        st = await fj_svc.get_settings(s)
        active = await fj_svc.is_active(s)
        await s.commit()
    check("کانل ست شد و عضویت اجباری فعاله",
          active and st["channel"] == "@teriakytest" and st["on"], str(st))

    # ── گیت: غیرعضو بلاک میشه و آپدیتش نگه داشته میشه ──
    gate_h.PENDING.clear()
    gate_h._LAST_GATE.clear()

    class _FjBot:
        def __init__(self, member=False):
            self.member_flag = member
            self.sent = []

        async def get_chat_member(self, chat, uid):
            if self.member_flag:
                return SimpleNamespace(status="member")
            raise _BR("User not found")

        async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
            self.sent.append((chat_id, text))
            return SimpleNamespace(message_id=len(self.sent))

    class _FjApp:
        def __init__(self, bot):
            self.bot = bot
            self.replayed = []

        async def process_update(self, upd):
            self.replayed.append(upd)

    bot_g = _FjBot(member=False)
    app_g = _FjApp(bot_g)
    ctx_g = SimpleNamespace(bot=bot_g, application=app_g)

    upd = _text_update("تریاکی شاپ", uid=8860, uname="gate1", fname="گیت‌خور")
    stopped = False
    try:
        await gate_h.gate_messages(upd, ctx_g)
    except _AHS:
        stopped = True
    g_body, g_kw = (upd.message.calls[-1][1], upd.message.calls[-1][2]) if upd.message.calls else ("", {})
    g_markup = g_kw.get("reply_markup")
    g_btns = [b for row in (g_markup.inline_keyboard if g_markup else []) for b in row]
    check("غیرعضو گیت خورد و پیام دکمه‌دار گرفت، دستورشم نزدیکه",
          stopped and "عضویت اجباری" in g_body
          and any(getattr(b, "url", None) == "https://t.me/teriakytest" for b in g_btns)
          and any(getattr(b, "callback_data", None) == "fj:check" for b in g_btns)
          and gate_h.PENDING.get(8860) is upd, g_body[:60])

    upd_adm = _text_update("تریاکی شاپ", uid=1001, uname="adm1", fname="ادمین")
    await gate_h.gate_messages(upd_adm, ctx_g)
    check("ادمین دور گیت رد میشه", not upd_adm.message.calls and 1001 not in gate_h.PENDING)

    class _FjQ:
        def __init__(self, uid):
            self.uid = uid
            self.answers = []
            self.edited = []
            self.message = SimpleNamespace(chat_id=-1008860, message_id=55)

        async def answer(self, text="", show_alert=False):
            self.answers.append(text)

        async def edit_message_text(self, text, parse_mode=None):
            self.edited.append(text)

    def _fj_upd(uid=8860, ctype="private"):
        return SimpleNamespace(
            callback_query=None,
            effective_user=SimpleNamespace(id=uid, username="gate1", first_name="گیت‌خور", is_bot=False),
            effective_chat=SimpleNamespace(id=-1008860, type=ctype),
            message=None,
        )

    q1 = _FjQ(8860)
    updq = _fj_upd()
    updq.callback_query = q1
    await gate_h.gate_confirm(updq, ctx_g)
    check("تایید قبل از عضو شدن رد میشه و دستور هنوز نگهداشته‌ست",
          any("هنوز عضو" in a for a in q1.answers) and not q1.edited
          and gate_h.PENDING.get(8860) is upd)

    bot_g.member_flag = True
    q2 = _FjQ(8860)
    updq2 = _fj_upd()
    updq2.callback_query = q2
    await gate_h.gate_confirm(updq2, ctx_g)
    check("تایید بعد از عضو شدن، ✅ و ادامه اجرای همون دستور",
          any("تایید شد" in a for a in q2.answers)
          and any("خوش اومدی" in e for e in q2.edited)
          and gate_h.PENDING.get(8860) is None
          and app_g.replayed == [upd], str(len(app_g.replayed)))

    upd2 = _text_update("تریاکی شاپ", uid=8860, uname="gate1", fname="گیت‌خور")
    await gate_h.gate_messages(upd2, ctx_g)
    check("عضو شده دیگه گیت نمی‌خوره", not upd2.message.calls)

    # ── گیت فقط پی‌وی‌ـه، تو گروه همه‌چی مثل قبل عادیه ──
    bot_g.member_flag = False
    upd_grp = _text_update("تریاکی شاپ", uid=8860, uname="gate1", fname="گیت‌خور")
    upd_grp.effective_chat = SimpleNamespace(id=-100111, type="supergroup")
    await gate_h.gate_messages(upd_grp, ctx_g)
    check("غیرعضو تو گروه دستور می‌زنه، گیت نمیاد", not upd_grp.message.calls and 8860 not in gate_h.PENDING)

    q_grp = _FjQ(8860)
    upd_gc = _fj_upd(ctype="supergroup")
    upd_gc.callback_query = q_grp
    await gate_h.gate_callbacks(upd_gc, ctx_g)
    check("دکمه غیرعضو تو گروه هم آزاده", not q_grp.answers and not gate_h.PENDING.get(8860))

    bot_g.member_flag = False
    fj_svc.member_cache_drop(8860)  # کش قدیمی عضویتش رو می‌پرونیم، وضعیت تازه (مثل بعد انقضا/رویداد)
    async with session_scope() as s:  # ردیفش هم تازه‌چک‌شده‌ست، خالیش می‌کنیم تا باز چک واقعی بخوره
        gu = await users.get_by_tg(s, 8860)
        gu.fj_member_status = gu.fj_checked_at = gu.fj_left_at = None
        await s.commit()
    qc = _FjQ(8860)
    updc = _fj_upd()
    updc.callback_query = qc
    stopped = False
    try:
        await gate_h.gate_callbacks(updc, ctx_g)
    except _AHS:
        stopped = True
    check("دکمه غیرعضو هم گیت میشه و پیام لینک فقط یه بار میره",
          stopped and any("عضو شو" in a for a in qc.answers)
          and len(bot_g.sent) == 1 and "عضویت اجباری" in bot_g.sent[0][1]
          and gate_h.PENDING.get(8860) is updc)
    try:
        await gate_h.gate_callbacks(updc, ctx_g)
    except _AHS:
        pass
    check("پیام گیت کالبکی پشت سر هم اسپم نمیشه", len(bot_g.sent) == 1)

    # ── خاموش کردن، کاملاً عبوری ──
    gate_h.PENDING.pop(8860, None)  # آپدیت کالبکی که تو تست قبلی گذاشتیم
    async with session_scope() as s:
        await fj_svc.set_enabled(s, False)
        await s.commit()
    upd3 = _text_update("تریاکی شاپ", uid=8860, uname="gate1", fname="گیت‌خور")
    await gate_h.gate_messages(upd3, SimpleNamespace(bot=_FjBot(member=False), application=app_g))
    check("عضویت اجباری غیرفعال، هیچ بلاکی نداره", not upd3.message.calls and 8860 not in gate_h.PENDING)

    # ── ست کانال از طریق پنل (پیام بعدی ادمین) ──
    async with session_scope() as s:
        adm, _ = await users.get_or_create(s, tg(1001, "adm1", "ادمین یک"))
        adm.pending_action = "fjchan"
        await s.commit()
    upd4 = _text_update("@fjchan2", uid=1001, uname="adm1", fname="ادمین یک")
    try:
        await pending_h.capture(upd4, None)
    except Exception:
        pass
    async with session_scope() as s:
        st2 = await fj_svc.get_settings(s)
        adm2 = await users.get_by_tg(s, 1001)
        pend = adm2.pending_action
        await s.commit()
    check("ست کانال با پیام بعدی پنل انجام شد و pending خالی شد",
          st2["channel"] == "@fjchan2" and st2["link"] == "https://t.me/fjchan2"
          and st2["on"] and pend is None, str(st2))

    async with session_scope() as s:
        await fj_svc.clear_channel(s)
        await s.commit()
    async with session_scope() as s:
        off = await fj_svc.is_active(s)
        await s.commit()
    check("حذف کانال گیت رو کامل پاک می‌کنه", not off)

    # ── 📊 آمار پنل ادمین (قالب بخش‌بندی‌شده: عملکرد و بازیکنان بالا، گروه‌ها ته لیست) ──
    from handlers import admin as admin_h
    stats_txt = await admin_h._stats_text()
    check("آمار پنل ادمین همه بخش‌های قالب جدید رو داره",
          all(x in stats_txt for x in ["📊 آمار زنده ربات", "<b>⚡️ عملکرد</b>", "🚀 زمان پاسخ ربات:",
                                       "📡 پینگ تلگرام:", "⚙️ پردازش داخلی:", "<b>👥 بازیکنان</b>",
                                       "⚡️ فعال ۱ ساعت اخیر:", "👤 فعال ۲۴ ساعت اخیر:",
                                       "🆕 بازیکنان جدید:", "🌍 کل بازیکنان:", "📈 نرخ فعالیت: %",
                                       "<b>🌍 وضعیت محله</b>", "🏴 تیم‌ها:", "🐕 سگ‌ها:",
                                       "🌱 محصولات در حال رشد:", "🚛 کاروان‌های فعال:",
                                       "<b>💰 اقتصاد</b>", "💵 تی‌پوینت کل:", "🏦 موجودی بانک:",
                                       "💸 دست بازیکنان:", "<b>🔥 فعالیت ۲۴ ساعت اخیر</b>",
                                       "⛏️ استخراج:", "⚔️ حمله:", "🎰 قمار:", "📊 مجموع اکشن‌ها:",
                                       "<b>🏘 گروه‌ها</b>", "🟢 فعال ۱ ساعت اخیر:",
                                       "👥 فعال ۲۴ ساعت اخیر:", "🌐 کل گروه‌ها:"]), stats_txt[:60])
    check("ترتیب بخش‌ها مثل قالبه: عملکرد، بازیکنان، اقتصاد، فعالیت و تهش گروه‌ها",
          stats_txt.index("<b>⚡️ عملکرد</b>") < stats_txt.index("<b>👥 بازیکنان</b>")
          < stats_txt.index("<b>💰 اقتصاد</b>") < stats_txt.index("<b>🔥 فعالیت ۲۴ ساعت اخیر</b>")
          < stats_txt.index("<b>🏘 گروه‌ها</b>") < stats_txt.index("⏱️ آمار"))
    check("آمار به خط رفرش زنده ختم میشه",
          stats_txt.endswith("⏱️ آمار زنده‌ست، با 🔃 به‌روزرسانی میشه"))

    # ── 📊 بخش‌های جدید آمار پنل ادمین ──
    import re as _re

    from sqlalchemy import func as _func
    from sqlalchemy import text as _sa_text

    from handlers import common as common_h
    from models import ActionEvent
    from services import actionlog as alog

    def _stat_ints(text: str, key: str) -> list[int]:
        """عددهای بعد از key تو خطش (کاما حذف میشه)، پیدا نشد لیست خالی
        فقط بعد از لیبل گرفته میشن که عدد فارسی لیبل (مثل «۲۴ ساعت») یا شماره‌های قبلش تو خط جمع‌بندی جمع نخوره"""
        for line in text.splitlines():
            if key in line:
                line = line[line.index(key) + len(key):]
                return [int(x.replace(",", "")) for x in _re.findall(r"[\d,]+", line)]
        return []

    def _stat_int(text: str, key: str):
        nums = _stat_ints(text, key)
        return nums[0] if nums else None

    st_all = await admin_h._stats_text()
    check("بخش‌های خلاصه آمار قالب جدید همه تو پیامن",
          all(x in st_all for x in [
              "🚀 زمان پاسخ ربات:", "📡 پینگ تلگرام:", "⚙️ پردازش داخلی:",
              "👤 فعال ۲۴ ساعت اخیر:", "🆕 بازیکنان جدید:", "🌍 کل بازیکنان:",
              "🌐 کل گروه‌ها:", "👥 فعال ۲۴ ساعت اخیر:",
              "🏴 تیم‌ها:", "🐕 سگ‌ها:", "💵 تی‌پوینت کل:", "🏦 موجودی بانک:", "💸 دست بازیکنان:",
              "📊 مجموع اکشن‌ها:", "⏱️ آمار زنده‌ست، با 🔃 به‌روزرسانی میشه",
          ]) and st_all.endswith("⏱️ آمار زنده‌ست، با 🔃 به‌روزرسانی میشه"))
    check("بدون بات، پینگ و زمان پاسخ نامعلومن و کرش نمی‌ده",
          "📡 پینگ تلگرام: ➖ نامعلوم" in st_all and "🚀 زمان پاسخ ربات: ➖ نامعلوم" in st_all)

    # ── 🏆 فعال‌ترین گروه‌های این ساعت تو آمار ادمین (سطل ساعت جاری ایران) ──
    from utils import now_iran as _nir_stat
    _bucket_now = f"{_nir_stat().date().isoformat()}-{_nir_stat().hour:02d}"
    async with session_scope() as s:
        g1s = await s.get(GroupActivity, -99000101)
        if g1s is None:
            g1s = GroupActivity(chat_id=-99000101)
            s.add(g1s)
        g1s.title, g1s.hour_key, g1s.msgs_hour = "گروه داغ محله", _bucket_now, 777
        g2s = await s.get(GroupActivity, -99000202)
        if g2s is None:
            g2s = GroupActivity(chat_id=-99000202)
            s.add(g2s)
        g2s.title, g2s.hour_key, g2s.msgs_hour = "گروه دوم بازار", _bucket_now, 12
        g3s = await s.get(GroupActivity, -99000303)
        if g3s is None:
            g3s = GroupActivity(chat_id=-99000303)
            s.add(g3s)
        g3s.title, g3s.hour_key, g3s.msgs_hour = "گروه کهنه دیشب", "2000-01-01-00", 9999  # سطل قدیمی
        # پلیرای دیده‌شده هر گروه، برای شمارش «تعداد پلیرای هر گروه» تو آمار
        s.add(GroupPlayer(chat_id=-99000101, user_tg=7301))
        s.add(GroupPlayer(chat_id=-99000101, user_tg=7305))
        s.add(GroupPlayer(chat_id=-99000101, user_tg=99, last_active_at=now_utc() - timedelta(days=2)))  # قدیمی نمیشمره
        s.add(GroupPlayer(chat_id=-99000202, user_tg=7309))
        await s.commit()
    st_top = await admin_h._stats_text()
    check("بخش فعال‌ترین گروه‌های این ساعت با مدال و شمارنده دستور میاد",
          "<b>🏆 فعال‌ترین گروه‌های این ساعت</b>" in st_top
          and "🥇 گروه داغ محله" in st_top
          and "تعداد دستورات 1ساعت اخیر: 777" in st_top
          and "تعداد دستورات 1ساعت اخیر: 12" in st_top,
          " | ".join(st_top.splitlines()[-10:-3])[:220])
    check("پلیرای فعال هر گروه (۱ ساعت اخیرش) زیر اسمش میاد",
          "پلیرای فعال: 2 | تعداد دستورات 1ساعت اخیر: 777" in st_top
          and "پلیرای فعال: 1 | تعداد دستورات 1ساعت اخیر: 12" in st_top,
          " | ".join(st_top.splitlines()[-10:-3])[:260])
    check("گروه سطل قدیمی ساعت دیگه تو فعال‌ترین‌ها نمیاد",
          "گروه کهنه دیشب" not in st_top)

    # ── 🏘 بخش گروه‌ها: فعال ۱ و ۲۴ ساعت اخیر و کل ──
    async with session_scope() as s:
        # سه گروه با فعالیت‌های متفاوت: نیم ساعت پیش، پنج ساعت پیش، سه روز پیش
        gd1 = await s.get(GroupActivity, -99000401)
        if gd1 is None:
            gd1 = GroupActivity(chat_id=-99000401, title="گروه تازه‌نفس")
            s.add(gd1)
        gd1.last_active_at = now_utc() - timedelta(minutes=30)
        gd2 = await s.get(GroupActivity, -99000402)
        if gd2 is None:
            gd2 = GroupActivity(chat_id=-99000402, title="گروه امروزی")
            s.add(gd2)
        gd2.last_active_at = now_utc() - timedelta(hours=5)
        gd3 = await s.get(GroupActivity, -99000403)
        if gd3 is None:
            gd3 = GroupActivity(chat_id=-99000403, title="گروه باستانی")
            s.add(gd3)
        gd3.last_active_at = now_utc() - timedelta(days=3)
        await s.commit()
    st_g = await admin_h._stats_text()
    _gh, _gd, _gt = (_stat_int(st_g, "🟢 فعال ۱ ساعت اخیر:"),
                     _stat_int(st_g, "👥 فعال ۲۴ ساعت اخیر:"),
                     _stat_int(st_g, "🌐 کل گروه‌ها:"))
    check("پنجره‌های گروه لجیک درست دارن: ۱ ساعته کوچکترین، ۲۴ ساعته وسط، کل بزرگترینه",
          _gh < _gd < _gt, f"{_gh}/{_gd}/{_gt}")

    # ── ⌨️ فعالیت گروه فقط با دستور سنجیده میشه، چت عادی ملت حساب نیس ──
    from handlers import pending as pending_h_cmd
    world_svc._PLAYER_MARK.clear()

    def _gmsg(txt, uid, uname, fname):
        """آپدیت فیک پیام گروهی، برای تست capture و شمارش فقط-دستورها"""
        msg = _Msg(text=txt, calls=[], chat_id=-99000505)
        return SimpleNamespace(
            message=msg, effective_message=msg,
            effective_user=SimpleNamespace(id=uid, username=uname, first_name=fname, is_bot=False),
            effective_chat=SimpleNamespace(id=-99000505, type="supergroup", title="گروه گپ"),
            callback_query=None,
        )

    await pending_h_cmd.capture(_gmsg("سلام بچه‌ها چه خبرا", 7367, "chatter", "حرف‌زن"), None)
    await pending_h_cmd.capture(_gmsg("تریاکی کنده کاری", 7368, "cmder", "دستوری"), None)
    await pending_h_cmd.capture(_gmsg("بانک", 7369, "cmder2", "دستوری۲"), None)
    async with session_scope() as s:
        g_cmd = await s.get(GroupActivity, -99000505)
        gp1 = await s.get(GroupPlayer, (-99000505, 7368))
        gp0 = await s.get(GroupPlayer, (-99000505, 7367))
        await s.commit()
    check("چت عادی شمرده نمیشه ولی هر دستور (پیشوندی یا کلیدواژه) یه شمارش میخوره",
          g_cmd is not None and g_cmd.msgs_hour == 2 and g_cmd.title == "گروه گپ",
          str(g_cmd.msgs_hour if g_cmd else None))
    check("پلیر فقط وقتی دیده‌شده ثبت میشه که دستور بزنه نه چت کنه",
          gp1 is not None and gp0 is None)

    # ── ⌨️ میانگین دستور تو دقیقه (نمونه تازه شمرده میشه، کهنه نه) ──
    import time as _tm
    common_h._CMD_TIMES.clear()
    st_noc = await admin_h._stats_text()
    check("بدون نمونه، نرخ دستور «هنوز نمونه‌ای نیس» می‌خوره",
          "⌨️ میانگین دستور تو دقیقه: هنوز نمونه‌ای نیس" in st_noc)
    for _i in range(5):
        common_h.note_cmd()
    common_h._CMD_TIMES.insert(0, _tm.time() - 3600)  # کهنه، بیرون پنجره نمیشمره
    _r0, _rn = common_h.cmd_per_min()
    st_rc = await admin_h._stats_text()
    check("نرخ دستور تو دقیقه روی پنجره کانفیگ حساب میشه و خط آمار پر میشه",
          _rn == 5 and abs(_r0 - 5 / config.CMD_RATE_WINDOW_MIN) < 1e-9
          and "⌨️ میانگین دستور تو دقیقه: 0.5" in st_rc,
          f"{_r0} | {[l for l in st_rc.splitlines() if '⌨️ میانگین' in l]}")
    check("capture با دستور واقعی نمونه نرخ رو هم ثبت می‌کنه",
          _tm.time() - common_h._CMD_TIMES[-1] < 60)
    common_h._CMD_TIMES.clear()

    # ── 🔁 جاب ادیت ساعتی آمار: آدرس پیام یادش می‌مونه و خودش ادیت می‌زنه ──
    class _EditBot:
        def __init__(self):
            self.edits = []

        async def get_me(self):
            return SimpleNamespace(id=1)

        async def edit_message_text(self, text, **k):
            self.edits.append((text, k))
            return SimpleNamespace(message_id=k.get("message_id"))

    upd_st = _fake_update("adm:stats:0", uid=1001)
    upd_st.callback_query.message.chat_id = 4242
    upd_st.callback_query.message.message_id = 777
    await admin_h.admin_cb(upd_st, SimpleNamespace(bot=_EditBot()))
    async with session_scope() as s:
        _ref = await team_svc.meta_get(s, admin_h.STATS_MSG_META_KEY)
        await s.commit()
    check("باز کردن آمار، آدرس آخرین پیامش برای جاب یاد می‌مونه", _ref == "4242:777", str(_ref))

    _jb = _EditBot()
    await admin_h.stats_autoedit_job(SimpleNamespace(bot=_jb))
    check("جاب ساعتی پیام آمار ذخیره‌شده رو با کیبوردش ادیت می‌کنه",
          len(_jb.edits) == 1 and _jb.edits[0][1].get("chat_id") == 4242
          and _jb.edits[0][1].get("message_id") == 777
          and "📊 آمار زنده ربات" in _jb.edits[0][0], str(_jb.edits[:1])[:160])

    async with session_scope() as s:
        await team_svc.meta_set(s, admin_h.STATS_MSG_META_KEY, "")
        await s.commit()
    _jb2 = _EditBot()
    await admin_h.stats_autoedit_job(SimpleNamespace(bot=_jb2))
    check("بدون آدرس ذخیره‌شده جاب کاری نمی‌کنه", not _jb2.edits)

    class _DeadBot(_EditBot):
        async def edit_message_text(self, text, **k):
            raise RuntimeError("deleted")

    async with session_scope() as s:
        await team_svc.meta_set(s, admin_h.STATS_MSG_META_KEY, "1:2")
        await s.commit()
    try:
        await admin_h.stats_autoedit_job(SimpleNamespace(bot=_DeadBot()))
        _dead_ok = True
    except Exception:
        _dead_ok = False
    check("ادیت ناموفق (پیام پاک‌شده) کرش نمی‌ده و بی‌صدا رد میشه", _dead_ok)

    class _FakeBot:
        async def get_me(self):
            await asyncio.sleep(0.001)
            return SimpleNamespace(id=1)

    common_h._PROC_TIMES.clear()
    for _i in range(3):
        common_h.note_proc_time(0.150)
    st_ping = await admin_h._stats_text(_FakeBot())
    _pl = [l for l in st_ping.splitlines() if "پینگ تلگرام:" in l][0]
    _rl = [l for l in st_ping.splitlines() if "زمان پاسخ ربات:" in l][0]
    _il = [l for l in st_ping.splitlines() if "پردازش داخلی:" in l][0]
    check("پینگ تلگرام با بات زنده عدد می‌گیره",
          bool(_re.search(r"[\d,]+ms", _pl)), _pl)
    check("زمان پاسخ ربات = پینگ + پردازش داخلی، با چراغ سبز",
          bool(_re.search(r"[\d,]+ms 🟢", _rl)) and _il.startswith("⚙️ پردازش داخلی: 150ms"),
          f"{_rl} | {_il}")
    _ping_v = int(_re.search(r"([\d,]+)ms", _pl).group(1).replace(",", ""))
    _resp_v = int(_re.search(r"([\d,]+)ms", _rl).group(1).replace(",", ""))
    check("عدد زمان پاسخ دقیقاً جمع پینگ و پردازشه",
          _resp_v == _ping_v + 150, f"{_ping_v}+150 vs {_resp_v}")
    common_h._PROC_TIMES.clear()

    # ── هوک‌های لاگ رویداد تو چهار مسیر وصلن ──
    _base_dir = os.path.dirname(os.path.abspath(__file__))
    _src = {p: open(os.path.join(_base_dir, *p.split("/")), encoding="utf-8").read()
            for p in ["services/battle.py", "services/pvattack.py",
                      "services/world.py", "handlers/mine.py"]}
    check("هوک لاگ رویداد: نبرد گروهی + حمله پی‌وی + قمارخانه + کنده‌کاری",
          'actionlog.log(session, "battle")' in _src["services/battle.py"]
          and 'actionlog.log(session, "pvattack")' in _src["services/pvattack.py"]
          and 'actionlog.log(session, "casino")' in _src["services/world.py"]
          and 'actionlog.log(s, "mine")' in _src["handlers/mine.py"])

    # ── شمارش رویدادهای ۲۴ ساعته، فقط COUNT توی SQL (بخش فعالیت ۲۴ ساعت اخیر) ──
    st_b0 = await admin_h._stats_text()
    m0, a0, c0, s0 = (_stat_int(st_b0, "⛏️ استخراج:"), _stat_int(st_b0, "⚔️ حمله:"),
                      _stat_int(st_b0, "🎰 قمار:"), _stat_int(st_b0, "📊 مجموع اکشن‌ها:"))
    async with session_scope() as s:
        await alog.log(s, "battle")
        await alog.log(s, "battle")
        await alog.log(s, "pvattack")
        await alog.log(s, "mine")
        await alog.log(s, "mine")
        await alog.log(s, "mine")
        await alog.log(s, "casino")
        s.add(ActionEvent(action="mine", at=now_utc() - timedelta(days=2)))  # قدیمی، نباید شمرده شه
        await s.commit()
    st_b1 = await admin_h._stats_text()
    m1, a1v, c1, s1 = (_stat_int(st_b1, "⛏️ استخراج:"), _stat_int(st_b1, "⚔️ حمله:"),
                       _stat_int(st_b1, "🎰 قمار:"), _stat_int(st_b1, "📊 مجموع اکشن‌ها:"))
    check("اکشن‌های ۲۴ساعته: استخراج و حمله (گروهی+پی‌وی جمع‌شده) و قمار هرکدوم خط خودشون",
          m1 == m0 + 3 and a1v == a0 + 3 and c1 == c0 + 1, f"{m0},{a0},{c0} -> {m1},{a1v},{c1}")
    check("مجموع اکشن‌ها برابر جمع سه خطه",
          s0 == m0 + a0 + c0 and s1 == m1 + a1v + c1, f"{s0} -> {s1}")

    # ── اکشن ناشناس نادیده گرفته میشه ──
    async with session_scope() as s:
        n_x0 = (await s.execute(select(_func.count(ActionEvent.id)))).scalar() or 0
        await alog.log(s, "hack")
        await s.commit()
    async with session_scope() as s:
        n_x1 = (await s.execute(select(_func.count(ActionEvent.id)))).scalar() or 0
        await s.commit()
    check("اکشن ناشناس لاگ نمیشه", n_x1 == n_x0, f"{n_x0}->{n_x1}")

    # ── پاکسازی ردیف‌های قدیمی رویداد موقع درج ──
    async with session_scope() as s:
        s.add(ActionEvent(action="battle", at=now_utc() - timedelta(hours=49)))
        s.add(ActionEvent(action="casino", at=now_utc() - timedelta(hours=50)))
        await s.commit()
    _ch0 = config.ACTION_LOG_PRUNE_CHANCE
    config.ACTION_LOG_PRUNE_CHANCE = 1.0
    try:
        async with session_scope() as s:
            await alog.log(s, "battle")  # با شانس ۱ حتماً پاکسازی می‌کنه
            await s.commit()
    finally:
        config.ACTION_LOG_PRUNE_CHANCE = _ch0
    async with session_scope() as s:
        left_old = (await s.execute(
            select(_func.count(ActionEvent.id)).where(
                ActionEvent.at < now_utc() - timedelta(hours=config.ACTION_LOG_KEEP_HOURS))
        )).scalar() or 0
        await s.commit()
    check("پاکسازی: ردیف‌های قدیمی‌تر از نگه‌داری رویداد حذف میشن", left_old == 0, f"مونده: {left_old}")

    # ── 🆕 تازه‌واردها و فعال‌های ۱ و ۲۴ ساعت اخیر (بخش بازیکنان) ──
    act_h0 = _stat_int(st_b1, "⚡️ فعال ۱ ساعت اخیر:")
    act0 = _stat_int(st_b1, "👤 فعال ۲۴ ساعت اخیر:")
    new0 = _stat_int(st_b1, "🆕 بازیکنان جدید:")
    tot0 = _stat_int(st_b1, "🌍 کل بازیکنان:")
    async with session_scope() as s:
        u_new, _ = await users.get_or_create(s, tg(7309, "newb", "تازه‌وارد"))
        u_new.level = 10
        u_old, _ = await users.get_or_create(s, tg(7305, "oldb", "کهنه‌کار"))
        u_old.level = 40
        u_old.created_at = now_utc() - timedelta(days=2)
        u_old.last_seen_at = now_utc() - timedelta(days=2)  # غیرفعال، تو هیچکدوم از آمارهای ۱/۲۴ ساعته نمیاد
        u_f0, _ = await users.get_or_create(s, tg(7301, "farmx", "کشاورز"))  # تازه‌وارد + لول ۱ فعال
        u_h, _ = await users.get_or_create(s, tg(7365, "hourguy", "یک‌ساعته"))
        u_h.created_at = now_utc() - timedelta(days=3)  # جدید نیس
        u_h.last_seen_at = now_utc() - timedelta(minutes=30)  # ولی تو ۱ ساعت اخیر فعاله
        u_m, _ = await users.get_or_create(s, tg(7366, "dayguy", "روزانه"))
        u_m.created_at = now_utc() - timedelta(days=3)
        u_m.last_seen_at = now_utc() - timedelta(hours=5)  # تو ۲۴ ساعت فعاله ولی ۱ ساعت نه
        await s.commit()
    st_c1 = await admin_h._stats_text()
    check("جدید فقط تازه‌واردها رو میشمره نه کاربرای قدیمی",
          _stat_int(st_c1, "🆕 بازیکنان جدید:") == new0 + 2,
          f"{_stat_int(st_c1, '🆕 بازیکنان جدید:')} vs {new0}")
    check("فعال ۲۴ ساعت اخیر فقط تازه‌فعالا رو میشمره نه کهنه‌کار غیرفعال",
          _stat_int(st_c1, "👤 فعال ۲۴ ساعت اخیر:") == act0 + 4,
          f"{_stat_int(st_c1, '👤 فعال ۲۴ ساعت اخیر:')} vs {act0}")
    check("فعال ۱ ساعت اخیر پنجره تنگ‌تری داره و نیم‌ساعتی تازه رو میشمره ولی پنج‌ساعته رو نه",
          _stat_int(st_c1, "⚡️ فعال ۱ ساعت اخیر:") == act_h0 + 3,
          f"{_stat_int(st_c1, '⚡️ فعال ۱ ساعت اخیر:')} vs {act_h0}")
    check("کل بازیکنان پنج تا ساخته‌شده جدید رو هم میشمره",
          _stat_int(st_c1, "🌍 کل بازیکنان:") == tot0 + 5,
          f"{_stat_int(st_c1, '🌍 کل بازیکنان:')} vs {tot0}")
    _rate_exp = round(_stat_int(st_c1, "👤 فعال ۲۴ ساعت اخیر:") * 100 / _stat_int(st_c1, "🌍 کل بازیکنان:"))
    check("نرخ فعالیت درصد فعال‌های ۲۴ ساعته به کل بازیکنانه",
          _stat_int(st_c1, "📈 نرخ فعالیت: %") == _rate_exp,
          f"{_stat_int(st_c1, '📈 نرخ فعالیت: %')} vs {_rate_exp}")

    # ── 🌱 پلات در حال رشد + 💰 بخش اقتصاد (کل، بانک، دست بازیکنان) ──
    # مبنا از st_c1 (بعد ساخت کاربرا) خونده میشه، اینجا دیگه کاربر تازه‌ای ساخته نمیشه
    gr0 = _stat_int(st_c1, "🌱 محصولات در حال رشد:")
    tot0 = _stat_int(st_c1, "💵 تی‌پوینت کل:")
    bk0 = _stat_int(st_c1, "🏦 موجودی بانک:")
    hd0 = _stat_int(st_c1, "💸 دست بازیکنان:")
    async with session_scope() as s:
        u_f = await users.get_by_tg(s, 7301)
        _now = now_utc()
        s.add(Plot(user_id=u_f.id, status="growing", crop="marijuana",
                   planted_at=_now, ready_at=_now + timedelta(hours=2)))  # واقعاً در حال رشد
        s.add(Plot(user_id=u_f.id, status="growing", crop="marijuana",
                   planted_at=_now - timedelta(hours=9), ready_at=_now - timedelta(hours=1)))  # آماده‌ست نه رشد
        s.add(Plot(user_id=u_f.id, status="empty"))
        u_f.cash += 5000
        u_f.bank_balance += 5000  # واریز تازه به بانک
        await s.commit()
    st_d1 = await admin_h._stats_text()
    check("در حال رشد فقط رشد واقعی (ready_at نگذشته) رو میشمره",
          _stat_int(st_d1, "🌱 محصولات در حال رشد:") == gr0 + 1,
          f"{_stat_int(st_d1, '🌱 محصولات در حال رشد:')}")
    tot1 = _stat_int(st_d1, "💵 تی‌پوینت کل:")
    bk1 = _stat_int(st_d1, "🏦 موجودی بانک:")
    hd1 = _stat_int(st_d1, "💸 دست بازیکنان:")
    check("تی‌پوینت کل جمع نقد و بانکه و هر بخش دقیقه",
          tot1 == tot0 + 10000 and bk1 == bk0 + 5000 and hd1 == hd0 + 5000,
          f"{tot0}->{tot1} ب:{bk0}->{bk1} د:{hd0}->{hd1}")
    check("کل تی‌پوینت برابر جمع بانک و دست بازیکنانه",
          tot1 == bk1 + hd1, f"{tot1} vs {bk1}+{hd1}")

    # ── ⚙️ زمان پردازش داخلی + 🚦 چراغ latency ──
    common_h._PROC_TIMES.clear()
    st_empty = await admin_h._stats_text()
    check("بدون نمونه، پردازش داخلی «هنوز نمونه‌ای نیس» می‌خوره",
          common_h.proc_avg_ms() == (None, 0) and "هنوز نمونه‌ای نیس" in st_empty)
    for _i in range(21):
        common_h.note_proc_time(0.002)
    check("لیست نمونه‌ها از سقف کانفیگ رد نمیشه و قدیمی‌ترین‌ها پاک میشن",
          len(common_h._PROC_TIMES) == config.PROC_SAMPLE_CAP and config.PROC_SAMPLE_CAP == 20,
          str(len(common_h._PROC_TIMES)))
    common_h._PROC_TIMES.clear()
    for _i in range(25):
        common_h.note_proc_time(0.001 * (_i + 1))
    _exp_ms = int(round(sum(common_h._PROC_TIMES) / len(common_h._PROC_TIMES) * 1000.0))
    st_proc = await admin_h._stats_text()
    _prl = [l for l in st_proc.splitlines() if "پردازش داخلی:" in l][0]
    _subl = [l for l in st_proc.splitlines() if l.startswith("└ میانگین")][0]
    check("میانگین آخرین نمونه‌ها با تعدادشون تو خط زیرین آمار فنی میاد",
          f"{_exp_ms}ms" in _prl and _subl == "└ میانگین 20 دستور اخیر", f"{_prl} | {_subl}")
    check("چراغ latency آستانه‌هاش درسته (۵۰۰ و ۱۵۰۰ میلی‌ثانیه)",
          common_h.proc_light(499) == "🟢 تند" and common_h.proc_light(500) == "🟡 وسط"
          and common_h.proc_light(1500) == "🔴 کند" and common_h.proc_light(None) == "➖ نامعلوم")
    common_h._PROC_TIMES.clear()
    _tm = common_h.proc_timer()
    await asyncio.sleep(0.01)
    _tm.done()
    _am, _cm = common_h.proc_avg_ms()
    check("proc_timer زمان واقعی پردازش رو ثبت می‌کنه",
          _cm == 1 and _am is not None and _am >= 9, f"{_am}ms")
    common_h._PROC_TIMES.clear()

    # ── ایندکس‌های لازم برای فیلترهای آمار ──
    async with session_scope() as s:
        ix_u = {r[1] for r in (await s.execute(_sa_text("PRAGMA index_list('users')"))).all()}
        ix_p = {r[1] for r in (await s.execute(_sa_text("PRAGMA index_list('plots')"))).all()}
        ix_e = {r[1] for r in (await s.execute(_sa_text("PRAGMA index_list('action_events')"))).all()}
        await s.commit()
    check("ایندکس‌های آمار ساخته شدن (users.created_at/last_seen_at + plots.status + action_events)",
          {"ix_users_created_at", "ix_users_last_seen_at"} <= ix_u
          and "ix_plots_status" in ix_p
          and {"ix_action_events_action", "ix_action_events_at", "ix_action_events_action_at"} <= ix_e,
          f"{sorted(ix_e)}")

    # ── سیستم شخصیت سگ‌ها کامل حذف شده 💫 ──
    check("دیگه شخصیتی تو کانفیگ و سرویس سگ نیس",
          not hasattr(config, "DOG_PERSONALITIES") and not hasattr(config, "DOG_PERSONALITY_POOLS")
          and not hasattr(dog_svc, "roll_personality") and not hasattr(dog_svc, "personality_of")
          and not hasattr(dog_svc, "ensure_personality") and not hasattr(dog_svc, "dog_defense")
          and not hasattr(dog_svc, "personality_steal_bonus") and not hasattr(dog_svc, "search_luck"))
    check("قیمت غذای سگ‌ها استخون 500 و گوشت 2000 و طلایی 5000 شده",
          [config.DOG_FOODS[k]["price"] for k in ("bone", "meat", "gold")] == [500, 2000, 5000],
          str({k: config.DOG_FOODS[k]["price"] for k in config.DOG_FOODS}))
    check("منحنی لول تیم سخت‌تر شده و نقطه مهاجرت از منحنی قدیمی معلومه",
          config.TEAM_XP_CURVE_BASE == 1000 and config.TEAM_XP_CURVE_EXP == 1.8
          and config.TEAM_XP_CURVE_MIGRATION_FROM == (200, 1.6)
          and team_svc.team_xp_need(1) == 1000)

    # ── رها کردن سگ 🕊 ──
    async with session_scope() as s:
        rl, _ = await users.get_or_create(s, tg(8809, "relea", "رهاکن"))
        rl.level = 20
        rl.cash = 500000
        ok, _ = await dog_svc.buy_dog(s, rl, "kangal", custom_name="ممد")
        assert ok
        ok, _ = await dog_svc.buy_dog(s, rl, "pitbull", custom_name="جباری")
        assert ok
        dogs_rl = await dog_svc.get_user_dogs(s, rl.id)
        before = len(dogs_rl)
        ok, msg = await dog_svc.release_dog(s, rl, dogs_rl[0])
        dogs_rl2 = await dog_svc.get_user_dogs(s, rl.id)
        check("رها کردن سگ کار می‌کنه و برگشتی نداره",
              ok and len(dogs_rl2) == before - 1 and "رها کردی" in msg, msg)
        ok, msg = await dog_svc.buy_dog(s, rl, "kangal", custom_name="ممد۲")
        check("بعد رها همون نژاد دوباره خریدنیه", ok, msg)
        await s.commit()

    # ── کارت سگ سیر + پیشنهاد سگ دیگه ──
    async with session_scope() as s:
        from handlers import dogs as dogs_h2
        sg_user = await users.get_by_tg(s, 1001)
        sg_dogs = await dog_svc.get_user_dogs(s, sg_user.id)
        w = next(d for d in sg_dogs if d.dog_key == "blackwolf")
        o = next(d for d in sg_dogs if d.dog_key == "doberman")
        sg_user.cash = 100000
        for _ in range(5):
            kok, kmsg, _ = await dog_svc.feed_dog(s, sg_user, w, "gold")
            assert kok, kmsg
        card = dogs_h2._dog_card_text(sg_user, w)
        check("کارت سگ سیر متن «سیر شده» رو داره",
              "سیر شده" in card and w.name in card,
              card.replace("\n", " | ")[-160:])
        for _ in range(5):
            kok, kmsg, _ = await dog_svc.feed_dog(s, sg_user, o, "gold")
            assert kok, kmsg
        allt = await dogs_h2._dogs_text(s, sg_user, await dog_svc.get_user_dogs(s, sg_user.id))
        check("همه سیرن، لیست سگ‌ها پر از خط «سیر شده» ـه",
              allt.count("سیر شده") >= 2, allt[:80])
        check("فرمت خط سگ تو لیست (نژاد | لول و تجربه | قدرت | قابلیت)",
              all(x in allt for x in ["🐾 نژاد", "⭐ لول", "از", "💪 قدرت حمله", "🎖"]))
        await s.commit()

    # ── تاریخ شمسی و تایم ایران ──
    check("جلالی: ۲۰۲۴/۳/۲۰ = ۱۴۰۳/۱/۱", gregorian_to_jalali(2024, 3, 20) == (1403, 1, 1))
    check("جلالی: ۲۰۲۶/۷/۲۲ = ۱۴۰۵/۴/۳۱", gregorian_to_jalali(2026, 7, 22) == (1405, 4, 31))
    check("جلالی: ۲۰۲۵/۳/۲۱ = ۱۴۰۴/۱/۱", gregorian_to_jalali(2025, 3, 21) == (1404, 1, 1))
    check("فرمت امروز ایران OK", len(iran_today()) == 10 and iran_today()[4] == "-", iran_today())
    check("فرمت تاریخ شمسی OK", jalali_str(now_utc()).startswith("140") and "/" in jalali_str(now_utc()),
          jalali_str(now_utc()))

    # ── پترن دستورهای جدید ──
    w_pat = re.compile(r"^وضعیت[\s‌]+آب[\s‌]+و[\s‌]+هوا!?$|^آب[\s‌]*و[\s‌]*هوا!?$")
    m_pat = re.compile(r"^وضعیت[\s‌]+بازار!?$|^بازار[\s‌]*سیاه!?$")
    check("پترن «وضعیت آب و هوا» و «آب و هوا»", w_pat.match("وضعیت آب و هوا") and w_pat.match("آب و هوا"))
    check("پترن «وضعیت بازار» و «بازار سیاه»", m_pat.match("وضعیت بازار") and m_pat.match("بازار سیاه"))
    check("پترن «جستجو» | «پناهگاه» | «قمارخانه»",
          re.compile(r"^جستجو!?$").match("جستجو")
          and re.compile(r"^پناهگاه!?$").match("پناهگاه")
          and re.compile(r"^قمارخانه!?$|^قمار!?$").match("قمار"))


    # ═══ آپدیت جدید: بازار 50/50 | متن جدید بازار | قفل کاشت | هلپ دکمه‌دار | /user /addtp /addxp | خوش‌آمد گروه ═══

    # ── مکانیک بازار پویا: حرکت شانسی دور و بر پایه، اشباع سنگین ریزش تند، باند کف/سقف جیتر‌دار ──
    random.seed(21)
    _up_hi = (1 + config.MARKET_MAX_STEP_CHANGE * 1.6) * (1 + config.MARKET_RANDOM_NOISE)
    check("کمیابی (عرضه زیر تقاضا) قیمت رو شانسی بین ۳ تا چهارونیم درصد می‌بره بالا",
          all(1.0 < world_svc._next_market_mult(1.0, 0, 10.0) <= _up_hi + 1e-9
              for _ in range(200)))
    check("اشباع ملایم قیمت رو آروم می‌ده پایین",
          all(0.86 < world_svc._next_market_mult(1.0, 12, 10.0) < 1.0
              for _ in range(200)))
    check("تعادل عرضه و تقاضا قیمت رو تکون نمیده جز نویز ریز",
          all(abs(world_svc._next_market_mult(1.0, 10, 10.0) - 1.0) <= config.MARKET_RANDOM_NOISE + 1e-9
              for _ in range(200)))
    _heavy = [world_svc._next_market_mult(1.0, 50, 10.0) for _ in range(300)]
    _mild = [world_svc._next_market_mult(1.0, 12, 10.0) for _ in range(300)]
    check("فروش خیلی سنگین ریزش رو تا 3 برابر عمیق‌تر می‌کنه (چک کردن بازار می‌صرفه)",
          all(x < 0.93 for x in _heavy) and sum(_heavy) / 300 < sum(_mild) / 300,
          f"heavy avg {sum(_heavy)/300:.3f} vs mild avg {sum(_mild)/300:.3f}")
    check("سقف و کف کلمپ با جیتر دور و بر ±25 درصد می‌شن، دقیق قفل نیس",
          world_svc._next_market_mult(1.299, 0, 10.0) <= config.MARKET_MAX_PRICE_MULTIPLIER + config.MARKET_BAND_JITTER
          and world_svc._next_market_mult(0.701, 999, 10.0) >= config.MARKET_MIN_PRICE_MULTIPLIER - config.MARKET_BAND_JITTER
          and all(1.20 <= world_svc._next_market_mult(1.31, 0, 0.1) <= 1.38 for _ in range(50))
          and all(0.60 <= world_svc._next_market_mult(0.71, 999, 10.0) <= 0.78 for _ in range(50)))
    check("کانفیگ بازار پویا",
          config.MARKET_MAX_PRICE_MULTIPLIER == 1.30 and config.MARKET_MIN_PRICE_MULTIPLIER == 0.70
          and config.MARKET_MAX_STEP_CHANGE == 0.05 and config.MARKET_SELL_SATURATION_MAX == 3.0
          and config.MARKET_BAND_JITTER == 0.08 and config.MARKET_RANDOM_NOISE == 0.025
          and config.MARKET_DEMAND_PER_ACTIVE_PLAYER > 0)

    # ── متن وضعیت بازار پویا، همه محصولات با روند و قیمت کامل ──
    mtxt = world_svc.market_view_text(
        {"marijuana": 1.0862, "gharch": 0.912, "peyote": 1.0, "teriak": 1.1, "cocaine": 0.8,
         "jahannam": 1.2, "eblis": 0.75}, 14340)
    check("متن بازار هدر و توضیح عرضه و تقاضا رو داره",
          "<b>📈 وضعیت بازار سیاه</b>" in mtxt
          and "هر فروشی رو قیمتش اثر می‌ذاره" in mtxt
          and "کمیاب بشه گرون‌تر میشه، اشباع بشه ارزون‌تر" in mtxt
          and "فروش سنگین یه محصول قیمتشو تند می‌ریزه" in mtxt
          and "قبل از کاشت یه چک به بازار بزن" in mtxt)
    check("محصول گرون‌شده با 📈 و قیمت جدید میاد",
          "📈 +8.6%" in mtxt and "💰 قیمت فروش الان: 325 تی‌پوینت" in mtxt,
          mtxt.replace("\n", " | ")[:170])
    check("محصول ارزون‌شده با 📉 و قیمت پایه کامل میاد",
          "📉 -8.8%" in mtxt and "📦 قیمت پایه: 800 تی‌پوینت" in mtxt)
    check("محصول سرِ پایه ⚖️ می‌گیره", "⚖️ +0.0%" in mtxt or "⚖️ 0.0%" in mtxt)
    check("افسانه‌ای‌ها هم تو نمای بازار دیده میشن",
          "جهنم" in mtxt and "ابلیس" in mtxt)
    check("تایمر حرکت بعدی بازار دو خطی",
          "⏳ حرکت بعدی بازار\n3 ساعت و 59 دقیقه دیگه" in mtxt)

    # ── کاشت آزاد تو هر لول: هر بذری که داری رو می‌تونی بکاری، قفل لول فقط روی خرید از شاپه ──
    async with session_scope() as s:
        lk, _ = await users.get_or_create(s, tg(8810, "lockp", "قفلی"))
        lk.level = 2
        await farming.add_seed_stock(s, lk.id, "cocaine", 1)
        lplot = Plot(user_id=lk.id, status="empty")
        s.add(lplot)
        await s.flush()
        ok, msg = await farming.plant(s, lk, lplot, "cocaine")
        check("کاشت کوکائین تو لول 2 موفقه (قفل لول فقط برای خریده)",
              ok and "کاشته شد" in msg, msg)
        ok2, msg2 = await shop_svc.purchase(s, lk, "seed", "cocaine")
        check("ولی خرید همون بذر از شاپ تو لول 2 رد میشه",
              not ok2 and "لول" in msg2, msg2)
        await s.commit()

    # ── کاشت بذر افسانه‌ای (از جستجو/کاروان/کوئست) تو لول 1 هم از هندلر متنی میشه ──
    from handlers import textcmd as textcmd_h2
    async with session_scope() as s:
        au, _ = await users.get_or_create(s, tg(8815, "anylvl", "آزاد"))
        au.level = 1
        await farming.add_seed_stock(s, au.id, "jahannam", 1)
        s.add(Plot(user_id=au.id, status="empty"))
        await s.commit()
    upd = _text_update("تریاکی کاشت جهنم", uid=8815, uname="anylvl", fname="آزاد")
    await textcmd_h2.plant_text(upd, None)
    ptxt = next(c[1] for c in upd.message.calls if "<b>🌱 کاشت</b>" in c[1])
    check("هندلر کاشت متنی بذر جهنم رو تو لول 1 می‌کاره",
          "<b>🌱 کاشت</b>" in ptxt and "کاشته شد" in ptxt and "قابل دسترسه" not in ptxt,
          ptxt[:120])


    # ── هلپ دکمه‌دار: منو | بخش‌ها | 🔙 آموزشات ──
    from handlers import start as start_h2
    check("منوی هلپ متن راهنمای انتخاب بخش رو داره",
          "بخش مورد نظر رو انتخاب کن تا آموزشات لازم رو بهت بدم" in start_h2._HELP_INTRO)
    menu_keys = [k for k, _ in kb2.HELP_MENU]
    check("هر بخش هلپ جایی تو متن‌ها هست",
          set(menu_keys) == set(start_h2.HELP_SECTIONS.keys()), str(menu_keys))
    hkb = kb2.help_menu_kb()
    h_datas = [b.callback_data for row in hkb.inline_keyboard for b in row]
    check("دکمه‌های هلپ برای هر بخش ساخته میشن",
          all(f"help:sec:{k}" in h_datas for k in menu_keys), str(h_datas))
    h_texts = [b.text for row in hkb.inline_keyboard for b in row]
    check("منوی هلپ دکمه 🏠 منوی اصلی هم داره",
          "menu:home" in h_datas and any("منوی اصلی" in t for t in h_texts), str(h_texts[-2:]))
    check("دکمه هوم هلپ ته کیبورده",
          hkb.inline_keyboard[-1][-1].callback_data == "menu:home")
    bkb = kb2.help_back_kb()
    b_datas = [b.callback_data for row in bkb.inline_keyboard for b in row]
    b_texts = [b.text for row in bkb.inline_keyboard for b in row]
    check("دکمه 🔙 آموزشات هست",
          "help:menu" in b_datas and any("آموزشات" in t for t in b_texts), str(b_texts))
    check("کیبورد برگشت هومم داره (تو گروه strip میشه)", "menu:home" in b_datas)  # تو گروه strip میشه
    for must in ("تیم", "نبرد", "سگ", "مزرعه", "شرکت", "انبار", "منابع", "فروشگاه", "شروع بازی",
                 "کنده‌کاری", "قمارخانه", "بانک", "ماموریت", "متفرقه"):
        check(f"بخش «{must}» تو منوی هلپ هست", any(must in title for _, title in kb2.HELP_MENU))

    # بخش سگ‌ها — ویژگی اصلی هر نژاد بدون اعداد دقیق (بالانس‌پذیر)
    dog_sec = start_h2.HELP_SECTIONS["dogs"]
    check("بخش سگ‌ها ویژگی اصلی هر نژاد رو داره",
          all(x in dog_sec for x in [
              "پیتبول", "قدرت حمله بیشتر",
              "دوبرمن", "کولدان حمله",
              "ژرمن شپرد", "تجربه بیشتر از نبرد",
              "کانگال", "دفاع بیشتر",
              "گرگ سیاه", "غارت بیشتر",
          ]))
    check("بخش سگ‌ها دیگه از شخصیت حرف نمی‌زنه (سیستم شخصیت حذف شده)",
          "شخصیت" not in dog_sec)
    check("بخش سگ‌ها تجربه از نبرد و تغییر اسم رو داره",
          "از نبرد تجربه" in dog_sec and "اسم سگ" in dog_sec)
    check("بخش شرکت و منابع و مخفیگاه تو هلپ هستن",
          all(k in start_h2.HELP_SECTIONS for k in ("company", "resources", "shelter", "start", "battle", "shop")))
    check("تو متن هلپ درصد و ضریب دقیق نیس",
          "%" not in start_h2.HELP_SECTIONS["company"] and "%" not in start_h2.HELP_SECTIONS["farm"]
          and "×" not in start_h2.HELP_SECTIONS["resources"])

    upd = _text_update("تریاکی راهنما", uid=8811, uname="helpr", fname="هلپر")
    await start_h2.help_cmd(upd, None)
    hmsg, hk = upd.message.calls[-1][1], upd.message.calls[-1][2].get("reply_markup")
    check("خروجی «راهنما» منوی دکمه‌دار میاره",
          "انتخاب کن" in hmsg and hk is not None
          and any(b.callback_data == "help:sec:farm" for row in hk.inline_keyboard for b in row))
    check("«راهنما» تو پی‌وی دکمه 🏠 منوی اصلی میاره",
          any(b.callback_data == "menu:home" for row in hk.inline_keyboard for b in row))

    # تو گروه دکمه هوم strip میشه ولی بخش‌های هلپ سر جاشونن
    upd_hg = _text_update("تریاکی راهنما", uid=8811, uname="helpr", fname="هلپر")
    upd_hg.effective_chat = SimpleNamespace(id=-100222, type="supergroup")
    await start_h2.help_cmd(upd_hg, None)
    hkg = upd_hg.message.calls[-1][2].get("reply_markup")
    hg_datas = [b.callback_data for row in hkg.inline_keyboard for b in row] if hkg else []
    check("«راهنما» تو گروه هوم strip میشه ولی بخش‌ها میمونن",
          "menu:home" not in hg_datas and "help:sec:farm" in hg_datas, str(hg_datas[-3:]))

    # رفتن تو یه بخش و برگشت با فیک کالبک
    upd = _fake_update("help:sec:team", uid=8811)
    await start_h2.help_section_cb(upd, None)
    edittext = next(c[1] for c in upd.callback_query.calls if c[0] == "edit")
    check("بخش تیم هلپ باز میشه با 🔙 آموزشات",
          "<b>👥 تیم</b>" in edittext and "جوین تیم" in edittext)
    upd = _fake_update("help:menu", uid=8811)
    await start_h2.help_menu_cb(upd, None)
    backtext = next(c[1] for c in upd.callback_query.calls if c[0] == "edit")
    check("برگشت به منوی آموزشات", "بخش مورد نظر رو انتخاب کن" in backtext)

    # ── /user و /addtp و /addxp ادمین ──
    from handlers import admin as admin_h
    async with session_scope() as s:
        victim2, _ = await users.get_or_create(s, tg(8812, "silktoch", "سیلکتاج"))
        victim2.cash = 1000
        victim2.level = 5
        await s.commit()

        check("جستجوی /user با آیدی عددی",
              [u.telegram_id for u in await users.search_users(s, "8812")] == [8812])
        check("جستجوی /user با @یوزرنیم",
              [u.telegram_id for u in await users.search_users(s, "@silktoch")] == [8812])
        check("جستجوی /user با بخشی از اسم",
              any(u.telegram_id == 8812 for u in await users.search_users(s, "سیلک")))
        check("جستجوی پوچ", await users.search_users(s, "ناشناس‌تازه") == [])
        await s.commit()

    # /addtp با کانتکست فیک
    async def _run_admin_cmd(fn, args, uid):
        updx = _text_update("/x", uid=uid, uname="adm", fname="ادمین")
        await fn(updx, SimpleNamespace(args=args))
        return updx

    updx = await _run_admin_cmd(admin_h.addtp_cmd, ["8812", "5000"], 1001)
    async with session_scope() as s:
        t = await users.get_by_tg(s, 8812)
        check("/addtp مستقیم واریز کرد",
              t.cash == 6000 and "واریز شد" in updx.message.calls[-1][1] and "6,000" in updx.message.calls[-1][1],
          updx.message.calls[-1][1][:100])

    updx = await _run_admin_cmd(admin_h.addxp_cmd, ["8812", "700"], 1001)
    async with session_scope() as s:
        t = await users.get_by_tg(s, 8812)
        check("/addxp مستقیم xp داد", t.xp > 0 or t.level > 5, f"lvl={t.level} xp={t.xp}")
        check("گزارش addxp تمیز و بدون تبریک چسبیده‌ست",
              any("تجربه دادی" in c[1] and "لول‌آپ شدی" not in c[1] for c in updx.message.calls),
              str([c[1][:60] for c in updx.message.calls]))
        check("تبریک لول‌آپ به‌صورت پیام جدا با قالب اورجینال اومد",
              any("لول‌آپ شدی (" in c[1] and c[1].startswith("🎉 تبریک") for c in updx.message.calls),
              str([c[1][:60] for c in updx.message.calls]))

    updx = await _run_admin_cmd(admin_h.addtp_cmd, ["999999999", "5000"], 1001)
    check("addtp به طرف ناموجود خطا میده", "نیس" in updx.message.calls[-1][1])
    updx = await _run_admin_cmd(admin_h.addtp_cmd, ["8812"], 1001)
    check("addtp ناقص راهنما میده", "فرم درست" in updx.message.calls[-1][1])
    updx = await _run_admin_cmd(admin_h.addtp_cmd, ["8812", "5000"], 1002)  # غیرادمین
    check("addtp برای غیرادمین کاملاً بی‌صداس", not updx.message.calls)

    # /detp و /dexp، کم کردن مستقیم سکه و تجربه (فقط ادمین)
    updx = await _run_admin_cmd(admin_h.detp_cmd, ["8812", "1500"], 1001)
    expected_cash = 6000 + config.LEVEL_CASH_REWARD * 6 - 1500  # ۶۰۰۰ واریزی + جایزه لول‌آپ به ۶ - کسر
    async with session_scope() as s:
        t = await users.get_by_tg(s, 8812)
        check("/detp مستقیم سکه کم کرد",
              t.cash == expected_cash and "کم شد" in updx.message.calls[-1][1]
              and f"{expected_cash:,}" in updx.message.calls[-1][1],
              updx.message.calls[-1][1][:100])
    updx = await _run_admin_cmd(admin_h.detp_cmd, ["8812", "999999"], 1001)
    async with session_scope() as s:
        t = await users.get_by_tg(s, 8812)
        check("detp بیشتر از موجودی، صفر می‌کنه نه منفی",
              t.cash == 0 and "کم شد" in updx.message.calls[-1][1])

    async with session_scope() as s:
        t = await users.get_by_tg(s, 8812)
        t.xp = 500
        await s.commit()
    updx = await _run_admin_cmd(admin_h.dexp_cmd, ["8812", "200"], 1001)
    async with session_scope() as s:
        t = await users.get_by_tg(s, 8812)
        check("/dexp مستقیم تجربه کم کرد",
              t.xp == 300 and "تجربه از" in updx.message.calls[-1][1] and "کم شد" in updx.message.calls[-1][1],
              updx.message.calls[-1][1][:100])
    updx = await _run_admin_cmd(admin_h.dexp_cmd, ["8812", "100"], 1002)  # غیرادمین
    check("dexp برای غیرادمین کاملاً بی‌صداس", not updx.message.calls)
    updx = await _run_admin_cmd(admin_h.detp_cmd, ["999999999", "10"], 1001)
    check("detp به طرف ناموجود خطا میده", "نیس" in updx.message.calls[-1][1])
    updx = await _run_admin_cmd(admin_h.dexp_cmd, ["8812"], 1001)
    check("dexp ناقص راهنما میده", "فرم درست" in updx.message.calls[-1][1])
    async with session_scope() as s:
        t = await users.get_by_tg(s, 8812)
        t.cash = 6000  # بالانس رو به حالت قبل از تست‌های detp برگردون (تست pending پایینش روش حساسه)
        await s.commit()

    # /user با یه نتیجه → کارت + دکمه‌ها
    updx = await _run_admin_cmd(admin_h.user_cmd, ["@silktoch"], 1001)
    card_text, card_mk = updx.message.calls[-1][1], updx.message.calls[-1][2].get("reply_markup")
    check("/user کارت طرف رو میاره",
          "<b>👤 سیلکتاج</b>" in card_text and "8812" in card_text and "🏦 بانک" in card_text,
          card_text[:120])
    check("دکمه‌های پول/XP روی کارتن",
          card_mk is not None
          and "adm:gtp:8812" in [b.callback_data for row in card_mk.inline_keyboard for b in row]
          and "adm:gxp:8812" in [b.callback_data for row in card_mk.inline_keyboard for b in row])

    # /user با چند نتیجه → لیست دکمه‌دار
    updx = await _run_admin_cmd(admin_h.user_cmd, [""], 1001)
    check("/user بدون آرگومان راهنما میده", "فرم درست" in updx.message.calls[-1][1])

    # فلو کامل کارت → پول دادن با پیام بعدی
    upd = _fake_update("adm:gtp:8812", uid=1001)
    await admin_h.admin_cb(upd, None)
    async with session_scope() as s:
        adm_user = await users.get_by_tg(s, 1001)
        check("دکمه 💰 پول بده فلو pending رو شروع کرد",
              adm_user.pending_action == "admtp" and adm_user.pending_value == "8812")
    upd = _text_update("2500", uid=1001, uname="adm", fname="ادمین")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    async with session_scope() as s:
        t = await users.get_by_tg(s, 8812)
        adm_user = await users.get_by_tg(s, 1001)
        check("pending ادمین پول رو به طرف رسوند",
              t.cash == 8500 and adm_user.pending_action is None,
              f"{t.cash}/{adm_user.pending_action}")
        check("گزارش واریز ادمین", "واریز شد به" in upd.message.calls[-1][1], upd.message.calls[-1][1][:80])
        # لغو فلو ادمین
        adm_user.pending_action = "admxp"
        adm_user.pending_value = "8812"
        msg_c = await dog_svc.cancel_pending(s, adm_user)
        check("لغو فلو ادمین پاکش می‌کنه", adm_user.pending_action is None and "بی‌خیال" in msg_c)

    # ── متن خوش‌آمد گروه (اد شدن ربات) ──
    gtxt = start_h2.group_welcome_text("TeriakyBot", is_admin=False)
    check("متن اد گروه قالب دقیق جدید رو داره",
          "🔥 تریاکی بات وارد گروه شد" in gtxt
          and "/start@TeriakyBot" in gtxt and f"{money(config.START_CASH)} جایزه بگیر" in gtxt
          and "⚔️ برای حمله روی پیام حریف ریپلای کن و بنویس\nحمله" in gtxt
          and "⛏️ برای کسب تی‌پوینت بنویس\nکنده کاری" in gtxt
          and "«تی راهنما» یا /help@TeriakyBot استفاده کنید" in gtxt, gtxt[:100])
    check("هشدار ادمین فقط وقتی ادمین نیستیم میاد",
          "⚠️ من هنوز تو این گروه ادمین نیستم" in gtxt
          and "⚠️" not in start_h2.group_welcome_text("TeriakyBot", is_admin=True))


    # ═══ این دور: قانون ویرگول (نه —) | زمین مکس ۵ و آپگرید گرون | غارت ۵-۱۰% | ایموجی بذرها | هلپ کورییت‌شده ═══

    # ── هیج « — » توی متن‌های بات نمونه (ویرگول «،» جاش نشسته) ──
    import glob as _glob
    dash_spots = []
    for f in _glob.glob("handlers/*.py") + _glob.glob("services/*.py") + _glob.glob("keyboards/*.py") + ["config.py"]:
        if " — " in open(f, encoding="utf-8").read():
            dash_spots.append(f)
    check("ویرگول جای دش توی همه متن‌های بات", not dash_spots, str(dash_spots))

    # ── غارت هر ضربه تا ۵٪ بر اساس دمیج ──
    check("سقف غارت هر ضربه ۵٪", config.BATTLE_STEAL_MAX_PCT == 0.05)

    # ── زمین: مکس لول ۶، آپگریدهای گرون‌تر با گیت لول ──
    check("مکس لول زمین ۶ه", config.PLOT_MAX_LEVEL == 6)
    check("قیمت آپگرید زمین گرون‌تر و رنده",
          config.PLOT_UPGRADE_PRICES == [8000, 15000, 45000, 150000, 300000]
          and economy.upgrade_price(1) == 8000 and economy.upgrade_price(4) == 150000
          and economy.upgrade_price(5) == 300000,
      str(config.PLOT_UPGRADE_PRICES))
    check("آپگرید زمین چوب هم می‌خواد",
          config.PLOT_UPGRADE_WOOD == [30, 60, 120, 250, 500]
          and economy.upgrade_wood(1) == 30 and economy.upgrade_wood(5) == 500)
    check("گیت لول آپگرید زمین",
          config.PLOT_UPGRADE_LEVELS == [3, 5, 10, 15, 20]
          and economy.plot_upgrade_required_level(1) == 3
          and economy.plot_upgrade_required_level(2) == 5
          and economy.plot_upgrade_required_level(3) == 10
          and economy.plot_upgrade_required_level(4) == 15
          and economy.plot_upgrade_required_level(5) == 20,
      str(config.PLOT_UPGRADE_LEVELS))

    # ── کولدان برداشت با ویرگول ──
    async with session_scope() as s:
        huser = await users.get_by_tg(s, 1001)
        huser.last_harvest_at = now_utc() - timedelta(seconds=42)
        ok, msg, _, _dqc, _nnc = await farming.harvest_all(s, huser)
        check("متن کولدان برداشت با ویرگول",
              not ok and "میشه برداشت کرد،" in msg and "مونده" in msg, msg)

    # ── ایموجی بذرها تو شاپ و دکمه کاشت ──
    check("ایموجی هر بذر تو کانفیگه",
          [config.SEEDS[k]["emoji"] for k in ("marijuana", "gharch", "peyote", "kratom", "khashkhash", "teriak", "cocaine")]
          == ["🌿", "🍄", "🌵", "🍃", "🌺", "☕", "⚪"])
    async with session_scope() as s:
        su1 = await users.get_by_tg(s, 1001)
        su1.level = 20
        skb = kb2.shop_seed_kb(su1, {"teriak": 3})
        seed_texts = [b.text for row in skb.inline_keyboard for b in row]
        check("دکمه‌های بذر شاپ ایموجی محصول رو دارن",
              any(t.startswith("🌿 ماری‌جوانا") for t in seed_texts)
              and any(t.startswith("🍄 قارچ") for t in seed_texts)
              and any(t.startswith("🍃 کراتوم") for t in seed_texts)
              and any(t.startswith("🌺 خشخاش سیاه") for t in seed_texts)
              and any(t.startswith("☕ تریاک | 📦 ×3") for t in seed_texts), str(seed_texts[:4]))
        splot1 = Plot(user_id=su1.id, status="empty")
        s.add(splot1)
        await s.flush()
        pkb = kb2.seeds_kb(su1, splot1, {"teriak": 3})
        p_texts = [b.text for row in pkb.inline_keyboard for b in row]
        check("دکمه کاشت بذر هم ایموجی داره",
              any(t.startswith("☕ تریاک") for t in p_texts), str(p_texts[:3]))

    # ── بخش‌های هلپ — متن نهایی کورییت‌شده ──
    import re as _re
    check("ارقام هلپ همه لاتینن",
          not any(_re.search(r"[۰-۹]", v) for v in start_h2.HELP_SECTIONS.values()))
    HS = start_h2.HELP_SECTIONS
    check("هلپ ۱۷ بخش داره و همه بخش‌های منو کلیدشون پوشش داده شده",
          set(HS) == {"start", "battle", "farm", "dogs", "company", "shelter", "team", "resources", "shop",
                      "mine", "casino", "bank", "quests", "misc", "skills", "gear", "titles"})
    check("هلپ مهارت‌ها (بخش جدید)",
          all(x in HS["skills"] for x in ["⭐️ مهارت", "امتیاز مهارت", "💥 قدرت", "⚡ سرعت",
                                          "🛡 دفاع", "💰 غارت", "لول 8", "25,000", "ریست"]))
    check("هلپ تجهیزات (بخش جدید)",
          all(x in HS["gear"] for x in ["🛡 تجهیزات", "سلاح و زره فعال", "دو تب", "دست خالی",
                                        "قابلیت مخصوص", "آپگرید تجهیزات"]))
    check("هلپ لقب‌ها (بخش جدید)",
          all(x in HS["titles"] for x in ["🏅 لقب", "Newbie", "Drug Lord", "لیدربرد", "تیم"]))
    check("هلپ کنده‌کاری (بخش جدید)",
          all(x in HS["mine"] for x in ["⛏ کنده‌کاری", "«تریاکی کنده کاری»", "«کنده کاری»", "60 ثانیه",
                                        "🪓 تبر", "⛏️ کلنگ", "لول 5", "«شکار کمیاب»"]))
    check("هلپ قمارخانه (بخش جدید)",
          all(x in HS["casino"] for x in ["🎰 قمارخانه", "«تریاکی قمارخانه»", "لول 7", "12 ساعت", "1.8 برابر"]))
    check("هلپ بانک (بخش جدید)",
          all(x in HS["bank"] for x in ["🏦 بانک", "«تریاکی بانک»", "ظرفیت", "حداقل لول کاراکتر"]))
    check("هلپ ماموریت روزانه (بخش جدید)",
          all(x in HS["quests"] for x in ["📋 ماموریت روزانه", "نیمه‌شب", "2 تا 3", "جایزه"]))
    check("هلپ متفرقه (بخش جدید)",
          all(x in HS["misc"] for x in ["🧭 متفرقه", "🔍 جستجو", "«تریاکی جستجو»", "📈 بازار سیاه",
                                        "🌦 آب‌وهوا", "⚡️ انرژی", "🌧 باران", "🌕 شب مهتابی"])
          and "پلیس" not in HS["misc"])
    check("هلپ شروع بازی",
          all(x in HS["start"] for x in ["«تریاکی پروفایل»", "کنده کاری", "«تریاکی شاپ»", "لول‌آپ"]))
    check("هلپ نبرد",
          all(x in HS["battle"] for x in ["ریپلای", "«حمله»", "«تریاکی درمان»", "لول 5", "سگ"]))
    check("هلپ مزرعه",
          all(x in HS["farm"] for x in ["«تریاکی کاشت [نام بذر]»", "«تریاکی برداشت»", "کیفیت",
                                        "چوب", "بذرهای افسانه‌ای"]))
    check("هلپ شرکت (بدون عدد دقیق ضریب)",
          all(x in HS["company"] for x in ["🏭 شرکت", "🪵 چوب‌بری", "کارخانه آهن", "چوب هم می‌خواد"])
          and "%" not in HS["company"])
    check("هلپ انبار (بدون پلیس)",
          all(x in HS["shelter"] for x in ["ظرفیت بذر", "چوب", "آهن"]) and "پلیس" not in HS["shelter"])
    check("هلپ تیم",
          all(x in HS["team"] for x in ["ساخت تیم", "جوین تیم [نام تیم]", "تیم من",
                                        "تیم درخواست @یوزر قبول", "تیم کیک @یوزر", "تیم ادمین @یوزر"]))
    check("هلپ منابع (سه راه + ارجاع به بخش کنده‌کاری)",
          all(x in HS["resources"] for x in ["چوب و آهن", "کنده‌کاری", "فروشگاه", "چوب‌بری", "⛏ کنده‌کاری"]))
    check("هلپ فروشگاه",
          all(x in HS["shop"] for x in ["🔫 سلاح", "🛡 زره", "⬆️ ارتقای سلاح و زره", "🧿 آرتیفکت",
                                        "🎒 پک چوب و آهن", "🐕 سگ", "سبز", "قرمز", "«تریاکی خرید [نام آیتم]»"]))

    check("واحد پول لاتین", money(1000) == "1,000 تی‌پوینت" and money_tp(1000) == "1,000 TP")
    check("عدد لاتین", fa_num(12345) == "12,345" and fa_dur(169) == "2 دقیقه و 49 ثانیه")


    # ═══ این دور: قفل مالکیت دکمه‌ها تو گروه | پیشوند «تریاکی » | فید سگ از روی کارت | دکمه مزرعه من تو بذر شاپ ═══

    from handlers.common import _MESSAGE_OWNERS, owner_guard, owner_of, strip_bot_cmd
    from telegram.ext import ApplicationHandlerStop

    # ── strip_bot_cmd ──
    check("strip_bot_cmd پیشوند تریاکی رو برمی‌داره",
          strip_bot_cmd("تریاکی زمین") == "زمین"
          and strip_bot_cmd("تریاکی  تیم فوتبالیست‌ها") == "تیم فوتبالیست‌ها"
          and strip_bot_cmd("زمین") == "زمین" and strip_bot_cmd("تریاکی") == "تریاکی" and strip_bot_cmd("") == "")

    # ── قفل مالکیت دکمه‌های گروهی ──
    _MESSAGE_OWNERS.clear()
    from handlers import rank as rank_h

    gmsg = _Msg(text="تریاکی رتبه", calls=[], chat_id=777, message_id=4242)
    gupd = SimpleNamespace(
        message=gmsg, effective_message=gmsg,
        effective_user=SimpleNamespace(id=8808, username="gr", first_name="گروهی"),
        effective_chat=SimpleNamespace(type="supergroup", id=777), callback_query=None,
    )
    await rank_h.rank_cb(gupd, None)
    check("پیام دکمه‌دار گروهی به اسم صاحب دستور ثبت شد", owner_of(777, 4242) == 8808)
    from models import MessageOwner
    async with session_scope() as s:
        mo = await s.get(MessageOwner, (777, 4242))
    check("مالک پیام تو دیتابیس هم ثبت شد", mo is not None and mo.owner_tg == 8808)

    def _cb(data, uid, mid=4242, cid=777):
        q = _Q(data=data, message=SimpleNamespace(photo=None, chat_id=cid, message_id=mid), calls=[])
        return SimpleNamespace(
            callback_query=q,
            effective_user=SimpleNamespace(id=uid, username="x", first_name="ایکس"),
            effective_chat=SimpleNamespace(type="supergroup", id=cid),
        )

    updg = _cb("menu:rank", 9999)
    stopped = False
    try:
        await owner_guard(updg, None)
    except ApplicationHandlerStop:
        stopped = True
    ans = updg.callback_query.calls
    check("غریبه رو دکمه مالِ بقیه: بلاک کامل بدون هیچ متنی",
          stopped and ans and ans[0][0] == "answer" and not ans[0][1] and not ans[0][2])

    updg = _cb("menu:rank", 8808)
    try:
        await owner_guard(updg, None)
        stopped = False
    except ApplicationHandlerStop:
        stopped = True
    check("صاحب دستور بدون وقفه رد میشه", not stopped and not updg.callback_query.calls)

    for shared in ("cv:hit", "team:mine"):
        updg = _cb(shared, 9999)
        try:
            await owner_guard(updg, None)
            stopped = False
        except ApplicationHandlerStop:
            stopped = True
        check(f"دکمه جمعی {shared} برای همه آزاده", not stopped)

    updg = _cb("menu:rank", 9999, mid=3333)
    try:
        await owner_guard(updg, None)
        stopped = False
    except ApplicationHandlerStop:
        stopped = True
    check("پیامی که ثبت نشده آزاده", not stopped)

    # ── ری‌استارت ربات: حافظه پاک ولی قفل از دیتابیس سر جاش میمونه ──
    _MESSAGE_OWNERS.clear()
    check("بعد پاک‌شدن حافظه مالک از یاد حافظه رفته", owner_of(777, 4242) is None)
    updg = _cb("menu:rank", 9999)
    stopped = False
    try:
        await owner_guard(updg, None)
    except ApplicationHandlerStop:
        stopped = True
    check("بعد ری‌استارت هم غریبه بلاکه (مالک از دیتابیس خونده میشه)", stopped)
    check("مالک دیتابیسی تو حافظه کش شد", owner_of(777, 4242) == 8808)

    updg = _cb("menu:rank", 8808)
    stopped = False
    try:
        await owner_guard(updg, None)
    except ApplicationHandlerStop:
        stopped = True
    check("بعد ری‌استارت صاحب دستور رد میشه", not stopped and not updg.callback_query.calls)

    _MESSAGE_OWNERS.clear()
    updg = _cb("menu:rank", 9999, mid=3333)
    stopped = False
    try:
        await owner_guard(updg, None)
    except ApplicationHandlerStop:
        stopped = True
    check("پیامی که تو دیتابیس هم نیس بعد ری‌استارت آزاده", not stopped)

    # ── «تریاکی شاپ» وسط اسم‌گذاری سگ قورت داده نمیشه ──
    async with session_scope() as s:
        pg, _ = await users.get_or_create(s, tg(8813, "ppfx", "پریفکس"))
        pg.level = 15
        pg.cash = 50000
        ok, _ = await dog_svc.hold_dog(s, pg, "doberman")
        assert ok
        await s.commit()
    upd = _text_update("تریاکی شاپ", uid=8813, uname="ppfx", fname="پریفکس")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    async with session_scope() as s:
        pg = await users.get_by_tg(s, 8813)
        pdgs = await dog_svc.get_user_dogs(s, pg.id)
    check("«تریاکی شاپ» به جای اسم سگ قورت داده نشد",
          not upd.message.calls and pg.pending_action == "dogname" and not pdgs)

    # ── «غذا بده» دیگه دیالوگ نمیاره، همون کارت آمار سگ میاره ──
    async with session_scope() as s:
        fowner = await users.get_by_tg(s, 7702)
        fdogs = await dog_svc.get_user_dogs(s, fowner.id)
        fid = fdogs[0].id if fdogs else 0
        await s.commit()
    upd = _fake_update(f"dogs:feed:{fid}", uid=7702)
    await dogs_h2.feed_picker(upd, None)
    ed = next((c for c in upd.callback_query.calls if c[0] == "edit"), None)
    check("غذا بده کارت آمار سگ رو با خط گرسنگی میاره",
          ed is not None and "<b>🐕 آمار" in ed[1] and "هنوز گرسنشه و" in ed[1] and "تا غذای دیگه جا داره" in ed[1],
          ed[1][:120] if ed else "-")

    fake_d = SimpleNamespace(name="رکس", feed_day=iran_today(), feeds_today=config.DOG_FEED_PER_DAY - 3)
    check("متن «هنوز گرسنشه و 3تا غذای دیگه جا داره»",
          dog_svc.hunger_text(fake_d) == "🍖 رکس هنوز گرسنشه و 3تا غذای دیگه جا داره", dog_svc.hunger_text(fake_d))
    fake_d.feeds_today = config.DOG_FEED_PER_DAY
    check("متن «سیر شده»", dog_svc.hunger_text(fake_d) == "🍖 رکس سیر شده", dog_svc.hunger_text(fake_d))

    # ── دکمه «مزرعه من» توی بذرهای شاپ، دقیقاً بالای بازگشت ──
    async with session_scope() as s:
        su2 = await users.get_by_tg(s, 1001)
        su2.level = 20
        skb2 = kb2.shop_seed_kb(su2, {})
        await s.commit()
    seed_datas = [b.callback_data for row in skb2.inline_keyboard for b in row]
    seed_names = [b.text for row in skb2.inline_keyboard for b in row]
    check("دکمه «مزرعه من» توی بذرهای شاپ، دقیقاً بالای بازگشت",
          "menu:farm" in seed_datas
          and seed_datas.index("menu:farm") == len(seed_datas) - 2
          and seed_datas[-1] == "menu:shop"
          and any("مزرعه من" in t for t in seed_names),
          str(seed_names[-3:]))

    # ── کوتیشن‌های هلپ: یا پیشوند تریاکی دارن یا دستور بدون‌پیشوند مجازن (تیمی/حمله/کنده کاری) ──
    BARE_OK = ("کنده کاری", "مزرعه من", "حمله", "کنده\u200cکاری تیمی", "شلیک", "اسم سگ [اسم فعلی] [اسم جدید]",
               "شکار کمیاب", "بانک", "بانک واریز 1200", "بانک برداشت 1200", "انتقال 4000 E86YF2", "مهارت")
    for key, body in start_h2.HELP_SECTIONS.items():
        for snip in re.findall("«(.+?)»", body):
            check(f"«{snip[:22]}» توی هلپ {key} پیشوند داره یا بدون‌پیشوند مجازه",
                  snip.startswith(("تریاکی", "تیم", "ساخت تیم", "جوین تیم")) or snip in BARE_OK, snip)

    # ── متن استارت پیوی بازطراحی‌شده: فقط یه قدم مشخص + ارجاع به راهنما ──
    upd = _text_update("/start", uid=7313, uname="nwb", fname="تازه")
    await start_h2.start_cmd(upd, None)
    stx = upd.message.calls[-1][1]
    check("استارت پیوی جدید فقط اولین قدم رو می‌گه و بقیه رو می‌فرسته به راهنما",
          "به بازی تریاکی خوش اومدی" in stx and "⛏ روی «کنده کاری» بزن و بکن" in stx
          and "برای شروع اولین قدم خیلی ساده‌ست" in stx
          and "جایزه شروع بازی" in stx and "خود بازی راهنماییت می‌کنم" in stx
          and "آموزشات" in stx and "سرمایه شروع می‌کنی" not in stx, stx[:200])
    check("دیگه لیست همه قابلیت‌ها تو خوش‌آمد نیس",
          "قابلیت" not in stx and "پادشاه" not in stx)

    # ── متن‌های راهنما داخل صفحه‌ها هم پیشوند گرفتن ──
    from handlers import bank as bank_h2, battle as battle_h2
    async with session_scope() as s:
        uh = await users.get_by_tg(s, 1001)
        btx = bank_h2._bank_text(uh)
        await s.commit()
    from handlers import attack as attack_h2
    check("پنل پی‌وی به نبرد گروهی ارجاع میده",
          "حمله | شلیک | بنگ | پیو" in battle_h2.ATTACK_GUIDE_TEXT
          and "گروه‌ها" in attack_h2.PV_PANEL_TEXT)
    check("متن بانک دستورها رو با تریاکی می‌گه",
          "«تریاکی واریز 1200»" in btx and "«تریاکی برداشت 1200»" in btx)
    check("noop واریز تیم بدون پیشونده", "«تیم واریز 1200»" in start_h2._NOOP_ANSWERS["depinfo"]
          and "تریاکی" not in start_h2._NOOP_ANSWERS["depinfo"], start_h2._NOOP_ANSWERS["depinfo"][:80])

    # ═══ این دور: لول مکس 👑 توی کیبوردها | پیشوندهای تریاک/تی | کامندهای منوی «/» ═══

    # ── زمین لول مکس: تایتل و دکمه هر دو 👑 لول مکس ──
    maxplot_sn = SimpleNamespace(id=901, level=config.PLOT_MAX_LEVEL,
                                 current_status=lambda: ("empty", 0))
    mk = kb2.farm_kb(SimpleNamespace(level=1), [maxplot_sn], 999999, 0)
    mtexts = [b.text for row in mk.inline_keyboard for b in row]
    mdatas = [b.callback_data for row in mk.inline_keyboard for b in row]
    check("زمین لول مکس تو کیبورد مزرعه با 👑 نشون داده میشه",
          f"🗺 زمین {fa_num(1)} | 👑 لول مکس" in mtexts and "noop:maxplot" in mdatas
          and not any(d.startswith("farm:up:") for d in mdatas), str(mtexts[:5]))

    # ── دکمه ساخت زمین: قالب دقیق «🔨 ساخت زمین 4 | 🪙 20,000 TP» ──
    e_plot = SimpleNamespace(id=903, level=1, current_status=lambda: ("empty", 0))
    fk = kb2.farm_kb(SimpleNamespace(level=20), [e_plot, e_plot, e_plot], 20000, 0)
    ftexts = [b.text for row in fk.inline_keyboard for b in row]
    fdatas = [b.callback_data for row in fk.inline_keyboard for b in row]
    check("دکمه ساخت زمین قالب دقیق جدید رو داره",
          "farm:buy" in fdatas and "🔨 ساخت زمین 4 | 🪙 20,000 TP" in ftexts, str(ftexts[-3:]))
    fb_btn = next(b for row in fk.inline_keyboard for b in row if b.callback_data == "farm:buy")
    check("دکمه ساخت زمین آبی (primary) مونده", fb_btn.style == "primary")

    # ── دکمه قفل ساخت زمین هم همون قالب با 🔒 و قرمز ──
    fk2 = kb2.farm_kb(SimpleNamespace(level=1), [e_plot, e_plot, e_plot], 20000, 0)
    lock_btn = next(b for row in fk2.inline_keyboard for b in row if b.callback_data == "noop:lock")
    check("قفل ساخت زمین قالب جدید + قرمز",
          lock_btn.text == f"🔒 ساخت زمین 4 | 🪙 20,000 TP | لول {fa_num(15)}"
          and lock_btn.style == "danger", lock_btn.text)

    # ── تایمرهای مزرعه (ساخت + رشد) قرمزن ──
    b_plot = SimpleNamespace(id=904, level=1, current_status=lambda: ("building", 300))
    g_plot = SimpleNamespace(id=905, level=1, current_status=lambda: ("growing", 120))
    tk3 = kb2.farm_kb(SimpleNamespace(level=1), [b_plot, g_plot], 10000, 0)
    b_style = next(b.style for row in tk3.inline_keyboard for b in row if b.callback_data == "noop:build")
    g_style = next(b.style for row in tk3.inline_keyboard for b in row if b.callback_data == "noop:grow")
    check("تایمر ساخت و رشد زمین نمایشی و بدون رنگن",
          b_style is None and g_style is None, f"{b_style}/{g_style}")

    # ── سگ لول مکس: غذاها جاشون رو به 👑 لول مکس میدن ──
    dk = kb2.dog_card_kb(SimpleNamespace(id=902, level=config.DOG_MAX_LEVEL), 3)
    dtexts = [b.text for row in dk.inline_keyboard for b in row]
    ddatas = [b.callback_data for row in dk.inline_keyboard for b in row]
    check("سگ لول مکس به جای غذاها 👑 لول مکس می‌گیره",
          "noop:maxdog" in ddatas and not any(d.startswith("cf:feed:") for d in ddatas)
          and any("👑 لول مکس" in t for t in dtexts), str(dtexts[:5]))

    # ── ساختمان تیم لول مکس: هر دو طرف حمله و دفاع 👑 لول مکس ──
    tb_k = kb2.team_bld_kb(SimpleNamespace(atk_bld=config.TEAM_BUILDING_MAX_LEVEL,
                                           def_bld=config.TEAM_BUILDING_MAX_LEVEL), True, 424242)
    tbtexts = [b.text for row in tb_k.inline_keyboard for b in row]
    tbdatas = [b.callback_data for row in tb_k.inline_keyboard for b in row]
    check("ساختمان تیم لول مکس هر دو طرفش 👑 لول مکسه",
          tbdatas.count("noop:maxbld") == 2
          and "⚔️ حمله 👑 لول مکس" in tbtexts and "🛡 دفاع 👑 لول مکس" in tbtexts,
          str(tbtexts[:5]))

    # ── کیبورد ساختمان تیم: 🔙 تیم من + 🏠 منوی اصلی (هوم تو گروه strip میشه) ──
    tb2 = kb2.team_bld_kb(SimpleNamespace(atk_bld=1, def_bld=1), False, 424242)
    tb2datas = [b.callback_data for row in tb2.inline_keyboard for b in row]
    tb2texts = [b.text for row in tb2.inline_keyboard for b in row]
    check("کیبورد ساختمان تیم 🔙 تیم من و 🏠 منوی اصلی داره",
          "team:bld" in tb2datas and "menu:team" in tb2datas and "menu:home" in tb2datas
          and any("منوی اصلی" in t for t in tb2texts)
          and tb2.inline_keyboard[-1][-1].callback_data == "menu:home", str(tb2texts[-3:]))
    tb2o = kb2.team_bld_kb(SimpleNamespace(atk_bld=1, def_bld=1), True, 424242)
    check("نسخه رهبر ساختمان هم دکمه هوم داره",
          any(b.callback_data == "menu:home" for row in tb2o.inline_keyboard for b in row))

    # ── جواب noopهای لول مکس با متن «بهتر از این نمیشه» ست شدن ──
    NA = start_h2._NOOP_ANSWERS
    check("جواب‌های 5 تا noop لول مکس دقیقن",
          NA["maxplot"] == "🌱 این زمین لول مکس، بهتر از این نمیشه"
          and NA["maxbank"] == "🏦 این بانک لول مکس، بهتر از این نمیشه"
          and NA["maxshelter"] == "🏚 این انبار لول مکس، بهتر از این نمیشه"
          and NA["maxdog"] == "🐕 این سگ لول مکس، بهتر از این نمیشه"
          and NA["maxbld"] == "🏗 این ساختمان لول مکس، بهتر از این نمیشه")

    # ── «تی شاپ» وسط اسم‌گذاری سگ قورت داده نمیشه (پیشوند سه‌تایی) ──
    async with session_scope() as s:
        pg3, _ = await users.get_or_create(s, tg(8816, "ppfx3", "پریفکس سوم"))
        pg3.level = 15
        pg3.cash = 50000
        ok, _ = await dog_svc.hold_dog(s, pg3, "doberman")
        assert ok
        await s.commit()
    upd = _text_update("تی شاپ", uid=8816, uname="ppfx3", fname="پریفکس سوم")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    async with session_scope() as s:
        pg3 = await users.get_by_tg(s, 8816)
        pdgs3 = await dog_svc.get_user_dogs(s, pg3.id)
    check("«تی شاپ» به جای اسم سگ قورت داده نشد",
          not upd.message.calls and pg3.pending_action == "dogname" and not pdgs3)

    # ── کامندهای منوی «/» تلگرام موقع بالا اومدن ربات ست میشن ──
    import bot as bot_mod
    from telegram import BotCommand as _BC

    class _SlashBot:
        def __init__(self):
            self.cmds = None

        async def get_me(self):
            return SimpleNamespace(username="teriaky_test_bot")

        async def set_my_commands(self, cmds):
            self.cmds = cmds

    slash_bot = _SlashBot()
    await bot_mod.on_start(SimpleNamespace(bot=slash_bot))
    check("set_my_commands با لیست جدید صدا زده میشه (بدون menu، botoff/boton ته لیست)",
          slash_bot.cmds is not None
          and [c.command for c in slash_bot.cmds]
          == ["start", "profile", "help", "heal", "shop", "botoff", "boton"]
          and all(isinstance(c, _BC) for c in slash_bot.cmds),
          str([c.command for c in (slash_bot.cmds or [])]))
    check("توضیح هر کامند ایموجی مخصوص خودشو داره",
          all(c.description and c.description[0] in "🎮🏠📖❤️🛒🔌" for c in slash_bot.cmds),
          str([c.description for c in (slash_bot.cmds or [])]))

    # ═══ این دور: کوئست‌های روزانه 📅 | سپر ۱۵ دقیقه و نبرد قدرت‌محور | رگرسیون باگ رها کردن سگ ═══

    # ── سرویس کوئست‌های روزانه ──
    import json as _json
    from services import quests as dq_svc
    from handlers import dquests as dquests_h

    async with session_scope() as s:
        q1, _ = await users.get_or_create(s, tg(8870, "qstd", "کوئستی"))
        quests = await dq_svc.ensure_quests(s, q1)
        check("هر روز 2 تا 3 کوئست ساخته میشه",
              2 <= len(quests) <= 3 and q1.dq_date == iran_today(), str(len(quests)))
        check("کوئست‌ها متمایزن و هدف کانفیگ رو دارن",
              len({q["kind"] for q in quests}) == len(quests)
              and all(q["target"] == config.DAILY_QUESTS[q["kind"]]["target"] for q in quests)
              and all(q["progress"] == 0 and not q["done"] for q in quests),
              str(quests))
        quests_again = await dq_svc.ensure_quests(s, q1)
        check("تو همون روز کوئست‌ها ثابتن", quests_again == quests)
        # روز عوض بشه از نو ساخته میشن
        q1.dq_date = "2000-01-01"
        quests_new = await dq_svc.ensure_quests(s, q1)
        check("ریست با عوض شدن روز (ساعت 12 به وقت ایران)",
              q1.dq_date == iran_today() and 2 <= len(quests_new) <= 3)

        # تعیین برای تست پیشرفت: یه کوئست ماین با جایزه مشخص دستی می‌کاریم
        q1.dq_data = _json.dumps([
            {"kind": "mine", "target": 2, "progress": 0, "done": False, "reward": {"type": "tp", "amount": 100}},
            {"kind": "search", "target": 1, "progress": 0, "done": False, "reward": {"type": "xp", "amount": 10}},
        ], ensure_ascii=False)
        cash_q = q1.cash
        done, left = await dq_svc.track(s, q1, "mine")
        check("یه بار ماین هنوز کوئست تموم نشده",
              not done and left == 2 and _json.loads(q1.dq_data)[0]["progress"] == 1)
        done, left = await dq_svc.track(s, q1, "mine")
        check("دومی کوئست رو کامل کرد و تی‌پوینتش واریز شد",
              len(done) == 1 and done[0]["kind"] == "mine" and q1.cash == cash_q + 100 and left == 1,
              f"{q1.cash - cash_q}/{left}")
        done3, left3 = await dq_svc.track(s, q1, "mine")
        check("کوئست تکمیل‌شده دوباره جایزه نمیده", not done3 and q1.cash == cash_q + 100)
        xp_b, lvl_b = q1.xp, q1.level
        done4, left4 = await dq_svc.track(s, q1, "search")
        check("کوئست آخر جایزه تجربه میده و همه تکمیلن",
              len(done4) == 1 and left4 == 0 and (q1.xp > xp_b or q1.level > lvl_b), str(left4))
        check("پیشرفت بیشتر از هدف نمی‌ره (کلمپ)",
              _json.loads(q1.dq_data)[0]["progress"] == 2)
        # متن جایزه‌ها
        check("متن جایزه‌ها",
          dq_svc.reward_text({"reward": {"type": "tp", "amount": 500}}) == "500 تی‌پوینت"
              and dq_svc.reward_text({"reward": {"type": "xp", "amount": 60}}) == "✨ 60 تجربه"
              and dq_svc.reward_text({"reward": {"type": "seed", "seed": "teriak", "amount": 1}}) == "🌱 بذر تریاک")
        check("عنوان کوئست با عدد لاتین",
              dq_svc.quest_title({"kind": "mine", "target": 20}) == "20 بار کنده‌کاری")
        await s.commit()

    # توزیع جایزه‌ها روشن‌عقله
    random.seed(77)
    kinds = {dq_svc._roll_reward("mine", 1)["type"] for _ in range(300)}
    check("قرعه جایزه هر سه مدل رو می‌ده", "tp" in kinds and "xp" in kinds and "seed" in kinds, str(kinds))

    # ── صفحه کوئست‌های روزانه (هندلر منوی اصلی) ──
    upd = _fake_update("menu:dquests", uid=8870)
    await dquests_h.daily_quests_cb(upd, None)
    ed = next((c for c in upd.callback_query.calls if c[0] == "edit"), None)
    check("صفحه کوئست‌های روزانه باز میشه",
          ed is not None and "<b>🎯 مأموریت‌های روزانه</b>" in ed[1]
          and "هر شب ساعت 12 ریست میشن" in ed[1]
          and "🎁" in ed[1], ed[1][:140] if ed else "-")
    check("کوئست‌های انجام‌شده خط خوردن و تیک خوردن",
          ed is not None and "<s>" in ed[1] and "✅ انجام شد" in ed[1] and "🏆 همه کوئست‌های امروز رو درو کردی" in ed[1],
          ed[1].replace("\n", " | ")[-200:] if ed else "-")

    # ── اعلان تکمیل کوئست (همونجا که کاربر فعاله) ──
    async def _announce(upd_, name, completed, left):
        await dquests_h.announce_completed(upd_, name, completed, left)
        return [c[1] for c in upd_.message.calls if c[0] == "reply"]

    q_mid = [{"kind": "mine", "target": 20, "progress": 20, "done": True,
              "reward": {"type": "tp", "amount": 450}, "notes": []}]
    upd = _text_update("x", uid=8870, uname="qstd", fname="کوئستی")
    texts = await _announce(upd, "کوئستی", q_mid, 2)
    check("متن آفرین با عنوان کوئست و جایزه و باقی‌مونده",
          len(texts) == 1 and "آفرین کوئستی کوئست «20 بار کنده‌کاری» رو تکمیل کردی" in texts[0]
          and "🎁 جایزه: 450 تی‌پوینت" in texts[0] and "هنوز 2 کوئست دیگه مونده" in texts[0],
          texts[0].replace("\n", " | ")[:200] if texts else "-")
    upd = _text_update("x", uid=8870, uname="qstd", fname="اصغر")
    texts = await _announce(upd, "اصغر", q_mid, 0)
    check("کوئست آخر تبریک ویژه داره",
          len(texts) == 1 and "ایوللل اصغر بهت تبریک میگم" in texts[0]
          and "همه کوئست‌ها رو درو کردی" in texts[0] and "دیگه کوئستی برای امروز نمونده" in texts[0]
          and "🎁 جایزه: 450 تی‌پوینت" in texts[0],
          texts[0].replace("\n", " | ")[:200] if texts else "-")
    upd = _text_update("x", uid=8870, uname="qstd", fname="کوئستی")
    texts = await _announce(upd, "کوئستی", [], 1)
    check("بدون کوئست تکمیلی هیچ پیامی نمیره", texts == [])

    # ── ادغام: کنده‌کاری واقعی کوئست رو تکمیل و اعلام می‌کنه ──
    async with session_scope() as s:
        mqu, _ = await users.get_or_create(s, tg(8871, "mqint", "ماین‌کوئستی"))
        mqu.dq_date = iran_today()
        mqu.dq_data = _json.dumps([
            {"kind": "mine", "target": 1, "progress": 0, "done": False, "reward": {"type": "tp", "amount": 100}},
            {"kind": "search", "target": 1, "progress": 0, "done": False, "reward": {"type": "tp", "amount": 50}},
        ], ensure_ascii=False)
        cash_qi = mqu.cash
        await s.commit()
    upd = _text_update("کنده کاری", uid=8871, uname="mqint", fname="ماین‌کوئستی")
    await mine_h.mine_cmd(upd, None)
    texts = [c[1] for c in upd.message.calls if c[0] == "reply"]
    check("کنده‌کاری واقعی کوئست رو کامل و اعلامش همونجا میاد",
          any("⛏️ کنده‌کاری" in t for t in texts)
          and any("آفرین" in t and "«1 بار کنده‌کاری»" in t and "🎁 جایزه: 100 تی‌پوینت" in t for t in texts),
          str([t.replace("\n", " ")[:70] for t in texts]))
    async with session_scope() as s:
        mqu = await users.get_by_tg(s, 8871)
        check("جایزه کوئست ماین به حساب نشست",
              mqu.cash >= cash_qi + 100 + 10, f"{mqu.cash} (قبل {cash_qi})")
        await s.commit()

    # ── رگرسیون باگ «رهاش کن» (relcf سه‌تیکه) ──
    from handlers import dogs as dogs_h3
    async with session_scope() as s:
        rl = await users.get_by_tg(s, 8809)
        dogs_now = await dog_svc.get_user_dogs(s, rl.id)
        rel_dog = dogs_now[0]
        n_before = len(dogs_now)
        did, dname = rel_dog.id, rel_dog.name
        await s.commit()
    upd = _fake_update(f"dog:rel:{did}", uid=8809)
    await dogs_h3.release_confirm(upd, None)
    ed = next((c for c in upd.callback_query.calls if c[0] == "edit"), None)
    rel_datas = [b.callback_data for row in ed[2]["reply_markup"].inline_keyboard for b in row] if ed else []
    check("فاکتور رها کردن سگ میاد با دکمه رهاش کن",
          ed is not None and "🕊 رها کردن" in ed[1] and "برگشتی نداره" in ed[1]
          and rel_datas == [f"relcf:{did}:8809", "txcl:8809"], str(rel_datas))
    upd = _fake_update(f"relcf:{did}:8809", uid=8809)
    await dogs_h3.release_execute(upd, None)
    ed2 = next((c for c in upd.callback_query.calls if c[0] == "edit"), None)
    async with session_scope() as s:
        rl = await users.get_by_tg(s, 8809)
        rest = await dog_svc.get_user_dogs(s, rl.id)
        check("دکمه «رهاش کن» کار می‌کنه و سگ آزاد میشه (رگرسیون)",
              ed2 is not None and "سگ‌های من" in ed2[1]
              and len(rest) == n_before - 1 and all(d.name != dname for d in rest),
              f"{n_before}→{len(rest)}" if ed2 else "no edit")
        await s.commit()

    # ── فلوی کامل نبرد HP گروهی (هندلر واقعی: ریپلای | کولدان | شکست | خودایجاد پروفایل) ──
    from handlers import battle as battle_h3

    def _tgroup(txt, uid, uname, fname, reply_user=None):
        """آپدیت فیک حمله گروهی با ریپلای اختیاری روی پیام طرف"""
        msg = _Msg(text=txt, calls=[], chat_id=-100555)
        msg.reply_to_message = SimpleNamespace(from_user=reply_user) if reply_user else None
        return SimpleNamespace(
            message=msg, effective_message=msg,
            effective_user=SimpleNamespace(id=uid, username=uname, first_name=fname, is_bot=False),
            effective_chat=SimpleNamespace(id=-100555, type="supergroup"),
            callback_query=None,
        )

    async with session_scope() as s:
        g_atk, _ = await users.get_or_create(s, tg(8890, "gangsta", "گانگستر"))
        g_atk.level = 10
        g_atk.cash = 50000
        g_atk.energy = config.MAX_ENERGY
        g_atk.last_attack_at = None
        await s.commit()

    # حریف از قبل اکانت داره (با آیدی همون ریپلای)، پروفایل خودکار پیدا کردنیه
    async with session_scope() as s:
        vic0, _ = await users.get_or_create(s, tg(8891, "victim1", "قربانی"))
        vic0.cash = 100000
        await s.commit()
    vic_tg = SimpleNamespace(id=8891, username="victim1", first_name="قربانی", is_bot=False)
    upd = _tgroup("حمله", 8890, "gangsta", "گانگستر", reply_user=vic_tg)
    await battle_h3.attack_cmd(upd, None)
    htxt = next((c[1] for c in upd.message.calls if "💥" in c[1]), "")
    check("حمله ریپلای گروهی متن قالب دقیق میاره",
          "<b>💥 به حریف «قربانی» حمله کردی</b>" in htxt
          and "🩸" in htxt and "دمیج وارد شد" in htxt
          and "❤️ سلامت حریف" in htxt and " از 200" in htxt
          and "تی‌پوینت غارت کردی" in htxt and "تجربه گرفتی" in htxt,
          htxt.replace("\n", " | ")[:220])
    async with session_scope() as s:
        vic = await users.get_by_tg(s, 8891)
        g_atk = await users.get_by_tg(s, 8890)
        check("حریف بدون استارت خودکار پروفایل گرفت و HPش کم شد",
              vic is not None and vic.hp is not None and vic.hp < battle_svc.max_hp(1))
        check("کولدان مهاجم ست شد", (await battle_svc.cooldown_left(s, g_atk)) > 0)
        await s.commit()

    # کولدان: حمله دوباره فوری رد میشه
    upd = _tgroup("حمله", 8890, "gangsta", "گانگستر", reply_user=vic_tg)
    await battle_h3.attack_cmd(upd, None)
    check("حمله توی کولدان رد میشه",
          "⏳" in upd.message.calls[-1][1] and "دیگه می‌تونی حمله کنی" in upd.message.calls[-1][1])

    # هر ۶ دستور جنگ با ریپلای کار می‌کنن
    for war in ("شلیک", "بنگ بنگ", "پیو پیو", "پیو", "تریاکی حمله", "تی بنگ"):
        async with session_scope() as s:
            g_atk = await users.get_by_tg(s, 8890)
            g_atk.last_attack_at = None
            g_atk.energy = config.MAX_ENERGY
            vic = await users.get_by_tg(s, 8891)
            vic.hp = battle_svc.max_hp(vic.level)
            vic.dead_until = None
            await s.commit()
        upd = _tgroup(war, 8890, "gangsta", "گانگستر", reply_user=vic_tg)
        await battle_h3.attack_cmd(upd, None)
        assert any("💥" in c[1] for c in upd.message.calls), f"{war}: {upd.message.calls[-1][1][:80]}"
    check("هر ۶ دستور جنگ با ریپلای کار می‌کنن", True)

    # بدون ریپلای و بدون آیدی، راهنمای دستورها میاد
    upd = _tgroup("حمله", 8890, "gangsta", "گانگستر")
    await battle_h3.attack_cmd(upd, None)
    check("حمله بدون هدف راهنما میده",
          "حمله | شلیک | بنگ | پیو" in upd.message.calls[-1][1])

    # خودتو نزن + ربات رو نمیشه زد
    self_tg = SimpleNamespace(id=8890, username="gangsta", first_name="گانگستر", is_bot=False)
    upd = _tgroup("حمله", 8890, "gangsta", "گانگستر", reply_user=self_tg)
    await battle_h3.attack_cmd(upd, None)
    check("حمله به خودی رد میشه", "خودتو نزن" in upd.message.calls[-1][1])
    bot_tg = SimpleNamespace(id=999999, username="somebot", first_name="ربات", is_bot=True)
    upd = _tgroup("حمله", 8890, "gangsta", "گانگستر", reply_user=bot_tg)
    await battle_h3.attack_cmd(upd, None)
    check("به ربات نمیشه حمله کرد", "ربات رو نمیشه زد" in upd.message.calls[-1][1])

    # ضربه آخر: قربانی از پا درمیاد
    async with session_scope() as s:
        g_atk = await users.get_by_tg(s, 8890)
        g_atk.last_attack_at = None
        g_atk.energy = config.MAX_ENERGY
        vic = await users.get_by_tg(s, 8891)
        vic.hp = 1
        vic.dead_until = None
        await s.commit()
    upd = _tgroup("حمله", 8890, "gangsta", "گانگستر", reply_user=vic_tg)
    await battle_h3.attack_cmd(upd, None)
    ktxt = next((c[1] for c in upd.message.calls if "☠️" in c[1]), "")
    check("ضربه آخر بلوک ☠️ و 🏆 رو میاره",
          "دمیج وارد شد" in ktxt
          and "<b>☠️ حریف «قربانی» شکست خورد</b>" in ktxt and "🏆 دوئل به پایان رسید" in ktxt,
          ktxt.replace("\n", " | ")[-170:])

    # به مرده نمیشه زد
    async with session_scope() as s:
        g_atk = await users.get_by_tg(s, 8890)
        g_atk.last_attack_at = None
        g_atk.energy = config.MAX_ENERGY
        await s.commit()
    upd = _tgroup("حمله", 8890, "gangsta", "گانگستر", reply_user=vic_tg)
    await battle_h3.attack_cmd(upd, None)
    check("حمله به بیهوش پیام دقیق میده",
          "💀 حریف «قربانی» مرده و تا" in upd.message.calls[-1][1]
          and "دقیقه دیگه زنده نمیشه" in upd.message.calls[-1][1]
          and "یه هدف دیگه پیدا کن" in upd.message.calls[-1][1])

    # مرده خودش هم نمی‌تونه بزنه
    atk_of_vic = SimpleNamespace(id=8890, username="gangsta", first_name="گانگستر", is_bot=False)
    upd = _tgroup("حمله", 8891, "victim1", "قربانی", reply_user=atk_of_vic)
    await battle_h3.attack_cmd(upd, None)
    check("بیهوش پیام «حالت جا نیومده» می‌گیره",
          "💀 هنوز حالت جا نیومده" in upd.message.calls[-1][1]
          and "دقیقه دیگه دوباره آماده نبرد میشی" in upd.message.calls[-1][1])

    # زنده شدن خودکار قربانی برای تست‌های بعدی
    async with session_scope() as s:
        vic = await users.get_by_tg(s, 8891)
        vic.dead_until = now_utc() - timedelta(seconds=1)
        battle_svc.revive_if_due(vic)
        check("قربانی بعد ۱۰ دقیقه با HP فول برگشت",
              vic.dead_until is None and vic.hp == battle_svc.max_hp(vic.level))
        await s.commit()

    # حمله با @یوزرنیم به کسی که هنوز استارت نکرده (از رجیستری دیده‌شده‌ها)
    _IDS = {8891: ("victim1", "قربانی"), 8892: ("stranger8", "غریبه")}

    class _GangBot:
        async def get_chat_member(self, chat_id, user_id):
            un, fn = _IDS.get(user_id, (None, "بی‌نام"))
            return SimpleNamespace(status="member", user=SimpleNamespace(
                id=user_id, username=un, first_name=fn, is_bot=False))

    fake_ctx = SimpleNamespace(bot=_GangBot())
    async with session_scope() as s:
        await seen_svc.remember(s, SimpleNamespace(id=8892, username="stranger8", first_name="غریبه"))
        g_atk = await users.get_by_tg(s, 8890)
        g_atk.last_attack_at = None
        g_atk.energy = config.MAX_ENERGY
        await s.commit()
    upd = _tgroup("حمله @stranger8", 8890, "gangsta", "گانگستر")
    await battle_h3.attack_cmd(upd, fake_ctx)
    atxt = next((c[1] for c in upd.message.calls if "💥" in c[1]), "")
    check("حمله با @یوزرنیم به غریبه کار می‌کنه",
          "<b>💥 به حریف «غریبه» حمله کردی</b>" in atxt and "دمیج وارد شد" in atxt,
          atxt.replace("\n", " | ")[:160])
    async with session_scope() as s:
        stn = await users.get_by_tg(s, 8892)
        check("غریبه هم پروفایل گرفت و HPش کم شد",
              stn is not None and stn.hp is not None and stn.hp < battle_svc.max_hp(1))
        await s.commit()

    # یوزرنیم ناشناس → پیدا نکردم
    upd = _tgroup("حمله @nobody_here_x", 8890, "gangsta", "گانگستر")
    await battle_h3.attack_cmd(upd, fake_ctx)
    check("یوزرنیم ناشناس «پیدا نکردم» میده", "پیدا نکردم" in upd.message.calls[-1][1])

    # کسی که دیگه تو گروه نیس (get_chat_member خطا بده)
    class _NoMemBot:
        async def get_chat_member(self, chat_id, user_id):
            from telegram.error import BadRequest
            raise BadRequest("User not found")

    async with session_scope() as s:
        await seen_svc.remember(s, SimpleNamespace(id=8893, username="gone_user", first_name="رفته"))
        await s.commit()
    upd = _tgroup("حمله @gone_user", 8890, "gangsta", "گانگستر")
    await battle_h3.attack_cmd(upd, SimpleNamespace(bot=_NoMemBot()))
    check("کسی که تو گروه نیس رد میشه", "تو این گروه نیس" in upd.message.calls[-1][1])

    # حمله با آیدی عددی
    async with session_scope() as s:
        g_atk = await users.get_by_tg(s, 8890)
        g_atk.last_attack_at = None
        g_atk.energy = config.MAX_ENERGY
        vic = await users.get_by_tg(s, 8891)
        vic.hp = battle_svc.max_hp(vic.level)
        vic.dead_until = None
        await s.commit()
    upd = _tgroup("پیو 8891", 8890, "gangsta", "گانگستر")
    await battle_h3.attack_cmd(upd, fake_ctx)
    check("حمله با آیدی عددی هم کار می‌کنه",
          any("<b>💥 به حریف «قربانی» حمله کردی</b>" in c[1] for c in upd.message.calls))

    # تو پی‌وی حمله، پنل هدف شانسی پی‌وی باز میشه
    upd = _text_update("حمله", uid=8890, uname="gangsta", fname="گانگستر")
    await battle_h3.attack_cmd(upd, None)
    pvt = upd.message.calls[-1][1]
    pvk = upd.message.calls[-1][2].get("reply_markup")
    check("حمله تو پی‌وی پنل هدف شانسی رو نشون میده",
          "هدف شانسی" in pvt
          and pvk is not None
          and any(b.callback_data == "patt:go" for row in pvk.inline_keyboard for b in row))

    # زیر نتیجه حمله پی‌وی به‌جای هدف شانسی، دکمه بازگشت به پنل حمله میاد
    from keyboards import keyboards as kb_ar
    prk = kb_ar.pv_result_kb()
    prs = [b.callback_data for row in prk.inline_keyboard for b in row]
    pr_txts = [b.text for row in prk.inline_keyboard for b in row]
    check("کیبورد نتیجه حمله پی‌وی: بازگشت + منوی اصلی، بدون هدف شانسی",
          prs == ["patt:back", "menu:home"] and pr_txts[0] == "🔙 بازگشت", f"{pr_txts} {prs}")

    # ═══ این دور: حمله پی‌وی کلاسیک ۱۲ساعته | کریتیکال گروهی ۲٪ | گیت لول و قیمت مزرعه ═══
    from services import pvattack as pv_svc
    from handlers import attack as pv_h3

    # ── کانفیگ حمله پی‌وی کلاسیک ──
    check("کانفیگ حمله پی‌وی کلاسیک",
          config.PV_ATTACK_ENERGY_COST == 15 and config.PV_ATTACK_LEVEL_RANGE == 4
          and config.PV_ATTACK_MIN_CHANCE == 0.15 and config.PV_ATTACK_MAX_CHANCE == 0.85
          and config.PV_BASE_CHANCE == 0.50)
    check("مصونیت پی‌وی دقیقا 6 ساعته", config.PV_ATTACK_SHIELD_SECONDS == 6 * 3600,
          str(config.PV_ATTACK_SHIELD_SECONDS))
    check("غارت و جریمه پی‌وی تو کانفیگن",
          config.PV_ATTACK_STEAL_MIN_PCT == 0.08 and config.PV_ATTACK_STEAL_MAX_PCT == 0.20
          and config.PV_ATTACK_LOSE_PENALTY_PCT == 0.05)
    check("کولدان حمله پی‌وی دقیقا 5 دقیقه‌ست", config.PV_ATTACK_COOLDOWN_SECONDS == 300)
    check("تجربه قربانی و هزینه شکستن سپر تو کانفیگن",
          config.PV_ATTACK_VICTIM_XP == 3 and config.PV_ATTACK_SHIELD_BREAK_COST == 1500)
    check("هزینه هدف دیگه خطی از 25 لول یک تا 1000 مکس‌لوله",
          config.PV_REROLL_MIN_COST == 25 and config.PV_REROLL_MAX_COST == 1000
          and pv_svc.reroll_cost(1) == 25
          and pv_svc.reroll_cost(config.MAX_LEVEL) == 1000
          and 25 < pv_svc.reroll_cost(10) < 1000)
    check("هزینه جاسوسی خطی از 50 لول یک تا 1000 مکس‌لوله",
          config.PV_SPY_MIN_COST == 50 and config.PV_SPY_MAX_COST == 1000
          and pv_svc.spy_cost(1) == 50
          and pv_svc.spy_cost(config.MAX_LEVEL) == 1000
          and 50 < pv_svc.spy_cost(10) < 1000)

    # ── شانس برد کلاسیک: پایه ۵۰٪ و کف/سقف ──
    check("شانس پایه با قدرت برابر 50 درصده", pv_svc.win_chance(100, 100) == 0.50)
    check("قوات غیرمتعادل به کف و سقف کلمپ میشه",
          pv_svc.win_chance(1, 99999) == config.PV_ATTACK_MIN_CHANCE
          and pv_svc.win_chance(99999, 1) == config.PV_ATTACK_MAX_CHANCE)

    # ── لیست هدف: فقط ±۲ لول، بدون خودش و بدون مصونیت‌دارها ──
    async with session_scope() as s:
        a0, _ = await users.get_or_create(s, tg(9400, "pvhero", "قهرمان"))
        a0.level = 20
        for vid, lv in ((9401, 18), (9402, 19), (9403, 21), (9404, 22),
                        (9405, 15), (9406, 25), (9407, 20)):
            v, _ = await users.get_or_create(s, tg(vid, f"pv{vid}", f"طرف{vid}"))
            v.level = lv
            v.shield_until = None
        sh = await users.get_by_tg(s, 9407)
        sh.shield_until = now_utc() + timedelta(hours=1)
        await s.commit()

        picked = set()
        picked_lvls = set()
        for _ in range(60):
            t = await pv_svc.pick_random_target(s, a0)
            if t is not None:
                picked.add(t.telegram_id)
                picked_lvls.add(t.level)
        check("هدف شانسی فقط حوالی لول خودته (±۴)",
              picked and all(abs(lv - 20) <= 4 for lv in picked_lvls)
              and {9405, 9406}.isdisjoint(picked), str(sorted(picked)))
        check("خودش و مصونیت‌دارها شانسی هم انتخاب نمیشن",
              9400 not in picked and 9407 not in picked, str(sorted(picked)))

        ex = await users.get_by_tg(s, 9401)
        picked2 = set()
        for _ in range(60):
            t = await pv_svc.pick_random_target(s, a0, exclude_id=ex.id)
            if t is not None:
                picked2.add(t.telegram_id)
        check("هدف دیگه هدف فعلی پیش‌نمایش رو کنار می‌ذاره",
              9401 not in picked2 and picked2, str(sorted(picked2)))

        # ── اجرای برد: انرژی + غارت درصدی + مصونیت ۱۲ساعته + آمار ──
        atk_u = await users.get_by_tg(s, 9400)
        vic = await users.get_by_tg(s, 9401)
        atk_u.energy = config.MAX_ENERGY
        atk_u.cash = 5000
        atk_u.pv_attack_at = None
        vic.cash = 10000
        vic.shield_until = None
        vxp_b = vic.xp
        wins_b, losses_b, e_before = atk_u.wins, vic.losses, atk_u.energy
        _old_wc = pv_svc.win_chance
        pv_svc.win_chance = lambda a, d: 1.0
        try:
            res = await pv_svc.execute(s, atk_u, vic)
        finally:
            pv_svc.win_chance = _old_wc
        lo = int(10000 * config.PV_ATTACK_STEAL_MIN_PCT)
        hi = int(10000 * config.PV_ATTACK_STEAL_MAX_PCT)
        check("حمله پی‌وی با شانس کامل برده", res["ok"] and res["won"], str(res))
        check("انرژی حمله پی‌وی کم میشه", atk_u.energy == e_before - config.PV_ATTACK_ENERGY_COST)
        check("غارت پی‌وی تو بازه درصدی و دقیق جابه‌جا میشه",
              lo <= res["steal"] <= hi and vic.cash == 10000 - res["steal"]
              and atk_u.cash == 5000 + res["steal"], f"{res['steal']} تو {lo}..{hi}")
        check("قربانی 6 ساعت مصونیت گرفت",
              vic.shield_until is not None and 21540 <= pv_svc.shield_left(vic) <= 21600,
          str(pv_svc.shield_left(vic)))
        check("برد و باخت پی‌وی ثبت میشه", atk_u.wins == wins_b + 1 and vic.losses == losses_b + 1)
        check("قربانی تجربه ناچیز پی‌وی گرفت",
              res["victim_xp"] == config.PV_ATTACK_VICTIM_XP
              and vic.xp == vxp_b + config.PV_ATTACK_VICTIM_XP, f"{vxp_b} → {vic.xp}")
        check("کولدان مهاجم بعد حمله ثبت شد", pv_svc.cooldown_left(atk_u) > 0)

        # ── حمله دوباره به مصون رد میشه و انرژی نمی‌سوزونه ──
        res2 = await pv_svc.execute(s, atk_u, vic)
        check("به مصون دوباره حمله نمیشه", not res2["ok"] and res2["reason"] == "shield")
        check("مصونیت انرژی نمی‌سوزونه", atk_u.energy == e_before - config.PV_ATTACK_ENERGY_COST)

        # ── کولدان ۱ دقیقه‌ای مهاجم: قربانی سالم هم باشه حمله رد میشه ──
        atk_u.energy = config.MAX_ENERGY
        vic_cd = await users.get_by_tg(s, 9402)
        vic_cd.shield_until = None
        res_cd = await pv_svc.execute(s, atk_u, vic_cd)
        check("حمله تو کولدان رد میشه و انرژی نمی‌سوزونه",
              not res_cd["ok"] and res_cd["reason"] == "cooldown" and res_cd["left"] > 0
              and atk_u.energy == config.MAX_ENERGY, str(res_cd))
        atk_u.pv_attack_at = None

        # ── اجرای باخت: جریمه ۵٪ از جیب مهاجم به قربانی ──
        vic2 = await users.get_by_tg(s, 9402)
        vic2.shield_until = None
        vic2.cash = 0
        atk_u.cash = 8000
        vic2_wins_b = vic2.wins
        pv_svc.win_chance = lambda a, d: 0.0
        try:
            res3 = await pv_svc.execute(s, atk_u, vic2)
        finally:
            pv_svc.win_chance = _old_wc
        pen = int(8000 * config.PV_ATTACK_LOSE_PENALTY_PCT)
        check("باخت پی‌وی جریمه رو به قربانی میرسونه",
              res3["ok"] and not res3["won"] and res3["penalty"] == pen
              and atk_u.cash == 8000 - pen and vic2.cash == pen and vic2.wins == vic2_wins_b + 1,
          str(res3))

        # ── فالبک وسیع: رنج خالی → اول بالاترها، نبود پایین‌ترها ──
        fa, _ = await users.get_or_create(s, tg(9420, "pvfar", "خیلی‌بالا"))
        fa.level = 50
        fa.shield_until = None
        # تو رنج ±۴ از لول 50 فقط خود 9420-ه که هدف نمیشه، بقیه همه پایین‌ترن → فالبک پایین‌تر
        t_fb = await pv_svc.pick_random_target(s, fa)
        check("فالبک وقتی بالاتری نیس پایین‌ترلولی میاره",
              t_fb is not None and t_fb.telegram_id != 9420 and t_fb.level < 50,
              str(t_fb.telegram_id if t_fb else None))
        hi, _ = await users.get_or_create(s, tg(9421, "pvhigh", "بالاتر از همه"))
        hi.level = 99
        hi.shield_until = None
        t_hi = await pv_svc.pick_random_target(s, fa)
        check("فالبک وقتی بالاتری هست حتی خیلی دور، اونو میاره",
              t_hi is not None and t_hi.telegram_id == 9421, str(t_hi.telegram_id if t_hi else None))
        hi.shield_until = None
        lo, _ = await users.get_or_create(s, tg(9422, "pvlow", "پایین‌تر از همه"))
        lo.level = 1
        lo.shield_until = now_utc() + timedelta(hours=2)
        fb, _ = await users.get_or_create(s, tg(9423, "pvbelow", "خیلی‌پایین"))
        fb.level = 10
        # پنجره ±4 لول fb خالی بمونه تا فالبک بالاترها اجرا شه، بقیه لول 6 تا 14 رو سپر می‌کنیم
        win_users = (await s.execute(
            __import__("sqlalchemy").select(User).where(User.level >= 6, User.level <= 14, User.id != fb.id)
        )).scalars().all()
        for wu in win_users:
            wu.shield_until = now_utc() + timedelta(hours=2)
        t_up = await pv_svc.pick_random_target(s, fb)
        check("فالبک وقتی پایین‌تری نیس بالاترلولی میاره",
              t_up is not None and t_up.level > 10, str(t_up.telegram_id if t_up else None))
        for wu in win_users:
            wu.shield_until = None
        await s.flush()

        # ── خودزنی رد میشه و رنج لول دیگه بلاک نیس (فالبک وسیع) ──
        res5 = await pv_svc.execute(s, atk_u, atk_u)
        check("خودزنی پی‌وی رد میشه", not res5["ok"] and res5["reason"] == "self")
        await s.commit()

    # ── فلوی کامل پی‌وی: دستور → لیست → تایید → اجرا → مصونیت ──
    async with session_scope() as s:
        e_atk, _ = await users.get_or_create(s, tg(9410, "pve2e", "ایتوئی"))
        e_atk.level = 20
        e_atk.energy = config.MAX_ENERGY
        e_atk.cash = 10000
        e_atk.pv_attack_at = None
        for vid, lv in ((9411, 20), (9412, 19)):
            v, _ = await users.get_or_create(s, tg(vid, f"pv{vid}", f"طرف{vid}"))
            v.level = lv
            v.cash = 9000
            v.shield_until = None
        await s.commit()

    upd = _text_update("حمله", uid=9410, uname="pve2e", fname="ایتوئی")
    await battle_h3.attack_cmd(upd, None)
    plist_txt = upd.message.calls[-1][1]
    plist_kb = upd.message.calls[-1][2].get("reply_markup")
    pdata = [b.callback_data for row in plist_kb.inline_keyboard for b in row]
    check("دستور «حمله» تو پی‌وی پنل هدف شانسی میده",
          "هدف شانسی" in plist_txt and "patt:go" in pdata, pdata[:6])
    check("پنل شانسی پیش‌نمایش و جاسوسی و مصونیت و نبرد گروهی رو توضیح میده",
          "هدف شانسی نزدیک لولت رو پیدا کن" in plist_txt
          and "پیش‌نمایشش رو می‌بینی" in plist_txt and "🕵 با جاسوسی جیب و قدرت دفاع و شانس بردت لو میره" in plist_txt
          and "مصون" in plist_txt and "داخل گروه‌ها" in plist_txt, plist_txt[:120])

    # دکمه شانسی: هدف کنترل‌شده تزریق میشه (SQL انتخاب شانسی با تست سرویس پوشش داده شد)
    async def _pick9411(session, u, exclude_id=None):
        return await users.get_by_tg(session, 9411)
    async def _pick9412(session, u, exclude_id=None):
        if exclude_id:
            return await users.get_by_tg(session, 9412)
        return await users.get_by_tg(session, 9411)
    async def _pick_none(session, u, exclude_id=None):
        return None

    class _FakeBot:
        def __init__(self):
            self.sent = []
        async def send_message(self, chat_id, text, **k):
            self.sent.append((chat_id, text))

    _fake_ctx = SimpleNamespace(bot=_FakeBot())
    _old_pick = pv_svc.pick_random_target
    _old_wc = pv_svc.win_chance
    pv_svc.pick_random_target = _pick9411
    pv_svc.win_chance = lambda a, d: 1.0
    try:
        upd = _fake_update("patt:go", uid=9410)
        await pv_h3.target_go_cb(upd, _fake_ctx)
    finally:
        pv_svc.pick_random_target = _old_pick
        pv_svc.win_chance = _old_wc
    rt = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    rkb = next((c[2].get("reply_markup") for c in upd.callback_query.calls if c[0] == "edit"), None)
    rdata = [b.callback_data for row in rkb.inline_keyboard for b in row] if rkb else []
    rtexts = [b.text for row in rkb.inline_keyboard for b in row] if rkb else []
    check("هدف شانسی اول پیش‌نمایش قربانی رو نشون میده، بدون شانس رایگان",
          "<b>🎯 هدف پیدا شد</b>" in rt and "طرف9411" in rt and "شانس برد 100 درصد" not in rt
          and "می‌زنیش یا یه هدف دیگه می‌خوای؟" in rt and "🕵 با جاسوسی" in rt, rt)
    async with session_scope() as s:
        id9411 = (await users.get_by_tg(s, 9411)).id
        id9412 = (await users.get_by_tg(s, 9412)).id
    check("دکمه‌های پیش‌نمایش: حمله، جاسوسی با قیمت، هدف دیگه با قیمت، بازگشت",
          rdata == [f"patt:hit:{id9411}", f"patt:spy:{id9411}", f"patt:next:{id9411}", "patt:back"]
          and "🕵 جاسوسی" in rtexts[1] and "1,000 TP" in rtexts[1]
          and "هدف دیگه" in rtexts[2] and "1,000 TP" in rtexts[2], str(rtexts))

    # ── جاسوسی: جیب و دفاع و شانس لو میره و هزینه کم میشه ──
    upd = _fake_update(f"patt:spy:{id9411}", uid=9410)
    await pv_h3.target_spy_cb(upd, None)
    rt = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    ans = next((c for c in upd.callback_query.calls if c[0] == "answer"), None)
    async with session_scope() as s:
        c_spy = (await users.get_by_tg(s, 9410)).cash
    check("جاسوسی گزارش جیب و دفاع و درصد رو الرت میده و 1000 هزینه برمیداره",
          ans is not None and ans[1] and ans[2].get("show_alert")
          and "🕵 جاسوسی از «طرف9411» گزارش داد" in str(ans[1][0])
          and "💰 جیبش 9,000 تی‌پوینت" in str(ans[1][0])
          and "🛡 قدرت دفاع" in str(ans[1][0]) and "🎲 شانس بردت" in str(ans[1][0])
          and "درصد" in str(ans[1][0])
          and c_spy == 10000 - pv_svc.spy_cost(20) and pv_svc.spy_cost(20) == 1000
          and "طرف9411" in rt, f"{ans} | {c_spy}")

    # پول کم: جاسوسی نمیشه، الرت یکدست و پول دست‌نخورده
    async with session_scope() as s:
        low2 = await users.get_by_tg(s, 9410)
        low2.cash = 5
        await s.commit()
    upd = _fake_update(f"patt:spy:{id9411}", uid=9410)
    await pv_h3.target_spy_cb(upd, None)
    ans = next((c for c in upd.callback_query.calls if c[0] == "answer"), None)
    async with session_scope() as s:
        c_low2 = (await users.get_by_tg(s, 9410)).cash
        low2 = await users.get_by_tg(s, 9410)
        low2.cash = 9000
        await s.commit()
    check("پول کم جاسوسی نمیده و همون پیش‌نمایش میمونه",
          ans is not None and ans[1] and "پولت برای جاسوسی کمه" in str(ans[1][0])
          and c_low2 == 5, f"{ans} | {c_low2}")

    # هزینه هدف دیگه از جیب کم میشه و قربانی تازه میاد
    pv_svc.pick_random_target = _pick9412
    try:
        upd = _fake_update(f"patt:next:{id9411}", uid=9410)
        await pv_h3.target_next_cb(upd, _fake_ctx)
    finally:
        pv_svc.pick_random_target = _old_pick
    rt = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    rkb = next((c[2].get("reply_markup") for c in upd.callback_query.calls if c[0] == "edit"), None)
    rdata = [b.callback_data for row in rkb.inline_keyboard for b in row] if rkb else []
    check("هدف دیگه یه قربانی تازه میاره", "طرف9412" in rt and f"patt:hit:{id9412}" in rdata and f"patt:spy:{id9412}" in rdata, rt)
    async with session_scope() as s:
        c_after = (await users.get_by_tg(s, 9410)).cash
    check("هزینه هدف دیگه لول 20 برابر 1000 تی‌پوینته و کم شد",
          c_after == 9000 - pv_svc.reroll_cost(20) and pv_svc.reroll_cost(20) == 1000, str(c_after))

    # پول کم: هدف دیگه نمیشه و همون پیش‌نمایش میمونه
    async with session_scope() as s:
        low = await users.get_by_tg(s, 9410)
        low.cash = 5
        await s.commit()
    pv_svc.pick_random_target = _pick9411
    try:
        upd = _fake_update(f"patt:next:{id9412}", uid=9410)
        await pv_h3.target_next_cb(upd, _fake_ctx)
    finally:
        pv_svc.pick_random_target = _old_pick
    rt = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    ans = next((c for c in upd.callback_query.calls if c[0] == "answer"), None)
    async with session_scope() as s:
        c_low = (await users.get_by_tg(s, 9410)).cash
    check("پول کم هدف دیگه نمیده و همون پیش‌نمایش میمونه",
          "طرف9412" in rt and ans is not None and ans[1] and "پولت برای هدف دیگه کمه" in str(ans[1][0])
          and c_low == 5, f"{rt[:40]} | {ans}")

    # هدف دیگه‌ای نباشه: همون پیش‌نمایش میمونه با الرت دقیق و پول کم نمیشه
    async with session_scope() as s:
        en = await users.get_by_tg(s, 9410)
        en.cash = 10000
        await s.commit()
    pv_svc.pick_random_target = _pick_none
    try:
        upd = _fake_update(f"patt:next:{id9412}", uid=9410)
        await pv_h3.target_next_cb(upd, _fake_ctx)
    finally:
        pv_svc.pick_random_target = _old_pick
    rt = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    ans = next((c for c in upd.callback_query.calls if c[0] == "answer"), None)
    async with session_scope() as s:
        c_en = (await users.get_by_tg(s, 9410)).cash
    check("هدف دیگه نیس همون پیش‌نمایش میمونه با الرت دقیق و بی‌هزینه",
          "طرف9412" in rt and c_en == 10000
          and ans is not None and ans[1] and ans[1][0] == "فعلا هدفی جز این در حوالی لولت پیدا نمیشه", rt)

    # دکمه بازگشت برمی‌گرده به پنل شانسی
    upd = _fake_update("patt:back", uid=9410)
    await pv_h3.target_back_cb(upd, _fake_ctx)
    rt = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    check("بازگشت پنل هدف شانسی رو برمی‌گردونه", "هدف شانسی" in rt, rt[:60])

    # حمله: برد + متن تمیز مهاجم + دی‌ام قربانی + مصونیت و کولدان
    pv_svc.pick_random_target = _pick9411
    pv_svc.win_chance = lambda a, d: 1.0
    try:
        upd = _fake_update("patt:go", uid=9410)
        await pv_h3.target_go_cb(upd, _fake_ctx)
        upd = _fake_update(f"patt:hit:{id9411}", uid=9410)
        await pv_h3.target_hit_cb(upd, _fake_ctx)
    finally:
        pv_svc.pick_random_target = _old_pick
        pv_svc.win_chance = _old_wc
    rt = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    check("نتیجه حمله تمیزه: فقط برد/باخت + پول و تجربه، حرفی از مصونیت نیس",
          "<b>⚔️ بردی!</b>" in rt and "غارت کردی" in rt and "طرف9411" in rt
          and "تجربه گرفتی" in rt and "12 ساعت" not in rt and "مصون" not in rt, rt)
    dm = _fake_ctx.bot.sent[-1] if _fake_ctx.bot.sent else (0, "")
    check("به قربانی تو پی‌وی خبر حمله رسید",
          _fake_ctx.bot.sent and dm[0] == 9411
          and "بهت حمله شد" in dm[1] and "دزدید" in dm[1] and "تجربه گرفتی" in dm[1], dm[1][:120])
    async with session_scope() as s:
        vis = await users.get_by_tg(s, 9411)
        atk9 = await users.get_by_tg(s, 9410)
        check("قربانی 12 ساعت مصون و مهاجم تو کولدانه",
              pv_svc.shield_left(vis) > 0 and pv_svc.cooldown_left(atk9) > 0)

    # کولدان ۱ دقیقه‌ای: نه هدف شانسی نه حمله
    upd = _fake_update("patt:go", uid=9410)
    await pv_h3.target_go_cb(upd, _fake_ctx)
    ans = next((c for c in upd.callback_query.calls if c[0] == "answer"), None)
    check("تو کولدان هدف شانسی الرت ثانیه میده",
          ans is not None and ans[1] and "ثانیه دیگه می‌تونی حمله کنی" in str(ans[1][0]), str(ans)[:90])
    upd = _fake_update(f"patt:hit:{id9412}", uid=9410)
    await pv_h3.target_hit_cb(upd, _fake_ctx)
    ans = next((c for c in upd.callback_query.calls if c[0] == "answer"), None)
    check("تو کولدان حمله هم الرت ثانیه میده",
          ans is not None and ans[1] and "ثانیه دیگه می‌تونی حمله کنی" in str(ans[1][0]), str(ans)[:90])

    # حریف سپردار: صفحه انتخاب شکستن سپر میاد
    async with session_scope() as s:
        brk, _ = await users.get_or_create(s, tg(9415, "brk", "شکننده"))
        brk.level = 20
        brk.energy = config.MAX_ENERGY
        brk.cash = 10
        brk.pv_attack_at = None
        await s.commit()
    upd = _fake_update(f"patt:hit:{id9411}", uid=9415)
    await pv_h3.target_hit_cb(upd, _fake_ctx)
    rt = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    rkb = next((c[2].get("reply_markup") for c in upd.callback_query.calls if c[0] == "edit"), None)
    rdata = [b.callback_data for row in rkb.inline_keyboard for b in row] if rkb else []
    check("حمله به سپردار صفحه انتخاب شکستن سپر میاره",
          "سپر داره" in rt and "طرف9411" in rt
          and rdata == [f"patt:break:{id9411}", "patt:back"], rt[:80])

    # شکستن سپر بدون پول کافی: الرت و سپر سر جاش
    upd = _fake_update(f"patt:break:{id9411}", uid=9415)
    await pv_h3.target_break_cb(upd, _fake_ctx)
    rt = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    ans = next((c for c in upd.callback_query.calls if c[0] == "answer"), None)
    async with session_scope() as s:
        c15 = (await users.get_by_tg(s, 9415)).cash
        sh11 = pv_svc.shield_left(await users.get_by_tg(s, 9411))
    check("پول کم سپر نمی‌شکنه و سپر سر جاشه",
          "سپر داره" in rt and ans is not None and ans[1] and "پولت برای شکستن سپر کمه" in str(ans[1][0])
          and c15 == 10 and sh11 > 0, f"{rt[:40]} | {ans}")

    # شکستن سپر با پول: هزینه کم میشه، حمله اجرا میشه و قربانی دوباره سپر می‌گیره + دی‌ام
    async with session_scope() as s:
        brk2, _ = await users.get_or_create(s, tg(9414, "brk2", "پولدار"))
        brk2.level = 20
        brk2.energy = config.MAX_ENERGY
        brk2.cash = 5000
        brk2.pv_attack_at = None
        await s.commit()
    n_sent = len(_fake_ctx.bot.sent)
    pv_svc.win_chance = lambda a, d: 1.0
    try:
        upd = _fake_update(f"patt:break:{id9411}", uid=9414)
        await pv_h3.target_break_cb(upd, _fake_ctx)
    finally:
        pv_svc.win_chance = _old_wc
    rt = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    async with session_scope() as s:
        c14 = (await users.get_by_tg(s, 9414)).cash
        sh11b = pv_svc.shield_left(await users.get_by_tg(s, 9411))
    check("شکستن سپر هزینه‌ش کم شد و حمله انجام شد و سپر تازه نشست",
          "<b>⚔️ بردی!</b>" in rt
          and 4000 <= c14 <= 5300 and sh11b > 0, f"cash={c14}")
    check("به قربانی از شکستن سپر هم دی‌ام رفت",
          len(_fake_ctx.bot.sent) == n_sent + 1
          and _fake_ctx.bot.sent[-1][0] == 9411 and "بهت حمله شد" in _fake_ctx.bot.sent[-1][1])

    # ── نبض انرژی: هر ۵ دقیقه +۲۰ به همه با یه کوئری، سقف MAX_ENERGY ──
    check("کانفیگ نبض انرژی ۵ دقیقه‌ی ۲۰تاییه",
          config.ENERGY_PULSE_SECONDS == 300 and config.ENERGY_PULSE_AMOUNT == 20)
    from handlers import jobs as jobs_h2
    async with session_scope() as s:
        e1 = await users.get_by_tg(s, 9400)  # انرژیش کم شده با حمله‌ها
        e1.energy = 50
        e2, _ = await users.get_or_create(s, tg(9420, "nrg2", "شارژی"))
        e2.energy = 95
        e3, _ = await users.get_or_create(s, tg(9421, "nrg3", "فولی"))
        e3.energy = config.MAX_ENERGY
        await s.commit()

        await s.execute(jobs_h2._energy_pulse_stmt())
        await s.commit()

        e1 = await users.get_by_tg(s, 9400)
        e2 = await users.get_by_tg(s, 9420)
        e3 = await users.get_by_tg(s, 9421)
        check("نبض انرژی ۲۰ تا به همه اضافه می‌کنه", e1.energy == 50 + 20, str(e1.energy))
        check("نبض انرژی روی سقف کلمپ میشه", e2.energy == config.MAX_ENERGY
              and e3.energy == config.MAX_ENERGY, f"{e2.energy}/{e3.energy}")

        e1.energy = 0
        await s.commit()
        await s.execute(jobs_h2._energy_pulse_stmt())
        await s.commit()
        e1 = await users.get_by_tg(s, 9400)
        check("نبض پشت‌سرهم بدون حلقه پر می‌کنه", e1.energy == 20, str(e1.energy))

    # ── ریجن تنبلی دیگه انرژی نمیده، فقط سقف نگه می‌داره (share سرور مهمه) ──
    async with session_scope() as s:
        lazy = await users.get_by_tg(s, 9400)
        lazy.energy = 10
        lazy.energy_updated_at = now_utc() - timedelta(hours=5)
        users.apply_energy_regen(lazy)
        check("ریجن تنبلی انرژی اضافه نمی‌کنه (فقط نبض دسته‌جمعی)",
              lazy.energy == 10, str(lazy.energy))
        lazy.energy = config.MAX_ENERGY + 50
        users.apply_energy_regen(lazy)
        check("ریجن تنبلی سقف رو نگه می‌داره", lazy.energy == config.MAX_ENERGY)
        await s.commit()

    # جاب واقعی نبض انرژی (ایندپوینت async)
    async with session_scope() as s:
        j1 = await users.get_by_tg(s, 9400)
        j1.energy = 0
        await s.commit()
    await jobs_h2.energy_pulse_job(None)
    async with session_scope() as s:
        j1 = await users.get_by_tg(s, 9400)
        check("جاب نبض انرژی واقعی اجرا میشه", j1.energy == 20, str(j1.energy))
    async with session_scope() as s:
        v1 = await users.get_by_tg(s, 9411)
        check("قربانی شانسی واقعا 6 ساعت مصون شد",
              v1.shield_until is not None and pv_svc.shield_left(v1) > 0)

    async with session_scope() as s:
        ntr = await users.get_by_tg(s, 9410)
        ntr.pv_attack_at = None
        await s.commit()
    pv_svc.pick_random_target = _pick_none
    try:
        upd = _fake_update("patt:go", uid=9410)
        await pv_h3.target_go_cb(upd, None)
    finally:
        pv_svc.pick_random_target = _old_pick
    nt = next((c[1] for c in upd.callback_query.calls if c[0] == "edit"), "")
    check("هدف نیس پیام دقیق تک‌خطی «هدفی حوالی لولت پیدا نشد» میاد",
          nt == "😴 هدفی حوالی لولت پیدا نشد", nt)

    # ── کریتیکال نبرد گروهی ۲٪ ──
    check("کانفیگ کریتیکال گروهی 2 درصده",
          config.BATTLE_CRIT_CHANCE == 0.02 and config.BATTLE_CRIT_MULT == 2.0)
    random.seed(11)
    _ocrit = config.BATTLE_CRIT_CHANCE
    config.BATTLE_CRIT_CHANCE = 1.0
    try:
        d_crit = [battle_svc.roll_damage(150, 100, 200) for _ in range(50)]
    finally:
        config.BATTLE_CRIT_CHANCE = 0.0
    check("با شانس کامل همه ضربه‌ها کریتیکال فلگ میخورن", all(c for _, c in d_crit))
    try:
        d_norm = [battle_svc.roll_damage(150, 100, 200) for _ in range(50)]
    finally:
        config.BATTLE_CRIT_CHANCE = _ocrit
    check("با شانس صفر هیچ کریتیکالی نیس", all(not c for _, c in d_norm))
    check("دمیج کریتیکال از معمولی بالاتره",
          sum(d for d, _ in d_crit) > sum(d for d, _ in d_norm) * 1.5,
          f"{sum(d for d, _ in d_crit)} vs {sum(d for d, _ in d_norm)}")

    ctxt = battle_h3.hit_text(
        {"dmg": 40, "crit": True, "hp_now": 100, "hp_max": 200,
         "steal": 0, "xp": 5, "notes": [], "killed": False}, "سارا")
    check("خط کریتیکال تو متن ضربه گروهی میاد",
          "⚡ کریتیکال" in ctxt and "🩸 40 دمیج وارد شد" in ctxt, ctxt)

    # ── گیت لول آپگرید زمین (سرویس) ──
    async with session_scope() as s:
        fu = await users.get_by_tg(s, 9410)  # لول ۲۰، همه آپگریدها براش بازه
        fu.cash = 500000
        fu.wood = 0
        p1 = Plot(user_id=fu.id, status="empty", level=1)
        s.add(p1)
        await s.flush()
        ok, msg = await farming.upgrade_plot(s, fu, p1)
        check("آپگرید زمین بدون چوب رد میشه", not ok and "چوب" in msg, msg)
        fu.wood = 500
        ok, msg = await farming.upgrade_plot(s, fu, p1)
        check("آپگرید زمین لول ۱ به ۲ با تی‌پوینت و چوب",
              ok and p1.level == 2 and fu.cash == 500000 - 8000 and fu.wood == 500 - 30, msg)

        fu2, _ = await users.get_or_create(s, tg(9415, "lowlvl", "کم‌لول"))
        fu2.level = 1
        fu2.cash = 999999
        f2 = Plot(user_id=fu2.id, status="empty", level=1)
        s.add(f2)
        await s.flush()
        ok, msg = await farming.upgrade_plot(s, fu2, f2)
        check("آپگرید زمین زیر لول ۳ قفله",
              not ok and "آپگرید به لول 2 لول 3 می‌خواد" in msg and f2.level == 1, msg)
        await s.commit()

    lk = kb2.farm_kb(SimpleNamespace(level=1),
                     [SimpleNamespace(id=998, level=1, current_status=lambda: ("empty", 0))], 1000, 0)
    ltexts = [b.text for row in lk.inline_keyboard for b in row]
    check("دکمه آپگرید قفل‌شده با لول لازم تو مزرعه دیده میشه",
          any("🔒 آپگرید | لول 3" in t for t in ltexts), str(ltexts))

    # ── رجیستری دیده‌شده‌ها case-insensitive ──
    async with session_scope() as s:
        await seen_svc.remember(s, SimpleNamespace(id=8895, username="CaseName", first_name="کیس"))
        row = await seen_svc.find_by_username(s, "@casename")
        check("یوزرنیم case-insensitive پیدا میشه", row is not None and row.telegram_id == 8895)
        await s.commit()

    # ── فلوی کامل درمان: همون لحظه استفاده، بدون انبار ──
    async with session_scope() as s:
        hl, _ = await users.get_or_create(s, tg(8894, "healy", "زخمی"))
        hl.cash = 5000
        hl.hp = battle_svc.max_hp(1)
        await s.commit()
    upd = _text_update("/heal", uid=8894, uname="healy", fname="زخمی")
    await battle_h3.heal_cmd(upd, None)
    check("HP فول پیام دقیق درمان میاره",
          upd.message.calls[-1][1] == "❤️ سلامتت کامله\nفعلاً نیازی به درمان نداری",
          upd.message.calls[-1][1][:60])

    async with session_scope() as s:
        hl = await users.get_by_tg(s, 8894)
        hl.hp = 100
        await s.commit()
    upd = _text_update("تی درمان", uid=8894, uname="healy", fname="زخمی")
    await battle_h3.heal_cmd(upd, None)
    hhome = upd.message.calls[-1][1]
    hhkb = upd.message.calls[-1][2].get("reply_markup")
    check("صفحه درمان ساده‌ست، آیتم‌ها فقط روی دکمه‌ها",
          "<b>❤️ درمان</b>" in hhome and "❤️ سلامت تو" in hhome and "100 از 200" in hhome
          and "🩹 باند کوچک" not in hhome and "💉 کیت درمان" not in hhome
          and "همون لحظه استفاده میشه" in hhome
          and hhkb is not None
          and any(b.callback_data == "heal:buy:band" for row in hhkb.inline_keyboard for b in row),
          hhome.replace("\n", " | ")[:230])
    hhtexts = [b.text for row in hhkb.inline_keyboard for b in row]
    check("دکمه‌های صفحه درمان قالب نام | قیمت | سلامت رو دارن",
          "🩹 باند کوچک | 🪙 400 TP | 🏥 سلامت +75" in hhtexts
          and "💉 کیت درمان | 🪙 900 TP | 🏥 سلامت +150" in hhtexts
          and "🏥 جعبه کمک‌های اولیه | 🪙 1,800 TP | 🏥 سلامت فول" in hhtexts, str(hhtexts))

    # باند: همون لحظه +75 و قیمتش از جیب رفت
    upd = _fake_update("heal:buy:band", uid=8894)
    await battle_h3.heal_buy_cb(upd, None)
    async with session_scope() as s:
        hl = await users.get_by_tg(s, 8894)
        check("باند همون لحظه +75 HP داد و قیمتش کم شد و تو انبار نیس",
              hl.hp == 175 and hl.cash == 5000 - config.HEAL_ITEMS["band"]["price"])
        hl.hp = battle_svc.max_hp(1)
        await s.commit()

    # HP فول، خرید رد میشه
    upd = _fake_update("heal:buy:band", uid=8894)
    await battle_h3.heal_buy_cb(upd, None)
    ans = next((c for c in upd.callback_query.calls if c[0] == "answer"), None)
    check("خرید با HP فول رد میشه با پیام دقیق",
          ans is not None and "سلامتت کامله" in str(ans[1]), str(ans)[:130])

    # پول کم، جعبه داده نمیشه
    async with session_scope() as s:
        hl = await users.get_by_tg(s, 8894)
        hl.hp = 50
        hl.cash = 100
        await s.commit()
    upd = _fake_update("heal:buy:box", uid=8894)
    await battle_h3.heal_buy_cb(upd, None)
    ans = next((c for c in upd.callback_query.calls if c[0] == "answer"), None)
    check("پول کم جعبه رو نمی‌ده", ans is not None and "پولت" in str(ans[1]) and "کمه" in str(ans[1]))

    # جعبه فول‌کننده
    async with session_scope() as s:
        hl = await users.get_by_tg(s, 8894)
        hl.cash = 5000
        await s.commit()
    upd = _fake_update("heal:buy:box", uid=8894)
    await battle_h3.heal_buy_cb(upd, None)
    async with session_scope() as s:
        hl = await users.get_by_tg(s, 8894)
        check("جعبه کمک‌های اولیه HP رو فول کرد و قیمتش کم شد",
              hl.hp == battle_svc.max_hp(1) and hl.cash == 5000 - config.HEAL_ITEMS["box"]["price"])
        await s.commit()

    # بیهوش نمی‌تونه درمان بشه
    async with session_scope() as s:
        hl = await users.get_by_tg(s, 8894)
        hl.dead_until = now_utc() + timedelta(seconds=300)
        hl.hp = 0
        await s.commit()
    upd = _fake_update("heal:buy:band", uid=8894)
    await battle_h3.heal_buy_cb(upd, None)
    ans = next((c for c in upd.callback_query.calls if c[0] == "answer"), None)
    check("بیهوش نمی‌تونه درمان بشه", ans is not None and "حالت جا نیومده" in str(ans[1]))
    async with session_scope() as s:
        hl = await users.get_by_tg(s, 8894)
        hl.dead_until = None
        hl.hp = battle_svc.max_hp(hl.level)
        await s.commit()

    # ── پروفایل قالب جدید: اسم ساده با قطع طولانی‌ها + خطوط اموال + خط تجربه ──
    from handlers import profile as profile_h2
    from utils import short_name as _sn
    check("اسم بلندتر از نمونه با چهار نقطه قطع میشه",
          _sn("Cosholatasdfghhjklq") == "Cosholatasdfghhjkl....")
    check("اسم کوتاه و معمولی همونطوری میمونه",
          _sn("Cosholat") == "Cosholat" and _sn("علی") == "علی"
          and _sn("Cosholatasdfghhjkl") == "Cosholatasdfghhjkl")
    check("اسم با ۱۹ کاراکتر میشه ۱۸ تاش با نقاط",
          len(_sn("a" * 19)) == 22 and _sn("a" * 19).endswith("...."))
    async with session_scope() as s:
        pf = await users.get_by_tg(s, 8890)
        cap = await profile_h2._profile_caption(s, pf)
        await s.commit()
    cap_xp = next((ln for ln in cap.split("\n") if ln.startswith("🌟 لول")), "")
    check("پروفایل خط لول و تجربه قالب جدید رو داره",
          cap_xp.startswith("🌟 لول 10 • ✨ ") and "/" in cap_xp, cap_xp)
    check("پروفایل مزرعه‌ش سه خطه",
          "🌱 زمین:" in cap and "\n🌾 در حال رشد:" in cap and "\n✅ آماده برداشت:" in cap)
    check("پروفایل رتبه و آمار جنگی داره",
          "🏆 رتبه" in cap and "<b>⚔️ آمار</b>" in cap and "💪 حمله:" in cap)

    async with session_scope() as s:
        pf2, _ = await users.get_or_create(s, tg(8896, "maxi", "ماکسی"))
        pf2.level = config.MAX_LEVEL
        pf2.xp = 10958
        cap2 = await profile_h2._profile_caption(s, pf2)
        await s.commit()
    cap2_xp = next((ln for ln in cap2.split("\n") if ln.startswith("🌟 لول")), "")
    check("بعد لول مکس فقط تجربه جمع‌شده نوشته میشه",
          cap2_xp == "🌟 لول 20 👑 • ✨ 10,958" and "/" not in cap2_xp, cap2_xp)

    # ── سقف لول ۲۰: لول قفل میشه ولی تجربه جمع میشه ──
    async with session_scope() as s:
        mx, _ = await users.get_or_create(s, tg(8897, "capp", "سقفی"))
        mx.level = 19
        notes = users.add_xp(mx, economy.xp_need(19) * 3)
        check("لول روی ۲۰ قفل میشه و بقیه تجربه جمع می‌مونه",
              mx.level == config.MAX_LEVEL and mx.xp > 0 and len(notes) >= 1)
        check("پیام لول مکس هم اومد", any("👑 لولت مکس شد" in n for n in notes))
        xp_b = mx.xp
        notes2 = users.add_xp(mx, 100)
        check("بعد مکس دیگه لول‌آپ نیس و فقط تجربه جمع میشه",
              mx.level == config.MAX_LEVEL and mx.xp == xp_b + 100 and notes2 == [])
        await s.commit()

    # ═════════ بازطراحی شاپ و سیستم پیشرفت ═════════
    from services import resources as res_svc
    from services import company as comp_svc
    from services import combat as combat_svc
    from handlers import mine as mine_h2
    from handlers import company as comp_h
    from handlers import shop as shop_h2
    from keyboards import keyboards as kb3

    # ── منابع: ظرفیت و واریز با سقف ──
    async with session_scope() as s:
        ru, _ = await users.get_or_create(s, tg(9601, "resu", "منبعی"))
        ru.shelter_level = 0
        check("ظرفیت چوب و آهن پایه",
              res_svc.wood_cap(ru) == config.RES_WOOD_CAP_TABLE[0] == 200
              and res_svc.iron_cap(ru) == config.RES_IRON_CAP_TABLE[0] == 100)
        check("ظرفیت با لول مخفیگاه بیشتر میشه",
              res_svc.wood_cap(SimpleNamespace(shelter_level=2)) == config.RES_WOOD_CAP_TABLE[2])
        check("ظرفیت انبار لول‌های پایین مثل قبله و لول ۱۰ به‌اندازه خروجی کارخونه مکس",
              config.RES_WOOD_CAP_TABLE[:3] == [200, 350, 500] and config.RES_IRON_CAP_TABLE[:3] == [100, 180, 260]
              and config.RES_WOOD_CAP_TABLE[10] >= 2880 and config.RES_IRON_CAP_TABLE[10] >= 3600)
        ru.wood = config.RES_WOOD_CAP_TABLE[0] - 5
        got = res_svc.add_res(ru, "wood", 100)
        check("واریز منبع سقف انبار رو رد نمی‌کنه", got == 5 and ru.wood == config.RES_WOOD_CAP_TABLE[0], str(got))
        check("برداشت منبع بدون موجودی کافی نمیشه", not res_svc.take_res(ru, "iron", 1))
        await s.commit()

    # ── دراپ کنده‌کاری: تی‌پوینت + تجربه + شانسی چوب/آهن ──
    async with session_scope() as s:
        mu, _ = await users.get_or_create(s, tg(9602, "miner2", "ماینر۲"))
        mu.axe_level = 5
        mu.pick_level = 5
        raws = [res_svc.mine_loot(mu) for _ in range(400)]
        check("تی‌پوینت کنده‌کاری همیشه میده", all(config.MINE_MIN <= r["cash"] for r in raws))
        check("تجربه کنده‌کاری پایه ۱ تا ۵ (شکار کمیاب دوبرابرش می‌کنه)",
              all(1 <= loot["xp"] <= config.MINE_XP_MAX * config.MINE_RARE_MULT
                  and (loot["rare"] or loot["xp"] <= config.MINE_XP_MAX)
                  for loot in (res_svc.mine_loot(SimpleNamespace(axe_level=1, pick_level=1)) for _ in range(200))))
        check("بونس تجربه ابزار تو کنده‌کاری",
              res_svc.mine_xp_mult(mu) == 1 + config.TOOL_XP_PER_LEVEL * 8)
        check("تجربه با ابزار قوی می‌تونه از ۵ رد بشه",
              max(r["xp"] for r in raws) > 5, str(max(r["xp"] for r in raws)))
        check("با ابزار مکس هم چوب هم آهن میفتاد",
              sum(1 for r in raws if r["wood"]) > 100 and sum(1 for r in raws if r["iron"]) > 50)
        check("شکار کمیاب گاهی اتفاق میفته، چوب و آهن حتمی و مولتیپلایرن",
              any(r["rare"] for r in raws)
              and all(r["wood"] >= config.MINE_RARE_MULT and r["iron"] >= config.MINE_RARE_MULT
                      for r in raws if r["rare"]))
        check("تی‌پوینت با ابزار ضرب میشه", res_svc.mine_cash_mult(mu) == 1 + config.TOOL_CASH_PER_LEVEL * 8)
        check("هزینه ارتقای ابزار از جدوله",
              res_svc.tool_upgrade_cost("axe", 1) == config.TOOLS["axe"]["upgrades"][0]
              and res_svc.tool_upgrade_cost("axe", config.TOOL_MAX_LEVEL) is None)
        await s.commit()

    # ── هندلر کنده‌کاری: رول با منابع + صفحه بخش ──
    upd_m = _text_update("کنده کاری", uid=9602, uname="miner2", fname="ماینر۲")
    await mine_h2.mine_cmd(upd_m, None)
    mt = next(c[1] for c in upd_m.message.calls if "⛏️ کنده‌کاری" in c[1])
    check("متن کنده‌کاری با قالب جدید و منابعه",
          all(x in mt for x in ["⛏️ کنده‌کاری", "تی‌پوینت به دست آوردی", "تجربه گرفتی", "🪙 موجودی:"])
          and len(next(c[2].get("reply_markup") for c in upd_m.message.calls if "⛏️ کنده‌کاری" in c[1]).inline_keyboard) >= 3,
          mt.replace("\n", "|")[:100])
    upd_m2 = _fake_update("menu:mine", uid=9602)
    await mine_h2.mine_home_cb(upd_m2, None)
    mt2 = next((c[1] for c in upd_m2.callback_query.calls if c[0] == "edit"), "")
    check("صفحه مستقل کنده کاری لول ابزار و موجودی رو نشون میده",
          all(x in mt2 for x in ["⛏ کنده کاری", "🪓 تبر لول 5", "کلنگ لول 5", "🪵 چوب", "⛏️ آهن"]), mt2[:80])

    # ── ارتقای تبر (تاییدیه + کسر آهن و تی‌پوینت) ──
    async with session_scope() as s:
        mu2 = await users.get_by_tg(s, 9602)
        mu2.axe_level = 1
        mu2.cash = 50000
        mu2.iron = 20
        await s.commit()
    upd_m3 = _fake_update("mine:upg:axe", uid=9602)
    await mine_h2.mine_upg_confirm(upd_m3, None)
    check("تاییدیه ارتقای تبر میاد",
          any("ارتقای 🪓 تبر" in c[1] for c in upd_m3.callback_query.calls if c[0] == "edit"))
    upd_m4 = _fake_update("cf:mine:upg:axe", uid=9602)
    await mine_h2.mine_upg_execute(upd_m4, None)
    async with session_scope() as s:
        mu3 = await users.get_by_tg(s, 9602)
        check("تبر لول ۲ شد و هزینه‌اش کم شد",
              mu3.axe_level == 2 and mu3.cash == 50000 - config.TOOLS["axe"]["upgrades"][0][0]
              and mu3.iron == 20 - config.TOOLS["axe"]["upgrades"][0][1], f"{mu3.axe_level}")

    # ── شرکت: ساخت، تولید lazy، ارتقا ──
    async with session_scope() as s:
        cu, _ = await users.get_or_create(s, tg(9603, "compo", "کارخونه‌دار"))
        cu.level = 6  # ساخت شرکت از لول 5 بازه
        cu.cash = 100000
        cu.wood = 500
        ok, msg = await comp_svc.build(s, cu, "lumber")
        check("چوب‌بری ساخته شد با تی‌پوینت",
              ok and cu.lumber_level == 1 and cu.cash == 100000 - config.FACTORIES["lumber"]["build"][0], msg)
        ok, msg = await comp_svc.build(s, cu, "ironmill")
        w_left = 500 - config.FACTORIES["ironmill"]["build"][1]
        check("کارخانه آهن چوب هم می‌خواست و کمش کرد",
              ok and cu.ironmill_level == 1 and cu.wood == w_left, f"{cu.wood}")
        cu.company_at = now_utc() - timedelta(seconds=config.FACTORY_TICK_SECONDS * 3)
        cu.wood = 0
        cu.iron = 0
        got = await comp_svc.settle(s, cu)
        check("تسویه lazy سه تیک تولید داد و ریخت تو انبار کارخونه",
              got["ticks"] == 3 and got["wood"] == 3 * config.FACTORIES["lumber"]["per_tick"]
              and got["iron"] == 3 * config.FACTORIES["ironmill"]["per_tick"]
              and cu.lumber_stock == got["wood"] and cu.ironmill_stock == got["iron"]
              and cu.wood == 0 and cu.iron == 0, str(got))
        got2 = await comp_svc.collect(s, cu, "lumber")
        check("برداشت انبار کارخونه چوب رو میده دست بازیکن",
              got2[0] and "📥" in got2[1] and cu.wood == got["wood"] and cu.lumber_stock == 0,
              f"{got2} | {cu.wood}/{cu.lumber_stock}")
        cu.cash = 500000
        cu.wood = 500
        ok, msg = await comp_svc.upgrade(s, cu, "lumber")
        tp2, w2 = comp_svc.upgrade_cost("lumber", 2)
        check("ارتقای چوب‌بری تی‌پوینت و چوب خورد",
              ok and cu.lumber_level == 2 and cu.wood == 500 - w2, msg)
        check("تولید با لول بیشتر میشه",
              comp_svc.factory_production("lumber", 2) == 2 * config.FACTORIES["lumber"]["per_tick"])
        await s.commit()

    # صفحه شرکت
    upd_c = _fake_update("menu:company", uid=9603)
    await comp_h.company_cb(upd_c, None)
    ctxt = next((c[1] for c in upd_c.callback_query.calls if c[0] == "edit"), "")
    check("صفحه شرکت ساختمان‌ها و موجودی منابع رو نشون میده",
          all(x in ctxt for x in ["🏭 شرکت", "🪵 چوب‌بری", "کارخانه آهن", "🪵 چوب", "⛏️ آهن"]), ctxt[:90])

    # ── آرتیفکت: گیت لول ۱۰، یکبار خرید، اثر روی استت ──
    check("آرتیفکت از لول ۱۰ بازه", config.ARTIFACT_MIN_LEVEL == 10)
    async with session_scope() as s:
        au, _ = await users.get_or_create(s, tg(9604, "arti", "آرتیفکتی"))
        au.cash = 5000000
        au.level = 9
        ok, msg = await shop_svc.purchase(s, au, "arti", "dragon")
        check("آرتیفکت زیر لول ۱۰ رد میشه", not ok and "لول" in msg)
        au.level = 12
        ok, msg = await shop_svc.purchase(s, au, "arti", "dragon")
        check("آرتیفکت خریده شد و کلید arti_ خورد",
              ok and "arti_dragon" in await users.get_item_keys(s, au.id), msg)
        ok, _ = await shop_svc.purchase(s, au, "arti", "dragon")
        check("آرتیفکت دوباره خریده نمیشه", not ok)
        keys = await users.get_item_keys(s, au.id)
        atk0, _ = combat_svc.combat_stats(au, [], [])
        atk1, dfn1 = combat_svc.combat_stats(au, keys, [])
        check("قلب اژدها قدرت حمله رو درصدی بیشتر می‌کنه",
              atk1 == int(atk0 * (1 + config.ARTIFACTS["dragon"]["atk_mult"])), f"{atk0}→{atk1}")
        check("تاج تاریکی غارت رو بیشتر می‌کنه",
              users.artifact_steal_bonus({"crown"}) == config.ARTIFACTS["crown"]["steal_bonus"])
        check("هسته رعد تجربه رو بیشتر می‌کنه",
              users.artifact_xp_mult({"thunder"}) == 1 + config.ARTIFACTS["thunder"]["xp_mult"])
        await s.commit()

    # صفحه آرتیفکت شاپ
    upd_a = _fake_update("shop:sec:arti", uid=9604)
    await shop_h2.render_section(upd_a, "arti")
    atxt = next((c[1] for c in upd_a.callback_query.calls if c[0] == "edit"), "")
    check("صفحه آرتیفکت باکس‌ها و قیمت‌ها رو داره",
          all(x in atxt for x in ["🧿 آرتیفکت", "🔥 قلب اژدها", "🛡 سنگ نگهبان", "⚡ هسته رعد",
                                  "🍀 شبدر افسانه‌ای", "👑 تاج تاریکی", "افزایش غارت"]), atxt[:90])

    # ── ارتقای سلاح و زره: استت بیشتر + کسر تی‌پوینت و آهن + گیت لول ──
    async with session_scope() as s:
        gu, _ = await users.get_or_create(s, tg(9605, "upgr", "آپگریدی"))
        gu.cash = 1000000
        gu.iron = 500
        gu.level = 20
        s.add(InventoryItem(user_id=gu.id, item_key="colt"))
        await s.flush()
        s0 = economy.gear_stat("weap", "colt", 1)
        s2 = economy.gear_stat("weap", "colt", 2)
        s5 = economy.gear_stat("weap", "colt", 5)
        row = (await s.execute(
            __import__("sqlalchemy").select(InventoryItem).where(
                InventoryItem.user_id == gu.id, InventoryItem.item_key == "colt"))).scalar_one()
        tp1 = economy.gear_upg_tp("weap", "colt", 1)
        ir1 = economy.gear_upg_iron("weap", "colt", 1)
        c_b, i_b = gu.cash, gu.iron
        row.level += 1
        gu.cash -= tp1
        gu.iron -= ir1
        await s.commit()
        check("استت سلاح با لول بیشتر میشه", s2 > s0 and s5 > s2, f"{s0}→{s2}→{s5}")
        check("گیت لول ارتقای گیر از جدوله",
              config.GEAR_UPG_LEVELS == [2, 5, 9, 13] and economy.gear_upg_min_level(1) == 2)

    # هندلر ارتقا با تاییدیه
    async with session_scope() as s:
        gu2 = await users.get_by_tg(s, 9605)
        gu2.iron = 500
        gu2.cash = 1000000
        await s.commit()
    upd_g = _fake_update("gup:weap:colt", uid=9605)
    await shop_h2.gear_up_confirm(upd_g, None)
    check("تاییدیه ارتقای سلاح استت فعلی و بعدی رو نشون میده",
          any("⬆️ ارتقای کلت کمری" in c[1] and "دمیج" in c[1] for c in upd_g.callback_query.calls if c[0] == "edit"))
    cash_before = 0
    async with session_scope() as s:
        gu3 = await users.get_by_tg(s, 9605)
        cash_before, iron_before = gu3.cash, gu3.iron
        lvl_before = (await users.get_item_levels(s, gu3.id))["colt"]
        await s.commit()
    upd_g2 = _fake_update("cf:gup:weap:colt", uid=9605)
    await shop_h2.gear_up_execute(upd_g2, None)
    async with session_scope() as s:
        gu4 = await users.get_by_tg(s, 9605)
        lvl_after = (await users.get_item_levels(s, gu4.id))["colt"]
        check("ارتقا اعمال شد و تی‌پوینت و آهن کم شد",
              lvl_after == lvl_before + 1
              and gu4.cash == cash_before - economy.gear_upg_tp("weap", "colt", lvl_before)
              and gu4.iron == iron_before - economy.gear_upg_iron("weap", "colt", lvl_before),
              f"{lvl_before}→{lvl_after}")

    # ── قالب جدید بخش سلاح شاپ: سه دسته سرد/گرم/ویژه + قفل قرمز ──
    async with session_scope() as s:
        su, _ = await users.get_or_create(s, tg(9606, "shoper", "خریدار"))
        su.level = 6
        await s.commit()
    upd_s = _fake_update("shop:sec:weap", uid=9606)
    await shop_h2.render_section(upd_s, "weap")
    stxt = next((c[1] for c in upd_s.callback_query.calls if c[0] == "edit"), "")
    skb = next((c[2].get("reply_markup") for c in upd_s.callback_query.calls if c[0] == "edit"), None)
    check("صفحه سلاح سه دسته رو نشون میده",
          all(x in stxt for x in ["🔪 سلاح سرد", "🔫 سلاح گرم", "🚀 سلاح ویژه"]), stxt[:120])
    check("دسته قفل تو متن بازگشایی داره",
          "🔒" in stxt and "⭕️ بازگشایی در سطح" in stxt, stxt[:200])
    secbtns = [b for row in skb.inline_keyboard for b in row]
    check("دکمه دسته باز سبزه",
          any(b.callback_data == "shop:sec:wcold" and b.style == "success" for b in secbtns)
          and any(b.callback_data == "shop:sec:whot" and b.style == "success" for b in secbtns),
          str([(b.text, b.style) for b in secbtns]))
    check("دسته قفل (لول کم) قرمزه",
          any(b.callback_data == "noop:lock" and b.style == "danger" for b in secbtns),
          str([(b.text, b.style) for b in secbtns]))

    # صفحه دسته گرم: باکس + دکمه بدون قیمت + قفل «به لول N»
    upd_s2 = _fake_update("shop:sec:whot", uid=9606)
    await shop_h2.render_section(upd_s2, "whot")
    ctxt = next((c[1] for c in upd_s2.callback_query.calls if c[0] == "edit"), "")
    ckb = next((c[2].get("reply_markup") for c in upd_s2.callback_query.calls if c[0] == "edit"), None)
    check("متن دسته گرم باکسی و فقط اطلاعات اصلیه",
          all(x in ctxt for x in ["🔫 سلاح گرم", "کلت کمری", "💥 دمیج", "⛏️", "تی‌پوینت",
                                  "⭕️ بازگشایی در سطح"]), ctxt[:200])
    cbtns = [b for row in ckb.inline_keyboard for b in row]
    buy_txt = [b.text for b in cbtns if b.callback_data.startswith("shop:buy:weap:")]
    lock_btns = [b for b in cbtns if b.callback_data == "noop:lock"]
    check("دکمه سلاح فقط اسمه و قیمت توش نیس",
          any("کلت کمری" in t for t in buy_txt)
          and all("تی‌پوینت" not in t and "TP" not in t and "⛏" not in t for t in buy_txt), str(buy_txt))
    check("دکمه قفل «به لول N» قرمزه",
          len(lock_btns) >= 3
          and all(t.text.startswith("🔒") and "به لول" in t.text for t in lock_btns)
          and all(b.style == "danger" for b in lock_btns), str([t.text for t in lock_btns]))
    check("دکمه خرید سبزه", all(b.style == "success" for b in cbtns if b.callback_data.startswith("shop:buy:weap:")))

    # ── بخش سگ شاپ: ویژگی درصدی هر نژاد + تی‌پوینت کامل + خط وضعیت زیر تیتر ──
    upd_d = _fake_update("shop:sec:dog", uid=9606)
    await shop_h2.render_section(upd_d, "dog")
    dtxt = next((c[1] for c in upd_d.callback_query.calls if c[0] == "edit"), "")
    check("بخش سگ شاپ ویژگی درصدی هر نژاد رو نشون میده",
          all(x in dtxt for x in ["🐕 پیتبول", "⚡ کاهش کولدان حمله تا 10%",
                                  "دوبرمن", "🛡 دفاع بیشتر تا 10%",
                                  "ژرمن شپرد", "🎁 تجربه بیشتر از نبرد تا 15%",
                                  "کانگال", "💥 قدرت حمله بیشتر تا 10%",
                                  "گرگ سیاه", "☠ غارت بیشتر تا 10%", "تا 30%"])
          and "توصیف" not in dtxt, dtxt[:200])
    dlines = dtxt.splitlines()
    check("خط وضعیت سطح و موجودی زیر تیتر بخش سگه",
          len(dlines) > 1 and dlines[1].startswith("🌟 سطح:") and "💵 موجودی:" in dlines[1]
          and "TP" in dlines[1], dlines[1] if len(dlines) > 1 else "-")
    drest = "\n".join(dlines[2:])
    check("قیمت سگ‌ها با تی‌پوینت کامله و TP فقط تو خط وضعیته",
          "تی‌پوینت" in drest and " TP" not in drest, drest[:200])
    check("دو خط آخر قدیمی بخش سگ حذف شدن",
          "هر نژاد فقط شخصیت" not in dtxt and "از نبرد تجربه می‌گیرن" not in dtxt)

    # ── ویژگی درصدی نژادها + تجربه سگ از نبرد + تغییر اسم ──
    async with session_scope() as s:
        du, _ = await users.get_or_create(s, tg(9607, "dogow", "سگدار"))
        du.level = 20
        du.cash = 999000
        ok, _ = await dog_svc.buy_dog(s, du, "doberman", custom_name="تندرو")
        ok, _ = await dog_svc.buy_dog(s, du, "kangal", custom_name="غول")
        dd = await dog_svc.get_user_dogs(s, du.id)
        check("پیتبول کولدان حمله رو تا 10% کم می‌کنه (لول مکس)",
              round(dog_svc.breed_cooldown_mult(
                  [SimpleNamespace(dog_key="pitbull", level=config.DOG_MAX_LEVEL, personality=None)]), 3) == 0.90)
        check("پیتبول لول پایین اثر کمتری داره",
              dog_svc.breed_cooldown_mult(
                  [SimpleNamespace(dog_key="pitbull", level=1, personality=None)]) > 0.95)
        check("ژرمن شپرد تجربه نبرد بیشتر میده",
              round(dog_svc.battle_xp_mult(
                  [SimpleNamespace(dog_key="shepherd", level=config.DOG_MAX_LEVEL, personality=None)]), 3) == 1.15)
        check("کانگال قدرت حمله و دوبرمن دفاع درصدی میدن",
              round(dog_svc.trait_atk_pct(
                  [SimpleNamespace(dog_key="kangal", level=config.DOG_MAX_LEVEL, personality=None)]), 3) == 0.10
              and round(dog_svc.trait_def_pct(
                  [SimpleNamespace(dog_key="doberman", level=config.DOG_MAX_LEVEL, personality=None)]), 3) == 0.10)
        kang = [d for d in dd if d.dog_key == "kangal"][0]
        check("کانگال هم شخصیت نداره (همه نولن)", kang.personality is None)
        check("خط ویژگی با درصد فعلی لوله (بدون ایموجی خود ویژگی، با دو نقطه)",
              dog_svc.trait_ability_lines(
                  SimpleNamespace(dog_key="pitbull", level=config.DOG_MAX_LEVEL, personality=None))
              == ["🎖 ویژگی: کاهش کولدان حمله 10%"],
              str(dog_svc.trait_ability_lines(SimpleNamespace(dog_key="pitbull", level=10, personality=None))))
        pit = SimpleNamespace(dog_key="pitbull", level=1, xp=0, personality=None, name="x")
        notes_d = await dog_svc.add_battle_xp([d for d in dd], config.DOG_BATTLE_XP_HIT)
        check("سگ‌ها از نبرد تجربه می‌گیرن", all(d.xp >= config.DOG_BATTLE_XP_HIT for d in dd))
        pit.xp = 0
        d10 = SimpleNamespace(dog_key="doberman", level=1, xp=dog_svc.dog_xp_need(1) - 1, personality=None, name="ی")
        notes_lv = await dog_svc.add_battle_xp([d10], config.DOG_BATTLE_XP_HIT * 5)
        check("سگ با تجربه نبرد لول‌آپ می‌کنه", d10.level == 2 and any("لول" in n for n in notes_lv), str(notes_lv))
        ok, msg = dog_svc.rename_dog(dd, "تندرو", "رعد")
        check("«اسم سگ» تغییر نام کار می‌کنه",
              ok and [d for d in dd if d.dog_key == "doberman"][0].name == "رعد", msg)
        ok, msg = dog_svc.rename_dog(dd, "رعد", "غول")
        check("اسم تکراری دو سگ رد میشه", not ok)
        await s.commit()

    # هندلر متنی «اسم سگ»
    upd_r = _text_update("اسم سگ غول کوه", uid=9607, uname="dogow", fname="سگدار")
    await dogs_h.dog_rename_text(upd_r, None)
    async with session_scope() as s:
        du2 = await users.get_by_tg(s, 9607)
        dd2 = await dog_svc.get_user_dogs(s, du2.id)
        check("دستور «اسم سگ» اسم رو عوض کرد",
              any(d.name == "کوه" for d in dd2), str([d.name for d in dd2]))

    # ── منابع تو شاپ: خرید دونه‌ای چوب و آهن ──
    async with session_scope() as s:
        bu, _ = await users.get_or_create(s, tg(9608, "buyer", "پک‌خر"))
        bu.cash = 10000
        ok, msg = await shop_svc.purchase_resource(s, bu, "wood", 5)
        check("خرید دونه‌ای چوب از شاپ",
              ok and bu.wood == 5 and bu.cash == 10000 - 5 * config.RES_SHOP["wood"]["unit"], msg)
        ok, msg = await shop_svc.purchase_resource(s, bu, "iron", 2)
        check("خرید دونه‌ای آهن تی‌پوینت کم و آهن زیاد می‌کنه",
              ok and bu.iron == 2 and bu.cash == 10000 - 750 - 600, msg)
        ok, msg = await shop_svc.purchase_resource(s, bu, "wood", 99999)
        check("بیشتر از جای انبار رد میشه (متن جای خالی)",
              not ok and "جای خالی" in msg, msg)
        bu.cash = 10
        ok, msg = await shop_svc.purchase_resource(s, bu, "iron", 1)
        check("پول ناکافی رد میشه", not ok and "کافی نیس" in msg, msg)
        ok, msg = await shop_svc.purchase_resource(s, bu, "wood", 0)
        check("تعداد صفر رد میشه", not ok and "حداقل" in msg, msg)
        await s.commit()

    # ── منوی اصلی: کنده کاری | شرکت | مخفیگاه ──
    mm = kb3.main_menu_kb()
    mm_datas = [b.callback_data for row in mm.inline_keyboard for b in row]
    check("منوی اصلی کنده کاری و شرکت و مخفیگاه داره",
          all(d in mm_datas for d in ("menu:mine", "menu:company", "menu:shelter")), str(mm_datas))
    sm_kb = kb3.shop_sections_kb()
    sm_datas = [b.callback_data for row in sm_kb.inline_keyboard for b in row]
    check("منوی شاپ ارتقاها و آرتیفکت و منابع رو داره",
          all(d in sm_datas for d in ("menu:gear", "shop:sec:arti", "shop:sec:res")),
          str(sm_datas))

    # ── مخفیگاه: متن با ظرفیت چوب و آهن ──
    async with session_scope() as s:
        hu, _ = await users.get_or_create(s, tg(9609, "hide", "مخفی"))
        hu.shelter_level = 2
        hu.wood = 250
        hu.iron = 26
        await s.commit()
    from handlers import world as world_h2
    upd_h = _text_update("تریاکی مخفیگاه", uid=9609, uname="hide", fname="مخفی")
    await world_h2.shelter_cmd(upd_h, None)
    htxt = upd_h.message.calls[-1][1]
    check("مخفیگاه ظرفیت بذر و چوب و آهن رو نشون میده",
          all(x in htxt for x in ["ظرفیت انبار هر بذر", "🪵 چوب", "⛏️ آهن"]), htxt[:120])
    check("پر بودن انبار با نوار انرژی نشون داده میشه",
          "▰" in htxt and "▱" in htxt and "/" in htxt, htxt[:200])
    hkb = upd_h.message.calls[-1][2].get("reply_markup")
    hdatas = [b.callback_data for row in hkb.inline_keyboard for b in row]
    check("دکمه فروش منابع تو مخفیگاه هست", "shelter:sell" in hdatas, str(hdatas))

    # ── متن جدید نتیجه قمار (برد/باخت) ──
    async with session_scope() as s:
        cz, _ = await users.get_or_create(s, tg(9610, "czno", "قمارباز۲"))
        cz.level = 10
        cz.cash = 500000
        cz.last_casino_at = None
        await s.commit()
    upd_z = _fake_update("cascf:25000", uid=9610)
    await world_h2.casino_execute(upd_z, None)
    ztxt = next((c[1] for c in upd_z.callback_query.calls if c[0] == "edit"
                 or (c[0] == "reply" and True)), "")
    ztxt = upd_z.callback_query.calls[-1][1]
    won_z = "زدی تو خال" in ztxt
    check("متن قمار قالب جدید رو داره (برد یا باخت)",
          (won_z and all(x in ztxt for x in ["🎰 زدی تو خال", "تی‌پوینت برنده شدی", "💵 موجودی فعلی",
                                             "⏳ دست بعدی", "ساعت دیگه"]))
          or (not won_z and all(x in ztxt for x in ["🎰 این دست شانس باهات یار نبود", "تی‌پوینت رو باختی",
                                                    "💰 موجودی فعلی", "⏳ دست بعدی", "ساعت دیگه"])),
          ztxt.replace("\n", " | ")[:120])
    check("مبلغ قمار با تی‌پوینت کامله", "تی‌پوینت برنده شدی" in ztxt or "تی‌پوینت رو باختی" in ztxt)
    check("زمان دست بعدی خط خودشه",
          ztxt.rstrip().endswith("⏳ دست بعدی\n12 ساعت دیگه"), ztxt.split("\n")[-2:])

    # ═══ این دور: دکمه بدون قیمت | سلاح ۳ دسته | فروش منابع | گیت پناهگاه | لول تیم | کنده‌کاری گروهی ═══
    check("سه دسته سلاح: سرد و گرم و ویژه",
          set(config.WEAPON_SECTIONS) == {"cold", "hot", "special"})
    check("هر سلاح یه دسته معتبر داره و هر دسته حداقل یه سلاح",
          all(w.get("sec") in config.WEAPON_SECTIONS for w in config.WEAPONS.values())
          and {w["sec"] for w in config.WEAPONS.values()} == set(config.WEAPON_SECTIONS))
    check("خرید دونه‌ای منابع گرون‌تر از فروششه (تولید می‌صرفه)",
          config.RES_SHOP["wood"]["unit"] == 150 and config.RES_SHOP["iron"]["unit"] == 300
          and config.RES_SELL_PRICES == {"wood": 60, "iron": 150}
          and all(config.RES_SHOP[k]["unit"] > config.RES_SELL_PRICES[k] for k in config.RES_SHOP),
          str(config.RES_SHOP))
    check("اسپلینگ درست کولدان",
          "کاهش کولدان" in config.DOGS["pitbull"]["trait_line"]
          and "کولدون" not in config.DOGS["pitbull"]["trait_line"])

    # ── دکمه‌های شاپ بدون قیمت، فقط اسم ──
    async with session_scope() as s:
        np_u, _ = await users.get_or_create(s, tg(9652, "noprice", "خریدار۲"))
        np_u.level = 20
        np_keys = set(await users.get_item_keys(s, np_u.id))
        np_stock = await farming.get_stock(s, np_u.id)
        no_price_txts = []
        for k2 in (kb3.shop_weap_kb(np_u, np_keys, "hot"), kb3.shop_arm_kb(np_u, np_keys),
                   kb3.shop_arti_kb(np_u, np_keys), kb3.shop_dog_kb(np_u, set(), 0),
                   kb3.shop_seed_kb(np_u, np_stock), kb3.shop_food_kb(),
                   kb3.gear_up_kb("weap", {"colt": 2}, np_u), kb3.gear_up_kb("arm", {"steel": 2}, np_u)):
            for row in k2.inline_keyboard:
                for b in row:
                    if b.callback_data.startswith(("shop:buy:", "gup:")):
                        no_price_txts.append(b.text)
        check("هیچ دکمه خرید یا ارتقایی قیمت نداره",
              no_price_txts and all("تی‌پوینت" not in t and "TP" not in t for t in no_price_txts),
              str(no_price_txts[:4]))
        rkb = kb3.shop_res_kb()
        rtxts = [b.text for row in rkb.inline_keyboard for b in row if b.callback_data.startswith("shop:buy:res:")]
        check("فقط دکمه منابع قیمت داره (قیمت دونه)",
              len(rtxts) == 2 and all("TP" in t and "دونه" in t for t in rtxts), str(rtxts))
        gup_txt = [b.text for row in kb3.gear_up_kb("arm", {"steel": 2}, np_u).inline_keyboard for b in row]
        check("دکمه ارتقا قالب «زره فولادی به لول 3» رو داره",
              any(t.replace("⬆️ ", "") == "زره فولادی به لول 3" for t in gup_txt), str(gup_txt))
        await s.commit()

    # ── 🎒 خرید دونه‌ای چوب/آهن: دکمه → سؤال تعداد → فاکتور ✅/❌ → چک جای انبار ──
    check("قیمت دونه چوب ۱۵۰ و آهن ۳۰۰ شده (پک ثابت حذف شده)",
          config.RES_SHOP["wood"]["unit"] == 150 and config.RES_SHOP["iron"]["unit"] == 300
          and "pack" not in config.RES_SHOP["wood"] and "pack" not in config.RES_SHOP["iron"])
    async with session_scope() as s:
        rb, _ = await users.get_or_create(s, tg(7359, "resb", "خریدارمنابع"))
        rb.cash = 100000
        rb.shelter_level = 0
        rb.wood = res_svc.wood_cap(rb) - 3  # فقط ۳ تا جای خالی تو انبار داره
        rb.iron = 0
        await s.commit()
    upd_rb = _fake_update("shop:buy:res:wood", uid=7359)
    await shop_h2.buy_confirm(upd_rb, None)
    ask_txt = next(c[1] for c in upd_rb.callback_query.calls if c[0] == "edit")
    async with session_scope() as s:
        rb = await users.get_by_tg(s, 7359)
    check("دکمه خرید چوب سؤال «چندتا می‌خوای» رو pending می‌کنه با قیمت دونه",
          rb.pending_action == "resbuy" and rb.pending_value == "wood"
          and "چندتا چوب میخوای بخری؟" in ask_txt
          and "عددشو همینجا بنویس و بفرست، مثلا: 24" in ask_txt
          and "❌ اگر هم پشیمون شدی بنویس «لغو»" in ask_txt
          and "قیمت هر دونه 150 TP" in ask_txt, ask_txt[:170])
    upd_bad = _text_update("سلام", uid=7359, uname="resb", fname="خریدارمنابع")
    try:
        await pending_h.capture(upd_bad, None)
    except Exception:
        pass
    async with session_scope() as s:
        rb = await users.get_by_tg(s, 7359)
        check("عدد غلط pending خرید منابع رو نگه می‌داره",
              rb.pending_action == "resbuy"
              and any("فقط یه عدد صحیح" in c[1] for c in upd_bad.message.calls))
    upd_cl = _text_update("لغو", uid=7359, uname="resb", fname="خریدارمنابع")
    try:
        await pending_h.capture(upd_cl, None)
    except Exception:
        pass
    async with session_scope() as s:
        rb = await users.get_by_tg(s, 7359)
        check("«لغو» pending خرید منابع رو پاک می‌کنه", rb.pending_action is None)
        rb.pending_action, rb.pending_value = "resbuy", "wood"
        await s.commit()
    upd_q = _text_update("24", uid=7359, uname="resb", fname="خریدارمنابع")
    try:
        await pending_h.capture(upd_q, None)
    except Exception:
        pass
    inv = upd_q.message.calls[-1]
    check("فاکتور خرید دونه‌ای با جمع درست و دکمه تایید/لغو میاد",
          inv[0] == "reply" and "🧾 فاکتور خرید 🪵 چوب" in inv[1]
          and "تعداد: 24 دونه" in inv[1] and "جمع فاکتور: 3,600 تی‌پوینت" in inv[1]
          and any(b.callback_data == "cf:shopres:wood:24"
                  for row in inv[2]["reply_markup"].inline_keyboard for b in row)
          and any(b.callback_data == "cl:shopres"
                  for row in inv[2]["reply_markup"].inline_keyboard for b in row),
          inv[1][:170])
    async with session_scope() as s:
        rb = await users.get_by_tg(s, 7359)
        check("بعد از فاکتور pending پاک شده", rb.pending_action is None)
    upd_cf = _fake_update("cf:shopres:wood:24", uid=7359)
    await shop_h2.buyres_execute(upd_cf, None)
    nofit_txt = next(c[1] for c in upd_cf.callback_query.calls if c[0] == "edit")
    async with session_scope() as s:
        rb = await users.get_by_tg(s, 7359)
        check("جای انبار کم باشه با «جای خالی برای اینهمه نداری» رد میشه و پول کم نمیشه",
              "توی انبارت جای خالی برای اینهمه نداری" in nofit_txt
              and "جای 3 تا چوب دیگه داره" in nofit_txt and rb.cash == 100000, nofit_txt[:180])
    upd_cf3 = _fake_update("cf:shopres:wood:3", uid=7359)
    await shop_h2.buyres_execute(upd_cf3, None)
    ok_txt = next(c[1] for c in upd_cf3.callback_query.calls if c[0] == "edit")
    async with session_scope() as s:
        rb = await users.get_by_tg(s, 7359)
        check("تایید فاکتور جا داشته باشه جنس واریز و پول کم میشه",
              rb.wood == res_svc.wood_cap(rb) and rb.cash == 100000 - 450,
              f"wood={rb.wood} cash={rb.cash}")
        check("متن موفقیت موجودی انبار بعد از خرید رو هم می‌گه",
              "موجودی انبارت" in ok_txt, ok_txt[:180])
    upd_cl2 = _fake_update("cl:shopres", uid=7359)
    await shop_h2.buyres_cancel(upd_cl2, None)
    check("لغو فاکتور با الرت برمی‌گرده به بخش منابع شاپ",
          any(a[0] == "answer" and "خرید لغو شد" in str(a[1][0])
              for a in upd_cl2.callback_query.calls if len(a) > 1 and a[1]),
          str(upd_cl2.callback_query.calls)[:120])

    # ── گیت سطح ارتقای پناهگاه ──
    check("جدول سطح ارتقای پناهگاه برای هر لول پر شده",
          len(config.SHELTER_UPGRADE_MIN_LEVELS) == config.SHELTER_MAX_LEVEL)
    async with session_scope() as s:
        sl, _ = await users.get_or_create(s, tg(9653, "shlv", "پناهی"))
        sl.cash = 9999999
        sl.level = 1
        ok_s1, m_s1 = await world_svc.upgrade_shelter(s, sl)
        check("ارتقای پناهگاه به لول ۱ از سطح ۱ ممکنه", ok_s1 and sl.shelter_level == 1, m_s1)
        ok_s2, m_s2 = await world_svc.upgrade_shelter(s, sl)
        check("ارتقای بعدی بدون سطح لازم رد میشه",
              not ok_s2 and "سطح" in m_s2 and sl.shelter_level == 1, m_s2)
        sl.level = config.SHELTER_UPGRADE_MIN_LEVELS[1]
        ok_s3, _ = await world_svc.upgrade_shelter(s, sl)
        check("با سطح لازم ارتقا انجام شد", ok_s3 and sl.shelter_level == 2)
        lock_styles = [b.style for row in kb3.shelter_kb(sl).inline_keyboard
                       for b in row if b.callback_data == "noop:lock"]
        check("دکمه ارتقای انبار زیر سطح قرمزه", lock_styles == ["danger"], str(lock_styles))
        await s.commit()

    # ── لول تیم: تجربه اعضا به تیم میرسه و ظرفیت رشد می‌کنه ──
    async with session_scope() as s:
        txu, _ = await users.get_or_create(s, tg(9654, "txp", "تیمی"))
        txu.level = 12
        txu.cash = 100000
        ok_tt, _ = await team_svc.create_team(s, txu, "تجربه‌ای‌ها")
        check("ساخت تیم برای تست لول تیم", ok_tt)
        ttx = await team_svc.get_team_of(s, txu.id)
        check("تیم از لول ۱ با ۱۰ ظرفیت شروع می‌کنه",
              (ttx.level or 1) == 1 and team_svc.team_capacity(ttx) == config.TEAM_CAP_TABLE[0])
        check("xp صفر چیزی نمی‌ده", (await team_svc.add_team_xp(s, txu, 0)) == [])
        need1 = team_svc.team_xp_need(1)
        notes_tx = await team_svc.add_team_xp(s, txu, 50)
        check("تجربه عضو به تیم میرسه", ttx.xp == 50 and not notes_tx, f"{ttx.xp} {notes_tx}")
        alon_x, _ = await users.get_or_create(s, tg(9655, "lone", "تنها"))
        check("بازیکن بی‌تیم سهمی نمی‌بره", (await team_svc.add_team_xp(s, alon_x, 50)) == [])
        await s.commit()
    upd_tm = _text_update("کنده کاری", uid=9654, uname="txp", fname="تیمی")
    await mine_h.mine_cmd(upd_tm, None)
    async with session_scope() as s:
        txu2 = await users.get_by_tg(s, 9654)
        ttx2 = await team_svc.get_team_of(s, txu2.id)
        check("کنده‌کاری عضو به تیم هم تجربه میده", ttx2.xp > 50, str(ttx2.xp))
        need1 = team_svc.team_xp_need(1)
        add_now = need1 - ttx2.xp
        notes_lv = await team_svc.add_team_xp(s, txu2, add_now)
        check("تیم با تجربه اعضا لول‌آپ می‌کنه و پیام داره",
              ttx2.level == 2 and any("لول 2" in n for n in notes_lv), f"{ttx2.level} {notes_lv}")
        check("ظرفیت تیم با لول رشد کرد (۱۰ ← ۱۲)", team_svc.team_capacity(ttx2) == 12)
        ttx2.level = config.TEAM_MAX_LEVEL
        ttx2.xp = 0
        notes_mx = await team_svc.add_team_xp(s, txu2, 99999)
        check("لول تیم از مکس رد نمیشه و xp جمع میمونه",
              ttx2.level == config.TEAM_MAX_LEVEL and ttx2.xp == 99999 and not notes_mx)
        await s.commit()

    # ── ساختمان تیم به لول تیم وابسته‌ست ──
    async with session_scope() as s:
        tb, _ = await users.get_or_create(s, tg(9656, "tbld", "سازنده"))
        tb.level = 12
        tb.cash = 100000
        await team_svc.create_team(s, tb, "سازندگان")
        tbm = await team_svc.get_team_of(s, tb.id)
        tbm.bank = 9999999
        tbm.level = 1
        ok_b1, m_b1 = await team_svc.upgrade_building(s, tb, "atk")
        check("ساختمان تا لول تیم ارتقا داره", ok_b1 and tbm.atk_bld == 1, m_b1)
        ok_b2, m_b2 = await team_svc.upgrade_building(s, tb, "atk")
        check("ساختمان از لول تیم جلوتر نمی‌زنه", not ok_b2 and "لول تیم" in m_b2, m_b2)
        tbm.level = 5
        ok_b3, _ = await team_svc.upgrade_building(s, tb, "atk")
        check("با لول تیم بالاتر ارتقا انجام میشه", ok_b3 and tbm.atk_bld == 2)
        b_txt = team_h2b_txt = None
        await s.commit()

    # ── فروش منابع از مخفیگاه (دکمه → متن → فاکتور → تایید) ──
    from handlers import pending as pending_h3
    async with session_scope() as s:
        rs, _ = await users.get_or_create(s, tg(9657, "rsell", "فروشنده"))
        rs.iron = 500
        rs.wood = 100
        rs.cash = 1000
        await s.commit()
    upd_rs = _fake_update("shelter:sell", uid=9657)
    await world_h2.resource_sell_cb(upd_rs, None)
    rscall = next((c for c in upd_rs.callback_query.calls if c[0] == "edit"), None)
    check("منوی فروش منابع قالب جدید «تا داری: دونه‌ای» رو با یادآوری فقط چوب و آهن داره",
          rscall is not None
          and all(x in rscall[1] for x in ["💰 فروش منابع", "🪵 چوب 100 تا داری: دونه‌ای 60 تی‌پوینت",
                                           "⛏️ آهن 500 تا داری: دونه‌ای 150 تی‌پوینت",
                                           "فقط چوب و آهن قابل فروش‌اند", "آهن 300", "چوب 200"])
          and "این همه قیمت فروششونه" not in rscall[1],
          (rscall[1][:200] if rscall else "-"))
    async with session_scope() as s:
        rs2 = await users.get_by_tg(s, 9657)
        check("بعد دکمه فروش pending روی ressell ست شد", rs2.pending_action == "ressell", str(rs2.pending_action))
        await s.commit()

    upd_bad = _text_update("سگ 100", uid=9657, uname="rsell", fname="فروشنده")
    try:
        await pending_h3.capture(upd_bad, None)
    except Exception:
        pass
    check("ورودی غلط فروش منابع فرمت رو یادآوری می‌کنه",
          "فرمت درست نیس" in upd_bad.message.calls[-1][1], upd_bad.message.calls[-1][1][:80])
    upd_much = _text_update("آهن 9999", uid=9657, uname="rsell", fname="فروشنده")
    try:
        await pending_h3.capture(upd_much, None)
    except Exception:
        pass
    check("فروش بیشتر از موجودی رد میشه",
          "فقط 500 تا" in upd_much.message.calls[-1][1], upd_much.message.calls[-1][1][:80])
    upd_fs = _text_update("آهن 300", uid=9657, uname="rsell", fname="فروشنده")
    stopped_fs = False
    try:
        await pending_h3.capture(upd_fs, None)
    except Exception as e:
        stopped_fs = type(e).__name__ == "ApplicationHandlerStop"
    fs_text = upd_fs.message.calls[-1][1]
    fs_mark = upd_fs.message.calls[-1][2].get("reply_markup")
    fs_datas = [b.callback_data for row in fs_mark.inline_keyboard for b in row] if fs_mark else []
    check("فاکتور فروش منابع مبلغ کلش رو می‌گه",
          stopped_fs
          and all(x in fs_text for x in ["💰 فروش 300 تا آهن", "قیمت فروشش میشه 45,000 تی‌پوینت", "می‌فروشیم؟"])
          and fs_datas == ["cf:sellres:iron:300", "cl:sellres"], fs_text[:150])
    async with session_scope() as s:
        rs3 = await users.get_by_tg(s, 9657)
        check("تا تایید فاکتور آهن و پول سر جاشونن",
              rs3.cash == 1000 and rs3.iron == 500 and rs3.pending_action is None, f"{rs3.cash}/{rs3.iron}")
        await s.commit()
    upd_cf = _fake_update("cf:sellres:iron:300", uid=9657)
    await world_h2.sellres_execute(upd_cf, None)
    async with session_scope() as s:
        rs4 = await users.get_by_tg(s, 9657)
        check("تایید فروش آهن کم و پول واریز شد",
              rs4.iron == 200 and rs4.cash == 1000 + 300 * config.RES_SELL_PRICES["iron"],
              f"{rs4.iron}/{rs4.cash}")
        ok_w, _, total_w = res_svc.sell_resource(rs4, "wood", 50)
        check("فروش چوب هم سرویسی جوابه",
              ok_w and total_w == 50 * config.RES_SELL_PRICES["wood"] and rs4.wood == 50, f"{total_w}")
        await s.commit()
    cf_text = next((c[1] for c in upd_cf.callback_query.calls if c[0] == "edit"), "")
    check("متن پایان فروش مبلغ و نقدینگی رو نشون میده",
          all(x in cf_text for x in ["💰", "فروخته شد", "💵 نقدینگی"]), cf_text[:150])

    # ── رگرسیون: «لغو» وسط فروش منابع کار می‌کنه (ressell توی لیست لغو نبود) ──
    async with session_scope() as s:
        rc, _ = await users.get_or_create(s, tg(9646, "rcancel", "لغوچی"))
        rc.iron = 50
        await s.commit()
    upd_rc = _fake_update("shelter:sell", uid=9646)
    await world_h2.resource_sell_cb(upd_rc, None)
    upd_lv = _text_update("لغو", uid=9646, uname="rcancel", fname="لغوچی")
    stopped_lv = False
    try:
        await pending_h3.capture(upd_lv, None)
    except Exception as e:
        stopped_lv = type(e).__name__ == "ApplicationHandlerStop"
    lv_txt = upd_lv.message.calls[-1][1]
    async with session_scope() as s:
        rc2 = await users.get_by_tg(s, 9646)
        check("«لغو» وسط فروش منابع pending رو پاک می‌کنه و «کاری در جریان نیس» نمیگه",
              stopped_lv and rc2.pending_action is None
              and "باشه بیخیال فروش منابع شدیم" in lv_txt and "در جریان نیس" not in lv_txt,
              f"{rc2.pending_action} | {lv_txt[:60]}")
        await s.commit()

    # بقیه اکشن‌های فراموش‌شده تو لیست لغو (سرچ اخراج عضو و ست کانال عضویت اجباری)
    for act in ("ressell", "teamkick", "fjchan", "dogname", "bankdep"):
        async with session_scope() as s:
            rc3 = await users.get_by_tg(s, 9646)
            rc3.pending_action = act
            msg_c = await dog_svc.cancel_pending(s, rc3)
            check(f"لغو اکشن {act} توی cancel_pending پشتیبانی میشه",
                  rc3.pending_action is None and "در جریان نیس" not in msg_c, msg_c[:40])
            await s.commit()
    async with session_scope() as s:
        rc4 = await users.get_by_tg(s, 9646)
        rc4.pending_action = None
        msg_c = await dog_svc.cancel_pending(s, rc4)
        check("بدون کار معلق، هنوز «کاری در جریان نیس که» میگه", "در جریان نیس" in msg_c, msg_c[:40])
        await s.commit()

    # ── «کنده کاری» تو گروه منو باز نمی‌کنه و آپگرید دستور جداست ──
    upd_gm = _text_update("کنده کاری", uid=9658, uname="gminer", fname="ماینرگروهی")
    upd_gm.effective_chat = SimpleNamespace(id=-100888, type="supergroup")
    await mine_h.mine_cmd(upd_gm, None)
    check("کنده کاری تو گروه فقط پیام نتیجه‌ست و کیبورد نداره",
          upd_gm.message.calls and all(c[2].get("reply_markup") is None for c in upd_gm.message.calls),
          str(upd_gm.message.calls[-1][2]))
    check("گزارش گروهی هم درآمد رو نشون میده",
          any("تی‌پوینت به دست آوردی" in c[1] for c in upd_gm.message.calls),
          str([c[1][:60] for c in upd_gm.message.calls]))
    upd_pv = _text_update("کنده کاری", uid=9659, uname="pvminer", fname="ماینرپی‌وی")
    await mine_h.mine_cmd(upd_pv, None)
    check("کنده کاری تو پی‌وی کیبورد داره",
          any(c[2].get("reply_markup") is not None for c in upd_pv.message.calls))
    upd_mu = _text_update("تی آپگرید کنده کاری", uid=9659, uname="pvminer", fname="ماینرپی‌وی")
    await mine_h.mine_tools_cb(upd_mu, None)
    check("«تی آپگرید کنده کاری» صفحه اصلی کنده‌کاری با هزینه ارتقای ابزار رو میاره",
          "⛏ کنده کاری" in upd_mu.message.calls[-1][1]
          and "🪓 تبر لول" in upd_mu.message.calls[-1][1]
          and "⬆️ هزینه ارتقا:" in upd_mu.message.calls[-1][1]
          and "وضعیت ابزار" not in upd_mu.message.calls[-1][1],
          upd_mu.message.calls[-1][1][:120])
    upd_mu2 = _text_update("تی کنده کاری آپگرید", uid=9659, uname="pvminer", fname="ماینرپی‌وی")
    await mine_h.mine_tools_cb(upd_mu2, None)
    check("«تی کنده کاری آپگرید» هم همون صفحه اصلی رو میاره",
          "🪓 تبر لول" in upd_mu2.message.calls[-1][1]
          and "⛏️ کلنگ لول" in upd_mu2.message.calls[-1][1],
          upd_mu2.message.calls[-1][1][:120])
    mk_home = [(b.text, b.callback_data) for r in kb.mine_kb().inline_keyboard for b in r]
    check("دکمه وضعیت ابزار از کیبورد کنده‌کاری حذف شده",
          not any(c == "mine:tools" for _, c in mk_home)
          and any(c == "mine:upg:axe" for _, c in mk_home)
          and any(c == "mine:upg:pick" for _, c in mk_home), str(mk_home))

    # ── «تی بکاپ» / «تی کپی»، فایل با اسم تریاکی ──
    from handlers import backup as backup_h

    class _Bot:
        def __init__(self): self.docs = []
        async def send_document(self, chat_id=None, document=None, filename=None, caption=None, **k):
            self.docs.append((chat_id, filename))
    bot_fake = _Bot()
    ctx_fake = SimpleNamespace(bot=bot_fake, user_data={})

    upd_bk = _text_update("تی بکاپ", uid=1001, uname="ali", fname="علی")
    await backup_h.backup_menu_text(upd_bk, ctx_fake)
    check("«تی بکاپ» منوی بک‌آپ رو با دکمه میاره",
          "بکاپ تریاکی" in upd_bk.message.calls[-1][1]
          and upd_bk.message.calls[-1][2].get("reply_markup") is not None, upd_bk.message.calls[-1][1][:60])

    upd_cp = _text_update("تی کپی", uid=1001, uname="ali", fname="علی")
    await backup_h.backup_copy_text(upd_cp, ctx_fake)
    doc_call = [c for c in upd_cp.message.calls if c[0] == "doc"]
    check("«تی کپی» فایل دی‌بی رو با اسم «تریاکی-…» میفرسته",
          bool(doc_call) and doc_call[-1][2]["filename"].startswith("تریاکی-"), str(doc_call))
    check("کپشن بک‌آپ آمار رو داره", bool(doc_call) and "بک‌آپ کامل تریاکی" in doc_call[-1][1])
    check("برای ادمین، نسخه به پی‌وی بقیه اونرها هم میره",
          any(cid == 1003 for cid, _ in bot_fake.docs), str(bot_fake.docs))

    bot_fake.docs.clear()
    upd_cp2 = _text_update("تی کپی", uid=7788, uname="na", fname="معمولی")
    await backup_h.backup_copy_text(upd_cp2, ctx_fake)
    doc_call2 = [c for c in upd_cp2.message.calls if c[0] == "doc"]
    check("کاربر عادی تو پی‌وی بات هم فایل تریاکی رو می‌گیره", bool(doc_call2), str(doc_call2))
    check("ولی نسخه‌ای برای اونرها نمیره", not bot_fake.docs, str(bot_fake.docs))

    upd_cg = _text_update("تی کپی", uid=7788, uname="na", fname="معمولی")
    upd_cg.effective_chat = SimpleNamespace(id=-100777, type="supergroup")
    await backup_h.backup_copy_text(upd_cg, ctx_fake)
    check("«تی کپی» برای غریبه تو گروه سکوت محضه", not upd_cg.message.calls, str(upd_cg.message.calls))

    upd_mk = _fake_update("bk:make", uid=1001)
    async def _mk_doc(document=None, filename=None, caption=None, **k):
        upd_mk.callback_query.calls.append(("doc", caption, {"filename": filename}))
    upd_mk.message.reply_document = _mk_doc
    await backup_h.backup_make_cb(upd_mk, ctx_fake)
    check("دکمه «ساخت بکاپ» فایل تریاکی رو میفرسته",
          any(c[0] == "doc" and c[2]["filename"].startswith("تریاکی-") for c in upd_mk.callback_query.calls),
          str(upd_mk.callback_query.calls))

    upd_up = _fake_update("bk:up", uid=7788)
    await backup_h.backup_upload_cb(upd_up, ctx_fake)
    check("آپلود بکاپ برای غریبه قفله",
          any(c[0] == "answer" and "فقط دست ادمینه" in str(c[1]) for c in upd_up.callback_query.calls),
          str(upd_up.callback_query.calls))

    upd_up2 = _fake_update("bk:up", uid=1001)
    ctx_fake.user_data = {}
    await backup_h.backup_upload_cb(upd_up2, ctx_fake)
    check("آپلود بکاپ برای ادمین حالت انتظار فایل روشن می‌کنه",
          ctx_fake.user_data.get("await_backup") is True
          and any(c[0] == "edit" and "آپلود بکاپ" in c[1] for c in upd_up2.callback_query.calls),
          str(upd_up2.callback_query.calls))

    # ═══ این دور: مدال 🎖️ | خاموشی ربات و گروه | ریست اکانت | لیدربرد تب‌دار | سپر خودی | آنتی‌اسپم ═══
    from handlers import common as common_h
    from handlers import power as power_h
    from handlers import rank as rank_h2
    from services import power as power_svc
    from telegram.ext import ApplicationHandlerStop

    # ── مدال = تجربه گرفته‌شده، با سطل روزانه و هفتگی به‌وقت ایران ──
    async with session_scope() as s:
        wk_key = team_svc.current_week_key()
        md1, _ = await users.get_or_create(s, tg(9801, "mdl1", "مدالی۱"))
        md2, _ = await users.get_or_create(s, tg(9802, "mdl2", "مدالی۲"))
        md1.medals = md1.medals_day = md1.medals_week = 0
        md2.medals = md2.medals_day = md2.medals_week = 0
        users.add_xp(md1, 30)
        users.add_xp(md2, 10)
        check("مدال دقیقاً به اندازه تجربه گرفته‌شده جمع میشه",
              md1.medals == 30 and md2.medals == 10, f"{md1.medals}")
        check("سطل روزانه و هفتگی مدال با کلید ایران پر شد",
              md1.medals_day == 30 and md1.medals_day_date == iran_today()
              and md1.medals_week == 30 and md1.medals_week_id == wk_key)
        stale_ns = SimpleNamespace(medals=99, medals_day=5, medals_day_date="2000-01-01",
                                   medals_week=7, medals_week_id="2000-W01")
        check("سطل کهنه روزانه و هفتگی صفر حساب میشه ولی کلی می‌مونه",
              users.medal_value(stale_ns, "day") == 0
              and users.medal_value(stale_ns, "week") == 0
              and users.medal_value(stale_ns, "all") == 99)
        top_all = await users.top_by_medals(s, "all", 10)
        vals = [users.medal_value(u, "all") for u in top_all]
        check("تاپ مدال کلی نزولیه", vals == sorted(vals, reverse=True), str(vals[:6]))
        from sqlalchemy import func as _f2
        n_higher = (await s.execute(select(_f2.count(User.id)).where(User.medals > 30))).scalar_one()
        rk1 = await users.medal_rank(s, md1, "all")
        check("رتبه مدال کلی درسته", rk1 == n_higher + 1, f"{rk1} vs {n_higher + 1}")
        md_stale, _ = await users.get_or_create(s, tg(9803, "mdl3", "مدالی۳"))
        md_stale.medals = 500
        md_stale.medals_day, md_stale.medals_day_date = 500, "2000-01-01"
        md_fresh, _ = await users.get_or_create(s, tg(9804, "mdl4", "مدالی۴"))
        md_fresh.medals = 3
        md_fresh.medals_day, md_fresh.medals_day_date = 3, iran_today()
        rk_stale = await users.medal_rank(s, md_stale, "day")
        rk_fresh = await users.medal_rank(s, md_fresh, "day")
        check("تو تب روزانه سطل کهنه باخته به سطل تازه",
              rk_fresh < rk_stale and users.medal_value(md_stale, "day") == 0,
              f"{rk_fresh} vs {rk_stale}")
        await s.commit()

    # ── مدال تیم: بِیس‌لاین جوین وسط بازه و جمع اعضا ──
    from models import TeamMember
    async with session_scope() as s:
        wk_key = team_svc.current_week_key()
        tlead, _ = await users.get_or_create(s, tg(9811, "tml1", "کاپیتان"))
        tlead.level = 30
        tlead.cash = config.TEAM_CREATE_COST + 1000
        tlead.medals = 100
        tlead.medals_day, tlead.medals_day_date = 40, iran_today()
        tlead.medals_week, tlead.medals_week_id = 80, wk_key
        ok, tname = await team_svc.create_team(s, tlead, "مدالیست‌ها")
        check("ساخت تیم مدالیست‌ها", ok, tname)
        team_md = await team_svc.get_team_of(s, tlead.id)
        m_lead = await team_svc.get_membership(s, tlead.id)
        check("بِیس‌لاین مدال موقع ساخت تیم ذخیره میشه",
              m_lead.join_medals == 100, str(m_lead.join_medals))
        tmm, _ = await users.get_or_create(s, tg(9812, "tmm1", "عضومدال"))
        tmm.medals = 120
        tmm.medals_day, tmm.medals_day_date = 85, iran_today()
        tmm.medals_week, tmm.medals_week_id = 75, wk_key
        m_mid = TeamMember(team_id=team_md.id, user_id=tmm.id, role="member",
                           join_medals=50, joined_at=now_utc())
        s.add(m_mid)
        await s.flush()
        check("جوین وسط بازه فقط مدال بعد اومدنش حساب میشه",
              team_svc._member_medals(m_mid, tmm, "week") == 70
              and team_svc._member_medals(m_mid, tmm, "day") == 70,
              f"{team_svc._member_medals(m_mid, tmm, 'week')}")
        check("تب کلی همه مدال‌های عضو حساب میشه",
              team_svc._member_medals(m_mid, tmm, "all") == 120)
        m_mid.joined_at = team_svc.week_start_utc_for(wk_key) - timedelta(days=1)
        check("عضو قبل از شروع هفته کل سطل هفتگیش حساب میشه",
              team_svc._member_medals(m_mid, tmm, "week") == 75)
        m_mid.joined_at = now_utc()
        sums = await team_svc.team_medal_sums(s, team_md.id)
        check("جمع مدال تیم، کلی همه مدال‌های اعضاست",
              sums["all"] == 220, str(sums))
        check("جمع مدال هفته و روز با بِیس‌لاین جوین حساب میشه",
              sums["week"] == 70 and sums["day"] == 70, str(sums))
        tops_md = await team_svc.top_teams_by_medals(s, "all", 10)
        check("لیدربرد تیم بر اساس مدال نزولیه",
              bool(tops_md) and all(tops_md[i][1] >= tops_md[i + 1][1] for i in range(len(tops_md) - 1)),
              str([(t.name, v) for t, v, _ in tops_md[:4]]))
        data_md = await team_svc.team_stats_data(s, team_md)
        check("آمار تیم جمع لول نداره و مدال داره",
              "level_sum" not in data_md and data_md["medals"]["all"] == 220, str(data_md.get("medals")))
        st_md = team_h._team_stats_text(data_md)
        check("خط مدال‌ها تو پروفایل تیمه", "🎖 مدال‌ها" in st_md and "<b>📊 آمار</b>" in st_md, st_md[:160])
        await s.commit()

    # ── لیدربرد بازیکن: تب‌دار، پیش‌فرض هفتگی، مدال‌محور ──
    upd_rk = _fake_update("menu:rank", uid=1001)
    await rank_h2.rank_cb(upd_rk, None)
    ed_rk = next((c for c in upd_rk.callback_query.calls if c[0] == "edit"), None)
    check("پیش‌فرض لیدربرد تب هفتگیه",
          ed_rk is not None and "<b>🏆 لیدربرد بازیکنا</b>" in ed_rk[1] and "🗓 هفتگی" in ed_rk[1],
          ed_rk[1][:90] if ed_rk else "-")
    check("لیدربرد قالب جدید: لول و رتبه و توضیح مدال",
          ed_rk is not None and "[Lv." in ed_rk[1] and "│" in ed_rk[1] and "🎖️" in ed_rk[1]
          and "رتبه‌ات:" in ed_rk[1] and "از" in ed_rk[1] and "(🎖️" in ed_rk[1]
          and "مدال‌ها از تجربه‌ای که می‌گیری جمع میشن" in ed_rk[1],
          ed_rk[1][-140:] if ed_rk else "-")
    mk_rk = ed_rk[2].get("reply_markup") if ed_rk else None
    row_rk = [(b.text, b.callback_data) for b in mk_rk.inline_keyboard[0]] if mk_rk else []
    check("سه دکمه ثابت روزانه/هفتگی/کلی بالای دکمه منو لیدربرد",
          row_rk == [("📅 روزانه", "rank:tab:week:day"),
                     ("🗓 هفتگی", "rank:tab:week:week"),
                     ("🌍 کلی", "rank:tab:week:all")],
          str(row_rk))
    upd_rk2 = _fake_update("rank:tab:week:day", uid=1001)
    await rank_h2.rank_tab_cb(upd_rk2, None)
    ed_rk2 = next((c for c in upd_rk2.callback_query.calls if c[0] == "edit"), None)
    check("سوئیچ به تب روزانه لیدربرد",
          ed_rk2 is not None and "<b>🏆 لیدربرد بازیکنا</b>" in ed_rk2[1] and "📅 روزانه" in ed_rk2[1])
    upd_rk3 = _fake_update("rank:tab:week:week", uid=1001)
    await rank_h2.rank_tab_cb(upd_rk3, None)
    check("زدن رو دکمه تب فعلی لیدربرد هیچ واکنشی نداره",
          not any(c[0] == "edit" for c in upd_rk3.callback_query.calls)
          and any(c[0] == "answer" for c in upd_rk3.callback_query.calls),
          str(upd_rk3.callback_query.calls))

    # ── لیدربرد تیم: تب‌دار با جمع مدال اعضا ──
    upd_tt = _fake_update("ttop:x", uid=1001)
    await team_h.top_teams_text(upd_tt, None)
    ed_tt = next((c for c in upd_tt.callback_query.calls if c[0] == "edit"), None)
    check("لیدربرد تیم پیش‌فرض هفتگیه و با مدال رتبه‌بندی میشه",
          ed_tt is not None and "<b>🏆 لیدربرد تیم‌ها</b>" in ed_tt[1] and "📅 هفتگی" in ed_tt[1] and "🎖️" in ed_tt[1],
          ed_tt[1][:110] if ed_tt else "-")
    check("قالب جدید لیدربرد تیم: [Lv.] با جداکننده و فوتر توضیح",
          ed_tt is not None and "🎖️ مجموع مدال‌های اعضای تیم" in ed_tt[1]
          and "💬 تیم [نام تیم]" in ed_tt[1] and "━━━━━━━━━━━━━━━━" in ed_tt[1],
          ed_tt[1][-160:] if ed_tt else "-")
    mk_tt = ed_tt[2].get("reply_markup") if ed_tt else None
    row_tt = [(b.text, b.callback_data) for b in mk_tt.inline_keyboard[0]] if mk_tt else []
    check("سه دکمه ثابت روزانه/هفتگی/کلی بالای دکمه منو لیدربرد تیم",
          row_tt == [("☀️ روزانه", "ttop:tab:week:day"),
                     ("📅 هفتگی", "ttop:tab:week:week"),
                     ("🌍 کلی", "ttop:tab:week:all")],
          str(row_tt))
    upd_tt2 = _fake_update("ttop:tab:week:day", uid=1001)
    await team_h.top_teams_tab_cb(upd_tt2, None)
    ed_tt2 = next((c for c in upd_tt2.callback_query.calls if c[0] == "edit"), None)
    check("سوئیچ به تب روزانه لیدربرد تیم",
          ed_tt2 is not None and "🏆 لیدربرد تیم‌ها" in ed_tt2[1] and "☀️ روزانه" in ed_tt2[1])
    upd_tt3 = _fake_update("ttop:tab:week:week", uid=1001)
    await team_h.top_teams_tab_cb(upd_tt3, None)
    check("زدن رو دکمه تب فعلی لیدربرد تیم هیچ واکنشی نداره",
          not any(c[0] == "edit" for c in upd_tt3.callback_query.calls)
          and any(c[0] == "answer" for c in upd_tt3.callback_query.calls),
          str(upd_tt3.callback_query.calls))

    # ═══ آنبوردینگ 🎯 + بازار پویا 📈 + تیم تغییر نام ✏️ + نامرئی لیدربرد 👻 + فیکس «تی برداشت» ═══
    import re as _reon

    from models import InventoryItem, SeedSale, TeamMember
    from services import onboarding as onb

    # ── زنجیره اولین‌ها: جایزه + راهنما، فقط یه بار ──
    async with session_scope() as s:
        ob, _ = await users.get_or_create(s, tg(7317, "onb", "تازه‌کار"))
        cash_ob0 = ob.cash
        t1 = await onb.first_mine(s, ob)
        check("اولین کنده‌کاری جایزه مشروطه و زنجیره قدم بعد رو داره",
              t1 is not None and ob.cash - cash_ob0 == config.FIRST_MINE_BONUS
              and "جایزه اولین کنده‌کاری" in t1 and "🎯 قدم بعد" in t1, str(t1)[:90])
        check("متن قدم بعد گرامرش درسته و «تریاکی زمین» و نقدینگی رو داره",
              "از «🌱 مزرعه من» تو منوی اصلی یا با نوشتن «تریاکی زمین» یه زمین بگیر" in t1
              and "💵 نقدینگی:" in t1, str(t1)[:200])
        check("جایزه اولین کنده‌کاری فقط یه باره",
              await onb.first_mine(s, ob) is None and ob.first_mine_at is not None)
        t2 = await onb.first_plant(s, ob)
        t3 = await onb.first_harvest(s, ob)
        check("اولین کاشت و برداشت هم جایزه و زنجیره دارن",
              t2 is not None and "جایزه اولین کاشت" in t2
              and t3 is not None and "جایزه اولین برداشت" in t3
              and ob.first_plant_at is not None and ob.first_harvest_at is not None)
        check("برداشت اول بسته چوب و آهن شروع میده (کافی برای اولین سلاح)",
              ob.wood == config.FIRST_HARVEST_WOOD and ob.iron == config.FIRST_HARVEST_IRON
              and config.FIRST_HARVEST_WOOD == 20 and config.FIRST_HARVEST_IRON == 10
              and config.FIRST_HARVEST_IRON >= config.WEAPONS["colt"]["iron"]
              and "چوب" in t3 and "آهن" in t3,
              f"wood={ob.wood} iron={ob.iron}")
        check("تکرار کاشت و برداشت جایزه نمیده",
              await onb.first_plant(s, ob) is None and await onb.first_harvest(s, ob) is None)

        # اولین سلاح، بعد دومی هیچی، زره اصلاً هیچی
        wk = list(config.WEAPONS)
        check("زره زنجیره آنبوردینگ نداره", await onb.first_weapon(s, ob, "arm") is None)
        s.add(InventoryItem(user_id=ob.id, item_key=wk[0]))
        w1 = await onb.first_weapon(s, ob, "weap")
        check("خرید اولین سلاح زنجیره نبرد رو میاره",
              w1 is not None and "آماده نبردی" in w1 and "اولین حمله" in w1, str(w1)[:80])
        s.add(InventoryItem(user_id=ob.id, item_key=wk[1]))
        check("سلاح دوم دیگه زنجیره نمیده", await onb.first_weapon(s, ob, "weap") is None)

        # ردیف‌های مأموریت و کارت منو
        rows_ob = await onb.mission_rows(s, ob)
        dones_ob = {k: d for k, _, d in rows_ob}
        check("ردیف‌های مأموریت با COUNT واقعی پر میشن",
              dones_ob["mine"] and dones_ob["plant"] and dones_ob["harvest"] and dones_ob["weapon"]
              and not dones_ob["plot"] and not dones_ob["attack"], str(rows_ob))
        card_ob = await onb.menu_card(s, ob)
        check("کارت مأموریت برای لول پایین با تیک و قدم فعلی میاد",
              card_ob is not None and "🎯 <b>مأموریت فعلی</b>" in card_ob
              and "✅" in card_ob and "🔹" in card_ob and "☐" in card_ob,
              (card_ob or "").replace("\n", " | "))
        ob.level = config.MISSION_GUIDE_MAX_LEVEL
        check("از لول راهنما به بعد کارت مأموریت نمیاد",
              await onb.menu_card(s, ob) is None)
        ob.level = 1
        await s.commit()

    # همه مرحله‌ها کامل، کارت محو میشه
    async with session_scope() as s:
        ob2, _ = await users.get_or_create(s, tg(7321, "onb2", "کامل‌شده"))
        ob2.first_mine_at = now_utc()
        ob2.first_plant_at = now_utc()
        ob2.first_harvest_at = now_utc()
        ob2.last_attack_at = now_utc()
        s.add(InventoryItem(user_id=ob2.id, item_key=list(config.WEAPONS)[0]))
        s.add(Plot(user_id=ob2.id, status="empty"))  # حالا یک زمین یعنی مرحله «اولین زمین» انجام شده
        rows_ob2 = await onb.mission_rows(s, ob2)
        check("بعد کامل شدن همه مرحله‌ها کارت مأموریت محو میشه",
              all(d for _, _, d in rows_ob2) and await onb.menu_card(s, ob2) is None, str(rows_ob2))
        await s.commit()

    # ── فیکس «تی برداشت» (آنپک خروجی harvest_all) ──
    from handlers import textcmd as textcmd_h3
    async with session_scope() as s:
        hu, _ = await users.get_or_create(s, tg(7325, "hav", "برداشتگر"))
        hu.last_harvest_at = None
        s.add(Plot(user_id=hu.id, status="empty"))
        await s.flush()
        hp = (await farming.get_user_plots(s, hu.id))[0]
        hp.status, hp.crop = "growing", "marijuana"
        hp.ready_at = now_utc() - timedelta(seconds=5)
        await world_svc._meta_set(s, "weather_key", "normal")
        await world_svc._meta_set(s, "weather_until", (now_utc() + timedelta(seconds=7200)).isoformat())
        cash_h0 = hu.cash
        await s.commit()
    upd_hv = _text_update("تی برداشت", uid=7325, uname="hav", fname="برداشتگر")
    try:
        await textcmd_h3.harvest_text(upd_hv, None)
        crashed_hv = False
    except Exception:
        crashed_hv = True
    htxt = upd_hv.message.calls[-1][1] if upd_hv.message.calls else ""
    check("«تی برداشت» بدون کرش کار می‌کنه",
          not crashed_hv and "<b>📦 برداشت</b>" in [c[1] for c in upd_hv.message.calls][0],
          htxt[:80])
    async with session_scope() as s:
        hu2 = await users.get_by_tg(s, 7325)
        check("بعد «تی برداشت» پول برداشت رسید و فروش واقعی هم ثبت شد",
              hu2.cash > cash_h0, f"{hu2.cash} vs {cash_h0}")
        mj_sales = (await s.execute(
            select(_func.coalesce(_func.sum(SeedSale.qty), 0)).where(SeedSale.seed_key == "marijuana")
        )).scalar() or 0
        check("برداشت واقعی توی عرضه بازار ثبت شد", mj_sales >= 1, str(mj_sales))
        await s.commit()

    # ── «تیم تغییر نام» ──
    async with session_scope() as s:
        ru, _ = await users.get_or_create(s, tg(7329, "ren", "رهبرنام"))
        ru.level = 12
        ru.cash = 150000
        ok_rn, _ = await team_svc.create_team(s, ru, "اسم قدیمی")
        assert ok_rn
        cash_rn0 = ru.cash  # بعد از هزینه ساخت تیم
        ok, msg = await team_svc.rename_team(s, ru, "اسم نونوار")
        check("رهبر با پول کافی اسم تیم رو عوض می‌کنه و هزینه کم میشه",
              ok and "اسم نونوار" in msg and ru.cash == cash_rn0 - config.TEAM_RENAME_COST
              and f"💸 {money(config.TEAM_RENAME_COST)} هم از جیبت کم شد" in msg, msg)
        ok, msg = await team_svc.rename_team(s, ru, "اسم نونوار")
        check("اسم فعلی دوباره رد میشه", not ok and "همینه" in msg, msg)
        ru.cash = 100
        ok, msg = await team_svc.rename_team(s, ru, "اسم فقیر")
        check("بدون پول کافی تغییر نام رد میشه", not ok and "می‌خواد" in msg, msg)
        ru.cash = 150000
        await s.commit()
    async with session_scope() as s:
        t_ren = await team_svc.get_team_by_name(s, "اسم نونوار")
        mu_r, _ = await users.get_or_create(s, tg(7333, "memr", "عضو ساده"))
        mu_r.cash = 100000
        s.add(TeamMember(team_id=t_ren.id, user_id=mu_r.id, role="member", join_medals=0))
        ok, msg = await team_svc.rename_team(s, mu_r, "اسم غریبه")
        check("عضو ساده نمی‌تونه اسم تیم رو عوض کنه", not ok and "رهبر" in msg, msg)
        ot, _ = await users.get_or_create(s, tg(7341, "oth", "تیم‌ساز"))
        ot.level = 12
        ot.cash = 100000
        ok_ot, _ = await team_svc.create_team(s, ot, "تیم مقصد")
        assert ok_ot
        ok, msg = await team_svc.rename_team(s, await users.get_by_tg(s, 7329), "تیم مقصد")
        check("اسم تکراری تیم دیگه رد میشه", not ok and "از قبل" in msg, msg)
        await s.commit()
    upd_rn = _text_update("تیم تغییر نام اسم آخرین", uid=7329, uname="ren", fname="رهبرنام")
    rn_ctx = SimpleNamespace(user_data={})
    await team_h.rename_text(upd_rn, rn_ctx)
    check("«تیم تغییر نام» اول فاکتور با دکمه تایید میاره و هنوز اعمال نمیشه",
          any("تغییر نام تیم" in c[1] and "اسم آخرین" in c[1] for c in upd_rn.message.calls)
          and rn_ctx.user_data.get("pending_team_rename") == "اسم آخرین",
          str([c[1][:70] for c in upd_rn.message.calls]))
    async with session_scope() as s:
        check("قبل زدن تایید اسم تیم عوض نشده", await team_svc.get_team_by_name(s, "اسم آخرین") is None)
        cash_rn_before = (await users.get_by_tg(s, 7329)).cash
        await s.commit()
    upd_rnc = _fake_update("tmcf:rename:7329", uid=7329)
    await team_h.team_confirm_cb(upd_rnc, rn_ctx)
    async with session_scope() as s:
        t_done = await team_svc.get_team_by_name(s, "اسم آخرین")
        ru2 = await users.get_by_tg(s, 7329)
        check("بعد تایید اسم عوض شد و هزینه از جیب رهبر کم شد",
              t_done is not None and ru2.cash == cash_rn_before - config.TEAM_RENAME_COST,
              f"{t_done} {ru2.cash}")
        check("اسم قبلی آزاد شده", await team_svc.get_team_by_name(s, "اسم نونوار") is None)
        await s.commit()
    check("پیام موفقیت تغییر نام اومد",
          any("اسم آخرین" in str(c[1]) for c in upd_rnc.callback_query.calls),
          str(upd_rnc.callback_query.calls[-2:]))
    check("معلق تغییر نام بعد اجرا پاک شد", "pending_team_rename" not in rn_ctx.user_data)
    upd_rnx = _fake_update("tmcf:rename:7329", uid=7329)
    await team_h.team_confirm_cb(upd_rnx, rn_ctx)
    check("تایید بدون معلق می‌گه منقضی شده",
          any("منقضی شده" in str(c[1]) for c in upd_rnx.callback_query.calls),
          str(upd_rnx.callback_query.calls[-2:]))

    # ── نامرئی لیدربرد 👻 (فقط ادمین) ──
    async with session_scope() as s:
        hid, _ = await users.get_or_create(s, tg(7337, "hid", "نامرئی"))
        hid.level = 20
        hid.medals = 999999
        vis0 = [u.id for u in await users.top_by_medals(s, "all", 100)]
        hid.lb_hidden = 1
        vis1 = [u.id for u in await users.top_by_medals(s, "all", 100)]
        check("کاربر نامرئی از لیست لیدربرد حذف میشه",
              hid.id in vis0 and hid.id not in vis1, f"{hid.id}")
        await s.commit()
    upd_hb = _text_update("/hideboard", uid=1001, uname="adm1", fname="ادمین یک")
    await admin_h.hideboard_cmd(upd_hb, None)
    async with session_scope() as s:
        adm_h1 = await users.get_by_tg(s, 1001)
        hb1 = adm_h1.lb_hidden
        await s.commit()
    check("/hideboard ادمین رو نامرئی می‌کنه و پیام می‌ده",
          hb1 == 1 and any("نامرئی شدی" in c[1] for c in upd_hb.message.calls),
          str([c[1][:60] for c in upd_hb.message.calls]))
    upd_hb2 = _text_update("/hideboard", uid=1001, uname="adm1", fname="ادمین یک")
    await admin_h.hideboard_cmd(upd_hb2, None)
    async with session_scope() as s:
        adm_h2 = await users.get_by_tg(s, 1001)
        hb2 = adm_h2.lb_hidden
        await s.commit()
    check("دوباره /hideboard برمی‌گردونه", hb2 == 0)
    upd_hb3 = _text_update("/hideboard", uid=7337, uname="hid", fname="نامرئی")
    await admin_h.hideboard_cmd(upd_hb3, None)
    async with session_scope() as s:
        hid3 = await users.get_by_tg(s, 7337)
        hb3 = hid3.lb_hidden
        await s.commit()
    check("/hideboard برای غیرادمین بی‌صداس و اثری نداره",
          not upd_hb3.message.calls and hb3 == 1)
    async with session_scope() as s:
        hid4 = await users.get_by_tg(s, 7337)
        hid4.lb_hidden = 0
        await s.commit()

    # ── بازار پویا: پنجره فروش ۲۴ ساعت + پاکسازی + حرکت اشباع ──
    async with session_scope() as s:
        sales0 = await world_svc._sales_24h(s)
        s.add(SeedSale(seed_key="peyote", qty=1000, at=now_utc() - timedelta(days=2, hours=1)))
        s.add(SeedSale(seed_key="peyote", qty=7, at=now_utc()))
        sales1 = await world_svc._sales_24h(s)
        check("فقط فروش‌های داخل پنجره ۲۴ ساعت تو عرضه حساب میشن",
              sales1.get("peyote", 0) - sales0.get("peyote", 0) == 7,
              f"{sales0.get('peyote')} -> {sales1.get('peyote')}")
        _pc0 = config.ACTION_LOG_PRUNE_CHANCE
        config.ACTION_LOG_PRUNE_CHANCE = 1.0
        try:
            await world_svc.record_sale(s, "gharch", 1)
        finally:
            config.ACTION_LOG_PRUNE_CHANCE = _pc0
        old_left = (await s.execute(
            select(_func.count(SeedSale.id)).where(
                SeedSale.at < now_utc() - timedelta(hours=config.MARKET_SALE_KEEP_HOURS))
        )).scalar() or 0
        check("پاکسازی خودکار ردیف‌های فروش قدیمی‌تر از نگه‌داری", old_left == 0, str(old_left))
        await s.commit()
    async with session_scope() as s:
        for kk in config.SEEDS:
            s.add(SeedSale(seed_key=kk, qty=100000, at=now_utc()))
        await world_svc._meta_set(s, "market", ",".join(f"{kk}:1.1000" for kk in config.SEEDS))
        await world_svc._meta_set(s, "market_until", "2000-01-01T00:00:00")
        rolled_sat = await world_svc.ensure_market(s)
        mults_sat, _ = await world_svc.market_mults(s)
        check("بازار اشباع‌شده قیمت‌ها رو عمیق‌تر میاره پایین (فروش سنگین = ریزش تند)",
              rolled_sat and all(0.84 <= mm < 1.10 for mm in mults_sat.values())
              and len({round(mm, 4) for mm in mults_sat.values()}) == len(mults_sat), str(mults_sat))
        await world_svc._meta_set(s, "market", ",".join(f"{kk}:0" for kk in config.SEEDS))
        await world_svc._meta_set(s, "market_until", (now_utc() + timedelta(seconds=14400)).isoformat())
        await s.commit()

    # ── قالب ردیف لیدربردها + ثبت دستورهای جدید ──
    upd_tlx = _fake_update("ttop:x", uid=1001)
    await team_h.top_teams_text(upd_tlx, None)
    ed_tlx = next((c for c in upd_tlx.callback_query.calls if c[0] == "edit"), None)
    check("ردیف لیدربرد تیم قالب «[Lv.XX] │ اسم 🎖️ عدد» رو داره",
          ed_tlx is not None and bool(_reon.search(r"🥇 \[Lv\.\d\d\] │ .+ 🎖️ [\d,]+", ed_tlx[1])),
          (ed_tlx[1] if ed_tlx else "-")[:150])
    upd_rlx = _fake_update("menu:rank", uid=1001)
    await rank_h2.rank_cb(upd_rlx, None)
    ed_rlx = next((c for c in upd_rlx.callback_query.calls if c[0] == "edit"), None)
    check("ردیف لیدربرد بازیکن قالب دوخطی با لقب بولد تو「» رو داره",
          ed_rlx is not None
          and (bool(_reon.search(r"🥇 .+? \[Lv\.\d\d\] │ .+\n<b>「.+」</b> 🎖️ [\d,]+", ed_rlx[1])) or "هنوز کسی" in ed_rlx[1]),
          (ed_rlx[1] if ed_rlx else "-")[:150])
    _init_src = open(os.path.join(_base_dir, "handlers", "__init__.py"), encoding="utf-8").read()
    check("ثبت دستورهای جدید تو رجیستری: تیم تغییر نام و /hideboard و /update",
          "team_rename" in _init_src and "hideboard" in _init_src and '"update"' in _init_src)

    # ── بازار بدون پیشوند + متن جدید + ریتم ساعتی ──
    check("بازار هر یک ساعت و هوا هر ۶ ساعت رول میشن، شانس هوای صاف بیشتر شد",
          config.MARKET_ROLL_SECONDS == 3600 and config.WEATHER_ROLL_SECONDS == 21600
          and abs(config.WEATHER_NORMAL_CHANCE - 0.70) < 1e-9)
    async with session_scope() as s:
        await world_svc._meta_set(s, "market_until", (now_utc() + timedelta(seconds=1950)).isoformat())
        await s.commit()
    upd_mk = _text_update("بازار", uid=7317, uname="onb", fname="تازه‌کار")
    await world_h.market_cmd(upd_mk, None)
    mtxt = upd_mk.message.calls[-1][1]
    check("دستور «بازار» بدون پیشوند هم کار می‌کنه",
          "<b>📈 وضعیت بازار سیاه</b>" in mtxt, mtxt[:60])
    check("متن بازار قالب جدیده: سطر حرکت ساعتی و فوتر تایمر دقیقه و ثانیه",
          "قیمت‌ها هر یک ساعت یه حرکت کوچیک دارن" in mtxt and "⏳ حرکت بعدی بازار" in mtxt
          and bool(_reon.search(r"32 دقیقه و \d+ ثانیه دیگه", mtxt)),
          mtxt.replace("\n", " | ")[-170:])
    check("ردیف محصول چهارخطیه و افسانه‌ای‌ها هم با اسم ایموجی‌دار خودشون میان",
          "🌿 ماری‌جوانا" in mtxt and "💰 قیمت فروش الان:" in mtxt and "📦 قیمت پایه:" in mtxt
          and "بذر جهنم 🔥" in mtxt, mtxt[:150])

    # ── فاصله بین منابع و بذرها تو متن انبار و مخفیگاه ──
    upd_sh = _text_update("تریاکی انبار", uid=7317, uname="onb", fname="تازه‌کار")
    await world_h.shelter_cmd(upd_sh, None)
    sh_txt = upd_sh.message.calls[-1][1]
    check("تو متن انبار بین چوب و آهن و بذرها فاصله‌ست که توهم نرن",
          bool(_reon.search(r"⛏️ آهن[^\n]*\n\n🌿", sh_txt)),
          sh_txt.replace("\n", " | ")[:150])

    # ── متن خرید «خریداری شد» ──
    async with session_scope() as s:
        bu, _ = await users.get_or_create(s, tg(7345, "buyfix", "خریدار"))
        bu.cash = 1000
        ok_by, msg_by = await shop_svc.purchase(s, bu, "seed", "marijuana")
        check("متن پاپ‌آپ خرید «خریداری شد» شد نه مالت",
              ok_by and "خریداری شد" in msg_by and "مالت" not in msg_by, msg_by)
        await s.commit()

    # ── قدم «اولین زمین» با خرید همون یک زمین تیک می‌خوره ──
    async with session_scope() as s:
        pm, _ = await users.get_or_create(s, tg(7349, "plotmis", "زمین‌دار"))
        r0 = {k: d for k, _, d in await onb.mission_rows(s, pm)}
        s.add(Plot(user_id=pm.id, status="empty"))
        await s.flush()
        r1 = {k: d for k, _, d in await onb.mission_rows(s, pm)}
        check("قدم مأموریت «اولین زمین» با یک زمین انجام میشه",
              not r0["plot"] and r1["plot"], f"{r0['plot']} ← {r1['plot']}")
        await s.commit()

    # ── شدت پویای آب‌وهوا: درصد هر رول تو بازه و روی متن‌ها و اکسسورها میشینه ──
    async with session_scope() as s:
        await world_svc._meta_set(s, "weather_until", "2000-01-01T00:00:00")
        old_nc2 = config.WEATHER_NORMAL_CHANCE
        config.WEATHER_NORMAL_CHANCE = 0.0  # موقتاً همیشه ویژه رول بشه
        try:
            k_sp, rec_sp = await world_svc.ensure_weather(s)
        finally:
            config.WEATHER_NORMAL_CHANCE = old_nc2
        pct_sp = int(await world_svc._meta(s, "weather_pct"))
        check("هوای ویژه درصد رول داره و تو بازه کف تا سقفه",
              rec_sp is not None and k_sp != "normal" and pct_sp == rec_sp["pct"]
              and config.WEATHER_MIN_PCT <= pct_sp <= config.WEATHER_MAX_PCT, f"{k_sp}/{pct_sp}")
        ann_sp = world_svc.weather_announce_text(k_sp, pct_sp)
        check("اعلان هوا درصد همین رول و مهلت ۶ ساعته رو می‌گه",
              f"{pct_sp}%" in ann_sp and "تا 6 ساعت آینده" in ann_sp,
              ann_sp.replace("\n", " | ")[-100:])
        st_key, st_pct, _st_left = await world_svc.weather_state(s)
        check("weather_state درصد رول فعلی رو برمی‌گردونه",
              st_key == k_sp and st_pct == pct_sp, f"{st_key}/{st_pct}")
        await s.commit()
    check("اکسسورهای هوا درصد رول رو اعمال می‌کنن",
          world_svc.weather_grow_speed("rain", 45) == 1.45
          and abs(world_svc.weather_grow_speed("frost", 20) - 1 / 1.2) < 1e-9
          and world_svc.weather_sell_mult("fest", 50) == 1.50
          and world_svc.weather_combat_mods("fog", 15) == (0.0, 0.15)
          and world_svc.weather_q5_bonus("moon", 12) == 0.12)
    check("بدون درصد رول، پایه کانفیگ میاد (سازگاری با هوای قدیمی)",
          world_svc.weather_grow_speed("rain") == 1.30
          and world_svc.weather_combat_mods("storm") == (-0.10, 0.0))

    # ── /update ادمین: ریلود کانفیگ + رول فوری بازار + بازخوانی ظرفیت + ریست کش، بدون دست زدن به هوا ──
    upd_una = _text_update("/update", uid=7333, uname="memr", fname="عضو ساده")
    await admin_h.update_cmd(upd_una, None)
    check("/update برای غیرادمین کاملاً بی‌صداس", len(upd_una.message.calls) == 0)

    class _UpBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, *a, **k):
            self.sent.append(a)

    async with session_scope() as s:
        await world_svc._meta_set(s, "market_until", (now_utc() + timedelta(seconds=3000)).isoformat())
        # هوا رو پین می‌کنیم: وقتی /update بزنیم نباید هیچ‌کدوم از اینا عوض بشه
        pin_wu = (now_utc() + timedelta(seconds=7200)).isoformat()
        await world_svc._meta_set(s, "weather_key", "heat")
        await world_svc._meta_set(s, "weather_until", pin_wu)
        await world_svc._meta_set(s, "weather_pct", "20")
        await s.commit()

    # ریلود کانفیگ رو منکی‌پچ می‌کنیم که هم صداش اصالت سنجی کنیم هم فایل واقعی دست‌نخورده بمونه
    import importlib as _ilib
    _orig_reload = _ilib.reload
    _reload_seen = []
    _ilib.reload = lambda m: _reload_seen.append(m)
    try:
        upd_up = _text_update("/update", uid=1001, uname="adm1", fname="ادمین یک")
        await admin_h.update_cmd(upd_up, SimpleNamespace(bot=_UpBot()))
    finally:
        _ilib.reload = _orig_reload
    check("/update کانفیگ رو واقعاً به‌روز لود می‌کنه (ظرفیتای تغییرکرده سریع اعمال میشن)",
          _reload_seen and _reload_seen[0] is config)
    utxt = upd_up.message.calls[-1][1]
    check("خروجی /update گزارش کامل به‌روزرسانیه",
          "🔄 وضعیت بازی به‌روز شد" in utxt and "⚙️ کانفیگ دوباره لود شد" in utxt
          and "📈 بازار" in utxt and "👥 ظرفیت" in utxt and "🧹 کش" in utxt
          and "🌦 آب‌وهوا دست‌نخورده موند" in utxt and "سرریز ظرفیت نیس" in utxt
          and "⭐ سطح" in utxt and "بازنشانی شد" in utxt and "🐕" in utxt,
          utxt.replace("\n", " | ")[:320])
    from datetime import datetime as _dtu
    async with session_scope() as s:
        left_mu = (_dtu.fromisoformat(await world_svc._meta(s, "market_until")) - now_utc()).total_seconds()
        check("بازار فورس رول شد و تایمر یک ساعته ریست شد",
              abs(left_mu - 3600) < 30, str(left_mu))
        check("/update به آب و هوا دست نمی‌زنه (کی و درصد و تا کِی، همه مثل قبل)",
              (await world_svc._meta(s, "weather_key")) == "heat"
              and (await world_svc._meta(s, "weather_pct")) == "20"
              and (await world_svc._meta(s, "weather_until")) == pin_wu,
              f"{await world_svc._meta(s, 'weather_key')} {await world_svc._meta(s, 'weather_until')}")
        # برگشت هوا به حالت عادی با تا ختم‌شدنش سر مرز بعدی، دیترمینیستیک برای ادامه سوییت
        await world_svc._meta_set(s, "weather_key", "normal")
        await world_svc._meta_set(s, "weather_until", world_svc._next_weather_boundary(now_utc()).isoformat())
        await world_svc._meta_set(s, "weather_pct", "0")
        await s.commit()
    check("کش عضویت بعد /update خالیه و مرور بعدی تازه چک میشه",
          len(fj_svc._MEMBER_CACHE) == 0)

    # ── ⭐ مهاجرت لول تیم به منحنی سخت‌تر: لول ۱۰ قدیمی مستقیم میشه لول ۵ جدید، یه‌بارمصرف ──
    async with session_scope() as s:
        mg, _ = await users.get_or_create(s, tg(7358, "mgtm", "رهبرمهاجر"))
        mg.level = 12
        mg.cash = 200000
        ok_mg, _ = await team_svc.create_team(s, mg, "مهاجرها")
        assert ok_mg
        t_mg = await team_svc.get_team_of(s, mg.id)
        t_mg.level, t_mg.xp = 10, 100  # سناریوی تیم قدیمی: لول ۱۰ با منحنی قبلی
        await team_svc.meta_set(s, "team_lvl_v2", "")  # فلگ خالی که مهاجرت مستقیم تست بشه
        await s.commit()
        ob_o, oe_o = config.TEAM_XP_CURVE_MIGRATION_FROM
        tot_mg = 100 + sum(int(ob_o * (lv ** oe_o)) for lv in range(1, 10))
        lv_mg, rem_mg = 1, tot_mg
        while lv_mg < config.TEAM_MAX_LEVEL and rem_mg >= team_svc.team_xp_need(lv_mg):
            rem_mg -= team_svc.team_xp_need(lv_mg)
            lv_mg += 1
        n_mig = await team_svc.migrate_team_levels(s)
        check("مهاجرت لول ۱۰ قدیمی دقیق روی منحنی جدید بازنشانی میشه (میشه لول ۵)",
              n_mig >= 1 and t_mg.level == lv_mg and t_mg.xp == rem_mg and lv_mg == 5,
              f"lvl={t_mg.level} xp={t_mg.xp} انتظار {lv_mg}/{rem_mg}")
        check("فلگ مهاجرت بعد از اجرا ست شده",
              (await team_svc.meta_get(s, "team_lvl_v2")) == "1")
        n_again = await team_svc.migrate_team_levels(s)
        check("اجرای دوباره مهاجرت هیچ کاری نمی‌کنه (یدمپوتنت)",
              n_again == 0 and t_mg.level == lv_mg and t_mg.xp == rem_mg,
              f"{n_again} lvl={t_mg.level}")
        await s.commit()

    # ═══ این دور: addxpgroup | اسم تیم «تریاک» | نامرئی کامل | جایزه اولین زمین | تبریک پایان مأموریت | ریست مثل روز اول ═══
    check("ظرفیت‌های جدول تیم دقیقاً جدول کاربره (۱۰،۱۲،۱۴،۱۶،۱۸،۲۱،۲۳،۲۵،۲۷،۳۰)",
          config.TEAM_CAP_TABLE == [10, 12, 14, 16, 18, 21, 23, 25, 27, 30])
    check("جایزه اولین خرید زمین 200 تی‌پوینته", config.FIRST_PLOT_BONUS == 200)

    # ── ✨ /addxpgroup: دادن مستقیم xp به تیم (با اسم چندکلمه‌ای یا آیدی) ──
    async with session_scope() as s:
        gx, _ = await users.get_or_create(s, tg(7351, "gxown", "رهبرایکس"))
        gx.level = 12
        gx.cash = 100000
        ok_gx, _ = await team_svc.create_team(s, gx, "تیم ایکس گروپ")
        assert ok_gx
        t_gx = await team_svc.get_team_of(s, gx.id)
        notes_svc = await team_svc.give_team_xp(s, t_gx, 30)
        check("give_team_xp سرویسی دقیقاً همون مقدار رو میده (بدون ضریب سهم اعضا)",
              t_gx.xp == 30 and not notes_svc, str(t_gx.xp))
        await s.commit()
    upd_g0 = _text_update("/addxpgroup", uid=7333, uname="memr", fname="عضو ساده")
    await admin_h.addxpgroup_cmd(upd_g0, SimpleNamespace(args=["تیم", "ایکس", "گروپ", "50"]))
    check("/addxpgroup برای غیرادمین کاملاً بی‌صداس", len(upd_g0.message.calls) == 0)
    upd_g1 = _text_update("/addxpgroup", uid=1001, uname="adm1", fname="ادمین یک")
    await admin_h.addxpgroup_cmd(upd_g1, SimpleNamespace(args=["تیم", "ایکس", "گروپ"]))
    check("/addxpgroup بدون مقدار فرم درست رو میگه",
          "فرم درست" in upd_g1.message.calls[-1][1], upd_g1.message.calls[-1][1][:70])
    async with session_scope() as s:
        t_gx = await team_svc.get_team_by_name(s, "تیم ایکس گروپ")
        xp_b4 = t_gx.xp
        await s.commit()
    upd_g2 = _text_update("/addxpgroup", uid=1001, uname="adm1", fname="ادمین یک")
    await admin_h.addxpgroup_cmd(upd_g2, SimpleNamespace(args=["تیم", "ایکس", "گروپ", "50"]))
    async with session_scope() as s:
        t_gx = await team_svc.get_team_by_name(s, "تیم ایکس گروپ")
        check("/addxpgroup با اسم چندکلمه‌ای xp دقیق داد",
              t_gx.xp == xp_b4 + 50, f"{xp_b4}->{t_gx.xp}")
        await s.commit()
    g2_txt = upd_g2.message.calls[-1][1]
    check("خروجی /addxpgroup لول و ظرفیت تیم رو گزارش می‌ده",
          "تیم «تیم ایکس گروپ»" in g2_txt and "لول تیم الان" in g2_txt and "ظرفیت اعضا" in g2_txt,
          g2_txt.replace("\n", " | ")[:160])
    async with session_scope() as s:
        t_gx = await team_svc.get_team_by_name(s, "تیم ایکس گروپ")
        tid_gx = t_gx.id
        need_now = team_svc.team_xp_need(t_gx.level) - t_gx.xp
        await s.commit()
    upd_g3 = _text_update("/addxpgroup", uid=1001, uname="adm1", fname="ادمین یک")
    await admin_h.addxpgroup_cmd(upd_g3, SimpleNamespace(args=[str(tid_gx), str(need_now)]))
    async with session_scope() as s:
        t_gx = await team_svc.get_team_by_name(s, "تیم ایکس گروپ")
        lv_gx = t_gx.level
        await s.commit()
    check("/addxpgroup با آیدی عددی تیم کار می‌کنه و لول‌آپ دقیق می‌خوره",
          lv_gx == 2 and len(upd_g3.message.calls) >= 2, f"lvl={lv_gx} calls={len(upd_g3.message.calls)}")
    check("نوت لول‌آپ تیم پیام جدا اومد و ظرفیت جدید رو می‌گه",
          any("لول 2 شد" in c[1] and "ظرفیت اعضا شد 12 نفر" in c[1] for c in upd_g3.message.calls),
          str([c[1][:60] for c in upd_g3.message.calls]))
    upd_g4 = _text_update("/addxpgroup", uid=1001, uname="adm1", fname="ادمین یک")
    await admin_h.addxpgroup_cmd(upd_g4, SimpleNamespace(args=["همچین", "تیمی", "نیس", "100"]))
    check("/addxpgroup تیم ناشناخته رو گزارش می‌ده",
          "پیدا نشد" in upd_g4.message.calls[-1][1])
    _init2_src = open(os.path.join(_base_dir, "handlers", "__init__.py"), encoding="utf-8").read()
    check("ثبت /addxpgroup تو رجیستری هندلرها", 'CommandHandler("addxpgroup"' in _init2_src)

    # ── اسم تیم «تریاک» و «تریاکی» دیگه به دستور اشتباه گرفته نمیشه ──
    async with session_scope() as s:
        tn, _ = await users.get_or_create(s, tg(7352, "tnam", "نام‌تیم"))
        tn.level = 12
        tn.cash = 200000
        tn.pending_action = "teamname"
        await s.commit()
    upd_tn = _text_update("تریاک", uid=7352, uname="tnam", fname="نام‌تیم")
    try:
        await pending_h.capture(upd_tn, None)
    except Exception:
        pass
    async with session_scope() as s:
        tn2 = await users.get_by_tg(s, 7352)
        pend_tn = (tn2.pending_action, tn2.pending_value)
        await s.commit()
    check("«تریاک» به عنوان اسم تیم قبول میشه و فاکتور ساخت میاد",
          upd_tn.message.calls and "ساخت تیم «تریاک»" in upd_tn.message.calls[-1][1]
          and pend_tn == ("teamcf", "تریاک"),
          f"{pend_tn} | {str(upd_tn.message.calls[-1][1])[:80]}")
    upd_tb = _text_update("تریاکی بازار", uid=7352, uname="tnam", fname="نام‌تیم")
    await pending_h.capture(upd_tb, None)
    check("«تریاکی بازار» هنوز دستور اصلیه و ورودی معلق نمیشه",
          not upd_tb.message.calls, str(upd_tb.message.calls))
    async with session_scope() as s:
        tn3 = await users.get_by_tg(s, 7352)
        tn3.pending_action = None
        tn3.pending_value = None
        await s.commit()

    # ── 👻 نامرئی کامل: هدف هیچ حمله‌ای نیس، تیمش هم تو لیدربرد و کارت ماسکه ──
    from services import pvattack as pvattack_svc
    async with session_scope() as s:
        hi, _ = await users.get_or_create(s, tg(7353, "ghst", "روح‌پنهان"))
        hi.level = 15
        hi.cash = 200000
        hi.lb_hidden = 1
        ok_h, _ = await team_svc.create_team(s, hi, "روح‌های شب")
        assert ok_h
        t_roh = await team_svc.get_team_of(s, hi.id)
        atkr, _ = await users.get_or_create(s, tg(7354, "hugh", "مهاجم‌عادی"))
        atkr.level = 15
        atkr.energy = config.MAX_ENERGY
        atkr.last_attack_at = None
        atkr.pv_attack_at = None
        await s.flush()
        hid_db = hi.id
        picked = await pvattack_svc.pick_random_target(s, atkr)
        check("هدف شانسی هرگز کاربر نامرئی رو نمیاره",
              picked is None or picked.telegram_id != 7353,
              str(picked.telegram_id if picked else None))
        tops_b = await team_svc.top_teams(s, 50)
        check("تیم رهبر نامرئی تو لیدربرد تیم نمیاد",
              all(t.id != t_roh.id for t, _ in tops_b), str([t.name for t, _ in tops_b]))
        data_h = await team_svc.team_stats_data(s, t_roh)
        check("رهبر نامرئی تو کارت تیم با 👻 ماسک میشه",
              data_h["owner_name"] == "👻 نامرئی", data_h["owner_name"])
        await s.commit()

    # حمله گروهی به نامرئی مثل آدم ناشناخته جواب می‌شنوه (محض احتیاط اسمش هم لو نره)
    async with session_scope() as s:
        hi1 = await users.get_by_tg(s, 7353)
        hp_b4_hide = hi1.hp
        await s.commit()
    gh_tg = SimpleNamespace(id=7353, username="ghst", first_name="روح‌پنهان", is_bot=False)
    upd_gh = _tgroup("حمله", 7354, "hugh", "مهاجم‌عادی", reply_user=gh_tg)
    await battle_h3.attack_cmd(upd_gh, None)
    check("حمله گروهی به نامرئی با متن «پیدا نکردم» برگشت می‌خوره",
          upd_gh.message.calls and upd_gh.message.calls[-1][1] == battle_h3.NOT_FOUND_TEXT,
          str(upd_gh.message.calls[-1][1])[:80] if upd_gh.message.calls else "-")
    async with session_scope() as s:
        hi2 = await users.get_by_tg(s, 7353)
        check("به نامرئی واقعاً ضربه‌ای نخورد (HP و وضعیت دست‌نخورده)",
              hi2.hp == hp_b4_hide and hi2.dead_until is None, str(hi2.hp))
        await s.commit()

    # حمله پی‌وی به نامرئی هم الرت «هدف گم شد» می‌ده
    upd_pv = _fake_update(f"patt:hit:{hid_db}", uid=7354)
    await attack_h2.target_hit_cb(upd_pv, SimpleNamespace(bot=_UpBot()))
    check("حمله پی‌وی به نامرئی الرت «هدف گم شد» می‌ده",
          any(c[0] == "answer" and any("هدف گم شد" in str(x) for x in c[1])
              for c in upd_pv.callback_query.calls),
          str(upd_pv.callback_query.calls[:2]))
    async with session_scope() as s:
        atkr2 = await users.get_by_tg(s, 7354)
        check("حمله ردشده روی نامرئی کولدان پی‌وی نمی‌سوزونه",
              atkr2.pv_attack_at is None, str(atkr2.pv_attack_at))
        await s.commit()

    # ── 🏡 جایزه اولین خرید زمین برگشت (فقط یه بار، زنجیره بذر رو میاره) ──
    async with session_scope() as s:
        fp, _ = await users.get_or_create(s, tg(7355, "fplot", "زمین‌اولی"))
        c0_fp = fp.cash
        t_fp = await onb.first_plot(s, fp)
        check("اولین خرید زمین جایزه 200 تی‌پوینتی و زنجیره بذر رو داره",
              t_fp is not None and "جایزه اولین زمین" in t_fp
              and "بذر" in t_fp and fp.cash - c0_fp == 200
              and fp.first_plot_at is not None,
              f"+{fp.cash - c0_fp} | {str(t_fp)[:80]}")
        check("متن قدم بعد بذر گِرامرش درسته (فروشگاه → مزرعه، بدون دولا)",
              "از «🛒 فروشگاه» یه بذر بخر و تو «🌱 مزرعه من» اولین محصولت رو بکار" in t_fp,
              str(t_fp)[:200])
        check("جایزه اولین زمین فقط یه باره",
              await onb.first_plot(s, fp) is None)
        await s.commit()

    # ── 🎉 تبریک پایان مأموریت با قالب دقیق کاربر، فقط یه بار ──
    from models import InventoryItem as _InvCg
    async with session_scope() as s:
        cg, _ = await users.get_or_create(s, tg(7356, "grat", "تبریکی"))
        cg.first_mine_at = now_utc()
        cg.first_plant_at = now_utc()
        cg.first_harvest_at = now_utc()
        cg.last_attack_at = now_utc()
        s.add(_InvCg(user_id=cg.id, item_key="colt"))
        await s.flush()
        check("تا یه قدم از مأموریت مونده (اولین زمین)، تبریک پایانی نمیاد",
              await onb.maybe_congrats(s, cg) is None)
        await onb.first_plot(s, cg)  # تیک اولین زمین + جایزه
        s.add(Plot(user_id=cg.id, status="empty"))
        await s.flush()
        cg_txt = await onb.maybe_congrats(s, cg)
        check("پیام تبریک پایان مأموریت دقیقاً قالب کاربره",
              cg_txt is not None
              and "🎉 تبریک" in cg_txt
              and "آموزش اولیه رو با موفقیت تموم کردی" in cg_txt
              and "حالا با تمام بخش‌های اصلی بازی آشنا شدی؛ وقتشه ربات رو به گروه خودت اضافه کنی و همراه دوستات رقابت، معامله و مبارزه رو شروع کنی" in cg_txt
              and "🔥 بازی واقعی تازه از اینجا شروع میشه" in cg_txt,
              str(cg_txt)[:110])
        check("تبریک پایان مأموریت فقط یه بار گفته میشه و دی‌بی علامت خورد",
              await onb.maybe_congrats(s, cg) is None and cg.onb_done_at is not None)
        await s.commit()

    # ── 🧨 /clearacc: کوئست‌ها و آنبوردینگ پاک، استارت دوباره مثل سلامای اول کاری ──
    async with session_scope() as s:
        wc, _ = await users.get_or_create(s, tg(7357, "wcl", "ریستی"))
        wc.level = 7
        wc.cash = 88888
        wc.first_mine_at = wc.first_plant_at = wc.first_harvest_at = now_utc()
        wc.first_plot_at = now_utc()
        wc.onb_done_at = now_utc()
        wc.last_mine_at = now_utc()
        wc.last_attack_at = now_utc()
        wc.dq_date = "2026-01-01"
        wc.dq_data = '[{"kind": "mine", "target": 20}]'
        await s.commit()
    upd_cw = _fake_update("cacc:ok:7357", uid=1001)
    await admin_h.clearacc_cb(upd_cw, SimpleNamespace(bot=_UpBot()))
    async with session_scope() as s:
        wc2 = await users.get_by_tg(s, 7357)
        check("ریست اکانت دیتای آنبوردینگ رو پاک می‌کنه (first_* و تبریک)",
              wc2.first_mine_at is None and wc2.first_plant_at is None
              and wc2.first_harvest_at is None and wc2.first_plot_at is None
              and wc2.onb_done_at is None,
              f"{wc2.first_mine_at} {wc2.first_plot_at} {wc2.onb_done_at}")
        check("کوئست‌های روزانه فعلی بعد ریست پاک شدن (مثل روز اول)",
              wc2.dq_date is None and wc2.dq_data is None, f"{wc2.dq_date}/{wc2.dq_data}")
        await s.commit()
    from handlers import start as start_h
    upd_sw = _text_update("/start", uid=7357, uname="wcl", fname="ریستی")
    await start_h.start_cmd(upd_sw, None)
    sw_txt = upd_sw.message.calls[0][1] if upd_sw.message.calls else ""
    check("بعد ریست، استارت دقیقاً همون خوش‌آمد روز اول کاری رو می‌گه",
          "به بازی تریاکی خوش اومدی" in sw_txt and "کنده کاری" in sw_txt
          and "برای شروع اولین قدم خیلی ساده‌ست" in sw_txt
          and "بزن و بکن تا اولین تی‌پوینت" in sw_txt and "راهنماییت می‌کنم" in sw_txt, sw_txt[:160])
    async with session_scope() as s:
        wc3 = await users.get_by_tg(s, 7357)
        wc3.level = 6
        wc3.last_mine_at = now_utc()
        await s.commit()
    upd_sw2 = _text_update("/start", uid=7357, uname="wcl", fname="ریستی")
    await start_h.start_cmd(upd_sw2, None)
    sw2_txt = upd_sw2.message.calls[0][1] if upd_sw2.message.calls else ""
    check("بازیکن فعال دیگه خوش‌آمد تازه‌کار نمی‌گیره (برگشتی)",
          "به بازی تریاکی خوش اومدی" not in sw2_txt and "خوب شد که دوباره اومدی" in sw2_txt,
          sw2_txt[:80])

    # ── دکمه آپدیت مزرعه + حذف رفرش پروفایل ──
    from keyboards import keyboards as kb3
    async with session_scope() as s:
        fu = await users.get_by_tg(s, 1001)
        fplots = await farming.get_user_plots(s, fu.id)
        fkb = kb3.farm_kb(fu, fplots, economy.plot_price(len(fplots)), 0)
        farm_flat = [(b.text, b.callback_data, b.style) for r in fkb.inline_keyboard for b in r]
        check("دکمه آپدیت مزرعه هست",
              any(t == "🔄 آپدیت" and c == "farm:rf" for t, c, _ in farm_flat), str(farm_flat[-2:]))
        pkb = kb3.profile_kb()
        prof_flat = [(b.text, b.callback_data) for r in pkb.inline_keyboard for b in r]
        check("رفرش پروفایل حذف شده",
              not any("رفرش" in t or "آپدیت" in t for t, _ in prof_flat), str(prof_flat))
        await s.commit()

    # ── تراتل داخلی و ضدتکرار دستورهای متنی ──
    check("تراتل کلیک اول آزاده", common_h.throttle("tkey1", 555000, 2) == 0)
    check("تراتل کلیک دوم بلاکه", common_h.throttle("tkey1", 555000, 2) > 0)
    check("تراتل برای کاربر دیگه آزاده", common_h.throttle("tkey1", 555001, 2) == 0)

    ran_sp = {"n": 0}

    @common_h.text_dedup
    async def _dummy_cmd(u, c):
        ran_sp["n"] += 1

    check("کولدان ضدتکرار دستورها نیم ثانیه‌ست", config.TEXT_DEDUP_SECONDS == 0.5)
    upd_sp1 = _text_update("اسپم تستی", uid=555010)
    await _dummy_cmd(upd_sp1, None)
    upd_sp2 = _text_update("اسپم تستی", uid=555010)
    stopped_sp = False
    try:
        await _dummy_cmd(upd_sp2, None)
    except ApplicationHandlerStop:
        stopped_sp = True
    check("دستور متنی تکراری زیر نیم ثانیه اجرا نمیشه", ran_sp["n"] == 1 and stopped_sp)
    check("تکرار دستور هیچ پیامی نمی‌گیره، کاملا سایلنته",
          not upd_sp2.message.calls, str(upd_sp2.message.calls))
    upd_sp3 = _text_update("اسپم تستی", uid=555010)
    try:
        await _dummy_cmd(upd_sp3, None)
    except ApplicationHandlerStop:
        pass
    check("تکرارهای پشت‌هم هم سایلنت میشن", not upd_sp3.message.calls)
    upd_sp4 = _text_update("یه دستور دیگه", uid=555010)
    await _dummy_cmd(upd_sp4, None)
    check("متن فرق‌کرده محدودیت نداره", ran_sp["n"] == 2)

    # ── نوت‌های لول‌آپ پیام جدا ──
    upd_an = _text_update("حمله", uid=555020)
    await common_h.announce_notes(upd_an, ["🎉 لول 2 شدی", "🔓 شاپ برات باز شد"])
    n_replies = len([c for c in upd_an.message.calls if c[0] == "reply"])
    check("هر نوت لول‌آپ یه پیام جداست", n_replies == 2, str(upd_an.message.calls))
    await common_h.announce_notes(upd_an, None)
    check("نوت خالی پیامی نمی‌فرسته",
          len([c for c in upd_an.message.calls if c[0] == "reply"]) == 2)

    # ── دکمه آپدیت مزرعه با تراتل ──
    from handlers import farm as farm_h2
    upd_rf1 = _fake_update("farm:rf", uid=555030)
    await farm_h2.farm_refresh_cb(upd_rf1, None)
    check("کلیک اول آپدیت مزرعه رندر میشه",
          any(c[0] == "edit" for c in upd_rf1.callback_query.calls), str(upd_rf1.callback_query.calls))
    upd_rf2 = _fake_update("farm:rf", uid=555030)
    await farm_h2.farm_refresh_cb(upd_rf2, None)
    check("کلیک دوم آپدیت مزرعه «آروم‌تر» می‌گیره",
          any(c[0] == "answer" and any("آروم‌تر" in str(x) for x in c[1])
              for c in upd_rf2.callback_query.calls),
          str(upd_rf2.callback_query.calls))
    check("و رندر دوباره انجام نمیشه",
          not any(c[0] == "edit" for c in upd_rf2.callback_query.calls))

    # ── خاموشی کلی و گروهی ربات (/botdown /botup /botoff /boton) ──
    def _pow_update(text, uid, chat_id=5511, chat_type="group", cb=False):
        msg = _Msg(text=text, calls=[], chat_id=chat_id, message_id=44)
        q = None
        if cb:
            q = _Q(data=text, message=SimpleNamespace(photo=None), calls=[])
        return SimpleNamespace(
            message=None if cb else msg,
            effective_message=q.message if cb else msg,
            callback_query=q,
            effective_user=SimpleNamespace(id=uid, username="pwr", first_name="پاور"),
            effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        )

    def _gcm(status):
        async def _f(chat_id, user_id):
            return SimpleNamespace(status=status)
        return _f

    member_ctx = SimpleNamespace(bot=SimpleNamespace(get_chat_member=_gcm("member")))
    gadmin_ctx = SimpleNamespace(bot=SimpleNamespace(get_chat_member=_gcm("administrator")))

    upd_bd0 = _pow_update("/botdown", 7788)
    await power_h.botdown_cmd(upd_bd0, None)
    check("/botdown برای غیرادمین سکوت محضه", not upd_bd0.message.calls)

    upd_bf_pv = _pow_update("/botoff", 7788, chat_id=7788, chat_type="private")
    await power_h.botoff_cmd(upd_bf_pv, None)
    check("/botoff تو پی‌وی راهنما میده",
          "ویژه گروه" in upd_bf_pv.message.calls[-1][1], upd_bf_pv.message.calls[-1][1][:80])

    upd_bf_m = _pow_update("/botoff", 7788)
    await power_h.botoff_cmd(upd_bf_m, member_ctx)
    check("ممبر نمی‌تونه ربات رو تو گروه خاموش کنه",
          "فقط توسط ادمین" in upd_bf_m.message.calls[-1][1], upd_bf_m.message.calls[-1][1][:60])

    upd_bf_a = _pow_update("/botoff", 7788)
    await power_h.botoff_cmd(upd_bf_a, gadmin_ctx)
    check("ادمین گروه ربات رو خاموش می‌کنه",
          "خاموش شد" in upd_bf_a.message.calls[-1][1], upd_bf_a.message.calls[-1][1][:80])
    async with session_scope() as s:
        check("خاموشی گروه تو دی‌بی ثبت شد", await power_svc.group_off(s, 5511))
        offs = await power_svc.off_group_ids(s)
        check("لیست گروه خاموش درسته", 5511 in offs)
        await s.commit()

    upd_gs = _pow_update("کنده کاری", 7788, chat_type="supergroup")
    stopped_g = False
    try:
        await power_h.power_gate(upd_gs, None)
    except ApplicationHandlerStop:
        stopped_g = True
    check("تو گروه خاموش هیچ واکنشی نیس",
          stopped_g and not upd_gs.message.calls, str(upd_gs.message.calls))

    upd_bo = _pow_update("/boton", 7788, chat_type="supergroup")
    try:
        await power_h.power_gate(upd_bo, None)
        passed_bo = True
    except ApplicationHandlerStop:
        passed_bo = False
    check("/boton از گیت رد میشه تا هندلرش برسه", passed_bo)

    upd_on = _pow_update("/boton", 7788)
    await power_h.boton_cmd(upd_on, gadmin_ctx)
    check("ادمین گروه ربات رو روشن می‌کنه",
          "روشن شد" in upd_on.message.calls[-1][1], upd_on.message.calls[-1][1][:80])
    async with session_scope() as s:
        check("گروه دوباره روشنه", not await power_svc.group_off(s, 5511))
        await s.commit()

    upd_bd = _pow_update("/botdown", 1001)
    await power_h.botdown_cmd(upd_bd, None)
    check("/botdown تایید میده", "تعمیر" in upd_bd.message.calls[-1][1], upd_bd.message.calls[-1][1][:60])
    async with session_scope() as s:
        check("ربات رو حالت تعمیره", await power_svc.is_down(s))
        await s.commit()

    power_h._MAINT_LAST.clear()
    upd_m1 = _pow_update("کنده کاری", 7788, chat_id=6611, chat_type="supergroup")
    stopped_m = False
    try:
        await power_h.power_gate(upd_m1, None)
    except ApplicationHandlerStop:
        stopped_m = True
    check("گیت تعمیر دستور کاربر عادی رو قطع می‌کنه", stopped_m)
    check("پیام «در دست توسعه و تعمیره» جواب داده میشه",
          any(config.MAINTENANCE_TEXT in str(c[1]) for c in upd_m1.message.calls),
          str(upd_m1.message.calls))
    n_calls1 = len(upd_m1.message.calls)
    try:
        await power_h.power_gate(upd_m1, None)
    except ApplicationHandlerStop:
        pass
    check("اسپم تو چند ثانیه فقط یه بار مارک تعمیر می‌گیره",
          len(upd_m1.message.calls) == n_calls1)

    upd_ma = _pow_update("کنده کاری", 1001, chat_id=6611, chat_type="supergroup")
    try:
        await power_h.power_gate(upd_ma, None)
        passed_ma = True
    except ApplicationHandlerStop:
        passed_ma = False
    check("ادمین ربات از گیت تعمیر رد میشه", passed_ma and not upd_ma.message.calls)

    upd_cbm = _pow_update("menu:home", 7788, chat_id=6611, cb=True)
    stopped_cb = False
    try:
        await power_h.power_gate(upd_cbm, None)
    except ApplicationHandlerStop:
        stopped_cb = True
    check("دکمه‌ها تو مد تعمیر الرت می‌گیرن (نسخه ساده بدون تگ)",
          stopped_cb and any(c[0] == "answer" and any(power_h.MAINTENANCE_PLAIN in str(x) for x in c[1])
                             for c in upd_cbm.callback_query.calls),
          str(upd_cbm.callback_query.calls))
    check("متن تعمیر بولده و نسخه ساده‌اش تگ نداره",
          config.MAINTENANCE_TEXT.startswith("<b>") and "<b>" not in power_h.MAINTENANCE_PLAIN
          and "🔧 ربات تریاکی در دست توسعه و تعمیره" in power_h.MAINTENANCE_PLAIN)

    upd_bu = _pow_update("/botup", 1001)
    await power_h.botup_cmd(upd_bu, None)
    check("/botup ربات رو برمی‌گردونه", "برگشت رو هوا" in upd_bu.message.calls[-1][1])
    async with session_scope() as s:
        check("ربات دیگه پایین نیس", not await power_svc.is_down(s))
        await s.commit()

    # ── /menu حذف شده ──
    from handlers import start as start_h3
    check("هندلر /menu دیگه وجود نداره", not hasattr(start_h3, "menu_cmd"))
    _adm_txt = admin_h._panel_text(SimpleNamespace(cash=0, level=1, xp=0))
    check("پنل ادمین دستورای جدید رو لیست کرده",
          "/clearacc" in _adm_txt and "/botdown" in _adm_txt and "/botoff" in _adm_txt)

    # ── /clearacc، ریست کامل اکانت با تاییدیه ──
    async with session_scope() as s:
        tgt, _ = await users.get_or_create(s, tg(7741, "victimx", "قربانی‌ریست"))
        tgt.level = 9
        tgt.cash = 99999
        tgt.wood = 50
        tgt.medals = 77
        tgt.wins = 4
        tgt.hp = battle_svc.max_hp(tgt.level)  # HP واقعی یه بازیکن فعال، باگ ensure_hp فقط None رو ریست می‌کرد
        s.add(Plot(user_id=tgt.id))
        await s.commit()

    upd_ca0 = _text_update("/clearacc", uid=1001)
    await admin_h.clearacc_cmd(upd_ca0, SimpleNamespace(args=[]))
    check("clearacc بدون آرگومان فرم درست رو میگه",
          "فرم درست" in upd_ca0.message.calls[-1][1], upd_ca0.message.calls[-1][1][:70])
    upd_ca1 = _text_update("/clearacc همچینکسی‌نی", uid=1001)
    await admin_h.clearacc_cmd(upd_ca1, SimpleNamespace(args=["همچینکسی‌نی"]))
    check("clearacc آدمی که نیس رو پیدا نمی‌کنه",
          "پیدا نشد" in upd_ca1.message.calls[-1][1])
    upd_ca2 = _text_update("/clearacc 7741", uid=1001)
    await admin_h.clearacc_cmd(upd_ca2, SimpleNamespace(args=["7741"]))
    ca2_txt, ca2_kw = upd_ca2.message.calls[-1][1], upd_ca2.message.calls[-1][2]
    check("clearacc پیش‌نمایش ریست رو با تاییدیه میاره",
          "ریست اکانت" in ca2_txt and "7741" in ca2_txt, ca2_txt[:120])
    ca_cbs = [b.callback_data for r in ca2_kw["reply_markup"].inline_keyboard for b in r]
    check("دکمه‌های تایید و لغو ریست", "cacc:ok:7741" in ca_cbs and "cacc:no:7741" in ca_cbs, str(ca_cbs))

    upd_can = _fake_update("cacc:no:7741", uid=1001)
    await admin_h.clearacc_cb(upd_can, None)
    async with session_scope() as s:
        tgt2 = await users.get_by_tg(s, 7741)
        check("لغو ریست، اکانت دست‌نخورده میمونه", tgt2.level == 9 and tgt2.cash == 99999)
        await s.commit()

    sent_dm = []

    class _CcBot:
        async def send_message(self, *a, **k):
            sent_dm.append(a)

    upd_cok = _fake_update("cacc:ok:7741", uid=1001)
    await admin_h.clearacc_cb(upd_cok, SimpleNamespace(bot=_CcBot()))
    async with session_scope() as s:
        w = await users.get_by_tg(s, 7741)
        check("ریست اکانت به حالت روز اول برمی‌گردونه",
              w.level == 1 and w.cash == config.START_CASH and w.medals == 0
              and w.wood == 0 and w.wins == 0 and w.bank_balance == 0,
              f"lvl {w.level} cash {w.cash} medals {w.medals}")
        wplots = await farming.get_user_plots(s, w.id)
        check("بعد ریست هم زمین هدیه نمیشه، مثل روز اول خودش رایگان می‌خره", len(wplots) == 0, str(len(wplots)))
        check("سلامت بعد ریست به مکس روز اول 200 برمی‌گرده (نه HP قدیمی)",
              w.hp == battle_svc.max_hp(1) == 200, str(w.hp))
        await s.commit()
    ed_cok = next((c for c in upd_cok.callback_query.calls if c[0] == "edit"), None)
    check("پیام موفقیت ریست", ed_cok is not None and "ریست شد" in ed_cok[1])
    check("به خود کاربر هم خبر رفت", bool(sent_dm) and sent_dm[0][0] == 7741, str(sent_dm))

    async with session_scope() as s:
        wown, _ = await users.get_or_create(s, tg(7745, "wown", "صاحبتیم"))
        wown.level = 30
        wown.cash = config.TEAM_CREATE_COST + 500
        ok, _ = await team_svc.create_team(s, wown, "موقتی‌ها")
        check("تیم موقتی ساخته شد", ok)
        await users.wipe_account(s, wown)
        check("ریست رهبر، تیمش منحل میشه",
              await team_svc.get_team_by_name(s, "موقتی‌ها") is None)
        check("بعد ریست عضو تیمی نیس", await team_svc.get_team_of(s, wown.id) is None)
        await s.commit()

    # ── سپر محافظتی خودی: حمله اول تاییدیه می‌خواد ──
    async with session_scope() as s:
        atk, _ = await users.get_or_create(s, tg(9861, "atkr", "مهاجم"))
        vic, _ = await users.get_or_create(s, tg(9862, "vicm", "قربان"))
        atk.level = vic.level = 12
        atk.energy = config.MAX_ENERGY
        atk.last_attack_at = None
        atk.shield_until = now_utc() + timedelta(hours=2)
        vic.shield_until = None
        vic.hp = battle_svc.max_hp(vic.level)
        vic.dead_until = None
        atk_db, vic_db = atk.id, vic.id
        await s.commit()

    atk_dm = []

    class _AtkBot:
        async def send_message(self, *a, **k):
            atk_dm.append(a)

    upd_sh = _fake_update(f"patt:hit:{vic_db}", uid=9861)
    await attack_h2.target_hit_cb(upd_sh, SimpleNamespace(bot=_AtkBot()))
    ed_sh = next((c for c in upd_sh.callback_query.calls if c[0] == "edit"), None)
    check("حمله با سپر خودی فعال تاییدیه می‌خواد",
          ed_sh is not None and "سپر محافظتی داری" in ed_sh[1] and "سپر میشکنه" in ed_sh[1],
          ed_sh[1][:120] if ed_sh else "-")
    mk_sh = ed_sh[2].get("reply_markup") if ed_sh else None
    sh_cbs = [b.callback_data for r in mk_sh.inline_keyboard for b in r] if mk_sh else []
    check("دکمه تایید شکستن سپر خودی",
          f"patt:shcf:{vic_db}" in sh_cbs and "patt:back" in sh_cbs, str(sh_cbs))
    async with session_scope() as s:
        atk2 = await users.get_by_tg(s, 9861)
        check("بدون تایید نه سپر شکست نه حمله خورد",
              atk2.shield_until is not None and atk2.pv_attack_at is None)
        await s.commit()

    upd_sh2 = _fake_update(f"patt:shcf:{vic_db}", uid=9861)
    await attack_h2.ownshield_hit_cb(upd_sh2, SimpleNamespace(bot=_AtkBot()))
    async with session_scope() as s:
        atk3 = await users.get_by_tg(s, 9861)
        vic3 = await users.get_by_tg(s, 9862)
        check("با تایید، سپر خودی شکست و حمله انجام شد",
              atk3.shield_until is None and atk3.pv_attack_at is not None)
        check("قربانی سپر 6 ساعته گرفت", vic3.shield_until is not None)
        await s.commit()
    ed_sh2 = next((c for c in upd_sh2.callback_query.calls if c[0] == "edit"), None)
    check("نتیجه حمله بعد تایید نمایش داده شد",
          ed_sh2 is not None and ("⚔️ بردی" in ed_sh2[1] or "تونست دفاع کنه، باختی" in ed_sh2[1]),
          ed_sh2[1][:110] if ed_sh2 else "-")
    if ed_sh2 is not None:
        _res_btns = [b.callback_data for row in ed_sh2[2]["reply_markup"].inline_keyboard for b in row]
        check("زیر متن نتیجه به‌جای هدف شانسی دکمه بازگشت اومده",
              _res_btns == ["patt:back", "menu:home"], str(_res_btns))
    check("دی‌ام قربانی هدر و سپر جدید رو داره",
          bool(atk_dm) and "🚨 بهت حمله شد" in str(atk_dm[-1][1])
          and "از حملات در امانی" in str(atk_dm[-1][1]), str(atk_dm[-1][1][:120] if atk_dm else "-"))

    # ── متن باخت مهاجم و دفاع قربانی (فرمول جدید) ──
    vt_lose = attack_h2._victim_text("تستی", {"won": False, "penalty": 23, "steal": 0, "victim_xp": 3})
    check("متن دی‌ام دفاع موفق قربانی",
          "<b>🚨 بهت حمله شد</b>" in vt_lose and "🛡 حریف «تستی» بهت حمله کرد ولی دفاع کردی" in vt_lose
          and "💵 23 تی‌پوینت جریمه‌ش رسید دستت" in vt_lose and "✨ 3 تجربه گرفتی" in vt_lose
          and "🛡 تا 6 ساعت از حملات در امانی" in vt_lose,
          vt_lose.replace("\n", " | ")[:170])

    # ── بانک ۵ لولی: جدول ظرفیت و قیمت و گیت سطح + قفل کیبورد ──
    bk_lock = kb3.bank_kb(SimpleNamespace(bank_level=1, level=1))
    bk_flat = [(b.text, b.callback_data, b.style) for r in bk_lock.inline_keyboard for b in r]
    check("دکمه قفل ارتقای بانک با سطح لازم، قرمزه",
          any("🔒 ارتقای بانک | لول 2 | سطح 4" in t and c == "noop:banklock" and st == "danger"
              for t, c, st in bk_flat), str(bk_flat))
    bk_open = kb3.bank_kb(SimpleNamespace(bank_level=1, level=4))
    bk_flat2 = [(b.text, b.callback_data) for r in bk_open.inline_keyboard for b in r]
    check("با سطح کافی دکمه ارتقای بانک فعاله",
          any(c == "bank:up" for _, c in bk_flat2), str(bk_flat2))
    bk_max = kb3.bank_kb(SimpleNamespace(bank_level=5, level=20))
    check("بانک لول مکس دکمه مکس داره",
          any("مکس" in b.text for r in bk_max.inline_keyboard for b in r))

    # ── متن شرکت: موجودی بالا + وضعیت هر ساختمان ──
    from services import company as company_svc
    cu = SimpleNamespace(wood=10, iron=20, lumber_level=0, ironmill_level=0)
    ctx_company = company_svc.company_text(cu)
    check("موجودی چوب و آهن بالای صفحه شرکته",
          "🪵 چوب 10 | ⛏️ آهن 20" in ctx_company.splitlines()[2], ctx_company[:150])
    check("قالب ساخته‌نشده هر ساختمان",
          ctx_company.count("وضعیت: ساخته نشده") == 2 and "هزینه ساخت:" in ctx_company
          and "تی‌پوینت" in ctx_company and " TP" not in ctx_company)
    cu2 = SimpleNamespace(wood=10, iron=20, lumber_level=2, ironmill_level=0,
                          lumber_stock=0, ironmill_stock=0)
    ctx_company2 = company_svc.company_text(cu2)
    per_hour = config.FACTORIES["lumber"]["per_tick"] * 2 * (3600 // config.FACTORY_TICK_SECONDS)
    check("قالب ساخته‌شده: وضعیت در حال تولید 🟢 + انبار + سرعت ساعتی",
          "وضعیت چوب‌بری: در حال تولید 🟢 (لول 2)" in ctx_company2
          and f"📦 انبار کارخونه: 0/{fa_num(comp_svc.factory_stock_cap('lumber', 2))}" in ctx_company2
          and f"⚙️ سرعت تولید: {fa_num(per_hour)} چوب در ساعت" in ctx_company2,
          ctx_company2.replace("\n", " | ")[:240])
    cu_full = SimpleNamespace(wood=10, iron=20, lumber_level=1, ironmill_level=1,
                              lumber_stock=comp_svc.factory_stock_cap("lumber", 1),
                              ironmill_stock=comp_svc.factory_stock_cap("ironmill", 1))
    ctx_full = company_svc.company_text(cu_full)
    check("انبار پر یعنی متوقف شده 🔴 با راهنمای برداشت",
          ctx_full.count("متوقف شده 🔴") == 2 and "انبارش پره، اول برداشت بزن" in ctx_full
          and f"📦 انبار کارخونه: {fa_num(comp_svc.factory_stock_cap('ironmill', 1))}/{fa_num(comp_svc.factory_stock_cap('ironmill', 1))}" in ctx_full,
          ctx_full.replace("\n", " | ")[:240])
    check("ظرفیت انبار کارخونه دقیق ۱۲ ساعت تولیده",
          comp_svc.factory_stock_cap("lumber", 1) == 288 and comp_svc.factory_stock_cap("ironmill", 1) == 360
          and comp_svc.factory_stock_cap("ironmill", 2) == 720,
          f"{comp_svc.factory_stock_cap('lumber', 1)}/{comp_svc.factory_stock_cap('ironmill', 1)}")

    # ── متن ابزار (ادغام‌شده تو صفحه اصلی کنده‌کاری) با تی‌پوینت کامل ──
    tt = mine_h.mine_home_text(SimpleNamespace(axe_level=1, pick_level=1, wood=0, iron=0))
    check("متن کنده‌کاری وضعیت ابزار رو هم داره و تی‌پوینت کامله نه TP",
          "⬆️ هزینه ارتقا:" in tt and "🪓 تبر لول 1" in tt and "تی‌پوینت" in tt and " TP" not in tt,
          tt.replace("\n", " | ")[:200])

    # ── نام یکدست «انبار» همه‌جا (مخفیگاه ری‌نیم شد) ──
    world_h2 = None
    from handlers import world as world_h2
    async with session_scope() as s:
        sht = await world_h2._shelter_text(s, SimpleNamespace(shelter_level=0, wood=0, iron=0, level=1, id=999999))
    check("تیتر صفحه انبار «انبار» ـه",
          sht.startswith("<b>🏚 انبار</b>") and "مخفیگاه" not in sht and "پلیس" not in sht, sht[:40])
    check("نوار پرشوندگی بذرها هم توی انبار هست مثل چوب و آهن",
          all(x in sht for x in ["🌿 ماری‌جوانا ▱", "🍄 قارچ ▱", "🌵 پیوت ▱", "🍃 کراتوم ▱", "🌺 خشخاش سیاه ▱", "☕ تریاک ▱", "⚪ کوکائین ▱"])
          and sht.count("▰") + sht.count("▱") >= 90,
          sht.replace("\n", " | ")[:220])
    check("بذر افسانه‌ای توی لیست انبار نمیاد",
          "جهنم" not in sht and "ابلیس" not in sht and "جهش‌یافته" not in sht)
    mm_flat = [b.text for r in kb3.main_menu_kb().inline_keyboard for b in r]
    check("دکمه منوی اصلی «انبار» با ایموجی جدیده", "🎒 انبار" in mm_flat, str(mm_flat))
    check("چیدمان دقیق منوی جدید (ترتیب ردیف‌ها)",
          [[b.text for b in r] for r in kb3.main_menu_kb().inline_keyboard] ==
          [["🌾 مزرعه من"],
           ["🏪 فروشگاه", "⚔️ حمله"],
           ["🎒 انبار", "⛏️ کنده‌کاری"],
           ["🏦 بانک"],
           ["⭐️ مهارت", "🛡 تجهیزات"],
           ["🐕 سگ‌ها", "🎯 مأموریت", "🏢 شرکت"],
           ["🏆 رتبه‌بندی", "📖 راهنما", "🚩 تیم من"],
           ["➕ افزودن به گروه"]],
          str([[b.text for b in r] for r in kb3.main_menu_kb().inline_keyboard]))
    check("بخش هلپ انبار اسم جدید رو داره",
          start_h3.HELP_SECTIONS["shelter"].startswith("<b>🏚 انبار</b>"))
    check("هلپ نبرد سلامت گفته نه HP",
          "سلامت" in start_h3.HELP_SECTIONS["battle"] and "HP" not in start_h3.HELP_SECTIONS["battle"])

    # ═══ این دور: دکمه‌های شرکت بدون قیمت | مخفیگاه تو هلپ | لول‌آپ اورجینال جدا | ایموجی کامندها ═══

    # ── دکمه ساخت/ارتقای شرکت بدون قیمت، قیمت تو صفحه تاییده ──
    ckb_new = kb3.company_kb(SimpleNamespace(lumber_level=0, ironmill_level=0))
    ckb_flat = [(b.text, b.callback_data) for r in ckb_new.inline_keyboard for b in r]
    check("دکمه ساخت چوب‌بری بدون قیمت با قالب جدید",
          ("🔨ساخت چوب‌بری 🪵", "comp:build:lumber") in ckb_flat, str(ckb_flat))
    check("دکمه ساخت کارخانه آهن بدون قیمت با قالب جدید",
          ("🔨ساخت کارخانه آهن 🏭", "comp:build:ironmill") in ckb_flat, str(ckb_flat))
    check("قیمت توی دکمه‌های شرکت نیس",
          not any("TP" in t or "تی‌پوینت" in t for t, _ in ckb_flat), str(ckb_flat))
    ckb_up = kb3.company_kb(SimpleNamespace(lumber_level=2, ironmill_level=0, lumber_stock=120, ironmill_stock=0))
    ckb_flat2 = [(b.text, b.callback_data) for r in ckb_up.inline_keyboard for b in r]
    check("دکمه ارتقای چوب‌بری هم بدون قیمته",
          ("⬆️ ارتقای چوب‌بری 🪵", "comp:upg:lumber") in ckb_flat2, str(ckb_flat2))
    check("انبار نیمه‌پر دکمه 📥 برداشت با مقدار داره",
          ("📥 برداشت 🪵 (120)", "comp:col:lumber") in ckb_flat2
          and not any("comp:col:ironmill" == d for _, d in ckb_flat2), str(ckb_flat2))
    upd_cc = _fake_update("comp:build:lumber", uid=1001)
    from handlers import company as company_h
    await company_h.company_action_confirm(upd_cc, None)
    ed_cc = next((c for c in upd_cc.callback_query.calls if c[0] == "edit"), None)
    check("صفحه تایید ساخت، هزینه رو نشون میده",
          ed_cc is not None and "💸 تی‌پوینت" in ed_cc[1] and "🪵 چوب" in ed_cc[1],
          ed_cc[1][:120] if ed_cc else "-")

    # ── متن لول‌آپ اورجینال: 🎉 تبریک، لول‌آپ شدی (5←6) ──
    async with session_scope() as s:
        lu, _ = await users.get_or_create(s, tg(9901, "lvup", "لول‌آپی"))
        lu.level, lu.xp = 1, 0
        notes_lu = users.add_xp(lu, 60)
        check("قالب اورجینال لول‌آپ",
              notes_lu and notes_lu[0].startswith("🎉 تبریک، لول‌آپ شدی (1←2)"),
              notes_lu[0][:60] if notes_lu else "-")
        check("خط جایزه و انرژی از متن لول‌آپ حذف شده (جایزه‌ها همچنان واریز میشن)",
              notes_lu and "جایزه" not in notes_lu[0] and "شارژ" not in notes_lu[0]
              and lu.cash > 0)
        await s.commit()
    async with session_scope() as s:
        lu2, _ = await users.get_or_create(s, tg(9902, "lvup2", "لول‌آپی۲"))
        lu2.level, lu2.xp = 4, 0
        notes_lu2 = users.add_xp(lu2, 500)
        check("لول‌آپ با آنلاک، لیست «آیتم های جدید باز شدن» رو داره",
              notes_lu2 and any("🔓 آیتم های جدید باز شدن" in n for n in notes_lu2),
              str([n[:50] for n in notes_lu2]))
        await s.commit()

    # ── بذرهای افسانه‌ای دیگه تو متن لول‌آپ نمیان و کاشتشون برای همه آزاده ──
    check("لول بازشدنی جهنم و ابلیس روی ۱ـه (کاشت برای همه آزاد، فقط جستجو/کاروان بهشون میرسه)",
          config.SEEDS["jahannam"]["min_level"] == 1 and config.SEEDS["eblis"]["min_level"] == 1)
    async with session_scope() as s:
        lv12, _ = await users.get_or_create(s, tg(7360, "lv12", "دوازدهی"))
        lv12.level, lv12.xp = 11, 0
        n12 = users.add_xp(lv12, economy.xp_need(11))
        _j12 = "\n".join(n12 or [])
        check("تو متن لول 12 اسم بذر جهنم نیس ولی سلاح و زره همون لول هستن",
              n12 and "جهنم" not in _j12 and "گاتلینگ" in _j12 and "زره تیتانیومی" in _j12,
              _j12[:120])
        lv18, _ = await users.get_or_create(s, tg(7361, "lv18", "هجدهی"))
        lv18.level, lv18.xp = 17, 0
        n18 = users.add_xp(lv18, economy.xp_need(17))
        _j18 = "\n".join(n18 or [])
        check("تو متن لول 18 اسم بذر ابلیس نیس",
              n18 and "ابلیس" not in _j18, _j18[:120])
        await s.commit()

    # ── لول‌های بدون آنلاک (مثل 9 و 18) خط دلگرمی می‌گیرن که متن خالی به نظر نرسه ──
    async with session_scope() as s:
        lv9, _ = await users.get_or_create(s, tg(7362, "lv9", "نُهی"))
        lv9.level, lv9.xp = 8, 0
        n9 = users.add_xp(lv9, economy.xp_need(8))
        _j9 = "\n".join(n9 or [])
        check("لول 9 هیچ آیتمی باز نمی‌کنه (درسته) ولی به جای سکوت خط دلگرمی میاد",
              n9 and n9[0].startswith("🎉 تبریک، لول‌آپ شدی (8←9)")
              and "🔓 آیتم های جدید باز شدن" not in _j9 and "💪" in _j9, _j9[:150])
        await s.commit()
    check("لول 18 سلاح ویژه Vampire باز می‌کنه (دیگه بذر ابلیس حساب نمیشه)",
          "🩸 Vampire" in _j18 and "🔓 آیتم های جدید باز شدن" in _j18, _j18[:150])

    # ── پنل ادمین: ایموجی مخصوص هر کامند و botoff/boton ته لیست ──
    pan = admin_h._panel_text(SimpleNamespace(cash=0, level=1, xp=0))
    check("ایموجی مخصوص هر کامند مدیریتی",
          all(e in pan for e in ("👤", "💵", "✨", "💸", "🧨", "🔧", "💾", "🔌")), pan[:400])
    check("botoff/boton ته لیست دستورهای مدیریتی‌ان",
          pan.find("/botoff") > pan.find("/backup") and pan.rfind("🔌") > pan.rfind("💾"))

    # ── پیام ممبر برای /botoff با کلمه گروه ──
    upd_bf_m2 = _pow_update("/botoff", 7788)
    await power_h.botoff_cmd(upd_bf_m2, member_ctx)
    check("متن رد ممبر «ادمین گروه» میگه",
          "❌ این دستور فقط توسط ادمین گروه قابل استفاده است" == upd_bf_m2.message.calls[-1][1],
          upd_bf_m2.message.calls[-1][1][:80])
    upd_bn_m = _pow_update("/boton", 7788)
    await power_h.boton_cmd(upd_bn_m, member_ctx)
    check("متن رد ممبر boton هم همینه",
          "❌ این دستور فقط توسط ادمین گروه قابل استفاده است" == upd_bn_m.message.calls[-1][1])

    # ── اعلان کوئست با جایزه تجربه: لول‌آپ پیام جداست ──
    upd_dqn = _text_update("x", uid=555040, uname="dqn", fname="کوئستی‌لول")
    q_xp = [{"kind": "mine", "target": 20, "progress": 20, "done": True,
             "reward": {"type": "xp", "amount": 60},
             "notes": ["🎉 تبریک، لول‌آپ شدی (1←2)"]}]
    from handlers import dquests as dquests_h2
    await dquests_h2.announce_completed(upd_dqn, "کوئستی‌لول", q_xp, 1)
    dq_texts = [c[1] for c in upd_dqn.message.calls if c[0] == "reply"]
    check("اعلان کوئست قاطی تبریک لول‌آپ نمیشه",
          dq_texts and "کوئست «20 بار کنده‌کاری»" in dq_texts[0] and "لول‌آپ شدی" not in dq_texts[0],
          str(dq_texts))
    check("تبریک لول‌آپ کوئست پیام جدا اومد",
          any(t.startswith("🎉 تبریک، لول‌آپ شدی") for t in dq_texts[1:]), str(dq_texts))

    # ═══ این دور: خط وضعیت زیر تیتر شاپ | ایموجی دوبل نشه | درصد آرتیفکت و سگ | بذر با نوار | لیدربرد ۳ دکمه‌ای | ریست ۱۲ شب ═══
    from utils import bar

    # ── خط «🌟 سطح | 💵 موجودی» زیر سرتیتر همه بخش‌های شاپ ──
    sh_ns = SimpleNamespace(cash=57879, level=20, wood=10, iron=20, shelter_level=0)
    async with session_scope() as s:
        sh_real, _ = await users.get_or_create(s, tg(9701, "shopstat", "شاپستات"))
        sh_real.cash, sh_real.level = 57879, 20
        seed_txt_st = await shop_h2._section_text(s, sh_real, "seed")
        food_txt_st = await shop_h2._section_text(s, sh_real, "food")
        res_txt_st = await shop_h2._section_text(s, sh_real, "res")
        wup_txt_st = await shop_h2._section_text(s, sh_real, "wup")
        await s.commit()
    st_pages = {
        "خانه سلاح": shop_h2._weap_home_text(sh_ns),
        "سلاح گرم": shop_h2._wsec_text(sh_ns, "hot"),
        "سلاح سرد": shop_h2._wsec_text(sh_ns, "cold"),
        "زره": shop_h2._arm_text(sh_ns),
        "سگ": shop_h2._dog_text(sh_ns),
        "آرتیفکت": shop_h2._arti_text(sh_ns),
        "منابع": res_txt_st,
        "بذر": seed_txt_st,
        "غذا": food_txt_st,
        "ارتقای سلاح": wup_txt_st,
    }
    bad_st = [n for n, t in st_pages.items()
              if not (t.splitlines()[1].startswith("🌟 سطح:")
                      and "💵 موجودی:" in t.splitlines()[1] and "TP" in t.splitlines()[1])]
    check("خط «سطح + موجودی» زیر سرتیتر هر ۱۰ صفحه شاپ هست", not bad_st, str(bad_st))
    check("قالب خط وضعیت «🌟 سطح: 20 | 💵 موجودی: 57,879 TP»",
          st_pages["خانه سلاح"].splitlines()[1] == f"🌟 سطح: 20 | 💵 موجودی: {fa_num(57879)} TP",
          st_pages["خانه سلاح"].splitlines()[1])
    shome = shop_h2._sections_text(47495, 5)
    check("صفحه اولیه فروشگاه هم خط وضعیت یکدست زیر تیتر داره",
          shome.splitlines()[0] == "<b>🛒 فروشگاه</b>"
          and shome.splitlines()[1] == "🌟 سطح: 5 | 💵 موجودی: 47,495 TP"
          and "🔫 سلاح‌ها، زره‌ها و ⬆️ ارتقاشون" in shome
          and "🎒 چوب و آهن" in shome
          and "🌱 بذر برای کشت توی زمینتون" in shome
          and "🐕 سگ‌ها و 🍖 غذاشون" in shome
          and "🧿 آرتیفکت‌های آخر بازی که بعد از لول 10 باز میشن" in shome
          and "نقدینگی" not in shome, shome.replace("\n", " | ")[:160])

    # ── ایموجی سلاح دوبل نمیشه، اسم تفنگ خودش 🔫 داره ──
    hot_txt = st_pages["سلاح گرم"]
    hot_heads = [l for l in hot_txt.splitlines() if "کلت کمری" in l]
    check("هد سلاح گرم بدون پیشوند دوبل 🔫",
          hot_heads and hot_heads[0] == "کلت کمری 🔫" and "🔫 کلت کمری 🔫" not in hot_txt,
          str(hot_heads))
    cold_txt = st_pages["سلاح سرد"]
    check("سلاح سرد بی‌ایموجی پیشوند بخش رو می‌گیره",
          any(l == "🔪 چاقو" for l in cold_txt.splitlines()), cold_txt[:160])
    gu_txt = shop_h2._gear_up_text("weap", {"colt": 2}, sh_ns)
    check("صفحه ارتقا هم اسم تفنگ رو دوبل نمی‌کنه",
          "کلت کمری 🔫 | لول 2" in gu_txt and "🔫 کلت کمری 🔫" not in gu_txt,
          gu_txt.replace("\n", " | ")[:200])
    upd_fc = _fake_update("shop:buy:weap:colt", uid=9701)
    await shop_h2.buy_confirm(upd_fc, None)
    fc_txt = next((c[1] for c in upd_fc.callback_query.calls if c[0] == "edit"), "")
    check("فاکتور خرید هم هد دوبل نداره",
          "کلت کمری 🔫" in fc_txt and "🔫 کلت کمری 🔫" not in fc_txt, fc_txt.replace("\n", " | ")[:160])

    # ── درصد اثر آرتیفکت جلوی متنش ──
    atxt2 = st_pages["آرتیفکت"]
    check("درصد اثر هر آرتیفکت جلوی لاینشه",
          all(x in atxt2 for x in ["(+10%)", "(+15%)", "(×1.5)"]) and atxt2.count("(+") >= 4,
          atxt2.replace("\n", " | ")[:260])

    # ── صفحه انبار: نوار بذرها با موجودی واقعی ──
    async with session_scope() as s:
        stu, _ = await users.get_or_create(s, tg(9702, "seedbar", "بذربار"))
        stu.shelter_level = 1
        await farming.add_seed_stock(s, stu.id, "marijuana", 7)
        await farming.add_seed_stock(s, stu.id, "jahannam", 3)
        await s.commit()
    upd_sb = _text_update("تریاکی انبار", uid=9702)
    await world_h2.shelter_cmd(upd_sb, None)
    sb_txt = upd_sb.message.calls[-1][1]
    cap_sb = config.SHELTER_SEED_CAP_BASE + config.SHELTER_SEED_CAP_PER_LEVEL * 1
    check("نوار بذر با موجودی واقعی انبار پر میشه",
          f"🌿 ماری‌جوانا {bar(7, cap_sb)} 7/{fa_num(cap_sb)}" in sb_txt, sb_txt.replace("\n", " | ")[:260])
    check("بذر جهنم (افسانه‌ای) تو انبار نشون داده نمیشه",
          "جهنم" not in sb_txt)
    check("تیتر انبار و صفحه ارتقاش یکدست «انبار» ـه",
          sb_txt.startswith("<b>🏚 انبار</b>") and "مخفیگاه" not in sb_txt)
    upd_shu = _fake_update("shelter:up", uid=9702)
    await world_h2.shelter_up_confirm(upd_shu, None)
    shu_txt = next((c[1] for c in upd_shu.callback_query.calls if c[0] == "edit"), "")
    check("تیتر تایید ارتقا هم «انبار» ـه",
          "<b>🏚 ارتقای انبار و مخفیگاه" not in shu_txt and "<b>🏚 ارتقای انبار" in shu_txt, shu_txt[:60])

    # ── ریست آمار دقیقا ۱۲ شب به وقت ایرانه ──
    from utils import iran_day_start_utc, iran_week_key, iran_week_start_utc, now_iran  # now_utc از بالای فایل ایمپورت شده
    ds = iran_day_start_utc()
    check("ریست روزانه ۱۲ شب به وقت ایرانه (۲۰:۳۰ UTC)",
          (ds.hour, ds.minute, ds.second) == (20, 30, 0) and ds <= now_utc() < ds + timedelta(hours=24),
          str(ds))
    check("تاریخ امروز هم از ساعت ایران حساب میشه",
          iran_today() == now_iran().date().isoformat())
    ds_ir = ds + timedelta(hours=3, minutes=30)
    check("شروع روز ایران دقیقا ۰۰:۰۰ به وقت تهرانه",
          (ds_ir.hour, ds_ir.minute) == (0, 0) and ds_ir.date().isoformat() == iran_today(), str(ds_ir))
    ws = iran_week_start_utc()
    check("ریست هفتگی دوشنبه ۱۲ شب به وقت ایرانه (یکشنبه ۲۰:۳۰ UTC)",
          (ws.hour, ws.minute, ws.second) == (20, 30, 0) and ws.weekday() == 6
          and ws <= now_utc() < ws + timedelta(days=7), str(ws))
    check("کلید هفته به‌وقت ایرانه",
          iran_week_key() == f"{now_iran().isocalendar()[0]}-W{now_iran().isocalendar()[1]:02d}",
          iran_week_key())
    mdz = SimpleNamespace(medals=99, medals_day=12, medals_day_date=iran_today(),
                          medals_week=34, medals_week_id=iran_week_key())
    check("مدال روز و هفته قبل از ریست همون مقداره",
          users.medal_value(mdz, "day") == 12 and users.medal_value(mdz, "week") == 34
          and users.medal_value(mdz, "all") == 99)

    # ═══ این دور: بازطراحی عضویت اجباری، کش ستینگ + کش عضویت + recheck رویدادمحور + پاکسازی با مهلت ═══

    check("کانفیگ‌های جدید گیت (کش/ری‌چک/مهلت پاکسازی/اسکن)",
          config.FORCE_JOIN_CACHE_SECONDS == 30 and config.FORCE_JOIN_RECHECK_SECONDS == 900
          and config.FORCE_JOIN_WIPE_AFTER_HOURS == 48 and config.FORCE_JOIN_WIPE_SCAN_SECONDS == 3600)
    from database import _NEW_COLUMNS as _nc
    fj_cols = {c for c, _ in _nc["users"]}
    check("سه ستون fj روی الگوی خودکار _NEW_COLUMNS‌ان (مایگریشن دستی لازم نیس)",
          {"fj_member_status", "fj_checked_at", "fj_left_at"} <= fj_cols, str(sorted(fj_cols)[-5:]))
    check("تشخیص کانال با آیدی عددی و یوزرنیم",
          fj_svc.same_channel("-100123456789", -100123456789, None)
          and not fj_svc.same_channel("-100123456789", -100999999999, None)
          and fj_svc.same_channel("@TeriakyTest", 5, "teriakytest")
          and not fj_svc.same_channel("@teriakytest", 5, None))

    # ── کش ستینگ: ۵ بار پشت‌سر فقط ۱ کوئری، invalidate هم فوری اعمال میشه ──
    gs_calls = {"n": 0}
    _orig_gs = fj_svc.get_settings

    async def _gs_count(s2):
        gs_calls["n"] += 1
        return await _orig_gs(s2)
    fj_svc.get_settings = _gs_count
    try:
        fj_svc.invalidate_settings()
        for _ in range(5):
            await fj_svc.get_settings_cached()
        check("کش ستینگ: ۵ خوانش پشت‌سر فقط ۱ کوئری دیتابیس", gs_calls["n"] == 1, str(gs_calls["n"]))
    finally:
        fj_svc.get_settings = _orig_gs

    async with session_scope() as s:
        await fj_svc._set(s, "fj_channel", "@gheydi")   # تغییر مستقیم دی‌بی بدون invalidate
        await s.commit()
    still = (await fj_svc.get_settings_cached())["channel"]
    async with session_scope() as s:
        await fj_svc.set_channel(s, "@teriakytest", "https://t.me/teriakytest")   # مسیر رسمی = invalidate
        await s.commit()
    fresh = (await fj_svc.get_settings_cached())["channel"]
    check("کش TTL داره ولی تغییر ادمین فوری invalidate میشه",
          still != "@gheydi" and fresh == "@teriakytest", f"{still!r}→{fresh!r}")

    # ── resolve_member: عضو تازه‌چک تلگرام نمی‌خوره | منقضی یه بار می‌خوره | غیرعضوی شناخته‌شده هرگز ──
    fj_svc._MEMBER_CACHE.clear()
    tg_calls = {"n": 0}

    class _TgCount:
        def __init__(self, member):
            self.member = member

        async def get_chat_member(self, chat, uid):
            tg_calls["n"] += 1
            if self.member:
                return SimpleNamespace(status="member")
            raise _BR("User not found")

    async with session_scope() as s:
        ru, _ = await users.get_or_create(s, tg(8866, "reslv", "ریزالو"))
        ru.fj_member_status, ru.fj_checked_at, ru.fj_left_at = 1, now_utc(), None
        await s.commit()
    m1 = await fj_svc.resolve_member(_TgCount(True), "@teriakytest", 8866)
    m2 = await fj_svc.resolve_member(_TgCount(True), "@teriakytest", 8866)
    check("عضوی تازه‌چک بدون هیچ تلگرامی رد میشه (دی‌بی + کش)", m1 and m2 and tg_calls["n"] == 0, str(tg_calls["n"]))

    fj_svc._MEMBER_CACHE.clear()
    async with session_scope() as s:
        ru = await users.get_by_tg(s, 8866)
        ru.fj_checked_at = now_utc() - timedelta(seconds=config.FORCE_JOIN_RECHECK_SECONDS + 30)
        await s.commit()
    m3 = await fj_svc.resolve_member(_TgCount(True), "@teriakytest", 8866)
    m4 = await fj_svc.resolve_member(_TgCount(True), "@teriakytest", 8866)
    check("چک منقضی فقط یه بار تلگرام می‌خوره و دوباره کش میشه",
          m3 and m4 and tg_calls["n"] == 1, str(tg_calls["n"]))

    async with session_scope() as s:  # ری‌چک قبلی ردیفو تازه کرده، دوباره کهنتش می‌کنیم تا باز چک بخوره
        ru = await users.get_by_tg(s, 8866)
        ru.fj_checked_at = now_utc() - timedelta(seconds=config.FORCE_JOIN_RECHECK_SECONDS + 30)
        await s.commit()
    fj_svc._MEMBER_CACHE.clear()
    tg_calls["n"] = 0
    m5 = await fj_svc.resolve_member(_TgCount(False), "@teriakytest", 8866)
    m6 = await fj_svc.resolve_member(_TgCount(False), "@teriakytest", 8866)
    check("لفت موقع ری‌چک فوراً بلاکه و بعدش تلگرام نمی‌خوره",
          not m5 and not m6 and tg_calls["n"] == 1, str(tg_calls["n"]))
    fj_svc._MEMBER_CACHE.clear()
    m7 = await fj_svc.resolve_member(_TgCount(False), "@teriakytest", 8866)
    check("غیرعضوی ثبت‌شده رو دی‌بی هم بدون هیچ تلگرامی بلاک میمونه",
          not m7 and tg_calls["n"] == 1, str(tg_calls["n"]))

    # ── رویداد chat_member: لفت فوری قطعه (حتی بدون پیام کاربر)، جوین فوری وصله ──
    async with session_scope() as s:
        evu = await users.get_by_tg(s, 8866)
        left0 = evu.fj_left_at
        await s.commit()
    fe_left = SimpleNamespace(chat_member=SimpleNamespace(
        chat=SimpleNamespace(id=-100777, username="teriakytest"),
        new_chat_member=SimpleNamespace(user=SimpleNamespace(id=8866, is_bot=False), status="left")))
    await gate_h.fj_member_event(fe_left, None)
    async with session_scope() as s:
        evu = await users.get_by_tg(s, 8866)
        st_left = (evu.fj_member_status, evu.fj_left_at is not None)
        await s.commit()
    check("رویداد لفت: وضعیت فوراً غیرعضو و مهلت پاکسازی شروع شد",
          st_left == (0, True), f"{st_left} با left_at قبلی {left0 is not None}")
    check("کش حافظه هم غیرعضو شد (بلاک فوری روی پیام بعدی)",
          fj_svc.member_cache_get(8866) is False)

    fe_join = SimpleNamespace(chat_member=SimpleNamespace(
        chat=SimpleNamespace(id=-100777, username="teriakytest"),
        new_chat_member=SimpleNamespace(user=SimpleNamespace(id=8866, is_bot=False), status="member")))
    await gate_h.fj_member_event(fe_join, None)
    async with session_scope() as s:
        evu = await users.get_by_tg(s, 8866)
        st_join = (evu.fj_member_status, evu.fj_left_at)
        await s.commit()
    check("رویداد جوین: عضو شد و مهلت پاکسازی‌اش صفر شد", st_join == (1, None), str(st_join))

    fe_other = SimpleNamespace(chat_member=SimpleNamespace(
        chat=SimpleNamespace(id=-100999, username="hamedan"),
        new_chat_member=SimpleNamespace(user=SimpleNamespace(id=8866, is_bot=False), status="left")))
    await gate_h.fj_member_event(fe_other, None)
    async with session_scope() as s:
        evu = await users.get_by_tg(s, 8866)
        st_other = evu.fj_member_status
        await s.commit()
    check("آپدیت کانال دیگه اثری نداره", st_other == 1, str(st_other))

    # ── گیت خاموش: مسیر پیام صفر session و صفر تلگرام (با کش گرم) ──
    async with session_scope() as s:
        await fj_svc.set_enabled(s, False)
        await s.commit()
    fj_svc.invalidate_settings()
    await fj_svc.get_settings_cached()  # کش گرم میشه
    ss_touched = {"n": 0}
    _orig_ss = fj_svc.session_scope
    from contextlib import asynccontextmanager as _acm

    @_acm
    async def _rec_ss():
        ss_touched["n"] += 1
        async with _orig_ss() as s3:
            yield s3
    fj_svc.session_scope = _rec_ss
    try:
        for _ in range(4):
            upd_off = _text_update("تریاکی شاپ", uid=8860, uname="gate1", fname="گیت‌خور")
            await gate_h.gate_messages(upd_off, SimpleNamespace(bot=SimpleNamespace(), application=SimpleNamespace()))
        check("گیت خاموش: ۴ پیام پی‌وی، صفر session و صفر getChatMember", ss_touched["n"] == 0)
    finally:
        fj_svc.session_scope = _orig_ss

    # ── جاب پاکسازی با مهلت: ۴۸ساعت لفت = ریست، لفت تازه و عضو و ادمین سالم ──
    from handlers import jobs as jobs_h2
    async with session_scope() as s:
        await fj_svc.set_channel(s, "@wipechan", "https://t.me/wipechan")
        wu, _ = await users.get_or_create(s, tg(8870, "wipee", "وایپی"))
        wu.level, wu.cash = 9, 123456
        wu.fj_member_status, wu.fj_checked_at = 0, now_utc()
        wu.fj_left_at = now_utc() - timedelta(hours=config.FORCE_JOIN_WIPE_AFTER_HOURS + 1)
        ku, _ = await users.get_or_create(s, tg(8871, "keeper", "نگهدار"))
        ku.level = 7
        ku.fj_member_status, ku.fj_left_at = 0, now_utc() - timedelta(hours=1)
        mu, _ = await users.get_or_create(s, tg(8872, "memberok", "عضوخوب"))
        mu.level, mu.fj_member_status = 7, 1
        adm = await users.get_by_tg(s, 1001)
        adm.fj_member_status = 0
        adm.fj_left_at = now_utc() - timedelta(hours=config.FORCE_JOIN_WIPE_AFTER_HOURS + 5)
        await s.commit()

    class _WipeBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
            self.sent.append((chat_id, text))
            return SimpleNamespace(message_id=len(self.sent))

    bot_wp = _WipeBot()
    await jobs_h2.fj_wipe_job(SimpleNamespace(bot=bot_wp))
    async with session_scope() as s:
        wu = await users.get_by_tg(s, 8870)
        ku = await users.get_by_tg(s, 8871)
        mu = await users.get_by_tg(s, 8872)
        adm = await users.get_by_tg(s, 1001)
        wipe_ok = (wu.level == 1 and wu.cash == config.START_CASH
                   and wu.fj_member_status is None and wu.fj_left_at is None)
        keep_ok = ku.level == 7 and ku.fj_left_at is not None
        member_ok = mu.level == 7 and mu.fj_member_status == 1
        adm_safe = adm.level != 1 and adm.fj_member_status == 0
        adm.fj_member_status = adm.fj_checked_at = adm.fj_left_at = None
        await s.commit()
    check("غیرعضوی 48ساعته ریست شد و پیامشم گرفت",
          wipe_ok and any(cid == 8870 for cid, _ in bot_wp.sent), f"level={wu.level}, dms={len(bot_wp.sent)}")
    check("لفت تازه‌کار و عضو و ادمین دست‌نخورده موندن",
          keep_ok and member_ok and adm_safe and len(bot_wp.sent) == 1, f"{keep_ok} {member_ok} {adm_safe}")

    async with session_scope() as s:
        await fj_svc.set_enabled(s, False)
        await s.commit()
    bot_wp2 = _WipeBot()
    await jobs_h2.fj_wipe_job(SimpleNamespace(bot=bot_wp2))
    async with session_scope() as s:
        ku = await users.get_by_tg(s, 8871)
        off_ok = ku.level == 7
        await s.commit()
    check("گیت خاموش باشه جاب پاکسازی هیچ کاری نمی‌کنه", off_ok and not bot_wp2.sent)

    # ── کش عضویت حافظه‌ای سقف داره، لیک نمی‌سازه ──
    fj_svc._MEMBER_CACHE.clear()
    for i in range(fj_svc._MEMBER_CAP + 500):
        fj_svc.member_cache_put(990000 + i, True, 60)
    check("کش عضویت کاربر سقفش رعایت میشه (GC مثل بقیه کش‌ها)",
          len(fj_svc._MEMBER_CACHE) <= fj_svc._MEMBER_CAP, str(len(fj_svc._MEMBER_CACHE)))

    # ═══ این دور: دکمه‌های آماده بانک + تایم‌اوت ورودی معلق + بایند چت ═══
    from handlers import bank as bank_h3
    from services import quests as quests_svc
    import json as _json

    # ── دکمه واریز: متن سوال دقیق + دکمه کل موجودی + اکشن معلق با زمان ──
    async with session_scope() as s:
        bu, _ = await users.get_or_create(s, tg(7370, "bnk", "بانکدار"))
        bu.cash = 5000
        bu.bank_balance = 0
        bu.bank_level = 1
        users.set_pending(bu, None)
        await s.commit()
    upd = _fake_update("bank:dep", uid=7370)
    await bank_h3.bank_ask_cb(upd, None)
    edt = next(c for c in upd.callback_query.calls if c[0] == "edit")
    qdatas = [b.callback_data for row in edt[2]["reply_markup"].inline_keyboard for b in row]
    qstyles = [b.style for row in edt[2]["reply_markup"].inline_keyboard for b in row]
    check("سوال واریز بانک قالب دقیق جدید رو داره",
          all(x in edt[1] for x in ["<b>💰 مبلغ واریز به بانک</b>", "چقد تی‌پوینت میخوای بزاری بانک؟",
                                    "عددشو همینجا بنویس و بفرست، مثلا: 1200",
                                    "یا اینکه از گزینه‌های زیر یکی رو انتخاب کن", "پشیمون شدی بنویس «لغو»"]),
          edt[1].replace("\n", " | ")[:110])
    check("دکمه آماده واریز فقط «کل موجودی»ـه و سبزه",
          qdatas == ["bankq:dep:all"] and qstyles == ["success"], str(qdatas))
    async with session_scope() as s:
        bu = await users.get_by_tg(s, 7370)
        check("اکشن معلق واریز با زمان ست شد", bu.pending_action == "bankdep" and bu.pending_at is not None)

    # کار معلق قبلی داشته باشی دکمه بانک فقط الرت میده
    async with session_scope() as s:
        bu = await users.get_by_tg(s, 7370)
        users.set_pending(bu, "resbuy", "", None)
        await s.commit()
    upd = _fake_update("bank:wd", uid=7370)
    await bank_h3.bank_ask_cb(upd, None)
    check("کار معلق قبلی داشته باشی دکمه بانک فقط الرت میده",
          any(c[0] == "answer" and "اول کار قبلیتو تموم کن" in str(c[1]) for c in upd.callback_query.calls),
          str(upd.callback_query.calls[:1]))
    async with session_scope() as s:
        bu = await users.get_by_tg(s, 7370)
        check("pending قبلی سر جاش موند", bu.pending_action == "resbuy")

    # ── دکمه برداشت: متن سوال + دو دکمه آماده نصف/کل ──
    async with session_scope() as s:
        bu = await users.get_by_tg(s, 7370)
        users.set_pending(bu, None)
        await s.commit()
    upd = _fake_update("bank:wd", uid=7370)
    await bank_h3.bank_ask_cb(upd, None)
    edt = next(c for c in upd.callback_query.calls if c[0] == "edit")
    qdatas = [b.callback_data for row in edt[2]["reply_markup"].inline_keyboard for b in row]
    qtexts = [b.text for row in edt[2]["reply_markup"].inline_keyboard for b in row]
    check("سوال برداشت بانک قالب دقیق جدید رو داره",
          all(x in edt[1] for x in ["<b>💰 مبلغ برداشت از بانک</b>", "چقد تی‌پوینت میخوای برداشت کنی؟",
                                    "عددشو همینجا بنویس و بفرست، مثلا: 1200", "پشیمون شدی بنویس «لغو»"]),
          edt[1].replace("\n", " | ")[:110])
    check("دکمه‌های آماده برداشت «نصف» و «کل موجودی»ـن",
          qdatas == ["bankq:wd:half", "bankq:wd:all"] and qtexts == ["💸 نصف موجودی", "💰 کل موجودی"], str(qdatas))
    async with session_scope() as s:
        bu = await users.get_by_tg(s, 7370)
        check("اکشن معلق برداشت ست شد", bu.pending_action == "bankwd")

    # ── کل موجودی واریز: pending جمع میشه و کارت تازه با موجودی جدید میاد ──
    upd = _fake_update("bankq:dep:all", uid=7370)
    await bank_h3.bank_quick_cb(upd, None)
    edt = next(c for c in upd.callback_query.calls if c[0] == "edit")
    async with session_scope() as s:
        bu = await users.get_by_tg(s, 7370)
        dep_ok = bu.bank_balance == 5000 and bu.cash == 0 and bu.pending_action is None
    check("دکمه کل موجودی همه نقدی رو برد تو بانک و pending رو جمع کرد", dep_ok)
    check("کارت بانک بعد واریز سریع موجودی جدیدو نشون داد",
          "🏦 موجودی بانک:" in edt[1] and "💵 نقدینگی:" in edt[1], edt[1].replace("\n", " | ")[:80])

    # نصف و بعد کل برداشت
    upd = _fake_update("bankq:wd:half", uid=7370)
    await bank_h3.bank_quick_cb(upd, None)
    async with session_scope() as s:
        bu = await users.get_by_tg(s, 7370)
        half_ok = bu.bank_balance == 2500 and bu.cash == 2500
    check("دکمه نصف موجودی نصف بانک رو برداشت کرد", half_ok)
    upd = _fake_update("bankq:wd:all", uid=7370)
    await bank_h3.bank_quick_cb(upd, None)
    async with session_scope() as s:
        bu = await users.get_by_tg(s, 7370)
        all_ok = bu.bank_balance == 0 and bu.cash == 5000
    check("دکمه کل موجودی بقیه بانک رو هم برداشت کرد", all_ok)

    # آلرت‌های لبه: بانک خالی | نقدی صفر | بانک پر
    upd = _fake_update("bankq:wd:all", uid=7370)
    await bank_h3.bank_quick_cb(upd, None)
    check("برداشت از بانک خالی آلرت میده",
          any(c[0] == "answer" and "بانکت خالیه" in str(c[1]) for c in upd.callback_query.calls))
    async with session_scope() as s:
        bu = await users.get_by_tg(s, 7370)
        bu.cash = 0
        await s.commit()
    upd = _fake_update("bankq:dep:all", uid=7370)
    await bank_h3.bank_quick_cb(upd, None)
    check("واریز با نقدی صفر آلرت میده",
          any(c[0] == "answer" and "نقدینگی نداری" in str(c[1]) for c in upd.callback_query.calls))
    async with session_scope() as s:
        bu = await users.get_by_tg(s, 7370)
        bu.bank_balance = bank_svc.bank_capacity(bu.bank_level)
        bu.cash = 500
        await s.commit()
    upd = _fake_update("bankq:dep:all", uid=7370)
    await bank_h3.bank_quick_cb(upd, None)
    async with session_scope() as s:
        bu = await users.get_by_tg(s, 7370)
        full_ok = bu.bank_balance == bank_svc.bank_capacity(1) and bu.cash == 500
    check("واریز به بانک پر آلرت ارتقا میده و چیزی عوض نمیشه",
          full_ok and any(c[0] == "answer" and "پره دیگه" in str(c[1]) for c in upd.callback_query.calls))

    # ── کانفیگ‌های این دور ──
    check("مهلت و جاروی ورودی معلق 60 و 20 ثانیه‌ست",
          config.PENDING_TIMEOUT_SECONDS == 60 and config.PENDING_SWEEP_SECONDS == 20)
    check("پنجره گروه‌های فعال آب‌وهوا 24 ساعته و بین ارسال‌ها مکث هست",
          config.WEATHER_GROUP_ACTIVE_HOURS == 24 and config.WEATHER_GROUP_SEND_DELAY > 0)
    check("دیبانس کاروان 2 ثانیه و مکث پیام همگانی مثبته",
          config.CARAVAN_HIT_DEBOUNCE_SECONDS == 2 and config.BROADCAST_DELAY_SECONDS > 0)
    check("رشد کوئست تیم 40% هدف و 30% جایزه",
          config.TEAM_QUEST_TARGET_GROWTH == 0.40 and config.TEAM_QUEST_REWARD_GROWTH == 0.30)
    check("رشد کوئست روزانه بازیکن 10% هدف و 12% جایزه",
          config.DAILY_QUEST_TARGET_GROWTH == 0.10 and config.DAILY_QUEST_REWARD_GROWTH == 0.12)
    check("یورش پلیس کاملاً خاموشه", config.POLICE_ENABLED is False)

    # ── جاروی ورودی معلق: عددی‌های منقضی خودکار بی‌خیال میشن ──
    sbot_pre = _WipeBot()
    await jobs_h2.pending_sweep_job(SimpleNamespace(bot=sbot_pre))
    sbot_pre.sent.clear()  # بک‌لاگ تست‌های قبلی جارو شد، حالا تست تمیز

    async with session_scope() as s:
        sw1, _ = await users.get_or_create(s, tg(7371, "swold", "خوابونده"))
        users.set_pending(sw1, "bankdep", "", 555)
        sw1.pending_at = now_utc() - timedelta(seconds=config.PENDING_TIMEOUT_SECONDS + 5)
        sw2, _ = await users.get_or_create(s, tg(7372, "swfresh", "تازه‌جواب"))
        users.set_pending(sw2, "bankwd", "", 666)
        await s.commit()
    sbot = _WipeBot()
    await jobs_h2.pending_sweep_job(SimpleNamespace(bot=sbot))
    async with session_scope() as s:
        sw1 = await users.get_by_tg(s, 7371)
        sw2 = await users.get_by_tg(s, 7372)
        old_done = sw1.pending_action is None and sw1.pending_at is None
        fresh_kept = sw2.pending_action == "bankwd" and sw2.pending_at is not None
    check("جارو pending منقضی رو جمع کرد", old_done)
    check("جارو pending تازه رو دست نزد", fresh_kept)
    check("پیام بی‌خیالی به همون چتی رفت که کار شروع شده بود",
          sbot.sent == [(555, "به دلیل عدم پاسخ، عملیات رو بیخیال شدیم")], str(sbot.sent))
    async with session_scope() as s:
        sw2 = await users.get_by_tg(s, 7372)
        users.set_pending(sw2, None)
        await s.commit()

    # ── ورودی معلق فقط تو همون چتی جواب داده میشه که شروع شده ──
    async with session_scope() as s:
        cbu, _ = await users.get_or_create(s, tg(7373, "chatbound", "چتی"))
        cbu.cash = 9000
        users.set_pending(cbu, "bankdep", "", 111)
        await s.commit()
    for _try in range(2):
        upd = _text_update("1200", uid=7373, uname="chatbound", fname="چتی")
        try:
            await pending_h.capture(upd, None)
        except Exception:
            pass
    async with session_scope() as s:
        cbu = await users.get_by_tg(s, 7373)
        check("ورودی معلق تو چت دیگه کاملاً بی‌صداس (نه ریپلای نه پاک شدن)",
              not upd.message.calls and cbu.pending_action == "bankdep", str(upd.message.calls)[:40])
        cbu.pending_chat_id = 100  # برگشت به همون چتی که دکمه رو زده بود
        await s.commit()
    upd = _text_update("1200", uid=7373, uname="chatbound", fname="چتی")
    st = False
    try:
        await pending_h.capture(upd, None)
    except Exception as e:
        st = type(e).__name__ == "ApplicationHandlerStop"
    async with session_scope() as s:
        cbu = await users.get_by_tg(s, 7373)
        chat_ok = (st and cbu.pending_action is None and cbu.bank_balance == 1200
                   and any("رفت تو بانک" in c[1] for c in upd.message.calls))
    check("تو همون چت، عدد به‌عنوان واریز پردازش شد", chat_ok, f"st={st}")

    # ── /update ادمین: آنبوردینگ زمین گیرکرده‌ها رو فیکس می‌کنه ──
    async with session_scope() as s:
        plu, _ = await users.get_or_create(s, tg(7374, "pltfix", "زمینی"))
        plu.first_plot_at = None
        s.add(Plot(user_id=plu.id))
        await s.commit()
    upd = _text_update("/update", uid=1001, uname="admin1", fname="ادمین")
    await admin_h.update_cmd(upd, None)
    rep = upd.message.calls[-1][1] if upd.message.calls else ""
    import re as _re2
    mfix = _re2.search(r"🌱 آنبوردینگ زمین ([\d,]+) بازیکن گیرکرده فیکس شد", rep)
    async with session_scope() as s:
        plu = await users.get_by_tg(s, 7374)
        fix_ok = plu.first_plot_at is not None and mfix is not None and int(mfix.group(1).replace(",", "")) >= 1
    check("/update ثبت اولین زمین گیرکرده‌ها رو فیکس کرد", fix_ok, rep.replace("\n", " | ")[:120])
    check("گزارش /update وضعیت بازی رو می‌گه", "🔄 وضعیت بازی به‌روز شد" in rep, rep[:40])

    # ── متن‌های سگ: خرید ساده و نوتیف لول‌آپ تشویقی ──
    async with session_scope() as s:
        dgu, _ = await users.get_or_create(s, tg(7375, "dogbuy", "سگ‌باز"))
        dgu.level = 8
        dgu.cash = 2000000
        dgbuy_ok, bmsg = await dog_svc.buy_dog(s, dgu, "doberman", "هانتر")
        await s.commit()
    check("متن خرید سگ ساده و بدون تگ HTMLه و روش آمار رو یادش میده",
          dgbuy_ok and "🐕 مبارکه، هانتر رفیق جدیدت شد" in bmsg and "<b>" not in bmsg
          and "«تریاکی آمار هانتر»" in bmsg, bmsg[:80])
    check("آخر متن خرید سگ نقدینگی هم نشون داده میشه",
          "\n\n💵 نقدینگی: " in bmsg and bmsg.rstrip().endswith("تی‌پوینت"), bmsg[-60:])
    async with session_scope() as s:
        dgu = await users.get_by_tg(s, 7375)
        ddogs = await dog_svc.get_user_dogs(s, dgu.id)
        dneed = dog_svc.dog_xp_need(ddogs[0].level)
        dnotes = await dog_svc.add_battle_xp(ddogs, dneed + 30)
        dlvl = ddogs[0].level
        await s.commit()
    check("نوتیف لول‌آپ سگ قالب تشویقی جدید رو داره",
          bool(dnotes) and "🆙 آفرین، هانتر لول‌آپ شد و الان قدرتش" in dnotes[0] and dlvl == 2,
          dnotes[0] if dnotes else "-")

    # ── پیام همگانی ادمین 📣 تمام‌فلو ──
    upd = _fake_update("adm:bcast:0", uid=1001)
    await admin_h.admin_cb(upd, None)
    edt = next(c for c in upd.callback_query.calls if c[0] == "edit")
    async with session_scope() as s:
        bau = await users.get_by_tg(s, 1001)
        bpa = bau.pending_action
    check("دکمه «پیام همگانی» پنل، متن پیام رو می‌خواد و اکشن معلق می‌ذاره",
          bpa == "bcast" and "پیامتو بفرست" in edt[1], f"{bpa} | {edt[1][:40]}")
    updt = _text_update("سلام ملت، ایونت دوبرابر شروع شد", uid=1001, uname="admin1", fname="ادمین")
    updt.message.message_id = 909
    st = False
    try:
        await pending_h.capture(updt, None)
    except Exception as e:
        st = type(e).__name__ == "ApplicationHandlerStop"
    sc_mk = updt.message.calls[-1][2].get("reply_markup") if updt.message.calls else None
    sc_datas = [b.callback_data for row in sc_mk.inline_keyboard for b in row] if sc_mk else []
    check("پیام بعدی ادمین کیبورد انتخاب دامنه رو آورد",
          st and bool(updt.message.calls) and "به کی بفرستمش؟" in updt.message.calls[-1][1]
          and sc_datas == ["bcs:g:100:909", "bcs:p:100:909", "bcs:a:100:909", "bcc"], str(sc_datas))
    async with session_scope() as s:
        bau = await users.get_by_tg(s, 1001)
        check("pending پیام همگانی بعد از گرفتن پیام جمع شد", bau.pending_action is None)
    upd = _fake_update("bcs:a:100:909", uid=1001)
    await admin_h.broadcast_scope_cb(upd, None)
    edt = next(c for c in upd.callback_query.calls if c[0] == "edit")
    mdatas = [b.callback_data for row in edt[2]["reply_markup"].inline_keyboard for b in row]
    check("انتخاب دامنه، سوال مد ارسال رو آورد",
          "چطور بره؟" in edt[1] and mdatas == ["bcm:f:a:100:909", "bcm:t:a:100:909", "bcc"], str(mdatas))
    upd = _fake_update("bcs:a:100:909", uid=9999)
    await admin_h.broadcast_scope_cb(upd, None)
    check("دامنه همگانی برای غیرادمین کاملاً بی‌صداس",
          [c[0] for c in upd.callback_query.calls] == ["answer"])

    class _BCastBot:
        def __init__(self, fails=()):
            self.fails = set(fails)
            self.fwd, self.cpy, self.edits = [], [], []

        async def forward_message(self, chat_id, from_chat_id, message_id):
            from telegram.error import Forbidden
            if chat_id in self.fails:
                raise Forbidden("blocked")
            self.fwd.append(chat_id)

        async def copy_message(self, chat_id, from_chat_id, message_id):
            from telegram.error import Forbidden
            if chat_id in self.fails:
                raise Forbidden("blocked")
            self.cpy.append(chat_id)

        async def edit_message_text(self, chat_id=None, message_id=None, text=None, parse_mode=None):
            self.edits.append(text)

    _delay_orig = config.BROADCAST_DELAY_SECONDS
    config.BROADCAST_DELAY_SECONDS = 0  # تو تست صدها مقصد داریم، صبر واقعی نه
    try:
        async with session_scope() as s:
            from sqlalchemy import select as _sel2
            g_list = list((await s.execute(_sel2(GroupActivity.chat_id))).scalars())
            u_list = list((await s.execute(_sel2(User.telegram_id))).scalars())
        bb = _BCastBot()
        res_g = await admin_h.broadcast_run(bb, 100, 909, "f", "g", 100, 909)
        check("همگانی فوروارد به همه گروه‌ها کامل رفت",
              res_g["total"] == len(g_list) > 0 and res_g["ok"] == len(g_list) and res_g["fail"] == 0
              and bb.fwd == g_list, f"{res_g}")
        fin = bb.edits[-1] or ""
        check("گزارش نهایی همگانی قالب کامل داره",
              "✅ پیام همگانی تموم شد" in fin and "📤 موفق:" in fin and "📊 کل مقصدها:" in fin
              and "👥 فقط گروه‌ها" in fin, fin.replace("\n", " | ")[:110])
        bb2 = _BCastBot(fails={g_list[-1]})
        res_g2 = await admin_h.broadcast_run(bb2, 100, 909, "f", "g", 100, 909)
        check("مقصد بلاک‌شده تو شمار خطا حساب میشه",
              res_g2["fail"] == 1 and res_g2["ok"] == len(g_list) - 1, f"{res_g2}")
        bb3 = _BCastBot()
        res_p = await admin_h.broadcast_run(bb3, 100, 909, "t", "p", 100, 909)
        check("همگانی ارسالی (copy) به همه پی‌وی‌ها رفت",
              res_p["total"] == len(u_list) > 0 and res_p["ok"] == len(u_list) and len(bb3.cpy) == len(u_list),
              f"{res_p['ok']}/{res_p['total']}")
    finally:
        config.BROADCAST_DELAY_SECONDS = _delay_orig

    # ── سوال هدیه ادمین هم ریتم قالب یکدست عددیه ──
    upd = _fake_update("adm:gtp:7375", uid=1001)
    await admin_h.admin_cb(upd, None)
    edt = next(c for c in upd.callback_query.calls if c[0] == "edit")
    async with session_scope() as s:
        gadm = await users.get_by_tg(s, 1001)
        gpa = gadm.pending_action
        gpv = gadm.pending_value
    check("سوال هدیه تی‌پوینت ادمین قالب یکدست داره",
          gpa == "admtp" and gpv == "7375"
          and all(x in edt[1] for x in ["<b>💰 هدیه تی‌پوینت به", "چقد تی‌پوینت میخوای بهش بدی؟",
                                        "عددشو همینجا بنویس و بفرست، مثلا: 5000",
                                        "❌ اگر هم پشیمون شدی بنویس «لغو»"]),
          edt[1].replace("\n", " | ")[:100])
    upd = _fake_update("adm:gxp:7375", uid=1001)
    await admin_h.admin_cb(upd, None)
    edt = next(c for c in upd.callback_query.calls if c[0] == "edit")
    check("سوال هدیه تجربه ادمین هم قالب یکدست داره",
          "<b>✨ هدیه تجربه به" in edt[1] and "چند تا تجربه میخوای بهش بدی؟" in edt[1]
          and "مثلا: 500" in edt[1] and "❌ اگر هم پشیمون شدی بنویس «لغو»" in edt[1],
          edt[1].replace("\n", " | ")[:100])
    # عددِ نامعتبر توی فلوی هدیه، خطای یکدست میگیره و pending سر جاش میمونه
    upd = _text_update("سلام", uid=1001, uname="admin1", fname="ادمین")
    st = False
    try:
        await pending_h.capture(upd, None)
    except Exception as e:
        st = type(e).__name__ == "ApplicationHandlerStop"
    async with session_scope() as s:
        gadm = await users.get_by_tg(s, 1001)
        bad_ok = gadm.pending_action == "admxp"
    check("عدد نامعتبر توی هدیه ادمین خطای یکدست میگیره و pending میمونه",
          st and bad_ok
          and any("❌ فقط عددشو بفرست، مثلا: 5000" in c[1] and "❌ اگر هم پشیمون شدی بنویس «لغو»" in c[1]
                  for c in upd.message.calls),
          str(upd.message.calls[-1][1])[:60] if upd.message.calls else "-")
    # عدد صحیح: اعمال میشه و pending جمع
    upd = _text_update("250", uid=1001, uname="admin1", fname="ادمین")
    st = False
    try:
        await pending_h.capture(upd, None)
    except Exception as e:
        st = type(e).__name__ == "ApplicationHandlerStop"
    async with session_scope() as s:
        gadm = await users.get_by_tg(s, 1001)
        await s.commit()
    check("هدیه تجربه ادمین با عدد درست اعمال و pending جمع میشه",
          st and gadm.pending_action is None
          and any("✨ 250 تجربه دادی به" in c[1] for c in upd.message.calls),
          str(upd.message.calls[-1][1])[:60] if upd.message.calls else "-")

    # ── تغییر نام تیم، تمام‌فلو (رگرسیون باگ پترن tmcf) ──
    async with session_scope() as s:
        rno, _ = await users.get_or_create(s, tg(7376, "rnowner", "رهبر"))
        rno.level = 8
        rno.cash = 200000
        rnok, _rnm = await team_svc.create_team(s, rno, "گرگ‌های شمال")
        assert rnok, _rnm
        await s.commit()
    ctxr = SimpleNamespace(user_data={})
    upd = _text_update("تیم تغییر نام قهرمانان", uid=7376, uname="rnowner", fname="رهبر")
    await team_h.rename_text(upd, ctxr)
    rtxt = upd.message.calls[-1][1] if upd.message.calls else ""
    check("فاکتور تغییر نام با اسم قدیم و جدید اومد",
          "✏️ تغییر نام تیم" in rtxt and "گرگ‌های شمال" in rtxt and "قهرمانان" in rtxt,
          rtxt.replace("\n", " | ")[:100])
    check("اسم جدید تا تایید تو کانتکست پارک شد",
          ctxr.user_data.get("pending_team_rename") == "قهرمانان", str(ctxr.user_data))
    upd = _fake_update("tmcf:rename:7376", uid=7376)
    await team_h.team_confirm_cb(upd, ctxr)
    async with session_scope() as s:
        rno = await users.get_by_tg(s, 7376)
        rteam = await team_svc.get_team_of(s, rno.id)
        rn_name, rn_id = (rteam.name, rteam.id) if rteam else (None, None)
        rn_cash = rno.cash
    check("تایید رینیم اسم تیم رو عوض کرد و هزینش رو برداشت",
          rn_name == "قهرمانان" and rn_cash == 200000 - config.TEAM_CREATE_COST - config.TEAM_RENAME_COST,
          f"{rn_name} {rn_cash}")
    check("پارک اسم بعد از اجرا خالی شد", "pending_team_rename" not in ctxr.user_data)

    from telegram.ext import CallbackQueryHandler as _CQH
    tmcf_pat = None
    for _hh in app.handlers.values():
        for _h in _hh:
            if isinstance(_h, _CQH) and getattr(getattr(_h, "callback", None), "__name__", "") == "team_confirm_cb":
                tmcf_pat = _h.pattern
    tmcf_src = getattr(tmcf_pat, "pattern", tmcf_pat) or ""
    check("پترن رجیستری tmcf رینیم رو dispatch می‌کنه (رگرسیون باگ اصلی)",
          bool(re.match(str(tmcf_src), "tmcf:rename:7376")), str(tmcf_src))

    # ═══ این دور: انتقال بانک به بانک با شماره حساب 💳 ═══

    # ── شماره حساب: فرمت، قطعیت، یکتایی ──
    async with session_scope() as s:
        ac1, _ = await users.get_or_create(s, tg(7390, "acc1", "حسابی یک"))
        ac2, _ = await users.get_or_create(s, tg(7391, "acc2", "حسابی دو"))
        a_code1, a_code2 = ac1.bank_acc, ac2.bank_acc
        a_code1_again = await bank_svc.ensure_bank_acc(s, ac1)
        await s.commit()
    check("شماره حساب با ساخت کاربر خودکار ساخته میشه و فرمتش 6 کاراکتر خواناس",
          bool(a_code1) and len(a_code1) == 6
          and all(c.isdigit() or (c.isalpha() and c.isupper()) for c in a_code1)
          and all(c not in a_code1 for c in "IO01"), a_code1)
    check("شماره حساب قطعیه و عوض نمیشه", a_code1_again == a_code1)
    check("شماره حساب‌ها یکتان", a_code1 != a_code2, f"{a_code1}/{a_code2}")

    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        btxt = bank_h3._bank_text(ac1)
    check("کارت بانک شماره حساب و راهنمای به اشتراک‌گذاریش رو داره",
          "💳 شماره بانک:" in btxt and a_code1 in btxt and "شماره رو به طرف بده" in btxt,
          btxt.replace("\n", " | ")[:80])

    # ── دکمه دراز انتقال زیر واریز/برداشت ──
    tfk = kb2.bank_kb(SimpleNamespace(bank_level=1, level=10))
    tf_row = [row for row in tfk.inline_keyboard if row and row[0].callback_data == "bank:tf"]
    tf_datas = [b.callback_data for row in tfk.inline_keyboard for b in row]
    check("دکمه دراز انتقال درست زیر واریز/برداشت اومده و آبیه",
          bool(tf_row) and len(tf_row[0]) == 1 and tf_row[0][0].text == "💳 انتقال موجودی"
          and tf_row[0][0].style == "primary"
          and tf_datas.index("bank:tf") == tf_datas.index("bank:wd") + 1, str(tf_datas[:4]))

    # ── فلو تمام: از دکمه تا تایید نهایی و اعمال ──
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        ac1.bank_balance = 15000
        ac1.bank_level = 1
        ac1.last_trf_at = None
        users.set_pending(ac1, None)
        ac2 = await users.get_by_tg(s, 7391)
        ac2.bank_balance = 0
        ac2.bank_level = 1
        await s.commit()
    upd = _fake_update("bank:tf", uid=7390)
    await bank_h3.bank_transfer_start(upd, None)
    edt = next(c for c in upd.callback_query.calls if c[0] == "edit")
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        tfa = ac1.pending_action
    check("دکمه انتقال، سوال شماره حساب رو با قالب یکدست می‌پرسه",
          tfa == "trf_to"
          and all(x in edt[1] for x in ["<b>💳 انتقال موجودی به حساب دیگه</b>",
                                        "به حساب کی میخوای پول واریز کنی؟",
                                        "شماره حسابشو همینجا بنویس و بفرست، مثلا: F8L6XS",
                                        "❌ اگر هم پشیمون شدی بنویس «لغو»"]), edt[1][:80])

    upd = _text_update("XYZXYZ", uid=7390, uname="acc1", fname="حسابی یک")
    st = False
    try:
        await pending_h.capture(upd, None)
    except Exception as e:
        st = type(e).__name__ == "ApplicationHandlerStop"
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        bad_acc = ac1.pending_action == "trf_to"
    check("شماره نامعتبر خطا می‌ده و pending سر جاش می‌مونه",
          st and bad_acc and any("همچین شماره حسابی پیدا نکردم" in c[1] for c in upd.message.calls))

    upd = _text_update(a_code1, uid=7390, uname="acc1", fname="حسابی یک")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        own_acc = ac1.pending_action == "trf_to"
    check("انتقال به حساب خودی رد میشه", own_acc and any("به حساب خودت" in c[1] for c in upd.message.calls))

    upd = _text_update(a_code2.lower(), uid=7390, uname="acc1", fname="حسابی یک")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        step2 = ac1.pending_action == "trf_amt" and ac1.pending_value == "7391"
    check("شماره درست (حتی کوچیک) به مرحله مبلغ میره و اسم گیرنده دیده میشه",
          step2 and any("💳 انتقال به حساب «حسابی دو»" in c[1] for c in upd.message.calls)
          and any("چقد تی‌پوینت میخوای بهش واریز کنی؟" in c[1] for c in upd.message.calls))

    upd = _text_update("سلام", uid=7390, uname="acc1", fname="حسابی یک")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    check("مبلغ نامعتبر خطای یکدست عددی می‌گیره",
          any("❌ فقط عددشو بفرست، مثلا: 8000" in c[1] for c in upd.message.calls))

    upd = _text_update("4999", uid=7390, uname="acc1", fname="حسابی یک")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        under_amt = ac1.pending_action == "trf_amt"
    check("مبلغ زیر حداقل 5,000 رد میشه و pending می‌مونه",
          under_amt and any(f"حداقل انتقال باید {money(config.TRF_MIN_AMOUNT)} باشه" in c[1] for c in upd.message.calls),
          str(upd.message.calls[-1][1][:60]) if upd.message.calls else "-")

    upd = _text_update("100001", uid=7390, uname="acc1", fname="حسابی یک")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        overmax_amt = ac1.pending_action == "trf_amt"
    check("مبلغ بالای سقف 100,000 رد میشه و pending می‌مونه",
          overmax_amt and any(f"حداکثر انتقال باید {money(config.TRF_MAX_AMOUNT)} باشه" in c[1] for c in upd.message.calls))

    upd = _text_update("99999", uid=7390, uname="acc1", fname="حسابی یک")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        over_amt = ac1.pending_action == "trf_amt"
    check("مبلغ بیشتر از موجودی بانک رد میشه و pending می‌مونه",
          over_amt and any("تو بانک این همه نداری" in c[1] for c in upd.message.calls))

    upd = _text_update("8000", uid=7390, uname="acc1", fname="حسابی یک")
    try:
        await pending_h.capture(upd, None)
    except Exception:
        pass
    fac_txt = upd.message.calls[-1][1] if upd.message.calls else ""
    fac_mk = upd.message.calls[-1][2].get("reply_markup") if upd.message.calls else None
    fac_datas = [b.callback_data for row in fac_mk.inline_keyboard for b in row] if fac_mk else []
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        tfa3 = ac1.pending_action
    check("فاکتور انتقال شماره حساب و اسم گیرنده رو نشون میده",
          tfa3 is None
          and all(x in fac_txt for x in ["<b>💳 تاییدیه انتقال</b>", "💸 مبلغ: 8,000 تی‌پوینت",
                                         f"🔢 شماره حساب: <code>{a_code2}</code>",
                                         "👤 حساب به نام «حسابی دو» هست",
                                         "🏦 موجودی بانکت بعد انتقال: 7,000 تی‌پوینت",
                                         "از انتقال اطمینان داری؟"])
          and "tbf:7391:8000" in fac_datas, fac_txt.replace("\n", " | ")[:140])

    class _TrfBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, parse_mode=None):
            self.sent.append((chat_id, text))

    tb = _TrfBot()
    upd = _fake_update("tbf:7391:8000", uid=7390)
    await bank_h3.bank_transfer_execute(upd, SimpleNamespace(bot=tb))
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        ac2 = await users.get_by_tg(s, 7391)
        moved_ok = ac1.bank_balance == 7000 and ac2.bank_balance == 8000
    check("تایید نهایی پول رو بانک به بانک جابه‌جا می‌کنه", moved_ok,
          f"{ac1.bank_balance}/{ac2.bank_balance}")
    tf_ans = [c for c in upd.callback_query.calls if c[0] == "answer"]
    check("فرستنده تایید موفقیت می‌گیره و کارتش ادیت میشه",
          tf_ans and "✅" in str(tf_ans[0][1]) and "واریز شد" in str(tf_ans[0][1]), str(tf_ans[:1]))
    check("گیرنده توی پی‌وی خبر واریز رو گرفت (با اسم فعلی فرستنده)",
          len(tb.sent) == 1 and tb.sent[0][0] == 7391
          and all(x in tb.sent[0][1] for x in ["یه انتقال به حسابت اومد", "💰 8,000 تی‌پوینت از طرف «"]),
          str(tb.sent[:1])[:90])
    # کولدان ۶۰ ثانیه‌ای بعد انتقال موفق
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        ac2 = await users.get_by_tg(s, 7391)
        cd_ok, cd_msg = await bank_svc.transfer_to(s, ac1, ac2, 5000)
        cd_left = bank_svc.trf_cooldown_left(ac1)
        ac1.last_trf_at = None
        await s.commit()
    check("انتقال دوباره بلافاصله کولدان ۶۰ ثانیه می‌خوره",
          not cd_ok and "تازه انتقال دادی" in cd_msg and "ثانیه دیگه نمیتونی انتقال بدی" in cd_msg
          and 1 <= cd_left <= 60, f"{cd_msg} | {cd_left}")

    # ── سرویس انتقال: لبه‌ها ──
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        ac2 = await users.get_by_tg(s, 7391)
        sv_self, _m1 = await bank_svc.transfer_to(s, ac1, ac1, 10000)
        sv_min, m_min = await bank_svc.transfer_to(s, ac1, ac2, 4999)
        sv_max, m_max = await bank_svc.transfer_to(s, ac1, ac2, 100001)
        ac2.bank_balance = bank_svc.bank_capacity(1) - 5000
        sv_room, rmsg = await bank_svc.transfer_to(s, ac1, ac2, 6000)
        sv_ok, _m2 = await bank_svc.transfer_to(s, ac1, ac2, 5000)
        await s.commit()
    check("محدوده انتقال 5,000 تا 100,000 سر سرویس هم هست",
          not sv_min and "حداقل انتقال باید 5,000 تی‌پوینت باشه" in m_min and not sv_max and "حداکثر انتقال باید 100,000 تی‌پوینت باشه" in m_max,
          f"{m_min} | {m_max}")
    check("سرویس انتقال خودی و سرِ ظرفیت رو رد می‌کنه ولی تا سقف قبوله",
          not sv_self and not sv_room and "فقط" in rmsg and sv_ok, f"{sv_self}/{sv_room}/{sv_ok}")

    # ── «بانک» بدون پیشوند + «بانک واریز/برداشت» + «انتقال n کد» ──
    check("«بانک» لخت و با پیشوند بانک رو باز می‌کنه",
          bool(pats["bankhome"].match("بانک")) and bool(pats["bankhome"].match("تریاکی بانک")))
    check("«بانک واریز/برداشت 1200» با و بدون پیشوند می‌خوره",
          bool(pats["bankdep2"].match("بانک واریز 1200")) and bool(pats["bankwd2"].match("تی بانک برداشت ۱۴۰۰")))
    check("«انتقال 4000 E86YF2» با و بدون پیشوند می‌خوره",
          bool(pats["banktrf"].match("انتقال 4000 E86YF2")) and bool(pats["banktrf"].match("تریاک انتقال ۷۰۰۰ E86YF2")))
    from handlers.bank import _bank_text as _btext
    btx2 = _btext(SimpleNamespace(bank_acc="X9Q2LM", bank_balance=0, bank_level=1))
    check("هینت دستورهای جدید تو صفحه بانک هست",
          "«بانک واریز 1200»" in btx2 and "«انتقال 4000 E86YF2»" in btx2, btx2[:60])

    async with session_scope() as s:
        bs1, _ = await users.get_or_create(s, tg(7392, "acc3", "حسابی سه"))
        bs2, _ = await users.get_or_create(s, tg(7393, "acc4", "حسابی چهار"))
        bs1.cash = 30000
        bs1.bank_balance = 30000
        bs1.bank_level = 2
        bs2.bank_balance = 0
        bs2.bank_level = 1
        code4 = await bank_svc.ensure_bank_acc(s, bs2)
        dok, dmsg = await bank_svc.deposit(s, bs1, 5000)
        await s.commit()
    check("متن واریز جدید: رفت تو بانک و جاش امنه، دور از هر دزدی",
          dok and "رفت تو بانک و جاش امنه، دور از هر دزدی 🛡" in dmsg, dmsg[:70])
    async with session_scope() as s:
        bs1 = await users.get_by_tg(s, 7392)
        bs2 = await users.get_by_tg(s, 7393)
        bs1.last_trf_at = None
        bs2.bank_balance = bank_svc.bank_capacity(1)
        fok4, fmsg4 = await bank_svc.transfer_to(s, bs1, bs2, 5000)
        bs2.bank_balance = bank_svc.bank_capacity(1) - 3000
        rok4, rmsg4 = await bank_svc.transfer_to(s, bs1, bs2, 5000)
        await s.commit()
    check("بانک پر گیرنده با اسمش رد میشه",
          not fok4 and "بانک «حسابی چهار» کاملاً پره، الان امکان واریز به حسابش نیست" in fmsg4, fmsg4[:80])
    check("جای خالی کم بانک گیرنده با اسم و مبلغ دقیق رد میشه",
          not rok4 and "بانک «حسابی چهار» فقط 3,000 تی‌پوینت جای خالی داره، کمتر بگو" in rmsg4, rmsg4[:80])

    # هندلر دستور «انتقال n کد»: فاکتور با دکمه تایید میاد
    async with session_scope() as s:
        bs2 = await users.get_by_tg(s, 7393)
        bs2.bank_balance = 0  # جای خالی برای فاکتور موفق
        await s.commit()
    upd_btx = _text_update(f"انتقال 8000 {code4}", uid=7392, uname="acc3", fname="حسابی سه")
    await bank_h3.transfer_text(upd_btx, None)
    btx_t = upd_btx.message.calls[-1][1] if upd_btx.message.calls else ""
    btx_mk = upd_btx.message.calls[-1][2].get("reply_markup") if upd_btx.message.calls else None
    btx_datas = [b.callback_data for row in btx_mk.inline_keyboard for b in row] if btx_mk else []
    check("«انتقال 8000 کد» فاکتور با شماره حساب و اسم گیرنده و دکمه تایید میاره",
          all(x in btx_t for x in ["<b>💳 تاییدیه انتقال</b>", "💸 مبلغ: 8,000 تی‌پوینت",
                                   f"🔢 شماره حساب: <code>{code4}</code>", "👤 حساب به نام «حسابی چهار» هست",
                                   "🏦 موجودی بانکت بعد انتقال: 27,000 تی‌پوینت"])
          and "tbf:7393:8000" in btx_datas, btx_t.replace("\n", " | ")[:140])
    upd_bad3 = _text_update("انتقال 8000 WRONG99", uid=7392, uname="acc3", fname="حسابی سه")
    await bank_h3.transfer_text(upd_bad3, None)
    check("شماره حساب اشتباه تو دستور انتقال رد میشه",
          any("همچین شماره حسابی پیدا نکردم" in c[1] for c in upd_bad3.message.calls))
    upd_low3 = _text_update(f"انتقال 3000 {code4}", uid=7392, uname="acc3", fname="حسابی سه")
    await bank_h3.transfer_text(upd_low3, None)
    check("زیر حداقل تو دستور انتقال هم قالب «باید باشه»ـه",
          any("حداقل انتقال باید 5,000 تی‌پوینت باشه" in c[1] for c in upd_low3.message.calls))
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        ac1.last_trf_at = None
        await s.commit()

    # اجرای دوباره باید چک دوباره بزنه: موجودی کم شده → رد
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        ac1.bank_balance = 100
        await s.commit()
    upd = _fake_update("tbf:7391:8000", uid=7390)
    await bank_h3.bank_transfer_execute(upd, SimpleNamespace(bot=tb))
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        ac2 = await users.get_by_tg(s, 7391)
        still_ok = ac1.bank_balance == 100
    tf_ans2 = [c for c in upd.callback_query.calls if c[0] == "answer"]
    check("موجودی تغییر کرده باشه تایید نهایی رد میشه",
          still_ok and tf_ans2 and "نداری" in str(tf_ans2[0][1]), str(tf_ans2[:1]))

    check("جاروی ورودی معلق، مراحل انتقال رو هم پوشش میده",
          "trf_to" in jobs_h2._NUMERIC_PENDING and "trf_amt" in jobs_h2._NUMERIC_PENDING)
    async with session_scope() as s:
        ac1 = await users.get_by_tg(s, 7390)
        users.set_pending(ac1, "trf_to", "")
        cmsg = await dog_svc.cancel_pending(s, ac1)
        tpclr = ac1.pending_action
        await s.commit()
    check("«لغو» وسط انتقال کار می‌کنه", tpclr is None and cmsg != "🤷 کاری در جریان نیس که")

    # ── پیام همگانی: رسانه (عکس/ویدیو/فایل) هم «به کی بفرستمش؟» می‌گیره ──
    async with session_scope() as s:
        bmu = await users.get_by_tg(s, 1001)
        users.set_pending(bmu, "bcast", None, 100)
        await s.commit()
    _med = SimpleNamespace(text=None, caption=None, message_id=77, calls=[],
                           chat=SimpleNamespace(id=100))

    async def _med_reply(text, **kw):
        _med.calls.append(("reply", text, kw))
        return _med
    _med.reply_html = _med_reply
    upd_med = SimpleNamespace(
        message=_med, effective_message=_med,
        effective_user=SimpleNamespace(id=1001, username="boss", first_name="باس"),
        effective_chat=SimpleNamespace(id=100, type="private"),
    )
    try:
        await pending_h.capture_bcast_media(upd_med, None)
    except Exception:
        pass
    async with session_scope() as s:
        bmu = await users.get_by_tg(s, 1001)
        med_cleared = bmu.pending_action is None
        await s.commit()
    check("عکس برای پیام همگانی هم واکنش می‌گیره و pending پاک میشه",
          med_cleared and _med.calls and "به کی بفرستمش؟" in _med.calls[0][1]
          and "broadcast_scope_kb".lower() not in str(_med.calls[0][2]).lower(),
          str(_med.calls[:1]))
    check("کیبورد دامنه همگانی به رسانه هم وصله",
          _med.calls and _med.calls[0][2].get("reply_markup") is not None)

    # ── تیم مخفی 👻 تاگل نامرئی لیدربرد ──
    async with session_scope() as s:
        rno = await users.get_by_tg(s, 7376)
        rteam = await team_svc.get_team_of(s, rno.id)
        rteam.points = 900_000_000_000
        rteam.week_points = 800_000_000_000
        rteam.bank = 700_000_000_000
        rno.medals = 99_000_000
        pre_vis = [t.id for t, _ in await team_svc.top_teams(s, 5)]
        pre_pts = [t.id for t, _ in await team_svc.top_teams_by_points(s, 5)]
        await s.commit()
    check("تیم گنده قبل از مخفی شدن صدر لیدربرد خزانه و امتیازه",
          bool(pre_vis) and pre_vis[0] == rn_id and bool(pre_pts) and pre_pts[0] == rn_id,
          f"{pre_vis[:3]}/{pre_pts[:3]}")
    async with session_scope() as s:
        rno = await users.get_by_tg(s, 7376)
        hok, hmsg = await team_svc.toggle_hidden(s, rno)
        hid_bank = [t.id for t, _ in await team_svc.top_teams(s, 50)]
        hid_pts = [t.id for t, _ in await team_svc.top_teams_by_points(s, 50)]
        hid_week = [t.id for t, _ in await team_svc.top_teams_week(s, 50)]
        hid_medals = [t.id for t, _, _ in await team_svc.top_teams_by_medals(s, "all", 50)]
        hid_medals_inc = [t.id for t, _, _ in await team_svc.top_teams_by_medals(s, "all", 50, include_hidden=True)]
        await s.commit()
    check("«تیم مخفی» تیم رو نامرئی کرد", hok and "نامرئی شد" in hmsg, hmsg[:60])
    check("تیم مخفی از لیدربرد خزانه و امتیاز و هفته حذف شد",
          rn_id not in hid_bank and rn_id not in hid_pts and rn_id not in hid_week)
    check("تیم مخفی تو مدال فقط با include_hidden دیده میشه",
          rn_id not in hid_medals and rn_id in hid_medals_inc)
    async with session_scope() as s:
        rno = await users.get_by_tg(s, 7376)
        hok3, hmsg3 = await team_svc.toggle_hidden(s, rno)
        back_bank = [t.id for t, _ in await team_svc.top_teams(s, 5)]
        back_pts = [t.id for t, _ in await team_svc.top_teams_by_points(s, 5)]
        await s.commit()
    check("دوباره «تیم مخفی» برش گردوند تو لیدربرد",
          hok3 and "برگشت تو لیدربردها" in hmsg3 and back_bank[0] == rn_id and back_pts[0] == rn_id, hmsg3[:50])

    # ── مخفی کردن تیم فقط دست ادمینه: عضو عادی رد میشه و وضعیت دست‌نخورده می‌مونه ──
    async with session_scope() as s:
        from models import Team as _TeamQ
        vis_before = (await s.get(_TeamQ, rn_id)).lb_hidden
        await s.commit()
    upd_mh = _text_update("تریاکی تیم مخفی", uid=7377, uname="memonly", fname="عضو ساده")
    await team_h.hide_team_text(upd_mh, None)
    async with session_scope() as s:
        from models import Team as _TeamQ2
        vis_after = (await s.get(_TeamQ2, rn_id)).lb_hidden
        await s.commit()
    check("مخفی کردن تیم فقط دست ادمینه، عضو عادی 🚫 می‌گیره و تیم دست‌نخورده می‌مونه",
          vis_before == vis_after
          and any("فقط دست ادمینه" in c[1] for c in upd_mh.message.calls),
          str(upd_mh.message.calls[-1][1][:60]) if upd_mh.message.calls else "-")

    # ── ادمین با اسم هر تیمی رو می‌تونه مخفی و برگردونه ──
    upd_ah = _text_update("تریاکی تیم مخفی قهرمانان", uid=1001, uname="باس", fname="باس")
    await team_h.hide_team_text(upd_ah, None)
    async with session_scope() as s:
        from models import Team as _TeamQ3
        hid1 = (await s.get(_TeamQ3, rn_id)).lb_hidden
        await s.commit()
    check("ادمین با اسم تیم مخفی می‌کنه",
          hid1 == 1 and any("نامرئی شد" in c[1] and "قهرمانان" in c[1] for c in upd_ah.message.calls),
          str(upd_ah.message.calls[-1][1][:60]) if upd_ah.message.calls else "-")
    upd_ah2 = _text_update("تریاکی تیم مخفی قهرمانان", uid=1001, uname="باس", fname="باس")
    await team_h.hide_team_text(upd_ah2, None)
    async with session_scope() as s:
        from models import Team as _TeamQ4
        hid2 = (await s.get(_TeamQ4, rn_id)).lb_hidden
        await s.commit()
    check("دوباره همون دستور برش می‌گردونه تو لیدربرد",
          hid2 == 0 and any("برگشت تو لیدربردها" in c[1] for c in upd_ah2.message.calls))
    upd_ah3 = _text_update("تریاکی تیم مخفی غیرموجود‌ها", uid=1001, uname="باس", fname="باس")
    await team_h.hide_team_text(upd_ah3, None)
    check("اسم تیم اشتباه خطای پیدا نکردم می‌ده",
          any("پیدا نکردم" in c[1] for c in upd_ah3.message.calls))
    check("پترن «تیم مخفی» ساده و با پیشوند و اسم کار می‌کنه",
          bool(pats["team_hide"].match("تیم مخفی")) and bool(pats["team_hide"].match("تریاکی تیم مخفی"))
          and bool(pats["team_hide"].match("تیم مخفی قهرمانان")))
    # اسم ناشناخته هم به هندلر میرسه ولی ادمین خطای «پیدا نکردم» می‌گیره، سیلنت رد نمیشه

    # ── کوئست‌های تیم: 8 تا، لول‌گیت و مقیاس‌خورده با جایزه بهبودیافته ──
    tq = {q["key"]: q for q in config.TEAM_QUESTS}
    check("تیم 8 کوئست روزانه داره (کشتن | برداشت | کاشت | معدن | غذا | جستجو | واریز بانک | کاروان)",
          len(config.TEAM_QUESTS) == 8
          and [q["key"] for q in config.TEAM_QUESTS] == ["kills", "harvest", "plant", "mine", "feed", "search", "depbank", "caravan"],
          str(list(tq)))
    check("ترتیب لول‌گیت کوئست‌های تیم 1 و 1 و 2 و 3 و 4 و 5 و 6 و 7ـه",
          [q["min_level"] for q in config.TEAM_QUESTS] == [1, 1, 2, 3, 4, 5, 6, 7])
    s1 = team_svc.team_quest_scaled(tq["kills"], 1)
    check("کوئست کش لول 1 همون مبناست با جایزه بیشتر",
          s1["target"] == 25 and s1["reward"] == 250 and s1["bank_reward"] == 2500,
          f"{s1['target']}/{s1['reward']}/{s1['bank_reward']}")
    s5m = team_svc.team_quest_scaled(tq["mine"], 5)
    check("کوئست معدن لول 5 دو پله رشد 40% خورد", s5m["target"] == 108, str(s5m["target"]))
    s10 = team_svc.team_quest_scaled(tq["kills"], 10)
    check("کوئست کش لول 10 سقف مقیاس با جایزه بهبودیافته",
          s10["target"] == 115 and s10["reward"] == 925 and s10["bank_reward"] == 9250,
          f"{s10['target']}/{s10['reward']}/{s10['bank_reward']}")
    check("تیایتل کوئست با عدد مقیاس‌خورده پر میشه", fa_num(115) in s10["title"], s10["title"])
    check("تیایتل کوئست بانک تیم هم مقیاس عددش پر میشه",
          fa_num(team_svc.team_quest_scaled(tq["depbank"], 6)["target"]) in team_svc.team_quest_scaled(tq["depbank"], 6)["title"])
    check("کوئست لول‌گیت برای تیم کم‌لول Noneـه", team_svc.team_quest_scaled(tq["mine"], 2) is None)
    check("لول 2 کوئست‌های معدن و غذا و جستجو و بانک و کاروان قفله",
          [q["key"] for q in team_svc.locked_quests_view(2)] == ["mine", "feed", "search", "depbank", "caravan"])
    td_view = TeamDaily(team_id=424242, day="2000-01-01", kills=0, harvests=0, kills_done=0, harvests_done=0)
    v8 = team_svc.quests_view(td_view, 8)
    v1 = team_svc.quests_view(td_view, 1)
    check("استعلام لول 8 هر 8 کوئست رو داره", len(v8) == 8, str(len(v8)))
    check("استعلام لول 1 فقط 2 کوئست باز داره",
          len(v1) == 2 and {q["key"] for q in v1} == {"kills", "harvest"}, str([q["key"] for q in v1]))
    check("شانس جایزه بذر افسانه‌ای کوئست تیم ۱۰٪ بعد لول 7ـه",
          config.TEAM_QUEST_LEGEND_CHANCE == 0.10 and config.TEAM_QUEST_LEGEND_MIN_LEVEL == 7
          and set(config.QUEST_LEGEND_SEEDS) == {"jahannam", "eblis"})

    async with session_scope() as s:
        qmo, _ = await users.get_or_create(s, tg(7378, "qmine", "معدنچی"))
        qmo.level = 8
        qmo.cash = 100000
        qok, _qn = await team_svc.create_team(s, qmo, "معدنچی‌ها")
        assert qok, _qn
        qteam = await team_svc.get_team_of(s, qmo.id)
        qteam.level = 3
        qd = await team_svc._daily(s, qteam.id)
        qd.qprog = _json.dumps({"mine": 59})
        q_bank_b, q_cash_b = qteam.bank, qmo.cash
        qnote = await team_svc.record_mine(s, qmo)
        qprog_after = _json.loads(qd.qprog or "{}")
        check("کوئست معدن تیم با ضربه 60اُم کامل شد و اعلان داد",
              qnote is not None and "کامل شد" in qnote and "کنده‌کاری" in qnote, str(qnote)[:70])
        check("جایزه عضو و بانک تیم با مقیاس لول 3 واریز شد",
              qmo.cash == q_cash_b + 300 and qteam.bank == q_bank_b + 3000,
              f"{qmo.cash - q_cash_b}/{qteam.bank - q_bank_b}")
        check("شمارنده JSON پیشرفت کوئست 60 شد", qprog_after.get("mine") == 60, str(qprog_after))
        await s.commit()

    # ── کوئست تیم: کاشت و غذا و واریز به بانک هم ثبت میشن + بذر افسانه‌ای برای لول 7+ ──
    async with session_scope() as s:
        qlo, _ = await users.get_or_create(s, tg(7384, "qleg", "خوش‌شانس"))
        qlo.level = 9
        qlo.cash = 100000
        ok_lq, _ = await team_svc.create_team(s, qlo, "برگ‌بخت‌ها")
        assert ok_lq
        qt2 = await team_svc.get_team_of(s, qlo.id)
        qt2.level = 8
        qd2 = await team_svc._daily(s, qt2.id)
        qd2.qprog = _json.dumps({"feed": 30, "plant": 60})  # تارگت لول 8: غذا 31 و کاشت 61
        cash_c0, bank_c0 = qlo.cash, qt2.bank
        _orig_tqr = team_svc.random.random
        try:
            team_svc.random.random = lambda: 0.0
            lnote = await team_svc.record_feed(s, qlo)
            team_svc.random.random = lambda: 0.5
            pnote = await team_svc.record_plant(s, qlo)
        finally:
            team_svc.random.random = _orig_tqr
        lg_stock = await farming.get_stock(s, qlo.id)
        cash_c1, bank_c1 = qlo.cash, qt2.bank
        dep1 = await team_svc.record_team_deposit(s, qlo, 25000)
        dep_mid = _json.loads((await team_svc._daily(s, qt2.id)).qprog or "{}").get("depbank")
        dep2 = await team_svc.record_team_deposit(s, qlo, 11000)  # تارگت واریز لول 8: 36,000
        qd2p = _json.loads((await team_svc._daily(s, qt2.id)).qprog or "{}")
        await s.commit()
    check("کوئست تیم لول 7+ با بخت به هر عضو بذر جهنم یا ابلیس داد و اعلانش کرد",
          lnote is not None and "بذر افسانه‌ای" in lnote
          and lg_stock.get("jahannam", 0) + lg_stock.get("eblis", 0) == 1, f"{lnote} | {lg_stock}")
    check("بدون بخت خط بذر افسانه‌ای تو اعلان نیس",
          pnote is not None and "کامل شد" in pnote and "بذر افسانه‌ای" not in pnote, str(pnote)[:80])
    check("جایزه‌های مقیاس‌شده غذا و کاشت و واریز (لول 8) واریز شدن",
          cash_c1 == cash_c0 + 770 + 840 and bank_c1 == bank_c0 + 7700 + 8400
          and qlo.cash == cash_c1 + 800 and qt2.bank == bank_c1 + 8000,
          f"{qlo.cash}/{qt2.bank}")
    check("واریز بانک تیم تو شمارنده کوئست جمع میشه و زیر تارگت اعلان نداره",
          dep1 is None and dep_mid == 25000 and qd2p.get("depbank") == 36000,
          f"{dep_mid}/{qd2p.get('depbank')}")
    check("رسیدن به تارگت واریز، کوئست بانک رو کامل می‌کنه و جایزه مقیاس‌شده میده",
          dep2 is not None and "کامل شد" in dep2 and "واریز" in dep2
          and qlo.cash == cash_c1 + 800 and qt2.bank == bank_c1 + 8000,
          f"{dep2} | {qt2.bank}")

    # ── روستر: اسم‌ها بر اساس لول از بالا به پایین ──
    async with session_scope() as s:
        r1u, _ = await users.get_or_create(s, tg(7385, "ros1", "کم‌لولی"))
        r1u.level = 8
        r1u.cash = 100000
        ok_r, _ = await team_svc.create_team(s, r1u, "روستری‌ها")
        assert ok_r, _
        r1u.level = 3
        r2u, _ = await users.get_or_create(s, tg(7386, "ros2", "بالالولی"))
        r2u.level = 9
        r3u, _ = await users.get_or_create(s, tg(7387, "ros3", "وسطولی"))
        r3u.level = 6
        _rt = await team_svc.get_team_of(s, r1u.id)
        s.add(TeamMember(team_id=_rt.id, user_id=r2u.id, role="member"))
        s.add(TeamMember(team_id=_rt.id, user_id=r3u.id, role="member"))
        await s.commit()
    upd_ros = _text_update("تریاکی تیم عضویت", uid=7385, uname="ros1", fname="کم‌لولی")
    await team_h.roster_text(upd_ros, None)
    ros_t = upd_ros.message.calls[-1][1] if upd_ros.message.calls else ""
    check("روستر بر اساس لول از بالا به پایین مرتبه",
          ros_t and ros_t.index("بالالولی") < ros_t.index("وسطولی") < ros_t.index("کم‌لولی"),
          ros_t.replace("\n", " | ")[:130])

    # ── کوئست روزانه بازیکن: مقیاس لول و گیت تنوع ──
    check("کوئست معدن بازیکن لول 10 با رشد مقیاس خورد",
          quests_svc.scaled_values("mine", 10) == (38, 936, 94), str(quests_svc.scaled_values("mine", 10)))
    check("کوئست معدن بازیکن لول 1 همون مبناست", quests_svc.scaled_values("mine", 1) == (20, 450, 45))
    async with session_scope() as s:
        pqu, _ = await users.get_or_create(s, tg(7379, "pq1", "تازه‌کار"))
        pqu.level = 1
        pqu.dq_date = None
        pqu.dq_data = None
        pqs = await quests_svc.ensure_quests(s, pqu)
        await s.commit()
    check("استخر کوئست لول 1 فقط حمله و معدنه",
          bool(pqs) and all(q["kind"] in ("attack", "mine") for q in pqs), str([q["kind"] for q in pqs]))
    async with session_scope() as s:
        pqh, _ = await users.get_or_create(s, tg(7380, "pq6", "با‌سابقه"))
        pqh.level = 6
        pqh.dq_date = None
        pqh.dq_data = None
        pqs6 = await quests_svc.ensure_quests(s, pqh)
        await s.commit()
    check("هدف کوئست‌های ساخته‌شده با لول کاربر مقیاس خورده",
          bool(pqs6) and all(q["target"] == quests_svc.scaled_values(q["kind"], 6)[0] for q in pqs6),
          str(pqs6[:1]))

    # ── کوئست روزانه: جایزه بذر جهنم/ابلیس با شانس ۱۰٪ بعد لول 10 ──
    _orig_dqr = quests_svc.random.random
    try:
        quests_svc.random.random = lambda: 0.90
        r_low9 = quests_svc._roll_reward("mine", 9)
        r_high12 = quests_svc._roll_reward("mine", 12)
        quests_svc.random.random = lambda: 0.96
        r_out12 = quests_svc._roll_reward("mine", 12)
    finally:
        quests_svc.random.random = _orig_dqr
    check("کوئست روزانه زیر لول 10 هیچ‌وقت جهنم/ابلیس نمی‌ده",
          r_low9["type"] == "seed" and r_low9["seed"] not in ("jahannam", "eblis"), str(r_low9))
    check("کوئست روزانه بعد لول 10 تو برش ۱۰٪ جهنم یا ابلیس می‌ده",
          r_high12["type"] == "seed" and r_high12["seed"] in ("jahannam", "eblis"), str(r_high12))
    check("بیرون برش ۱۰٪ حتی بعد لول 10 هم بذر معمولی می‌ده",
          r_out12["type"] == "seed" and r_out12["seed"] not in ("jahannam", "eblis")
          and "mutant" != r_out12["seed"], str(r_out12))
    check("ثابت‌های بذر افسانه‌ای روزانه ۱۰٪ بعد لول 10 و بدون جهش‌یافته",
          config.DAILY_QUEST_LEGEND_CHANCE == 0.10 and config.DAILY_QUEST_LEGEND_MIN_LEVEL == 10)

    # ── دیبانس کلیک کاروان ──
    world_svc.CARAVAN_CLICKS.clear()
    spam1 = world_svc.caravan_click_spam(-100777, 7381)
    spam2 = world_svc.caravan_click_spam(-100777, 7381)
    spam3 = world_svc.caravan_click_spam(-100777, 7382)
    check("کلیک تندتند دوم اسپمه ولی دیبانس به ازای هر کاربره",
          spam1 is False and spam2 is True and spam3 is False, f"{spam1}/{spam2}/{spam3}")

    # هندلر: ضربه اول جواب دمیج می‌گیره، کلیک تندتند بعدی فقط جواب خالی
    world_svc.CARAVAN_CLICKS.clear()
    world_svc.caravan_spawn(-100777)["hp"] = 9_999_999
    async with session_scope() as s:
        cvu, _ = await users.get_or_create(s, tg(7383, "cvh", "کاروان‌زن"))
        cvu.level = 10
        await s.commit()

    def _cv_update(uid):
        q = _CBQ(data="cv:hit", message=SimpleNamespace(photo=None, chat_id=-100777, message_id=42), calls=[])
        async def _mr(text, **k):
            q.calls.append(("reply", text, k))
            return q.message
        q.message.reply_html = _mr
        return SimpleNamespace(
            callback_query=q, message=q.message, effective_message=q.message,
            effective_user=SimpleNamespace(id=uid, username="cvh", first_name="کاروان‌زن"),
            effective_chat=SimpleNamespace(id=-100777, type="supergroup"),
        )

    upd = _cv_update(7383)
    await world_h.caravan_hit_cb(upd, None)
    a1 = [c for c in upd.callback_query.calls if c[0] == "answer"]
    check("ضربه اول به کاروان جواب دمیج داد", bool(a1) and "دمیج" in str(a1[0][1]), str(a1[:1])[:70])
    upd2 = _cv_update(7383)
    await world_h.caravan_hit_cb(upd2, None)
    check("کلیک تندتند دوم فقط جواب خالی گرفت (دیبانس 2 ثانیه)",
          len(upd2.callback_query.calls) == 1 and upd2.callback_query.calls[0][0] == "answer"
          and not upd2.callback_query.calls[0][1] and not upd2.callback_query.calls[0][2],
          str(upd2.callback_query.calls[:2]))
    del world_svc.CARAVANS[-100777]
    world_svc.CARAVAN_CLICKS.clear()
    world_svc.CARAVAN_HITS.pop((-100777, 7383), None)

    # ── متن کولدان جستجو، قالب تبلیغاتی درخواستی ──
    sct = world_svc.search_cooldown_text(300)
    check("متن کولدان جستجو قالب دقیق درخواستی رو داره",
          all(x in sct for x in [f"⏳ هر {fa_num(10)} دقیقه یک بار میتونی جستجو بزنی", "دیگه برگرد",
                                 "🔥 تریاکی | یه محله‌ست که تو باید پادشاهش بشی",
                                 "زمین بخر، بذر بکار، کنده‌کاری کن، سلاح بگیر و به رقیبات حمله کن",
                                 "با دوستات تیم بزن و تو رقابت‌های گروهی شرکت کن",
                                 "بزن Start و رایگان شروع کن 🚀"]),
          sct[:70])
    check("کولدان جستجو 10 دقیقه‌ست", config.SEARCH_COOLDOWN_MINUTES == 10)

    # ═════════ بچ جدید: سلاح‌های ویژه + مهارت + لقب + تجهیزات + منوی جدید + ادمین تیم + خرید بذر تعدادی + کارخونه گران‌تر + انبار بزرگ‌تر ═════════

    # ── باز شدن سلاح‌های ویژه تو متن لول‌آپ ──
    async with session_scope() as s:
        lv16u, _ = await users.get_or_create(s, tg(9871, "ulvl16", "شانزدهی"))
        lv16u.level, lv16u.xp = 15, 0
        n16 = users.add_xp(lv16u, economy.xp_need(15))
        _j16 = "\n".join(n16 or [])
        check("لول 16 اولین سلاح ویژه Viper-X رو باز می‌کنه",
              "🔓 آیتم های جدید باز شدن" in _j16 and "💀 Viper-X" in _j16, _j16[:130])
        lv16u.level, lv16u.xp = 19, 0
        n20 = users.add_xp(lv16u, economy.xp_need(19))
        _j20 = "\n".join(n20 or [])
        check("لول 20 هم Oblivion باز میشه هم پیام لول مکس",
              "👑 Oblivion" in _j20 and "👑 لولت مکس شد" in _j20, _j20[:170])
        await s.commit()

    # ── بخش سلاح ویژه تو شاپ ──
    sw_kb = kb3.shop_weap_kb(SimpleNamespace(level=20), set(), "special")
    sw_txt = [b.text for row in sw_kb.inline_keyboard for b in row]
    _sp_names = [config.WEAPONS[k]["name"] for k in ("viperx", "hellfire", "vampire", "shadowfang", "oblivion")]
    check("بخش سلاح ویژه هر پنج سلاح رو سبز و قابل خرید نشون میده",
          sum(1 for t in sw_txt if t in _sp_names) == 5, str(sw_txt))
    sl_kb = kb3.shop_weap_sections_kb(SimpleNamespace(level=15))
    sec_lock = [(b.text, b.style) for row in sl_kb.inline_keyboard for b in row if "ویژه" in b.text]
    check("سکشن سلاح ویژه زیر لول 16 با قفل قرمزه",
          sec_lock and sec_lock[0][1] == "danger" and "به لول 16" in sec_lock[0][0], str(sec_lock))
    sl_kb16 = kb3.shop_weap_sections_kb(SimpleNamespace(level=16))
    sec_open = [(b.text, b.callback_data, b.style) for row in sl_kb16.inline_keyboard for b in row if "ویژه" in b.text]
    check("روی لول 16 سکشن ویژه سبز باز میشه",
          sec_open and sec_open[0][1] == "shop:sec:wspecial" and sec_open[0][2] == "success", str(sec_open))

    # ── بتل: قابلیت‌های پنج سلاح ویژه (نبرد واقعی با دمیج سنجیده‌شده) ──
    _orig_roll = battle_svc.roll_damage
    _orig_night = battle_svc._is_night
    _orig_rand = battle_svc.random
    _orig_pchance = config.POISON_CHANCE
    battle_svc.roll_damage = lambda atk, dfn, vm: (50, False)
    from models import InventoryItem as _InvB
    async with session_scope() as s:
        await world_svc._meta_set(s, "weather_key", "normal")
        await world_svc._meta_set(s, "weather_until", (now_utc() + timedelta(seconds=7200)).isoformat())
        aw1, _ = await users.get_or_create(s, tg(9887, "abilatk", "ابیلیتی‌زن"))
        aw1.level = 16
        vi1, _ = await users.get_or_create(s, tg(9888, "abilv1", "طعمه‌یک"))
        vi1.level = 3
        lo1, _ = await users.get_or_create(s, tg(9889, "abilv2", "طعمه‌دو"))
        lo1.level = 5
        s.add(_InvB(user_id=aw1.id, item_key="viperx", level=1))
        await s.commit()

        def _reset_hit(att, vic):
            att.last_attack_at = None
            att.energy = config.MAX_ENERGY
            att.dead_until = None
            vic.dead_until = None

        # 💀 سم با شانس ۱۰۰٪
        config.POISON_CHANCE = 1.0
        _reset_hit(aw1, vi1)
        vi1.hp = battle_svc.max_hp(vi1.level)
        res_p = await battle_svc.execute_hit(s, aw1, vi1)
        check("💀 سم Viper-X اثر می‌گیره و تا ۱۰ دقیقه طرف مسمومه",
              res_p["ok"] and any("💀" in l and "Viper-X" in l for l in res_p["abil_lines"])
              and vi1.poison_until is not None and vi1.poison_until > now_utc(),
              str(res_p.get("abil_lines")))
        await s.flush()

        # اثر سم روی دفاع (با پاک کردن و برگردوندن سم، قبل/بعد سنجیده میشه)
        poisoned_until = vi1.poison_until
        vi1.poison_until = None
        _, dfn_base, _ = await battle_svc.battle_powers(s, aw1, vi1)
        vi1.poison_until = poisoned_until
        _, dfn_pois, info_p2 = await battle_svc.battle_powers(s, aw1, vi1)
        check("قربانی مسموم 15% دفاعش کمتره",
              dfn_pois == max(1, int(dfn_base * (1 - config.POISON_CUT))) and info_p2.get("poison_target") is True,
              f"{dfn_base}->{dfn_pois}")
        atk_self, _, info_self = await battle_svc.battle_powers(s, vi1, aw1)
        atk_self_clean = None
        vi1.poison_until = None
        atk_clean, _, _ = await battle_svc.battle_powers(s, vi1, aw1)
        vi1.poison_until = poisoned_until
        check("طرف مسموم وقتی حمله می‌کنه هم 15% ضعیف‌تره",
              info_self.get("poison_self") is True and atk_self == max(1, int(atk_clean * (1 - config.POISON_CUT))),
              f"{atk_clean}->{atk_self}")
        await s.commit()

        # 🔥 هفایر روی حریف زیر 30% سلامت
        aw1.equipped_weapon = "hellfire"
        s.add(_InvB(user_id=aw1.id, item_key="hellfire", level=1))
        await s.flush()
        _reset_hit(aw1, lo1)
        lo1.hp = int(0.29 * battle_svc.max_hp(lo1.level))
        res_h = await battle_svc.execute_hit(s, aw1, lo1)
        check("🔥 Hellfire به حریف نیمه‌جان (زیر 30%) دمیج 10% بیشتر می‌زنه",
              res_h["ok"] and res_h["dmg"] == max(1, round(50 * (1 + config.HELLFIRE_BONUS * 1)))
              and any("🔥" in l and "Hellfire" in l for l in res_h["abil_lines"]),
              f"{res_h.get('dmg')} {res_h.get('abil_lines')}")
        _reset_hit(aw1, lo1)
        lo1.hp = battle_svc.max_hp(lo1.level)
        res_h0 = await battle_svc.execute_hit(s, aw1, lo1)
        check("حریف سالم (بالای 30%) بونس هفایر نمی‌گیره",
              res_h0["ok"] and res_h0["dmg"] == 50 and not any("🔥" in l for l in res_h0["abil_lines"]),
              str(res_h0.get("abil_lines")))

        # رشد درصد قابلیت با لول ارتقای سلاح (لول 5 → ×1.8)
        growth5 = 1 + config.SPECIAL_ABILITY_GROWTH * (5 - 1)
        inh5 = (await s.execute(select(_InvB).where(_InvB.user_id == aw1.id, _InvB.item_key == "hellfire"))).scalar_one()
        inh5.level = 5
        await s.flush()
        _reset_hit(aw1, lo1)
        lo1.hp = int(0.29 * battle_svc.max_hp(lo1.level))
        res_h5 = await battle_svc.execute_hit(s, aw1, lo1)
        check("با لول ارتقای سلاح درصد قابلیت بیشتر میشه (لول 5 → ×1.8)",
              res_h5["ok"] and res_h5["dmg"] == max(1, round(50 * (1 + config.HELLFIRE_BONUS * growth5)))
              and any("18%" in l for l in res_h5["abil_lines"]),
              f"{res_h5.get('dmg')} {res_h5.get('abil_lines')}")
        inh5.level = 1

        # 🩸 وامپایر بخشی از سلامت رو برمی‌گردونه
        aw1.equipped_weapon = "vampire"
        s.add(_InvB(user_id=aw1.id, item_key="vampire", level=1))
        await s.flush()
        hp_max_a = battle_svc.max_hp(aw1.level)
        aw1.hp = hp_max_a - 100
        _reset_hit(aw1, lo1)
        aw1.hp = hp_max_a - 100
        lo1.hp = battle_svc.max_hp(lo1.level)
        res_v = await battle_svc.execute_hit(s, aw1, lo1)
        check("🩸 Vampire ده درصد دمیج رو به سلامت خودم برمی‌گردونه",
              res_v["ok"] and aw1.hp == hp_max_a - 100 + max(0, round(50 * config.VAMPIRE_LEECH * 1))
              and any("🩸" in l and "Vampire" in l for l in res_v["abil_lines"]),
              f"{aw1.hp} {res_v.get('abil_lines')}")
        _reset_hit(aw1, lo1)
        aw1.hp = hp_max_a - 3
        lo1.hp = battle_svc.max_hp(lo1.level)
        res_v2 = await battle_svc.execute_hit(s, aw1, lo1)
        check("هیل وامپایر از سقف HP رد نمیشه", res_v2["ok"] and aw1.hp == hp_max_a, str(aw1.hp))

        # 🌑 شدوفنگ فقط شبانه
        aw1.equipped_weapon = "shadowfang"
        s.add(_InvB(user_id=aw1.id, item_key="shadowfang", level=1))
        await s.flush()
        battle_svc._is_night = lambda: True
        _reset_hit(aw1, lo1)
        lo1.hp = battle_svc.max_hp(lo1.level)
        res_sh = await battle_svc.execute_hit(s, aw1, lo1)
        check("🌑 Shadow Fang شبانه (18 تا 4) دمیج 20% بیشتر می‌زنه",
              res_sh["ok"] and res_sh["dmg"] == max(1, round(50 * (1 + config.SHADOW_BONUS * 1)))
              and any("🌑" in l and "Shadow Fang" in l for l in res_sh["abil_lines"]),
              f"{res_sh.get('dmg')} {res_sh.get('abil_lines')}")
        battle_svc._is_night = lambda: False
        _reset_hit(aw1, lo1)
        lo1.hp = battle_svc.max_hp(lo1.level)
        res_d = await battle_svc.execute_hit(s, aw1, lo1)
        check("روز شدوفنگ هیچ بونسی نداره",
              res_d["ok"] and res_d["dmg"] == 50 and not any("🌑" in l for l in res_d["abil_lines"]),
              str(res_d.get("abil_lines")))

        # 👑 ابلیویون: هر ضربه یه قابلیت رندوم از چهارتا
        aw1.equipped_weapon = "oblivion"
        s.add(_InvB(user_id=aw1.id, item_key="oblivion", level=1))
        await s.flush()
        battle_svc.random = SimpleNamespace(
            choice=lambda seq: "hellfire", random=random.random, uniform=random.uniform)
        _reset_hit(aw1, lo1)
        lo1.hp = int(0.29 * battle_svc.max_hp(lo1.level))
        res_o = await battle_svc.execute_hit(s, aw1, lo1)
        check("👑 Oblivion هر بار یه قابلیت رندوم فعال می‌کنه و خط قابلیت اسم خودشو میاره",
              res_o["ok"] and any(l.startswith("👑 Oblivion این بار:") for l in res_o["abil_lines"]),
              str(res_o.get("abil_lines")))
        battle_svc.random = _orig_rand
        battle_svc._is_night = _orig_night

        # 💰 مهارت غارت روی غارت ضربه (8 لول → 24% بیشتر)
        # ابلیویون هنوز دستشه و رندوم واقعی فعاله، به قابلیت هلفایر قفلش می‌کنیم
        # (هدف HP کامل داره پس هیچ قابلیتی فایر نمیشه و دمیج دقیقاً 50 می‌مونه، مستقل از رندوم و ساعت شب/روز)
        aw1.skill_loot = 8
        xp_att = aw1.xp
        battle_svc.random = SimpleNamespace(
            choice=lambda seq: "hellfire", random=random.random, uniform=random.uniform)
        _reset_hit(aw1, lo1)
        lo1.hp = battle_svc.max_hp(lo1.level)
        lo1.cash = 10000
        pre_cash = lo1.cash
        res_lt = await battle_svc.execute_hit(s, aw1, lo1)
        battle_svc.random = _orig_rand
        exp_steal = int(int(pre_cash * config.BATTLE_STEAL_MAX_PCT
                            * min(1.0, 50 / battle_svc.max_hp(lo1.level))) * (1 + 0.03 * 8))
        check("مهارت غارت مبلغ دزدی هر ضربه رو بیشتر می‌کنه",
              res_lt["ok"] and res_lt["steal"] == exp_steal and res_lt["steal"] > 0,
              f"{res_lt.get('steal')} vs {exp_steal}")
        aw1.skill_loot = 0
        await s.commit()
    battle_svc.roll_damage = _orig_roll
    config.POISON_CHANCE = _orig_pchance
    check("ثابت‌های قابلیت ویژه",
          config.SPECIAL_ABILITY_GROWTH == 0.20 and config.POISON_CUT == 0.15 and config.POISON_SECONDS == 600
          and config.HELLFIRE_THRESHOLD == 0.30 and config.VAMPIRE_LEECH == 0.10
          and config.SHADOW_BONUS == 0.20 and config.SHADOW_NIGHT_FROM == 18 and config.SHADOW_NIGHT_TO == 4)
    check("متن هر پنج قابلیت ویژه تو کانفیگ هست",
          set(config.WEAPON_ABILITY_TEXT) == {"poison", "hellfire", "vampire", "shadow", "oblivion"})

    # ── مهارت‌ها: خدمات پایه ──
    async with session_scope() as s:
        sk1, _ = await users.get_or_create(s, tg(9893, "skiller", "مهارتی"))
        sk1.level = 6
        sk1.skill_points = None
        sk1.skill_power = None
        sk1.skill_speed = None
        sk1.skill_defense = None
        sk1.skill_loot = None
        users.ensure_skills(sk1)
        check("امتیاز مهارت پس‌دررو برای کاربر قدیمی = لول منهای یک",
              sk1.skill_points == 5 and all(getattr(sk1, f"skill_{k}") == 0 for k in config.SKILLS),
              str(sk1.skill_points))
        ok_s1, _ = users.spend_skill_point(sk1, "power")
        check("خرج یه امتیاز مهارت، لول قابلیت رو بالا می‌بره",
              ok_s1 and sk1.skill_power == 1 and sk1.skill_points == 4)
        check("هر لول قدرت دو درصده", combat.skill_pct(sk1, "power") == 0.02)
        sk1.skill_power = config.SKILL_MAX_LEVEL
        ok_s2, why_s2 = users.spend_skill_point(sk1, "power")
        check("قابلیت بیشتر از لول 8 بالا نمیره", not ok_s2 and "مکس" in why_s2)
        sk1.skill_power = 0
        sk1.skill_points = 0
        ok_s3, _ = users.spend_skill_point(sk1, "speed")
        check("بدون امتیاز مهارت رد میشه", not ok_s3)
        sk1.skill_points = 12
        sk1.skill_power, sk1.skill_speed, sk1.skill_defense, sk1.skill_loot = 4, 2, 1, 1
        sk1.cash = 100
        ok_r0, why_r0 = users.reset_skills(sk1)
        check("ریست بدون 25,000 تی‌پوینت رد میشه و قیمتش تو کانفیگه",
              not ok_r0 and config.SKILL_RESET_COST == 25000)
        sk1.cash = 30000
        ok_r, back_r = users.reset_skills(sk1)
        check("ریست همه امتیازهای خرج‌شده رو برمی‌گردونه و صفر می‌کنه",
              ok_r and back_r == 8 and sk1.skill_points == 20 and sk1.cash == 30000 - 25000
              and all(users.skill_level(sk1, k) == 0 for k in config.SKILLS), f"back={back_r}")
        ok_r2, _ = users.reset_skills(sk1)
        check("ریست دوم وقتی چیزی خرج نشده رد میشه", not ok_r2)
        await s.commit()

    # ── مهارت‌ها تو استت و کولدان نبرد ──
    async with session_scope() as s:
        sk1 = await users.get_by_tg(s, 9893)
        sk1.skill_power = 8
        a8, d8 = combat.combat_stats(sk1, {}, [])
        check("8 لول قدرت، حمله رو 16% می‌بره بالا",
              a8 == int((config.ATK_BASE + config.ATK_PER_LEVEL * sk1.level) * 1.16),
              f"{a8} base={config.ATK_BASE + config.ATK_PER_LEVEL * sk1.level}")
        sk1.skill_power = 0
        sk1.skill_defense = 8
        _, d8b = combat.combat_stats(sk1, {}, [])
        check("8 لول دفاع، دفاع رو 16% می‌بره بالا",
              d8b == int((config.DEF_BASE + config.DEF_PER_LEVEL * sk1.level) * 1.16), str(d8b))
        sk1.skill_defense = 0
        sk1.skill_speed = 8
        sk1.last_attack_at = now_utc()
        left8 = await battle_svc.cooldown_left(s, sk1)
        sk1.skill_speed = 0
        left0 = await battle_svc.cooldown_left(s, sk1)
        check("8 لول سرعت کولدان 30 ثانیه رو 16% کمتر می‌کنه",
              left8 < left0 and left8 <= int(config.BATTLE_COOLDOWN_SECONDS * 0.84),
              f"{left8}/{left0}")
        sk1.last_attack_at = None
        await s.commit()

    # ── مهارت تو لول‌آپ ──
    async with session_scope() as s:
        skx, _ = await users.get_or_create(s, tg(9894, "lvskill", "لول‌آپی"))
        skx.level, skx.xp = 1, 0
        notes_x = users.add_xp(skx, economy.xp_need(1))
        check("هر لول‌آپ 1 امتیاز مهارت میده و خبرش میاد",
              skx.skill_points == 1 and any("🎖" in n and "امتیاز مهارت" in n for n in notes_x),
              str(skx.skill_points))
        skx.xp = 0
        users.add_xp(skx, economy.xp_need(2))
        check("امتیازها با هر لول جمع میشن", skx.skill_points == 2, str(skx.skill_points))
        await s.commit()

    # ── صفحه مهارت و هندلرها ──
    from handlers import skills as skills_h
    from handlers import gear as gear_h
    async with session_scope() as s:
        ge, _ = await users.get_or_create(s, tg(9896, "skillpage", "صفحه‌ای"))
        ge.level = 15
        ge.skill_points = 3
        ge.cash = 30000
        await s.commit()
    upd_mk = _fake_update("menu:skills", uid=9896)
    await skills_h.skills_cb(upd_mk, None)
    ed_mk = next((c for c in upd_mk.callback_query.calls if c[0] == "edit"), None)
    check("صفحه مهارت: هدر، شمار امتیاز و چهار قابلیت",
          ed_mk is not None and "<b>⭐️ مهارت‌ها</b>" in ed_mk[1] and "🎖 امتیاز مهارت: 3" in ed_mk[1]
          and all(config.SKILLS[k]["name"] in ed_mk[1] for k in ("power", "speed", "defense", "loot")),
          ed_mk[1][:150] if ed_mk else "-")
    mk_datas = {(b.callback_data) for row in ed_mk[2]["reply_markup"].inline_keyboard for b in row}
    check("دکمه‌های صفحه مهارت‌ها",
          all(f"sk:up:{k}" in mk_datas for k in config.SKILLS) and "sk:reset" in mk_datas, str(mk_datas))
    upd_su = _fake_update("sk:up:power", uid=9896)
    await skills_h.skill_up_cb(upd_su, None)
    async with session_scope() as s:
        ge = await users.get_by_tg(s, 9896)
        check("دکمه بعلاوه قدرت، امتیاز خرج می‌کنه و لولش بالا میره",
              ge.skill_power == 1 and ge.skill_points == 2,
              f"{ge.skill_power}/{ge.skill_points}")
        await s.commit()
    check("الرت سبز ارتقای مهارت",
          any(c[0] == "answer" and c[1] and "قدرت" in str(c[1][0]) for c in upd_su.callback_query.calls),
          str(upd_su.callback_query.calls)[:120])
    upd_sr = _fake_update("sk:reset", uid=9896)
    await skills_h.skill_reset_confirm(upd_sr, None)
    ed_sr = next((c for c in upd_sr.callback_query.calls if c[0] == "edit"), None)
    sr_datas = {b.callback_data for row in ed_sr[2]["reply_markup"].inline_keyboard for b in row} if ed_sr else set()
    check("تأییدیه ریست مهارت با هزینه 25,000",
          ed_sr is not None and "ریست مهارت" in ed_sr[1] and "25,000" in ed_sr[1] and "cf:sk:reset" in sr_datas,
          ed_sr[1][:120] if ed_sr else "-")
    upd_cfr = _fake_update("cf:sk:reset", uid=9896)
    await skills_h.skill_reset_execute(upd_cfr, None)
    async with session_scope() as s:
        ge = await users.get_by_tg(s, 9896)
        check("تایید ریست: امتیاز برمی‌گرده و پول کم میشه",
              ge.skill_power == 0 and ge.skill_points == 3 and ge.cash == 30000 - 25000,
              f"{ge.skill_points}/{ge.cash}")
        await s.commit()

    # ── لقب‌ها ──
    check("لقب روی مرزها درسته",
          users.title_of(SimpleNamespace(level=1)) == ("🌱", "Newbie")
          and users.title_of(SimpleNamespace(level=2)) == ("🥉", "Rookie")
          and users.title_of(SimpleNamespace(level=3)) == ("🥉", "Rookie")
          and users.title_of(SimpleNamespace(level=4)) == ("🔹", "Member")
          and users.title_of(SimpleNamespace(level=19)) == ("☠️", "Godfather")
          and users.title_of(SimpleNamespace(level=20)) == ("💎", "Drug Lord"), str(users.title_of(SimpleNamespace(level=4))))
    check("جدول لقب 11 ردیف و سر جاش از لول 1 تا 20",
          len(config.TITLES) == 11 and config.TITLES[0][0] == 1 and config.TITLES[-1][0] == 20
          and all(config.TITLES[i][0] < config.TITLES[i + 1][0] for i in range(10)))

    # ── پروفایل: خط لقب و لقب لیدربرد ──
    async with session_scope() as s:
        pft, _ = await users.get_or_create(s, tg(9895, "proftit", "لقبی"))
        pft.level = 20
        cap_t = await profile_h2._profile_caption(s, pft)
        await s.commit()
    check("پروفایل خط «🏅 ایموجی لقب» داره",
          "🏅 💎 Drug Lord" in cap_t and "<b>🛡 تجهیزات</b>" in cap_t and "<b>💰 دارایی</b>" in cap_t,
          cap_t.splitlines()[4] if cap_t else "-")

    # ── تجهیزات: انتخاب سلاح و زره فعال ──
    async with session_scope() as s:
        gw, _ = await users.get_or_create(s, tg(9897, "gearw", "گیری"))
        gw.level = 8
        from models import InventoryItem as _InvG
        s.add(_InvG(user_id=gw.id, item_key="knife", level=1))
        s.add(_InvG(user_id=gw.id, item_key="colt", level=1))
        s.add(_InvG(user_id=gw.id, item_key="jacket", level=1))
        s.add(_InvG(user_id=gw.id, item_key="kevlar", level=1))
        await s.commit()
        gw = await users.get_by_tg(s, 9897)
        lv_g = await users.get_item_levels(s, gw.id)
        check("بدون تجهیز دستی، بهترین سلاح و زره خودکار انتخاب میشن",
              combat.weapon_choice(gw, lv_g) == "colt" and combat.armor_choice(gw, lv_g) == "kevlar")
        atk_best, dfn_best = combat.combat_stats(gw, lv_g, [])
        await s.commit()
    upd_gw = _fake_update("menu:gear", uid=9897)
    await gear_h.gear_cb(upd_gw, None)
    ed_gw = next((c for c in upd_gw.callback_query.calls if c[0] == "edit"), None)
    check("صفحه تجهیزات: هدر، استت و سلاح/زره فعال",
          ed_gw is not None and "<b>🛡 تجهیزات</b>" in ed_gw[1]
          and "🔫 سلاح فعال: کلت کمری 🔫" in ed_gw[1] and "🦺 زره فعال: جلیقه کِولار" in ed_gw[1]
          and "💪 حمله:" in ed_gw[1] and "🛡 دفاع:" in ed_gw[1],
          ed_gw[1][:160] if ed_gw else "-")
    gw_datas = {b.callback_data for row in ed_gw[2]["reply_markup"].inline_keyboard for b in row}
    check("دکمه‌های تجهیزات: تب‌ها، برداشتن هر آیتم و آپگرید",
          {"gear:tab:weap", "gear:tab:arm", "gear:upg", "gear:eq:weap:knife", "gear:eq:weap:colt"} <= gw_datas,
          str(gw_datas))
    upd_tab = _fake_update("gear:tab:arm", uid=9897)
    await gear_h.gear_tab_cb(upd_tab, None)
    ed_tab = next((c for c in upd_tab.callback_query.calls if c[0] == "edit"), None)
    check("تب زره‌ها لیست زره‌ها رو نشون میده",
          ed_tab is not None and "gear:eq:arm:kevlar" in
          {b.callback_data for row in ed_tab[2]["reply_markup"].inline_keyboard for b in row},
          ed_tab[1][:80] if ed_tab else "-")
    upd_eq = _fake_update("gear:eq:weap:knife", uid=9897)
    await gear_h.gear_equip_cb(upd_eq, None)
    async with session_scope() as s:
        gw = await users.get_by_tg(s, 9897)
        lv_g2 = await users.get_item_levels(s, gw.id)
        check("تجهیز چاقو ذخیره میشه و مبنای نبرد قرار می‌گیره (هرچند ضعیف‌تره)",
              gw.equipped_weapon == "knife" and combat.weapon_choice(gw, lv_g2) == "knife", gw.equipped_weapon)
        atk_weak, _ = combat.combat_stats(gw, lv_g2, [])
        check("استت با سلاح ضعیف‌ترِ تجهیزشده کمتره", atk_weak < atk_best, f"{atk_weak}<{atk_best}")
        await s.commit()
    ed_eq = next((c for c in upd_eq.callback_query.calls if c[0] == "edit"), None)
    check("بعد تجهیز، تیک ✅ میوفته رو آیتم",
          ed_eq is not None and "🔫 سلاح فعال: 🔪 چاقو" in ed_eq[1], ed_eq[1][:120] if ed_eq else "-")
    check("الرت تجهیز نشون میده",
          any(c[0] == "answer" and c[1] and "دستت شد" in str(c[1][0]) for c in upd_eq.callback_query.calls))
    upd_eq_none = _fake_update("gear:eq:weap:rpg", uid=9897)
    await gear_h.gear_equip_cb(upd_eq_none, None)
    check("تجهیز آیتمی که نداری رد میشه",
          any(c[0] == "answer" and c[1] and "نداری" in str(c[1][0]) for c in upd_eq_none.callback_query.calls),
          str([c for c in upd_eq_none.callback_query.calls if c[0] == "answer"])[:120])
    upd_un = _fake_update("gear:un:weap", uid=9897)
    await gear_h.gear_unequip_cb(upd_un, None)
    async with session_scope() as s:
        gw = await users.get_by_tg(s, 9897)
        check("👊 دست خالی، انتخاب خودکار دوباره فعال میشه",
              gw.equipped_weapon is None and combat.weapon_choice(gw, lv_g2) == "colt")
        await s.commit()
    upd_gu = _fake_update("gear:upg", uid=9897)
    await gear_h.gear_upg_cb(upd_gu, None)
    ed_gu = next((c for c in upd_gu.callback_query.calls if c[0] == "edit"), None)
    gu_datas = {b.callback_data for row in ed_gu[2]["reply_markup"].inline_keyboard for b in row} if ed_gu else set()
    check("آپگرید تجهیزات از همون بخش تجهیزاته و به wup/aup میره",
          ed_gu is not None and "⬆️ آپگرید تجهیزات" in ed_gu[1] and {"shop:sec:wup", "shop:sec:aup"} <= gu_datas,
          str(gu_datas))

    # صفحه تجهیزات با سلاح ویژه، متن قابلیت رو چاپ می‌کنه
    async with session_scope() as s:
        ga2, _ = await users.get_or_create(s, tg(9898, "abilpage", "ابلیفون"))
        ga2.level = 18
        s.add(_InvB(user_id=ga2.id, item_key="vampire", level=1))
        ga2.equipped_weapon = "vampire"
        await s.commit()
    upd_gv = _fake_update("menu:gear", uid=9898)
    await gear_h.gear_cb(upd_gv, None)
    ed_gv = next((c for c in upd_gv.callback_query.calls if c[0] == "edit"), None)
    check("تجهیزات وقتی سلاح ویژه فعاله، قابلیتشو نشون میده",
          ed_gv is not None and ("🎯 قابلیت ویژه: " + config.WEAPON_ABILITY_TEXT["vampire"]) in ed_gv[1],
          ed_gv[1][:200] if ed_gv else "-")

    # ── پول ساخت تیم 50,000 و کیس‌اینسنسیتیو جستجوی تیم ──
    check("هزینه ساخت تیم 50,000 شد", config.TEAM_CREATE_COST == 50000)
    async with session_scope() as s:
        tbo, _ = await users.get_or_create(s, tg(9883, "tboss", "رئیس‌کلاب"))
        tbo.level = 10
        tbo.cash = 200000
        ok_cl, disp_cl = await team_svc.create_team(s, tbo, "Master Club")
        check("تیم لاتینی ساخته شد", ok_cl, disp_cl)
        found_up = await team_svc.get_team_by_name(s, "MASTER CLUB")
        found_low = await team_svc.get_team_by_name(s, "master club")
        check("جستجوی تیم به بزرگی/کوچکی حروف حساس نیس («تیم Master» همون «تیم master»)",
              found_up is not None and found_low is not None and found_up.id == found_low.id)
        tbo2, _ = await users.get_or_create(s, tg(9884, "tboss2", "رئیس‌دوم"))
        tbo2.level = 10
        tbo2.cash = 200000
        ok_dup, dup_msg = await team_svc.create_team(s, tbo2, "MASTER club")
        check("تیم با همون اسم و کیس متفاوت تکراریه", not ok_dup and "از قبل هست" in dup_msg, dup_msg)
        await s.commit()

    # ─-─ ادمین‌سازی تیم با بخشی از اسم + تأییدیه ──
    from handlers import team as team_h_tadm
    async with session_scope() as s:
        owna, _ = await users.get_or_create(s, tg(9884, "owna", "موخ‌باز"))
        owna = await users.get_by_tg(s, 9884)
        owna.level = 10
        owna.cash = 200000
        ok_ta, msg_ta = await team_svc.create_team(s, owna, "موخ‌لند")
        check("تیم تست ادمین‌سازی ساخته شد", ok_ta, msg_ta)
        team_ta = await team_svc.get_team_of(s, owna.id)
        memc, _ = await users.get_or_create(s, tg(9885, "cosholat", "کوشولات"))
        memc.level = 4
        s.add(TeamMember(team_id=team_ta.id, user_id=memc.id, role="member",
                         join_medals=0, joined_at=now_utc()))
        await s.commit()
        mrow_c = await team_svc.get_membership(s, memc.id)
        member_c_id = mrow_c.id

    upd_ad_no = _text_update("تیم اد ادمین cos", uid=9885, uname="cosholat", fname="کوشولات")
    await team_h_tadm.team_admin_add_text(upd_ad_no, None)
    check("غیر رهبر نمی‌تونه مدیر بذاره",
          any("فقط رهبر" in c[1] for c in upd_ad_no.message.calls), str(upd_ad_no.message.calls)[:140])
    upd_ad_z = _text_update("تیم اد ادمین zzz", uid=9884, uname="owna", fname="موخ‌باز")
    await team_h_tadm.team_admin_add_text(upd_ad_z, None)
    check("اسم ناشناس رد میشه",
          any("پیدا نشد" in c[1] for c in upd_ad_z.message.calls), str(upd_ad_z.message.calls)[:140])
    upd_ad1 = _text_update("تیم اد ادمین cos", uid=9884, uname="owna", fname="موخ‌باز")
    await team_h_tadm.team_admin_add_text(upd_ad1, None)
    ad1 = upd_ad1.message.calls[-1]
    ad1_datas = {b.callback_data for row in ad1[2]["reply_markup"].inline_keyboard for b in row}
    check("«تیم اد ادمین cos» با بخشی از اسم مچ میکنه و تأییدیه می‌گیره",
          "عضو پیدا شده" in ad1[1] and "کوشولات" in ad1[1]
          and {f"tadm:add:{member_c_id}", "tadm:no"} <= ad1_datas,
          f"{ad1[1][:120]} {ad1_datas}")
    upd_ad_self = _text_update("تیم اد ادمین owna", uid=9884, uname="owna", fname="موخ‌باز")
    await team_h_tadm.team_admin_add_text(upd_ad_self, None)
    check("رهبر که نمیشه مدیر بشه", any("خودت رهبری" in c[1] for c in upd_ad_self.message.calls))

    upd_tac = _fake_update(f"tadm:add:{member_c_id}", uid=9884)
    await team_h_tadm.team_admin_confirm_cb(upd_tac, None)
    async with session_scope() as s:
        mrow_c2 = await team_svc.get_membership(s, (await users.get_by_tg(s, 9885)).id)
        check("تأیید مدیر کردن، نقش عضو رو admin می‌کنه", mrow_c2.role == "admin", mrow_c2.role)
        await s.commit()
    ed_tac = next((c for c in upd_tac.callback_query.calls if c[0] == "edit"), None)
    check("متن تأیید مدیر شدن", ed_tac is not None and "مدیر تیم شد" in ed_tac[1], ed_tac[1][:90] if ed_tac else "-")
    upd_ad2 = _text_update("تیم اد ادمین cosh", uid=9884, uname="owna", fname="موخ‌باز")
    await team_h_tadm.team_admin_add_text(upd_ad2, None)
    check("مدیر دوباره مدیر نمیشه", any("همین الان مدیره" in c[1] for c in upd_ad2.message.calls))

    upd_del = _text_update("تیم حذف ادمین COSH", uid=9884, uname="owna", fname="موخ‌باز")
    await team_h_tadm.team_admin_del_text(upd_del, None)
    dl1 = upd_del.message.calls[-1]
    dl_datas = {b.callback_data for row in dl1[2]["reply_markup"].inline_keyboard for b in row}
    check("«تیم حذف ادمین COSH» با حروف بزرگ هم پیداش میکنه",
          "عضو پیدا شده" in dl1[1] and f"tadm:del:{member_c_id}" in dl_datas, f"{dl1[1][:100]} {dl_datas}")
    upd_tdc = _fake_update(f"tadm:del:{member_c_id}", uid=9884)
    await team_h_tadm.team_admin_confirm_cb(upd_tdc, None)
    async with session_scope() as s:
        mrow_c3 = await team_svc.get_membership(s, (await users.get_by_tg(s, 9885)).id)
        check("تأیید حذف مدیر، برمی‌گرده عضو عادی", mrow_c3.role == "member", mrow_c3.role)
        await s.commit()
    upd_tno = _fake_update("tadm:no", uid=9884)
    await team_h_tadm.team_admin_cancel_cb(upd_tno, None)
    check("لغو تأییدیه تیم ادمین", any("لغو شد" in str(c[1]) for c in upd_tno.callback_query.calls if c[0] == "edit"))

    import handlers as _h_adminpats
    names_reg = [n for n, _, _ in _h_adminpats.TEXT_HANDLERS]
    pats_reg = {n: p for n, p, _ in _h_adminpats.TEXT_HANDLERS}
    import re as _re_admpat
    check("پترن «تیم اد/حذف ادمین» قبل از کاتچ‌آل «تیم» رجیستر شده و مچ میکنه",
          names_reg.index("team_admin_add") < names_reg.index("team") and names_reg.index("team_admin_del") < names_reg.index("team")
          and _re_admpat.compile(pats_reg["team_admin_add"]).match("تریاکی تیم اد ادمین cosholat")
          and _re_admpat.compile(pats_reg["team_admin_del"]).match("تیم حذف ادمین cosholat"))

    # ── خروج از تیم با متن محترمانه ──
    upd_lv = _fake_update(f"tmcf:leave:{9885}", uid=9885)
    await team_h_tadm.team_confirm_cb(upd_lv, None)
    ed_lv = next((c for c in upd_lv.callback_query.calls if c[0] == "edit"), None)
    check("خروج از تیم با متن تمیز «🚪 از تیم «X» خارج شدی»",
          ed_lv is not None and "🚪 از تیم «" in ed_lv[1] and "خارج شدی" in ed_lv[1]
          and "برو بیرون" not in ed_lv[1] and "😅" not in ed_lv[1],
          ed_lv[1][:110] if ed_lv else "-")

    # ── مایگریشن پلاسما → گاتلینگ ──
    async with session_scope() as s:
        pm1, _ = await users.get_or_create(s, tg(9881, "pm1user", "پلاسما۱"))
        pm2, _ = await users.get_or_create(s, tg(9882, "pm2user", "پلاسما۲"))
        s.add(_InvB(user_id=pm1.id, item_key="plasma", level=3))
        s.add(_InvB(user_id=pm2.id, item_key="plasma", level=1))
        s.add(_InvB(user_id=pm2.id, item_key="minigun", level=2))
        await s.commit()
        pm1_id, pm2_id = pm1.id, pm2.id
    await init_db()  # مایگریشن اینجا ردیف‌های پلاسما رو می‌بره رو گاتلینگ
    async with session_scope() as s:
        lv_m1 = await users.get_item_levels(s, pm1_id)
        lv_m2 = await users.get_item_levels(s, pm2_id)
    check("دارنده پلاسما بدون گاتلینگ، گاتلینگ با همون لول می‌گیره",
          lv_m1.get("minigun") == 3 and "plasma" not in lv_m1, str(lv_m1))
    check("دارنده هر دو، فقط ردیف پلاسما پاک میشه (تداخل نمیخوره)",
          lv_m2.get("minigun") == 2 and "plasma" not in lv_m2 and len(lv_m2) == 1, str(lv_m2))

    # ── کارخونه‌ها: قیمت و تولید جدید ──
    check("هزینه ارتقای کارخونه‌ها: لول‌های پایین ارزون، لول‌های بالا تصاعدی گرون",
          comp_svc.upgrade_cost("lumber", 2) == (6000, 40) and comp_svc.upgrade_cost("lumber", 10) == (2250000, 800)
          and comp_svc.upgrade_cost("ironmill", 2) == (9000, 60) and comp_svc.upgrade_cost("ironmill", 10) == (3300000, 1210),
          str(comp_svc.upgrade_cost("ironmill", 10)))
    check("جدول‌های ارتقای کارخونه صعودی‌ان و به ازای هر لول یه ردیف",
          len(config.FACTORIES["lumber"]["up_tp"]) == config.FACTORY_MAX_LEVEL - 1
          and config.FACTORIES["lumber"]["up_tp"] == sorted(config.FACTORIES["lumber"]["up_tp"])
          and config.FACTORIES["ironmill"]["up_wood"] == sorted(config.FACTORIES["ironmill"]["up_wood"]))
    check("تولید هر تیک کمتر شده (چوب 4، آهن 5) و 12 ساعت لول مکس میشه 2880/3600",
          config.FACTORIES["lumber"]["per_tick"] == 4 and config.FACTORIES["ironmill"]["per_tick"] == 5
          and comp_svc.factory_stock_cap("lumber", 10) == 2880 and comp_svc.factory_stock_cap("ironmill", 10) == 3600)

    # ── خرید بذر تعدادی: خدمات ──
    async with session_scope() as s:
        sl1, _ = await users.get_or_create(s, tg(9891, "lowseed", "تازه‌بذر"))
        sl1.level = 1
        sl1.cash = 10 ** 9
        ok1, m1 = await shop_svc.purchase_seed(s, sl1, "eblis", 1)
        ok2, m2 = await shop_svc.purchase_seed(s, sl1, "peyote", 1)
        ok3, _ = await shop_svc.purchase_seed(s, sl1, "marijuana", 0)
        check("گیت‌های خرید بذر: افسانه‌ای رد میشه، گیت لول، تعداد حداقل 1",
              not ok1 and "افسانه‌ای" in m1 and not ok2 and "لول 4" in m2 and not ok3, f"{m1[:40]}|{m2[:30]}")
        sl1.cash = 0
        ok4, m4 = await shop_svc.purchase_seed(s, sl1, "marijuana", 1)
        check("پول ناکافی خرید بذر رو رد می‌کنه", not ok4 and "کافی نیس" in m4, m4[:60])
        await s.commit()

    # ── خرید بذر تعدادی: فلوی کامل اینلاین ──
    async with session_scope() as s:
        sb, _ = await users.get_or_create(s, tg(9892, "seedbuyer", "بذرباز"))
        sb.level = 10
        sb.cash = 100000
        sb.shelter_level = 0
        await s.commit()
    upd_sb = _fake_update("shop:buy:seed:marijuana", uid=9892)
    await shop_h2.buy_confirm(upd_sb, None)
    ed_sb = next((c for c in upd_sb.callback_query.calls if c[0] == "edit"), None)
    async with session_scope() as s:
        sb = await users.get_by_tg(s, 9892)
    check("دکمه بذر سؤال «چندتا بذر میخوای بخری؟» رو pending می‌کنه",
          sb.pending_action == "seedbuy" and sb.pending_value == "marijuana"
          and ed_sb is not None and "چندتا بذر ماری‌جوانا میخوای بخری؟" in ed_sb[1]
          and "قیمت هر بذر 120 TP" in ed_sb[1],
          ed_sb[1][:130] if ed_sb else "-")
    upd_bad = _text_update("سلام", uid=9892, uname="seedbuyer", fname="بذرباز")
    try:
        await pending_h.capture(upd_bad, None)
    except Exception:
        pass
    async with session_scope() as s:
        sb = await users.get_by_tg(s, 9892)
        check("عدد غلط pending بذر رو نگه می‌داره",
              sb.pending_action == "seedbuy" and any("فقط یه عدد صحیح" in c[1] for c in upd_bad.message.calls))
    upd_q3 = _text_update("3", uid=9892, uname="seedbuyer", fname="بذرباز")
    try:
        await pending_h.capture(upd_q3, None)
    except Exception:
        pass
    fak = upd_q3.message.calls[-1]
    fak_datas = {b.callback_data for row in fak[2]["reply_markup"].inline_keyboard for b in row}
    check("فاکتور بذر با قالب فاکتور منابع: تعداد، جمع، رشد و فروش",
          "🧾 فاکتور خرید 🌿 ماری‌جوانا" in fak[1] and "تعداد: 3 بذر" in fak[1]
          and "جمع فاکتور: 360 تی‌پوینت" in fak[1] and "رشد هرکدوم 5 دقیقه" in fak[1]
          and "فروش هرساقه 300 TP" in fak[1] and {"cf:shopseed:marijuana:3", "cl:shopseed"} <= fak_datas,
          fak[1][:200])
    async with session_scope() as s:
        sb = await users.get_by_tg(s, 9892)
        check("بعد فاکتور pending بذر پاک شده", sb.pending_action is None)
    upd_cfs = _fake_update("cf:shopseed:marijuana:3", uid=9892)
    await shop_h2.buyseed_execute(upd_cfs, None)
    async with session_scope() as s:
        sb = await users.get_by_tg(s, 9892)
        st_sb = await farming.get_stock(s, sb.id)
        check("تأیید فاکتور: 3 بذر خریده شد و پول کم شد",
              st_sb.get("marijuana") == 3 and sb.cash == 100000 - 3 * 120, f"{st_sb} {sb.cash}")
        await s.commit()
    check("الرت موفقیت خرید بذر نشون داده میشه",
          any(c[0] == "answer" and c[1] and "خریدی" in str(c[1][0]) for c in upd_cfs.callback_query.calls))

    # سقف انبار بذر: الان 3 تا داریم و ظرفیت 5 تاست، خرید 3 دیگه رد میشه
    upd_q4 = _text_update("3", uid=9892, uname="seedbuyer", fname="بذرباز")
    await shop_h2.buy_confirm(_fake_update("shop:buy:seed:marijuana", uid=9892), None)
    try:
        await pending_h.capture(upd_q4, None)
    except Exception:
        pass
    upd_cfx = _fake_update("cf:shopseed:marijuana:3", uid=9892)
    await shop_h2.buyseed_execute(upd_cfx, None)
    async with session_scope() as s:
        sb = await users.get_by_tg(s, 9892)
        st_sb2 = await farming.get_stock(s, sb.id)
    ans_x = [c for c in upd_cfx.callback_query.calls if c[0] == "answer" and c[1]]
    check("خریدی که از ظرفیت انبار بذر رد کنه با پیام دقیق رد میشه (فقط 2 تا جا)",
          st_sb2.get("marijuana") == 3 and ans_x and "انبار بذرت جا نداره" in str(ans_x[0][1][0])
          and "فقط 2 تا دیگه جا داری" in str(ans_x[0][1][0]) and sb.cash == 100000 - 360,
          str(ans_x[0][1][0])[:140] if ans_x else "-")

    # ═══ این دور: بونوس مهارت لول ۱۰/۲۰ + بک‌فیل /update | گیت لول ۵ شرکت + قیمت ۲-۳ برابر ═══
    # ═══ دستورهای متنی انبار/ماموریت/آمار/مهارت + متن مهارت و تجهیزات روی الگوی جدید ═══

    # ── امتیاز مهارت موردانتظار: لول 10 دو تا و لول 20 سه تا ──
    check("امتیاز مهارت موردانتظار هر لول (بونوس لول 10 و 20)",
          users.expected_skill_points(1) == 0 and users.expected_skill_points(2) == 1
          and users.expected_skill_points(6) == 5 and users.expected_skill_points(9) == 8
          and users.expected_skill_points(10) == 10 and users.expected_skill_points(11) == 11
          and users.expected_skill_points(19) == 19 and users.expected_skill_points(20) == 22,
          str(users.expected_skill_points(20)))

    async with session_scope() as s:
        btr, _ = await users.get_or_create(s, tg(9913, "retro10", "قدیمی"))
        btr.level = 12
        btr.skill_points = None
        users.ensure_skills(btr)
        check("پس‌دررو با بونوس: امتیاز کاربر قدیمی لول 12 میشه 12",
              btr.skill_points == 12, str(btr.skill_points))
        b10, _ = await users.get_or_create(s, tg(9912, "bon10", "بونوسی"))
        b10.level, b10.xp = 9, 0
        b10.skill_points = 0  # تا اینجا سر راه درست گرفته، فقط بونوس لول 10 مهمه
        notes_b = users.add_xp(b10, economy.xp_need(9))
        check("رسیدن به لول 10 دو امتیاز مهارت میده و تو خبرش هست",
              b10.level == 10 and b10.skill_points == 2
              and any("🎖 2 امتیاز مهارت" in n for n in notes_b),
              f"{b10.skill_points} | {notes_b}")
        b10.level = 19
        b10.xp = 0
        notes_b2 = users.add_xp(b10, economy.xp_need(19))
        check("رسیدن به لول 20 سه امتیاز مهارت میده",
              b10.level == 20 and b10.skill_points == 5
              and any("🎖 3 امتیاز مهارت" in n for n in notes_b2),
              f"{b10.skill_points}")
        await s.commit()

    # ── شرکت: گیت لول 5 (خریدهای قدیمی قفل ولی سالم می‌مونن) ──
    check("قیمت ارتقای کارخونه‌ها دو تا سه برابر شد (چوب همون قبلیه)",
          comp_svc.upgrade_cost("lumber", 2) == (6000, 40) and comp_svc.upgrade_cost("lumber", 10) == (2250000, 800)
          and comp_svc.upgrade_cost("ironmill", 2) == (9000, 60) and comp_svc.upgrade_cost("ironmill", 10) == (3300000, 1210),
          str(comp_svc.upgrade_cost("ironmill", 10)))

    async with session_scope() as s:
        cl, _ = await users.get_or_create(s, tg(9914, "lowlvl", "کم‌لول"))
        cl.level = 3
        cl.lumber_level = 2
        cl.lumber_stock = 100
        cl.cash = 500000
        cl.wood = 500
        ok_l1, msg_l1 = await comp_svc.collect(s, cl, "lumber")
        check("برداشت کارخونه زیر لول 5 قفله و موجودیش دست نمی‌خوره",
              not ok_l1 and "🔒" in msg_l1 and "لول 5" in msg_l1 and cl.lumber_stock == 100, msg_l1[:110])
        ok_l2, msg_l2 = await comp_svc.upgrade(s, cl, "lumber")
        check("ارتقای کارخونه زیر لول 5 قفله و لول کارخونه سر جاشه",
              not ok_l2 and "🔒" in msg_l2 and cl.lumber_level == 2, msg_l2[:110])
        ok_l3, msg_l3 = await comp_svc.build(s, cl, "ironmill")
        check("ساخت شرکت زیر لول 5 رد میشه",
              not ok_l3 and "🔒" in msg_l3 and "لول 5" in msg_l3 and cl.ironmill_level == 0, msg_l3[:110])
        ctxt_l = comp_svc.company_text(cl)
        check("صفحه شرکت خط قفل رو نشون میده",
              "🔒 شرکتت تا لول 5 قفله" in ctxt_l, ctxt_l.replace("\n", " | ")[:160])
        cl.level = 5
        cl.wood = 50
        ok_l4, msg_l4 = await comp_svc.collect(s, cl, "lumber")
        check("لول 5 شد و قفل خودش باز شد، تولید قبلی هم میاد دستش",
              ok_l4 and cl.lumber_stock == 0 and cl.wood == 150, f"{ok_l4} | {cl.wood}")
        await s.commit()

    check("کانفیگ گیت لول شرکت 5-ه", config.COMPANY_MIN_LEVEL == 5)

    # ── /update: امتیاز مهارت خرج‌نکرده‌ها به مقدار درست به‌روز میشه ──
    async with session_scope() as s:
        uf1, _ = await users.get_or_create(s, tg(9915, "upd_fill1", "پرشونده"))
        uf1.level = 12
        uf1.skill_points = 11  # مقدار قدیمی بمانده از قبل از بونوس لول 10
        uf1.skill_power = uf1.skill_speed = uf1.skill_defense = uf1.skill_loot = 0
        uf2, _ = await users.get_or_create(s, tg(9916, "upd_spent", "خرج‌کرده"))
        uf2.level = 15
        uf2.skill_points = 10
        uf2.skill_power = 2
        uf2.skill_speed = 1
        uf2.skill_defense = uf2.skill_loot = 0
        await s.commit()
    upd_up = _text_update("/update", uid=1001, uname="adm", fname="ادمین")
    await admin_h.update_cmd(upd_up, None)
    rep_up = next((c[1] for c in upd_up.message.calls if "به‌روز" in c[1]), "")
    check("گزارش /update خط امتیاز مهارت داره",
          "🎖 امتیاز مهارت" in rep_up, rep_up.splitlines()[-2] if rep_up else "-")
    async with session_scope() as s:
        uf1 = await users.get_by_tg(s, 9915)
        uf2 = await users.get_by_tg(s, 9916)
        check("/update امتیاز بازیکنِ هنوز-خرج‌نکرده رو به مقدار لولش به‌روز می‌کنه",
              uf1.skill_points == 12, str(uf1.skill_points))
        check("/update امتیاز خرج‌کرده‌ها رو دست نمی‌زنه",
              uf2.skill_points == 10 and uf2.skill_power == 2, str(uf2.skill_points))

    # ── دستورهای متنی: انبار | ماموریت | آمار/امار | مهارت ──
    pats_now = {n: re.compile(p) for n, p, _ in handlers.TEXT_HANDLERS}
    check("«انبار» با و بدون پیشوند انبار رو باز می‌کنه",
          bool(pats_now["shelter"].match("انبار")) and bool(pats_now["shelter"].match("تی انبار")),
          pats_now["shelter"].pattern)
    check("«آمار» و «امار» جفتش کار می‌کنن (تنها و با اسم سگ)",
          bool(pats_now["stats"].match("آمار")) and bool(pats_now["stats"].match("امار"))
          and bool(pats_now["stats"].match("تریاکی امار"))
          and bool(pats_now["dogstats"].match("امار لوله‌کش")) and bool(pats_now["dogstats"].match("تی آمار لوله‌کش")),
          pats_now["dogstats"].pattern)
    check("«مهارت» با و بدون پیشوند منوی مهارت رو باز می‌کنه",
          bool(pats_now["skills_txt"].match("مهارت")) and bool(pats_now["skills_txt"].match("تریاکی مهارت")),
          pats_now["skills_txt"].pattern)
    check("«ماموریت» و «مأموریت» با هر دو املای ی و کسره بخش مأموریت رو باز می‌کنن",
          bool(pats_now["dquests_txt"].match("ماموریت")) and bool(pats_now["dquests_txt"].match("مأموریت"))
          and bool(pats_now["dquests_txt"].match("ماموریت‌ها")) and bool(pats_now["dquests_txt"].match("مأموریت‌های روزانه"))
          and bool(pats_now["dquests_txt"].match("تی مأموریت")),
          pats_now["dquests_txt"].pattern)

    from handlers import world as world_hx
    from handlers import dquests as dq_hx
    upd_anb = _text_update("انبار", uid=9917, uname="anb", fname="انباری")
    await world_hx.shelter_cmd(upd_anb, None)
    txt_anb = next((c[1] for c in upd_anb.message.calls if "انبار" in c[1]), "")
    check("نوشتن «انبار» صفحه انبار رو باز می‌کنه",
          "<b>🏚 انبار</b>" in txt_anb, txt_anb[:60])
    upd_mam = _text_update("مأموریت", uid=9917)
    await dq_hx.daily_quests_cb(upd_mam, None)
    txt_mam = next((c[1] for c in upd_mam.message.calls if "مأموریت" in c[1]), "")
    check("نوشتن «مأموریت» صفحه با سر تیتر «مأموریت‌های روزانه» باز میشه",
          "<b>🎯 مأموریت‌های روزانه</b>" in txt_mam, txt_mam[:60])
    upd_mhk = _text_update("مهارت", uid=9917)
    await skills_h.skills_cb(upd_mhk, None)
    txt_mhk = next((c[1] for c in upd_mhk.message.calls if "مهارت" in c[1]), "")
    check("نوشتن «مهارت» منوی مهارت رو باز می‌کنه",
          "<b>⭐️ مهارت‌ها</b>" in txt_mhk, txt_mhk[:60])
    check("«آمار»/«امار» به هندلر پروفایل وصله (بلوک ⚔️ آمار همون تو پروفایله)",
          dict((n, fn) for n, _, fn in handlers.TEXT_HANDLERS)["stats"] is textcmd_h.profile_text)

    # ── متن مهارت روی الگوی کارفرما ──
    async with session_scope() as s:
        stx, _ = await users.get_or_create(s, tg(9918, "skltext", "متنی"))
        stx.skill_points = 19
        await s.commit()
        txt_sk = skills_h.skills_text(stx)
    check("متن مهارت: هدر، شمار امتیاز و توضیح بونوس لول 10 و 20",
          txt_sk.splitlines()[0] == "<b>⭐️ مهارت‌ها</b>" and "🎖 امتیاز مهارت: 19" in txt_sk
          and "هر لول‌آپ یه امتیاز مهارت(جز لول 10 و 20) می‌گیری" in txt_sk,
          txt_sk.splitlines()[4] if txt_sk else "-")
    check("بلاک چهار قابلیت: اسم با لول، خط توضیح ▫️، خط الان/بعدی",
          "💥 قدرت | لول 0 از 8" in txt_sk and "▫️ هر لول 2% حمله بیشتر" in txt_sk
          and "⚡ سرعت | لول 0 از 8" in txt_sk and "▫️ هر لول 2% حمله و کاشت سریع‌تر" in txt_sk
          and "🛡 دفاع | لول 0 از 8" in txt_sk and "▫️ هر لول 2% دفاع بیشتر" in txt_sk
          and "💰 غارت | لول 0 از 8" in txt_sk and "▫️ هر لول 3% غارت بیشتر از برد" in txt_sk
          and "الان 0% ، بعدی 2%" in txt_sk and "الان 0% ، بعدی 3%" in txt_sk,
          txt_sk.replace("\n", " | ")[:230])
    check("خط ریست آخر متن با مبلغ کامله",
          txt_sk.rstrip().endswith("♻️ ریست همه امتیازاتو برمی‌گردونه و مهارت‌ها صفر میشن (25,000 تی‌پوینت)"),
          txt_sk.rstrip().splitlines()[-1])
    async with session_scope() as s:
        stx = await users.get_by_tg(s, 9918)
        stx.skill_power = 8
        txt_mx = skills_h.skills_text(stx)
        await s.commit()
    check("قابلیت مکس «👑 مکس» می‌گیره",
          "💥 قدرت | لول 8 از 8" in txt_mx and "الان 16% ، 👑 مکس" in txt_mx,
          txt_mx.replace("\n", " | ")[:240])

    # ── تجهیزات: توضیح قابلیت ویژه زیر سلاح فعال و قبل از زره ──
    async with session_scope() as s:
        gab, _ = await users.get_or_create(s, tg(9919, "gearab", "گیراب"))
        gab.level = 18
        from models import InventoryItem as _InvA
        s.add(_InvA(user_id=gab.id, item_key="vampire", level=1))
        gab.equipped_weapon = "vampire"
        await s.commit()
    upd_ga = _fake_update("menu:gear", uid=9919)
    await gear_h.gear_cb(upd_ga, None)
    ed_ga = next((c for c in upd_ga.callback_query.calls if c[0] == "edit"), None)
    t_ga = ed_ga[1] if ed_ga else ""
    _iw = t_ga.find("🔫 سلاح فعال: " + config.WEAPONS["vampire"]["name"])
    _ia = t_ga.find("🎯 قابلیت ویژه: " + config.WEAPON_ABILITY_TEXT["vampire"])
    _ig = t_ga.find("با ارتقای سلاح درصد قابلیت بیشتر میشه")
    _iz = t_ga.find("🦺 زره فعال")
    check("توضیح قابلیت ویژه دقیقاً زیر سلاح فعاله و قبل از زره میاد",
          0 <= _iw < _ia < _ig < _iz, t_ga.replace("\n", " | ")[:200])
    check("متن قابلیت اوبلیویون همون جمله کارفرماس",
          config.WEAPON_ABILITY_TEXT["oblivion"]
          == "👑 هر حمله یکی از قابلیت‌های دیگر سلاح‌های ویژه، به‌صورت تصادفی فعال میشه",
          config.WEAPON_ABILITY_TEXT["oblivion"])

    # ── مهارت ⚡ سرعت، زمان رشد بذر رو هم کمتر می‌کنه ──
    async with session_scope() as s:
        await world_svc._meta_set(s, "weather_key", "normal")
        await world_svc._meta_set(s, "weather_until", (now_utc() + timedelta(seconds=7200)).isoformat())
        spd, _ = await users.get_or_create(s, tg(9920, "planter", "کاشته"))
        spd.level = 10
        spd.skill_speed = 0
        await farming.add_seed_stock(s, spd.id, "marijuana", 5)
        p1s = Plot(user_id=spd.id, status="empty", level=1)
        s.add(p1s)
        await s.flush()
        ok_p1, _ = await farming.plant(s, spd, p1s, "marijuana")
        sec0 = (p1s.ready_at - now_utc()).total_seconds()
        spd.skill_speed = 8
        p2s = Plot(user_id=spd.id, status="empty", level=1)
        s.add(p2s)
        await s.flush()
        ok_p2, _ = await farming.plant(s, spd, p2s, "marijuana")
        sec8 = (p2s.ready_at - now_utc()).total_seconds()
        check("مهارت سرعت کاشت رو تندتر می‌کنه (لول 8 یعنی 16%)",
              ok_p1 and ok_p2 and sec8 < sec0 and sec8 <= int(sec0 / 1.16) + 1,
              f"{sec0:.0f} → {sec8:.0f}")
        await s.commit()

    # ═══ این دور: لقب تو لیدربرد (دوخطی) و لیست اعضای تیم (بولد「») + لقب آخر 💎 Drug Lord ═══

    check("لقب لول 20 اسمش Drug Lord-ه",
          users.title_of(SimpleNamespace(level=20)) == ("💎", "Drug Lord"),
          str(users.title_of(SimpleNamespace(level=20))))

    # ── لیدربرد بازیکنان: هر ردیف دوخطی، ایموجی لقب + اسم لقب بولد تو「» ──
    async with session_scope() as s:
        lb1, _ = await users.get_or_create(s, tg(9951, "lb_a", "امیررضا تست"))
        lb1.level, lb1.medals = 19, 90000000
        lb2, _ = await users.get_or_create(s, tg(9952, "lb_b", "سینا تست"))
        lb2.level, lb2.medals = 5, 89000000
        lb3, _ = await users.get_or_create(s, tg(9953, "lb_c", "تازه تست"))
        lb3.level, lb3.medals = 1, 88000000
        await s.commit()
    upd_lb = _fake_update("menu:rank", uid=9950)
    await rank_h2.rank_cb(upd_lb, None, tab="all")
    ed_lb = next((c for c in upd_lb.callback_query.calls if c[0] == "edit"), None)
    t_lb = ed_lb[1] if ed_lb else ""
    lns_lb = t_lb.splitlines()
    _i1 = next((i for i, ln in enumerate(lns_lb) if "امیررضا تست" in ln), -1)
    check("ردیف لیدربرد: نشان رتبه + ایموجی لقب + [Lv.] │ اسم",
          _i1 >= 0 and bool(re.search(r"^\S+ ☠️ \[Lv\.19\] │ امیررضا تست$", lns_lb[_i1])),
          lns_lb[_i1] if _i1 >= 0 else t_lb[:140])
    check("خط دوم ردیف: اسم لقب بولد تو「» + مدال",
          _i1 >= 0 and lns_lb[_i1 + 1] == "<b>「Godfather」</b> 🎖️ 90,000,000",
          lns_lb[_i1 + 1] if _i1 >= 0 else "-")
    _i2 = next((i for i, ln in enumerate(lns_lb) if "سینا تست" in ln), -1)
    check("ردیف لول 5: ایموجی 🔹 و لقب Member",
          _i2 >= 0 and bool(re.search(r"^\S+ 🔹 \[Lv\.05\] │ سینا تست$", lns_lb[_i2]))
          and lns_lb[_i2 + 1] == "<b>「Member」</b> 🎖️ 89,000,000",
          (lns_lb[_i2] + " ~ " + lns_lb[_i2 + 1]) if _i2 >= 0 else "-")
    _i3 = next((i for i, ln in enumerate(lns_lb) if "تازه تست" in ln), -1)
    check("حتی لول 1 هم لقب داره (🌱 Newbie)، هیچ لقب خالی نیس",
          _i3 >= 0 and lns_lb[_i3 + 1] == "<b>「Newbie」</b> 🎖️ 88,000,000"
          and "「」" not in t_lb,
          (lns_lb[_i3 + 1] if _i3 >= 0 else "-"))

    # ── اعضای تیم: لقب بولد تو「» کنار اسم، با ایموجی لقب ──
    async with session_scope() as s:
        from models import TeamMember as _TMemT
        tow, _ = await users.get_or_create(s, tg(9960, "t_own_t", "رهبر تست"))
        tow.level, tow.cash = 18, 100000
        ok_tt, _ = await team_svc.create_team(s, tow, "تیم لقبی‌ها")
        check("تیم تست لقب ساخته شد", ok_tt, _)
        tm1t, _ = await users.get_or_create(s, tg(9961, "t_m1", "عضو پنج"))
        tm1t.level = 5
        tm2t, _ = await users.get_or_create(s, tg(9962, "t_m2", "عضو یکی"))
        tm2t.level = 1
        team_tt = await team_svc.get_team_of(s, tow.id)
        s.add(_TMemT(team_id=team_tt.id, user_id=tm1t.id, role="member", join_medals=0))
        s.add(_TMemT(team_id=team_tt.id, user_id=tm2t.id, role="member", join_medals=0))
        await s.flush()
        data_tt = await team_svc.team_stats_data(s, team_tt)
        txt_tt = team_h._team_stats_text(data_tt)
        await s.commit()
    check("ردیف عضو: تگ نقش + ایموجی لقب + اسم + لقب بولد「» | لول",
          any(ln == "👑 ☠️ رهبر تست <b>「Godfather」</b> | لول 18" for ln in txt_tt.splitlines())
          and any(ln == "🔸 🔹 عضو پنج <b>「Member」</b> | لول 5" for ln in txt_tt.splitlines())
          and any(ln == "🔸 🌱 عضو یکی <b>「Newbie」</b> | لول 1" for ln in txt_tt.splitlines()),
          " | ".join(ln for ln in txt_tt.splitlines() if "「" in ln)[:210])
    check("قالب قدیمی «| Lv.» دیگه تو اعضا نیس",
          "| Lv." not in txt_tt, txt_tt[:120])

    # بیشتر از ۱۲ عضو، صفحه فقط ۱۲ تا رو میگه و «و n نفر دیگه» آخرش میاد
    async with session_scope() as s:
        from models import TeamMember as _TMemT2
        team_tt = await team_svc.get_team_of(s, (await users.get_by_tg(s, 9960)).id)
        for j in range(14):
            extra, _ = await users.get_or_create(s, tg(9970 + j, f"t_x{j}", f"عضو اضافه {j + 1}"))
            extra.level = 2
            s.add(_TMemT2(team_id=team_tt.id, user_id=extra.id, role="member", join_medals=0))
        await s.flush()
        data_tt2 = await team_svc.team_stats_data(s, team_tt)
        txt_tt2 = team_h._team_stats_text(data_tt2)
        await s.commit()
    check("فقط ۱۲ عضو اول با لقب نشون داده میشن و بقیشون «و n نفر دیگه»",
          txt_tt2.count("<b>「") == 12 and "🔸 و 5 نفر دیگه" in txt_tt2,
          f"{txt_tt2.count('<b>「')} | " + next((ln for ln in txt_tt2.splitlines() if "نفر دیگه" in ln), "-"))

    # ── تیم عضویت هم فرمت لقب‌دار داره ──
    upd_ros = _text_update("تیم عضویت", uid=9960, uname="t_own_t", fname="رهبر تست")
    await team_h.roster_text(upd_ros, None)
    txt_ros = next((c[1] for c in upd_ros.message.calls if "اعضای تیم" in c[1]), "")
    check("تیم عضویت: ردیف با لقب بولد + لول + برد",
          "👑 ☠️ رهبر تست <b>「Godfather」</b> | لول 18 | ⚔️ 0 برد" in txt_ros,
          " | ".join(ln for ln in txt_ros.splitlines() if "「" in ln)[:120])

    # ── /update خط لقب تو گزارشش داره ──
    upd_ut = _text_update("/update", uid=1001, uname="adm", fname="ادمین")
    await admin_h.update_cmd(upd_ut, None)
    rep_ut = next((c[1] for c in upd_ut.message.calls if "به‌روز" in c[1]), "")
    check("گزارش /update خط لقب‌ها رو هم داره",
          "🏅 لقب" in rep_ut and "Drug Lord" in rep_ut,
          next((ln for ln in rep_ut.splitlines() if "🏅" in ln), "-"))

    # ── تمیزکاری ته تست‌ها ──
    fj_svc._MEMBER_CACHE.clear()
    async with session_scope() as s:
        await fj_svc.clear_channel(s)
        await s.commit()

    print(f"\n🎉 همه تست‌ها سبز شدن، {PASS} مورد")


asyncio.run(main())
