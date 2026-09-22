import asyncio
import json
from types import SimpleNamespace

import httpx

from Backend.chat_modules.derpibooru_images import search_ranked as search_derpi
from Backend.chat_modules.twibooru_images import search_ranked as search_twi
from Backend.routes import derpibooru_search as browser
from Backend.routes.derpibooru_search import SearchRequest, _clean_tags, _filter_known_tags, _mix_results
from Backend.chat_modules.booru_media import select_media


def test_animation_uses_playable_media_instead_of_still_thumbnail():
    assert select_media({'large': 'https://cdn.example/still.jpg',
                         'full': 'https://cdn.example/movie.webm'}, True).endswith('movie.webm')
    assert select_media({'large': 'https://cdn.example/still.png',
                         'full': 'https://cdn.example/moving.gif'}, True).endswith('moving.gif')
    assert select_media({'full': 'https://cdn.example/original.gif',
                         'webm': 'https://cdn.example/nonexistent.webm'}, True).endswith('original.gif')


def test_derpi_browser_retains_video_without_changing_chat_defaults():
    async def handler(request):
        return httpx.Response(200, json={'images': [{'id': 11, 'score': 4,
            'animated': True, 'tags': ['safe', 'animated'],
            'representations': {'full': 'https://cdn.example/video.webm'}}]})
    transport = httpx.MockTransport(handler)
    assert asyncio.run(search_derpi('animated', rating='safe', transport=transport)) == []
    rows = asyncio.run(search_derpi('animated', rating='safe', transport=transport, browser_media=True))
    assert rows[0]['video'] is True


def test_clean_tags_rejects_rating_and_boolean_syntax():
    assert _clean_tags(["Twilight Sparkle", "SAFE", "humanized OR pony", "cute", "cute"]) == [
        "twilight sparkle", "cute"]


def test_derpibooru_sort_and_source_are_forwarded():
    async def handler(request):
        assert request.url.params["sf"] == "created_at"
        assert request.url.params["page"] == "3"
        return httpx.Response(200, json={"images": [{"id": 4, "score": 8,
            "tags": ["safe", "twilight sparkle"], "representations": {"large": "https://cdn.example/a.png"},
            "created_at": "2026-01-01T00:00:00Z"}]})
    rows = asyncio.run(search_derpi("twilight sparkle", rating="safe", sort="time", page=3,
        transport=httpx.MockTransport(handler)))
    assert rows[0]["source"] == "Derpibooru"


def test_browser_pages_do_not_skip_three_images_per_page():
    async def handler(request):
        size = int(request.url.params['per_page'])
        page = int(request.url.params['page'])
        return httpx.Response(200, json={'images': [
            {'id': i, 'score': 1000-i, 'tags': ['safe', 'twilight sparkle'],
             'representations': {'large': 'https://cdn.example/a.png'}}
            for i in range((page-1)*size+1, page*size+1)
        ]})
    ids = []
    for page in range(1, 4):
        rows = asyncio.run(search_derpi('twilight sparkle', rating='safe', page=page,
            limit=9, browser_media=True, transport=httpx.MockTransport(handler)))
        ids.extend(int(row['id'].split(':')[1]) for row in rows)
    assert ids == list(range(1, 28))


def test_twibooru_normalizes_post_and_uses_everything_filter():
    async def handler(request):
        assert request.url.path == "/api/v3/search/posts"
        assert request.url.params["filter_id"] == "2"
        assert request.url.params["sf"] == "random"
        return httpx.Response(200, json={"posts": [{"id": 9, "score": 3, "media_type": "image",
            "thumbnails_generated": True, "hidden_from_users": False, "animated": False,
            "tags": ["suggestive", "pinkie pie"], "representations": {"large": "https://cdn.example/b.png"},
            "created_at": "2026-01-02T00:00:00Z"}]})
    rows = asyncio.run(search_twi("pinkie pie", rating="suggestive", sort="random",
        transport=httpx.MockTransport(handler)))
    assert rows[0]["source"] == "Twibooru"
    assert rows[0]["id"] == "twibooru:9"


