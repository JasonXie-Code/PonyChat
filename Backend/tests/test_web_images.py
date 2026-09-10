"""Real image bytes, isolated network, Agent selection and phone-receipt deletion."""
import asyncio
import base64
import importlib
import importlib.util
import json
from io import BytesIO
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from test_autonomous_normal import PACKAGE, turn, model_result

search_module = importlib.import_module(PACKAGE + '.autonomous_web_search')
downloads = importlib.import_module(PACKAGE + '.web_image_download')
images = importlib.import_module(PACKAGE + '.autonomous_web_images')
stickers = importlib.import_module(PACKAGE + '.autonomous_stickers')
units = importlib.import_module(PACKAGE + '.assistant_units')

spec = importlib.util.spec_from_file_location('web_image_transfer_test', Path(__file__).parents[1] / 'chat_image_transfer.py')
transfer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = transfer
spec.loader.exec_module(transfer)


def png():
    output = BytesIO()
    Image.new('RGBA', (60, 40), (255, 0, 0, 255)).save(output, 'PNG')
    return output.getvalue()


async def public_resolver(host, port):
    return '93.184.216.34'


def downloader(handler=None):
    return downloads.PublicImageDownloader(resolver=public_resolver, transport=httpx.MockTransport(
        handler or (lambda req: httpx.Response(200, content=png(), headers={'content-type': 'image/png'}))))


def search_tool():
    return search_module.SearxngSearch(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={
        'results': [{'title': '红色图片', 'url': 'https://example.com/source', 'img_src': 'https://images.example.com/red.png'}]})))


def test_search_category_image_fields_dedup_and_shared_budget():
    requests = []
    def handle(req):
        requests.append(req)
        return httpx.Response(200, json={'results': [
            {'title': 'valid', 'url': 'https://example.com/page', 'img_src': 'https://example.com/a.png'},
            {'url': 'https://example.com/duplicate', 'img_src': 'https://example.com/a.png'},
            {'url': 'https://example.com/private', 'img_src': 'http://127.0.0.1/a.png'},
            {'url': 'https://example.com/no-image'}]})
    tool = search_module.SearxngSearch(transport=httpx.MockTransport(handle))
    async def run():
        result = await tool.search_images({'query': '红色图片'})
        assert len(result['results']) == 1
        assert result['results'][0]['source_url'] == 'https://example.com/page'
        await tool.search({'query': 'page'})
        await tool.search_images({'query': 'other'})
        assert (await tool.search_images({'query': 'limit'}))['status'] == 'budget_exhausted'
    asyncio.run(run())
    assert [r.url.params['categories'] for r in requests] == ['images', 'general', 'images']


def test_approximate_match_policy_reaches_search_results_and_tool_schema():
    tool = images.WebImageTools(search_tool(), username='test')
    registered = {}
    tool.register(lambda name, description, schema, callback: registered.update({name: description}))
    result = asyncio.run(tool.search({'query': '图片'}))
    for text in (result['note'], registered['search_images']):
        assert '选1至2张最接近的' in text
        assert '用户明确强调的必需条件' in text
        assert '不编造已发送' in text


def test_explicit_no_alternatives_rejects_approximate_stage():
    tool = images.WebImageTools(search_tool(), username='test')
    tool.candidates['fixture'] = {}
    tool.require_exact_match = True
    with pytest.raises(ValueError, match='禁止选择近似图'):
        asyncio.run(tool.stage({'image_ref': 'fixture', 'match_kind': 'approximate'}))


def test_download_pins_public_ip_retains_host_tls_and_normalizes_actual_pixels():
    seen = []
    def handle(req):
        seen.append(req)
        return httpx.Response(200, content=png(), headers={'content-type': 'image/png'})
    item = asyncio.run(downloader(handle).download('https://images.example.com/red.png'))
    assert seen[0].url.host == '93.184.216.34'
    assert seen[0].headers['host'] == 'images.example.com'
    assert seen[0].extensions['sni_hostname'] == 'images.example.com'
    picture = Image.open(BytesIO(item['data']))
    assert picture.format == 'JPEG' and picture.size == (60, 40)
    assert picture.getpixel((20, 20))[0] > 240


@pytest.mark.parametrize('url', ['http://127.0.0.1/x', 'http://169.254.169.254/x',
    'http://[::1]/x', 'http://localhost/x', 'file:///secret', 'https://user:pass@example.com/x',
    'http://example.com:8080/x'])
