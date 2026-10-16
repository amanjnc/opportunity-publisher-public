"""Explicit repair of unapproved, unpublished drafts. Never publishes."""
import argparse
import asyncio
import logging
import re
import sqlite3
from datetime import datetime

from settings import config, env, ROOT
from storage import get_opportunities, get_publications, update_opportunity, DB_PATH
from telegram_media import source_image
from transform import extract

LOG=logging.getLogger(__name__)


async def repair(images_only=False):
    claimed={p['opportunity_id'] for p in get_publications(1000000)}
    items=[o for o in get_opportunities('review',limit=100000) if o['id'] not in claimed]
    backup=ROOT/'data'/('before_draft_repair_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db')
    with sqlite3.connect(DB_PATH) as original, sqlite3.connect(backup) as saved:
        original.backup(saved)
    print(f'{len(items)} unapproved, unpublished drafts to repair. Database backed up.')
    client=None
    entities={}
    api_id,api_hash=env('TELEGRAM_API_ID'),env('TELEGRAM_API_HASH')
    if api_id and api_hash:
        try:
            from telethon import TelegramClient
            client=TelegramClient(str(ROOT/'data'/'collector'),int(api_id),api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                client=None
            else:
                for channel in config().get('telegram_channels',[]):
                    entity=await client.get_entity(channel)
                    entities[entity.id]=entity
        except Exception as exc:
            LOG.warning('Live Telegram refresh unavailable (%s). Saved text can still be repaired.',type(exc).__name__)
            if client:
                await client.disconnect()
            client=None
    count=photos=refreshed=0
    try:
        for opp in items:
            raw=opp.get('raw_text','')
            image=''
            match=re.fullmatch(r'telegram:(\d+):(\d+)',opp.get('source_key',''))
            if client and match:
                entity=entities.get(int(match.group(1)))
                if entity:
                    try:
                        msg=await client.get_messages(entity,ids=int(match.group(2)))
                        if msg:
                            text=msg.raw_text or ''
                            links=[e.url for e in (msg.entities or []) if getattr(e,'url',None)]
                            if text.strip():
                                raw=text+'\n'+'\n'.join(links)
                                refreshed+=1
                            image=await source_image(client,entity,msg)
                    except Exception as exc:
                        LOG.warning('Live lookup failed for #%s (%s); using saved text.',opp['id'],type(exc).__name__)
            changes={}
            if raw.strip() and not images_only:
                fresh=extract(raw,opp.get('source_name',''),opp.get('source_url',''))
                changes={key:fresh.get(key,'') for key in ('title','organization','category','location','deadline','deadline_note','eligibility','description','apply_url')}
                # Preserve verified fields when the new parser cannot recover them.
                for key in ('organization','eligibility','deadline','location','apply_url'):
                    if not changes[key] and opp.get(key) and not (key=='apply_url' and opp[key].startswith('https://t.me/')):
                        changes[key]=opp[key]
                changes.update(raw_text=raw,telegram_text='',linkedin_text='')
                count+=1
            if image:
                changes['image_path']=image
                photos+=1
            if changes:
                update_opportunity(opp['id'],changes)
        print(f'Finished: {count} drafts repaired, {refreshed} original messages refreshed, {photos} source images saved.')
        print('Nothing published. Reopen dashboard and refresh Review Inbox.')
        if not client:
            print('Telegram images were not checked. Stop worker/dashboard, check connection and retry this command.')
    finally:
        if client:
            await client.disconnect()


if __name__=='__main__':
    logging.basicConfig(level=logging.WARNING,format='%(message)s')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images-only',action='store_true')
    args=parser.parse_args()
    asyncio.run(repair(args.images_only))
