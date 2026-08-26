import os
import ctypes
import site

# nvidia-npp-cu12 installs libnppicc.so.12 inside site-packages/nvidia/npp/lib/,
# which is not on LD_LIBRARY_PATH. Load it globally before torchcodec is imported
# so the dynamic linker can resolve it when torchcodec dlopen's its shared libs.
def _preload_npp():
    for _sp in site.getsitepackages():
        _p = os.path.join(_sp, "nvidia", "npp", "lib", "libnppicc.so.12")
        if os.path.exists(_p):
            ctypes.CDLL(_p, mode=ctypes.RTLD_GLOBAL)
            return

_preload_npp()

import spaces  # MUST come before torch / any CUDA-touching import
import torch
import gradio as gr
from transformers import AutoModelForCausalLM, AutoProcessor

MODEL_ID = "OpenMOSS-Team/MOSS-VL-Realtime"

print("Loading processor...")
processor = AutoProcessor.from_pretrained(
    MODEL_ID, trust_remote_code=True, frame_extract_num_threads=1
)

print("Loading model...")
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    trust_remote_code=True,
    torch_dtype=torch.bfloat16,
    attn_implementation="sdpa",
).to("cuda")
model.eval()
print("Model ready.")

# Control tokens the realtime loop emits alongside real text; strip them from the
# user-facing answer but surface silence as a status.
_CONTROL_TOKENS = ("<|round_start|>", "<|round_end|>", "<|silence|>")


def _extract_frames(video_path, video_fps, max_frames):
    """Decode a video into a list of (PIL.Image, timestamp_seconds), sampled at video_fps."""
    from torchcodec.decoders import VideoDecoder
    from torchvision.transforms.functional import to_pil_image

    decoder = VideoDecoder(video_path)
    duration = float(decoder.metadata.duration_seconds or 0.0)
    if duration <= 0:
        # Fall back to a single frame if duration is unknown.
        frame = decoder[0]
        return [(to_pil_image(frame), 0.0)]

    step = 1.0 / float(video_fps) if float(video_fps) > 0 else 1.0
    timestamps = []
    t = 0.0
    # keep a small epsilon away from the very end (no frame plays exactly at duration)
    end = max(duration - 1e-3, 0.0)
    while t <= end and len(timestamps) < int(max_frames):
        timestamps.append(round(t, 3))
        t += step
    if not timestamps:
        timestamps = [0.0]

    batch = decoder.get_frames_played_at(seconds=timestamps)
    frames = []
    for i in range(batch.data.shape[0]):
        img = to_pil_image(batch.data[i])
        ts = float(batch.pts_seconds[i])
        frames.append((img, ts))
    return frames


# --- Inference ---

