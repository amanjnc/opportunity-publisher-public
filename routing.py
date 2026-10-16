"""Category routing for future Telegram posts; historical destinations stay attached."""
import re
from settings import env

EDUCATION_CATEGORIES = frozenset(('scholarship', 'fellowship'))


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


def telegram_destination(opportunity):
    from grouped_posts import is_grouped, group_category
    raw = str(opportunity.get('raw_text') or '')
    category = group_category(raw) if is_grouped(raw) else str(opportunity.get('category') or '')
    route = 'education' if category.strip().casefold() in EDUCATION_CATEGORIES else 'general'
    # Missing education secret holds those items; never fall back to the wrong channel.
    return telegram_routes().get(route, '')
