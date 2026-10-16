"""Import an encrypted Telegram login without replacing opportunity history."""
import asyncio
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet
from settings import ROOT, env
from storage import get_state, set_state, init_db


def decode_login(value):
    try:
        return Fernet(env('STATE_ENCRYPTION_KEY').encode()).decrypt(value.encode()).decode()
    except Exception:
        raise RuntimeError('Cannot decrypt repaired login; check STATE_ENCRYPTION_KEY.') from None


async def repair():
    value = env('TELEGRAM_COLLECTOR_LOGIN')
    if not value:
        print('No collector login repair requested.')
        return
    if not (ROOT / '.cloud-restored').is_file():
        raise RuntimeError('Restore current cloud state before repairing its login.')
    init_db()
    digest = hashlib.sha256(value.encode()).hexdigest()
    if get_state('telegram:login_repair') == digest:
        print('Collector login repair already applied.')
        return
    from telethon import TelegramClient
    from telethon.sessions import StringSession, SQLiteSession
    session = StringSession(decode_login(value))
    client = TelegramClient(session, int(env('TELEGRAM_API_ID')), env('TELEGRAM_API_HASH'),
                            connection_retries=1, request_retries=1, timeout=15)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError('Repaired Telegram login is not authorized; log in locally again.')
        # Save only the verified Telegram session. Never replace opportunities.db.
        target = SQLiteSession(str(ROOT / 'data' / 'collector'))
        try:
            target.set_dc(session.dc_id, session.server_address, session.port)
            target.auth_key = session.auth_key
            target.save()
        finally:
            target.close()
    finally:
        await client.disconnect()
    set_state('telegram:login_repair', digest)
    set_state('cloud:last_collection_attempt', '0')
    from cloud_state import save
    save()
    print('Verified Telegram login repaired; opportunity and publication history preserved.')


if __name__ == '__main__':
    asyncio.run(repair())