@spaces.GPU(duration=180)
def analyze_video(
    video=None,
    prompt="",
    image=None,
    max_new_tokens=512,
    temperature=0.0,
    top_p=1.0,
    repetition_penalty=1.0,
    video_fps=1.0,
    max_frames=64,
):
    """Analyze a video (or optional image) with a text prompt using MOSS-VL-Realtime.

    Streams partial results frame-by-frame to reflect the model's realtime
    perception: the video is fed in as a sequence of timestamped frames and the
    answer is progressively updated as more of the stream is observed.

    Args:
        video: An uploaded video to analyze (primary input).
        prompt: The question or instruction about the media.
        image: An optional uploaded image to analyze instead of a video.
        max_new_tokens: Maximum number of tokens to generate.
        temperature: Sampling temperature (0 = greedy).
        top_p: Nucleus sampling threshold.
        repetition_penalty: Penalty for repeated tokens.
        video_fps: Frames per second to sample from video.
        max_frames: Maximum number of frames to extract from video.
    """
    if not prompt or not prompt.strip():
        yield "", {"error": "Please enter a prompt."}
        return
    if video is None and image is None:
        yield "", {"error": "Please upload a video or an image."}
        return

    do_sample = float(temperature) > 0.0

    # Image path: single offline call (not a streaming source).
    if video is None and image is not None:
        result = model.offline_image_generate(
            processor,
            prompt=prompt,
            image=image,
            max_new_tokens=int(max_new_tokens),
            temperature=float(temperature),
            top_p=float(top_p),
            repetition_penalty=float(repetition_penalty),
            do_sample=do_sample,
            vision_chunked_length=64,
        )
        yield result, {"prompt": prompt, "status": "done", "response": result}
        return

    # Video path: stream frame-by-frame through the realtime session.
    try:
        frames = _extract_frames(video, video_fps, max_frames)
    except Exception as exc:  # decoding failed -> fall back to offline below
        frames = None
        decode_error = str(exc)
    else:
        decode_error = None

    if frames:
        try:
            import time

            total = len(frames)
            # Wall-clock budget for the streaming pass so we always finish well
            # within the @spaces.GPU duration (the realtime loop does not stop on
            # its own — it idles on <|silence|> waiting for more input).
            deadline = time.monotonic() + 60.0
            session = model.create_realtime_session(
                processor,
                initial_prompt="",
                max_new_tokens=int(max_new_tokens),
                temperature=float(temperature),
                top_p=float(top_p),
                repetition_penalty=float(repetition_penalty),
                do_sample=do_sample,
            )
            session.start()
            session.push_prompt(prompt)

            answer = ""
            try:
                for idx, (img, ts) in enumerate(frames):
                    session.push_frame(img, timestamp=ts)
                    # Drain whatever the model has emitted so far without blocking.
                    while True:
                        chunk = session.poll_output(timeout=0.0)
                        if chunk is None:
                            break
                        if chunk in _CONTROL_TOKENS:
                            continue
                        answer += chunk
                    processed = idx + 1
                    response_text = (
                        answer.strip()
                        if answer
                        else "…(observing, no response yet)"
                    )
                    yield response_text, {
                        "prompt": prompt,
                        "status": "observing" if not answer else "responding",
                        "frames_processed": processed,
                        "frames_total": total,
                        "timestamp_seconds": round(ts, 3),
                        "response": response_text,
                    }
                    if time.monotonic() > deadline:
                        break

                # All frames pushed; drain remaining output with a bounded grace
                # period. Stop once the model has been idle (silent) for a short
                # while, or once the wall-clock deadline is hit.
                idle_deadline = time.monotonic() + 8.0
                while time.monotonic() < deadline and time.monotonic() < idle_deadline:
                    chunk = session.poll_output(timeout=0.25)
                    if chunk is None:
                        continue
                    if chunk in _CONTROL_TOKENS:
                        continue
                    answer += chunk
                    idle_deadline = time.monotonic() + 8.0  # got text -> extend
                    yield answer.strip(), {
                        "prompt": prompt,
                        "status": "responding",
                        "frames_processed": total,
                        "frames_total": total,
                        "response": answer.strip(),
                    }
            finally:
                session.close()

            answer = answer.strip()
            if not answer:
                # Model stayed silent the whole stream -> deterministic offline pass.
                answer = model.offline_video_generate(
                    processor,
                    prompt=prompt,
                    video=video,
                    max_new_tokens=int(max_new_tokens),
                    temperature=float(temperature),
                    top_p=float(top_p),
                    repetition_penalty=float(repetition_penalty),
                    do_sample=do_sample,
                    vision_chunked_length=64,
                    video_fps=float(video_fps),
                    max_frames=int(max_frames),
                )
            yield answer, {
                "prompt": prompt,
                "status": "done",
                "frames_processed": total,
                "frames_total": total,
                "response": answer,
            }
            return
        except Exception as exc:
            decode_error = f"realtime streaming failed: {exc}"

    # Fallback: single offline video pass (also covers decode/stream failures).
    result = model.offline_video_generate(
        processor,
        prompt=prompt,
        video=video,
        max_new_tokens=int(max_new_tokens),
        temperature=float(temperature),
        top_p=float(top_p),
        repetition_penalty=float(repetition_penalty),
        do_sample=do_sample,
        vision_chunked_length=64,
        video_fps=float(video_fps),
        max_frames=int(max_frames),
    )
    out = {"prompt": prompt, "status": "done", "response": result}
    if decode_error:
        out["note"] = decode_error
    yield result, out


