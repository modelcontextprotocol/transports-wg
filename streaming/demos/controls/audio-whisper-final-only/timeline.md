# Timeline – whisper

## Request
```json
{
  "inputs": "https://github.com/gradio-app/gradio/raw/main/test/test_files/audio_sample.wav",
  "task": "transcribe",
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
| 3.51 | Status.PROCESSING |  | |
| 4.01 | Status.FINISHED |  | |

## Final Response (truncated)
```json
{
  "result": " We'll be right back.",
  "elapsed": 4.006018877029419
}
```

## Streaming Interpretation
- **Category:** Text generation from audio input (ASR)
- **Observed:** STARTING -> PROCESSING -> FINISHED, returns transcript.
- **Ideal:** Stream partial transcript as audio chunks are processed, especially for long audio.

## Files
- `timeline.jsonl`
- `response.json`
- `request.json`