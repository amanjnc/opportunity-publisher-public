"""Encrypted durable state in a dedicated PRIVATE GitHub repository branch.
Never fall back to an empty database after a restore failure.
"""
import base64
import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from functools import lru_cache
from datetime import datetime, timezone, timedelta
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent
BRANCH = 'publisher-state'
MAX_BYTES = 25_000_000
PART_BYTES = 16_000_000
MAX_ARCHIVE_BYTES = 150_000_000
META_FILE = '.cloud-state-meta.json'


class StateAPIError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def api(path, method='GET', data=None):
    token = os.environ.get('STATE_REPO_TOKEN') or os.environ.get('GH_TOKEN')
    if not token:
        token = subprocess.check_output(['gh', 'auth', 'token'], text=True).strip()
    for attempt in range(4):
        request = Request('https://api.github.com/' + path, method=method,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'User-Agent': 'OpportunityPublisher'})
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            # Read only to classify. Never print provider bodies or secret URLs.
            body = exc.read(4096).decode('utf-8', 'replace').lower()
            rate_limited = exc.code == 429 or (exc.code == 403 and
                (exc.headers.get('Retry-After') or exc.headers.get('X-RateLimit-Remaining') == '0'
                 or 'rate limit' in body or 'secondary rate' in body))
            transient = rate_limited or exc.code in (500, 502, 503, 504)
            if transient and attempt < 3:
                delay = min(20, max(2, int(exc.headers.get('Retry-After', '0') or '0')))
                delay = max(delay, (2, 5, 10)[attempt])
                print(f'Temporary GitHub state response {exc.code}; retrying in {delay}s.', flush=True)
                time.sleep(delay)
                continue
            hint = 'rate limit' if rate_limited else ('access denied; check state token permissions/expiry' if exc.code in (401,403) else 'request rejected')
            raise StateAPIError(exc.code, f'GitHub state request failed: HTTP {exc.code} ({hint})') from None
        except (URLError, TimeoutError, ConnectionError):
            if attempt < 3:
                time.sleep((2,5,10)[attempt])
                continue
            raise RuntimeError('GitHub state connection failed after bounded retries; no unsafe overwrite attempted.') from None


@lru_cache(maxsize=1)

def repo():
    name = os.environ.get('STATE_REPOSITORY', '').strip()
    if not name or name.count('/') != 1 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._/' for c in name):
        raise RuntimeError('STATE_REPOSITORY must name your private owner/repository.')
    if not api('repos/' + name).get('private'):
        raise RuntimeError('Cloud state requires a PRIVATE repository.')
    return name


def compact_image(binary):
    """Compress large source photos, keeping small or unreadable files intact."""
    if len(binary) <= 400_000:
        return binary
    try:
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(binary)) as source:
            if getattr(source, 'is_animated', False):
                return binary
            image = ImageOps.exif_transpose(source)
            image.thumbnail((1600, 1600))
            if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
                rgba = image.convert('RGBA')
                background = Image.new('RGB', rgba.size, 'white')
                background.paste(rgba, mask=rgba.getchannel('A'))
                image = background
            else:
                image = image.convert('RGB')
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=85, optimize=True)
            candidate = output.getvalue()
            return candidate if len(candidate) < len(binary) else binary
    except Exception:
        return binary


def archived_images(snapshot, data):
    """Build unique media entries; adjust only the archived database copy."""
    from opportunity_dates import deadline_problem
    snapshot.row_factory = sqlite3.Row
    rows = snapshot.execute(
        "SELECT * FROM opportunities WHERE status<>'rejected' AND id NOT IN "
        "(SELECT opportunity_id FROM publications WHERE platform='telegram' AND status='posted')"
    ).fetchall()
    media, hashes, names = {}, {}, {}
    for row in rows:
        if deadline_problem(dict(row)) == 'Application deadline has already passed.':
            continue
        name = row['image_path']
        if not name or Path(name).name != name:
            continue
        path = data / 'media' / name
        if not path.is_file():
            continue
        if name not in names:
            binary = compact_image(path.read_bytes())
            digest = hashlib.sha256(binary).digest()
            canonical = hashes.setdefault(digest, name)
            names[name] = canonical
            media.setdefault(canonical, binary)
        canonical = names[name]
        if canonical != name:
            snapshot.execute('UPDATE opportunities SET image_path=? WHERE id=?',
                             (canonical, row['id']))
    snapshot.commit()
    return media


