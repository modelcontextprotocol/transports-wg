# Self-Forcing video-content stream

This capture calls `multimodalart/self-forcing` through raw Gradio SSE. It
separates frame-level HTML progress from actual HLS media availability, saves
every changing playlist, and downloads each newly referenced MPEG-TS block.

## Result

- Terminal event: `complete`
- Time to first playable video block: **6.778 seconds**
- Frame/progress updates: **89**
- Changing playlist revisions: **8**, including the initial empty manifest
- Playable MPEG-TS artifacts: **7**
- Frames represented by artifacts: **81**
- Tool completion: **24.486 seconds**
- Final video: **81 frames, 832×480, 15 FPS, 5.4 seconds, H.264**

The prior exploratory capture described 89 outputs as content chunks. The
canonical evidence corrects that interpretation: **89 updates are progress/UI
snapshots, while seven updates introduce new playable media artifacts.**

## Media timeline

| Artifact | First available | Duration | Frames |
|---|---:|---:|---:|
| `segment_000.ts` | 6.778 s | 0.600 s | 9 |
| `segment_001.ts` | 8.825 s | 0.800 s | 12 |
| `segment_002.ts` | 10.888 s | 0.800 s | 12 |
| `segment_003.ts` | 13.069 s | 0.800 s | 12 |
| `segment_004.ts` | 15.413 s | 0.800 s | 12 |
| `segment_005.ts` | 17.841 s | 0.800 s | 12 |
| `segment_006.ts` | 20.169 s | 0.800 s | 12 |

The first 0.6-second playable block arrived about 17.7 seconds before terminal
completion. Later frame progress continued between block boundaries.

## Reconstruction

Every TS artifact independently validates as H.264, 832×480, 15 FPS. The local
HLS playlist decodes to 81 ordered frames. Because each block is independently
encoded and separated by an HLS discontinuity, PyAV decodes the original TS
artifacts in playlist order and re-encodes a stable H.264 MP4 with explicit
1/15-second timestamps. The resulting MP4 validates as 81 frames at 15 FPS and
5.4 seconds. The original TS artifacts remain unchanged for audit.

## Evidence

- `request.json` — exact endpoint, prompt, seed, and FPS
- `raw/events.jsonl` — every raw SSE line with arrival time
- `raw/playlists/` — every distinct HLS playlist revision
- `raw/playlist_revisions.jsonl` — playlist hashes and availability timing
- `artifacts/segments/` — seven original MPEG-TS artifacts
- `artifacts/final_playlist.m3u8` — stable local playlist
- `artifacts/final_video.mp4` — validated reconstructed video
- `response.json` — timing, hashes, frame counts, and codec metadata
- `capture.py` — complete reproduction and validation client
