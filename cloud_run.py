"""One bounded cloud cycle. No sleeping worker, no interactive Telegram login."""
import logging
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime

from settings import config, enabled
from storage import db, init_db, update_opportunity, get_opportunities, get_state, set_state
from post_content import application_url
def collect_all():
    """Separate process provides a hard deadline, including stalled source threads."""
    seconds = min(180, max(10, int(config().get('cloud_work_seconds', 300)) - 120))
    result = subprocess.run([sys.executable, 'main.py', 'collect'], timeout=seconds, check=True)
    return {'collector_exit': result.returncode}

import publish
from roundup import publish_roundup, sync_roundup_destination

LOG = logging.getLogger(__name__)


def auto_approve():
    """Trusted configured sources only; never override rejected or duplicate records."""
    if not config().get('cloud_auto_approve', 0):
        return 0
    count = 0
    today = datetime.now(publish.TZ).date().isoformat()
    from opportunity_quality import publication_block_reason
    for item in get_opportunities('review', limit=2000):
        if publication_block_reason(item):
            continue
        deadline = item.get('deadline') or ''
        if deadline:
            try:
                datetime.strptime(deadline, '%Y-%m-%d')
            except ValueError:
                continue
            if deadline < today:
                continue
        if not application_url(item) or len(item['title'].strip()) < 12:
            continue
        if not (item.get('description') or item.get('raw_text')):
            continue
        try:
            update_opportunity(item['id'], {}, status='approved')
            count += 1
        except ValueError:
            pass
    return count


def report_queues():
    """Read-only diagnostics using the same eligibility rules as publishing."""
    from collections import Counter
    from dedup import find_match
    from opportunity_quality import publication_block_reason
    from routing import telegram_destination, telegram_routes
    from settings import config
    with db() as c:
        items = [dict(r) for r in c.execute("SELECT * FROM opportunities ORDER BY created_at,id")]
        attempts = {r['opportunity_id']: dict(r) for r in c.execute("SELECT * FROM publications WHERE platform='telegram'")}
    previous = [item for item in items if item['id'] in attempts]
    routes = telegram_routes()
    ready = {route: [] for route in routes}
    reasons = {route: Counter() for route in routes}
    priority = {str(x).strip().lstrip('@').casefold() for x in config().get('priority_telegram_channels', [])}
    items.sort(key=lambda item: str(item.get('source_name', '')).strip().lstrip('@').casefold() not in priority)
    for item in items:
        destination = telegram_destination(item)
        route = next((key for key,value in routes.items() if value == destination), 'unconfigured')
        if route not in reasons:
            reasons[route] = Counter()
        attempt = attempts.get(item['id'])
        if attempt:
            reason = 'previous attempt: ' + attempt['status']
        elif item['status'] == 'rejected':
            reason = 'rejected'
        elif not application_url(item):
            reason = 'missing application link'
        else:
            reason = publication_block_reason(item)
            if not reason and find_match(item, previous):
                reason = 'duplicate of previously attempted opportunity'
            if not reason and item['status'] != 'approved':
                reason = 'awaiting approval or duplicate review'
        try:
            collected_since = float(get_state('cloud:last_collection_attempt', '0'))
            created = datetime.fromisoformat(item['created_at']).timestamp()
        except (ValueError, TypeError):
            collected_since, created = float('inf'), 0
        if created >= collected_since:
            print('Latest collection item:', {'id': item['id'], 'title': item['title'],
                  'reason': reason or 'eligible'}, flush=True)
        if reason:
            reasons[route][reason] += 1
        elif route in ready:
            ready[route].append(item)
        if 'stability mechanism' in item['title'].casefold() or 'esm traineeship' in item['title'].casefold():
            print('ESM queue diagnostic:', {'id': item['id'], 'route': route, 'reason': reason or 'eligible'}, flush=True)
    for route in reasons:
        queue = ready.get(route, [])
        print('Queue diagnostic:', {'channel': route, 'eligible_waiting': len(queue),
              'excluded_counts': dict(reasons[route]),
              'next_posts': [{'rank': n, 'id': item['id'], 'title': item['title']} for n,item in enumerate(queue[:10],1)]}, flush=True)


def restore_requested_aixbio():
    """Repair the exact existing record confirmed by the owner; never resend."""
    url = 'https://opportunities.ohubet.com/opportunities/aixbio-research-fellowship-2027'
    marker = 'repair:user-requested-aixbio-2027:v1'
    if get_state(marker):
        return
    with db() as c:
        rows = c.execute("SELECT * FROM opportunities WHERE apply_url=? OR raw_text LIKE ? ORDER BY id",
                         (url, '%' + url + '%')).fetchall()
        if not rows:
            print('Requested AIxBio record not found; no replacement or duplicate created.', flush=True)
            return
        row = rows[0]
        if c.execute("SELECT 1 FROM publications WHERE opportunity_id=? AND platform='telegram'", (row['id'],)).fetchone():
            print('Requested AIxBio already attempted; publication history retained.', flush=True)
            set_state(marker, 'already-attempted')
            return
        c.execute("UPDATE opportunities SET title=?,category='Fellowship',deadline='2026-10-19',deadline_note='',apply_url=?,status='approved' WHERE id=?",
                  ('AIxBio Research Fellowship 2027 — Fully Funded £10,000 Fellowship in the UK', url, row['id']))
    set_state(marker, 'repaired')
    print('Requested AIxBio record restored to approved fellowship queue; normal expiry and duplicate checks still apply.', flush=True)


