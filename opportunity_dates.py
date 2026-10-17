"""Conservative deadline and source-age checks in Ethiopia local time."""
import re
from datetime import datetime, date, timedelta, timezone

TZ=timezone(timedelta(hours=3))
LABEL=re.compile(r'(?i)(?:application |registration |admission )?deadline|apply by|applications? clos(?:e|es|ing)(?: on)?|closing date|last date(?: to apply)?')
DATE=re.compile(r'\b(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]20\d{2}|\d{1,2}\s+[A-Za-z]+[,]?\s+20\d{2}|[A-Za-z]+\s+\d{1,2}[,]?\s+20\d{2})\b')
FORMATS=('%Y-%m-%d','%Y/%m/%d','%d %B %Y','%d %b %Y','%B %d %Y','%b %d %Y')


def reference_date(value):
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00')).astimezone(TZ).date()
    except (ValueError,TypeError):return None


def deadline_values(raw):
    lines=str(raw or '').splitlines()
    result=[]
    for i,line in enumerate(lines):
        match=LABEL.search(line)
        if match:
            value=line[match.end():].strip(' :–—-*_')
            if not value and i+1<len(lines):value=lines[i+1].strip()
            result.append(value)
    return result


def parse_value(value,reference=None):
    value=re.sub(r'(?<=\d)(?:st|nd|rd|th)\b','',str(value),flags=re.I)
    value=re.sub(r'<[^>]*>|[*_]','',value).strip()
    if re.search(r'(?i)ዓ\.?\s*ም|E\.?C\.?\b|Ethiopian calendar',value):return None
    match=DATE.search(value)
    if match:
        token=match.group().replace(',','')
        for fmt in FORMATS:
            try:return datetime.strptime(token,fmt).date()
            except ValueError:pass
        numeric=re.fullmatch(r'(\d{1,2})[/-](\d{1,2})[/-](20\d{2})',token)
        if numeric:
            a,b,year=map(int,numeric.groups())
            # Ambiguous numeric dates are held, never silently guessed.
            if a!=b and a<=12 and b<=12:return None
            day,month=(a,b) if a>12 or a==b else (b,a)
            try:return date(year,month,day)
            except ValueError:return None
        return None
    if reference:
        if re.search(r'(?i)\btomorrow\b',value):return reference+timedelta(days=1)
        if re.search(r'(?i)\btoday\b',value):return reference
        match=re.search(r'\b(?:\d{1,2}\s+[A-Za-z]+|[A-Za-z]+\s+\d{1,2})\b',value)
        if match:
            for fmt in ('%d %B %Y','%d %b %Y','%B %d %Y','%b %d %Y'):
                try:return datetime.strptime(match.group()+' '+str(reference.year),fmt).date()
                except ValueError:pass
    return None


def parse_deadline(raw,reference=None):
    dates=[parse_value(v,reference) for v in deadline_values(raw)]
    return min(d for d in dates if d).isoformat() if any(dates) else ''


def deadline_problem(opp,now=None):
    today=(now or datetime.now(TZ)).astimezone(TZ).date()
    reference=reference_date(opp.get('source_posted_at') or opp.get('created_at'))
    values=deadline_values(str(opp.get('raw_text') or '')+'\n'+str(opp.get('description') or ''))
    note=str(opp.get('deadline_note') or '').strip()
    if note:values.append(note)
    dates=[]
    stored=str(opp.get('deadline') or '').strip()
    if stored:
        try:dates.append(date.fromisoformat(stored))
        except ValueError:return 'Invalid saved deadline.'
    for value in values:
        if re.fullmatch(r'(?i)(?:not specified|unknown|n/?a|rolling(?: applications)?|open until filled|ongoing|varies|various)\W*',value):
            continue
        parsed=parse_value(value,reference)
        if parsed:dates.append(parsed)
        elif value:return 'Explicit deadline could not be verified; publication held.'
    if any(d<today for d in dates):return 'Application deadline has already passed.'
    return ''


def source_is_recent(value,now=None):
    if not isinstance(value,datetime):return False
    if value.tzinfo is None:value=value.replace(tzinfo=timezone.utc)
    current=now or datetime.now(timezone.utc)
    return current-timedelta(days=5)<=value<=current+timedelta(minutes=5)
