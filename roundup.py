"""One imageless weekly Telegram digest; preview never sends anything."""
import argparse
import re
from datetime import datetime, timedelta
from html import escape, unescape

from dedup import find_match
from publish import TZ
from settings import config, enabled, env
from storage import db, init_db, utcnow


def post_link(channel, message_id):
    if not str(message_id).isdigit():
        return ''
    if re.fullmatch(r'@[A-Za-z][A-Za-z0-9_]{3,}', channel):
        return f'https://t.me/{channel[1:]}/{message_id}'
    if re.fullmatch(r'-100\d+', channel):
        return f'https://t.me/c/{channel[4:]}/{message_id}'
    return ''


def sync_roundup_destination():
    """Remember route aliases and migrate channel renames without mixing channels."""
    from routing import telegram_routes
    routes = telegram_routes()
    if 'general' not in routes:
        raise ValueError('TELEGRAM_TARGET_CHANNEL is required')
    init_db()
    migrated = []
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        records = c.execute("SELECT DISTINCT destination FROM publications WHERE platform='telegram' AND destination<>''").fetchall()
        destinations = {r[0].casefold() for r in records}
        guards = [dict(r) for r in c.execute('SELECT * FROM weekly_roundups')]
        known = {}
        for route in routes:
            row = c.execute('SELECT value FROM state WHERE key=?', ('telegram:route:'+route,)).fetchone()
            if row:
                known[route] = row[0]
        mappings = {old.casefold(): routes[route] for route, old in known.items()
                    if old.casefold() != routes[route].casefold()}
        # Upgrade the original one-channel history. Existing public messages remain
        # in their actual channel, even when their category is now routed elsewhere.
        if 'general' not in known:
            legacy = destinations - {v.casefold() for v in routes.values()} - set(mappings)
            if not destinations:
                legacy = {row['week_key'].rsplit(':',1)[0].casefold() for row in guards} - {v.casefold() for v in routes.values()}
            if len(legacy) > 1:
                raise ValueError('Multiple historical channels require explicit alias mapping')
            if legacy:
                mappings[next(iter(legacy))] = routes['general']
        for old, new in mappings.items():
            if old in {v.casefold() for v in routes.values()}:
                raise ValueError('Channel rename overlaps another active route')
            c.execute("UPDATE publications SET destination=? WHERE platform='telegram' AND lower(destination)=?", (new, old))
            for row in guards:
                prefix, week = row['week_key'].rsplit(':',1)
                if prefix.casefold() == old:
                    c.execute("""INSERT OR IGNORE INTO weekly_roundups
                        (week_key,status,text,remote_id,error,created_at) VALUES(?,?,?,?,?,?)""",
                        (new.casefold()+':'+week,row['status'],row['text'],row['remote_id'],row['error'],row['created_at']))
            migrated.append(old)
        c.execute("UPDATE publications SET destination=? WHERE platform='telegram' AND destination=''", (routes['general'],))
        for route, channel in routes.items():
            c.execute('INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', ('telegram:route:'+route,channel))
    return ','.join(migrated)


