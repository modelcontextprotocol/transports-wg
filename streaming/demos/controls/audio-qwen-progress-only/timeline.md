# Timeline – qwen-tts

## Request
```json
{
  "text": "Hello! Welcome to the streaming TTS demo. This audio is generated in real time and should benefit from chunked playback.",
  "language": "English",
  "voice_description": "Speak in a warm, clear, and enthusiastic tone, slightly fast, like a helpful assistant.",
  "api_name": "/generate_voice_design"
}
```

## Timeline (chronological)

| Elapsed (s) | Code | Progress / Data | Notes |
|---|---|---|---|
| 0.5 | Status.STARTING |  | |
| 1.0 | Status.STARTING |  | |
| 1.5 | Status.PROGRESS | 22/100 steps ZeroGPU init | |
| 2.0 | Status.PROGRESS | 66/100 steps ZeroGPU init | |
| 2.5 | Status.PROGRESS |  | |
| 3.0 | Status.PROGRESS |  | |
| 3.5 | Status.PROGRESS |  | |
| 4.0 | Status.PROGRESS |  | |
| 4.5 | Status.PROGRESS |  | |
| 5.01 | Status.PROGRESS |  | |
| 5.51 | Status.PROGRESS |  | |
| 6.01 | Status.PROGRESS |  | |
| 6.51 | Status.PROGRESS |  | |
| 7.01 | Status.PROGRESS |  | |
| 7.51 | Status.PROGRESS |  | |
| 8.01 | Status.PROGRESS |  | |
| 8.51 | Status.PROGRESS |  | |
| 9.01 | Status.PROGRESS |  | |
| 9.51 | Status.PROGRESS |  | |
| 10.01 | Status.PROGRESS |  | |
| 10.51 | Status.PROGRESS |  | |
| 11.01 | Status.PROGRESS |  | |
| 11.51 | Status.PROGRESS |  | |
| 12.01 | Status.PROGRESS |  | |
| 12.51 | Status.PROGRESS |  | |
| 13.01 | Status.PROGRESS |  | |
| 13.51 | Status.PROGRESS |  | |
| 14.01 | Status.FINISHED |  | |
| 14.51 | Status.FINISHED |  | |
| 15.01 | Status.FINISHED |  | |

## Final Response (truncated)
```json
{
  "result": "('/tmp/gradio/2bee92e13bfd9d900770d9747a6aac5491c82f4caf91c2e1b534d55fa98c6440/audio.wav', 'Voice design generation completed successfully!')",
  "elapsed": 15.013140439987183
}
```

## Streaming Interpretation
- **Category:** Realtime streaming audio
- **Observed:** ZeroGPU init progress and PROCESSING. Audio generation itself not chunked in these spaces (except Kokoro original).
- **Ideal:** `gr.Audio(streaming=True)` yielding `(sample_rate, numpy_array)` chunks; MCP tool could return audio chunks incrementally for low latency playback.

## Files
- `timeline.jsonl`
- `response.json`
- `final_info.json`
- `request.json`