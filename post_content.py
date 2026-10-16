"""Detailed, source-backed posts. Application links are never shortened or sliced."""
import re
from html import escape, unescape
from urllib.parse import urlsplit

SOCIAL_SOURCES={'t.me','telegram.me','www.t.me','www.telegram.me'}
URL_RE=re.compile(r'https?://[^\s<>"\']+',re.I)
MONEY_RE=re.compile(r'(?i)(?:\b(?:ETB|USD|EUR|GBP|birr|dollars?|euros?|shillings?|salary|stipend|allowance|grant amount|funding amount|scholarship (?:amount|value)|remuneration)\b|[$€£₹]|ብር)')
# Remove only recognizable channel advertising and generic recruitment filler.
PROMO_RE=re.compile(r'''(?ix)
    ["“”']?if\s+this\s+isn['’]?t\s+for\s+you,?\s*please\s+share\s+it\s+with\s+others\s+who\s+might\s+be\s+interested[.!]?["“”']?
    |follow\s+us\s*(?:for\s+more\s+opportunities)?(?:\s*[:👇]+)?
    |motivated,?\s*creative,?\s*and\s*energetic\s+candidates\s+eager\s+to\s+learn\s+and\s+grow[.!]?
''')


def application_url(opp):
    # A dedicated field wins over incidental links in the source; keep query IDs.
    value=unescape(str(opp.get('apply_url') or '').strip())
    if value.startswith('www.'):
        value='https://'+value
    try:
        p=urlsplit(value)
        if p.scheme.lower() not in ('http','https') or not p.hostname or re.search(r'\s|[<>"\']',value):
            return ''
        if p.hostname.lower() in SOCIAL_SOURCES:
            # A channel's source post is not an application link. Telegram bot
            # application endpoints remain usable if selected in the apply field.
            if value.rstrip('/')==str(opp.get('source_url') or '').rstrip('/') or re.search(r'/\d+/?$',p.path):
                return ''
        return value
    except ValueError:
        return ''


def _key(text):
    return re.sub(r'\W+','',text.casefold())


def clean_details(opp):
    from transform import source_lines, _tidy
    raw=str(opp.get('description') or opp.get('raw_text') or '')
    if raw.rstrip().endswith(('…','...')) and len(str(opp.get('raw_text') or ''))>len(raw):
        raw=str(opp['raw_text'])
    from source_cleanup import clean_source
    raw=clean_source(PROMO_RE.sub('',raw))
    result=[]
    for line in source_lines(raw):
        if line.startswith('@') or re.match(r'(?i)^follow\s+us',line):
            continue
        selected=application_url(opp)
        def keep_useful_link(found):
            link=found.group(0).rstrip('.,;!)]}')
            host=(urlsplit(link).hostname or '').lower()
            if link==selected or (host in SOCIAL_SOURCES and (re.search(r'/\d+/?$',urlsplit(link).path) or link.rstrip('/')==str(opp.get('source_url') or '').rstrip('/'))):
                return ''
            return found.group(0)
        line=_tidy(URL_RE.sub(keep_useful_link,line))
        line=re.sub(r'^["“”]+|["“”]+$','',line).strip()
        if not line or _key(line)==_key(str(opp.get('title') or '')):
            continue
        if re.fullmatch(r'(?i)(?:register|register now|apply|apply here|apply now|registration link|application link|how to apply)\s*[:👇]*',line):
            continue
        if re.match(r'(?i)^(?:original source|source link)\b',line):
            continue
        # Deadline is displayed prominently in the fit block instead.
        if re.match(r'(?i)^(?:application |registration )?deadline\s*[:–-]',line):
            continue
        if re.fullmatch(r'[\W_]+',line):
            continue
        if line not in result:
            result.append(line)
    # Recover financial facts from original text even if an older description
    # was shortened. Include the full amount/type/period line, never just a number.
    for line in source_lines(clean_source(str(opp.get('raw_text') or ''))):
        if MONEY_RE.search(line):
            value=_tidy(PROMO_RE.sub('',line),remove_urls=True)
            if value and not any(_key(value) in _key(existing) for existing in result):
                result.append(value)
    # Keep facts once: the top fit block already contains these details.
    who=_key(PROMO_RE.sub('', str(opp.get('eligibility') or '')))
    title=_key(str(opp.get('title') or ''))
    where=_key(str(opp.get('location') or ''))
    cleaned=[]
    for i,line in enumerate(result):
        key=_key(line)
        eligibility_line=re.sub(r'(?i)^(?:who can apply|eligibility(?: criteria)?)\s*[:?]\s*','',line)
        covered=_key(eligibility_line)
        if who and len(covered)>10 and covered in who:
            continue
        if who and key in ('whocanapply','eligibility','eligibilitycriteria'):
            following=[]
            for next_line in result[i+1:]:
                if section_style(next_line) or label_style(next_line):
                    break
                following.append(next_line)
            if following and all(_key(value) in who for value in following):
                continue
        if title and title in key and re.match(r'(?i)^(?:calling young changemakers|join (?:the|our))',line) and not MONEY_RE.search(line):
            continue
        if who and re.match(r'(?i)^are you aged\b',line):
            continue
        labeled=label_style(line)
        if labeled and labeled[0] in ('format','location','where'):
            value=_key(labeled[2])
            if where and value and value in where:
                continue
        if not any(_key(previous)==key for previous in cleaned):
            cleaned.append(line)
    return cleaned


