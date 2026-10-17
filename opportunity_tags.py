"""Generate our own discovery tags from opportunity facts, never source hashtags."""
import re
from source_cleanup import clean_source
from message_layout import visible_text

FIELDS = [
    ('IT', r'\b(?:computer science|information technology|information systems|software (?:engineer|develop|systems)|cyber\s?security|data science|IT (?:officer|specialist|support|technician)|network (?:engineer|administrator)|web develop|app develop)'),
    ('Software', r'\b(?:software|web|mobile|full.stack|front.end|back.end)\s+(?:engineer|develop)|\bprogrammers?\b|\b(?:build|develop|design) software\b'),
    ('ElectricalEngineering', r'\b(?:electrical|electronics?)\s+engineer'),
    ('MechanicalEngineering', r'\bmechanical engineer'),
    ('CivilEngineering', r'\bcivil engineer|\bstructural engineer'),
    ('Engineering', r'\bengineering\b'),
    ('Finance', r'\b(?:finance|financial (?:analyst|management|officer|reporting|planning|controller|specialist|manager|director)|accounting|accountants?|auditing|auditors?|treasury|bookkeeping)\b'),
    ('Marketing', r'\b(?:marketing|brand management|digital advertising|market research)\b'),
    ('Healthcare', r'\b(?:medicine|medical|healthcare|health care|public health|nursing|nurses?|physicians?|clinical|pharmacy|laboratory diagnostics)\b'),
    ('Business', r'\b(?:business administration|business management|entrepreneurship|entrepreneurs?|MBA)\b'),
    ('SocialSciences', r'\b(?:social sciences?|sociology|political science|anthropology|social work)\b'),
    ('Law', r'\b(?:law|legal|lawyers?|attorneys?|jurisprudence)\b'),
    ('Economics', r'\b(?:economics|economists?)\b'),
    ('Education', r'\b(?:teachers?|teaching|education specialist|educational leadership|pedagogy)\b'),
    ('Agriculture', r'\b(?:agriculture|agricultural|agronomy|agronomists?)\b'),
    ('Environment', r'\b(?:environmental|climate|conservation|sustainability|renewable energy)\b'),
    ('Communications', r'\b(?:communications? (?:officer|specialist|manager)|journalism|public relations|media relations)\b'),
    ('HumanResources', r'\bhuman resources|\bHR (?:officer|manager|specialist)\b'),
    ('Logistics', r'\b(?:logistics|supply chain|procurement|warehousing)\b'),
    ('Administration', r'\b(?:administrative (?:assistant|officer)|office administration|executive assistant)\b'),
    ('Sales', r'\b(?:sales (?:representative|manager|officer|executive)|business development)\b'),
    ('Research', r'\b(?:research (?:assistant|fellow|scientist|associate|project)|researchers?)\b'),
]
DEGREES = [
    ('Bachelors', r"\b(?:bachelor(?:s|['’]s)?|undergraduate|BSc|BA degree|BEng)\b"),
    ('Masters', r"\b(?:master(?:s|['’]s)?|MSc|MA degree|MBA|MPhil)\b"),
    ('PhD', r'\b(?:Ph\.?D\.?|doctoral|doctorate)\b'),
    ('Postdoctoral', r'\bpost[ -]?doc(?:toral)?\b'),
]
TYPES = [
    ('Scholarships',r'\bscholarships?\b'),
    ('Fellowships',r'\b(?:fellowships?|fellows programme|fellows program)\b'),
    ('Internships',r'\binternships?\b|\bintern programme\b'),
    ('ExchangePrograms',r'\bexchange (?:programs?|programmes?|students?)\b'),
    ('Grants',r'\bgrants?\b|\bfunding call\b'),
    ('Mentorship',r'\bmentorship\b'),
    ('Training',r'\b(?:training|workshops?|bootcamps?)\b'),
    ('Volunteering',r'\bvolunteer(?:s|ing)?\b'),
    ('Competitions',r'\b(?:competition|hackathon|innovation challenge)s?\b'),
]
CATEGORY_TAGS={'Education':'Education','Job':'Jobs','Internship':'Internships','Scholarship':'Scholarships',
               'Fellowship':'Fellowships','Mentorship':'Mentorship','Grant':'Grants',
               'Competition':'Competitions','Training':'Training','Volunteering':'Volunteering'}


