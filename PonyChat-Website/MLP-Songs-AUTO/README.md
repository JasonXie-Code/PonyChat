# MLP-Songs-AUTO

Automatic score-following demo for `music-auto.ponychat.org`.

Demo song:

- `source/audio/catchy-song.mp3`
- `source/scores/catchy-song.pdf`
- `source/charts/*.png`

Shared dependencies live in `P:\PonyChat\misc\tools`, not inside this project.

## Commands

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\build_demo.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

Local URL: `http://127.0.0.1:8777/`

## Pipeline

`build_demo.ps1` runs `scripts/build_demo.py`.

1. Run Audiveris from `P:\PonyChat\misc\tools\audiveris`.
2. Export MusicXML/MXL into `generated/omr`.
3. Parse MusicXML notes, lyrics, measures, harmony, pitch, and note duration.
4. Extract PDF chord text and tempo with `pypdf`.
5. Decode MP3 with ffmpeg and build an audio chroma matrix.
6. Build a score chroma matrix from MusicXML pitches and note durations.
7. Align score/audio with chroma cosine DTW, using spectral flux DTW only as fallback.
8. Extract Audiveris `.omr` notehead coordinates and project them onto the original PNG score pages.
9. Generate `generated/sync.json`, `generated/analysis.json`, `generated/report.json`, and notehead/layout metadata.

No manual timing, note-coordinate, or lyric-alignment data is used.
