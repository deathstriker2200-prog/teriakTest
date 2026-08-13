"""
کوئست‌های روزانه بازیکن 📅
هر روز ۲ تا ۴ ماموریت رندوم به‌وقت ایران (راند ۲۲) | ریست هر شب ساعت ۱۲ به‌وقت ایران (تنبل، با اولین تعامل)
جایزه بر اساس سختی کوئست: تی‌پوینت | تجربه | بذر رندوم معمولی
روی خود کاربر ذخیره میشه (dq_date + dq_data) و جدول جدید نمی‌خواد
"""

import json
import random

from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import User
from services.farming import add_seed_stock, try_add_seed
from services.users import add_xp
from utils import fa_num, iran_today, money


# ───────── ذخیره و خواندن ─────────

def _load(user: User) -> list[dict]:
    """لیست کوئست‌های ذخیره‌شده روی کاربر، خراب/خالی → لیست خالی"""
    if not user.dq_data:
        return []
    try:
        data = json.loads(user.dq_data)
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []


def _save(user: User, quests: list[dict]) -> None:
    user.dq_data = json.dumps(quests, ensure_ascii=False)


# ───────── متن‌ها ─────────

def quest_title(q: dict) -> str:
    """عنوان کوئست با عدد هدفش، مثل «انجام 5 حمله»"""
    cfg = config.DAILY_QUESTS[q["kind"]]
    return cfg["title"].format(n=fa_num(q["target"]))


def reward_text(q: dict) -> str:
    """متن جایزه کوئست برای نمایش"""
    r = q["reward"]
    if r["type"] == "tp":
        return money(r["amount"])
    if r["type"] == "xp":
        return f"✨ {fa_num(r['amount'])} تجربه"
    return f"🌱 {fa_num(r['amount'])} تا بذر {config.SEEDS[r['seed']]['name']}"


def remaining(quests: list[dict]) -> int:
    """تعداد کوئست‌های ناتموم"""
    return sum(1 for q in quests if not q["done"])


# ───────── ساخت کوئست‌های روز ─────────

def scaled_values(kind: str, level: int) -> tuple[int, int, int]:
    """(هدف, تی‌پوینت, تجربه) مقیاس‌خورده با لول بازیکن، هرچی لول بالاتر سخت‌تر و پرجایزه‌تر"""
    cfg = config.DAILY_QUESTS[kind]
    steps = max(0, int(level or 1) - 1)
    target = max(1, round(cfg["target"] * (1 + config.DAILY_QUEST_TARGET_GROWTH * steps)))
    tp = round(cfg["tp"] * (1 + config.DAILY_QUEST_REWARD_GROWTH * steps))
    xp = round(cfg["xp"] * (1 + config.DAILY_QUEST_REWARD_GROWTH * steps))
    return target, tp, xp


def _roll_reward(kind: str, level: int) -> dict:
    """
    قرعه جایزه بر اساس سختی کوئست، تی‌پوینت | تجربه | بذر
    گیت لول درخواست کارفرما: جهنم/ابلیس لول 5+ | جهش‌یافته لول 8+ | کوکائین لول 3+ (economy.seed_drop_allowed)
    """
    from services import economy
    _, tp, xp = scaled_values(kind, level)
    r = random.random()
    if r < config.DAILY_QUEST_TP_WEIGHT:
        return {"type": "tp", "amount": tp}
    if r < config.DAILY_QUEST_TP_WEIGHT + config.DAILY_QUEST_XP_WEIGHT:
        return {"type": "xp", "amount": xp}
    cut = config.DAILY_QUEST_TP_WEIGHT + config.DAILY_QUEST_XP_WEIGHT
    if level >= config.DAILY_QUEST_MUTANT_MIN_LEVEL and r < cut + config.DAILY_QUEST_MUTANT_CHANCE:
        return {"type": "seed", "seed": "mutant", "amount": 1}
    cut += config.DAILY_QUEST_MUTANT_CHANCE
    if level >= config.DAILY_QUEST_LEGEND_MIN_LEVEL and r < cut + config.DAILY_QUEST_LEGEND_CHANCE:
        return {"type": "seed", "seed": random.choice(config.QUEST_LEGEND_SEEDS), "amount": random.randint(1, config.DAILY_QUEST_SEED_MAX)}
    seeds = economy.allowed_normal_seeds(level)
    return {"type": "seed", "seed": random.choice(seeds), "amount": random.randint(1, config.DAILY_QUEST_SEED_MAX)}


async def ensure_quests(session: AsyncSession, user: User) -> list[dict]:
    """
    کوئست‌های امروز کاربر رو بگیر، اگه روز عوض شده باشه از نو می‌سازه
    ریست هر شب ساعت ۱۲ به‌وقت ایران، خودکار با اولین تعامل بعد از نیمه شب
    از بین کوئست‌های رزروشده برای لول کاربر می‌سازه، هدف و جایزه با لول مقیاس می‌خوره
    """
    today = iran_today()
    if user.dq_date == today and _load(user):
        return _load(user)

    pool = [k for k, c in config.DAILY_QUESTS.items() if user.level >= c.get("min_level", 1)]
    if not pool:
        pool = list(config.DAILY_QUESTS)[:1]  # همیشه حداقل یه کوئست باشه
    kinds = random.sample(
        pool,
        k=min(len(pool), random.randint(config.DAILY_QUEST_COUNT_MIN, config.DAILY_QUEST_COUNT_MAX)),
    )
    quests = [
        {
            "kind": k,
            "target": scaled_values(k, user.level)[0],
            "progress": 0,
            "done": False,
            "reward": _roll_reward(k, user.level),
        }
        for k in kinds
    ]
    user.dq_date = today
    _save(user, quests)
    return quests


# ───────── ثبت پیشرفت ─────────

async def track(session: AsyncSession, user: User, kind: str, n: int = 1) -> tuple[list[dict], int]:
    """
    ثبت یه رویداد بازی: attack | harvest | mine | plant | search | feed
    خروجی: (کوئست‌های تازه تکمیل‌شده با جایزه اعمال‌شده، تعداد مونده بعدش)
    """
    quests = await ensure_quests(session, user)
    completed: list[dict] = []
    touched = False
    for q in quests:
        if q["kind"] != kind:
            continue
        touched = True
        if q["done"]:
            continue
        q["progress"] = min(q["target"], q["progress"] + n)
        if q["progress"] >= q["target"]:
            q["done"] = True
            notes: list[str] = []
            r = q["reward"]
            from services import tracklog as tl
            if r["type"] == "tp":
                user.cash += r["amount"]
                await tl.bump_quest(session, user.id, r["amount"], 0)  # لاگ ردیابی ادمین
            elif r["type"] == "xp":
                notes = add_xp(user, r["amount"])
                from services import teams as team_svc
                notes += await team_svc.add_team_xp(session, user, r["amount"])
                await tl.bump_quest(session, user.id, 0, r["amount"])  # لاگ ردیابی ادمین
            else:
                taken = await try_add_seed(session, user, r["seed"], r["amount"])  # انبار پر بذر رو نمی‌خوره (راند ۹)
                if taken < r["amount"]:
                    notes.append("🌾 انبار بذرت پر بود و بذر جایزه افتاد زمین 😖")
            q["notes"] = notes
            completed.append(q)
    if touched:
        _save(user, quests)
    return completed, remaining(quests)
