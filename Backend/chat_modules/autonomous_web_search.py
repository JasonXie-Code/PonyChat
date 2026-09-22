"""Normal chat's sole web-search provider: private, server-configured SearXNG."""
from .Prompts import AUTONOMOUS_WEB_SEARCH_TEXT

from .Prompts import mlp_reference
import asyncio
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import ipaddress
import json
import os
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx

from .harness_runtime import HarnessToolValidationError
from .mlp_wiki_snapshot import PAGES_DIR, read_snapshot, wiki_title

_slots = asyncio.Semaphore(2)
_PAGE_BYTES = 1_000_000
_PAGE_CHARS = 20_000
_REDIRECTS = {301, 302, 303, 307, 308}
_CLASH_FAKE_IP = ipaddress.ip_network("198.18.0.0/15")




class _PageReadError(ValueError):
    pass


class _PageTextParser(HTMLParser):
    """Extract visible page text without executing or retaining active content."""

    _ignored = {"script", "style", "noscript", "svg", "template", "canvas"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._in_title = False
        self.text = []
        self.title = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self._ignored:
            self._ignored_depth += 1
        elif tag == "title" and not self._ignored_depth:
            self._in_title = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self._ignored and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._ignored_depth:
            return
        value = re.sub(r"\s+", " ", data).strip()
        if not value:
            return
        self.text.append(value)
        if self._in_title:
            self.title.append(value)


def plain(value, limit):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>", "", str(value or "")))).strip()[:limit]


def public_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        host = parsed.hostname.lower()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value
    except ValueError:
        return None


def _allowed_resolved_address(host, address):
    parsed = ipaddress.ip_address(address)
    if parsed.is_global:
        return True
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        # Clash Fake-IP DNS maps public hostnames into this benchmarking range.
        # The original hostname has already passed lexical private-host checks;
        # allowing only this exact range preserves local TUN routing without
        # admitting literal/private targets.
        return parsed.version == 4 and parsed in _CLASH_FAKE_IP


async def resolve_public(host, port):
    rows = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(row[4][0] for row in rows))
    if not addresses or any(not _allowed_resolved_address(host, address) for address in addresses):
        raise _PageReadError("blocked_address")
    return addresses[0]


def _page_text(body, content_type, encoding):
    raw = body.decode(encoding or "utf-8", errors="replace")
    media_type = content_type.split(";", 1)[0].lower()
    if media_type == "application/json":
        try:
            raw = json.dumps(json.loads(raw), ensure_ascii=False)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        content = re.sub(r"\s+", " ", raw).strip()
        return "", content[:_PAGE_CHARS], len(content) > _PAGE_CHARS
    if media_type in {"text/html", "application/xhtml+xml"}:
        parser = _PageTextParser()
        parser.feed(raw)
        content = re.sub(r"\s+", " ", " ".join(parser.text)).strip()
        title = plain(" ".join(parser.title), 300)
        return title, content[:_PAGE_CHARS], len(content) > _PAGE_CHARS
    content = re.sub(r"\s+", " ", raw).strip()
    return "", content[:_PAGE_CHARS], len(content) > _PAGE_CHARS


