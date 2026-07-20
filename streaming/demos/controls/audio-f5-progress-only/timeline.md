# Timeline – f5-tts

## Request
```json
{
  "ref_audio": "https://github.com/gradio-app/gradio/raw/main/test/test_files/audio_sample.wav",
  "ref_text": "Hello, this is a reference voice.",
  "gen_text": "This is a test of streaming text to speech, demonstrating how progressive audio chunks would improve latency.",
  "remove_silence": false,
  "api_name": "/predict"
}
```

## Timeline (chronological)

| Elapsed (s) | Code | Progress / Data | Notes |
|---|---|---|---|
| 0.5 | Status.STARTING |  | |
| 1.0 | Status.STARTING |  | |
| 1.5 | Status.PROCESSING |  | |
| 2.0 | Status.PROCESSING |  | |
| 2.5 | Status.PROCESSING |  | |
| 3.0 | Status.PROCESSING |  | |
| 3.5 | Status.PROCESSING |  | |
| 4.0 | Status.PROCESSING |  | |
| 4.5 | Status.PROCESSING |  | |
| 5.0 | Status.PROCESSING |  | |
| 5.51 | Status.PROCESSING |  | |
| 6.01 | Status.PROCESSING |  | |
| 6.51 | Status.PROCESSING |  | |
| 7.01 | Status.PROCESSING |  | |
| 7.51 | Status.FINISHED |  | |
| 8.01 | Status.FINISHED |  | |
| 8.51 | Status.FINISHED |  | |

## Final Response (truncated)
```json
{
  "result": "/tmp/gradio/134481ea26494a3da5b1bf6220b0c1533d8d7d72ad71935f6bb653a5a19e9af6/tmpu05xkvij.wav",
  "elapsed": 8.507962226867676
}
```

## Streaming Interpretation
- **Category:** Realtime streaming audio
- **Observed:** ZeroGPU init progress and PROCESSING. Audio generation itself not chunked in these spaces (except Kokoro original).
- **Ideal:** `gr.Audio(streaming=True)` yielding `(sample_rate, numpy_array)` chunks; MCP tool could return audio chunks incrementally for low latency playback.

## Files
- `timeline.jsonl`
- `response.json`
- `request.json`