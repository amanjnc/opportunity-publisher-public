"""Encrypted durable state in a dedicated PRIVATE GitHub repository branch.
Never fall back to an empty database after a restore failure.
"""
import base64
import io
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent
BRANCH = 'publisher-state'
MAX_BYTES = 25_000_000


def api(path, method='GET', data=None):
    token = os.environ.get('STATE_REPO_TOKEN') or os.environ.get('GH_TOKEN')
    if not token:
        token = subprocess.check_output(['gh', 'auth', 'token'], text=True).strip()
    request = Request('https://api.github.com/' + path, method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                 'Content-Type': 'application/json', 'User-Agent': 'OpportunityPublisher'})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        # Do not include request URLs, headers, credentials or state payloads.
        raise RuntimeError(f'GitHub state request failed: HTTP {exc.code}') from None


def repo():
    name = os.environ.get('STATE_REPOSITORY', '').strip()
    if not name or name.count('/') != 1 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._/' for c in name):
        raise RuntimeError('STATE_REPOSITORY must name your private owner/repository.')
    if not api('repos/' + name).get('private'):
        raise RuntimeError('Cloud state requires a PRIVATE repository.')
    return name


def pack():
    data = ROOT / 'data'
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, 'w', zipfile.ZIP_DEFLATED) as archive:
        from storage import DB_PATH, init_db
        init_db()
        snapshot = sqlite3.connect(':memory:')
        with sqlite3.connect(DB_PATH) as source:
            source.backup(snapshot)
        # serialize avoids copying live WAL files.
        archive.writestr('opportunities.db', snapshot.serialize())
        rows = snapshot.execute("SELECT image_path FROM opportunities WHERE status<>'rejected' AND id NOT IN (SELECT opportunity_id FROM publications WHERE platform='telegram' AND status='posted')").fetchall()
        snapshot.close()
        session = data / 'collector.session'
        if session.exists():
            # Telethon is closed before final save; checkpoint reads during publishing are safe.
            with sqlite3.connect(session) as source:
                target = sqlite3.connect(':memory:')
                source.backup(target)
                archive.writestr('collector.session', target.serialize())
                target.close()
        for (name,) in rows:
            if name and Path(name).name == name:
                path = data / 'media' / name
                if path.is_file():
                    archive.write(path, 'media/' + name)
    binary = Fernet(os.environ['STATE_ENCRYPTION_KEY'].encode()).encrypt(memory.getvalue())
    if len(binary) > MAX_BYTES:
        raise RuntimeError('Encrypted state exceeds 25 MB; move state to dedicated storage before continuing.')
    return binary


def save(seed=False):
    name = repo()
    if seed:
        metadata = api('repos/' + name)
        head = api(f'repos/{name}/git/ref/heads/{metadata["default_branch"]}')['object']['sha']
        # Seed is intentionally one-time. Existing branch fails instead of overwriting history.
        api(f'repos/{name}/git/refs', 'POST', {'ref': 'refs/heads/' + BRANCH, 'sha': head})
    entry = None
    try:
        entry = api(f'repos/{name}/contents/state.enc?ref={BRANCH}')
    except RuntimeError as exc:
        if not seed:
            raise
    payload = {'message': 'Checkpoint encrypted publisher state', 'branch': BRANCH,
               'content': base64.b64encode(pack()).decode()}
    if entry:
        payload['sha'] = entry['sha']
    api(f'repos/{name}/contents/state.enc', 'PUT', payload)
    print('Encrypted state checkpoint saved.', flush=True)


def restore():
    name = repo()
    entry = api(f'repos/{name}/contents/state.enc?ref={BRANCH}')
    # Git blobs endpoint supplies base64 for state files larger than 1 MB as well.
    blob = api(f'repos/{name}/git/blobs/{entry["sha"]}')
    encrypted = base64.b64decode(blob['content'])
    plain = Fernet(os.environ['STATE_ENCRYPTION_KEY'].encode()).decrypt(encrypted)
    data = ROOT / 'data'
    if data.exists() and any(data.iterdir()):
        raise RuntimeError('Restore requires an empty data directory. Refusing to overwrite local records.')
    with zipfile.ZipFile(io.BytesIO(plain)) as archive:
        if sum(info.file_size for info in archive.infolist()) > 150_000_000:
            raise RuntimeError('State archive exceeds restore size limit.')
        for info in archive.infolist():
            path = Path(info.filename)
            if path.is_absolute() or '..' in path.parts:
                raise RuntimeError('Invalid archive path')
        archive.extractall(data)
    (ROOT / '.cloud-restored').write_text('ok')
    print('State restored; publication history and Telegram session retained.')


if __name__ == '__main__':
    command = sys.argv[1]
    if command == 'restore':
        restore()
    elif command == 'seed':
        save(seed=True)
    elif command == 'save':
        if not (ROOT / '.cloud-restored').exists():
            raise RuntimeError('Restore did not succeed; refusing state overwrite.')
        save()
    else:
        raise SystemExit('Use seed, restore or save')
