"""Command line entry: collect, work, publish a test, or display status."""
import argparse
import logging
import time
from datetime import datetime, timezone

from collectors import collect_all
from roundup import publish_roundup
from publish import allowed_platforms, publish_manual_test, publish_scheduled
from settings import config, enabled
from storage import get_opportunities, get_publications, get_state, init_db, set_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
LOG = logging.getLogger(__name__)


def run_worker():
    init_db()
    cfg = config()
    interval = max(5, int(cfg.get("collect_every_minutes", 30))) * 60
    print("Worker started. Press Ctrl+C to stop. Publishing enabled:", enabled("AUTO_PUBLISH"))
    print("Configured publishing platforms:", allowed_platforms())
    # The next collection is immediate, subsequent collections are periodic.
    last_collection = 0.0
    while True:
        now = time.time()
        try:
            roundup_result = publish_roundup()
            if roundup_result:
                print(roundup_result, flush=True)
            for message in publish_scheduled():
                if "no new approved" not in message:
                    print(message, flush=True)
        except Exception:
            LOG.exception("Publishing scheduler check failed")
        if now - last_collection >= interval:
            try:
                print("Collection result:", collect_all(), flush=True)
            except Exception:
                LOG.exception("Collection crashed; will try at next interval")
            last_collection = now
        time.sleep(20)


def main():
    parser = argparse.ArgumentParser(description="Opportunity Publisher")
    parser.add_argument("command", choices=("worker", "collect", "status", "test-publish"))
    parser.add_argument("--platform", choices=("telegram", "linkedin"), default="telegram")
    args = parser.parse_args()
    init_db()
    if args.command == "worker":
        try:
            run_worker()
        except KeyboardInterrupt:
            print("Worker stopped")
    elif args.command == "collect":
        print(collect_all())
    elif args.command == "test-publish":
        print(publish_manual_test(args.platform))
    elif args.command == "status":
        for status in ("review", "approved", "rejected"):
            print(status, len(get_opportunities(status, limit=100000)))
        print("Last 10 publications:")
        for pub in get_publications(10):
            print(pub["platform"], pub["status"], pub["title"], pub["error"])

if __name__ == "__main__":
    main()
