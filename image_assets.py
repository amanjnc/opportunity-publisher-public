"""Use verified source photos only. Missing photos stay text-only."""
from __future__ import annotations
import io
import re
from settings import ROOT
MEDIA_DIR = ROOT / 'data' / 'media'

def attachment_image(opp: dict) -> tuple[bytes, str, str] | None:
    """Return the verified source photo, or None. Never generate fallback images."""
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
    return None
