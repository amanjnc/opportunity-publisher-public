"""Screen promotional products and vague announcements before publication."""
import re
from source_cleanup import clean_source
from message_layout import visible_text
from urllib.parse import urlsplit


def publication_block_reason(opp):
    from opportunity_dates import deadline_problem, source_is_recent
    problem=deadline_problem(opp)
    if problem:return problem
    if str(opp.get('source_key') or '').startswith('telegram:') and not opp.get('source_posted_at'):
        return 'Source date must be verified against the five-day collection window.'
    if opp.get('source_posted_at'):
        from datetime import datetime
        try:posted=datetime.fromisoformat(opp['source_posted_at'].replace('Z','+00:00'))
        except ValueError:return 'Source publication time is invalid.'
        if not source_is_recent(posted):return 'Source post is older than five days.'
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
    # Brief genuine calls remain eligible without a prescribed detail count.
    actionable = bool(re.search(
        r'(?i)\b(?:apply(?: now| here)?|applications? (?:are |is )?(?:open|invited|available)|call for applications|register|registration|submit (?:your |an? )?application|vacanc(?:y|ies)|hiring|recruiting|recruitment)\b', text))
    opportunity = bool(re.search(
        r'(?i)\b(?:scholarships?|scholars program|fellowships?|traineeships?|internships?|grants?|admissions?|jobs?|vacanc(?:y|ies)|volunteers?|training|workshops?|conferences?|competitions?|challenges?|mentorship|exchange programs?)\b', text))
    if not actionable and not concrete_role:
        return 'Informational announcement without an identifiable application or recruitment call.'
    if not (named or concrete_role or opportunity):
        return 'Promotional or vague announcement without an identifiable opportunity.'
    return ''
