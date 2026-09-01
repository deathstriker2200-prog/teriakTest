"""
باس‌های محله 👹 (راند ۲۳، درخواست کارفرما)
هر روز دو باس تو هر گروه فعال اسپان میشن، ساعتاشون شانسی ولی حداقل ۲ ساعت فاصله دارن
درجه‌ها: ⚪ معمولی ۷۰ درصد | 🟣 اپیک ۲۰ درصد | 🟡 لجندری ۱۰ درصد (راند ۲۹: ماندگاری ۱۰/۲۰/۳۰ دقیقه و جواب باس منهای دفاع زره)
قطعه افسانه‌ای برای قاتل تضمینی نیست و هر باس فقط یک رول کمیاب فرگمنت بین سه نفر برتر دارد
حالت باس فعال درون حافظه‌ست (مثل کاروان، با ری‌استارت می‌ره) ولی برنامه روزانه اسپون تو دیتابیسه
عکس باس‌ها از پنل ادمین با فرستادن عکس ست میشه و فایلش روی سرور ذخیره می‌مونه
"""

import json
import os
import random
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import BossPlan, GameMeta, User
from services.users import add_xp
from utils import fa_dur, fa_num, money, now_iran, now_utc

# ───────── حالت درون حافظه ─────────
# chat_id → {key, tier, hp, max_hp, expires_at, damages{uid:dmg}, names{uid:name}, killer, message_id}
BOSSES: dict[int, dict] = {}
# (chat_id, user_id) → آخرین ضربه، کولدان ۱ دقیقه‌ای هر بازیکن
BOSS_HITS: dict[tuple[int, int], object] = {}
# (chat_id, user_tg) → آخرین کلیک روی دکمه، دیبانس اسپم
BOSS_CLICKS: dict[tuple[int, int], object] = {}

_IMAGES_META_KEY = "boss_images"


# ───────── عکس باس‌ها (از پنل ادمین روی سرور ذخیره میشن) ─────────

def image_path(key: str) -> str:
    return os.path.join(config.BOSS_IMAGE_DIR, key + ".jpg")


def has_image(key: str) -> bool:
    return os.path.exists(image_path(key))


async def _meta_list(session: AsyncSession) -> list[str]:
    row = await session.get(GameMeta, _IMAGES_META_KEY)
    try:
        d = json.loads(row.value) if row else []
    except (ValueError, TypeError):
        return []
    return d if isinstance(d, list) else []


async def remember_image(session: AsyncSession, key: str) -> None:
    """کلید باس رو تو لیست «عکس‌دارها» نگه می‌داره (برای نمایش ✅/❌ پنل، کنار خود فایل)"""
    lst = await _meta_list(session)
    if key not in lst:
        lst.append(key)
    row = await session.get(GameMeta, _IMAGES_META_KEY)
    if row is None:
        row = GameMeta(key=_IMAGES_META_KEY, value="[]")
        session.add(row)
    row.value = json.dumps(lst, ensure_ascii=False)


# ───────── برنامه اسپون روزانه (۲ باس، ≥۲ ساعت فاصله، شانسی ولی ثابت برای اون روز) ─────────

def _plan_times(chat_id: int, day: str) -> list[str]:
    """دو ساعت شانسی ثابت برای اون روز/گروه، داخل پنجره کانفیگ با حداقل فاصله"""
    rng = random.Random(f"bossplan:{day}:{int(chat_id)}")
    lo = config.BOSS_WINDOW_FROM * 60
    hi = config.BOSS_WINDOW_TO * 60 - 1
    gap = config.BOSS_MIN_GAP_MINUTES
    for _ in range(64):
        a = rng.randint(lo, hi)
        b = rng.randint(lo, hi)
        if abs(a - b) >= gap:
            t1, t2 = sorted((a, b))
            return [f"{t1 // 60:02d}:{t1 % 60:02d}", f"{t2 // 60:02d}:{t2 % 60:02d}"]
    # عملا نمی‌رسه اینجا، ولی اگه پنجره خیلی تنگ باشه یه جفت بی‌تعارض برمی‌گردونیم
    return [f"{lo // 60:02d}:{lo % 60:02d}", f"{(lo + gap) // 60:02d}:{(lo + gap) % 60:02d}"]


async def ensure_plan(session: AsyncSession, chat_id: int, day: str | None = None) -> BossPlan:
    """برنامه امروز گروه رو بگیر، نبود با سید ثابت بساز"""
    day = day or now_iran().date().isoformat()
    row = await session.get(BossPlan, (chat_id, day))
    if row is None:
        row = BossPlan(chat_id=chat_id, day=day, times=",".join(_plan_times(chat_id, day)), spawned=0)
        session.add(row)
        await session.flush()
    return row