class SearxngSearch:
    def __init__(self, *, endpoint=None, transport=None, resolver=resolve_public, snapshot_dir=PAGES_DIR):
        self.endpoint = endpoint if endpoint is not None else os.environ.get(
            "PONYCHAT_SEARXNG_URL", "http://127.0.0.1:18786")
        self.transport, self.resolver, self.calls = transport, resolver, 0
        self.page_calls, self.page_cache = 0, {}
        self.snapshot_dir = snapshot_dir

    async def search(self, arguments):
        query = arguments.get("query")
        url = arguments.get("url")
        if bool(isinstance(query, str) and query.strip()) == bool(isinstance(url, str) and url.strip()):
            raise HarnessToolValidationError(AUTONOMOUS_WEB_SEARCH_TEXT['search_1'])
        if url is not None:
            if arguments.get("time_range", ""):
                raise HarnessToolValidationError(AUTONOMOUS_WEB_SEARCH_TEXT['search_5'])
            if arguments.get('source', 'web') not in {'web', 'mlp_wiki'}:
                raise HarnessToolValidationError('不支持的搜索来源')
            if arguments.get('source') == 'mlp_wiki' and wiki_title(url.strip()) is None:
                raise HarnessToolValidationError(AUTONOMOUS_WEB_SEARCH_TEXT['search_6'])
            return await self._read_with_recovery(url.strip())
        return await self._search(arguments, category="general")

    async def search_images(self, arguments):
        tags = arguments.get('derpibooru_tags')
        animated = arguments.get('animated')
        if animated is not None and type(animated) is not bool:
            raise HarnessToolValidationError('animated must be boolean')
        if animated is not None and not tags:
            raise HarnessToolValidationError('Animation search requires derpibooru_tags and rating')
        from .derpibooru_images import RATINGS, search_ranked
        rating = arguments.get('rating')
        if tags and rating not in RATINGS:
            raise HarnessToolValidationError(AUTONOMOUS_WEB_SEARCH_TEXT['search_images_1'])
        if rating is not None and not tags:
            raise HarnessToolValidationError(AUTONOMOUS_WEB_SEARCH_TEXT['search_images_2'])
        if tags:
            results = await search_ranked(tags, rating=rating, transport=self.transport,
                                          g4_pony=arguments.get('g4_pony') is True,
                                          **({'animated': animated} if animated is not None else {}))
            fallback = False
            if not results and animated is True:
                results = await search_ranked(tags, rating=rating, transport=self.transport,
                                              g4_pony=arguments.get('g4_pony') is True, animated=False)
                fallback = bool(results)
            if results:
                self.calls += 1
                return {'provider': 'derpibooru', 'status': 'success',
                        'query': arguments.get('query', ''), 'rating': rating, 'results': results,
                        'animation_fallback': fallback}
            if animated is not None:
                return {'provider': 'derpibooru', 'status': 'no_results', 'results': [],
                        'animation_fallback': False}
            if rating != 'safe':
                self.calls += 1
                return {'provider': 'derpibooru', 'status': 'no_results', 'rating': rating,
                        'query': arguments.get('query', ''), 'results': [],
                        'note': AUTONOMOUS_WEB_SEARCH_TEXT['search_images_3']}
        return await self._search(arguments, category="images")

    async def _search(self, arguments, *, category):
        query = arguments.get("query", "")
        period = arguments.get("time_range", "")
        source = arguments.get("source", "web")
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 300:
            raise HarnessToolValidationError(AUTONOMOUS_WEB_SEARCH_TEXT['search_4'])
        if period not in {"", "day", "week", "month", "year"}:
            raise HarnessToolValidationError("不支持的搜索时间范围")
        if source not in {"web", "mlp_wiki"}:
            raise HarnessToolValidationError("不支持的搜索来源")
        search_query = ("site:mlp.huijiwiki.com/wiki/ " if source == "mlp_wiki" else "") + query.strip()
        base = {"provider": "searxng", "query": query.strip(), "source": source, "results": [],
                "searched_at": datetime.now(timezone.utc).isoformat(),
                "note": (AUTONOMOUS_WEB_SEARCH_TEXT['base_3'] + mlp_reference
                         if source == "mlp_wiki" else
                         AUTONOMOUS_WEB_SEARCH_TEXT['base_2'])}
        self.calls += 1
        if not self.endpoint:
            return {**base, "status": "unavailable"}
        async def fetch():
            async with _slots:
                async with httpx.AsyncClient(transport=self.transport, trust_env=False,
                                             follow_redirects=False, timeout=14) as client:
                    async with client.stream("GET", self.endpoint.rstrip("/") + "/search", params={
                        # Locale filters returned empty Google results on the deployed adapter.
                        # Preserve the query language; do not expose unsupported language filters.
                        "q": search_query, "format": "json", "language": "all",
                        "time_range": period, "categories": category, "safesearch": 1,
                    }) as response:
                        response.raise_for_status()
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 1_000_000:
                                raise ValueError('Search response too large')
                        return body
        try:
            body = await asyncio.wait_for(fetch(), timeout=18)
            data = json.loads(body)
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                return {**base, "status": "invalid_response"}
            results, seen = [], set()
            # Wikipedia returns an infobox rather than an ordinary search result.
            # Preserve its actual source URL and text in the same bounded tool output.
            boxes = data.get("infoboxes") or []
            rows = []
            if category == "general" and isinstance(boxes, list):
                for box in boxes[:3]:
                    if not isinstance(box, dict):
                        continue
                    refs = box.get("urls") or []
                    url = public_url(box.get("id"))
                    if not url and isinstance(refs, list):
                        url = next((public_url(ref.get('url')) for ref in refs
                                    if isinstance(ref, dict) and public_url(ref.get('url'))), None)
                    if url and box.get('content'):
                        rows.append({'title': box.get('infobox'), 'url': url, 'content': box['content'],
                                     'engines': box.get('engines') or [box.get('engine', 'wikipedia')]})
            rows.extend(data['results'])
            for row in rows:
                if not isinstance(row, dict):
                    continue
                url = public_url(row.get("url"))
                image_url = public_url(row.get("img_src")) if category == "images" else None
                identity = image_url if category == "images" else url
                if not url or not identity or identity in seen:
                    continue
                parsed_url = urlsplit(url)
                if source == "mlp_wiki" and not (
                        parsed_url.hostname == "mlp.huijiwiki.com" and parsed_url.path.startswith("/wiki/")):
                    continue
                seen.add(identity)
                engines = row.get("engines", [])
                results.append({"title": plain(row.get("title"), 250), "url": url,
                    "snippet": plain(row.get("content"), 1000),
                    "published_at": plain(row.get("publishedDate"), 100) or None,
                    "engines": [plain(v, 60) for v in engines[:5]] if isinstance(engines, list) else []})
                if category == "images":
                    results[-1].update(image_url=image_url, source_url=url)
                if len(results) == 6:
                    break
            failures = data.get("unresponsive_engines") or []
            if not isinstance(failures, list):
                return {**base, "status": "invalid_response"}
            failures = [{"engine": plain(item[0], 60), "reason": plain(item[1], 150)}
                        for item in failures[:10] if isinstance(item, (list, tuple)) and len(item) >= 2]
            status = ("partial" if failures else "success") if results else ("unavailable" if failures else "no_results")
            return {**base, "status": status, "results": results, "unresponsive_engines": failures}
        except (asyncio.TimeoutError, httpx.TimeoutException):
            return {**base, "status": "timeout"}
        except httpx.HTTPStatusError as exc:
            return {**base, "status": "rate_limited" if exc.response.status_code == 429 else "unavailable"}
        except (httpx.RequestError, ValueError, TypeError, KeyError):
            return {**base, "status": "unavailable"}

    async def _read_with_recovery(self, url):
        if url in self.page_cache:
            return {**self.page_cache[url], 'cached_this_turn': True}
        result = await self._read_page(url)
        if result['status'] in {'access_denied', 'unavailable', 'timeout', 'rate_limited', 'empty'}:
            snapshot = await asyncio.to_thread(read_snapshot, url, self.snapshot_dir)
            if snapshot:
                result = {**snapshot, 'provider': 'mlp_wiki_snapshot', 'status': 'success',
                          'requested_url': url, 'freshness': 'local_snapshot',
                          'retrieved_at': result['fetched_at'], 'fetched_at': None,
                          'online_status': result['status'],
                          'note': AUTONOMOUS_WEB_SEARCH_TEXT['result_1'] + mlp_reference}
        if result['status'] == 'success':
            self.page_cache[url] = dict(result)
        return result

    async def _read_page(self, url):
        base = {"provider": "direct_webpage", "requested_url": url,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "note": AUTONOMOUS_WEB_SEARCH_TEXT['base_1']}
        self.page_calls += 1
        if not public_url(url):
            return {**base, "status": "blocked_url"}

        async def fetch():
            current = url
            async with _slots:
                async with httpx.AsyncClient(transport=self.transport, trust_env=False,
                        follow_redirects=False, timeout=14) as client:
                    for hop in range(4):
                        if not public_url(current):
                            raise _PageReadError("blocked_url")
                        original = httpx.URL(current)
                        if original.port not in {None, 80, 443}:
                            raise _PageReadError("blocked_port")
                        port = original.port or (443 if original.scheme == "https" else 80)
                        address = await self.resolver(original.host, port)
                        if not _allowed_resolved_address(original.host, address):
                            raise _PageReadError("blocked_address")
                        target = original.copy_with(host=address)
                        async with client.stream(
                            "GET",
                            target,
                            headers={
                                "Host": original.netloc.decode("ascii"),
                                "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.1",
                                "Accept-Encoding": "identity",
                                "User-Agent": "PonyChat-WebReader/1.0",
                            },
                            extensions={"sni_hostname": original.host},
                        ) as response:
                            if response.status_code in _REDIRECTS:
                                location = response.headers.get("location")
                                if hop == 3 or not location:
                                    raise _PageReadError("too_many_redirects")
                                current = urljoin(str(original), location)
                                continue
                            response.raise_for_status()
                            content_type = response.headers.get("content-type", "").lower()
                            media_type = content_type.split(";", 1)[0]
                            if not (media_type.startswith("text/") or media_type in {
                                    "application/xhtml+xml", "application/json"}):
                                raise _PageReadError("unsupported_content")
                            declared = response.headers.get("content-length")
                            if declared and (not declared.isdigit() or int(declared) > _PAGE_BYTES):
                                raise _PageReadError("page_too_large")
                            body = bytearray()
                            async for chunk in response.aiter_bytes(chunk_size=65536):
                                body.extend(chunk)
                                if len(body) > _PAGE_BYTES:
                                    raise _PageReadError("page_too_large")
                            return str(original), bytes(body), content_type, response.encoding
            raise _PageReadError("unavailable")

        try:
            final_url, body, content_type, encoding = await asyncio.wait_for(fetch(), timeout=20)
            if b'Just a moment...' in body[:8192] and b'cf-' in body[:8192]:
                raise _PageReadError('access_denied')
            title, content, truncated = _page_text(body, content_type, encoding)
            if not content:
                return {**base, "status": "empty", "url": final_url, "title": title}
            return {**base, "status": "success", "url": final_url, "title": title,
                    "content": content, "content_truncated": truncated, 'freshness': 'live'}
        except _PageReadError as exc:
            return {**base, "status": str(exc)}
        except (asyncio.TimeoutError, httpx.TimeoutException):
            return {**base, "status": "timeout"}
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            return {**base, 'http_status': code, "status": (
                'access_denied' if code in {401, 403} else 'rate_limited' if code == 429 else 'unavailable')}
        except (httpx.RequestError, OSError, UnicodeError, ValueError, TypeError):
            return {**base, "status": "unavailable"}

    def register(self, capability):
        capability("web_search", AUTONOMOUS_WEB_SEARCH_TEXT['register_2'] + mlp_reference + AUTONOMOUS_WEB_SEARCH_TEXT['register_1'], {
            "type": "object", "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 300},
                "url": {"type": "string", "minLength": 1, "maxLength": 2048},
                "source": {"type": "string", "enum": ["web", "mlp_wiki"]},
                "time_range": {"type": "string", "enum": ["", "day", "week", "month", "year"]}},
            "additionalProperties": False}, self.search)
