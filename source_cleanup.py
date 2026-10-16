"""Remove source promotion without discarding opportunity application links."""
import re
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
    return host in SOCIAL_HOSTS


def promotional(line):
    plain=visible_text(line).strip().strip('*_')
    return bool(SOCIAL_LABEL.search(plain) or FOLLOW.search(plain) or MENTION_LINE.fullmatch(plain))


def clean_source(text):
    lines=str(text or '').splitlines()
    blocked=set()
    for line in lines:
        if promotional(line):
            blocked.update(links(line))
    cleaned=[]
    for line in lines:
        if promotional(line):
            continue
        urls=links(line)
        # Telegram collectors may append the same hidden footer URLs again.
        plain=visible_text(line).strip()
        if urls and (all(u in blocked or social_url(u) for u in urls)):
            without=URL.sub('',plain).strip(' 🔵📲📘▶️🎵🔗👉*_:')
            if not without:
                continue
        # Strip hashtag tokens from text, leaving HTML attributes/URLs untouched.
        chunks=re.split(r'(<[^>]*>)',line)
        line=''.join(chunk if chunk.startswith('<') else HASHTAG.sub('',chunk)
                     for chunk in chunks)
        if visible_text(line).strip().strip('*_'):
            cleaned.append(line.rstrip())
        elif not line.strip():
            cleaned.append('')
    return re.sub(r'\n{3,}','\n\n','\n'.join(cleaned)).strip()
