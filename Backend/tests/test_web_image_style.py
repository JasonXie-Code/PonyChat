import asyncio
import importlib

import httpx

from test_autonomous_normal import PACKAGE

style = importlib.import_module(PACKAGE + '.web_image_style')
derpi = importlib.import_module(PACKAGE + '.derpibooru_images')


def test_default_style_and_fallback_query():
    source = {'query': '碧琪', 'derpibooru_tags': 'pinkie pie, solo', 'rating': 'safe'}
    result = style.apply_style(source)
    assert result['derpibooru_tags'] == 'pinkie pie, solo, pony, vector, show accurate'
    assert result['g4_pony'] and 'G4' in result['query']
    assert source['query'] == '碧琪' and source['derpibooru_tags'] == 'pinkie pie, solo'
    assert style.apply_style(result)['derpibooru_tags'] == result['derpibooru_tags']


def test_explicit_user_style_and_non_pony_search_are_preserved():
    explicit = {'query': '碧琪人类形态油画', 'derpibooru_tags': 'pinkie pie, humanized',
                'rating': 'safe', 'style': 'user_requested'}
    assert style.apply_style(explicit) == explicit
    unrelated = {'query': '红玫瑰照片'}
    assert style.apply_style(unrelated) == unrelated


def test_default_exclusions_are_fixed_and_results_are_rechecked():
    def handle(request):
        query = request.url.params['q']
        assert 'pony, vector, show accurate' in query and '-humanized' in query and '-g5' in query
        return httpx.Response(200, json={'images': [
            {'id': i, 'score': 500-i, 'tags': tags,
             'representations': {'large': 'https://derpicdn.net/test.png'}}
            for i, tags in [(1, ['safe', 'pony', 'vector', 'show accurate', 'humanized']),
                            (2, ['safe', 'pony', 'vector', 'show accurate']),
                            (3, ['safe', 'pony', '3d'])]]})
    result = asyncio.run(derpi.search_ranked('pinkie pie, pony, vector, show accurate',
        rating='safe', g4_pony=True, transport=httpx.MockTransport(handle)))
    assert len(result) == 1 and result[0]['source_url'].endswith('/2')
