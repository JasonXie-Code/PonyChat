"""Search tool schema and real style/provider path use the requested image subject."""
import asyncio
import importlib

import httpx
import pytest

from test_autonomous_normal import PACKAGE

images = importlib.import_module(PACKAGE + '.autonomous_web_images')
search = importlib.import_module(PACKAGE + '.autonomous_web_search')
derpi = importlib.import_module(PACKAGE + '.derpibooru_images')
style = importlib.import_module(PACKAGE + '.web_image_style')


@pytest.mark.parametrize('subject,tags', [
    ('pony', 'fluttershy, solo'),
    ('other', 'angel bunny, solo'),
    ('mixed', 'fluttershy, angel bunny'),
])
def test_requested_subject_reaches_derpibooru_without_extra_participants(monkeypatch, subject, tags):
    requests = []
    def respond(request):
        query = request.url.params['q']
        requests.append(query)
        if subject == 'pony':
            assert 'pony, vector, show accurate' in query and '-humanized' in query
            row_tags = ['safe', 'fluttershy', 'pony', 'vector', 'show accurate']
        else:
            assert 'pony' not in query and 'vector' not in query
            assert ('fluttershy' in query) == (subject == 'mixed')
            row_tags = ['safe', *tags.split(', ')]
        return httpx.Response(200, json={'images': [
            dict(id=i, score=100-i, tags=row_tags,
                 representations={'large': f'https://derpicdn.net/{i}.png'}) for i in range(1, 4)]})
    original = derpi.search_ranked
    tool = images.WebImageTools(search.SearxngSearch(transport=httpx.MockTransport(respond)), username='subject-test')
    result = asyncio.run(tool.search(dict(query=tags, derpibooru_tags=tags, subject_type=subject, rating='safe')))
    assert len(result['results']) == 3 and len(requests) == 1


def test_subject_is_required_before_search_and_exposed_to_agent():
    tool = images.WebImageTools(None, username='subject-test')
    schemas = {}
    tool.register(lambda name, description, schema, callback: schemas.update({name: schema}))
    assert 'subject_type' in schemas['search_images']['required']
    with pytest.raises(ValueError, match='subject_type'):
        asyncio.run(tool.search({'query': 'pet'}))


def test_pony_fallback_web_query_keeps_nonhuman_default():
    result = style.apply_style({'query': 'Fluttershy', 'subject_type': 'pony'})
    assert 'G4 pony' in result['query'] and '-human' in result['query']
    explicit = {'query': 'Fluttershy human form', 'subject_type': 'pony', 'style': 'user_requested'}
    assert style.apply_style(explicit) == explicit


def test_explicit_human_form_reaches_search_and_is_returned():
    def respond(request):
        query = request.url.params['q']
        assert query == 'safe, fluttershy, humanized'
        return httpx.Response(200, json={'images': [dict(id=7, score=100,
            tags=['safe', 'fluttershy', 'humanized'],
            representations={'large': 'https://derpicdn.net/7.png'})]})
    tool = images.WebImageTools(search.SearxngSearch(transport=httpx.MockTransport(respond)), username='subject-test')
    result = asyncio.run(tool.search(dict(query='Fluttershy human form', subject_type='other',
        style='user_requested', derpibooru_tags='fluttershy, humanized', rating='safe')))
    assert result['results'][0]['source_url'] == 'https://derpibooru.org/images/7'
