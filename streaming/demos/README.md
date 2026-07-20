# Streaming Examples – Gradio API client captures from remotely deployed HF Spaces

This folder contains live demo calls to remotely deployed Hugging Face Spaces,
capturing streaming progress, partial results, and final outputs. Captures use
either `gradio_client` or the Space's raw Gradio SSE endpoint, depending on
which representation exposes the streaming behavior most faithfully.

## Structure

Positive captures are under `streaming/`; progress-only and final-only
comparisons are under `controls/`.

Each positive capture preserves:

- `request.json` — the request sent to the remote producer
- `raw/` — raw SSE lines and playlist revisions as observed
- `artifacts/` — downloaded images, audio segments, video segments, and finals
- `response.json` — measured timing and media information
- `capture.py` — the script used to collect the evidence
- `source/` — relevant producer source and endpoint information
- `timeline.md` — a human-readable account of the capture

## Captured Demos

### 1. Diffusion – denoising progress
**`controls/image-flux-progress-only` (black-forest-labs/FLUX.1-schnell, 5084 likes)**

Gradio API:
```python
predict(prompt, seed, randomize_seed, width, height, num_inference_steps, api_name="/infer") -> (result, seed)
```

Timeline shows:
- `STARTING` → `PROCESSING`
- `PROGRESS` desc="ZeroGPU init" 10% → 92% (0-6 sec)
- `PROGRESS` 2/4 steps → 3/4 steps (denoising)
- `FINISHED`

Streaming opportunity: yield intermediate decoded latents each step. Current returns only final image (`image.webp`). See `final_image.webp` and `timeline.md`.

**Similar:** `stabilityai/stable-diffusion-3.5-large` same pattern.

#### `image-flux-streaming` – **verified image-content streaming**

We subsequently deployed a temporary modified FLUX.1 Schnell Space on an
A100 80 GB. A worker thread ran Diffusers while
`callback_on_step_end` decoded FLUX's packed latents and placed each image in
a queue consumed by the Gradio generator.

The remote call returned four distinct 768×768 WebP images during a four-step
generation:

| Step | Elapsed |
|---:|---:|
| 1/4 | 2.586 s |
| 2/4 | 3.422 s |
| 3/4 | 4.140 s |
| 4/4 | 4.729 s |
| Final | 5.324 s |

The first four images have distinct SHA-256 hashes. This demonstrates actual
changing image content, not `gr.Progress` events. The temporary remote Space
was permanently deleted after capture.

Evidence: `streaming/image-flux-streaming/raw/client_yields.jsonl`,
`streaming/image-flux-streaming/artifacts/denoising_contact_sheet.webp`, and
`streaming/image-flux-streaming/timeline.md`. The deleted Space implementation and
local capture client are preserved as `source/space_app.py` and `capture.py`.

### 2. Video – progress as generating

#### a) `video-hls-streaming` – **verified MPEG-TS artifact streaming**
Description from Hub: "Generate streaming videos from text prompts in real time"
API:
```python
predict(prompt, seed, fps, api_name="/video_generation_handler_streaming") -> (live_stream, generation_status)
```
The canonical raw-SSE recapture distinguishes UI progress from media:

- **89** frame/status progress snapshots
- **8** distinct playlist revisions, including an initial empty manifest
- **7** newly available MPEG-TS content artifacts
- First playable video at **6.778 s**
- Completion at **24.486 s**
- Final media: **81 frames, 832×480, 15 FPS, H.264, 5.4 s**

Every TS artifact is preserved, hashed, and independently decoded. The local
playlist decodes to 81 frames. Because the HLS blocks are independently encoded
and separated by discontinuities, PyAV reconstructs a stable, timestamp-correct
MP4 while retaining the original TS artifacts for audit.

This corrects the exploratory interpretation: 89 generator yields are not 89
media chunks. Seven yields introduce new playable video artifacts; the rest
are progress snapshots.

Evidence: `streaming/video-hls-streaming/raw/events.jsonl`,
`streaming/video-hls-streaming/artifacts/segments/`, and
`streaming/video-hls-streaming/artifacts/final_video.mp4`.

