"""Search provider failures, result boundaries and actual Agent registration."""
import asyncio
import importlib
import json

import httpx
import pytest

from test_autonomous_normal import normal, turn, model_result, PACKAGE

web = importlib.import_module(PACKAGE + '.autonomous_web_search')
explicit_search = importlib.import_module(PACKAGE + '.autonomous_contracts').explicit_search


def search(payload, *, code=200):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(code, json=payload)
    return web.SearxngSearch(transport=httpx.MockTransport(handle)), seen


def test_real_result_shape_and_private_url_filter():
    tool, seen = search({'results': [
        {'title': '<b>紫悦</b>', 'url': 'https://example.com/twilight', 'content': 'Twilight &amp; friends'},
        {'url': 'https://example.com/twilight'}, {'url': 'http://127.0.0.1/private'},
        {'url': 'javascript:alert(1)'}], 'unresponsive_engines': [['bing', 'timeout']]})
    data = asyncio.run(tool.search({'query': '紫悦'}))
    assert data['status'] == 'partial' and len(data['results']) == 1
    assert data['results'][0]['title'] == '紫悦'
    assert data['results'][0]['snippet'] == 'Twilight & friends'
    assert data['results'][0]['published_at'] is None
    assert seen[0].url.params['q'] == '紫悦'
    assert seen[0].url.params['language'] == 'all'
    assert seen[0].url.host == '127.0.0.1'


def test_mlp_wiki_search_is_site_scoped_and_filters_other_domains():
    tool, seen = search({'results': [
        {'title': '紫悦', 'url': 'https://mlp.huijiwiki.com/wiki/%E7%B4%AB%E6%82%A6',
         'content': '第一季中的角色资料'},
        {'title': 'untrusted', 'url': 'https://example.com/wiki/twilight', 'content': 'later story'},
    ], 'unresponsive_engines': []})
    data = asyncio.run(tool.search({'query': '紫悦 第一季', 'source': 'mlp_wiki'}))
    assert data['status'] == 'success' and data['source'] == 'mlp_wiki'
    assert len(data['results']) == 1
    assert data['results'][0]['url'].startswith('https://mlp.huijiwiki.com/wiki/')
    assert seen[0].url.params['q'] == 'site:mlp.huijiwiki.com/wiki/ 紫悦 第一季'
    assert '第1至第3季' in data['note']


@pytest.mark.parametrize('payload,code,status', [
    ({'results': []}, 200, 'no_results'),
    ({'results': [], 'unresponsive_engines': [['brave', 'blocked']]}, 200, 'unavailable'),
    ({'results': []}, 429, 'rate_limited'), ({}, 503, 'unavailable'),
    ({'not_results': []}, 200, 'invalid_response')])
def test_failures_are_explicit_without_fallback(payload, code, status):
    tool, seen = search(payload, code=code)
    assert asyncio.run(tool.search({'query': 'Twilight Sparkle'}))['status'] == status
    assert len(seen) == 1


def test_budget_and_timeout():
    tool, seen = search({'results': []})
    async def exercise():
        for _ in range(3):
            await tool.search({'query': 'pony'})
        assert (await tool.search({'query': 'pony'}))['status'] == 'budget_exhausted'
    asyncio.run(exercise())
    assert len(seen) == 3
    def timeout(request):
        raise httpx.ReadTimeout('private endpoint details')
    tool = web.SearxngSearch(transport=httpx.MockTransport(timeout))
    assert asyncio.run(tool.search({'query': 'pony'}))['status'] == 'timeout'


def test_wikipedia_infobox_is_delivered_and_deduplicated():
    tool, _ = search({'results': [{'title': 'duplicate', 'url': 'https://en.wikipedia.org/wiki/Twilight_Sparkle'}],
        'infoboxes': [{'infobox': 'Twilight Sparkle', 'id': 'https://en.wikipedia.org/wiki/Twilight_Sparkle',
                      'content': 'A fictional character.', 'engines': ['wikipedia']},
                     {'infobox': 'private', 'id': 'http://127.0.0.1/secret', 'content': 'hidden'}]})
    data = asyncio.run(tool.search({'query': 'Twilight Sparkle'}))
    assert data['status'] == 'success' and len(data['results']) == 1
    assert data['results'][0]['snippet'] == 'A fictional character.'
    assert data['results'][0]['engines'] == ['wikipedia']


