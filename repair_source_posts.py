"""Owner-requested repairs of two identified Telegram publications; never resend."""
from settings import env
from storage import db, get_state, set_state
from http_utils import post_json
from source_cleanup import clean_source
from message_layout import telegram_layout
from grouped_posts import split_messages
from transform import format_post


def telegram_action(method, payload):
    result, _ = post_json('https://api.telegram.org/bot'+env('TELEGRAM_BOT_TOKEN')+'/'+method,
                          payload, timeout=25)
    if not result.get('ok'):
        raise RuntimeError('Telegram did not confirm requested post repair')


def repair_requested_posts(checkpoint=None):
    # Exact IDs and titles were identified in the owner's 00:15 and 00:30 runs.
    for oid, expected, remove in [(295, 'IELTS Preparation Class + IELTS Exam Booking!', True),
                                  (318, 'EUROPEAN STABILITY MECHANISM', False)]:
        marker=f'repair:source-promotion:v1:{oid}'
        if get_state(marker):
            continue
        with db() as c:
            row=c.execute('SELECT o.*, p.destination, p.remote_id FROM opportunities o JOIN publications p ON p.opportunity_id=o.id WHERE o.id=? AND p.platform=? AND p.status=?',
                          (oid,'telegram','posted')).fetchone()
            if not row or expected.casefold() not in row['title'].casefold():
                continue
            item=dict(row)
            parts=[dict(r) for r in c.execute('SELECT * FROM publication_parts WHERE opportunity_id=? AND platform=? ORDER BY id',(oid,'telegram'))]
        # Never infer a historical destination from current routing.
        if not item['destination'] or not parts:
            print(f'Repair #{oid}: historical message parts/destination unavailable; no action taken.',flush=True)
            continue
        if not remove:
            # Render from original facts, discarding stale extracted promotional fields.
            from transform import basic_extract
            fresh=basic_extract(item['raw_text'], item.get('source_name',''), item.get('apply_url',''))
            item.update(fresh)
            item['telegram_text']=''
            item['raw_text']=clean_source(item['raw_text'],item.get('source_name',''))
            item['category']='Internship'
            text=format_post(item,'telegram')
            if parts[0]['kind']=='photo':
                caption, continuations=telegram_layout(text)
                replacements=[caption]+continuations
            else:
                replacements=split_messages(text)
            if len(replacements)>len(parts):
                print(f'Repair #{oid}: cleaned text needs additional messages; held without truncation.',flush=True)
                continue
        for index, part in enumerate(parts):
            done=f'{marker}:message:{part["remote_id"]}'
            if get_state(done):
                continue
            payload={'chat_id':item['destination'],'message_id':int(part['remote_id'])}
            if remove or index>=len(replacements):
                method='deleteMessage'
            else:
                method='editMessageCaption' if part['kind']=='photo' else 'editMessageText'
                payload.update({'caption' if part['kind']=='photo' else 'text':replacements[index], 'parse_mode':'HTML'})
                if method=='editMessageText':payload['link_preview_options']={'is_disabled':True}
            telegram_action(method,payload)
            set_state(done,'confirmed')
            if checkpoint:checkpoint()
        if remove:
            with db() as c:
                c.execute("UPDATE opportunities SET status='rejected' WHERE id=?",(oid,))
                c.execute("UPDATE publications SET status='removed',error='Owner requested removal of promotional service advertisement' WHERE opportunity_id=? AND platform='telegram'",(oid,))
        set_state(marker,'confirmed')
        if checkpoint:checkpoint()
        print(f'Repair #{oid}: '+('promotional post removed.' if remove else 'published traineeship cleaned.'),flush=True)
