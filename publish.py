"""Image-first Telegram publishing + permitted LinkedIn Image and Posts APIs."""
from __future__ import annotations

import json
import logging
import uuid
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from http_utils import post_json
from image_assets import attachment_image
from settings import config, enabled, env
from storage import claim_next, set_publication
from transform import format_post
from message_layout import telegram_layout, visible_units
from post_content import application_url

LOG = logging.getLogger(__name__)
TZ = timezone(timedelta(hours=3), 'Africa/Addis_Ababa')


def send_telegram(text: str, photo: tuple[bytes,str,str] | None = None, on_part=None, *, channel: str | None = None) -> str:
    """Use sendPhoto so every publication has both a picture and a bold caption."""
    token, channel = env('TELEGRAM_BOT_TOKEN'), channel or env('TELEGRAM_TARGET_CHANNEL')
    if not token or not channel:
        raise RuntimeError('Telegram bot token and destination channel must be configured in .env')
    if photo is None:
        raise RuntimeError('Image required for Telegram post')
    binary, mimetype, filename = photo
    if len(binary) > 9_000_000:
        raise RuntimeError('Image is too large to upload')
    caption, continuations = telegram_layout(text)
    boundary = 'boundary' + uuid.uuid4().hex
    def field(name: str, value: str) -> bytes:
        return (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode('utf-8')
    body = b''.join([field('chat_id', channel), field('caption', caption),
                     field('parse_mode', 'HTML'),
                     (f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="{filename}"\r\n'
                      f'Content-Type: {mimetype}\r\n\r\n').encode(),
                     binary, b'\r\n', f'--{boundary}--\r\n'.encode()])
    req = Request(f'https://api.telegram.org/bot{token}/sendPhoto', data=body,
                  headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}, method='POST')
    try:
        with urlopen(req, timeout=40) as response:
            raw = response.read(300000)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                preview = raw[:400].decode("utf-8", "replace")
                preview = preview.replace(token, "[TOKEN HIDDEN]")
                raise RuntimeError(
                    f"Unexpected response: HTTP {response.status}; "
                    f"Content-Type: {response.headers.get('Content-Type')}; "
                    f"Body: {preview!r}"
                ) from None
    except HTTPError as error:
        raise RuntimeError(f'Telegram API HTTP {error.code} (token hidden): '
                           f'{error.read(180).decode("utf-8", "replace")}') from None
    except URLError as error:
        raise RuntimeError(f'Telegram connection failed: {error.reason}') from None
    if not data.get('ok'):
        raise RuntimeError(data.get('description', 'Telegram rejected photo'))
    photo_id = str(data.get('result', {}).get('message_id', ''))
    if not photo_id.isdigit():
        raise RuntimeError('Telegram did not confirm a photo message ID')
    if on_part:
        on_part(photo_id, 'photo')
    first_detail_id = ''
    for continuation in continuations:
        time.sleep(1.05)
        detail_id = send_telegram_text(continuation, channel=channel)
        if not first_detail_id:
            first_detail_id = detail_id
        if on_part:
            on_part(detail_id, 'details')
    # Roundups open the full detail message when a continuation was required.
    return first_detail_id or photo_id



def send_telegram_text(text: str, *, channel: str | None = None) -> str:
    """Detailed posts and roundups: HTML text with link previews disabled."""
    token, channel = env('TELEGRAM_BOT_TOKEN'), channel or env('TELEGRAM_TARGET_CHANNEL')
    if not token or not channel:
        raise RuntimeError('Telegram destination and bot token are required')
    if not 0 < visible_units(text) <= 4096:
        raise RuntimeError('Telegram text must fit in one message; nothing was truncated')
    data, _ = post_json(f'https://api.telegram.org/bot{token}/sendMessage',
                       {'chat_id': channel, 'text': text, 'parse_mode': 'HTML',
                        'link_preview_options': {'is_disabled': True}}, timeout=30)
    if not data.get('ok') or not str((data.get('result') or {}).get('message_id', '')).isdigit():
        raise RuntimeError('Telegram did not confirm a message ID')
    return str(data['result']['message_id'])

def _linkedin_headers(token: str, version: str) -> dict:
    return {'Authorization': f'Bearer {token}', 'Linkedin-Version': version,
            'X-Restli-Protocol-Version': '2.0.0'}


