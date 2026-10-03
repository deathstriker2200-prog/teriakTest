"""ساخت کارت تصویری مینیمال پروفایل با هویت طلایی/سرمه‌ای تریاکی."""

from __future__ import annotations

import io
import threading
import unicodedata
from functools import lru_cache
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

WIDTH = 1280
HEIGHT = 720

_ROOT = Path(__file__).resolve().parents[1]
_ASSET_DIR = _ROOT / "assets" / "profile"
_LOGO_PATH = _ASSET_DIR / "teriaky_logo.jpg"
_FONT_REGULAR = _ASSET_DIR / "Vazirmatn-Regular.ttf"
_FONT_BOLD = _ASSET_DIR / "Vazirmatn-Bold.ttf"

# یک FreeTypeFont هم‌زمان بین threadها مصرف نشود؛ رندر کوتاه است و این قفل امن‌تر است.
_RENDER_LOCK = threading.Lock()

NAVY = (38, 53, 79, 255)
NAVY_SOFT = (67, 82, 106, 255)
GOLD = (222, 156, 37, 255)
GOLD_DARK = (178, 112, 15, 255)
CREAM = (248, 244, 237, 255)
PANEL = (255, 253, 249, 232)
PANEL_LINE = (224, 210, 184, 255)
MUTED = (116, 119, 124, 255)
WHITE = (255, 255, 255, 255)

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_ROLE_NAMES = {"owner": "رهبر", "admin": "مدیر", "member": "عضو"}


def sanitize_text(value: object, max_chars: int, fallback: str = "—") -> str:
    """متن تک‌خط امن؛ کنترل/ایموجی حذف و طول برای قاب محدود می‌شود."""
    text = " ".join(str(value or "").replace("\u200f", " ").replace("\u200e", " ").split())
    clean: list[str] = []
    for ch in text:
        category = unicodedata.category(ch)
        if category.startswith("C") and ch != "\u200c":
            continue
        # فونت فارسی کارت color-emoji ندارد؛ حذفشان از مربع خالی شیک‌تر است.
        if category == "So":
            continue
        clean.append(ch)
    text = "".join(clean).strip()
    if not text:
        text = fallback
    if len(text) > max_chars:
        text = text[: max(1, max_chars - 1)].rstrip() + "…"
    return text


def fa_number(value: object) -> str:
    """عدد کامل با جداکننده هزارگان فارسی؛ مقدار واقعی خلاصه یا گرد نمی‌شود."""
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        number = 0
    return f"{number:,}".replace(",", "٬").translate(_FA_DIGITS)


def role_name(value: object) -> str:
    return _ROLE_NAMES.get(str(value or ""), "بدون نقش")


def _has_rtl(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


def _display(text: object) -> str:
    value = str(text or "")
    if not _has_rtl(value):
        return value
    return get_display(arabic_reshaper.reshape(value))


@lru_cache(maxsize=96)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    # BASIC اجباری است چون shaping/bidi را خودمان انجام می‌دهیم؛ RAQM دوباره RTL را برمی‌گرداند.
    return ImageFont.truetype(
        str(_FONT_BOLD if bold else _FONT_REGULAR),
        size=size,
        layout_engine=ImageFont.Layout.BASIC,
    )


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> float:
    box = draw.textbbox((0, 0), _display(text), font=font)
    return float(box[2] - box[0])


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_size: int,
    min_size: int,
    *,
    bold: bool = False,
) -> ImageFont.FreeTypeFont:
    for size in range(max_size, min_size - 1, -2):
        font = _font(size, bold)
        if _text_width(draw, text, font) <= max_width:
            return font
    return _font(min_size, bold)


def _draw_rtl(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: object,
    font: ImageFont.FreeTypeFont,
    fill,
    *,
    anchor: str = "ra",
) -> None:
    draw.text(xy, _display(text), font=font, fill=fill, anchor=anchor)


def _rounded_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=22, fill=PANEL, outline=PANEL_LINE, width=2)
    draw.rounded_rectangle((x2 - 10, y1 + 18, x2 - 5, y1 + 55), radius=3, fill=GOLD)
    _draw_rtl(draw, (x2 - 24, y1 + 31), title, _font(25, True), NAVY, anchor="ra")