def build_roundup(now=None, channel=None):
    init_db()
    now = (now or datetime.now(TZ)).astimezone(TZ)
    monday = now.date() - timedelta(days=now.weekday())
    sunday = monday + timedelta(days=6)
    channel = channel or env('TELEGRAM_TARGET_CHANNEL')
    with db() as c:
        rows = c.execute("""SELECT o.*, p.remote_id FROM publications p
            JOIN opportunities o ON o.id=p.opportunity_id
            WHERE p.platform='telegram' AND p.status='posted'
            AND lower(p.destination)=lower(?)
            AND o.status<>'rejected' AND o.deadline>=? AND o.deadline<=?
            ORDER BY o.deadline, o.title, o.id""", (channel, monday.isoformat(), sunday.isoformat())).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        # Validate full ISO dates, not lexical approximations or rolling deadlines.
        try:
            deadline = datetime.strptime(item['deadline'], '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue
        if not monday <= deadline <= sunday or find_match(item, items):
            continue
        link = post_link(channel, item['remote_id'])
        if not link:
            raise ValueError('A published item has no usable channel post link. Fix its publication record before sending.')
        item['post_link'] = link
        items.append(item)
    if not items:
        return monday.isoformat(), '', 0
    def label(day):
        return f'{day:%B} {day.day}, {day.year}'
    lines = ['#Opportunity_Alerts📣', '', 'Good morning family🥰', '',
             '🌟 <b>Your Weekly Opportunity Roundup is here!</b>',
             f'📅 {label(monday)} – {label(sunday)}', '',
             'Already shared in our channel and closing this week. Tap a title for the full details 👇', '']
    for item in items:
        deadline = datetime.strptime(item['deadline'], '%Y-%m-%d').date()
        lines += [f'✍️ <a href="{escape(item["post_link"], quote=True)}">{escape(item["title"])}</a>',
                  f'{escape(item["category"] or "Opportunity")} · <b>Deadline: {label(deadline)}</b>', '']
    lines += ['Best of luck with your applications! ✨']
    text = '\n'.join(lines)
    # Conservatively count UTF-16 units after removing our HTML formatting.
    visible = unescape(re.sub(r'<[^>]*>', '', text))
    if len(visible.encode('utf-16-le')) // 2 > 4096:
        raise ValueError('Roundup exceeds Telegram’s single-message limit. Nothing sent; shorten titles/introduction before retrying. No opportunities were silently omitted.')
    return monday.isoformat(), text, len(items)


def _publish_channel_roundup(channel, now):
    now = (now or datetime.now(TZ)).astimezone(TZ)
    hour = int(config().get('roundup_hour', 8))
    if not 0 <= hour <= 23:
        raise ValueError('roundup_hour must be 0–23')
    if not enabled('AUTO_PUBLISH') or now.weekday() != 0 or now.hour < hour:
        return ''
    if not channel or not env('TELEGRAM_BOT_TOKEN'):
        return ''
    week = (now.date() - timedelta(days=now.weekday())).isoformat()
    key = channel.casefold() + ':' + week
    sync_roundup_destination()
    init_db()
    with db() as c:
        if c.execute('SELECT 1 FROM weekly_roundups WHERE week_key=?', (key,)).fetchone():
            return ''
    _, text, count = build_roundup(now, channel=channel)
    if not text:
        return ''
    # Atomic persistent claim: no automatic resend after ambiguous network outcomes.
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        cursor = c.execute('INSERT OR IGNORE INTO weekly_roundups(week_key,status,text,created_at) VALUES(?,?,?,?)',
                           (key, 'claim', text, utcnow()))
        if not cursor.rowcount:
            return ''
    try:
        from publish import send_telegram_text
        remote = send_telegram_text(text, channel=channel)
        with db() as c:
            c.execute("UPDATE weekly_roundups SET status='posted',remote_id=? WHERE week_key=?", (remote, key))
        return f'Weekly roundup posted to {channel}: {count} opportunities'
    except Exception as exc:
        with db() as c:
            c.execute("UPDATE weekly_roundups SET status='needs_review',error=? WHERE week_key=?", (str(exc)[:500], key))
        return 'Weekly roundup needs review; automatic resend blocked to avoid duplicates.'


def publish_roundup(now=None):
    from routing import telegram_routes
    now = (now or datetime.now(TZ)).astimezone(TZ)
    if not enabled('AUTO_PUBLISH') or now.weekday() != 0 or now.hour < int(config().get('roundup_hour', 8)):
        return ''
    results = []
    sync_roundup_destination()
    for channel in telegram_routes().values():
        try:
            result = _publish_channel_roundup(channel, now)
            if result:
                results.append(result)
        except Exception as exc:
            results.append('Weekly roundup could not be prepared for one channel: ' + type(exc).__name__)
    return '\n'.join(results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Preview only: does not publish')
    parser.add_argument('--date', help='Preview a week using YYYY-MM-DD')
    args = parser.parse_args()
    now = datetime.fromisoformat(args.date).replace(tzinfo=TZ) if args.date else None
    week, text, count = build_roundup(now)
    print(f'Week {week}: {count} opportunities\n{text or "No eligible published opportunities."}')
