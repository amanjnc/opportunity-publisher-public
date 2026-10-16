"""Small HTTP helpers built only on the Python standard library."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = 'OpportunityPublisher/2.0 (local personal curation app)'


def get_bytes(url: str, params: dict | None = None, limit: int = 5_000_000) -> bytes:
    if params:
        url += ('&' if '?' in url else '?') + urlencode(params)
    request = Request(url, headers={'User-Agent': USER_AGENT,
                                    'Accept': 'application/json, application/xml, text/xml, */*'})
    try:
        with urlopen(request, timeout=25) as response:
            return response.read(limit + 1)[:limit]
    except HTTPError as error:
        raise RuntimeError(f'Server returned HTTP {error.code}') from None
    except URLError as error:
        raise RuntimeError(f'Connection failed: {error.reason}') from None


def get_json(url: str, params: dict | None = None):
    return json.loads(get_bytes(url, params))


def post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 30):
    body = json.dumps(payload).encode('utf-8')
    req = Request(url, body, headers={'Content-Type': 'application/json',
                  'User-Agent': USER_AGENT, **(headers or {})}, method='POST')
    try:
        with urlopen(req, timeout=timeout) as response:
            data = response.read(3_000_000)
            return json.loads(data) if data else {}, dict(response.headers)
    except HTTPError as error:
        # Do NOT report full URL: it might contain a private Telegram bot token.
        raise RuntimeError(f'API returned HTTP {error.code}: {error.read(200).decode("utf-8", "replace")}') from None
    except URLError as error:
        raise RuntimeError(f'API connection failed: {error.reason}') from None