def plan_due(plan: BossPlan, ir=None) -> bool:
    """آیا نوبت اسپون بعدی اون روز رسیده؟"""
    times = [t for t in plan.times.split(",") if t]
    if plan.spawned >= len(times):
        return False
    ir = ir or now_iran()
    hh, mm = times[plan.spawned].split(":")
    return (ir.hour * 60 + ir.minute) >= (int(hh) * 60 + int(mm))


# ───────── اسپون ─────────

def roll_boss() -> dict:
    """قرعه درجه (۷۰/۲۰/۱۰) + انتخاب یکنواخت باس داخل درجه"""
    r = random.random()
    acc = 0.0
    tier = config.BOSS_TIER_SPAWN[-1][0]
    for name, chance in config.BOSS_TIER_SPAWN:
        acc += chance
        if r < acc:
            tier = name
            break
    pool = [b for b in config.BOSSES if b["tier"] == tier]
    return random.choice(pool)


def spawn(chat_id: int, boss: dict | None = None) -> dict:
    """اسپون باس تو گروه، boss=None یعنی با قرعه درجه؛ خروجی حالت باس"""
    boss = boss or roll_boss()
    st = {
        "key": boss["key"],
        "tier": boss["tier"],
        "hp": boss["hp"],
        "max_hp": boss["hp"],
        "expires_at": now_utc() + timedelta(minutes=boss["mins"]),
        "damages": {},
        "names": {},
        "message_id": None,
        "board_at": now_utc(),  # آخرین ادیت برد، جاب هر ۲ دقیقه تازه‌ش می‌کنه (راند ۲۹)
    }
    BOSSES[chat_id] = st
    return st


def active(chat_id: int) -> dict | None:
    st = BOSSES.get(chat_id)
    if st and st["expires_at"] > now_utc() and st["hp"] > 0:
        return st
    return None


def boss_of(st: dict) -> dict:
    return config.BOSS_BY_KEY[st["key"]]


# ───────── قواعد دعوا ─────────

def click_spam(chat_id: int, user_tg: int) -> bool:
    """کلیک تندتند دکمه بی‌صدا نادیده گرفته میشه"""
    key = (chat_id, user_tg)
    now = now_utc()
    last = BOSS_CLICKS.get(key)
    BOSS_CLICKS[key] = now
    return bool(last and (now - last).total_seconds() < config.BOSS_CLICK_DEBOUNCE_SECONDS)


def hit_left(chat_id: int, user_id: int) -> int:
    """ثانیه مونده از کولدان ضربه (هر ۱ دقیقه)"""
    last = BOSS_HITS.get((chat_id, user_id))
    if not last:
        return 0
    left = config.BOSS_HIT_COOLDOWN_SECONDS - (now_utc() - last).total_seconds()
    return max(0, int(left))


async def attack(session: AsyncSession, chat_id: int, user: User, dmg: int,
                 armor_def: int = 0) -> dict:
    """
    ضربه به باس، دمیج = قدرت حمله بازیکن با نوسان
    هر ضربه اسکناس و XP میده، باس هم جواب میده ولی کشنده نیس (کف ۱ HP)
    راند ۲۹ (درخواست کارفرما): جواب باس اول از دفاع زره کم میشه، مازادش از جون میره
    خروجی: {status: none|cooldown|hit|killed, ...}
    """
    st = active(chat_id)
    if not st:
        return {"status": "none"}

    left = hit_left(chat_id, user.id)
    if left:
        return {"status": "cooldown", "left": left}

    BOSS_HITS[(chat_id, user.id)] = now_utc()
    swing = config.BOSS_DMG_VARIANCE
    dmg = max(1, round(dmg * random.uniform(1 - swing, 1 + swing)))
    st["hp"] -= dmg
    st["damages"][user.id] = st["damages"].get(user.id, 0) + dmg
    st["names"][user.id] = user.first_name or user.username or "؟"

    cash_gain = dmg * config.BOSS_MONEY_PER_DMG
    user.cash += cash_gain
    notes = add_xp(user, config.BOSS_HIT_XP)
    from services import teams as team_svc
    notes += await team_svc.add_team_xp(session, user, config.BOSS_HIT_XP)

    # جواب باس: غیر کشنده، کف ۱ HP (راند ۲۹: اول از دفاع زره کم میشه، قابلیت‌ها اعمال نمیشن)
    boss = boss_of(st)
    taken = max(0, boss["dmg"] - max(0, int(armor_def or 0)))
    user.hp = max(1, (user.hp or 1) - taken)

    res = {
        "status": "hit",
        "dmg": dmg,
        "cash": cash_gain,
        "taken": taken,
        "hp_left": max(0, st["hp"]),
        "max_hp": st["max_hp"],
        "notes": notes,
    }

    if st["hp"] <= 0:
        res["status"] = "killed"
        res["key"] = st["key"]
        res["rewards"] = await _settle(session, chat_id, killer_id=user.id)
    return res