def test_unsafe_urls_never_reach_http(url):
    def forbidden(req):
        pytest.fail('Unsafe request sent')
    with pytest.raises(downloads.ImageDownloadError):
        asyncio.run(downloader(forbidden).download(url))


def test_redirect_to_private_dns_is_rejected_without_second_request():
    calls = []
    async def resolve(host, port):
        return '10.1.2.3' if host == 'private.example.com' else '93.184.216.34'
    def handle(req):
        calls.append(req)
        return httpx.Response(302, headers={'location': 'https://private.example.com/secret'})
    tool = downloads.PublicImageDownloader(resolver=resolve, transport=httpx.MockTransport(handle))
    with pytest.raises(downloads.ImageDownloadError, match='blocked_address'):
        asyncio.run(tool.download('https://example.com/start'))
    assert len(calls) == 1


@pytest.mark.parametrize('headers,body', [({'content-type': 'image/png'}, b'not an image'),
    ({'content-type': 'text/html'}, b'<html>login</html>'),
    ({'content-type': 'image/svg+xml'}, b'<svg/>'),
    ({'content-type': 'image/png', 'content-length': str(downloads.MAX_BYTES + 1)}, b'')])
def test_fake_formats_and_declared_size_fail(headers, body):
    with pytest.raises(downloads.ImageDownloadError):
        asyncio.run(downloader(lambda req: httpx.Response(200, headers=headers, content=body)).download('https://example.com/a'))


def test_decoded_dimensions_and_stream_size_are_bounded(monkeypatch):
    monkeypatch.setattr(downloads, 'MAX_PIXELS', 100)
    with pytest.raises(downloads.ImageDownloadError):
        downloads.normalize_image(png())
    monkeypatch.setattr(downloads, 'MAX_BYTES', 30)
    with pytest.raises(downloads.ImageDownloadError):
        asyncio.run(downloader().download('https://example.com/a'))


def test_agent_search_inspect_stage_and_phone_receipt_remove_only_owned_bytes():
    image_tools = images.WebImageTools(search_tool(), username='alice', downloader=downloader(),
                                      transfer_store=transfer.store_web_image_transfer)
    async def run_agent(prompt, config, tools, **kwargs):
        assert json.loads(prompt)['web_images_available'] is True
        result = await tools['search_images'].callback({'query': '红色图片'})
        ref = result['results'][0]['image_ref']
        with pytest.raises(images.HarnessToolValidationError):
            await tools['stage_web_image'].callback({'image_ref': ref})
        view = await tools['read_web_image'].callback({'image_ref': ref})
        assert Image.open(BytesIO(base64.b64decode(view['content'][1]['data']))).size == (60, 40)
        await tools['stage_web_image'].callback({'image_ref': ref, 'after_bubble_index': 0})
        return model_result('给你找到了一张红色图片。')
    result = asyncio.run(turn(messages=[{'role': 'user', 'content': '上网搜索一张红色图片发给我'}],
        web_search_tools=image_tools.search_provider, web_image_tools=image_tools, harness_runner=run_agent))
    request = SimpleNamespace()
    image_tools.apply_to_request(request, result['bubble_count'])
    attachment = request._assistant_asset_attachments[0]
    assert attachment['type'] == 'image' and attachment['metadata']['source_url'] == 'https://example.com/source'
    filename = attachment['url'].split('/')[-1]
    assert transfer.load_chat_image_transfer(filename)
    assert not transfer.discard_web_image_transfer(filename, 'bob')
    assert transfer.load_chat_image_transfer(filename)
    assert transfer.discard_web_image_transfer(filename, 'alice')
    assert transfer.load_chat_image_transfer(filename) is None
    assert transfer.discard_web_image_transfer(filename, 'alice')
    assert image_tools.downloaded == {}


def test_stickers_and_web_images_keep_requested_bubble_order():
    request = SimpleNamespace()
    first = {'type': 'sticker', 'metadata': {'request_id': 'sticker'}}
    second = {'type': 'image', 'metadata': {'request_id': 'web'}}
    stickers.apply_image_attachments(request, [(first, 0)], 2)
    stickers.apply_image_attachments(request, [(second, 1)], 2, append=True)
    result = units.build_assistant_units('one\n\ntwo', reply_sequence=request._assistant_reply_sequence,
                                        attachment_by_request_id=request._assistant_asset_by_request_id)
    assert [r['type'] for r in result] == ['asset', 'text', 'asset', 'text']
    assert result[2]['attachment']['type'] == 'image'


