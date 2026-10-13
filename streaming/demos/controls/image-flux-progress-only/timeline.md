# Timeline – flux-schnell

## Request
```json
{
  "prompt": "a tiny astronaut hatching from an egg on the moon, soft studio lighting",
  "seed": 0,
  "randomize_seed": true,
  "width": 512,
  "height": 512,
  "num_inference_steps": 4,
  "api_name": "/infer"
}
```

## Timeline (chronological)

| Elapsed (s) | Code | Progress / Data | Notes |
|---|---|---|---|
| 0.5 | Status.STARTING |  | |
| 1.0 | Status.PROCESSING |  | |
| 1.5 | Status.PROCESSING |  | |
| 2.0 | Status.PROGRESS | 10/100 steps ZeroGPU init | |
| 2.5 | Status.PROGRESS | 26/100 steps ZeroGPU init | |
| 3.0 | Status.PROGRESS | 36/100 steps ZeroGPU init | |
| 3.5 | Status.PROGRESS | 46/100 steps ZeroGPU init | |
| 4.0 | Status.PROGRESS | 55/100 steps ZeroGPU init | |
| 4.51 | Status.PROGRESS | 64/100 steps ZeroGPU init | |
| 5.01 | Status.PROGRESS | 73/100 steps ZeroGPU init | |
| 5.51 | Status.PROGRESS | 83/100 steps ZeroGPU init | |
| 6.01 | Status.PROGRESS | 92/100 steps ZeroGPU init | |
| 6.51 | Status.PROGRESS |  | |
| 7.01 | Status.PROGRESS |  | |
| 7.51 | Status.PROGRESS | 2/4 steps | |
| 8.01 | Status.PROGRESS |  | |
| 8.51 | Status.FINISHED |  | |
| 9.01 | Status.FINISHED |  | |

## Final Response (truncated)
```json
{
  "result": "('/tmp/gradio/ef0d9b4d06490598806ef0b21a36c1b45f0b1b996f6dcb13347e63487426795b/image.webp', 1286542496)",
  "elapsed": 9.008892297744751
}
```

## Streaming Interpretation
- **Category:** Diffusion denoising
- **Observed streaming:** `gr.Progress(track_tqdm=True)` yields ZeroGPU init progress 10%->92% and inference steps 0/4 -> 2/4 etc.
- **Ideal streaming API:** Yield intermediate decoded images per step; current only returns final image.
- **MCP benefit:** Tool could return `progress` + `intermediate_image` each step, allowing UI to show denoising.

## Files
- `timeline.jsonl`
- `response.json`
- `request.json`