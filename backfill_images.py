"""Compatibility entry point: source photo repair for unapproved drafts only."""
import asyncio
from repair_drafts import repair
if __name__ == '__main__':
    asyncio.run(repair(images_only=True))