async def expire(session: AsyncSession, chat_id: int) -> dict | None:
    """تایم باس تموم شده، اگه فعال بود می‌ره بدون جایزه نهایی"""
    st = BOSSES.get(chat_id)
    if not st or st["expires_at"] > now_utc() or st["hp"] <= 0:
        return None
    BOSSES.pop(chat_id, None)
    return {"key": st["key"], "tier": st["tier"]}


async def _settle(session: AsyncSession, chat_id: int, killer_id: int) -> dict:
    """
    تسویه کشتن باس: جایزه رومیزی بین نفرهای برتر دمیج بر اساس رتبه (BOSS_RANK_PCT)
    جم هر درجه به صورت مجموع کنترل‌شده بین سه نفر برتر تقسیم می‌شود؛ لجندری ۵۰ تا ۸۰ جم.
    فرگمنت با یک رول کمیاب بین سه نفر برتر می‌افتد و قطعه افسانه‌ای فقط با شانس درجه به قاتل می‌رسد.
    """
    st = BOSSES.pop(chat_id, None)
    if not st:
        return {"rows": [], "drop_part": False}
    boss = boss_of(st)
    damages = st["damages"]
    if not damages:
        return {"rows": [], "drop_part": False}

    ranked = sorted(damages.items(), key=lambda kv: -kv[1])[: config.BOSS_TOP_REWARDS]

    # 💎 فقط باس جم می‌دهد. مجموع هر باس از بازه درجه رول و بین سه نفر برتر ۵۰/۳۰/۲۰ تقسیم می‌شود.
    gem_gains: dict[int, int] = {}
    top_gem = ranked[: config.BOSS_GEM_TOP_N]
    if top_gem:
        lo_g, hi_g = config.BOSS_GEM_TOTAL_RANGE[boss["tier"]]
        total_gems = random.randint(lo_g, hi_g)
        weights = [0.50, 0.30, 0.20][:len(top_gem)]
        weight_sum = sum(weights)
        allocated = 0
        for idx, (uid, _d) in enumerate(top_gem):
            g = total_gems - allocated if idx == len(top_gem) - 1 else round(total_gems * weights[idx] / weight_sum)
            allocated += g
            gu = await session.get(User, uid)
            if gu is not None:
                gu.gems = (gu.gems or 0) + g
                gem_gains[uid] = g

    # 🔹 فرگمنت باس کمیاب است: برای هر باس فقط یک رول، نه جایزه تضمینی برای همه.
    fragment_gains: dict[int, int] = {}
    frag_candidates = ranked[: config.BOSS_FRAGMENT_TOP_N]
    frag_chance = config.BOSS_FRAGMENT_DROP_CHANCE[boss["tier"]]
    if frag_candidates and random.random() < frag_chance:
        weights = config.BOSS_FRAGMENT_RANK_WEIGHTS[:len(frag_candidates)]
        uid, _d = random.choices(frag_candidates, weights=weights, k=1)[0]
        frag_lo, frag_hi = config.BOSS_FRAGMENT_DROP[boss["tier"]]
        amount = random.randint(frag_lo, frag_hi)
        gu = await session.get(User, uid)
        if gu is not None:
            gu.boss_fragments = (gu.boss_fragments or 0) + amount
            fragment_gains[uid] = amount

    rows = []
    for idx, (uid, d) in enumerate(ranked):
        u = await session.get(User, uid)
        if not u:
            continue
        pct = config.BOSS_RANK_PCT[idx] if idx < len(config.BOSS_RANK_PCT) else config.BOSS_RANK_PCT[-1]
        share = max(1, round(boss["reward"] * pct))
        if uid == killer_id:
            share += round(boss["reward"] * config.BOSS_KILLER_BONUS)
        u.cash += share
        rows.append({
            "user_id": uid,
            "name": st["names"].get(uid, "؟"),
            "dmg": d,
            "share": share,
            "top": idx == 0,
            "killer": uid == killer_id,
            "gems": gem_gains.get(uid, 0),
            "fragments": fragment_gains.get(uid, 0),
        })

    # 🧩 قطعه افسانه‌ای دیگر تضمینی نیست؛ فقط قاتل و با شانس پایین درجه باس
    drop_part = False
    killer = await session.get(User, killer_id)
    part_chance = config.BOSS_PART_DROP.get(boss["tier"], 0.0)
    if killer is not None and random.random() < part_chance:
        killer.legendary_parts = (killer.legendary_parts or 0) + 1
        drop_part = True

    return {
        "rows": rows,
        "drop_part": drop_part,
        "killer_gems": gem_gains.get(killer_id, 0),
        "total_gems": sum(gem_gains.values()),
        "total_fragments": sum(fragment_gains.values()),
    }


# ───────── متن‌ها ─────────

