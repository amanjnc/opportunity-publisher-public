"""Cross-source identity checks: shared links need corroborating opportunity facts."""
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def normalized(value):
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return ' '.join(re.findall(r'\w+', value))


def canonical_url(value):
    """Ignore known tracking only; preserve application/job IDs and other parameters."""
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
        # Preserve HTTP vs HTTPS on unusual nonstandard ports.
        scheme = 'https' if not port or port in (80, 443) else p.scheme.lower()
        return urlunsplit((scheme, host, p.path.rstrip('/') or '/', urlencode(query), ''))
    except ValueError:
        return ''


TITLE_FILLER = set('opportunity opportunities alert opening openings vacancy vacancies hiring now apply join the our a an and for at in of to fully funded free paid programme program'.split())
ROLE_KINDS = set('intern internship assistant officer manager director engineer developer accountant analyst nurse teacher coordinator specialist consultant technician supervisor apprenticeship apprentice volunteer'.split())
ROLE_ALIASES = {'internship':'intern', 'apprenticeship':'apprentice'}
SEASONS = {'spring', 'summer', 'autumn', 'fall', 'winter'}


def title_tokens(value):
    return {ROLE_ALIASES.get(t, t) for t in normalized(value).split()
            if t not in TITLE_FILLER and not re.fullmatch(r'20\d{2}', t)}


def cycle(value):
    title = normalized(value.get('title'))
    explicit = normalized(value.get('intake') or value.get('cohort') or '')
    years = set(re.findall(r'\b20\d{2}\b', title + ' ' + explicit))
    cohorts = set(re.findall(r'\b(?:cohort|intake|round|batch)\s+(\d+)\b', title))
    seasons = set(title.split()) & SEASONS
    return years, cohorts, seasons


def vacancy_id(value):
    explicit = normalized(value.get('vacancy_id') or value.get('job_id') or value.get('requisition_id'))
    if explicit:
        return explicit
    text = str(value.get('description') or '') + '\n' + str(value.get('raw_text') or '')
    found = re.search(r'(?i)\b(?:vacancy|job|requisition)\s*(?:id|number|no\.?|reference|ref)\s*[:#=-]\s*([\w-]{3,})', text)
    return normalized(found.group(1)) if found else ''


def description(value):
    text = str(value.get('description') or value.get('raw_text') or '')
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'(?im)^\s*(?:follow us|share this|#\w+|@\w+).*$', '', text)
    return normalized(text)[:6000]


def match(a, b):
    """Return (exact|possible|'', reason). Missing facts are not confirmations."""
    ta, tb = normalized(a.get('title')), normalized(b.get('title'))
    oa, ob = normalized(a.get('organization')), normalized(b.get('organization'))
    la, lb = normalized(a.get('location')), normalized(b.get('location'))
    ua, ub = canonical_url(a.get('apply_url')), canonical_url(b.get('apply_url'))
    same_url = bool(ua and ua == ub and urlsplit(ua).hostname not in
                    ('t.me', 'telegram.me', 'linkedin.com'))
    same_org = bool(oa and ob and oa == ob)
    same_title = bool(len(ta) >= 10 and ta == tb)
    tokens_a, tokens_b = title_tokens(ta), title_tokens(tb)
    score = SequenceMatcher(None, ta, tb).ratio() if ta and tb else 0
    overlap = len(tokens_a & tokens_b) / max(1, len(tokens_a | tokens_b))
    similar_title = same_title or (score >= .72 and overlap >= .60) or (tokens_a == tokens_b and len(tokens_a) >= 2)

    # A generic portal must not collapse different employers, locations or cycles.
    if oa and ob and oa != ob:
        return '', ''
    if la and lb and la != lb:
        return '', ''
    for ca, cb in zip(cycle(a), cycle(b)):
        if ca and cb and ca != cb:
            return '', ''
    levels = [{'bachelor', 'bachelors', 'undergraduate'}, {'master', 'masters', 'postgraduate'}, {'phd', 'doctoral', 'doctorate'}]
    study_a = {i for i, words in enumerate(levels) if tokens_a & words}
    study_b = {i for i, words in enumerate(levels) if tokens_b & words}
    if study_a and study_b and study_a != study_b:
        return '', ''
    ida, idb = vacancy_id(a), vacancy_id(b)
    if ida and idb and ida != idb:
        return '', ''
    roles_a, roles_b = tokens_a & ROLE_KINDS, tokens_b & ROLE_KINDS
    if roles_a and roles_b and roles_a != roles_b:
        return '', ''
    senior_a = set(ta.split()) & {'senior', 'junior', 'lead', 'entry'}
    senior_b = set(tb.split()) & {'senior', 'junior', 'lead', 'entry'}
    if senior_a and senior_b and senior_a != senior_b:
        return '', ''
    if not (same_url or same_org or same_title or (ida and ida == idb)):
        return '', ''

    da, db = str(a.get('deadline') or '').strip(), str(b.get('deadline') or '').strip()
    same_deadline = bool(da and db and da == db)
    changed_deadline = bool(da and db and da != db)
    desc_a, desc_b = description(a), description(b)
    same_description = bool(min(len(desc_a), len(desc_b)) >= 100 and desc_a == desc_b)
    similar_description = same_description or (
        min(len(desc_a), len(desc_b)) >= 160
        and len(set(desc_a.split()) & set(desc_b.split())) / max(1, len(set(desc_a.split()) | set(desc_b.split()))) >= .82
    )

    # A changed deadline is preserved for verification, never silently discarded.
    strong_link = same_url and (same_title or (similar_title and similar_description and (same_org or same_deadline))
                               or (similar_title and same_org and same_deadline and score >= .90 and overlap >= .80))
    strong_facts = same_org and similar_title and same_deadline and similar_description
    strong_id = bool(ida and ida == idb and same_org and similar_title)
    existing_identity = same_org and same_title
    if strong_link or strong_facts or strong_id or existing_identity:
        if changed_deadline:
            return 'possible', 'Same opportunity identity but different deadlines; check extension or new cycle'
        return 'exact', ('Same application link and matching opportunity details' if strong_link
                         else 'Matching employer, role/program and supporting identity details')
    if same_url and (similar_title or (same_org and similar_description)):
        return 'possible', 'Shared application link with partially matching opportunity details'
    if same_org and similar_title:
        return 'possible', 'Similar role/program at the same organization; insufficient confirmation'
    if same_title and (not oa or not ob):
        return 'possible', 'Same title but employer or application identity is missing'
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