def test_agent_calls_only_searxng_and_receives_calendar_context():
    tool, seen = search({'results': [{'title': 'Twilight', 'url': 'https://example.com', 'content': 'pony'}]})
    calendar = {'daily': [{'period': '2026-09-06', 'content': '今天的摘要'}], 'annual': []}
    async def runner(prompt, config, tools, **kw):
        assert set(tools) == {'web_search'}
        assert 'language' not in tools['web_search'].parameters['properties']
        assert 'url' in tools['web_search'].parameters['properties']
        assert tools['web_search'].parameters['properties']['source']['enum'] == ['web', 'mlp_wiki']
        assert json.loads(prompt)['calendar_memory'] == calendar
        data = await tools['web_search'].callback({'query': 'Twilight Sparkle'})
        assert data['provider'] == 'searxng' and data['results'][0]['title'] == 'Twilight'
        return model_result('我查到紫悦的资料了')
    data = asyncio.run(turn(web_search_tools=tool, calendar_memory=calendar, harness_runner=runner))
    assert data['tool_trace'][0]['tool'] == 'web_search'
    assert len(seen) == 1


def test_direct_webpage_read_extracts_visible_text_and_pins_public_dns():
    seen = []

    async def resolver(host, port):
        assert (host, port) == ('example.com', 443)
        return '198.18.1.23'

    def handle(request):
        seen.append(request)
        return httpx.Response(200, headers={'content-type': 'text/html; charset=utf-8'}, content=(
            '<html><head><title>示例页面</title><style>hidden</style></head>'
            '<body><main><h1>新品发布</h1><p>正文内容可以被角色阅读。</p>'
            '<script>ignore me</script></main></body></html>').encode())

    tool = web.SearxngSearch(transport=httpx.MockTransport(handle), resolver=resolver)
    data = asyncio.run(tool.search({'url': 'https://example.com/news'}))
    assert data['status'] == 'success'
    assert data['url'] == 'https://example.com/news'
    assert data['title'] == '示例页面'
    assert '正文内容可以被角色阅读' in data['content']
    assert 'ignore me' not in data['content'] and 'hidden' not in data['content']
    assert seen[0].url.host == '198.18.1.23'
    assert seen[0].headers['host'] == 'example.com'


def test_direct_webpage_blocks_private_redirect_and_invalid_arguments():
    async def resolver(host, port):
        return '93.184.216.34'

    def redirect(request):
        return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})

    tool = web.SearxngSearch(transport=httpx.MockTransport(redirect), resolver=resolver)
    assert asyncio.run(tool.search({'url': 'https://example.com/start'}))['status'] == 'blocked_url'
    with pytest.raises(web.HarnessToolValidationError):
        asyncio.run(tool.search({'query': 'pony', 'url': 'https://example.com'}))
    with pytest.raises(web.HarnessToolValidationError):
        asyncio.run(tool.search({}))

    async def private_resolver(host, port):
        return '192.168.1.20'

    private = web.SearxngSearch(transport=httpx.MockTransport(redirect), resolver=private_resolver)
    assert asyncio.run(private.search({'url': 'https://example.com/private'}))['status'] == 'blocked_address'


@pytest.mark.parametrize('text,expected', [
    ('看看这个 https://example.com/news', True),
    ('https://example.com/news', True),
    ('不要打开这个网址：https://example.com/private', False),
    ('Please open this link https://example.com/news', True),
])
def test_url_messages_trigger_bounded_web_tool(text, expected):
    assert explicit_search(text) is expected


def test_mlp_wiki_policy_requires_prompt_first_and_limits_relationship_history():
    assert '已有相关内容就直接回答，不调用网络工具' in web.MLP_WIKI_POLICY
    assert '角色自身的固有设定不受季数限制' in web.MLP_WIKI_POLICY
    assert '角色当前的关系、共同经历、事件发展和相识状态以《友谊就是魔法》第1至第3季为准' in web.MLP_WIKI_POLICY
    assert '即使第7季才揭示也可以查证后讲述' in web.MLP_WIKI_POLICY
    assert '不强加前三季关键词' in web.MLP_WIKI_POLICY


def test_later_revealed_background_survives_search_and_tool_guidance():
    tool, seen = search({'results': [
        {'title': '完美的一对', 'url': 'https://mlp.huijiwiki.com/wiki/完美的一对',
         'content': '第7季揭示的苹果嘉儿父母往事'},
    ]})
    data = asyncio.run(tool.search({'query': '苹果嘉儿 父母 爱情故事', 'source': 'mlp_wiki'}))
    assert data['results'] and data['status'] == 'success'
    assert seen[0].url.params['q'] == 'site:mlp.huijiwiki.com/wiki/ 苹果嘉儿 父母 爱情故事'
    registered = []
    tool.register(lambda *args: registered.append(args))
    for guidance in (data['note'], registered[0][1], web.MLP_WIKI_POLICY):
        assert web.MLP_CANON_SCOPE in guidance
        assert '不得把后续季新发生的结识' in guidance
        assert '旧角色档案' in guidance
