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
    """Apply the authorized single-channel username rename to saved routing.
    
    Multiple historical destinations require explicit routing; never merge them.
    This does not send or edit any Telegram messages.
    """
    channel = env('TELEGRAM_TARGET_CHANNEL')
    if not post_link(channel, '1'):
        raise ValueError('Invalid TELEGRAM_TARGET_CHANNEL for roundup links')
    init_db()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        destinations = {r[0].casefold() for r in c.execute(
            "SELECT DISTINCT destination FROM publications WHERE platform='telegram' AND destination<>''")}
        keys = [dict(r) for r in c.execute('SELECT * FROM weekly_roundups')]
        if not destinations:
            destinations.update(row['week_key'].rsplit(':', 1)[0].casefold() for row in keys)
        previous = destinations - {channel.casefold()}
        if len(previous) > 1:
            raise ValueError('Multiple historical Telegram channels found; explicit roundup routing is required')
        old = next(iter(previous), '')
        if old:
            c.execute("UPDATE publications SET destination=? WHERE platform='telegram' AND lower(destination)=?",
                      (channel, old))
            for row in keys:
                prefix, week = row['week_key'].rsplit(':', 1)
                if prefix.casefold() != old:
                    continue
                # Retain old audit records; copy their send guard to the new alias.
                c.execute("""INSERT OR IGNORE INTO weekly_roundups
                    (week_key,status,text,remote_id,error,created_at) VALUES(?,?,?,?,?,?)""",
                    (channel.casefold()+':'+week,row['status'],row['text'],
                     row['remote_id'],row['error'],row['created_at']))
            # Keep a private audit breadcrumb, but do not treat it as another channel.
            c.execute("INSERT INTO state(key,value) VALUES('roundup:previous_destination',?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (old,))
        c.execute("UPDATE publications SET destination=? WHERE platform='telegram' AND destination=''", (channel,))
    return old


def build_roundup(now=None):
    init_db()
    now = (now or datetime.now(TZ)).astimezone(TZ)
    monday = now.date() - timedelta(days=now.weekday())
    sunday = monday + timedelta(days=6)
    channel = env('TELEGRAM_TARGET_CHANNEL')
    with db() as c:
        rows = c.execute("""SELECT o.*, p.remote_id FROM publications p
            JOIN opportunities o ON o.id=p.opportunity_id
            WHERE p.platform='telegram' AND p.status='posted'
            AND (p.destination='' OR lower(p.destination)=lower(?))
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


def publish_roundup(now=None):
    now = (now or datetime.now(TZ)).astimezone(TZ)
    hour = int(config().get('roundup_hour', 8))
    if not 0 <= hour <= 23:
        raise ValueError('roundup_hour must be 0–23')
    if not enabled('AUTO_PUBLISH') or now.weekday() != 0 or now.hour < hour:
        return ''
    channel = env('TELEGRAM_TARGET_CHANNEL')
    if not channel or not env('TELEGRAM_BOT_TOKEN'):
        return ''
    week = (now.date() - timedelta(days=now.weekday())).isoformat()
    key = channel.casefold() + ':' + week
    sync_roundup_destination()
    init_db()
    with db() as c:
        if c.execute('SELECT 1 FROM weekly_roundups WHERE week_key=?', (key,)).fetchone():
            return ''
    _, text, count = build_roundup(now)
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
        remote = send_telegram_text(text)
        with db() as c:
            c.execute("UPDATE weekly_roundups SET status='posted',remote_id=? WHERE week_key=?", (remote, key))
        return f'Weekly roundup posted: {count} opportunities'
    except Exception as exc:
        with db() as c:
            c.execute("UPDATE weekly_roundups SET status='needs_review',error=? WHERE week_key=?", (str(exc)[:500], key))
        return 'Weekly roundup needs review; automatic resend blocked to avoid duplicates.'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Preview only: does not publish')
    parser.add_argument('--date', help='Preview a week using YYYY-MM-DD')
    args = parser.parse_args()
    now = datetime.fromisoformat(args.date).replace(tzinfo=TZ) if args.date else None
    week, text, count = build_roundup(now)
    print(f'Week {week}: {count} opportunities\n{text or "No eligible published opportunities."}')