def _stat_row(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    label: str,
    value: object,
    *,
    value_color=NAVY,
) -> None:
    label_font = _font(19, False)
    value_text = str(value)
    value_font = _fit_font(draw, value_text, width - 145, 24, 11, bold=True)
    _draw_rtl(draw, (x + width - 22, y), label, label_font, MUTED, anchor="ra")
    # مقدار سمت چپ با عرض پویا؛ برای فارسی هم anchor راست نسبت به مرز میانی ثابت می‌ماند.
    if _has_rtl(value_text):
        _draw_rtl(draw, (x + width - 148, y), value_text, value_font, value_color, anchor="ra")
    else:
        draw.text((x + 22, y), value_text, font=value_font, fill=value_color, anchor="la")


@lru_cache(maxsize=1)
def _base_background() -> Image.Image:
    image = Image.new("RGBA", (WIDTH, HEIGHT), CREAM)
    draw = ImageDraw.Draw(image, "RGBA")

    # گرادیان بسیار نرم کرم؛ ظاهر تمیز لوگو را نگه می‌دارد.
    for y in range(HEIGHT):
        mix = y / max(1, HEIGHT - 1)
        color = (
            round(252 - 7 * mix),
            round(249 - 8 * mix),
            round(243 - 7 * mix),
            255,
        )
        draw.line((0, y, WIDTH, y), fill=color)

    logo = Image.open(_LOGO_PATH).convert("RGB").resize((590, 590), Image.Resampling.LANCZOS)
    logo = logo.filter(ImageFilter.GaussianBlur(0.25)).convert("RGBA")
    logo.putalpha(Image.new("L", logo.size, 58))
    image.alpha_composite(logo, (345, 70))

    # نور طلایی بسیار کم در گوشه‌ها.
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    gd.ellipse((-150, -260, 500, 380), fill=(242, 178, 51, 28))
    gd.ellipse((930, 480, 1420, 920), fill=(42, 57, 83, 18))
    glow = glow.filter(ImageFilter.GaussianBlur(70))
    image.alpha_composite(glow)

    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((22, 22, WIDTH - 22, HEIGHT - 22), radius=36, outline=(218, 151, 31, 230), width=4)
    draw.rounded_rectangle((30, 30, WIDTH - 30, HEIGHT - 30), radius=31, outline=(255, 255, 255, 170), width=2)
    draw.rounded_rectangle((48, 39, 240, 45), radius=3, fill=GOLD)
    return image