def write_archive(archive, name, binary):
    info = zipfile.ZipInfo(name, date_time=(1980,1,1,0,0,0))
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, binary)


def read_meta():
    path = ROOT / META_FILE
    return json.loads(path.read_text()) if path.exists() else {}


def write_meta(sha, digest, media_paths=()):
    (ROOT / META_FILE).write_text(json.dumps({'sha': sha, 'digest': digest, 'media_paths': list(media_paths)}))


def pack():
    data = ROOT / 'data'
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, 'w', zipfile.ZIP_DEFLATED) as archive:
        from storage import DB_PATH, init_db
        init_db()
        snapshot = sqlite3.connect(':memory:')
        with sqlite3.connect(DB_PATH) as source:
            source.backup(snapshot)
        # Retain identity facts and the text used by duplicate matching. Only
        # rejected records older than seven days lose redundant saved captions.
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        snapshot.execute("UPDATE opportunities SET telegram_text='',linkedin_text='',"
                         "raw_text=substr(raw_text,1,6000),description=substr(description,1,6000),image_path='' "
                         "WHERE status='rejected' AND updated_at<?", (cutoff,))
        snapshot.commit()
        media = archived_images(snapshot, data)
        snapshot.execute('VACUUM')
        # serialize avoids copying live WAL files. All records/history remain.
        write_archive(archive, 'opportunities.db', snapshot.serialize())
        snapshot.close()
        session = data / 'collector.session'
        if session.exists():
            # Telethon is closed before final save; checkpoint reads during publishing are safe.
            with sqlite3.connect(session) as source:
                target = sqlite3.connect(':memory:')
                source.backup(target)
                write_archive(archive, 'collector.session', target.serialize())
                target.close()
        for name, binary in media.items():
            write_archive(archive, 'media/' + name, binary)

    plain = memory.getvalue()
    if sum(info.file_size for info in zipfile.ZipFile(io.BytesIO(plain)).infolist()) > MAX_ARCHIVE_BYTES:
        raise RuntimeError('State exceeds verified restore capacity; publication stopped before sending.')
    return plain


def get_entry(name, path, missing_ok=False):
    try:
        return api(f'repos/{name}/contents/{path}?ref={BRANCH}')
    except StateAPIError as exc:
        if missing_ok and exc.status == 404:
            return None
        raise


def put_entry(name, path, binary, previous=None):
    payload = {'message': 'Checkpoint encrypted publisher state', 'branch': BRANCH,
               'content': base64.b64encode(binary).decode()}
    if previous:
        payload['sha'] = previous['sha']
    # Only retry a conflict when nobody changed this exact file. A competing
    # state writer must never be overwritten with an older local database.
    for attempt in range(3):
        try:
            result = api(f'repos/{name}/contents/{path}', 'PUT', payload)
            return result['content']['sha']
        except StateAPIError as exc:
            if exc.status not in (409,422) or attempt == 2:
                raise
            current = get_entry(name, path, missing_ok=True)
            intended = hashlib.sha1(b'blob ' + str(len(binary)).encode() + b'\0' + binary).hexdigest()
            if current and current['sha'] == intended:
                return current['sha']  # Previous attempt succeeded despite lost response.
            if (current or {}).get('sha') != (previous or {}).get('sha'):
                raise RuntimeError('Remote state changed concurrently; refusing to overwrite newer publication history.') from None
            time.sleep(attempt + 1)


