# Kokoro audio-content stream

This capture calls the duplicated `hexgrad/Kokoro-TTS` Space through its raw
Gradio SSE endpoint. Each generator update points to an HLS EVENT playlist.
The capture client saves every changing playlist revision and downloads each
newly referenced AAC segment immediately.

## Result

- Terminal event: `complete`
- Time to first playable audio: **3.726 seconds**
- Changing playlist revisions: **5**
- Playable AAC segments: **5**
- Zero-duration framing segments: **1**
- Declared streamed duration: **63.450 seconds**
- Terminal time: **10.345 seconds**
- Reconstructed WAV duration: **63.829 seconds**
- Final format: mono, 24 kHz, PCM signed 16-bit WAV

The producer synthesized substantially more audio than the wall-clock capture
time, but the important streaming property is that the first independently
playable 11.075-second AAC artifact was available 6.6 seconds before the tool
completed.

## Segment timeline

| Artifact | First available | Declared duration | Bytes |
|---|---:|---:|---:|
| `segment_000.aac` | 3.726 s | 11.075 s | 105,094 |
| `segment_002.aac` | 7.442 s | 12.950 s | 126,460 |
| `segment_003.aac` | 8.188 s | 12.750 s | 122,865 |
| `segment_004.aac` | 9.099 s | 13.675 s | 131,372 |
| `segment_005.aac` | 9.809 s | 13.000 s | 127,026 |

A 39-byte, zero-duration AAC separator produced after the first segment is
preserved but is not counted as usable audio content.

## Semantics

Gradio emits cumulative playlist snapshots. The useful media units are new AAC
files referenced for the first time by each changed playlist. All playlist
snapshots remain under `raw/playlists/`, and the downloaded media remains under
`artifacts/segments/`.

The final remote playlist was rewritten to stable local segment paths and then
reconstructed into `artifacts/final_audio.wav` with bundled FFmpeg. PyAV
independently validated every playable AAC segment and the final WAV.

## Evidence

- `request.json` — exact endpoint, text, voice, speed, and hardware choice
- `raw/events.jsonl` — every raw SSE line with arrival time
- `raw/playlists/` — every distinct playlist revision
- `raw/playlist_revisions.jsonl` — revision hashes, timing, and segment counts
- `artifacts/segments/` — all AAC artifacts
- `artifacts/final_playlist.m3u8` — stable local playlist
- `artifacts/final_audio.wav` — reconstructed and validated final audio
- `response.json` — segment metadata, hashes, timing, and codec validation
- `capture.py` — complete reproduction and validation client
- `source/space_app.py` — producer implementation
