"""Screen promotional products and vague announcements before publication."""
import re
from source_cleanup import clean_source
from message_layout import visible_text
from urllib.parse import urlsplit


def publication_block_reason(opp):
    raw='\n'.join(str(opp.get(k) or '') for k in
                  ('title','description','raw_text','eligibility','location'))
    host=(urlsplit(str(opp.get('apply_url') or '')).hostname or '').lower()
    if any(host == root or host.endswith('.'+root) for root in
           ('tiktok.com','youtube.com','youtu.be','instagram.com','facebook.com','fb.com','twitter.com','x.com')):
        return 'Social-media content link is not an opportunity application page.'
    title=visible_text(str(opp.get('title') or ''))
    if re.search(r"(?i)\b(?:am|i['’]?m|we['’]?re|we are|going|now)\s+live\b|\blive (?:on|in) (?:tiktok|instagram|facebook|youtube)\b",title):
        return 'Livestream or personal status announcement; not an opportunity.'
    text=visible_text(clean_source(raw))
    text=re.sub(r'https?://\S+','',text)
    tool=bool(re.search(r'(?i)\b(?:free tool|web app|university finder|grad school finder|search tool|search platform|subscription|software trial)\b',text))
    access=bool(re.search(r'(?i)\b(?:free access|days? of free|first \d+|searches per|trial|request access|sign up|signups?|subscribe)\b',text))
    concrete_role=bool(re.search(r'(?i)\b(?:engineer|developer|officer|manager|assistant|intern|internship|research fellow)\b',str(opp.get('title') or '')))
    if tool and access and not concrete_role:
        return 'Promotional tool, subscription or limited-access offer; not a specific opportunity.'
    organization=str(opp.get('organization') or '').strip()
    if organization.casefold() in ('not specified','unknown','n/a','none','a professor','various','multiple'):
        organization=''
    named=bool(organization or re.search(
        r'(?im)\b(?:organization|organisation|institution|employer|company|host|organized by)\s*:\s*[A-Za-z][^\n]{3,}|'
        r'\b(?:University of|Ministry of|African Union|World Bank|United Nations|UNICEF|UNDP|FAO)\b|'
        r'\b(?:at|by|from)\s+[A-Z][\w&.-]+(?:\s+[A-Z][\w&.-]+){0,5}\s+(?:University|College|Foundation|Institute|PLC|Ltd|Inc)\b',text))
    deadline=bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(opp.get('deadline') or '')))
    # Different kinds of concrete details count once each. Length alone is not evidence.
    facts=sum(bool(re.search(pattern,text,re.I)) for pattern in (
        r'\b(?:responsibilities|duties|you will|deliverables|fields of (?:study|training))\b',
        r'\b(?:qualifications|requirements|must have|must hold|eligible applicants|eligibility|years? (?:of )?experience|degree in)\b',
        r'\b(?:salary|stipend|tuition|accommodation|benefits|funding covers)\b',
        r'\b(?:duration|start date|work location|working hours|contract type)\s*:',
    ))
    if not named and not deadline and facts < 2:
        return 'Vague announcement: no identifiable institution, no deadline and insufficient concrete details.'
    return ''
