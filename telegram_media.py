"""Retrieve actual image media, including another item in the same album."""
import io
import logging
from pathlib import Path

from image_assets import MEDIA_DIR

LOG = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 20_000_000


def image_media(msg):
    if getattr(msg, 'photo', None):
        return msg
    doc = getattr(msg, 'document', None)
    if (getattr(doc, 'mime_type', '') or '').lower() in ('image/jpeg','image/png','image/webp'):
        return msg
    # Link previews are not source-attached images.
    return None


async def source_image(client, entity, msg, siblings=()):
    candidates = [msg]
    group = getattr(msg, 'grouped_id', None)
    if group:
        candidates += [m for m in siblings if m and m.id != msg.id and getattr(m, 'grouped_id', None) == group]
        if not any(image_media(m) for m in candidates):
            nearby = await client.get_messages(entity, ids=list(range(max(1,msg.id-16),msg.id+17)))
            candidates += [m for m in nearby if m and getattr(m,'grouped_id',None) == group]
    for candidate in candidates:
        media = image_media(candidate)
        if media is None:
            continue
        size = getattr(getattr(candidate, 'file', None),'size',0) or 0
        if size > MAX_IMAGE_BYTES:
            LOG.warning('Source image too large for message %s', candidate.id)
            continue
        try:
            binary = await client.download_media(media, file=bytes)
            if not isinstance(binary,bytes) or not binary or len(binary)>MAX_IMAGE_BYTES:
                continue
            from PIL import Image, ImageOps
            with Image.open(io.BytesIO(binary)) as im:
                if im.width * im.height > 40_000_000:
                    continue
                rgb=ImageOps.exif_transpose(im).convert('RGB')
                rgb.thumbnail((2000,2000))
                MEDIA_DIR.mkdir(parents=True,exist_ok=True)
                target=MEDIA_DIR/f'channel_{entity.id}_post_{candidate.id}.jpg'
                # Safe filenames, verified bytes, and a supported extension.
                rgb.save(target,format='JPEG',quality=90,optimize=True)
                return target.name
        except Exception as exc:
            LOG.warning('Source image lookup for message %s failed (%s)',candidate.id,type(exc).__name__)
    return ''
