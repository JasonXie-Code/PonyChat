"""Real provider boundaries with deterministic transport and isolated archives."""
import asyncio
import hashlib
import importlib

import httpx
import pytest

from test_autonomous_web_search import web

snapshots = importlib.import_module(web.__package__ + '.mlp_wiki_snapshot')
URL = 'https://mlp.huijiwiki.com/wiki/辉麦与金梨果酱'


async def resolver(host, port):
    return '93.184.216.34'


def archive(tmp_path):
    body = '# 辉麦与金梨果酱\n\n父母来自苹果家与梨家，故事在第7季揭示。'
    (tmp_path / '辉麦与金梨果酱.txt').write_bytes(body.encode('utf-8'))
    return body


@pytest.mark.parametrize('failure', [403, 429, 503, 'timeout', 'challenge'])
def test_original_wiki_snapshot_recovers_online_failure(tmp_path, failure):
    body = archive(tmp_path)
    seen = []

    def handle(request):
        seen.append(request)
        if failure == 'timeout':
            raise httpx.ReadTimeout('network timeout')
        if failure == 'challenge':
            return httpx.Response(200, headers={'content-type': 'text/html'},
                                  text='<title>Just a moment...</title><script>cf-chl</script>')
        return httpx.Response(failure)

    tool = web.SearxngSearch(transport=httpx.MockTransport(handle), resolver=resolver, snapshot_dir=tmp_path)
    data = asyncio.run(tool.search({'url': URL, 'source': 'mlp_wiki'}))
    assert data['status'] == 'success' and data['provider'] == 'mlp_wiki_snapshot'
    assert data['freshness'] == 'local_snapshot' and data['fetched_at'] is None
    assert data['snapshot_captured_at'] is None and data['retrieved_at']
    assert data['content'] == body
    assert data['snapshot_sha256'] == hashlib.sha256((tmp_path / '辉麦与金梨果酱.txt').read_bytes()).hexdigest()
    assert data['online_status'] in {'access_denied', 'rate_limited', 'unavailable', 'timeout'}
    assert '不是最新网页' in data['note'] and web.MLP_CANON_SCOPE in data['note']
    assert data['url'] == URL and len(seen) == 1
    again = asyncio.run(tool.search({'url': URL}))
    assert again['cached_this_turn'] and len(seen) == 1
    assert tool.page_calls == 1 and tool.calls == 0


def test_live_page_wins_over_snapshot(tmp_path):
    archive(tmp_path)
    tool = web.SearxngSearch(resolver=resolver, snapshot_dir=tmp_path,
        transport=httpx.MockTransport(lambda r: httpx.Response(200,
            headers={'content-type': 'text/html'}, text='<h1>在线正文</h1>')))
    data = asyncio.run(tool.search({'url': URL}))
    assert data['provider'] == 'direct_webpage' and data['freshness'] == 'live'
    assert data['content'] == '在线正文'


def test_missing_snapshot_retains_online_failure(tmp_path):
    tool = web.SearxngSearch(resolver=resolver, snapshot_dir=tmp_path,
        transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    data = asyncio.run(tool.search({'url': URL}))
    assert data['status'] == 'access_denied' and data['http_status'] == 403
    assert 'content' not in data


def test_search_and_page_budgets_are_independent_and_bounded(tmp_path):
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.path == '/search':
            return httpx.Response(200, json={'results': []})
        return httpx.Response(200, headers={'content-type': 'text/html'}, text='<p>正文</p>')

    tool = web.SearxngSearch(resolver=resolver, snapshot_dir=tmp_path, transport=httpx.MockTransport(handle))

    async def exercise():
        for i in range(3):
            assert (await tool.search({'query': str(i)}))['status'] == 'no_results'
        for i in range(3):
            assert (await tool.search({'url': 'https://example.com/' + str(i)}))['status'] == 'success'
        assert (await tool.search({'query': 'fourth'}))['status'] == 'budget_exhausted'
        assert (await tool.search({'url': 'https://example.com/fourth'}))['status'] == 'budget_exhausted'
        assert (await tool.search({'url': 'https://example.com/0'}))['cached_this_turn']

    asyncio.run(exercise())
    assert len(seen) == 6 and tool.calls == tool.page_calls == 3


@pytest.mark.parametrize('url', [
    'https://example.com/wiki/辉麦与金梨果酱',
    'https://mlp.huijiwiki.com.evil.test/wiki/辉麦与金梨果酱',
    'https://mlp.huijiwiki.com:9999/wiki/辉麦与金梨果酱',
    'https://user@mlp.huijiwiki.com/wiki/辉麦与金梨果酱',
    'https://mlp.huijiwiki.com/wiki/辉麦与金梨果酱?action=edit',
    'https://mlp.huijiwiki.com/wiki/%00',
    'https://mlp.huijiwiki.com/wiki/../../private',
])
def test_snapshot_cannot_read_unrelated_or_unsafe_files(tmp_path, url):
    archive(tmp_path)
    assert snapshots.read_snapshot(url, tmp_path) is None


def test_snapshot_header_prevents_sanitized_filename_collision(tmp_path):
    (tmp_path / 'Foo_Bar.txt').write_text('# Foo:Bar\n\nwrong page', encoding='utf-8')
    assert snapshots.read_snapshot('https://mlp.huijiwiki.com/wiki/Foo%2FBar', tmp_path) is None


def test_snapshot_rejects_invalid_utf8_and_caps_output(tmp_path):
    path = tmp_path / '辉麦与金梨果酱.txt'
    path.write_bytes(b'\xff\xfe')
    assert snapshots.read_snapshot(URL, tmp_path) is None
    archive(tmp_path)
    data = snapshots.read_snapshot(URL, tmp_path, max_chars=10)
    assert len(data['content']) == 10 and data['content_truncated']


def test_snapshot_does_not_override_private_dns_or_redirect_guard(tmp_path):
    archive(tmp_path)

    async def private(host, port):
        return '127.0.0.1'

    tool = web.SearxngSearch(resolver=private, snapshot_dir=tmp_path)
    assert asyncio.run(tool.search({'url': URL}))['status'] == 'blocked_address'
    redirect = web.SearxngSearch(resolver=resolver, snapshot_dir=tmp_path,
        transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})))
    assert asyncio.run(redirect.search({'url': URL}))['status'] == 'blocked_url'


def test_wiki_source_direct_read_must_stay_on_wiki(tmp_path):
    tool = web.SearxngSearch(snapshot_dir=tmp_path)
    with pytest.raises(web.HarnessToolValidationError):
        asyncio.run(tool.search({'url': 'https://example.com/', 'source': 'mlp_wiki'}))
