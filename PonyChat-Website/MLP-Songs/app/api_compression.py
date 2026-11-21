"""Compress API bodies before the private relay, leaving media byte ranges exact."""
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.gzip import GZipMiddleware


def accepts_gzip(value):
    choices = {}
    for item in value.lower().split(','):
        name, *parameters = item.strip().split(';')
        quality = 1.0
        for parameter in parameters:
            if parameter.strip().startswith('q='):
                try:
                    quality = float(parameter.strip()[2:])
                except ValueError:
                    quality = 0
        choices[name] = quality
    return 0 < choices.get('gzip', choices.get('*', 0)) <= 1


class ApiCompression:
    def __init__(self, app):
        self.app = app
        self.compressed = GZipMiddleware(app, minimum_size=1024, compresslevel=5)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope.get('path', '').startswith('/api/'):
            await self.app(scope, receive, send)
            return
        if accepts_gzip(Headers(scope=scope).get('accept-encoding', '')):
            await self.compressed(scope, receive, send)
            return

        async def vary(message):
            if message['type'] == 'http.response.start':
                MutableHeaders(scope=message).add_vary_header('Accept-Encoding')
            await send(message)
        await self.app(scope, receive, vary)
