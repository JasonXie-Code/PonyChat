import asyncio
import importlib
import httpx
import pytest
from test_autonomous_normal import PACKAGE

module = importlib.import_module(PACKAGE + '.derpibooru_images')
search = importlib.import_module(PACKAGE + '.autonomous_web_search')


def test_ranked_safe_candidates_and_fixed_sort():
    def handle(request):
        assert request.url.params['q'] == 'safe, twilight sparkle, hugging'
        assert request.url.params['filter_id'] == str(module.EVERYTHING_FILTER_ID)
        assert request.url.params['sf'] == 'score'
        assert request.url.params['sd'] == 'desc'
        return httpx.Response(200, json={'images': [
            {'id': i, 'score': score, 'tags': tags,
             'representations': {'large': 'https://derpicdn.net/img/a.png'}}
            for i, score, tags in [(1, 5, ['safe']), (2, 100, ['explicit']),
                                   (3, 50, ['safe'])]]})
    result = asyncio.run(module.search_ranked('twilight sparkle, hugging',
        rating='safe', transport=httpx.MockTransport(handle)))
    assert [r['score'] for r in result] == [50, 5]


@pytest.mark.parametrize('query', ['safe OR explicit', '*', 'rating:explicit', '-safe'])
def test_filter_injection_never_requests(query):
    def forbidden(request):
        pytest.fail('Invalid query reached network')
    assert asyncio.run(module.search_ranked(query, rating='safe', transport=httpx.MockTransport(forbidden))) == []


def test_no_results_falls_back_without_shared_call_limit():
    calls = []
    def handle(request):
        calls.append(request.url.host)
        return httpx.Response(200, json={'images': [], 'results': []})
    provider = search.SearxngSearch(transport=httpx.MockTransport(handle))
    async def run():
        for _ in range(3):
            await provider.search_images({'query': '紫悦', 'derpibooru_tags': 'twilight sparkle', 'rating': 'safe'})
        assert (await provider.search_images({'query': '紫悦', 'derpibooru_tags': 'twilight sparkle', 'rating': 'safe'}))['status'] == 'no_results'
    asyncio.run(run())
    assert len(calls) == 8


def test_rating_required():
    with pytest.raises(search.HarnessToolValidationError, match='rating'):
        asyncio.run(search.SearxngSearch().search_images({'query': '碧琪', 'derpibooru_tags': 'pinkie pie'}))


def test_requested_rating_is_sent_and_other_ratings_filtered():
    def handle(request):
        assert request.url.params['q'] == 'semi-grimdark, pinkie pie'
        return httpx.Response(200, json={'images': [
            {'id': i, 'score': 100, 'tags': [rating],
             'representations': {'large': 'https://derpicdn.net/a.png'}}
            for i, rating in [(1, 'safe'), (2, 'semi-grimdark')]]})
    rows = asyncio.run(module.search_ranked('pinkie pie', rating='semi-grimdark',
        transport=httpx.MockTransport(handle)))
    assert len(rows) == 1 and rows[0]['rating'] == 'semi-grimdark'


def test_repeated_requested_rating_tag_is_canonicalized():
    def handle(request):
        assert request.url.params['q'] == 'explicit, pony, vector'
        return httpx.Response(200, json={'images': [{
            'id': 1, 'score': 100, 'tags': ['explicit', 'pony', 'vector'],
            'representations': {'large': 'https://derpicdn.net/a.png'}}]})
    rows = asyncio.run(module.search_ranked('pony, explicit, vector', rating='explicit',
        transport=httpx.MockTransport(handle)))
    assert len(rows) == 1 and rows[0]['rating'] == 'explicit'


def test_g4_style_relaxes_vector_and_show_accurate_when_strict_results_are_few():
    calls = []
    def handle(request):
        calls.append(request.url.params['q'])
        if 'vector, show accurate' in request.url.params['q']:
            images = [{'id': 1, 'score': 100, 'tags': ['safe', 'pony', 'vector', 'show accurate'],
                       'representations': {'large': 'https://derpicdn.net/strict.png'}}]
        else:
            assert 'pony' in request.url.params['q']
            assert 'vector' not in request.url.params['q'] and 'show accurate' not in request.url.params['q']
            images = [{'id': 2, 'score': 90, 'tags': ['safe', 'pony'],
                       'representations': {'large': 'https://derpicdn.net/relaxed.png'}},
                      {'id': 3, 'score': 80, 'tags': ['safe', 'pony', '3d'],
                       'representations': {'large': 'https://derpicdn.net/excluded.png'}}]
        return httpx.Response(200, json={'images': images})
    rows = asyncio.run(module.search_ranked('pinkie pie, pony, vector, show accurate',
        rating='safe', g4_pony=True, transport=httpx.MockTransport(handle)))
    assert len(calls) == 2
    assert 'vector, show accurate' in calls[0] and 'vector' not in calls[1] and 'show accurate' not in calls[1]
    assert all(tag in calls[0] and tag in calls[1] for tag in ('pony', '-human', '-anthro', '-3d', '-g5'))
    assert [row['source_url'] for row in rows] == [
        'https://derpibooru.org/images/1', 'https://derpibooru.org/images/2']
    assert rows[0]['style_relaxed'] is False and rows[1]['style_relaxed'] is True


@pytest.mark.parametrize('rating', module.RATINGS)
def test_every_rating_uses_the_everything_filter(rating):
    def handle(request):
        assert request.url.params['q'] == f'{rating}, pinkie pie'
        assert request.url.params['filter_id'] == str(module.EVERYTHING_FILTER_ID)
        return httpx.Response(200, json={'images': [
            {'id': 1, 'score': 100, 'tags': [rating],
             'representations': {'large': 'https://derpicdn.net/a.png'}}]})
    rows = asyncio.run(module.search_ranked('pinkie pie', rating=rating,
        transport=httpx.MockTransport(handle)))
    assert len(rows) == 1 and rows[0]['rating'] == rating


def test_non_safe_empty_does_not_silently_change_rating():
    calls = []
    def handle(request):
        calls.append(request.url.host)
        return httpx.Response(200, json={'images': []})
    provider = search.SearxngSearch(transport=httpx.MockTransport(handle))
    result = asyncio.run(provider.search_images({'query': '碧琪',
        'derpibooru_tags': 'pinkie pie', 'rating': 'semi-grimdark'}))
    assert result['status'] == 'no_results' and calls == ['derpibooru.org']