def encode_media_checkpoint(name, plain, meta):
    """Keep immutable encrypted media buckets separate from changing DB records."""
    with zipfile.ZipFile(io.BytesIO(plain)) as original:
        names = original.namelist()
        media = [key for key in names if key.startswith('media/')]
        if not media or len(plain) < 4_000_000:
            return None, []
        core = io.BytesIO()
        with zipfile.ZipFile(core, 'w') as archive:
            for key in names:
                if key not in media:
                    write_archive(archive, key, original.read(key))
        buckets = {}
        for key in media:
            bucket = hashlib.sha256(key.encode()).hexdigest()[0]
            buckets.setdefault(bucket, []).append(key)
        cipher = Fernet(os.environ['STATE_ENCRYPTION_KEY'].encode())
        parts = []
        known = set(meta.get('media_paths', []))
        for keys in buckets.values():
            out = io.BytesIO()
            with zipfile.ZipFile(out, 'w') as archive:
                for key in sorted(keys):
                    write_archive(archive, key, original.read(key))
            binary = out.getvalue()
            digest = hashlib.sha256(binary).hexdigest()
            path = 'state-media/' + digest + '.enc'
            if path not in known and not get_entry(name, path, missing_ok=True):
                put_entry(name, path, cipher.encrypt(binary))
            parts.append({'path': path, 'sha256': digest})
    manifest = json.dumps({'format': 'publisher-media-v2', 'core': base64.b64encode(core.getvalue()).decode(),
                           'parts': parts, 'names': names, 'digest': hashlib.sha256(plain).hexdigest()}).encode()
    root = cipher.encrypt(manifest)
    if len(root) > MAX_BYTES:
        raise RuntimeError('Database manifest exceeds checkpoint capacity; no publication attempted.')
    return root, [part['path'] for part in parts]


def decode_media_checkpoint(name, manifest, cipher):
    if not 1 <= len(manifest.get('parts', [])) <= 16:
        raise RuntimeError('Invalid media checkpoint manifest.')
    files = {}
    def add_archive(binary):
        with zipfile.ZipFile(io.BytesIO(binary)) as archive:
            for info in archive.infolist():
                path = Path(info.filename)
                if path.is_absolute() or '..' in path.parts or info.filename in files:
                    raise RuntimeError('Invalid or duplicate state archive path.')
                if info.file_size > MAX_ARCHIVE_BYTES:
                    raise RuntimeError('State member exceeds capacity.')
                files[info.filename] = archive.read(info)
                if sum(map(len, files.values())) > MAX_ARCHIVE_BYTES:
                    raise RuntimeError('State exceeds restore capacity.')
    add_archive(base64.b64decode(manifest['core']))
    for part in manifest['parts']:
        if not re.fullmatch(r'state-media/[a-f0-9]{64}\.enc', part['path']):
            raise RuntimeError('Invalid media part path.')
        binary = cipher.decrypt(read_blob(name, get_entry(name, part['path'])))
        if hashlib.sha256(binary).hexdigest() != part['sha256']:
            raise RuntimeError('Media part integrity check failed.')
        add_archive(binary)
    if set(manifest['names']) != set(files) or len(manifest['names']) != len(files):
        raise RuntimeError('Incomplete checkpoint media index.')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        for key in manifest['names']:
            write_archive(archive, key, files[key])
    return out.getvalue()


