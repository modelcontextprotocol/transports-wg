# FLUX.1 Schnell — live denoising content stream

A local `gradio_client` called the temporary remote Space `evalstate/flux-streaming-denoising` on an A100 80 GB. The Space used a worker thread and queue to turn Diffusers' `callback_on_step_end` into live Gradio generator outputs. The Space was permanently deleted after capture.

## Request

- Model: `black-forest-labs/FLUX.1-schnell`
- Prompt: “a tiny astronaut hatching from a translucent blue egg on the moon, cinematic lighting”
- Seed: `12345`
- Dimensions: `768 × 768`
- Inference steps: `4`
- Endpoint: `/infer_streaming`

## Content timeline

| Yield | Elapsed | Content |
|---:|---:|---|
| 0 | 2.586 s | Decoded image from denoising step 1/4 |
| 1 | 3.422 s | Decoded image from denoising step 2/4 |
| 2 | 4.140 s | Decoded image from denoising step 3/4 |
| 3 | 4.729 s | Decoded image from denoising step 4/4 |
| 4 | 5.324 s | Final image; identical to step 4 |

The first four images have distinct SHA-256 hashes, proving that these are changing image-content snapshots rather than repeated progress notifications. The final result intentionally repeats the last denoising image.

## Files

- `request.json` — request parameters
- `raw/client_yields.jsonl` — each observed generator yield and arrival time
- `artifacts/chunks/chunk_00.webp` … `chunk_03.webp` — denoising snapshots
- `artifacts/final_image.webp` — final result
- `artifacts/denoising_contact_sheet.webp` — four-step visual comparison
- `response.json` — final API result metadata
- `capture.py` — local Gradio capture client
- `source/space_app.py` — deleted Space's queue-based implementation
- `raw/space_info.json` — runtime metadata before deletion
- `raw/run.log` — captured application logs