def _hp_bar(hp: int, max_hp: int) -> str:
    """نوار سلامت ۱۰ خونه‌ای با مربع"""
    fill = 0 if max_hp <= 0 else round((max(0, hp) / max_hp) * 10)
    return "🟥" * fill + "⬜" * (10 - fill)


def card_text(st: dict) -> str:
    """کارت حضور باس با داستان و مشخصات، مثل نمونه‌ای که کارفرما داد"""
    boss = boss_of(st)
    tier = config.BOSS_TIERS[boss["tier"]]
    lines = [
        f"🚨 <b>{boss['name']} وارد محله شد!</b>",
        "",
        f"{boss['emoji']} <b>{boss['name']} | {boss['tag']}</b>",
        f"{tier['emoji']} درجه: {tier['name']}",
        "",
        f"👤 شخصیت: {boss['char']}",
        "",
        f"📖 داستان: {boss['story']}",
        "",
        f"❤️ سلامتی: {fa_num(st['hp'])}",
        f"⚔️ سبک مبارزه: {boss['style']}",
        f"📍 محل حضور: {boss['place']}",
        f"⚔️ قدرت: {fa_num(boss['dmg'])} (اول از دفاع زره‌ت کم میشه)",
        "",
        f"🎁 جایزه شکست: {money(boss['reward'])} (پلکانی بین ۵ نفر برتر دمیج)",
        f"🔹 فرگمنت باس برای {fa_num(config.BOSS_FRAGMENT_TOP_N)} نفر برتر",
        f"🧩 شانس قطعه افسانه‌ای قاتل: {fa_num(int(config.BOSS_PART_DROP.get(boss['tier'], 0) * 100))}%",
        "💎 جم فقط از باس می‌افتد و بین سه نفر برتر تقسیم می‌شود",
    ]
    lines.append(f"⏳ تا {fa_num(boss['mins'])} دقیقه دیگه محله رو ترک می‌کنه")
    return "\n".join(lines)


def board_text(st: dict) -> str:
    """برد زنده زیر کارت که با هر ضربه ادیت میشه"""
    left = max(0, int((st["expires_at"] - now_utc()).total_seconds()))
    lines = [
        f"{_hp_bar(st['hp'], st['max_hp'])} {fa_num(max(0, st['hp']))}/{fa_num(st['max_hp'])}",
        "",
        "🗡 برترین ضربه‌زنا:",
    ]
    ranked = sorted(st["damages"].items(), key=lambda kv: -kv[1])[:5]
    if ranked:
        for idx, (uid, d) in enumerate(ranked, 1):
            lines.append(f"{idx}. {st['names'].get(uid, '؟')} → {fa_num(d)}")
    else:
        lines.append("هنوز هیچ‌کس ضربه نزده، کی شروع می‌کنه؟ 😈")
    lines.append("")
    lines.append(f"⏳ {fa_dur(left)} دیگه می‌ره | هر ۱ دقیقه یه ضربه")
    return "\n".join(lines)


def end_text(res: dict, key: str) -> str:
    """پیام پایانی: کشتن با جدول جایزه یا فرار باس (راند ۴۱: قالب تازه، جایزه ویژه قاتل جدا نمایش داده میشه)"""
    boss = config.BOSS_BY_KEY[key]
    rows = res.get("rows", [])
    if not rows:
        return f"🌫 {boss['emoji']} <b>{boss['name']}</b> رد شد و رفت، هیچ‌کس نتونست زمینش بذاره"
    lines = [
        f"🏆 {boss['emoji']} <b>{boss['name']} زمین خورد</b>",
        "",
    ]
    killer_name = "؟"
    for r in rows:
        mark = "👑" if r["top"] else "▫️"
        gem = f" + 💎×{fa_num(r['gems'])}" if r.get("gems") else ""
        frag = f" + 🔹×{fa_num(r['fragments'])}" if r.get("fragments") else ""
        lines.append(f"{mark} {r['name']} ({fa_num(r['dmg'])} دمیج) → {money(r['share'])}{gem}{frag}")
        if r["killer"]:
            killer_name = r["name"]
    lines.append("")
    lines.append(f"قاتل: {killer_name}")
    lines.append(f"💎 مجموع جم واردشده: {fa_num(res.get('total_gems', 0))}")
    lines.append(f"🔹 مجموع فرگمنت: {fa_num(res.get('total_fragments', 0))}")
    if res.get("drop_part"):
        lines.append("🧩 قاتل باس یک قطعه افسانه‌ای هم پیدا کرد")
    return "\n".join(lines)


def fled_text(key: str) -> str:
    boss = config.BOSS_BY_KEY[key]
    return (
        f"🌫 <b>{boss['emoji']} {boss['name']} محله رو ترک کرد</b>\n\n"
        "کسی نتونست زمینش بذاره، دفعه بعد زودتر جمع شین 😤"
    )


