# Timeline – wan555-i2v

## Request
```json
{
  "input_image": "/tmp/test_image.jpg",
  "prompt": "a cute cat dancing",
  "steps": 4,
  "duration": 2.0,
  "frame_multiplier": 16
}
```

## Timeline (chronological)

| Elapsed (s) | Code | Progress / Data | Notes |
|---|---|---|---|
| 1.0 | Status.STARTING |  | |
| 2.0 | Status.LOG |  LOG:['Waiting for a GPU to become available', 'info'] | |
| 3.0 | Status.LOG |  LOG:['Waiting for a GPU to become available', 'info'] | |
| 4.0 | Status.LOG |  LOG:['Waiting for a GPU to become available', 'info'] | |
| 5.0 | Status.LOG |  LOG:['Waiting for a GPU to become available', 'info'] | |
| 6.0 | Status.LOG |  LOG:['Waiting for a GPU to become available', 'info'] | |
| 7.0 | Status.LOG |  LOG:['Waiting for a GPU to become available', 'info'] | |
| 8.0 | Status.LOG |  LOG:['Waiting for a GPU to become available', 'info'] | |
| 9.0 | Status.LOG |  LOG:['Successfully acquired a GPU', 'success'] | |
| 10.0 | Status.PROGRESS | 0/4 steps | |
| 11.01 | Status.PROGRESS | 0/4 steps | |
| 12.01 | Status.PROGRESS | 1/4 steps | |
| 13.01 | Status.PROGRESS | 2/4 steps | |
| 14.01 | Status.PROGRESS | 2/4 steps | |
| 15.01 | Status.PROGRESS | 3/4 steps | |
| 16.01 | Status.PROGRESS | 3/4 steps | |
| 17.01 | Status.PROGRESS |  | |
| 18.01 | Status.PROGRESS | 2/3 clip Rendering Media | |
| 19.01 | Status.FINISHED |  | |
| 20.01 | Status.FINISHED |  | |

## Final Response (truncated)
```json
{
  "result": "('/tmp/gradio/0f40e96eac6e6d37e69438081f1a1857f7acf5803c12dff6834738c264d4a1e0/tmphv8fh3u1.mp4', '/tmp/gradio/0f40e96eac6e6d37e69438081f1a1857f7acf5803c12dff6834738c264d4a1e0/tmphv8fh3u1.mp4', 1229035046)",
  "elapsed": 20.00832462310791
}
```

## Streaming Interpretation
- **Category:** Video I2V with progress
- **Observed:** LOG `Waiting for GPU`, `Successfully acquired a GPU`, then `PROGRESS` steps 0/4..3/4, then `Rendering Media` clip 2/3.
- **Ideal:** Return GPU wait status, then denoising steps progress, then rendering progress, finally video file. Stream partial video preview.

## Files
- `timeline.jsonl`
- `response.json`
- `request.json`