import re
from html.parser import HTMLParser


def text_units(text):
    return len(text.encode("utf-16-le")) // 2


class Plain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def visible_text(html):
    parser = Plain()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts)


def visible_units(html):
    return text_units(visible_text(html))
def _caption_priority(line, section=""):
    """Higher scores mean more useful information."""
    plain = visible_text(line).strip().casefold()

    if re.search(r'<a\b[^>]*href=', line, re.I):
        return 100

    if re.search(r"\bdeadline\b|closing tomorrow|apply today", plain):
        return 98

    if re.search(
        r"\b(salary|stipend|allowance|funding|grant|"
        r"tuition|scholarship coverage|fully funded|"
        r"fee|fees|cost)\b|"
        r"\b(?:ETB|USD|EUR|GBP|birr)\b|[$€£]|ብር",
        plain,
        re.I,
    ):
        return 94

    if re.search(
        r"\b(who|eligibility|eligible|requirements|"
        r"qualifications|age|aged|nationality)\b",
        plain,
    ):
        return 92

    if section == "eligibility":
        return 90

    if re.search(
        r"^(?:[^\w]*)(?:where|location|venue|format|"
        r"mode|date|dates|time|duration|start date)\s*:",
        plain,
    ):
        return 85

    if section == "benefits":
        return 75

    if section == "duties":
        return 65

    if re.search(r"\b(organizer|organisation|organization|host)\s*:", plain):
        return 35

    return 50


def _caption_section(line):
    """Recognize standalone section headings."""
    plain = visible_text(line).strip()
    key = re.sub(r"\W+", "", plain.casefold())

    sections = {
        "whattoexpect": "benefits",
        "whatyoullgain": "benefits",
        "whatyougain": "benefits",
        "benefits": "benefits",
        "whatweoffer": "benefits",
        "whatmakesitspecial": "benefits",
        "funding": "benefits",
        "scholarshipcoverage": "benefits",
        "whocanapply": "eligibility",
        "whocanparticipate": "eligibility",
        "whoshouldapply": "eligibility",
        "eligibility": "eligibility",
        "eligibilitycriteria": "eligibility",
        "requirements": "eligibility",
        "qualifications": "eligibility",
        "responsibilities": "duties",
        "whatyoulldo": "duties",
        "eventdetails": "details",
        "programdetails": "details",
        "fieldsoftraining": "benefits",
        "whatyoulllearn": "benefits",
    }
    return sections.get(key)


def telegram_layout(text):
    """Automatically fit useful content into one image caption."""
    limit = 1024
    text = text.strip()

    if not text:
        raise ValueError("The opportunity caption is empty.")

    if visible_units(text) <= limit:
        return text, []

    source = [line.strip() for line in text.splitlines() if line.strip()]
    # Our generated discovery footer is reserved, not ranked away by shortening.
    footer = ''
    if source and re.fullmatch(r'#[A-Za-z][A-Za-z0-9]*(?: #[A-Za-z][A-Za-z0-9]*)*', source[-1]):
        footer = source.pop()

    # Keep the opportunity header and title together.
    opening = source[:2]
    remaining = source[2:]

    items = []
    section = ""
    heading = None
    seen = set()

    for line in remaining:
        detected = _caption_section(line)

        if detected:
            section = detected
            heading = line
            continue

        key = re.sub(r"\W+", "", visible_text(line).casefold())
        if key and key in seen:
            continue
        if key:
            seen.add(key)

        # Preserve complete content lines and their original HTML.
        items.append({
            "line": line,
            "heading": heading,
            "score": _caption_priority(line, section),
        })

    def assemble(selected):
        lines = list(opening)
        previous_heading = None

        for index, item in enumerate(items):
            if index not in selected:
                continue

            current_heading = item["heading"]

            if current_heading != previous_heading:
                if lines and lines[-1] != "":
                    lines.append("")
                if current_heading:
                    lines.extend([current_heading, ""])

            # Fit details and application links get their own spacing.
            if item["score"] >= 85:
                if lines and lines[-1] != "":
                    lines.append("")

            lines.append(item["line"])
            previous_heading = current_heading

        if footer:
            lines.extend(['', footer])
        return "\n".join(lines).strip()

    # Reserve room for the application link before selecting other details.
    selected = {
        index for index, item in enumerate(items)
        if re.search(r'<a\b[^>]*href=', item["line"], re.I)
    }

    if visible_units(assemble(selected)) > limit:
        # An unusually long title can consume the whole caption.
        # Use a short header while keeping the application link intact.
        opening = ["📣 <b>Opportunity — apply below</b>"]

    if visible_units(assemble(selected)) > limit:
        raise ValueError(
            "The application link text alone exceeds the caption limit. "
            "Use a short link label such as 'Apply here'."
        )

    # Add the most useful complete facts first.
    ranked = sorted(
        range(len(items)),
        key=lambda index: (-items[index]["score"], index),
    )

    for index in ranked:
        if index in selected:
            continue

        candidate = selected | {index}
        if visible_units(assemble(candidate)) <= limit:
            selected = candidate

    caption = assemble(selected)
    return caption, []