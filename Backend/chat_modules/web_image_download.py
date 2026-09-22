"""Bounded, memory-only public image downloads with DNS-pinned connections."""
import asyncio
import ipaddress
import socket
import warnings
from io import BytesIO
from urllib.parse import urljoin

import httpx
from PIL import Image, ImageOps

from .autonomous_web_search import public_url

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000
_slots = asyncio.Semaphore(2)
_FAKE_IP = ipaddress.ip_network('198.18.0.0/15')


class ImageDownloadError(ValueError):
    pass


async def _resolve_real_public(host):
    """Bypass local synthetic DNS through a fixed, TLS-verified resolver.

    Never connect to a Fake-IP or trust a proxy to enforce our SSRF boundary.
    Each redirect still resolves and pins its own validated public address.
    """
    async with httpx.AsyncClient(trust_env=False, timeout=6, follow_redirects=False) as client:
        async with client.stream('GET', 'https://1.1.1.1/dns-query',
                params={'name': host, 'type': 'A'},
                headers={'Accept': 'application/dns-json'}) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    raise ImageDownloadError('invalid_dns_response')
    import json
    try:
        result = json.loads(body)
        if result.get('Status') != 0 or result.get('TC'):
            raise ValueError('DNS lookup failed')
        addresses = [ipaddress.ip_address(row['data']) for row in result.get('Answer', [])
                     if row.get('type') in {1, 28}]
        if not addresses or any(not address.is_global for address in addresses):
            raise ImageDownloadError('blocked_address')
        return str(addresses[0])
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        if isinstance(exc, ImageDownloadError):
            raise
        raise ImageDownloadError('invalid_dns_response') from exc


async def resolve_public(host, port):
    rows = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(row[4][0] for row in rows))
    # Only synthetic answers trigger fallback. Mixed private/public answers
    # remain blocked; literal Fake-IP URLs are rejected by public_url as well.
    if addresses and all(ipaddress.ip_address(ip) in _FAKE_IP for ip in addresses):
        if not public_url('https://' + host):
            raise ImageDownloadError('blocked_address')
        return await _resolve_real_public(host)
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ImageDownloadError('blocked_address')
    return addresses[0]


def normalize_image(raw):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP', 'GIF'}:
                    raise ImageDownloadError('unsupported_image')
                if source.width * source.height > MAX_PIXELS:
                    raise ImageDownloadError('image_too_large')
                animated = getattr(source, 'is_animated', False)
                fmt = source.format
                if animated:
                    if source.width * source.height * source.n_frames > 200_000_000:
                        raise ImageDownloadError('animation_too_large')
                    for frame in range(source.n_frames):
                        source.seek(frame)
                        source.load()
                source.seek(0)
                picture = ImageOps.exif_transpose(source)
                picture.thumbnail((2560, 2560))
                rgba = picture.convert('RGBA')
                canvas = Image.new('RGB', rgba.size, 'white')
                canvas.paste(rgba, mask=rgba.getchannel('A'))
                output = BytesIO()
                canvas.save(output, 'JPEG', quality=88, optimize=True)
                data = output.getvalue()
                if len(data) > MAX_BYTES:
                    raise ImageDownloadError('image_too_large')
                if animated:
                    if len(raw) > MAX_BYTES:
                        raise ImageDownloadError('image_too_large')
                    return {'data': raw, 'mime_type': {'GIF': 'image/gif', 'WEBP': 'image/webp', 'PNG': 'image/png'}[fmt],
                            'width': source.width, 'height': source.height, 'animated': True,
                            'preview_data': data, 'preview_mime_type': 'image/jpeg'}
                return {'data': data, 'mime_type': 'image/jpeg', 'animated': False,
                        'width': canvas.width, 'height': canvas.height}
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageDownloadError('invalid_or_oversized_image') from exc


class PublicImageDownloader:
    def __init__(self, *, transport=None, resolver=resolve_public):
        self.transport, self.resolver = transport, resolver

    async def download(self, url):
        try:
            return await asyncio.wait_for(self._download(url), timeout=25)
        except (httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
            raise ImageDownloadError('download_unavailable') from exc

    async def _download(self, url):
        async with _slots:
            async with httpx.AsyncClient(transport=self.transport, trust_env=False,
                    follow_redirects=False, timeout=10) as client:
                for hop in range(4):
                    if not public_url(url):
                        raise ImageDownloadError('blocked_url')
                    original = httpx.URL(url)
                    if original.port not in {None, 80, 443}:
                        raise ImageDownloadError('blocked_port')
                    # Resolve once, connect to that exact public IP, retain TLS
                    # hostname verification and HTTP virtual-host routing.
                    ip = await self.resolver(original.host, original.port or (443 if original.scheme == 'https' else 80))
                    if not ipaddress.ip_address(ip).is_global:
                        raise ImageDownloadError('blocked_address')
                    target = original.copy_with(host=ip)
                    async with client.stream('GET', target,
                            headers={'Host': original.netloc.decode('ascii'),
                                     'Accept': 'image/jpeg,image/png,image/webp,image/gif',
                                     'Accept-Encoding': 'identity', 'User-Agent': 'PonyChat-Image/1.0'},
                            extensions={'sni_hostname': original.host}) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            if hop == 3 or not response.headers.get('location'):
                                raise ImageDownloadError('too_many_redirects')
                            url = urljoin(str(original), response.headers['location'])
                            continue
                        response.raise_for_status()
                        if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                            raise ImageDownloadError('encoded_response')
                        declared = response.headers.get('content-length')
                        if declared and (not declared.isdigit() or int(declared) > MAX_BYTES):
                            raise ImageDownloadError('image_too_large')
                        content_type = response.headers.get('content-type', '').split(';')[0].lower()
                        if content_type not in {'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'application/octet-stream'}:
                            raise ImageDownloadError('unsupported_image')
                        body = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            body.extend(chunk)
                            if len(body) > MAX_BYTES:
                                raise ImageDownloadError('image_too_large')
                        return await asyncio.to_thread(normalize_image, bytes(body))
        raise ImageDownloadError('download_unavailable')
