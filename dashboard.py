"""Private, offline-installed web dashboard using Python's standard library."""
from __future__ import annotations

import hashlib
import html
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from settings import config, enabled, env
from storage import (add_opportunity, get_opportunity, get_opportunities, get_publications,
                     init_db, mark_manual_linkedin, update_opportunity)
from transform import CATEGORIES, extract, format_post
from image_assets import attachment_image

HOST, PORT = '127.0.0.1', 8501
TOKEN = secrets.token_urlsafe(30)


def esc(value) -> str:
    return html.escape(str(value or ''), quote=True)


def page(content: str, tab: str = 'review', notice: str = '') -> str:
    nav = [('review', 'Review inbox'), ('approved', 'Approved queue'),
           ('publications', 'Publications'), ('add', 'Add opportunity'), ('setup', 'Setup')]
    links = ''.join(f'<a class="{("on" if name == tab else "")}" href="/?tab={name}">{label}</a>'
                    for name, label in nav)
    alert = f'<div class="notice">{esc(notice)}</div>' if notice else ''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Opportunity Publisher</title>
<style>
:root{{--bg:#f6f8fc;--ink:#182238;--soft:#687389;--border:#dfe5ee;--primary:#2458d3}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.5 system-ui,Segoe UI,Arial;background:var(--bg);color:var(--ink)}}
header{{background:#fff;border-bottom:1px solid var(--border);padding:22px max(18px,calc((100vw - 1100px)/2))}}
header h1{{font-size:23px;margin:0}}header p{{margin:4px 0 0;color:var(--soft)}}
nav{{display:flex;gap:9px;overflow:auto;margin:0 auto;padding:14px 18px;max-width:1136px}}
nav a{{text-decoration:none;color:#47536b;padding:9px 15px;border-radius:8px;white-space:nowrap}}
nav a.on{{background:#e5edff;color:#1445bd;font-weight:700}}
main{{max-width:1100px;margin:8px auto 40px;padding:0 18px}}
h2{{font-size:22px}}h3{{font-size:18px;margin:0 0 5px}}
.card{{background:#fff;border:1px solid var(--border);border-radius:13px;padding:21px;margin:14px 0}}
.notice{{border:1px solid #98c3ef;border-radius:8px;padding:10px 15px;background:#eaf3ff;margin:12px 0}}
.muted{{color:var(--soft);font-size:13px}}.pill{{background:#eff3fb;border-radius:20px;font-size:12px;padding:5px 9px;display:inline-block}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
label{{display:block;font-size:13px;font-weight:600;margin:14px 0 5px}}
input,textarea,select{{width:100%;border:1px solid #cad3e2;border-radius:7px;padding:10px 12px;font:inherit;background:#fff}}
textarea{{min-height:100px;resize:vertical}}button,.btn{{font:inherit;display:inline-block;cursor:pointer;color:#fff;background:var(--primary);border:0;border-radius:8px;padding:10px 14px;text-decoration:none}}
button.secondary{{background:#e7ebf4;color:#26395f}}button.danger{{background:#b93b40}}
.actions{{display:flex;gap:8px;flex-wrap:wrap;margin:17px 0}}details>summary{{cursor:pointer;font-weight:650}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6fb;border-radius:8px;padding:14px}}
footer{{color:var(--soft);margin:28px auto;text-align:center;padding:12px}}
.preview{{white-space:pre-wrap;overflow-wrap:anywhere;border:1px solid #e2e7f0;background:#f7f9fe;border-radius:12px;padding:16px;line-height:1.7}}
.preview-image{{display:block;width:100%;max-width:550px;border-radius:13px;border:1px solid #e1e6ef;object-fit:contain}}

@media(max-width:650px){{.cols{{grid-template-columns:1fr}}.card{{padding:15px}}}}
</style></head><body><header><h1>📣 Opportunity Publisher</h1><p>Private local workspace • Nothing is published without approval</p></header>
<nav>{links}</nav><main>{alert}{content}</main><footer>Running only on this computer • 127.0.0.1</footer></body></html>'''


def inputfield(label: str, name: str, value: str = '', textarea: bool = False) -> str:
    inp = (f'<textarea name="{name}" id="{name}">{esc(value)}</textarea>' if textarea else
           f'<input type="text" name="{name}" id="{name}" value="{esc(value)}">')
    return f'<label for="{name}">{esc(label)}</label>{inp}'


def opportunity_editor(opp: dict) -> str:
    from storage import duplicate_warning
    warning = duplicate_warning(opp)
    fields = [('Title', 'title'), ('Organization', 'organization'), ('Location', 'location'),
              ('Deadline (YYYY-MM-DD or empty)', 'deadline'), ('Deadline wording from source', 'deadline_note'), ('Eligibility', 'eligibility'),
              ('Application link', 'apply_url'), ('Source link (private review only)', 'source_url')]
    midpoint = 4
    left = ''.join(inputfield(label, key, opp.get(key, '')) for label, key in fields[:midpoint])
    right = ''.join(inputfield(label, key, opp.get(key, '')) for label, key in fields[midpoint:])
    opts = ''.join(f'<option value="{esc(cat)}" {"selected" if opp.get("category") == cat else ""}>{esc(cat)}</option>'
                   for cat in CATEGORIES)
    left += f'<label for="category">Category</label><select name="category" id="category">{opts}</select>'
    preview_t = format_post(opp, 'telegram')
    preview_l = esc(format_post(opp, 'linkedin'))
    link = opp.get('source_url', '')
    anchor = (f'<a href="{esc(link)}" target="_blank" rel="noopener noreferrer">Check source privately ↗</a>'
              if link.startswith('https://') else '')
    mark = (f'''<form method="post" action="/mark-linkedin">
<input type="hidden" name="token" value="{TOKEN}"><input type="hidden" name="id" value="{opp['id']}">
<button class="secondary">Mark LinkedIn manually published</button></form>'''
            if opp['status'] == 'approved' else '')
    return f'''<div class="card"><details><summary><span class="pill">{esc(opp['category'])}</span>
#{opp['id']} — {esc(opp['title'])}</summary>
<p style="color:#a64000">{esc(warning)}</p>
<p class="muted">{esc(opp['source_name'])} · {esc(opp['created_at'])} · {esc(opp['status'])} &nbsp; {anchor}</p>
<form method="post" action="/edit">
<input type="hidden" name="token" value="{TOKEN}"><input type="hidden" name="id" value="{opp['id']}">
<div class="cols"><div>{left}</div><div>{right}</div></div>
{inputfield('Full description (verify facts; published caption is shorter)', 'description', opp.get('description', ''), True)}
<div class="cols"><div>{inputfield('Telegram custom message (optional)', 'telegram_text', opp.get('telegram_text', ''), True)}</div>
<div>{inputfield('LinkedIn custom message (optional)', 'linkedin_text', opp.get('linkedin_text', ''), True)}</div></div>
<div class="actions"><button name="action" value="save" class="secondary">Save changes</button>
<button name="action" value="approve">Approve & queue</button>
<button name="action" value="reject" class="danger">Reject</button></div></form>
<h4>Attached image</h4>
<img class="preview-image" loading="lazy" src="/image?id={opp['id']}" alt="Image that will accompany this opportunity">
<p class="muted">{'Source Telegram image (when available)' if opp.get('image_path') else 'Automatically generated branded card'}. Both platforms will receive an image.</p>
<h4>Suggested Telegram post</h4><p class="muted">Full details are preserved. If too long for a photo caption, the image is followed by the detailed text and application link.</p><div class="preview">{preview_t}</div>
<h4>Suggested LinkedIn post</h4><pre>{preview_l}</pre>
{mark}<details><summary>Raw source text</summary><pre>{esc(opp.get('raw_text', '')[:12000])}</pre></details>
</details></div>'''


def regenerate_review_drafts() -> int:
    """Explicitly rebuild only UNAPPROVED drafts; never change approved or posted items."""
    changed = 0
    for item in get_opportunities('review', limit=10000):
        from storage import get_publications
        if item['id'] in {p['opportunity_id'] for p in get_publications(100000)}:
            continue
        if not item.get('raw_text', '').strip():
            continue
        fresh = extract(item['raw_text'], item['source_name'], item['source_url'])
        # Intentionally replace old guesses and custom post drafts; caller opts in.
        update_opportunity(item['id'], {**{field: fresh.get(field, '') for field in (
            'title', 'organization', 'category', 'location', 'deadline', 'eligibility',
            'description', 'apply_url', 'deadline_note')}, 'telegram_text': '', 'linkedin_text': ''})
        changed += 1
    return changed


def content_for(tab: str) -> str:
    if tab in ('review', 'approved'):
        opps = get_opportunities(tab)
        title = 'Needs your review' if tab == 'review' else 'Approved publishing queue'
        intro = ('Check the official source, deadline and eligibility before approving.'
                 if tab == 'review' else 'Approved items will be posted at the scheduled time after enabling publishing.')
        cards = ''.join(opportunity_editor(opp) for opp in opps)
        refresh = (f'''<form method="post" action="/refresh-drafts" class="card">
<input type="hidden" name="token" value="{TOKEN}">
<p><strong>Better formatting is available for existing collected drafts.</strong></p>
<p class="muted">Rebuild titles, categories, descriptions and post previews using the saved original messages. Only items in Review Inbox are changed. This replaces any previous manual edits or custom messages for those unapproved drafts.</p>
<button class="secondary">Improve all review drafts</button></form>''' if tab == 'review' and opps else '')
        return f'<h2>{title} ({len(opps)})</h2><p class="muted">{intro}</p>' + refresh + (cards or
               '<div class="card">Nothing here yet. Add an opportunity or configure sources.</div>')
    if tab == 'publications':
        publications = get_publications(150)
        cards = ''.join(f'<div class="card"><strong>{esc(p["platform"].title())} · {esc(p["status"])} · '
                        f'#{p["opportunity_id"]} {esc(p["title"])}</strong><div class="muted">{esc(p["updated_at"])}</div>'
                        f'<p>{esc(p.get("error", ""))}</p></div>' for p in publications)
        return '<h2>Publications</h2>' + (cards or '<div class="card">No publications yet.</div>')
    if tab == 'add':
        return f'''<h2>Add an opportunity</h2><p class="muted">Paste a posting you are permitted to reuse. LinkedIn posts can be added here manually.</p>
<div class="card"><form method="post" action="/add">
<input type="hidden" name="token" value="{TOKEN}">
{inputfield('Paste opportunity text', 'raw', '', True)}
{inputfield('Source name', 'source_name', 'Manual submission')}
{inputfield('Source link (private review only)', 'source_url')}
{inputfield('Title (optional)', 'title_hint')}
<div class="actions"><button>Add to review inbox</button></div></form></div>'''
    if tab == 'setup':
        cfg = config()
        mapping = [('Telegram channels', cfg['telegram_channels']), ('RSS feeds', cfg['rss_feeds']),
                   ('Greenhouse boards', cfg['greenhouse_boards']), ('Lever sites', cfg['lever_sites']),
                   ('Publishing hours (Ethiopia)', cfg.get('publish_hours', [])),
                   ('Automatic publishing', 'ON' if enabled('AUTO_PUBLISH') else 'OFF'),
                   ('Telegram bot', 'Configured' if env('TELEGRAM_BOT_TOKEN') else 'Missing'),
                   ('LinkedIn', 'API enabled' if enabled('AUTO_LINKEDIN') else 'Manual publishing'),
                   ('OpenAI extraction', 'Configured' if env('OPENAI_API_KEY') else 'Optional: not configured')]
        rows = ''.join(f'<div class="card"><strong>{esc(name)}</strong><p>{esc(value)}</p></div>' for name,value in mapping)
        return ('<h2>Configuration</h2><p class="muted">Edit .env and config.yaml in VS Code. '
                'Restart the worker after changing these values.</p>' + rows)
    return '<h2>Unknown page</h2>'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        uri = urlsplit(self.path)
        if uri.path == '/image':
            try:
                opp_id = int(parse_qs(uri.query).get('id', ['0'])[0])
                opp = get_opportunity(opp_id)
                if not opp:
                    self.send_error(404)
                    return
                data, content_type, _ = attachment_image(opp)
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(data)
            except (ValueError, RuntimeError, ImportError):
                self.send_error(404, 'Image unavailable. Install Pillow via the update installer.')
            return
        if uri.path not in ('/', ''):
            self.send_error(404)
            return
        tab = parse_qs(uri.query).get('tab', ['review'])[0]
        notice = parse_qs(uri.query).get('notice', [''])[0]
        self.render(page(content_for(tab), tab, notice))

    def render(self, body, code=200):
        payload = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; form-action 'self'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if self.path not in ('/add', '/edit', '/mark-linkedin', '/refresh-drafts'):
            self.send_error(404)
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > 250_000:
                self.send_error(413)
                return
            form = parse_qs(self.rfile.read(size).decode('utf-8'), keep_blank_values=True)
            arg = lambda key: form.get(key, [''])[0]
            if not secrets.compare_digest(arg('token'), TOKEN):
                self.send_error(403, 'Invalid form token')
                return
            if self.path == '/refresh-drafts':
                count = regenerate_review_drafts()
                return self.redirect('review', f'Rebuilt {count} review drafts. Verify every item before approval.')
            if self.path == '/add':
                if not arg('raw').strip():
                    return self.redirect('add', 'Paste some opportunity text first.')
                source_name = arg('source_name') or 'Manual submission'
                source_url = arg('source_url')
                raw = arg('raw')
                opp = extract(raw + '\n' + source_url, source_name, source_url, arg('title_hint'))
                opp.update(source_name=source_name, source_url=source_url, raw_text=raw,
                           source_key='manual:' + hashlib.sha256((source_url + raw).encode()).hexdigest())
                new = add_opportunity(opp)
                return self.redirect('review', 'Added to review inbox.' if new else 'Duplicate; already exists.')
            opp_id = int(arg('id'))
            if self.path == '/mark-linkedin':
                marked = mark_manual_linkedin(opp_id)
                return self.redirect('approved', 'Marked as manually published.' if marked else 'Already recorded.')
            action = arg('action')
            if action not in ('save', 'approve', 'reject'):
                self.send_error(400)
                return
            changes = {key: arg(key) for key in ('title', 'organization', 'category', 'location', 'deadline',
                                                'eligibility', 'apply_url', 'source_url', 'description',
                                                'telegram_text', 'linkedin_text', 'deadline_note')}
            from post_content import application_url
            if action == 'approve' and (not changes['title'].strip() or not application_url(changes)):
                return self.redirect('review', 'Approval requires a title and valid application link. The original channel source link cannot be used to apply.')
            status = 'approved' if action == 'approve' else 'rejected' if action == 'reject' else None
            update_opportunity(opp_id, changes, status=status)
            self.redirect('approved' if status == 'approved' else 'review', 'Changes saved.')
        except (KeyError, ValueError) as exc:
            self.render(page('<h2>Invalid submission</h2>', notice=str(exc)), 400)

    def redirect(self, tab, notice):
        from urllib.parse import urlencode
        self.send_response(303)
        self.send_header('Location', '/?' + urlencode({'tab': tab, 'notice': notice}))
        self.end_headers()


def main():
    init_db()
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as error:
        print(f'Could not start dashboard on port {PORT}: {error}. Close any other dashboard window.')
        return
    url = f'http://{HOST}:{PORT}'
    print(f'Opportunity Publisher dashboard available at {url}', flush=True)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('Dashboard stopped')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
