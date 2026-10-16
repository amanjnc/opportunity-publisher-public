"""Safe image selection: source Telegram photo -> generated branded PNG.

Pillow uses OS fonts at runtime; no font files are bundled/distributed.
Required for every scheduled post to carry an image.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from datetime import date

from settings import ROOT
from transform import deadline_display, CATEGORY_STYLES

MEDIA_DIR = ROOT / 'data' / 'media'


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    candidates = ([r'C:\Windows\Fonts\segoeuib.ttf',
                   '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'] if bold else
                  [r'C:\Windows\Fonts\segoeui.ttf',
                   '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'])
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _break_lines(draw, text, font, max_width, maximum=3):
    words = str(text).split()
    lines = []
    line = ''
    for word in words:
        candidate = f'{line} {word}'.strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
        if len(lines) >= maximum:
            break
    if len(lines) < maximum and line:
        lines.append(line)
    if len(lines) > maximum:
        lines = lines[:maximum]
    if len(lines) == maximum and len(' '.join(lines).split()) < len(words):
        while lines[-1] and draw.textbbox((0, 0), lines[-1] + '…', font=font)[2] > max_width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += '…'
    return lines


def branded_card(opp: dict) -> bytes:
    from PIL import Image, ImageDraw
    category = str(opp.get('category') or 'Other')
    title = str(opp.get('title') or 'New opportunity').strip()
    who = str(opp.get('eligibility') or 'Check requirements').strip()
    where = str(opp.get('location') or '').strip()
    deadline, urgency = deadline_display(str(opp.get('deadline') or ''))
    icon = CATEGORY_STYLES.get(category, CATEGORY_STYLES['Other'])[0][0]

    canvas = Image.new('RGB', (1200, 675), '#0F1C36')
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((28, 28, 1172, 647), radius=42, fill='#192D50')
    draw.rounded_rectangle((68, 70, 1132, 605), radius=34, fill='#FFFFFF')
    draw.rounded_rectangle((106, 108, 485, 170), radius=22, fill='#E7EFFC')
    draw.text((132, 120), category.upper() + '  |  OPPORTUNITY', font=_font(21, True), fill='#164791')
    draw.text((108, 200), 'YOUR NEXT OPPORTUNITY', font=_font(20, True), fill='#557195')
    title_font = _font(56 if len(title) < 55 else 45, True)
    for i, line in enumerate(_break_lines(draw, title, title_font, 975, maximum=3)):
        draw.text((105, 250 + i * 64), line, font=title_font, fill='#13233D')
    # The lower section is a fit-at-a-glance strip, not a picture of an unrelated job.
    draw.line((108, 468, 1093, 468), fill='#D8E2EE', width=3)
    draw.text((110, 487), 'WHO CAN APPLY', font=_font(18, True), fill='#547093')
    draw.text((110, 525), who[:34], font=_font(23, True), fill='#152949')
    if where:
        draw.text((480, 487), 'LOCATION', font=_font(18, True), fill='#547093')
        draw.text((480, 525), where[:27], font=_font(23, True), fill='#152949')
    draw.text((835, 487), 'DEADLINE', font=_font(18, True), fill='#547093')
    draw.text((835, 525), deadline[:20], font=_font(23, True), fill='#152949')
    if urgency:
        draw.text((840, 568), urgency.replace('🚨', '').replace('⏰', '').replace('🔥', '').replace('📌', '').strip()[:25],
                  font=_font(15, True), fill='#A03B3B')
    out = io.BytesIO()
    canvas.save(out, format='PNG', optimize=True)
    return out.getvalue()


def attachment_image(opp: dict) -> tuple[bytes, str, str]:
    """Return re-encoded source photo or generated PNG. No arbitrary disk paths."""
    rel = str(opp.get('image_path') or '')
    if re.fullmatch(r'[a-zA-Z0-9_-]+\.(?:jpg|jpeg|png|webp)', rel, re.I):
        path = MEDIA_DIR / rel
        if path.is_file() and path.stat().st_size <= 10_000_000:
            try:
                from PIL import Image, ImageOps
                with Image.open(path) as src:
                    src.verify()
                with Image.open(path) as src:
                    rgb = ImageOps.exif_transpose(src).convert('RGB')
                    rgb.thumbnail((1600, 1600))
                    out = io.BytesIO()
                    rgb.save(out, format='JPEG', quality=85, optimize=True)
                    return out.getvalue(), 'image/jpeg', 'opportunity.jpg'
            except Exception:
                pass
    return branded_card(opp), 'image/png', 'opportunity.png'