def test_twibooru_keeps_webm_only_posts_for_android_video_rendering():
    async def handler(request):
        return httpx.Response(200, json={"posts": [{"id": 10, "score": 4, "media_type": "image",
            "thumbnails_generated": True, "hidden_from_users": False, "animated": True,
            "tags": ["safe", "twilight sparkle"],
            "representations": {"large": "https://cdn.example/a.webm", "thumb": "https://cdn.example/a.webm"}}]})
    rows = asyncio.run(search_twi("twilight sparkle", rating="safe",
        transport=httpx.MockTransport(handler)))
    assert rows[0]["image_url"] == "https://cdn.example/a.webm"
    assert rows[0]["video"] is True


def test_mixed_results_alternate_sources_without_losing_provider_order():
    derpi = [{"id": "d1"}, {"id": "d2"}]
    twi = [{"id": "t1"}, {"id": "t2"}, {"id": "t3"}]
    assert [row["id"] for row in _mix_results(derpi, twi, "score")] == [
        "d1", "t1", "d2", "t2", "t3"]


def test_negative_tags_survive_and_rating_cannot_be_excluded():
    assert _clean_tags('ts, -animated, -safe') == ['ts', '-animated']


def test_natural_translation_returns_model_selected_rating(monkeypatch):
    monkeypatch.setattr(browser.model_manager, 'get_model_for_task',
                        lambda task: {'model_name': 'test', 'api_key': 'key'})

    async def fake_call(payload, *args, **kwargs):
        assert 'Choose exactly one content rating' in payload['messages'][0]['content']
        return SimpleNamespace(text='{"tags":["Twilight Sparkle","night"],"rating":"safe"}')

    monkeypatch.setattr(browser, 'call_llm_payload', fake_call)
    assert asyncio.run(browser.translate_query('夜晚的紫悦', 'tester')) == (
        ['twilight sparkle', 'night'], 'safe')


def test_natural_search_uses_model_rating_for_both_sources(monkeypatch):
    async def authenticate(*args):
        return 'tester'

    async def translate(*args):
        return ['twilight sparkle', 'animated'], 'suggestive'

    ratings = []

    async def provider(tags, *, rating, **kwargs):
        ratings.append(rating)
        return []

    monkeypatch.setattr(browser, '_authenticated_username', authenticate)
    monkeypatch.setattr(browser, 'translate_query', translate)

    async def keep_tags(tags):
        return tags

    monkeypatch.setattr(browser, '_filter_known_tags', keep_tags)
    monkeypatch.setattr(browser, 'search_ranked', provider)
    monkeypatch.setattr(browser, 'search_twibooru', provider)
    response = asyncio.run(browser.search(SearchRequest(
        username='tester', query='有些暗示意味的紫悦动图', mode='natural', rating='safe')))
    assert ratings == ['suggestive', 'suggestive']
    assert response['rating'] == 'suggestive'


def test_unknown_tags_are_removed_only_when_both_boorus_confirm_the_miss():
    async def handler(request):
        tag = request.url.params['q'].removeprefix('name:')
        if tag == 'twilight sparkle' and request.url.host == 'derpibooru.org':
            return httpx.Response(200, json={'tags': [{'name': 'twilight sparkle'}]})
        if tag == 'twi only' and request.url.host == 'twibooru.org':
            return httpx.Response(200, json={'tags': [{'name': 'twi only'}]})
        if tag == 'provider unavailable' and request.url.host == 'derpibooru.org':
            return httpx.Response(503)
        return httpx.Response(200, json={'tags': []})

    tags = ['twilight sparkle', 'twi only', 'invented prose', 'provider unavailable']
    assert asyncio.run(_filter_known_tags(tags, httpx.MockTransport(handler))) == [
        'twilight sparkle', 'twi only', 'provider unavailable']


