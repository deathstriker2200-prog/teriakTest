#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مهاجرت دیتای ربات تریاکی از SQLite به PostgreSQL (راهنمای کامل: DEPLOY_UBUNTU.md)

ورودی‌ها (متغیر محیطی):
  TERIAKY_MIGRATE_FROM  مسیر فایل SQLite (مثل /home/teriaky/teriaky-backup.db) یا URL کامل
  TERIAKY_MIGRATE_TO    آدرس مقصد (مثل postgresql+asyncpg://teriaky:PASS@localhost:5432/teriaky)

فلگ‌ها:
  --yes          تایید تعاملی رو رد می‌کنه (برای اجرای غیردستی)
  --verify-only  بدون هیچ نوشتنی، فقط تعداد ردیف‌های هر جدول رو بین مبدأ و مقصد مقایسه می‌کنه

idempotent: ردیف‌هایی که کلید اصلی‌شون قبلاً تو مقصد هست رد میشن
پس اجرای دوباره اسکریپت هیچ دیتای تکراری نمی‌سازه و امنه
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

CHUNK = 500  # اندازه هر بسته INSERT


def _norm_url(raw: str) -> str:
    """مسیر ساده فایل یا URL خام رو به URL استاندارد SQLAlchemy تبدیل می‌کنه"""
    raw = (raw or "").strip()
    if not raw:
        return raw
    if "://" not in raw:  # مسیر خالص فایل SQLite
        return f"sqlite+aiosqlite:///{raw}"
    if raw.startswith("postgres://"):
        return "postgresql+asyncpg://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://") and not raw.startswith("postgresql+asyncpg://"):
        return "postgresql+asyncpg://" + raw[len("postgresql://"):]
    if raw.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + raw[len("sqlite:///"):]
    return raw


def _fail(msg: str, code: int = 1) -> None:
    print(f"❌ {msg}")
    raise SystemExit(code)


async def _verify(src, dst, tables) -> bool:
    """مقایسه تعداد ردیف هر جدول بین مبدأ و مقصد (بدون نوشتن)"""
    ok = True
    print(f"{'جدول':<22} | {'مبدأ':>8} | {'مقصد':>8}")
    print("-" * 46)
    async with src.connect() as c1, dst.connect() as c2:
        from sqlalchemy import inspect as sa_inspect
        src_names = set(await c1.run_sync(lambda c: sa_inspect(c).get_table_names()))
        for table in tables:
            # راند ۳۲: جدول ناموجود تو مبدأ (بک‌آپ قدیمی) صفر ردیف حساب میشه تا verify هم کرش نکنه
            n1 = (await c1.execute(select(func.count()).select_from(table))).scalar_one() if table.name in src_names else 0
            n2 = (await c2.execute(select(func.count()).select_from(table))).scalar_one()
            mark = "✅" if n1 == n2 else "⚠️"
            print(f"{mark} {table.name:<20} | {n1:>8} | {n2:>8}")
            if n1 != n2:
                ok = False
    return ok


async def _sync_sequences(dst, tables) -> None:
    """سریال‌های Postgres (AUTOINCREMENT) رو با بیشترین id واقعی سینک می‌کنه تا INSERT بعدی تداخل نگیره"""
    if dst.url.get_backend_name() != "postgresql":
        return
    async with dst.begin() as conn:
        for table in tables:
            for col in table.c:
                if not (col.primary_key and getattr(col, "autoincrement", None) is True):
                    continue
                seq = (await conn.execute(
                    text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": table.name, "c": col.name}
                )).scalar()
                if seq:
                    await conn.execute(text(
                        f'SELECT setval(\'{seq}\', COALESCE((SELECT MAX("{col.name}") FROM "{table.name}"), 1))'
                    ))
    print("🔧 سریال‌های Postgres با بیشترین id هر جدول سینک شدن")


