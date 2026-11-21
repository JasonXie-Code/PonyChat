"""Bounded event-loop stall evidence without request bodies or frame locals."""
import sys
import threading
import time


class LoopWatchdog:
    def __init__(self, loop, report, *, interval=.5, threshold=2., cooldown=30.):
        self.loop, self.report = loop, report
        self.interval, self.threshold, self.cooldown = interval, threshold, cooldown
        self.owner = threading.get_ident()
        self.last_tick = time.monotonic()
        self.last_report = float('-inf')
        self.stop_event = threading.Event()
        self.handle = None
        self.thread = threading.Thread(target=self._watch, name='event-loop-watchdog', daemon=True)

    def start(self):
        self._tick()
        self.thread.start()
        return self

    def _tick(self):
        if not self.stop_event.is_set():
            self.last_tick = time.monotonic()
            self.handle = self.loop.call_later(self.interval, self._tick)

    def _watch(self):
        while not self.stop_event.wait(self.interval):
            now = time.monotonic()
            delay = now - self.last_tick
            if delay < self.threshold or now - self.last_report < self.cooldown:
                continue
            self.last_report = now
            frame = sys._current_frames().get(self.owner)
            stack = []
            try:
                while frame is not None and len(stack) < 20:
                    stack.append(f'{frame.f_code.co_filename}:{frame.f_lineno} ({frame.f_code.co_name})')
                    frame = frame.f_back
            finally:
                del frame
            try:
                self.report('[EventLoopStall] heartbeat_lag=%.3fs thread=%s stack=%s',
                            delay, self.owner, ' <- '.join(stack))
            except Exception:
                # Diagnostics must never terminate the watcher or affect requests.
                pass

    def stop(self):
        # Called on the owning event loop; never join a logging thread on-loop.
        self.stop_event.set()
        if self.handle is not None:
            self.handle.cancel()
