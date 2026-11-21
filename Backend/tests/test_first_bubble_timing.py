import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('first_bubble_timing', Path(__file__).parents[1] / 'Agent-Test/first_bubble_timing.py')
timing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timing)


def test_timing_ignores_accepted_and_handles_split_sse(monkeypatch):
    monkeypatch.setattr(timing.time, 'monotonic', lambda: 100)
    probe = timing.FirstBubbleTiming()
    probe.observe(b'data: {"type":"accepted"}\n\n')
    assert probe.first_bubble_seconds is None
    probe.observe(b'data: {"type":"assistant_para')
    monkeypatch.setattr(timing.time, 'monotonic', lambda: 112.5)
    probe.observe(b'graph","content":"hello"}\n\n')
    assert probe.first_bubble_seconds == 12.5
    monkeypatch.setattr(timing.time, 'monotonic', lambda: 140)
    probe.observe(b'data: {"type":"assistant_paragraph","content":"later"}\n\n')
    assert probe.first_bubble_seconds == 12.5
    probe.reset()
    assert probe.first_bubble_seconds is None
