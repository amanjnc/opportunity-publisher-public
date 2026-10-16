"""Read the project's small YAML config subset and .env without external packages.

Intentionally supports lists, numbers and strings used by our generated config.yaml;
not intended to be a general YAML parser.
"""
import ast
from functools import lru_cache
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _read_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, val = stripped.split("=", 1)
        key = key.strip()
        if not key.isidentifier():
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        os.environ.setdefault(key, val)


_read_dotenv(ROOT / '.env')


def _value(raw: str):
    val = raw.strip()
    if not val:
        return None
    try:
        if val.startswith('[') and val.endswith(']'):
            return list(ast.literal_eval(val)) if val != '[]' else []
        if val[0] in ("'", '"'):
            return ast.literal_eval(val)
        if val.isdecimal():
            return int(val)
    except (SyntaxError, ValueError):
        pass
    return val


@lru_cache(maxsize=1)
def config() -> dict:
    path = ROOT / 'config.yaml'
    result = {}
    active_list = None
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.rstrip()
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if line.lstrip().startswith('- '):
            if active_list is None:
                raise ValueError('List item found without a key in config.yaml')
            result[active_list].append(_value(line.lstrip()[2:]))
        elif ':' in line and not line[0].isspace():
            key, value = line.split(':', 1)
            if not key.strip().isidentifier():
                raise ValueError(f'Invalid config key: {key}')
            v = _value(value)
            result[key.strip()] = v if v is not None else []
            active_list = key.strip() if v is None else None
        else:
            raise ValueError(f'Unsupported config.yaml line: {line}')
    for key in ('telegram_channels', 'rss_feeds', 'greenhouse_boards', 'lever_sites', 'required_keywords'):
        result[key] = result.get(key) or []
        if not isinstance(result[key], list):
            raise ValueError(f'{key} must be a list in config.yaml')
    return result


def env(key: str, default: str = '') -> str:
    return os.getenv(key, default).strip()


def enabled(key: str) -> bool:
    return env(key).lower() in ('1', 'true', 'yes', 'on')