def financial_lines(opp,details):
    return [line for line in details if MONEY_RE.search(line)]


SECTION_STYLES = {
    'whatyoullgain': ('🎯', 'benefits'), 'whatyougain': ('🎯', 'benefits'),
    'benefits': ('🎁', 'benefits'), 'whatweoffer': ('🎁', 'benefits'),
    'whocanapply': ('👤', 'eligibility'), 'eligibility': ('👤', 'eligibility'),
    'eligibilitycriteria': ('👤', 'eligibility'), 'requirements': ('📋', 'eligibility'),
    'qualifications': ('🎓', 'eligibility'), 'responsibilities': ('🛠️', 'duties'),
    'whatyoulldo': ('🛠️', 'duties'),
    'fieldsoftraining': ('📚', 'training'), 'whatyoulllearn': ('📚', 'training'),
    'whatmakesitspecial': ('✨', 'benefits'), 'howtoapply': ('📝', 'application'),
    'applicationprocess': ('📝', 'application'), 'documentsrequired': ('📎', 'application'),
    'funding': ('💰', 'funding'), 'scholarshipcoverage': ('🎓', 'funding'),
    'abouttherole': ('💼', 'about'), 'abouttheprogram': ('ℹ️', 'about'),
    'whattoexpect': ('🎯', 'benefits'),
    'whocanparticipate': ('👤', 'eligibility'),
    'whocanparticipateinthisprogram': ('👤', 'eligibility'),
    'whoshouldapply': ('👤', 'eligibility'),
    'whocanjoin': ('👤', 'eligibility'),
    'eventdetails': ('📆', 'details'),
    'programdetails': ('📋', 'details'),
}
LABEL_STYLES = {
    'duration': '🗓️', 'format': '💻', 'mode': '💻', 'location': '📍', 'where': '📍',
    'venue': '📍', 'fee': '💸', 'fees': '💸', 'cost': '💸', 'tuition': '🎓',
    'organizer': '🏛️', 'organisation': '🏛️', 'organization': '🏛️', 'host': '🏛️',
        'date': '📅', 'dates': '📅', 'eventdate': '📅','time': '⏰', 'eventtime': '⏰',
    'salary': '💰', 'stipend': '💰', 'allowance': '💰', 'grantamount': '💰',
    'fundingamount': '💰', 'scholarshipamount': '🎓', 'scholarshipvalue': '🎓',
    'employmenttype': '💼', 'jobtype': '💼', 'workinghours': '🕒',
    'startdate': '🗓️', 'contact': '☎️', 'email': '✉️', 'deadline': '📅',
}

def section_style(line):
    return SECTION_STYLES.get(_key(line))

def label_style(line):
    if ':' not in line:
        return None

    label, value = line.split(':', 1)
    label = re.sub(r'^[^\w]+', '', label).strip()
    key = _key(label)

    if key in LABEL_STYLES:
        return key, label, value.strip()

    return None
def detail_icon(line,state,index):
    lower=line.casefold()
    if MONEY_RE.search(line):return '💰'
    if re.search(r'one.on.one|mentorship|mentoring',lower):return '🤝'
    if re.search(r'networking|network with|career development',lower):return '🌐'
    if re.search(r'workshop|practical skill|hands.on',lower):return '🛠️'
    if re.search(r'project|innovation|idea',lower):return '💡'
    if re.search(r'training|course|learn|education',lower):return '📚'
    if state=='eligibility':return '✅'
    if state=='application':return '📎'
    if state=='duties':return '🔹'
    if state in ('benefits','training','funding'):
        return ('🌟','🛠️','💡','🌱')[index % 4]
    return '🔹'

