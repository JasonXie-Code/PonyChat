"""Exact-title recovery from the project's original Huiji Wiki text archive."""
import hashlib
import os
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit

PAGES_DIR = Path(os.environ.get('PONYCHAT_MLP_WIKI_SNAPSHOT_DIR') or
                 Path(__file__).resolve().parents[1] / 'data' / 'mlp' / 'pages')


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


def search_snapshots(queries, directory=PAGES_DIR, *, limit=3):
    """Find original wiki articles locally when online discovery is incomplete."""
    root = Path(directory).resolve() if directory is not None else None
    if root is None or not root.is_dir():
        return []
    variants = [str(query).strip() for query in queries if str(query).strip()]
    if not variants:
        return []
    stopwords = {'这里', '什么', '哪些', '怎么', '详细', '介绍', '地标', '建筑',
                 '特色', '物品', '来历', '地点', '相关', '资料'}
    terms = [term for query in variants for term in re.split(r'\s+', query)
             if len(term) >= 2 and term not in stopwords]
    if not terms:
        return []
    ranked = []
    for path in root.glob('*.txt'):
        try:
            if not path.resolve().is_relative_to(root) or path.stat().st_size > 1_000_000:
                continue
            content = path.read_text(encoding='utf-8-sig')
        except (OSError, UnicodeError):
            continue
        header, _, _ = content.partition('\n')
        if not header.startswith('# '):
            continue
        title = header[2:].strip()
        if not title or len(title) > 200:
            continue
        first = min((content.find(term) for term in terms if term in content), default=0)
        scores = []
        for query in variants:
            parts = [term for term in re.split(r'\s+', query)
                     if len(term) >= 2 and term not in stopwords]
            scores.append(sum(((1000 + 100 * len(term)) if term == title else
                               (300 + 20 * len(term)) if term in title else
                               min(content.count(term), 10) * min(len(term), 5))
                              for term in parts))
        score = max(scores, default=0)
        if score <= 0:
            continue
        if len(set(terms)) == 1:
            # A direct entity question should favor articles that discuss the
            # entity early, not omnibus pages repeating it in a later list.
            score += int(600 * (1 - first / max(len(content), 1)))
        start = max(0, first - 100)
        snippet = re.sub(r'\s+', ' ', content[start:start + 750]).strip()
        ranked.append((score, title, snippet))
    ranked.sort(key=lambda row: (-row[0], len(row[1]), row[1]))
    results = [{'title': title, 'url': 'https://mlp.huijiwiki.com/wiki/' + quote(title, safe=''),
                'snippet': snippet, 'published_at': None, 'engines': ['local_mlp_wiki_snapshot'],
                'freshness': 'local_snapshot'} for _, title, snippet in ranked[:limit]]
    if results:
        article = read_snapshot(results[0]['url'], root, max_chars=8500)
        if article:
            results[0]['content'] = article['content']
            results[0]['content_truncated'] = article['content_truncated']
    return results
