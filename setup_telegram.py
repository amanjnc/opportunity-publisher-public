"""One-time interactive Telegram user login for reading permitted channels."""
import asyncio
from pathlib import Path

from settings import env

async def main():
    try:
        from telethon import TelegramClient
    except ImportError:
        print('Telegram library not installed. Run: .venv\\Scripts\\python.exe -m pip install telethon')
        return
    api_id, api_hash = env('TELEGRAM_API_ID'), env('TELEGRAM_API_HASH')
    if not api_id or not api_hash:
        print('First fill TELEGRAM_API_ID and TELEGRAM_API_HASH in .env')
        return
    data_dir = Path(__file__).resolve().parent / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    async with TelegramClient(str(data_dir / 'collector'), int(api_id), api_hash) as client:
        await client.start()
        me = await client.get_me()
        print(f'Telegram login saved for: {me.first_name}. Keep data/collector.session PRIVATE.')

if __name__ == '__main__':
    asyncio.run(main())
