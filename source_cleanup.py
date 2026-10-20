"""Remove source promotion without discarding opportunity application links."""
import re
import unicodedata
from html import unescape
from urllib.parse import urlsplit
from message_layout import visible_text

URL = re.compile(r'https?://[^\s<>"\')\]]+', re.I)
SOCIAL_LABEL = re.compile(
    r'(?i)^[^\w]*(?:linkedin|telegram|facebook|youtube|tik\s*tok|instagram|'
    r'twitter|whatsapp|our\s+(?:socials?|channels?|pages?))\s*(?:[:：|–—-]|$)')
FOLLOW = re.compile(
    r'(?i)^[^\w]*(?:follow|subscribe|connect\s+with)\b|'
    r'^[^\w]*join\b.*\b(?:channel|group|updates|community)\b')
HASHTAG = re.compile(r'(?<![\w&])#[^\W#]+', re.UNICODE)
MENTION_LINE = re.compile(r'^[^\w@]*@[A-Za-z][A-Za-z0-9_]*[\W_]*$')
SOCIAL_HOSTS = {'t.me','telegram.me','facebook.com','fb.com','instagram.com',
                'youtube.com','youtu.be','tiktok.com','twitter.com','x.com','wa.me'}


def links(line):
    return [unescape(u).rstrip('.,;!') for u in URL.findall(line)]


def social_url(url):
    parsed=urlsplit(url)
    host=(parsed.hostname or '').lower().removeprefix('www.')
    if host == 'linkedin.com':
        # Actual LinkedIn vacancies stay; personal/company profiles are promotion.
        return not parsed.path.startswith('/jobs/')
    return any(host == root or host.endswith('.'+root) for root in SOCIAL_HOSTS)


# These identify the publisher's marketing, not the opportunity provider.
SOURCE_BRAND = re.compile(r'(?i)\b(?:OHUB(?:4AllET)?|OHUBET|OHUB Educational Consultancy|Rez[_ ]On[_ ]Bridge)\b')
MARKETING = re.compile(r"(?i)\b(?:connect with us|for (?:more |daily )?updates|our (?:social media|telegram|channel|page)|advertise with us|paid promotion|educational consultancy|exam booking|IELTS preparation class|book (?:your|an?) (?:IELTS|exam)|contact us for (?:admission|visa|consultancy)|study abroad consultancy)\b")
FACT = re.compile(r'(?i)^(?:[^\w]*)(?:more info(?:rmation)?|details|deadline|apply|application(?:s| process| link)?|eligibility|requirements|benefits|responsibilities|qualifications|salary|stipend|duration|location|host|organis[ae]r|how to apply|documents required)\b')


def promotional(line):
    plain=unicodedata.normalize('NFKC', visible_text(line)).strip().strip('*_')
    return bool(SOCIAL_LABEL.search(plain) or FOLLOW.search(plain) or
                MENTION_LINE.fullmatch(plain) or MARKETING.search(plain) or
                (SOURCE_BRAND.search(URL.sub('', plain)) and not FACT.search(plain)))


def clean_source(text, source_name=""):
    lines=str(text or '').splitlines()
    # A source handle/email identifies the source's contact, never the employer's.
    source_key=re.sub(r'[^a-z0-9]', '', str(source_name).lower().lstrip('@'))
    def source_contact(line):
        contacts=re.findall(r'(?i)[\w.+-]+@[\w.-]+|@[a-z][a-z0-9_]+',line)
        return bool(source_key and len(source_key)>3 and any(
            source_key in re.sub(r'[^a-z0-9]', '', value.lower()) for value in contacts))
    in_promotion=False
    blocked=set()
    for line in lines:
        if promotional(line):
            blocked.update(links(line))
    cleaned=[]
    for line in lines:
        plain=visible_text(line).strip().strip('*_')
        # A marketing block may be in the middle. Resume at a real fact section.
        if FACT.search(plain) and not promotional(line):
            in_promotion=False
        if promotional(line) or source_contact(line):
            in_promotion=True
            continue
        if in_promotion and (re.search(r'(?i)\b(?:phone|email|contact|address|website|consultancy|test center|test centre|instagram|telegram|linkedin|facebook|tiktok|youtube)\b|\+?\d[\d ()-]{7,}|[\w.+-]+@[\w.-]+',plain) or SOURCE_BRAND.search(plain)):
            continue
        urls=links(line)
        # Telegram collectors may append the same hidden footer URLs again.
        plain=visible_text(line).strip()
        if urls and (all(u in blocked or social_url(u) for u in urls)):
            without=URL.sub('',plain).strip(' 🔵📲📘▶️🎵🔗👉*_:')
            if not without:
                continue
        line=re.sub(r'<a\b[^>]*href=[\"\']([^\"\']+)[\"\'][^>]*>.*?</a>',
                    lambda m: '' if social_url(unescape(m.group(1))) else m.group(0), line, flags=re.I)
        chunks=re.split(r'(<[^>]*>)',line)
        line=''.join(chunk if chunk.startswith('<') else URL.sub(
            lambda m: '' if social_url(m.group(0)) or m.group(0) in blocked else m.group(0),chunk)
            for chunk in chunks)
        # Strip hashtag tokens from text, leaving HTML attributes/URLs untouched.
        chunks=re.split(r'(<[^>]*>)',line)
        line=''.join(chunk if chunk.startswith('<') else HASHTAG.sub('',chunk)
                     for chunk in chunks)
        if visible_text(line).strip().strip('*_'):
            cleaned.append(line.rstrip())
        elif not line.strip():
            cleaned.append('')
    return re.sub(r'\n{3,}','\n\n','\n'.join(cleaned)).strip()