def test_failed_download_or_fabricated_ref_cannot_be_staged():
    tool = images.WebImageTools(search_tool(), username='alice', downloader=downloader(
        lambda req: httpx.Response(403)))
    async def run():
        with pytest.raises(images.HarnessToolValidationError):
            await tool.read({'image_ref': 'https://example.com/fake'})
        ref = (await tool.search({'query': 'picture'}))['results'][0]['image_ref']
        assert (await tool.read({'image_ref': ref}))['status'] == 'unavailable'
        with pytest.raises(images.HarnessToolValidationError):
            await tool.stage({'image_ref': ref})
        assert not tool.downloaded and not tool.selected
    asyncio.run(run())


def test_expiry_really_frees_bytes_without_another_request(monkeypatch):
    monkeypatch.setattr(transfer, '_CHAT_IMAGE_TRANSFER_TTL_SECONDS', 0.05)
    url = transfer.store_web_image_transfer(png(), 'image/png', 'alice')
    filename = url.split('/')[-1]
    time.sleep(.15)
    assert filename not in transfer._CACHE


def test_cancelled_agent_discards_staged_server_image():
    image_tools = images.WebImageTools(search_tool(), username='alice', downloader=downloader(),
        transfer_store=transfer.store_web_image_transfer, transfer_discard=transfer.discard_web_image_transfer)
    names = []
    async def cancelled(prompt, config, tools, **kwargs):
        ref = (await tools['search_images'].callback({'query': 'red'}))['results'][0]['image_ref']
        await tools['read_web_image'].callback({'image_ref': ref})
        await tools['stage_web_image'].callback({'image_ref': ref})
        names.extend(url.split('/')[-1] for url in image_tools.transfers.values())
        assert all(name in transfer._CACHE for name in names)
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(turn(web_image_tools=image_tools, harness_runner=cancelled))
    assert names and all(name not in transfer._CACHE for name in names)
    assert image_tools.downloaded == {}


def test_private_dns_answer_is_rejected_even_with_another_public_answer(monkeypatch):
    async def scenario():
        async def mixed(*args, **kwargs):
            return [(2, 1, 6, '', ('93.184.216.34', 443)), (2, 1, 6, '', ('10.0.0.1', 443))]
        monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', mixed)
        with pytest.raises(downloads.ImageDownloadError, match='blocked_address'):
            await downloads.resolve_public('example.com', 443)
    asyncio.run(scenario())


@pytest.mark.parametrize('answer', ['93.184.216.34', '10.0.0.1', '198.18.1.2', None])
def test_fake_ip_uses_verified_dns_and_rejects_unsafe_answers(monkeypatch, answer):
    original_client = httpx.AsyncClient
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={'Status': 0, 'Answer': (
            [{'type': 1, 'data': answer}] if answer else [])})
    monkeypatch.setattr(downloads.httpx, 'AsyncClient', lambda **kwargs:
        original_client(transport=httpx.MockTransport(handle), **kwargs))
    async def scenario():
        async def fake(*args, **kwargs):
            return [(2, 1, 6, '', ('198.18.1.103', 443))]
        monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', fake)
        if answer == '93.184.216.34':
            assert await downloads.resolve_public('images.example.com', 443) == answer
        else:
            with pytest.raises(downloads.ImageDownloadError, match='blocked_address'):
                await downloads.resolve_public('images.example.com', 443)
    asyncio.run(scenario())
    assert len(requests) == 1
    assert requests[0].url.host == '1.1.1.1'
    assert requests[0].url.params['name'] == 'images.example.com'


def test_fake_ip_literal_never_uses_fallback(monkeypatch):
    async def forbidden(host):
        pytest.fail('Literal Fake-IP must not reach fallback')
    monkeypatch.setattr(downloads, '_resolve_real_public', forbidden)
    with pytest.raises(downloads.ImageDownloadError, match='blocked_url'):
        asyncio.run(downloads.PublicImageDownloader().download('https://198.18.1.103/a.png'))


def test_image_metadata_survives_message_attachment_storage():
    spec = importlib.util.spec_from_file_location('web_image_attachment_test', Path(__file__).parents[1] / 'db/message_attachments.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.normalize_attachment({'type': 'image', 'url': '/chat_images/tmp_a.jpg',
        'metadata': {'source': 'web_search', 'source_url': 'https://example.com/page', 'ephemeral': True}})
    assert result['type'] == 'image' and json.loads(result['metadata_json'])['ephemeral'] is True
