"""Stream selected signed text assets compressed before the private relay.

This changes transport representation only. Asset admission, decoded signed
bytes, and byte-range responses remain the responsibility of the original app.
"""
import re

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.gzip import GZipResponder

from api_compression import accepts_gzip


_EVIDENCE = re.compile(
    r'/follow-media/generated/[a-z0-9-]+/acceptance-evidence/[A-Za-z0-9][A-Za-z0-9_.-]*\.json')
_FRONTEND = re.compile(
    r'/follow-media/v/[a-f0-9]{64}/generated/[a-z0-9-]+/accepted-frontend/[a-z0-9.-]+\.(?:js|css)')
_CLOCK = re.compile(
    r'/follow-media/v/[a-f0-9]{64}/generated/laughter-song/acceptance-evidence/reading-clock-source-systems\.json')


def selected_asset(path):
    return any(pattern.fullmatch(path) is not None for pattern in (_EVIDENCE, _FRONTEND, _CLOCK))


def vary_encoding(headers):
    if 'accept-encoding' not in {part.strip().lower() for part in headers.get('vary', '').split(',')}:
        headers.add_vary_header('Accept-Encoding')


def weak_etag(headers):
    etag = headers.get('etag')
    if etag and not etag.startswith('W/'):
        headers['ETag'] = 'W/' + etag


class SourceAssetCompression:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope['type'] != 'http' or scope.get('method') != 'GET'
                or not selected_asset(scope.get('path', '')) or 'range' in Headers(scope=scope)):
            await self.app(scope, receive, send)
            return
        gzip = accepts_gzip(Headers(scope=scope).get('accept-encoding', ''))

        async def representation_send(message):
            if message['type'] == 'http.response.start':
                headers = MutableHeaders(scope=message)
                vary_encoding(headers)
                if headers.get('content-encoding') == 'gzip':
                    weak_etag(headers)
            await send(message)

        async def guarded_app(current_scope, current_receive, compressed_send):
            output = send

            async def gate(message):
                nonlocal output
                if message['type'] == 'http.response.start':
                    headers = MutableHeaders(scope=message)
                    if (message['status'] == 200 and 'content-encoding' not in headers
                            and 'content-range' not in headers):
                        output = compressed_send
                    elif message['status'] == 304 and 'content-encoding' not in headers:
                        vary_encoding(headers)
                        if gzip:
                            weak_etag(headers)
                await output(message)

            await self.app(current_scope, current_receive, gate)

        if not gzip:
            await guarded_app(scope, receive, representation_send)
            return
        # FileResponse's optional sendfile extension bypasses body middleware.
        # Disable it only for this negotiated compressed representation so the
        # installed Starlette responder can compress each file chunk in turn.
        current_scope = dict(scope)
        current_scope['extensions'] = {key: value for key, value in scope.get('extensions', {}).items()
                                       if key != 'http.response.pathsend'}
        # Negotiation was already parsed above (including wildcard and q=0).
        # Select the streaming responder directly rather than reparsing with
        # GZipMiddleware's literal, case-sensitive substring check.
        await GZipResponder(guarded_app, minimum_size=1024, compresslevel=5)(
            current_scope, receive, representation_send)