def save(seed=False):
    name = repo()
    if seed:
        metadata = api('repos/' + name)
        head = api(f'repos/{name}/git/ref/heads/{metadata["default_branch"]}')['object']['sha']
        api(f'repos/{name}/git/refs', 'POST', {'ref': 'refs/heads/' + BRANCH, 'sha': head})
    entry = get_entry(name, 'state.enc', missing_ok=seed)
    meta = read_meta()
    if not seed and meta.get('sha') != (entry or {}).get('sha'):
        raise RuntimeError('Remote state changed since restore; refusing to overwrite another writer.')
    plain = pack()
    digest = hashlib.sha256(plain).hexdigest()
    if meta.get('digest') == digest and entry:
        print('State unchanged; durable checkpoint already current.', flush=True)
        return
    encrypted = Fernet(os.environ['STATE_ENCRYPTION_KEY'].encode()).encrypt(plain)
    media_root, media_paths = encode_media_checkpoint(name, plain, meta)
    if media_root is not None:
        root = media_root
    elif len(encrypted) <= MAX_BYTES:
        root = encrypted  # Retain legacy single-file format for small archives.
    else:
        parts = []
        for offset in range(0, len(encrypted), PART_BYTES):
            binary = encrypted[offset:offset+PART_BYTES]
            sha = hashlib.sha256(binary).hexdigest()
            path = 'state-parts/' + sha + '.enc'
            existing = get_entry(name, path, missing_ok=True)
            if not existing:
                put_entry(name, path, binary)
            parts.append({'path': path, 'sha256': sha, 'bytes': len(binary)})
        manifest = json.dumps({'format': 'publisher-sharded-v1', 'parts': parts,
                               'sha256': hashlib.sha256(encrypted).hexdigest()}).encode()
        root = Fernet(os.environ['STATE_ENCRYPTION_KEY'].encode()).encrypt(manifest)
    # Publishing the manifest last is the commit point. Interrupted staging
    # leaves the previous state usable. Recheck root after uploading the parts.
    current = get_entry(name, 'state.enc', missing_ok=seed)
    if (current or {}).get('sha') != (entry or {}).get('sha'):
        raise RuntimeError('Concurrent checkpoint detected; refusing to replace newer state.')
    # Keep the immediately previous complete checkpoint for recovery.
    if entry:
        previous_root = read_blob(name, entry)
        backup = get_entry(name, 'state.previous.enc', missing_ok=True)
        if (backup or {}).get('sha') != entry['sha']:
            put_entry(name, 'state.previous.enc', previous_root, backup)
    sha = put_entry(name, 'state.enc', root, entry)
    write_meta(sha, digest, media_paths)
    print(f'Encrypted state checkpoint saved ({len(encrypted):,} bytes).', flush=True)
    # Verify persisted root before removing any local or remote media.
    if read_blob(name, get_entry(name, 'state.enc')) != root:
        raise RuntimeError('Checkpoint read-back failed; cleanup was not attempted.')
    try:
        cleanup_local_media(plain)
        cleanup_remote_media(name)
    except Exception as exc:
        # Maintenance is optional; a durable checkpoint must not become a
        # failed publishing run because housekeeping was unavailable.
        print(f'Storage cleanup deferred ({type(exc).__name__}); saved state retained.', flush=True)


def cleanup_local_media(plain):
    """Only delete files omitted from an already saved and verified archive."""
    with zipfile.ZipFile(io.BytesIO(plain)) as archive:
        keep = {Path(n).name for n in archive.namelist() if n.startswith('media/')}
    folder = ROOT / 'data' / 'media'
    count = 0
    if folder.exists():
        for path in folder.iterdir():
            if path.is_file() and not path.is_symlink() and path.name not in keep:
                path.unlink()
                count += 1
    if count:
        print(f'Storage cleanup: removed {count} unused local images.', flush=True)


def checkpoint_parts(name, entry):
    """Validate a checkpoint before using its references for garbage collection."""
    cipher = Fernet(os.environ['STATE_ENCRYPTION_KEY'].encode())
    plain = cipher.decrypt(read_blob(name, entry))
    if not plain.startswith(b'{'):
        with zipfile.ZipFile(io.BytesIO(plain)) as archive:
            if archive.testzip() is not None:
                raise RuntimeError('Recovery archive integrity failed.')
        return set()
    manifest = json.loads(plain)
    if manifest.get('format') == 'publisher-media-v2':
        decode_media_checkpoint(name, manifest, cipher)
    else:
        decode_sharded_checkpoint(name, manifest, cipher)
    return {part['path'] for part in manifest['parts']}