def styled_details(details,platform):
    esc=lambda value:escape(str(value),quote=True)
    lines=[]
    state='about'
    index=0
    for line in details:
        
        section=section_style(line)
        if section:
            icon,state=section
            index=0
            if lines and lines[-1]!='':lines.append('')
            label=line.rstrip(':?')
            lines.append(f'{icon} <b>{esc(label)}</b>' if platform=='telegram' else f'{icon} {label}')
            lines.append('')
            continue
        label=label_style(line)
        if label:
            key,name,value=label
            icon=LABEL_STYLES[key]
            if lines and lines[-1]!='':lines.append('')
            if platform=='telegram':
                if MONEY_RE.search(line) or key in ('fee','fees','cost','tuition','deadline'):
                    lines.append(f'{icon} <b>{esc(f'{name}: {value}')}</b>')
                else:
                    lines.append(f'{icon} <b>{esc(name)}:</b> {esc(value)}')
            else:
                lines.append(f'{icon} {name}: {value}')
            continue
        icon=detail_icon(line,state,index)
        if MONEY_RE.search(line) and platform=='telegram':
            lines.append(f'{icon} <b>{esc(line)}</b>')
        else:
            # Plain introductions stay readable; lists have one purposeful icon.
            prefix=icon+' ' if state!='about' or len(line)<150 else ''
            lines.append(prefix+(esc(line) if platform=='telegram' else line))
        index+=1
    return lines

def render_post(opp,platform,today=None):
    from transform import _tag, deadline_display, labeled_value
    if platform not in ('telegram','linkedin'):
        raise ValueError('Unsupported platform')
    if platform == 'telegram':
        from grouped_posts import is_grouped, render_group
        if is_grouped(str(opp.get('raw_text') or '')):
            return render_group(opp['raw_text'], str(opp.get('telegram_text') or ''))
    url=application_url(opp)
    category=str(opp.get('category') or 'Other')
    title=str(opp.get('title') or 'Opportunity — title needs review').strip()
    who=PROMO_RE.sub('',str(opp.get('eligibility') or '')).strip(' ;,\n')
    where=str(opp.get('location') or '').strip()
    deadline,urgency=deadline_display(str(opp.get('deadline') or ''),today=today)
    if not opp.get('deadline'):
        note=opp.get('deadline_note') or labeled_value(str(opp.get('raw_text') or ''),'deadline')
        if note:deadline=str(note).strip()
    icon,header=_tag(category,title)
    esc=lambda value:escape(str(value),quote=True)
    where_icon='💻' if re.search(r'(?i)online|virtual|remote',where) else '📍'
    if platform=='telegram':
        lines=[f'{icon} <b>{esc(header)}</b>',f'<b>{esc(title)}</b>','']
        if who:lines.append(f'👤 <b>Who:</b> {esc(who)}')
        if where:lines.append(f'{where_icon} <b>Where:</b> {esc(where)}')
        lines.append(f'📅 <b>Deadline: {esc(deadline)}</b>'+(' '+esc(urgency) if urgency else ''))
    else:
        # LinkedIn does not render Telegram's HTML bold; use readable native text.
        lines=[f'{icon} {header}',title,'']
        if who:lines.append(f'👤 Who can apply: {who}')
        if where:lines.append(f'{where_icon} Location: {where}')
        lines.append(f'📅 DEADLINE: {deadline}'+(' '+urgency if urgency else ''))
    custom=str(opp.get(f'{platform}_text') or '').strip()
    details=clean_details(opp)
    if custom:
        custom_opp=dict(opp,description=custom,raw_text='')
        custom_details=clean_details(custom_opp)
        for line in financial_lines(opp,details):
            if not any(_key(line) in _key(value) for value in custom_details):
                custom_details.append(line)
        details=custom_details
    if details:
        lines.append('')
        lines.extend(styled_details(details,platform))
    if url:
        lines+=['',f'🔗 <a href="{esc(url)}">Apply here</a>' if platform=='telegram' else f'🔗 Apply here: {url}']
    else:
        lines+=['','⚠️ Application link needs review before publishing.']
    return '\n'.join(lines)
