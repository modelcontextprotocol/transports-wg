# Progress-only and final-only controls

These captures demonstrate workloads where the remote API reports status or
progress but does not deliver usable partial content.

| Directory | Modality | Observed behavior |
|---|---|---|
| `image-flux-progress-only/` | Image | Initialization and denoising progress, then final image |
| `video-wan-progress-only/` | Video | Queue, denoising, and rendering progress, then final MP4 |
| `audio-qwen-progress-only/` | Audio | Initialization/processing, then final WAV |
| `audio-f5-progress-only/` | Audio | Processing status, then final WAV |
| `audio-whisper-final-only/` | Text from audio | Processing status, then final transcript |

These retain their compact exploratory layout. They are comparison evidence,
not canonical positive streaming captures.