def classify_tags(opp):
    # URLs, source branding and hashtags provide no classification evidence.
    parts=[str(opp.get(k) or '') for k in
           ('title','organization','description','eligibility','location','raw_text')]
    evidence=visible_text(clean_source('\n'.join(parts)))
    evidence=re.sub(r'https?://\S+','',evidence)
    # Negative statements must not establish a work format or funding level.
    evidence=re.sub(r'(?i)\b(?:not|no|non)[ -]+(?:fully[ -]+funded|remote|hybrid|in[ -]?person|on[ -]?site)\b','',evidence)
    found=[]
    def add(tag):
        if tag not in found:found.append(tag)
    category=str(opp.get('category') or '').strip()
    joblike=category in ('Job','Internship') or bool(re.search(r'(?i)\b(?:vacanc(?:y|ies)|hiring|job opportunities|job openings?)\b',evidence))
    if joblike:
        modes=[
            ('RemoteJobs',r'\b(?:fully[ -]remote|remote[ -]first|work(?:ing)? remotely|remote (?:work|jobs?|roles?|positions?)|(?:role|position) is remote|work from home)\b|(?:location|work (?:mode|arrangement|type))\s*:\s*remote\b|^\W*remote\W*$'),
            ('HybridJobs',r'\bhybrid (?:work|jobs?|roles?|positions?|arrangement|schedule)|(?:role|position) is hybrid\b|(?:location|work (?:mode|arrangement|type))\s*:\s*hybrid\b|^\W*hybrid\W*$'),
            ('InPersonJobs',r'\b(?:in[ -]person|on[ -]site|office[ -]based) (?:work|jobs?|roles?|positions?|employment)\b|(?:location|work (?:mode|arrangement|type))\s*:\s*(?:in[ -]person|on[ -]site)\b|^\W*(?:in[ -]person|on[ -]site)\W*$'),
        ]
        for tag,pattern in modes:
            if re.search(pattern,evidence,re.I|re.M):add(tag)
        if re.search(r'\b(?:NGO|non[ -]?governmental|nonprofit|non-profit|humanitarian organization)\b',evidence,re.I):add('NGOJobs')
        if re.search(r'\b(?:government (?:jobs?|vacanc(?:y|ies)|ministry|agency)|civil service|ministry of|public sector)\b',evidence,re.I):add('GovernmentJobs')
        if re.search(r'\b(?:fresh graduates?|recent graduates?|new graduates?|no (?:prior |previous )?(?:work )?experience required)\b',evidence,re.I):add('FreshGraduate')
    for tag,pattern in FIELDS:
        if re.search(pattern,evidence,re.I):add(tag)
    # Avoid the generic engineering tag when a discipline is known.
    if any(tag.endswith('Engineering') and tag!='Engineering' for tag in found):
        found=[tag for tag in found if tag!='Engineering']
    for tag,pattern in DEGREES:
        if re.search(pattern,evidence,re.I):add(tag)
    for tag,pattern in [('FullyFunded',r'\bfully[ -]funded\b|\ball expenses (?:paid|covered)\b'),
                        ('PartiallyFunded',r'\bpartially[ -]funded\b|\bpartial (?:scholarships?|funding)\b')]:
        if re.search(pattern,evidence,re.I):add(tag)
    if category in CATEGORY_TAGS:add(CATEGORY_TAGS[category])
    # Grouped listings can contain more than one opportunity type.
    from grouped_posts import is_grouped
    if is_grouped(str(opp.get('raw_text') or '')):
        for tag,pattern in TYPES:
            if re.search(pattern,evidence,re.I):add(tag)
    return ['#'+tag for tag in found] or ['#Opportunities']


def tag_post(text,opp):
    return text.rstrip()+'\n\n'+' '.join(classify_tags(opp))
