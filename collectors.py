"""Collect via optional Telegram library, RSS, and official employer job board APIs."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timedelta, timezone

from http_utils import get_bytes, get_json
from settings import config, env
from storage import add_opportunity, get_state, set_state, source_exists, db, init_db
from transform import extract, plain_text
from opportunity_dates import source_is_recent, parse_deadline, reference_date
from image_assets import MEDIA_DIR
from telegram_media import source_image

LOG = logging.getLogger(__name__)


def keyword_match(text: str, cfg: dict) -> bool:
    terms = cfg.get('required_keywords') or []
    return not terms or any(term.lower() in text.lower() for term in terms)


def store(raw: str, source_key: str, source_name: str, source_url: str, cfg: dict,
          title_hint: str = '', fields: dict | None = None, source_html: str = '') -> bool:
    if not raw.strip() or not keyword_match(raw, cfg) or source_exists(source_key):
        return False
    data = extract(raw, source_name, source_url, title_hint)
    from grouped_posts import is_grouped, render_group, group_category
    if is_grouped(raw):
        data['category'] = group_category(raw)
        data['telegram_text'] = render_group(raw, source_html)
    if fields:
        data.update({k: v for k, v in fields.items() if v})
    data.update({'source_key': source_key, 'source_url': source_url,
                 'source_name': source_name, 'raw_text': raw[:14000]})
    from routing import opportunity_category
    data['category'] = opportunity_category(data)
    reference=reference_date(data.get('source_posted_at'))
    parsed=parse_deadline(raw,reference)
    if parsed:data['deadline']=parsed
    return add_opportunity(data)


def _rss_entries(raw: bytes, limit: int) -> list[dict]:
    """Support ordinary RSS 2.0 and Atom feeds without feedparser dependency."""
    root = ET.fromstring(raw)
    items = root.findall('./channel/item')
    if items:
        def value(node, tag):
            child = node.find(tag)
            return ''.join(child.itertext()).strip() if child is not None else ''
        return [{'id': value(item, 'guid'), 'title': value(item, 'title'),
                 'summary': value(item, 'description'), 'link': value(item, 'link')}
                for item in items[:limit]]
    atom = '{http://www.w3.org/2005/Atom}'
    entries = root.findall(f'{atom}entry')
    result = []
    for entry in entries[:limit]:
        def txt(tag):
            child = entry.find(f'{atom}{tag}')
            return ''.join(child.itertext()).strip() if child is not None else ''
        links = [child.attrib.get('href', '') for child in entry.findall(f'{atom}link')
                 if child.attrib.get('rel', 'alternate') == 'alternate']
        result.append({'id': txt('id'), 'title': txt('title'),
                       'summary': txt('summary') or txt('content'), 'link': links[0] if links else ''})
    return result


def _fetch_public_sources_serial(cfg: dict | None = None) -> int:
    cfg = cfg or config()
    max_items = max(1, min(300, int(cfg.get('max_items_per_source', 30))))
    total = 0
    for feed in cfg['rss_feeds']:
        try:
            entries = _rss_entries(get_bytes(feed), max_items)
            for entry in entries:
                url = entry['link']
                raw = f"{entry['title']}\n{plain_text(entry['summary'])}\n{url}"
                total += int(store(raw, f"rss:{feed}:{entry['id'] or url}", feed, url, cfg,
                                   title_hint=entry['title']))
        except Exception as exc:
            LOG.error('Could not collect RSS feed %s: %s', feed, exc)
    for slug in cfg['greenhouse_boards']:
        if not re.fullmatch(r'[\w-]{1,80}', slug):
            LOG.warning('Skipping invalid Greenhouse board slug: %s', slug)
            continue
        try:
            jobs = get_json(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs',
                            {'content': 'true'}).get('jobs', [])[:max_items]
            for job in jobs:
                url = job.get('absolute_url', '')
                desc = plain_text(job.get('content', ''))[:5500]
                location = (job.get('location') or {}).get('name') or ''
                raw = f"{job.get('title', '')}\n{slug}\nLocation: {location}\n{desc}\n{url}"
                total += int(store(raw, f"greenhouse:{slug}:{job['id']}", slug, url, cfg,
                                   title_hint=job.get('title', ''),
                                   fields={'organization': slug, 'location': location,
                                           'category': 'Job', 'apply_url': url}))
        except Exception as exc:
            LOG.error('Could not collect Greenhouse %s: %s', slug, exc)
    for site in cfg['lever_sites']:
        if not re.fullmatch(r'[\w-]{1,80}', site):
            LOG.warning('Skipping invalid Lever site: %s', site)
            continue
        try:
            jobs = get_json(f'https://api.lever.co/v0/postings/{site}',
                            {'mode': 'json', 'limit': max_items})
            for job in jobs[:max_items]:
                url = job.get('hostedUrl') or job.get('applyUrl') or ''
                categories = job.get('categories') or {}
                location = categories.get('location', '')
                desc = plain_text(job.get('descriptionPlain') or job.get('description', ''))[:5500]
                raw = f"{job.get('text', '')}\n{site}\nLocation: {location}\n{desc}\n{url}"
                total += int(store(raw, f"lever:{site}:{job['id']}", site, url, cfg,
                                   title_hint=job.get('text', ''),
                                   fields={'organization': site, 'location': location,
                                           'category': 'Job', 'apply_url': url}))
        except Exception as exc:
            LOG.error('Could not collect Lever %s: %s', site, exc)
    return total


def fetch_public_sources(cfg=None):
    """Fetch independent public sources concurrently; serialize writes in SQLite."""
    cfg = cfg or config()
    tasks = []
    keys = ('rss_feeds', 'greenhouse_boards', 'lever_sites')
    for key in keys:
        for source in cfg[key]:
            one = dict(cfg, **{k: [] for k in keys})
            one[key] = [source]
            tasks.append(one)
    if not tasks:
        return 0
    workers = max(1, min(8, int(cfg.get('public_source_workers', 4))))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return sum(pool.map(_fetch_public_sources_serial, tasks))


async def refresh_pending_source_dates(client, entity):
    # Backfill missing metadata in unsent legacy records without resending them.
    init_db()
    prefix=f'telegram:{entity.id}:'
    with db() as c:
        rows=c.execute(
            "SELECT id,source_key FROM opportunities o WHERE source_key LIKE ? "
            "AND source_posted_at='' AND status IN ('approved','review') "
            "AND NOT EXISTS (SELECT 1 FROM publications p WHERE p.opportunity_id=o.id) "
            "ORDER BY id LIMIT 100",(prefix+'%',)).fetchall()
    ids={int(row['source_key'].split(':')[-1]):row['id'] for row in rows
         if row['source_key'].split(':')[-1].isdigit()}
    if not ids:return
    messages=await client.get_messages(entity,ids=list(ids))
    with db() as c:
        for message in messages:
            if message and isinstance(getattr(message,'date',None),datetime) and message.id in ids:
                c.execute("UPDATE opportunities SET source_posted_at=? WHERE id=? AND source_posted_at=''",
                          (message.date.isoformat(),ids[message.id]))

async def fetch_telegram_async(cfg: dict | None = None) -> int:
    cfg = cfg or config()
    channels = cfg['telegram_channels']
    if not channels:
        return 0
    api_id, api_hash = env('TELEGRAM_API_ID'), env('TELEGRAM_API_HASH')
    if not api_id or not api_hash:
        LOG.warning('Skipping Telegram: set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env')
        return 0
    try:
        from telethon import TelegramClient
    except ImportError:
        LOG.error('Telegram collection library missing. Run: .venv\\Scripts\\python.exe -m pip install telethon')
        return 0
    session = Path(__file__).resolve().parent / 'data' / 'collector'
    session.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(session), int(api_id), api_hash, request_retries=1, connection_retries=1, timeout=15, flood_sleep_threshold=0)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            LOG.error('Telegram not signed in. Run: python setup_telegram.py')
            return 0
        total = 0
        collection_now = datetime.now(timezone.utc)
        cutoff = collection_now - timedelta(days=5)
        max_items = max(1, min(300, int(cfg.get('max_items_per_source', 30))))
        semaphore = asyncio.Semaphore(max(1, min(4, int(cfg.get("telegram_source_workers", 2)))))
        async def collect_channel(channel):
            async with semaphore:
                return await asyncio.wait_for(collect_channel_inner(channel), timeout=int(cfg.get("source_timeout_seconds", 50)))
        async def collect_channel_inner(channel):
            channel_total = 0
            try:
                entity = await client.get_entity(channel)
                await refresh_pending_source_dates(client, entity)
                cursor_key = f'telegram:last_id:{entity.id}'
                old_id = int(get_state(cursor_key, '0'))
                messages = [m async for m in client.iter_messages(entity, min_id=old_id, limit=max_items, reverse=True, offset_date=cutoff)]
                highest = old_id
                for msg in sorted(messages, key=lambda m: m.id):
                    highest = max(highest, msg.id)
                    if not source_is_recent(getattr(msg, 'date', None), collection_now):
                        continue
                    raw = (msg.raw_text or '')[:13000]
                    if not raw:
                        continue
                    extra_urls = [e.url for e in (msg.entities or []) if getattr(e, 'url', None)]
                    raw += '\n' + '\n'.join(extra_urls)
                    username = getattr(entity, 'username', '') or ''
                    url = f'https://t.me/{username}/{msg.id}' if username else ''
                    source_key = f'telegram:{entity.id}:{msg.id}'
                    media_name = ''
                    if not source_exists(source_key) and keyword_match(raw, cfg):
                        media_name = await source_image(client, entity, msg, messages)
                    channel_total += int(store(raw, source_key, channel, url, cfg,
                                       fields={'image_path': media_name, 'source_posted_at': msg.date.isoformat()},
                                       source_html=getattr(msg, 'text_html', '') or ''))
                if highest > old_id:
                    set_state(cursor_key, str(highest))
            except Exception as exc:
                LOG.error('Could not collect Telegram channel %s (%s)', channel, type(exc).__name__)
            return channel_total
        results = await asyncio.gather(*(collect_channel(channel) for channel in channels), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                LOG.warning('Telegram source timed out or failed (%s)', type(result).__name__)
            else:
                total += result
        return total
    finally:
        await client.disconnect()


def collect_all() -> dict:
    cfg = config()
    with ThreadPoolExecutor(max_workers=2) as pool:
        public_job = pool.submit(fetch_public_sources, cfg)
        telegram = asyncio.run(fetch_telegram_async(cfg))
        public = public_job.result()
    return {'public': public, 'telegram': telegram, 'total_new': public + telegram}
