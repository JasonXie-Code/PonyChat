"""Exact-title recovery from the project's original Huiji Wiki text archive."""
import hashlib
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

PAGES_DIR = Path(__file__).resolve().parents[1] / 'data' / 'mlp' / 'pages'


def wiki_title(url):
    """Accept article URLs only, never reinterpret a URL as a filesystem path."""
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in {'http', 'https'} or parsed.hostname != 'mlp.huijiwiki.com'
                or parsed.username or parsed.password or parsed.port not in {None, 80, 443}
                or not parsed.path.startswith('/wiki/') or parsed.query):
            return None
        title = unquote(parsed.path[len('/wiki/'):]).replace('_', ' ')
        if not title or len(title) > 200 or any(ord(c) < 32 for c in title):
            return None
        return title
    except (ValueError, TypeError):
        return None


def read_snapshot(url, directory=PAGES_DIR, *, max_chars=20_000):
    title = wiki_title(url)
    if title is None or directory is None:
        return None
    try:
        root = Path(directory).resolve()
        # Same filename mapping as fetch_mlp_wiki.py; header validation below
        # rejects sanitized-name collisions and truncated-title ambiguities.
        name = re.sub(r'[\\/:*?"<>|]', '_', title) + '.txt'
        path = (root / name).resolve()
        if not path.is_relative_to(root) or path.stat().st_size > 1_000_000:
            return None
        body = path.read_bytes()
        content = body.decode('utf-8-sig')
        header, _, text = content.partition('\n')
        if header.strip().replace('_', ' ') != '# ' + title or not text.strip():
            return None
        return {'title': title, 'url': url, 'content': content[:max_chars],
                'content_truncated': len(content) > max_chars,
                'snapshot_sha256': hashlib.sha256(body).hexdigest(),
                'snapshot_captured_at': None}
    except (OSError, UnicodeError, ValueError):
        return None