def test_zero_result_natural_search_retries_without_confirmed_invalid_tags(monkeypatch):
    async def authenticate(*args):
        return 'tester'

    async def translate(*args):
        return ['twilight sparkle', 'lying', 'invented prose'], 'safe'

    async def filter_tags(tags):
        assert tags == ['twilight sparkle', 'lying', 'invented prose']
        return ['twilight sparkle', 'lying']

    queries = []

    async def provider(tags, **kwargs):
        queries.append(tags)
        return [] if 'invented prose' in tags else [{'id': kwargs.get('browser_media', False)}]

    monkeypatch.setattr(browser, '_authenticated_username', authenticate)
    monkeypatch.setattr(browser, 'translate_query', translate)
    monkeypatch.setattr(browser, '_filter_known_tags', filter_tags)
    monkeypatch.setattr(browser, 'search_ranked', provider)
    monkeypatch.setattr(browser, 'search_twibooru', provider)
    response = asyncio.run(browser.search(SearchRequest(
        username='tester', query='紫悦躺着', mode='natural', rating='safe')))
    assert queries == [
        'twilight sparkle, lying, invented prose',
        'twilight sparkle, lying, invented prose',
        'twilight sparkle, lying',
        'twilight sparkle, lying',
    ]
    assert response['tags'] == ['twilight sparkle', 'lying']
    assert response['has_more'] is True
    assert len(response['images']) == 2


def test_both_providers_forward_exclusions_and_remove_mislabeled_video():
    async def handler(request):
        assert '-animated' in request.url.params['q']
        rows = [
            {'id': 1, 'score': 5, 'tags': ['safe', 'ts'], 'animated': False,
             'media_type': 'image', 'thumbnails_generated': True,
             'representations': {'large': 'https://cdn.example/a.png'}},
            {'id': 2, 'score': 8, 'tags': ['safe', 'ts'], 'animated': False,
             'media_type': 'video', 'thumbnails_generated': True,
             'representations': {'full': 'https://cdn.example/b.webm'}},
            {'id': 3, 'score': 9, 'tags': ['safe', 'ts', 'animated'], 'animated': True,
             'media_type': 'image', 'thumbnails_generated': True,
             'representations': {'full': 'https://cdn.example/c.gif'}},
        ]
        return httpx.Response(200, json={'images': rows, 'posts': rows})
    transport = httpx.MockTransport(handler)
    derpi = asyncio.run(search_derpi('ts, -animated', rating='safe', transport=transport, browser_media=True))
    twi = asyncio.run(search_twi('ts, -animated', rating='safe', transport=transport))
    assert [r['id'] for r in derpi] == ['derpibooru:1']
    assert [r['id'] for r in twi] == ['twibooru:1']


def test_preview_prefers_small_motion_and_preserves_original():
    from Backend.chat_modules.booru_media import select_preview
    reps = {'full': 'https://cdn.example/full.webm', 'small': 'https://cdn.example/small.webm',
            'medium': 'https://cdn.example/medium.webm'}
    assert select_preview(reps, reps['full'], True) == reps['small']
    assert reps['full'] == 'https://cdn.example/full.webm'
    reps = {'full': 'https://cdn.example/full.gif', 'small': 'https://cdn.example/small.gif',
            'webm': 'https://cdn.example/nonexistent.webm'}
    assert select_preview(reps, reps['full'], True) == reps['small']


def test_preview_never_substitutes_still_for_motion():
    from Backend.chat_modules.booru_media import select_preview
    for full in ('movie.webm', 'moving.gif', 'moving.webp', 'moving.png'):
        original = 'https://cdn.example/' + full
        assert select_preview({'small': 'https://cdn.example/still.jpg'}, original, True) == original
    assert select_preview({'small': 'https://cdn.example/small.jpg'},
                          'https://cdn.example/full.jpg') == 'https://cdn.example/small.jpg'
