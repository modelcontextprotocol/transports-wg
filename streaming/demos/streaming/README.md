# Content-streaming captures

| Directory | Semantics | First content | Content updates | Terminal |
|---|---|---:|---:|---:|
| `image-flux-streaming/` | Changing image snapshots | 2.586 s | 4 | 5.324 s |
| `text-gemma-streaming/` | Cumulative text snapshots; locally derived deltas | 4.141 s | 44 | 7.074 s |
| `audio-kokoro-streaming/` | New AAC artifacts exposed by HLS snapshots | 3.726 s | 5 | 10.345 s |
| `video-hls-streaming/` | New MPEG-TS artifacts exposed by HLS snapshots | 6.778 s | 7 | 24.486 s |
| `audio-asr-streaming-input/` | Stateful audio chunks produce revisable transcript snapshots | 31.366 s | 3 | 94.261 s |
| `document-ocr-streaming/` | Page events containing cumulative markdown snapshots | 7.765 s | 25 non-empty changes | 15.791 s |
| `video-understanding-streaming/` | Frame-observation snapshots followed by cumulative answer snapshots | 12.637 s | 38 answer changes | 23.556 s |
| `audio-asr-delta-reconciliation/` | Per-round provisional deltas followed by corrected confirmed snapshots | 2.484 s | 12 deltas + 4 updates | 15.805 s |

Important qualifications:

- Self-Forcing emitted 89 progress snapshots but only seven new media
  artifacts. The corpus records these as different event types.
- `gradio/stream_asr` preserves accumulated audio only when calls share a
  Gradio queue session. Independent simple `/call` requests are stateless.
- OvisOCR2 emitted 41 `stream` payloads but only 25 changing non-empty
  markdown snapshots.
- MOSS-VL observed all 11 sampled frames before lexical output began in the
  retained run; it did not interleave words with frame ingestion.
- Qwen realtime ASR deltas are appendable only within one inference round.
  Reconciled updates revise the pending transcript region.
