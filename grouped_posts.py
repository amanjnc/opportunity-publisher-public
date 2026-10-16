"""Keep source roundups together, with safe Telegram HTML and every link."""
import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit
from message_layout import visible_text, text_units

PROMOTION = re.compile(r'(?i)^\s*[^\w<]*(?:follow|subscribe|join)\b.*(?:channel|updates|opportunities|abilink)|^\s*@\w+\s*$')
KINDS = re.compile(r'(?i)\b(?:internships?|volunteers?|fellowships?|fellows|scholarships?|programmes?|programs?|vacanc(?:y|ies)|jobs?|grants?|training|workshops?)\b')


def is_grouped(raw):
    urls = {u.rstrip(').,') for u in re.findall(r'https?://[^\s<>"\]]+', raw)}
    urls = {u for u in urls if urlsplit(u).hostname not in ('t.me', 'telegram.me')}
    headings = [line for line in raw.splitlines()
                if 'http' not in line and KINDS.search(line) and len(line.strip()) > 8]
    return len(urls) >= 2 and len(headings) >= 2


def group_category(raw):
    headings = '\n'.join(line for line in raw.splitlines() if 'http' not in line and not PROMOTION.search(line.strip('*_')))
    if re.search(r'(?i)\b(?:internships?|volunteers?|jobs?|vacanc(?:y|ies)|grants?|training|workshops?|competitions?|mentorships?)\b', headings):
        return 'Other'
    if re.search(r'(?i)\bscholarships?\b', headings):
        return 'Scholarship'
    if re.search(r'(?i)\b(?:fellowships?|fellows)\b', headings):
        return 'Fellowship'
    return 'Other'


class SafeHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []
    def handle_starttag(self, tag, attrs):
        if tag in ('b', 'strong', 'i', 'em', 'u', 's', 'code', 'pre'):
            self.parts.append('<' + tag + '>'); self.stack.append(tag)
        elif tag == 'a':
            href = dict(attrs).get('href', '')
            if urlsplit(href).scheme in ('https', 'http'):
                self.parts.append('<a href="' + escape(href, quote=True) + '">'); self.stack.append(tag)
    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.parts.append('</' + self.stack.pop() + '>')
    def handle_data(self, data):
        self.parts.append(escape(data, quote=False))


def render_group(raw, source_html=''):
    source = source_html or escape(raw, quote=False)
    lines = []
    for line in source.splitlines():
        plain = visible_text(line).strip().strip('*_')
        if PROMOTION.search(plain):
            continue
        # Convert pasted Markdown when native Telegram HTML is unavailable.
        if not source_html:
            line = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', line)
            line = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'<a href="\2">\1</a>', line)
        lines.append(line.rstrip('\\'))
    parser = SafeHTML(); parser.feed('\n'.join(lines)); parser.close()
    return ''.join(parser.parts) + ''.join('</'+tag+'>' for tag in reversed(parser.stack))


def split_messages(html, limit=4096):
    """Split only when Telegram requires it; keep balanced formatting and links."""
    class Split(SafeHTML):
        def __init__(self):
            super().__init__(); self.starts=[]; self.units=0; self.messages=[]
        def flush(self):
            if self.units:
                self.messages.append(''.join(self.parts)+''.join('</'+t+'>' for t in reversed(self.stack)))
                self.parts=list(self.starts); self.units=0
        def handle_starttag(self, tag, attrs):
            before=len(self.parts); super().handle_starttag(tag,attrs)
            if len(self.parts)>before:self.starts.append(self.parts[-1])
        def handle_endtag(self, tag):
            if self.stack and self.stack[-1]==tag:
                super().handle_endtag(tag); self.starts.pop()
        def handle_data(self, data):
            for char in data:
                size=text_units(char)
                if self.units+size>limit:self.flush()
                self.parts.append(escape(char,quote=False)); self.units+=size
    parser=Split(); parser.feed(html); parser.close(); parser.flush()
    return parser.messages