#### b) `controls/video-wan-progress-only` (kulkas2pintu/wan555, 527 likes, trending 108, MCP server)
MCP URL: `https://kulkas2pintu-wan555.hf.space/gradio_api/mcp/`

API:
```
predict(input_image, last_image, prompt, steps, negative_prompt, duration_seconds, guidance_scale, guidance_scale_2, seed, randomize_seed, quality, scheduler, flow_shift, frame_multiplier, safe_mode, video_component, api_name="/generate_video") -> (generated_video, download_video, seed)
```

Timeline captured (20s):
- `STARTING`
- `LOG` "Waiting for a GPU to become available" (multiple polls 2-8s)
- `LOG` "Successfully acquired a GPU"
- `PROGRESS` 0/4 steps, 1/4, 2/4, 3/4
- `PROGRESS` "Rendering Media" clip 2/3
- `FINISHED` → `final_video.mp4` (32-frame clip)

Streaming benefit: return GPU wait ETA, then denoising progress, then intermediate frame previews, then final video.

### 3. Realtime / Streaming Audio

#### a) `controls/audio-qwen-progress-only` (Qwen/Qwen3-TTS, 2047 likes)
API:
- `/generate_voice_design` (text, language, voice_description) → (audio, status)
- `/generate_voice_clone` (ref_audio, ref_text, target_text)
- `/generate_custom_voice`

Timeline: ZeroGPU init 22%→66% then PROCESSING 12s → FINISHED. Returns wav + status. Should be `streaming=True` audio yielding chunks.

#### b) `controls/audio-f5-progress-only` (mrfakename/E2-F5-TTS, 2886 likes)
API: `predict(ref_audio, ref_text, gen_text, remove_silence) -> generated_speech`
Requires reference wav. We used `audio_sample.wav` from Gradio repo.
Timeline: STARTING → PROCESSING 7.5s → FINISHED. Non-streaming currently, but long TTS benefits from chunked return `(sample_rate, numpy_array)` streaming.

#### c) Original best reference (not directly callable due to closed API)
`hexgrad/Kokoro-TTS` (3399 likes) `app.py` shows:
```python
out_stream = gr.Audio(streaming=True, autoplay=True)
def generate_all(text, voice, speed):
    for _, ps, _ in pipeline(text, voice, speed):
        audio = models[False](ps, ref_s, speed)
        yield 24000, audio.numpy()
```
This is the canonical streaming audio pattern. Duplicates like `Remsky/Kokoro-TTS-Zero` show progress callback `update_progress(chunk_num, total_chunks, tokens_per_sec, rtf, ...)`.

MCP servers: `ResembleAI/Chatterbox` (1742 likes) MCP URL `https://resembleai-chatterbox.hf.space/gradio_api/mcp/` – TTS with voice styling, same benefit.

#### d) `audio-kokoro-streaming` – **verified AAC artifact streaming**

We recaptured the API-open duplicate through raw Gradio SSE and followed each
`/gradio_api/stream/.../playlist.m3u8` update to the underlying AAC artifacts.
The capture preserves every distinct playlist revision and downloads each new
segment when it first appears.

| Playable segment | First available | Duration | Bytes |
|---:|---:|---:|---:|
| 0 | 3.726 s | 11.075 s | 105,094 |
| 1 | 7.442 s | 12.950 s | 126,460 |
| 2 | 8.188 s | 12.750 s | 122,865 |
| 3 | 9.099 s | 13.675 s | 131,372 |
| 4 | 9.809 s | 13.000 s | 127,026 |

The stream completed at 10.345 seconds. The five playable segments declare
63.450 seconds of audio. A stable local HLS playlist was reconstructed into a
63.829-second mono 24 kHz WAV. PyAV validated every AAC artifact and the final
WAV; all segment and final-artifact hashes are recorded.

Evidence: `streaming/audio-kokoro-streaming/raw/events.jsonl`,
`streaming/audio-kokoro-streaming/artifacts/segments/`,
`streaming/audio-kokoro-streaming/artifacts/final_playlist.m3u8`, and
`streaming/audio-kokoro-streaming/artifacts/final_audio.wav`.

