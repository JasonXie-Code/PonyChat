"""Resident inference must survive slow probes; recovery must respect ownership."""
from types import SimpleNamespace
from unittest.mock import Mock
from LocalLLM import supervise_gemma as supervisor


def test_live_model_never_probed_or_restarted(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, 'LOGS', tmp_path)
    monkeypatch.setattr(supervisor, 'configured_process', lambda: SimpleNamespace(pid=123))
    probe, launch = Mock(), Mock()
    monkeypatch.setattr(supervisor, 'listening', probe)
    monkeypatch.setattr(supervisor, 'launch', launch)
    assert supervisor.tick() == 123
    probe.assert_not_called()
    launch.assert_not_called()


def test_other_listener_is_never_stopped(monkeypatch):
    monkeypatch.setattr(supervisor, 'configured_process', lambda: None)
    monkeypatch.setattr(supervisor, 'listening', lambda _: True)
    launch = Mock()
    monkeypatch.setattr(supervisor, 'launch', launch)
    supervisor.tick(123)
    launch.assert_not_called()


def test_absent_model_recovered(monkeypatch):
    monkeypatch.setattr(supervisor, 'configured_process', lambda: None)
    monkeypatch.setattr(supervisor, 'listening', lambda _: False)
    launch = Mock()
    monkeypatch.setattr(supervisor, 'launch', launch)
    supervisor.tick(123)
    launch.assert_called_once()


def test_stop_marker_blocks_recovery(monkeypatch, tmp_path):
    marker = tmp_path / 'gemma.stop'
    marker.touch()
    monkeypatch.setattr(supervisor, 'STOP', marker)
    launch = Mock()
    monkeypatch.setattr(supervisor, 'launch', launch)
    assert supervisor.tick(123) == 123
    launch.assert_not_called()


def test_explicit_stop_marks_before_termination(monkeypatch, tmp_path):
    marker = tmp_path / 'gemma.stop'
    process = SimpleNamespace(pid=123, terminate=lambda: marker.exists() or (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(supervisor, 'LOGS', tmp_path)
    monkeypatch.setattr(supervisor, 'STOP', marker)
    monkeypatch.setattr(supervisor, 'configured_process', lambda: process)
    supervisor.stop()
    assert marker.exists()


def test_process_identity_requires_binary_alias_and_port():
    process = SimpleNamespace(exe=lambda: str(supervisor.BINARY),
        cmdline=lambda: ['llama-server', '--alias', supervisor.ALIAS, '--port', '8072'])
    assert supervisor.matches(process)
    assert not supervisor.matches(process, 8069)
    process.cmdline = lambda: ['llama-server', '--alias', 'other', '--port', '8072']
    assert not supervisor.matches(process)
