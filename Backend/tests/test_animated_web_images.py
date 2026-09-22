import asyncio
import base64
from io import BytesIO

import httpx
from PIL import Image

from test_web_images import images, downloads, transfer, search_module
from test_derpibooru_images import module as derpi


def gif():
    out = BytesIO()
    Image.new('RGB', (20, 20), 'red').save(out, 'GIF', save_all=True,
        append_images=[Image.new('RGB', (20, 20), 'blue')], duration=[100, 200], loop=0)
    return out.getvalue()


def row(animated):
    return {'id': 7, 'score': 10, 'tags': ['safe', 'fluttershy'] + (['animated'] if animated else []),
            'animated': animated, 'representations': {'large': 'https://derpicdn.net/image.' + ('gif' if animated else 'png')}}


def test_animated_search_is_explicit_and_falls_back_to_static():
    queries = []
    def handle(request):
        q = request.url.params['q']
        queries.append(q)
        return httpx.Response(200, json={'images': [row(False)] if '-animated' in q else []})
    provider = search_module.SearxngSearch(transport=httpx.MockTransport(handle))
    result = asyncio.run(provider.search_images({'query': '柔柔动图', 'derpibooru_tags': 'fluttershy',
                                                'rating': 'safe', 'animated': True}))
    assert queries == ['safe, fluttershy, animated', 'safe, fluttershy, -animated']
    assert result['animation_fallback'] is True
    assert result['results'][0]['animated'] is False


def test_animated_success_does_not_search_static_and_filters_wrong_rows():
    queries = []
    def handle(request):
        queries.append(request.url.params['q'])
        return httpx.Response(200, json={'images': [row(False), row(True)]})
    provider = search_module.SearxngSearch(transport=httpx.MockTransport(handle))
    result = asyncio.run(provider.search_images({'query': '柔柔动图', 'derpibooru_tags': 'fluttershy',
                                                'rating': 'safe', 'animated': True}))
    assert len(queries) == 1 and len(result['results']) == 1
    assert result['animation_fallback'] is False and result['results'][0]['animated'] is True


def test_animation_bytes_survive_inspection_staging_and_transfer():
    raw = gif()
    class Downloader:
        async def download(self, url):
            return downloads.normalize_image(raw)
    tool = images.WebImageTools(None, username='gif-test', downloader=Downloader(),
        transfer_store=transfer.store_web_image_transfer, transfer_discard=transfer.discard_web_image_transfer)
    tool.candidates['web:gif'] = {'image_url': 'https://example.com/a.gif',
        'source_url': 'https://example.com/a', 'title': 'animation'}
    async def run():
        view = await tool.read({'image_ref': 'web:gif'})
        assert view['content'][1]['mimeType'] == 'image/jpeg'
        assert Image.open(BytesIO(base64.b64decode(view['content'][1]['data']))).format == 'JPEG'
        staged = await tool.stage({'image_ref': 'web:gif', 'match_kind': 'exact'})
        assert staged['animated'] is True
        url = tool.transfers['web:gif']
        assert url.endswith('.gif')
        data, mime = transfer.load_chat_image_transfer(url)
        assert data == raw and mime == 'image/gif'
        saved = Image.open(BytesIO(data))
        assert saved.n_frames == 2 and saved.info['loop'] == 0
        saved.seek(1)
        assert saved.info['duration'] == 200
        tool.discard()
        assert transfer.load_chat_image_transfer(url) is None
    asyncio.run(run())