def render_profile_card(data: dict) -> bytes:
    """یک JPEG معتبر 1280×720 از snapshot ساده و thread-safe پروفایل می‌سازد."""
    with _RENDER_LOCK:
        image = _base_background().copy()
        draw = ImageDraw.Draw(image, "RGBA")

        name = sanitize_text(data.get("name"), 32, "بازیکن تریاکی")
        username = sanitize_text(data.get("username"), 32, "بدون یوزرنیم")
        title = sanitize_text(data.get("title"), 28, "عضو تریاکی")

        # هدر هویت
        name_font = _fit_font(draw, name, 760, 56, 30, bold=True)
        _draw_rtl(draw, (WIDTH - 62, 69), name, name_font, NAVY, anchor="ra")
        sub = f"{title}  |  {username}"
        sub_font = _fit_font(draw, sub, 760, 24, 17)
        _draw_rtl(draw, (WIDTH - 64, 125), sub, sub_font, NAVY_SOFT, anchor="ra")

        draw.text((62, 69), "TERIAKY", font=_font(28, True), fill=NAVY, anchor="la")
        draw.text((199, 72), "BOT", font=_font(20, True), fill=GOLD_DARK, anchor="la")
        draw.text((62, 108), "PLAYER PROFILE", font=_font(15), fill=MUTED, anchor="la")

        # نوار XP
        bar_x1, bar_y1, bar_x2, bar_y2 = 48, 166, WIDTH - 48, 202
        draw.rounded_rectangle((bar_x1, bar_y1, bar_x2, bar_y2), radius=18, fill=(231, 226, 216, 235))
        xp = max(0, int(data.get("xp") or 0))
        xp_need = max(0, int(data.get("xp_need") or 0))
        max_level = bool(data.get("max_level"))
        ratio = 1.0 if max_level else min(1.0, xp / max(1, xp_need))
        fill_x = bar_x1 + round((bar_x2 - bar_x1) * ratio)
        if fill_x > bar_x1:
            draw.rounded_rectangle((bar_x1, bar_y1, max(bar_x1 + 36, fill_x), bar_y2), radius=18, fill=GOLD)
        level_text = f"لول {fa_number(data.get('level'))}"
        xp_text = "بالاترین لول" if max_level else f"XP  {fa_number(xp)} / {fa_number(xp_need)}"
        _draw_rtl(draw, (bar_x2 - 18, 184), level_text, _font(20, True), NAVY, anchor="rm")
        draw.text((bar_x1 + 18, 184), _display(xp_text), font=_font(18, True), fill=NAVY, anchor="lm")

        col_w = 370
        cols = (45, 455, 865)
        top_y, top_h = 226, 218
        bottom_y, bottom_h = 466, 207

        # ردیف اول: نبرد | منابع | دارایی (چیدمان بصری چپ به راست)
        _rounded_panel(draw, (cols[0], top_y, cols[0] + col_w, top_y + top_h), "قدرت")
        _stat_row(draw, cols[0], top_y + 76, col_w, "حمله", fa_number(data.get("attack")))
        _stat_row(draw, cols[0], top_y + 120, col_w, "دفاع", fa_number(data.get("defense")))
        _stat_row(draw, cols[0], top_y + 164, col_w, "قدرت کل", fa_number(data.get("power")), value_color=GOLD_DARK)

        _rounded_panel(draw, (cols[1], top_y, cols[1] + col_w, top_y + top_h), "منابع")
        _stat_row(draw, cols[1], top_y + 76, col_w, "چوب", fa_number(data.get("wood")))
        _stat_row(draw, cols[1], top_y + 120, col_w, "آهن", fa_number(data.get("iron")))
        rank_value = f"{fa_number(data.get('rank'))} از {fa_number(data.get('rank_total'))}"
        _stat_row(draw, cols[1], top_y + 164, col_w, "رتبه", rank_value, value_color=GOLD_DARK)

        _rounded_panel(draw, (cols[2], top_y, cols[2] + col_w, top_y + top_h), "دارایی")
        _stat_row(draw, cols[2], top_y + 76, col_w, "تی‌پوینت", fa_number(data.get("cash")))
        _stat_row(draw, cols[2], top_y + 120, col_w, "جم", fa_number(data.get("gems")))
        _stat_row(draw, cols[2], top_y + 164, col_w, "بانک", fa_number(data.get("bank")), value_color=GOLD_DARK)

        # ردیف دوم: رکورد | کارتل | سگ
        _rounded_panel(draw, (cols[0], bottom_y, cols[0] + col_w, bottom_y + bottom_h), "رکورد")
        _stat_row(draw, cols[0], bottom_y + 71, col_w, "برد", fa_number(data.get("wins")))
        _stat_row(draw, cols[0], bottom_y + 111, col_w, "باخت", fa_number(data.get("losses")))
        energy_value = f"{fa_number(data.get('energy'))} / {fa_number(data.get('energy_cap'))}"
        _stat_row(draw, cols[0], bottom_y + 151, col_w, "انرژی", energy_value, value_color=GOLD_DARK)

        _rounded_panel(draw, (cols[1], bottom_y, cols[1] + col_w, bottom_y + bottom_h), "کارتل")
        team_name = sanitize_text(data.get("team_name"), 24, "بدون کارتل")
        team_font = _fit_font(draw, team_name, col_w - 44, 29, 18, bold=True)
        _draw_rtl(draw, (cols[1] + col_w - 22, bottom_y + 90), team_name, team_font, NAVY, anchor="ra")
        _stat_row(draw, cols[1], bottom_y + 133, col_w, "نقش", role_name(data.get("team_role")), value_color=GOLD_DARK)

        _rounded_panel(draw, (cols[2], bottom_y, cols[2] + col_w, bottom_y + bottom_h), "سگ برتر")
        dog_name = sanitize_text(data.get("dog_name"), 24, "بدون سگ")
        dog_font = _fit_font(draw, dog_name, col_w - 44, 28, 18, bold=True)
        _draw_rtl(draw, (cols[2] + col_w - 22, bottom_y + 86), dog_name, dog_font, NAVY, anchor="ra")
        breed = sanitize_text(data.get("dog_breed"), 22, "—")
        dog_meta = f"{breed}  |  لول {fa_number(data.get('dog_level'))}"
        dog_meta_font = _fit_font(draw, dog_meta, col_w - 44, 19, 14)
        _draw_rtl(draw, (cols[2] + col_w - 22, bottom_y + 129), dog_meta, dog_meta_font, MUTED, anchor="ra")
        _stat_row(draw, cols[2], bottom_y + 158, col_w, "تعداد سگ", fa_number(data.get("dog_count")), value_color=GOLD_DARK)

        # شارپ‌سازی خیلی ملایم نوشته‌ها و خروجی سبک برای تلگرام.
        image = ImageEnhance.Sharpness(image.convert("RGB")).enhance(1.05)
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=94, optimize=True, progressive=True, subsampling=0)
        return out.getvalue()