### 4. Text generation from input source (LLM token streaming)

#### `text-gemma-streaming` (huggingface-projects/gemma-4-12b-it)

This Space uses `gr.Server()` with custom FastAPI endpoint, not standard Blocks. We captured via direct HTTP:

- POST `/gradio_api/call/v2/chat` with `{text, files, history, thinking, max_new_tokens,...}` → `{"event_id": ...}`
- GET `/gradio_api/call/chat/{event_id}` SSE stream:
  `event: generating` + `data: [{"reasoning": "...", "content": "..."}]`

The cleaned capture disables thinking and requests exactly five short
sentences. It produced:

- First ordinary content at **4.141 s**
- **44** changing content snapshots
- **0** reasoning updates
- `event: complete` at **7.074 s**
- A complete 252-character, five-sentence final answer

The producer output uses cumulative snapshots. Every raw SSE line from the
successful capture remains available in
`streaming/text-gemma-streaming/raw/events.jsonl`.

The producer does **not** emit independent text chunks; it emits cumulative
snapshots. Comparing consecutive raw snapshots shows the newly added suffix,
but the producer does not label or send that suffix separately. The public
Space also runs on ZeroGPU, so live reproduction can fail
with allocation, quota, or runtime errors even though the retained canonical
capture completed successfully. This example is evidence for snapshot
streaming and the delta-versus-snapshot design question, not a claim of native
delta delivery.

Similar spaces: `Qwen/Qwen3.5-Omni-Offline-Demo` (omni multimodal), `burtenshaw/karpathy-llm-council` (MCP-tagged), `UnstableLlama/semancer-12b`.

### 5. Speech-to-text (input source → text)

#### `controls/audio-whisper-final-only` (openai/whisper, 2790 likes)
API: `predict(inputs, task) -> output`
Timeline: STARTING → PROCESSING 3.5s → FINISHED, returns transcript "We'll be right back."
Streaming benefit: for long audio, return partial transcript chunks.

## Reproduction – gradio_client

Install:
```bash
uv pip install gradio_client pillow requests -p <venv>
```

Example (flux):
```python
from gradio_client import Client
client = Client("black-forest-labs/FLUX.1-schnell")
job = client.submit("a tiny astronaut...", 0, True, 512, 512, 4, api_name="/infer")
while not job.done():
    print(job.status())
result = job.result()  # (image_path, seed)
```

Example (self-forcing streaming video):
```python
client = Client("multimodalart/self-forcing")
job = client.submit("a cat astronaut floating in space", -1, 15, api_name="/video_generation_handler_streaming")
# job.status().code goes STARTING -> PROCESSING -> ITERATING -> FINISHED
# result = ({'video': '.../playlist.m3u8'}, '<div>Stream Complete! Generated 81 frames...')
```

Example (LLM token streaming via raw HTTP SSE, no gradio_client):
```python
import requests
resp = requests.post("https://huggingface-projects-gemma-4-12b-it.hf.space/gradio_api/call/v2/chat", json=payload)
event_id = resp.json()["event_id"]
with requests.get(f"https://huggingface-projects-gemma-4-12b-it.hf.space/gradio_api/call/chat/{event_id}", stream=True) as r:
    for line in r.iter_lines():
        if line.startswith(b"data:"):
            print(json.loads(line[5:]))
```

## Why these benefit from MCP streaming

- **Diffusion**: intermediate denoised images give user feedback and allow early cancellation.
- **Video**: long generation (15-36s observed) with GPU queue waiting; progress + partial frames or HLS segments reduce perceived latency.
- **Audio TTS**: streaming chunks enable playback before full synthesis; crucial for long texts.
- **ASR / LLM**: token-by-token or partial transcript streaming enables real-time UX, tool chaining (e.g., ASR → LLM → TTS pipeline in `smolagents/hf-realtime-voice`).

All listed spaces have verified running status and many already tagged `mcp-server` (check via `hf discover search "video generation" --kind mcp`).
