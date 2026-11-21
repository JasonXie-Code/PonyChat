"""Independent deadlines for SDK model steps, excluding tool execution."""
import asyncio


class ModelCallTimeoutError(asyncio.TimeoutError):
    pass


class ModelCallDeadline:
    def __init__(self, seconds):
        self.seconds = seconds
        self.loop = asyncio.get_running_loop()
        self.expired = asyncio.Event()
        self.handles = {}
        self.closed = False

    def observe(self, kind, data):
        if self.seconds is not None:
            self.loop.call_soon_threadsafe(self.event, kind, dict(data))

    def event(self, kind, data):
        if self.closed or data.get('turn') is None or data.get('step') is None:
            return
        key = (str(data['turn']), str(data['step']))
        if kind == 'step/start' and key not in self.handles:
            self.handles[key] = self.loop.call_later(self.seconds, self.expired.set)
        elif kind in ('assistant/message', 'step/end'):
            handle = self.handles.pop(key, None)
            if handle:
                handle.cancel()

    def close(self):
        self.closed = True
        for handle in self.handles.values():
            handle.cancel()
        self.handles.clear()