def cleanup_remote_media(name):
    """Daily atomic pruning; retain current AND previous complete checkpoints.

    Uses a fast-forward Git update: a competing writer makes the update fail,
    never deleting assets referenced by a newer state. Git history is retained.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    marker = get_entry(name, 'state-maintenance.json', missing_ok=True)
    if marker and json.loads(read_blob(name, marker)).get('date') == today:
        return
    head = api(f'repos/{name}/git/ref/heads/{BRANCH}')['object']['sha']
    commit = api(f'repos/{name}/git/commits/{head}')
    tree = api(f'repos/{name}/git/trees/{commit["tree"]["sha"]}?recursive=1')
    if tree.get('truncated'):
        raise RuntimeError('Incomplete tree; refusing cleanup.')
    entries = {item['path']: item for item in tree['tree'] if item['type'] == 'blob'}
    # Read by the pinned tree blob SHA, never by a moving branch reference.
    current = entries.get('state.enc')
    previous = entries.get('state.previous.enc')
    if not current or not previous:
        return
    keep = checkpoint_parts(name, current) | checkpoint_parts(name, previous)
    candidates = [path for path in entries if
                  re.fullmatch(r'state-(?:media|parts)/[a-f0-9]{64}\.enc', path)
                  and path not in keep]
    changes = [{'path': path, 'mode': '100644', 'type': 'blob', 'sha': None}
               for path in candidates]
    changes.append({'path': 'state-maintenance.json', 'mode': '100644', 'type': 'blob',
                    'content': json.dumps({'date': today, 'removed_groups': len(candidates)})})
    new_tree = api(f'repos/{name}/git/trees', 'POST',
                   {'base_tree': commit['tree']['sha'], 'tree': changes})['sha']
    new_commit = api(f'repos/{name}/git/commits', 'POST',
                     {'message': 'Prune unused encrypted media; retain recovery checkpoint',
                      'tree': new_tree, 'parents': [head]})['sha']
    api(f'repos/{name}/git/refs/heads/{BRANCH}', 'PATCH', {'sha': new_commit, 'force': False})
    print(f'Storage cleanup: removed {len(candidates)} unused encrypted groups; recovery checkpoint retained.', flush=True)


def read_blob(name, entry):
    blob = api(f'repos/{name}/git/blobs/{entry["sha"]}')
    return base64.b64decode(blob['content'])


def restore():
    name = repo()
    entry = api(f'repos/{name}/contents/state.enc?ref={BRANCH}')
    encrypted = read_blob(name, entry)
    cipher = Fernet(os.environ['STATE_ENCRYPTION_KEY'].encode())
    plain = cipher.decrypt(encrypted)
    restored_media_paths = []
    if plain.startswith(b'{'):
        manifest = json.loads(plain)
        if manifest.get('format') == 'publisher-media-v2':
            plain = decode_media_checkpoint(name, manifest, cipher)
            restored_media_paths = [part['path'] for part in manifest['parts']]
            manifest = None
        if manifest is None:
            pass
        else:
            plain = decode_sharded_checkpoint(name, manifest, cipher)
    data = ROOT / 'data'
    if data.exists() and any(data.iterdir()):
        raise RuntimeError('Restore requires an empty data directory. Refusing to overwrite local records.')
    with zipfile.ZipFile(io.BytesIO(plain)) as archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_ARCHIVE_BYTES:
            raise RuntimeError('State archive exceeds restore size limit.')
        for info in archive.infolist():
            path = Path(info.filename)
            if path.is_absolute() or '..' in path.parts:
                raise RuntimeError('Invalid archive path')
        archive.extractall(data)
    write_meta(entry['sha'], hashlib.sha256(plain).hexdigest(), restored_media_paths)
    (ROOT / '.cloud-restored').write_text('ok')
    print('State restored; publication history and Telegram session retained.')


def decode_sharded_checkpoint(name, manifest, cipher):
    if manifest.get('format') != 'publisher-sharded-v1' or not 1 <= len(manifest.get('parts', [])) <= 16:
        raise RuntimeError('Invalid encrypted state manifest.')
    chunks = []
    for part in manifest['parts']:
        if not re.fullmatch(r'state-parts/[a-f0-9]{64}\.enc', part['path']):
            raise RuntimeError('Invalid state part path.')
        binary = read_blob(name, get_entry(name, part['path']))
        if len(binary) != part['bytes'] or hashlib.sha256(binary).hexdigest() != part['sha256']:
            raise RuntimeError('State part integrity check failed; restore stopped.')
        chunks.append(binary)
    encrypted = b''.join(chunks)
    if hashlib.sha256(encrypted).hexdigest() != manifest['sha256']:
        raise RuntimeError('Checkpoint integrity check failed.')
    plain = cipher.decrypt(encrypted)
    return plain

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
