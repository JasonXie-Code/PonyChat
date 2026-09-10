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