# --- UI ---

CSS = """
#col-container { max-width: 1100px; margin: 0 auto; }
.dark .gradio-container { color: var(--body-text-color); }
"""

with gr.Blocks(
    css=CSS,
    title="MOSS-VL-Realtime Demo",
) as demo:
    gr.Markdown(
        """
        # MOSS-VL-Realtime

        Multimodal vision-language model for realtime streaming video understanding.
        Upload a video (or an image) and ask any question — the model perceives the
        video frame-by-frame and streams its answer as the stream is observed.

        [Model Card](https://huggingface.co/OpenMOSS-Team/MOSS-VL-Realtime) |
        [GitHub](https://github.com/OpenMOSS/MOSS-VL)
        """
    )

    with gr.Column(elem_id="col-container"):
        with gr.Row():
            with gr.Column(scale=1):
                video_input = gr.Video(
                    label="Video (primary input)",
                )
                image_input = gr.Image(
                    label="Image (optional, secondary)",
                    type="filepath",
                )
            with gr.Column(scale=1):
                prompt_input = gr.Textbox(
                    label="Prompt",
                    placeholder="Ask a question about the video or image...",
                    lines=4,
                )
                run_btn = gr.Button("Analyze", variant="primary")

                response_text_output = gr.Textbox(
                    label="Response (text, streamed)",
                    lines=6,
                )
                output = gr.JSON(
                    label="Response (streamed)",
                )

        with gr.Accordion("Advanced Settings", open=False):
            with gr.Row():
                max_new_tokens = gr.Slider(
                    64, 4096, value=512, step=64, label="Max New Tokens"
                )
                temperature = gr.Slider(
                    0.0, 1.5, value=0.0, step=0.05, label="Temperature"
                )
            with gr.Row():
                top_p = gr.Slider(
                    0.1, 1.0, value=1.0, step=0.05, label="Top-p"
                )
                repetition_penalty = gr.Slider(
                    1.0, 2.0, value=1.0, step=0.05, label="Repetition Penalty"
                )
            with gr.Accordion("Video Sampling", open=False):
                with gr.Row():
                    video_fps = gr.Slider(
                        0.1, 4.0, value=1.0, step=0.1, label="Video FPS"
                    )
                    max_frames = gr.Slider(
                        8, 256, value=64, step=8, label="Max Frames"
                    )

    gr.Examples(
        examples=[
            ["luoge.mp4", "根据柜员的说法，柜台上三个杯子分别对应什么大小的？"],
            ["luoge.mp4", "Describe what is happening in this video."],
        ],
        inputs=[video_input, prompt_input],
        outputs=[response_text_output, output],
        fn=analyze_video,
        cache_examples=True,
        cache_mode="lazy",
    )

    run_btn.click(
        fn=analyze_video,
        inputs=[
            video_input, prompt_input, image_input,
            max_new_tokens, temperature, top_p, repetition_penalty,
            video_fps, max_frames,
        ],
        outputs=[response_text_output, output],
        api_name="analyze",
    )

    prompt_input.submit(
        fn=analyze_video,
        inputs=[
            video_input, prompt_input, image_input,
            max_new_tokens, temperature, top_p, repetition_penalty,
            video_fps, max_frames,
        ],
        outputs=[response_text_output, output],
        api_name="analyze_submit",
    )


if __name__ == "__main__":
    demo.launch(mcp_server=True, theme=gr.themes.Citrus())
