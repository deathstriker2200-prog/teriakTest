"""مصرف لحظه‌ای سرور 🖥 (راند ۱۷، درخواست کارفرما: CPU و رم و دیسک توی آمار ادمین)

بدون دیپندنسی، از /proc لینوکس و shutil استاندارد | روی غیرلینوکس None برمی‌گردونه
تا سکشن سرور توی آمار اصلاً نیاد و چیزی نمی‌شکنه
"""

import os
import shutil

from utils import fa_num


def server_usage() -> dict | None:
    """دیکشنری مصرف سرور یا None: لود CPU و درصد بر اساس هسته | رم و دیسک به گیگ | آپتایم فارسی"""
    try:
        cores = os.cpu_count() or 1
        load1, load5, load15 = os.getloadavg()
    except (OSError, AttributeError):
        return None

    mem_total_kb = mem_avail_kb = None
    try:
        with open("/proc/meminfo", encoding="ascii", errors="ignore") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem_avail_kb = int(line.split()[1])
    except (OSError, ValueError):
        return None
    if not mem_total_kb or mem_avail_kb is None:
        return None
    mem_used_kb = mem_total_kb - mem_avail_kb

    disk = shutil.disk_usage("/")

    uptime_s = 0.0
    try:
        with open("/proc/uptime", encoding="ascii") as f:
            uptime_s = float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        uptime_s = 0.0

    up_days = int(uptime_s // 86400)
    up_hours = int((uptime_s % 86400) // 3600)
    up_min = int((uptime_s % 3600) // 60)
    uptime_fa = (
        f"{fa_num(up_days)} روز و {fa_num(up_hours)} ساعت" if up_days
        else f"{fa_num(up_hours)} ساعت و {fa_num(up_min)} دقیقه"
    )

    return {
        "cores": cores,
        "load1": round(load1, 2),
        "load5": round(load5, 2),
        "load15": round(load15, 2),
        "cpu_pct": round(load1 / cores * 100),
        "mem_total_gb": f"{mem_total_kb / 1048576:.1f}",
        "mem_used_gb": f"{mem_used_kb / 1048576:.1f}",
        "mem_pct": round(mem_used_kb * 100 / mem_total_kb),
        "disk_total_gb": f"{disk.total / 1073741824:.1f}",
        "disk_used_gb": f"{disk.used / 1073741824:.1f}",
        "disk_pct": round(disk.used * 100 / disk.total),
        "uptime_s": uptime_s,
        "uptime_fa": uptime_fa,
    }
