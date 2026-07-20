# Content-streaming captures

| Directory | Semantics | First content | Content updates | Terminal |
|---|---|---:|---:|---:|
| `image-flux-streaming/` | Changing image snapshots | 2.586 s | 4 | 5.324 s |
| `text-gemma-streaming/` | Cumulative text snapshots; locally derived deltas | 4.141 s | 44 | 7.074 s |
| `audio-kokoro-streaming/` | New AAC artifacts exposed by HLS snapshots | 3.726 s | 5 | 10.345 s |
| `video-hls-streaming/` | New MPEG-TS artifacts exposed by HLS snapshots | 6.778 s | 7 | 24.486 s |

Important qualifications:


- Self-Forcing emitted 89 progress snapshots but only seven new media
  artifacts. The corpus records these as different event types.
