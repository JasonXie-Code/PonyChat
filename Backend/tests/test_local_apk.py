"""Public APK pointers must switch safely without restarting the backend."""
import importlib.util
import json
from pathlib import Path

from fastapi import HTTPException
import pytest

from Backend.routes.system_impl import local_apk


def test_latest_pointer_is_read_per_request(tmp_path, monkeypatch):
    monkeypatch.setenv("PONYCHAT_LOCAL_APK_RELEASE_DIR", str(tmp_path))
    for code in (375, 376):
        filename = f"PonyChat-v5.6.{code - 340}-{code}-release.apk"
        (tmp_path / filename).write_bytes(b"verified apk fixture")
        (tmp_path / "latest.json").write_text(json.dumps({
            "filename": filename, "version_code": code, "bytes": 20,
        }))
        assert local_apk.latest_release()["version_code"] == code
        response = local_apk.file_response(filename)
        assert response.headers["cache-control"] == "no-cache"
        assert Path(response.path).parent == tmp_path


def test_distribution_rejects_escape_and_incomplete_publication(tmp_path, monkeypatch):
    monkeypatch.setenv("PONYCHAT_LOCAL_APK_RELEASE_DIR", str(tmp_path))
    for filename in ("../private.env", "C:/private.apk", "latest.json"):
        with pytest.raises(HTTPException) as caught:
            local_apk.release_file(filename)
        assert caught.value.status_code == 404
    with pytest.raises(HTTPException) as caught:
        local_apk.latest_release()
    assert caught.value.status_code == 503


def test_local_publisher_refuses_version_rollback(tmp_path):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("local_apk_publish", root / "Android-App/tools/local_apk_publish.py")
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    releases = tmp_path / "var/releases"
    releases.mkdir(parents=True)
    (releases / "latest.json").write_text('{"version_code":376}')
    with pytest.raises(RuntimeError, match="older version"):
        publisher.publish_local(tmp_path, tmp_path / "older.apk", {"version_code": 375}, lambda _: "unused")


def test_release_notes_survive_publication_and_version_api(tmp_path, monkeypatch):
    import asyncio
    from Backend.routes.system import get_app_version
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('notes_publisher', root / 'Android-App/tools/local_apk_publish.py')
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    apk = tmp_path / 'PonyChat-v6.0.38-416-release.apk'
    apk.write_bytes(b'apk')
    report = dict(version_name='6.0.38', version_code=416, sha256='test-hash',
                  bytes=3, certificate_sha256='test-cert')
    with pytest.raises(RuntimeError, match='release notes'):
        publisher.publish_local(tmp_path, apk, report, lambda _: 'test-hash')
    notes = '长期记忆默认开启。\n修复关系刷新。'
    publisher.publish_local(tmp_path, apk, dict(report, release_notes=notes), lambda _: 'test-hash')
    monkeypatch.setenv('PONYCHAT_LOCAL_APK_RELEASE_DIR', str(tmp_path / 'var/releases'))
    result = asyncio.run(get_app_version())
    assert result['release_notes'] == notes
    assert result['version_code'] == 416