def _linkedin_upload(photo: tuple[bytes,str,str], author: str, token: str, version: str) -> str:
    data, _ = post_json('https://api.linkedin.com/rest/images?action=initializeUpload',
                        {'initializeUploadRequest': {'owner': author}},
                        headers=_linkedin_headers(token, version), timeout=35)
    info = data.get('value') or {}
    upload_url, urn = info.get('uploadUrl', ''), info.get('image', '')
    parts = urlsplit(upload_url)
    if parts.scheme != 'https' or not (parts.hostname and
       (parts.hostname.endswith('.linkedin.com') or parts.hostname == 'linkedin.com'
        or parts.hostname.endswith('.licdn.com') or parts.hostname == 'licdn.com')):
        raise RuntimeError('Unexpected LinkedIn image upload host')
    if not urn.startswith('urn:li:image:'):
        raise RuntimeError('LinkedIn did not provide a valid image URN')
    binary, mimetype, _ = photo
    req = Request(upload_url, data=binary, method='PUT', headers={
        'Authorization': f'Bearer {token}', 'Content-Type': mimetype})
    try:
        with urlopen(req, timeout=60) as response:
            if response.status not in (200, 201, 202, 204):
                raise RuntimeError(f'LinkedIn upload response {response.status}')
    except HTTPError as error:
        raise RuntimeError(f'LinkedIn image upload failed: HTTP {error.code}') from None
    except URLError as error:
        raise RuntimeError(f'LinkedIn image upload connection failed: {error.reason}') from None
    return urn


def send_linkedin(text: str, photo: tuple[bytes,str,str] | None = None) -> str:
    token, author, version = (env('LINKEDIN_ACCESS_TOKEN'), env('LINKEDIN_AUTHOR_URN'),
                              env('LINKEDIN_API_VERSION'))
    if not token or not author or not version:
        raise RuntimeError('LinkedIn API token, author URN and API version must be configured')
    if not (author.startswith('urn:li:person:') or author.startswith('urn:li:organization:')):
        raise RuntimeError('Invalid LinkedIn author URN')
    if photo is None:
        raise RuntimeError('Image required for LinkedIn post')
    if len(text) > 3000:
        raise RuntimeError('LinkedIn post exceeds 3000 characters. Review the full preview; nothing was truncated or uploaded.')
    urn = _linkedin_upload(photo, author, token, version)
    payload = {'author': author, 'commentary': text, 'visibility': 'PUBLIC',
               'distribution': {'feedDistribution': 'MAIN_FEED', 'targetEntities': [],
                                'thirdPartyDistributionChannels': []},
               'content': {'media': {'id': urn}},
               'lifecycleState': 'PUBLISHED', 'isReshareDisabledByAuthor': False}
    _, headers = post_json('https://api.linkedin.com/rest/posts', payload,
                           headers=_linkedin_headers(token, version), timeout=35)
    return headers.get('x-restli-id', headers.get('X-RestLi-Id', ''))


def publish_one(platform: str, slot_key: str) -> str:
    opportunity = claim_next(platform, slot_key)
    if not opportunity:
        return f'{platform}: no new approved opportunity or slot already used'
    try:
        if not application_url(opportunity):
            raise RuntimeError('Application link is missing or invalid; review before publishing')
        photo = attachment_image(opportunity)
        text = format_post(opportunity, platform)
        if platform == 'telegram':
            from storage import record_publication_part
            remote_id = send_telegram(text, photo, channel=opportunity['publication_destination'], on_part=lambda remote, kind: record_publication_part(opportunity['id'], platform, remote, kind))
        else:
            remote_id = send_linkedin(text, photo)
        set_publication(opportunity['id'], platform, 'posted', remote_id=remote_id)
        return f"{platform}: posted #{opportunity['id']} {opportunity['title']}"
    except Exception as exc:
        # No retry after uncertain outcome, to avoid duplicate public posts.
        set_publication(opportunity['id'], platform, 'failed', error=str(exc))
        LOG.exception('Publishing failed for %s #%s', platform, opportunity['id'])
        return f"{platform}: FAILED #{opportunity['id']} — {exc} (inspect before manual retry)"


def allowed_platforms() -> list[str]:
    result = []
    if env('TELEGRAM_BOT_TOKEN') and env('TELEGRAM_TARGET_CHANNEL'):
        result.append('telegram')
    if enabled('AUTO_LINKEDIN') and env('LINKEDIN_ACCESS_TOKEN') and env('LINKEDIN_AUTHOR_URN'):
        result.append('linkedin')
    return result


def scheduled_slot(now: datetime | None = None) -> str | None:
    now = (now or datetime.now(TZ)).astimezone(TZ)
    hours = config().get('publish_hours', [8, 10, 12, 14, 16, 18, 20])
    if now.hour not in hours or now.minute >= 30:
        return None
    return now.strftime('%Y-%m-%d-%H')


def publish_scheduled():
    if not enabled('AUTO_PUBLISH'):
        return []
    slot = scheduled_slot()
    if not slot:
        return []
    return [publish_one(platform, slot) for platform in allowed_platforms()]


def publish_manual_test(platform: str):
    if platform not in allowed_platforms():
        return f'{platform} not configured. See README.md'
    return publish_one(platform, 'manual-' + uuid.uuid4().hex)
