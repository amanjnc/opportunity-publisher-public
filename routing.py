"""Category routing for future Telegram posts; historical destinations stay attached."""
import re
import unicodedata
from settings import env

EDUCATION_CATEGORIES = frozenset(('scholarship', 'fellowship', 'education'))


def valid_channel(value):
    return bool(re.fullmatch(r'@[A-Za-z][A-Za-z0-9_]{3,}|-100\d+', value or ''))


def telegram_routes():
    general = env('TELEGRAM_TARGET_CHANNEL')
    education = env('TELEGRAM_EDUCATION_CHANNEL')
    if general and not valid_channel(general):
        raise ValueError('Invalid TELEGRAM_TARGET_CHANNEL')
    if education and not valid_channel(education):
        raise ValueError('Invalid TELEGRAM_EDUCATION_CHANNEL')
    if general and education and general.casefold() == education.casefold():
        raise ValueError('General and education destination channels must be different')
    return {name: channel for name, channel in (('general', general), ('education', education)) if channel}



def opportunity_category(opportunity):
    from grouped_posts import is_grouped, group_category
    from source_cleanup import clean_source
    title=clean_source(str(opportunity.get('title') or ''))
    raw=clean_source('\n'.join(str(opportunity.get(key) or '') for key in
                              ('title', 'raw_text', 'description', 'eligibility', 'telegram_text')))
    title=unicodedata.normalize('NFKC', title)
    raw=unicodedata.normalize('NFKC', raw)
    saved=str(opportunity.get('category') or '').strip()
    # Ethiopian source titles often announce scholarships entirely in Amharic.
    amharic_study = re.search(r'(?:ነ[ፃጻ]\s+(?:የ)?ትምህርት|የትምህርት\s+[እዕ]ድል|ስኮላርሺፕ|ስኮላርሽፕ)',title)
    if amharic_study:return 'Scholarship'
    # A university employer does not turn a real vacancy into a scholarship.
    employment = re.search(r'(?i)\b(?:hiring|vacanc(?:y|ies)|job openings?|(?:scholarship|admissions?) (?:officer|manager)|software engineer|assistant professor|lecturer)\b',title)
    if employment:return saved if saved not in ('Scholarship','Fellowship','Other') else 'Job'
    if re.search(r'(?i)\bscholarships?\b',title):return 'Scholarship'
    if re.search(r'(?i)\b(?:fellowships?|postdoctoral|research fellow)\b',title):return 'Fellowship'
    # Admissions/degree study belongs to education even without a scholarship label.
    if re.search(r'(?i)\b(?:admissions?|tuition fees?|study (?:in|at)|universities|bachelor|master|PhD|doctoral)\b',title):
        return 'Education'
    # Funding/study signals in the body outweigh incidental references to jobs.
    # Actual vacancy titles have already been handled above.
    if re.search(r'(?i)\b(?:scholarships?|(?:international )?scholars(?: program(?:me)?)?|undergrads?|undergraduates?|bachelor[’\x27]?s?|master[’\x27]?s?|phd|doctoral)\b', raw) and re.search(r'(?i)\b(?:scholarships?|need[ -]based (?:funding|aid)|financial aid|tuition waiver|fully funded|funded (?:study|degree)|international scholars)\b',raw):
        return 'Scholarship'
    if is_grouped(raw):return group_category(raw)
    if saved.casefold() in EDUCATION_CATEGORIES:return saved.title()
    if re.search(r'(?i)\b(?:scholarships?|fellowships?)\b',raw) and not re.search(r'(?i)\b(?:hiring|vacanc(?:y|ies)|job description|responsibilities)\b',raw):
        return 'Fellowship' if re.search(r'(?i)\bfellowships?\b',raw) else 'Scholarship'
    return saved or 'Other'


def telegram_destination(opportunity):
    route = 'education' if opportunity_category(opportunity).casefold() in EDUCATION_CATEGORIES else 'general'
    return telegram_routes().get(route, '')
