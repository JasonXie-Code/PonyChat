"""Serve verified playback copies without changing signed recording locators.

The batch producer verifies decoded alignment, hashes and peaks before atomically
publishing its complete manifest. Original media remain the signature inputs.
No partial progress manifest is ever eligible for playback.
"""
import json
import hashlib
from functools import lru_cache
import math
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import threading
from urllib.parse import urlsplit

from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse
from file_signature import signature
from runtime_paths import data_root

_LOCK = threading.RLock()
_STATE = None
_SHA = re.compile(r'[0-9a-f]{64}')
_LOSSLESS_FORMATS = {'audio/flac': '.flac', 'audio/wav': '.wav'}
_OPUS_FORMATS = {'audio/ogg': '.opus'}
_BATCH_FORMATS = {'music-peak-normalization-v1': _LOSSLESS_FORMATS,
                  'music-opus-playback-v1': _OPUS_FORMATS}
_AUDIO_EXTENSIONS = {'.aac', '.aif', '.aiff', '.alac', '.flac', '.m4a', '.mp3', '.oga',
                     '.ogg', '.opus', '.wav', '.webm', '.wma'}


def is_audio_asset(path):
    suffix = PurePosixPath(path).suffix.lower()
    return suffix in _AUDIO_EXTENSIONS or (mimetypes.guess_type(path)[0] or '').startswith('audio/')


class CatalogPlaybackOnly:
    """Keep static evidence audio off the public playback surface."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            path = scope['path']
            if not path.startswith('/audio/') and is_audio_asset(path):
                response = JSONResponse({'detail': 'Audio recording unavailable'}, status_code=404)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def clear_cache():
    global _STATE
    with _LOCK:
        _STATE = None
        _output_sha256.cache_clear()


def deployed_opus_only():
    return os.environ.get('MLP_DEPLOYED_OPUS_ONLY') == '1'


@lru_cache(maxsize=4096)
def _output_sha256(path, clock):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return digest if _clock(path) == clock else ''


def deployed_source_url(path):
    """Recognize an original recording locator without opening an original file."""
    if not deployed_opus_only():
        return None
    media = Path(os.environ['MLP_MEDIA_ROOT']) / 'audio'
    try:
        relative = Path(path).relative_to(media)
        if not relative.parts or '..' in relative.parts:
            return None
        return '/audio/' + relative.as_posix()
    except ValueError:
        return None


def deployed_recording_binding(path):
    """Return the original identity only while the manifest's Opus verifies."""
    url = deployed_source_url(path)
    if url is None:
        return None
    row = _manifest().get(url)
    if row is None:
        return None
    try:
        clock = _clock(row['path'])
        if clock != row['clock'] or _output_sha256(row['path'], clock) != row['output_sha256']:
            return None
        return row['source_sha256'], row['output_sha256'], clock
    except OSError:
        return None


def _clock(path):
    stat = path.stat()
    return signature(str(path), stat), stat.st_size, stat.st_mtime_ns


def _contained(root, relative):
    if not isinstance(relative, str) or '\\' in relative or ':' in relative:
        raise ValueError('Invalid normalized media locator')
    pure = PurePosixPath(relative)
    if pure.is_absolute() or '..' in pure.parts or not pure.parts:
        raise ValueError('Normalized media escaped root')
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Normalized media symlink escaped root')
    return path


def _manifest():
    global _STATE
    configured = os.environ.get('MLP_NORMALIZED_ROOT')
    if not configured:
        return {}
    root = Path(configured).resolve()
    media = Path(os.environ.get('MLP_MEDIA_ROOT', str(root / 'media'))).resolve()
    path = root / 'audio-normalization-manifest.json'
    try:
        with _LOCK:
            before = _clock(path)
            owner = (str(root), str(media), before)
            if _STATE is not None and _STATE[0] == owner:
                return _STATE[1]
            body = json.loads(path.read_bytes())
            if before != _clock(path):
                raise ValueError('Normalization manifest changed while reading')
            tracks = body.get('tracks')
            formats = _BATCH_FORMATS.get(body.get('schema'))
            deployed = deployed_opus_only()
            if deployed and formats is not _OPUS_FORMATS:
                raise ValueError('Deployed audio requires the verified Opus manifest')
            if formats is None or body.get('complete') is not True \
                    or not isinstance(tracks, list) or not tracks \
                    or body.get('expected_track_count') != len(tracks) \
                    or body.get('track_count') != len(tracks):
                raise ValueError('Only a complete verified normalization batch may activate')
            entries, ids = {}, set()
            for row in tracks:
                src, sid = row['src'], row['song_id']
                parts = urlsplit(src)
                relative = row['normalized_relative_path']
                peak = row['output_peak_dbfs']
                if formats is _OPUS_FORMATS:
                    output_valid = (row.get('bitrate_bps') == 320_000 and row['sample_rate'] == 48_000
                                    and row['channels'] == 2 and peak <= -.1)
                else:
                    output_valid = abs(peak + .1) <= .002
                if not isinstance(sid, str) or sid in ids or src in entries \
                        or parts.scheme or parts.netloc or parts.query or parts.fragment \
                        or not parts.path.startswith('/audio/') \
                        or row.get('content_type') not in formats \
                        or row.get('alignment_verified') is not True \
                        or not isinstance(relative, str) \
                        or not relative.startswith('audio-normalized/audio/') \
                        or not relative.endswith(formats[row['content_type']]) \
                        or not all(_SHA.fullmatch(row[k]) for k in ('source_sha256', 'output_sha256')) \
                        or not math.isfinite(row['gain_db']) \
                        or not math.isfinite(peak) or not output_valid \
                        or row['decoded_samples'] <= 0 or row['sample_rate'] <= 0 or row['channels'] <= 0:
                    raise ValueError('Malformed normalized recording')
                target = _contained(root, relative)
                clock = _clock(target)
                source = _contained(media / 'audio', parts.path[len('/audio/'):])
                source_clock = None if deployed else _clock(source)
                if clock[1] != row['output_size_bytes'] or (not deployed and clock[2] != row['output_mtime_ns']):
                    raise ValueError('Verified normalized output changed')
                if not deployed and (source_clock[1] != row['source_size_bytes'] or source_clock[2] != row['source_mtime_ns']):
                    raise ValueError('Verified original recording changed')
                if deployed and _output_sha256(target, clock) != row['output_sha256']:
                    raise ValueError('Deployed Opus hash differs from the manifest')
                entries[src] = dict(row, root=root, path=target, clock=clock,
                                    source_path=source, source_clock=source_clock)
                ids.add(sid)
            _STATE = owner, entries
            return entries
    except (OSError, ValueError, TypeError, KeyError):
        # A bad/replaced manifest cannot leave an earlier generation active.
        return {}


