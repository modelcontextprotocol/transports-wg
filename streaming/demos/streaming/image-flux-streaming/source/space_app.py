import queue
import random
import threading
import traceback

import gradio as gr
import numpy as np
import spaces
import torch
from diffusers import DiffusionPipeline

MODEL_ID = "black-forest-labs/FLUX.1-schnell"
DTYPE = torch.bfloat16
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
MAX_SEED = np.iinfo(np.int32).max
MAX_IMAGE_SIZE = 2048

pipe = DiffusionPipeline.from_pretrained(MODEL_ID, torch_dtype=DTYPE).to(DEVICE)
pipe.vae.enable_slicing()


def decode_preview(pipeline, packed_latents, height, width):
    """Decode FLUX's packed latent representation into a PIL preview."""
    with torch.no_grad():
        latents = pipeline._unpack_latents(
            packed_latents, height, width, pipeline.vae_scale_factor
        )
        latents = (
            latents / pipeline.vae.config.scaling_factor
        ) + pipeline.vae.config.shift_factor
        decoded = pipeline.vae.decode(latents, return_dict=False)[0]
        return pipeline.image_processor.postprocess(decoded, output_type="pil")[0]


@spaces.GPU()
def infer_streaming(
    prompt,
    seed=42,
    randomize_seed=False,
    width=768,
    height=768,
    num_inference_steps=4,
):
    """Yield real image content from the denoising callback while FLUX runs."""
    if randomize_seed:
        seed = random.randint(0, MAX_SEED)

    events = queue.Queue()
    finished = object()

    def callback_on_step_end(pipeline, step, timestep, callback_kwargs):
        try:
            preview = decode_preview(
                pipeline, callback_kwargs["latents"], int(height), int(width)
            )
            events.put(("preview", step + 1, preview))
        except Exception:
            events.put(("preview_error", step + 1, traceback.format_exc()))
        return callback_kwargs

    def run_pipeline():
        try:
            generator = torch.Generator(device=DEVICE).manual_seed(int(seed))
            final_image = pipe(
                prompt=prompt,
                width=int(width),
                height=int(height),
                num_inference_steps=int(num_inference_steps),
                generator=generator,
                guidance_scale=0.0,
                callback_on_step_end=callback_on_step_end,
                callback_on_step_end_tensor_inputs=["latents"],
            ).images[0]
            events.put(("final", int(num_inference_steps), final_image))
        except Exception:
            events.put(("fatal_error", 0, traceback.format_exc()))
        finally:
            events.put(finished)

    worker = threading.Thread(target=run_pipeline, daemon=True)
    worker.start()

    preview_count = 0
    while True:
        event = events.get()
        if event is finished:
            break
        kind, step, payload = event
        if kind == "preview":
            preview_count += 1
            yield payload, int(seed), f"Denoising step {step}/{int(num_inference_steps)}"
        elif kind == "preview_error":
            print(payload, flush=True)
            yield None, int(seed), f"Preview decode failed at step {step}; generation continues"
        elif kind == "final":
            yield payload, int(seed), f"Done — final image ({preview_count} previews streamed)"
        else:
            raise RuntimeError(payload)

    worker.join()


examples = [
    "a tiny astronaut hatching from an egg on the moon",
    "a cat holding a sign that says hello world",
    "an anime illustration of a wiener schnitzel",
]

with gr.Blocks() as demo:
    gr.Markdown(
        "# FLUX.1 Schnell — live denoising content stream\n"
        "Each update is a decoded image emitted from `callback_on_step_end`, "
        "not a progress-only notification."
    )
    prompt = gr.Text(label="Prompt", value=examples[0])
    with gr.Row():
        seed = gr.Number(label="Seed", value=12345, precision=0)
        randomize_seed = gr.Checkbox(label="Randomize seed", value=False)
        steps = gr.Slider(1, 12, value=4, step=1, label="Inference steps")
    with gr.Row():
        width = gr.Slider(256, MAX_IMAGE_SIZE, value=768, step=32, label="Width")
        height = gr.Slider(256, MAX_IMAGE_SIZE, value=768, step=32, label="Height")
    run = gr.Button("Stream denoising", variant="primary")
    image = gr.Image(label="Current image")
    seed_out = gr.Number(label="Used seed", precision=0)
    status = gr.Textbox(label="Status")
    run.click(
        infer_streaming,
        [prompt, seed, randomize_seed, width, height, steps],
        [image, seed_out, status],
        api_name="infer_streaming",
        concurrency_limit=1,
    )

demo.queue(default_concurrency_limit=1).launch(mcp_server=True)
