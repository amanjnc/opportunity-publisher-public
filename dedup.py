"""Conservative cross-source comparisons. Possible matches are held for review."""
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def normalized(value):
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return ' '.join(re.findall(r'\w+', value))


def canonical_url(value):
    try:
        p = urlsplit(str(value or '').strip())
        if p.scheme.lower() not in ('http', 'https') or not p.hostname:
            return ''
        host = p.hostname.lower().removeprefix('www.')
        port = p.port
        if port and port not in (80, 443):
            host += ':' + str(port)
        query = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                       if not k.casefold().startswith('utm_') and k.casefold() not in
                       ('fbclid', 'gclid', 'mc_cid', 'mc_eid'))
        return urlunsplit(('https', host, p.path.rstrip('/') or '/', urlencode(query), ''))
    except ValueError:
        return ''


def match(a, b):
    """Return (exact|possible|'', reason). Never use a channel's identity as employer."""
    ta, tb = normalized(a.get('title')), normalized(b.get('title'))
    oa, ob = normalized(a.get('organization')), normalized(b.get('organization'))
    da, db = a.get('deadline', ''), b.get('deadline', '')
    ya, yb = set(re.findall(r'\b20\d{2}\b', ta)), set(re.findall(r'\b20\d{2}\b', tb))
    if ya and yb and ya != yb:
        return '', ''
    # Different known deadlines may be new cycles or extensions: require review,
    # rather than silently throwing away an update.
    different_deadline = bool(da and db and da != db)
    ua, ub = canonical_url(a.get('apply_url')), canonical_url(b.get('apply_url'))
    same_url = bool(ua and ua == ub and urlsplit(ua).hostname not in
                    ('t.me', 'telegram.me', 'linkedin.com'))
    same_org = bool(oa and oa == ob)
    same_title = bool(len(ta) >= 10 and ta == tb)
    score = SequenceMatcher(None, ta, tb).ratio() if ta and tb else 0
    la, lb = normalized(a.get('location')), normalized(b.get('location'))
    same_location = not la or not lb or la == lb
    if (same_url and same_title) or (same_org and same_title and same_location):
        return ('possible' if different_deadline else 'exact',
                'Same title/application or employer; deadline changed' if different_deadline
                else 'Same opportunity title and application/employer')
    if same_url and (score >= .65 or not ta or not tb):
        return 'possible', 'Shared application link and similar title'
    if same_org and score >= .84 and same_location:
        return 'possible', 'Similar title at the same organization'
    if same_title and (not oa or not ob) and same_location:
        return 'possible', 'Same title; employer needs verification'
    raw_a = normalized(re.sub(r'https?://\S+', '', a.get('raw_text', '')))
    raw_b = normalized(re.sub(r'https?://\S+', '', b.get('raw_text', '')))
    if len(raw_a) >= 80 and raw_a == raw_b:
        return 'possible', 'Identical source text with different identifiers'
    return '', ''


def find_match(data, candidates):
    possible = None
    for row in candidates:
        candidate = dict(row)
        if candidate.get('id') == data.get('id'):
            continue
        level, reason = match(data, candidate)
        if level == 'exact':
            return candidate, level, reason
        if level and possible is None:
            possible = candidate, level, reason
    return possible
