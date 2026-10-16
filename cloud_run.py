"""One bounded cloud cycle. No sleeping worker, no interactive Telegram login."""
import logging
import os
import signal
import subprocess
import sys
import time
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
    for item in get_opportunities('review', limit=2000):
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
        last_collection = float(get_state('cloud:last_collection_attempt', '0'))
        if time.time() - last_collection >= 30 * 60:
            # Persist attempt time before collecting, even if a source times out.
            set_state('cloud:last_collection_attempt', str(time.time()))
            if checkpoint:
                checkpoint()
            try:
                print('Collection:', collect_all(), flush=True)
            except (TimeoutError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
                print('Collection stopped; collected records retained:', type(exc).__name__, flush=True)
        else:
            print('Collection not due; using the saved queue.', flush=True)
        signal.alarm(max(1, int(budget - (time.monotonic() - started))))
        print('Automatically approved:', auto_approve(), flush=True)
        if not enabled('AUTO_PUBLISH'):
            print('Publishing disabled; collection-only run.')
            return
        if checkpoint:
            checkpoint()
        now = datetime.now(publish.TZ)
        # One FIFO opportunity per destination, with stable five-minute slots.
        from routing import telegram_routes
        slot = now.strftime('%Y-%m-%d-%H-') + f'{(now.minute // 5) * 5:02d}'
        for platform in publish.allowed_platforms():
            destinations = list(telegram_routes().items()) if platform == 'telegram' else [('linkedin', None)]
            for route, destination in destinations:
                if time.monotonic() - started > budget - 55:
                    return
                message = publish.publish_one(platform, f'queue:{slot}:{route}', destination=destination)
                print(message, flush=True)
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