def recover_missing_application_links():
    """Re-extract links lost by old cleanup; never reset publication attempts."""
    from source_cleanup import clean_source
    from transform import preferred_url
    recovered = 0
    with db() as c:
        rows = c.execute(
            "SELECT * FROM opportunities o WHERE status IN ('review','approved') "
            "AND apply_url='' AND NOT EXISTS "
            "(SELECT 1 FROM publications p WHERE p.opportunity_id=o.id)"
        ).fetchall()
        for row in rows:
            item = dict(row)
            candidate = preferred_url(clean_source(item.get('raw_text', ''), item.get('source_name', '')))
            if candidate and application_url({'apply_url': candidate, 'source_url': item.get('source_url', '')}):
                c.execute("UPDATE opportunities SET apply_url=? WHERE id=? AND apply_url=''",
                          (candidate, item['id']))
                recovered += 1
    print('Recovered missing application links:', recovered, flush=True)


def run(checkpoint=None):
    init_db()
    sync_roundup_destination()
    cfg = config()
    budget = min(300, max(30, int(cfg.get('cloud_work_seconds', 300))))
    started = time.monotonic()
    def alarm(signum, frame):
        raise TimeoutError('Cloud work budget reached; saving progress and exiting.')
    # Linux Actions runner: stop collection even if many sources are slow.
    signal.signal(signal.SIGALRM, alarm)
    signal.alarm(budget)
    original_claim = publish.claim_next
    original_set = publish.set_publication
    import storage
    original_part = storage.record_publication_part
    def claimed(platform, slot, **kwargs):
        item = original_claim(platform, slot, **kwargs)
        if item and checkpoint:
            checkpoint()  # Durable reservation BEFORE sending. Failure prevents send.
        return item
    def completed(*args, **kwargs):
        original_set(*args, **kwargs)
        if checkpoint:
            checkpoint()
    def part(*args, **kwargs):
        original_part(*args, **kwargs)
        if checkpoint:
            checkpoint()
    publish.claim_next = claimed
    publish.set_publication = completed
    storage.record_publication_part = part
    try:
        # Reserve up to 120 seconds for publishing and state saves.
        signal.alarm(budget)
        last_collection = float(get_state('cloud:last_collection_success',
                                          get_state('cloud:last_collection_attempt', '0')))
        # Preserve the legacy successful baseline before recording a new attempt.
        if not get_state('cloud:last_collection_success'):
            set_state('cloud:last_collection_success', str(last_collection))
        collection_interval = max(5, int(cfg.get('collect_every_minutes', 120))) * 60
        if time.time() - last_collection >= collection_interval:
            # Persist attempt time before collecting, even if a source times out.
            collection_started = time.time()
            set_state('cloud:last_collection_attempt', str(collection_started))
            print('Collection started:', datetime.now(publish.TZ).isoformat(), flush=True)
            if checkpoint:
                checkpoint()
            try:
                print('Collection:', collect_all(), flush=True)
                set_state('cloud:last_collection_success', str(collection_started))
                print('Collection completed:', datetime.now(publish.TZ).isoformat(), flush=True)
            except (TimeoutError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
                print('Collection stopped; collected records retained:', type(exc).__name__, flush=True)
        else:
            print('Collection not due; using the saved queue.', flush=True)
        signal.alarm(max(1, int(budget - (time.monotonic() - started))))
        restore_requested_aixbio()
        recover_missing_application_links()
        print('Automatically approved:', auto_approve(), flush=True)
        report_queues()
        if not enabled('AUTO_PUBLISH'):
            print('Publishing disabled; collection-only run.')
            return
        if checkpoint:
            checkpoint()
        # One FIFO opportunity per destination on every workflow invocation.
        from routing import telegram_routes
        # Retries of the same GitHub run reuse the claim; distinct runs may post immediately.
        slot = os.environ.get('GITHUB_RUN_ID') or uuid.uuid4().hex
        for platform in publish.allowed_platforms():
            destinations = list(telegram_routes().items()) if platform == 'telegram' else [('linkedin', None)]
            for route, destination in destinations:
                if time.monotonic() - started > budget - 55:
                    return
                message = publish.publish_one(platform, f'queue:{slot}:{route}', destination=destination)
                print(f'{route}: {message}', flush=True)
        if time.monotonic() - started < budget - 45:
            # Persist roundup claim before its network send as well.
            import roundup
            original_send = publish.send_telegram_text
            def send_roundup(text, **kwargs):
                if checkpoint:
                    checkpoint()
                return original_send(text, **kwargs)
            publish.send_telegram_text = send_roundup
            try:
                print(publish_roundup(), flush=True)
            finally:
                publish.send_telegram_text = original_send
    finally:
        signal.alarm(0)
        publish.claim_next = original_claim
        publish.set_publication = original_set
        storage.record_publication_part = original_part
        print(f'Cycle elapsed: {time.monotonic() - started:.1f}s', flush=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if not os.path.exists('.cloud-restored'):
        raise SystemExit('Restore encrypted state first. Refusing to run without publication history.')
    from cloud_state import save
    try:
        run(checkpoint=save)
    finally:
        save()
    from pathlib import Path
    Path('.cloud-cycle-complete').write_text('ok')