def playback_metadata(songs):
    """Attach the settings measured against the exact Opus that this URL serves."""
    entries = _manifest()
    if len(entries) != len(songs) or {r['song_id'] for r in entries.values()} != {s['id'] for s in songs}:
        return
    path = data_root() / 'loudness-playback.json'
    try:
        loudness = _loudness_metadata(path, _clock(path))
    except OSError:
        loudness = {}
    for song in songs:
        song.pop('loudnessPlayback', None)
        row = entries.get(urlsplit(song.get('src', '')).path)
        if row is not None and row['song_id'] == song['id']:
            song['source_src'] = song['src']
            song['normalizationGain'] = 1
            song['normalizedPeakDbfs'] = row['output_peak_dbfs']
            if row['content_type'] == 'audio/ogg':
                song['normalizedAudioExt'] = 'opus'
                song['normalizedAudioBitrate'] = row['bitrate_bps'] // 1000
                settings = loudness.get(row['output_sha256'])
                if settings is not None:
                    song['loudnessPlayback'] = settings
            elif row['content_type'] == 'audio/wav':
                song['normalizedAudioExt'] = 'wav'
            else:
                song.pop('normalizedAudioExt', None)
            if row['content_type'] != 'audio/ogg':
                song.pop('normalizedAudioBitrate', None)


@lru_cache(maxsize=4)
def _loudness_metadata(path, clock):
    try:
        body = json.loads(path.read_bytes())
        if _clock(path) != clock or body.get('target_lufs') != -11:
            return {}
        return {digest: {'gain': row['gain'], 'ceiling': row['ceiling'],
                         'integratedLufs': row['output_lufs']}
                for digest, row in body['tracks'].items() if isinstance(row, dict)
                and 0 < row['gain'] <= 32 and .1 <= row['ceiling'] <= 1
                and -70 < row['output_lufs'] <= 0 and -70 < row['true_peak_dbtp'] <= -1}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {}


def audio_response(audio_path, media_root, *, opus_only=False):
    """The original URL remains stable for exact signed-frame clock ownership."""
    root = Path(media_root).resolve()
    try:
        original = _contained(root / 'audio', audio_path)
        row = _manifest().get('/audio/' + audio_path)
        if (opus_only or deployed_opus_only()) and (row is None or row['content_type'] != 'audio/ogg'
                          or not -.104 <= row['output_peak_dbfs'] <= -.1):
            raise FileNotFoundError
        if row is not None:
            if _contained(row['root'], row['normalized_relative_path']) != row['path'] \
                    or _clock(row['path']) != row['clock']:
                raise ValueError('Verified normalized output changed')
            if deployed_opus_only():
                if deployed_recording_binding(original) is None:
                    raise ValueError('Deployed Opus recording changed')
            elif original != row['source_path'] or _clock(original) != row['source_clock']:
                raise ValueError('Original recording changed after normalization')
            normalization = ('opus-320kbps' if row['content_type'] == 'audio/ogg'
                             else 'peak-minus-0.1dbfs')
            return FileResponse(row['path'], media_type=row['content_type'], headers={
                'ETag': '"' + row['output_sha256'] + '"',
                'Cache-Control': 'no-cache, max-age=0, must-revalidate',
                'X-Audio-Normalized': normalization,
            })
        if not original.is_file():
            raise FileNotFoundError
        return FileResponse(original, headers={'Cache-Control': 'no-cache, max-age=0, must-revalidate'})
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(404, 'Audio recording unavailable') from error