async def main() -> None:
    argv = sys.argv[1:]
    yes = "--yes" in argv
    verify_only = "--verify-only" in argv

    src_url = _norm_url(os.getenv("TERIAKY_MIGRATE_FROM", ""))
    dst_url = _norm_url(os.getenv("TERIAKY_MIGRATE_TO", ""))
    if not src_url or not dst_url:
        _fail("هر دو متغیر TERIAKY_MIGRATE_FROM و TERIAKY_MIGRATE_TO لازمن (راهنما: DEPLOY_UBUNTU.md)")
    if src_url == dst_url:
        _fail("مبدأ و مقصد نمی‌تونن یکی باشن")

    from database import Base
    from models import models as _models  # noqa: F401  (ثبت جدول‌ها روی metadata)

    tables = Base.metadata.sorted_tables  # مرتیب‌شده بر اساس وابستگی کلید خارجی

    src = create_async_engine(src_url)
    dst = create_async_engine(dst_url)

    # اسکیمای مقصد رو کامل می‌کنیم (create_all امن و idempotent ـه) تا verify روی مقصد خالی هم تمیز گزارش بده
    async with dst.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if verify_only:
        ok = await _verify(src, dst, tables)
        await src.dispose()
        await dst.dispose()
        if ok:
            print("\n🎉 verify برقراره، تعداد ردیف همه جدول‌ها یکیه")
            raise SystemExit(0)
        print("\n❌ verify شکست خورد، بعضی جدول‌ها بین مبدأ و مقصد فرق دارن")
        raise SystemExit(1)

    if not yes:
        print("⚠️ این اسکریپت همه ردیف‌های مبدأ رو به مقصد کپی می‌کنه (ردیف تکراری رد میشه، چیزی پاک نمیشه)")
        print(f"مبدأ: {src_url.split('://')[0]} | مقصد: {dst_url.split('://')[0]}")
        try:
            ans = input("مطمئنی؟ برای شروع دقیقاً بنویس YES: ")
        except EOFError:
            ans = ""
        if ans.strip() != "YES":
            _fail("لغو شد (برای اجرای غیرتعاملی فلگ --yes رو بذار)")

    total_new = 0
    async with src.connect() as sc:
        from sqlalchemy import inspect as sa_inspect
        src_table_names = set(await sc.run_sync(lambda c: sa_inspect(c).get_table_names()))

        async with dst.begin() as dc:
            for table in tables:
                if table.name not in src_table_names:
                    print(f"⏭ {table.name}: تو دیتابیس مبدأ وجود نداره (احتمالاً بک‌آپ قدیمیه)، رد شد")
                    continue
                pks = [c.name for c in table.primary_key.columns]
                if not pks:
                    print(f"⏭ {table.name}: کلید اصلی نداره، رد شد")
                    continue
                existing = {
                    tuple(r) for r in
                    (await dc.execute(select(*[table.c[p] for p in pks]))).all()
                }
                src_rows = (await sc.execute(select(table))).mappings().all()
                batch: list[dict] = []
                inserted = 0
                for r in src_rows:
                    if tuple(r[p] for p in pks) in existing:
                        continue
                    batch.append(dict(r))
                    if len(batch) >= CHUNK:
                        await dc.execute(table.insert(), batch)
                        inserted += len(batch)
                        batch = []
                if batch:
                    await dc.execute(table.insert(), batch)
                    inserted += len(batch)
                total_new += inserted
                print(f"📦 {table.name}: {inserted} ردیف جدید، {len(src_rows) - inserted} ردیف تکراری رد شد")

    await _sync_sequences(dst, tables)

    ok = await _verify(src, dst, tables)
    await src.dispose()
    await dst.dispose()
    if not ok:
        _fail("بعد از کپی، verify مغایرت گرفت — خروجی بالا رو ببین")
    print(f"\n🎉 مهاجرت تموم شد — {total_new} ردیف جدید کپی شد و verify برقراره")


if __name__ == "__main__":
    asyncio.run(main())
