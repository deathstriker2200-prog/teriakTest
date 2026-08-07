#!/usr/bin/env python3
"""
ست‌کن دائمی متغیرهای ربات «تریاکی» (راند ۱۸، درخواست کارفرما)

مثل export می‌مونه ولی دائمیه: مقدار رو توی فایل .env کنار پروژه می‌نویسه
و بعد از ریبوت سرور هم می‌مونه. خود ربات موقع استارت خودش همون فایل رو می‌خونه

    python3 teriaky_set.py TERIAKY_TOKEN 123456:AAAA...
    python3 teriaky_set.py TERIAKY_ADMIN_IDS 1001,1003
    python3 teriaky_set.py TERIAKY_DB "postgresql+asyncpg://user:pass@localhost:5432/teriaky"
    python3 teriaky_set.py --list            (نمایش متغیرهای فعال فایل با ماسک توکن)

بعد از هر تغییر یه ری‌استارت لازمه: sudo systemctl restart teriaky
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")

MASK_KEYS = ("TOKEN", "PASS", "SECRET")  # اسم‌هایی که تو --list ماسک میشن


def _esc(val: str) -> str:
    """مقادیری که فاصله یا کاراکتر حساس دارن رو ساده کوتیشن می‌کنه"""
    if any(ch in val for ch in " #'\"$"):
        if '"' not in val:
            return f'"{val}"'
        if "'" not in val:
            return f"'{val}'"
    return val


def _key_of(line: str) -> str:
    """اسم متغیر یه خط فعال رو درمیاره، خط کامنت یا ناقص خالی برمی‌گردونه"""
    body = line.strip()
    if not body or body.startswith("#"):
        return ""
    if body.startswith("export "):
        body = body[len("export "):].lstrip()
    if "=" not in body:
        return ""
    return body.partition("=")[0].strip()


def set_var(key: str, value: str, path: str = ENV_PATH) -> bool:
    """
    KEY=VALUE رو توی فایل می‌نویسه: هست آپدیت میشه، نیس ته فایل اضافه میشه
    کامنت‌ها و بقیه خطوط دست‌نخورده می‌مونن، نوشتن اتمیکه، برمی‌گردونه True اگه آپدیت بود
    """
    key = key.strip()
    if not key or "=" in key or key.startswith("#") or " " in key:
        raise ValueError("bad key")
    lines = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    out, updated = [], False
    for line in lines:
        raw = line.strip("\r")
        if not updated and _key_of(raw) == key:
            out.append(f"{key}={_esc(value)}")
            updated = True
        else:
            out.append(raw)
    if not updated:
        out.append(f"{key}={_esc(value)}")
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, path)  # اتمیک: وسط کار فایل نصفه‌نیمه نمی‌مونه
    try:
        os.chmod(path, 0o600)  # توکن داخلشه، فقط مالک بخونه
    except OSError:
        pass
    return updated


def _read_active(path: str = ENV_PATH) -> list[tuple[str, str]]:
    """خطوط فعال فایل رو به شکل جفت کلید/مقدار برمی‌گردونه (برای --list)"""
    rows = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                key = _key_of(line)
                if not key:
                    continue
                val = line.strip().partition("=")[2].strip()
                rows.append((key, val))
    except (OSError, UnicodeError):
        pass
    return rows


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = ENV_PATH
    if "--file" in args:  # برای تست و حالتای خاص
        i = args.index("--file")
        path = args[i + 1]
        del args[i:i + 2]
    if not args or args[0] in ("-h", "--help", "help", "راهنما"):
        print(__doc__)
        return 0
    if args[0] in ("--list", "-l", "list", "لیست"):
        rows = _read_active(path)
        if not rows:
            print("ℹ️ فایل .env خالیه یا پیدا نشد")
            return 0
        for key, val in rows:
            shown = val
            if any(m in key for m in MASK_KEYS) and len(val) > 8:
                shown = val[:6] + "…"
            print(f"{key}={shown}")
        return 0
    if len(args) < 2:
        print("❌ مقدار رو هم بده، مثال: python3 teriaky_set.py TERIAKY_TOKEN 123456:AAAA")
        return 2
    key, value = args[0], " ".join(args[1:])
    try:
        updated = set_var(key, value, path)
    except ValueError:
        print("❌ اسم متغیر درست نیس (بدون فاصله و مساوی)")
        return 2
    verb = "آپدیت شد" if updated else "اضافه شد"
    print(f"✅ {key} {verb} تو {os.path.basename(path)} | برای اعمال: sudo systemctl restart teriaky")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
