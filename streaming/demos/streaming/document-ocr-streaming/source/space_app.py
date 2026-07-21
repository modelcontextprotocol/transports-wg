from __future__ import annotations

import base64
import html
import io
import mimetypes
import os
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

try:
    import spaces  # Must be imported before torch on Hugging Face ZeroGPU.
except ImportError:  # Local development uses a no-op decorator.
    class _LocalSpaces:
        @staticmethod
        def GPU(*decorator_args: Any, **decorator_kwargs: Any) -> Callable:
            def decorate(function: Callable) -> Callable:
                return function

            if decorator_args and callable(decorator_args[0]) and len(decorator_args) == 1:
                return decorator_args[0]
            return decorate

    spaces = _LocalSpaces()

import gradio as gr
import fitz
import torch
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from gradio.data_classes import FileData
from PIL import Image, ImageOps
from starlette.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"
MODEL_ID = "ATH-MaaS/OvisOCR2"
LOCAL_MODEL_DEFAULT = Path("/root/models/ATH-MaaS/OvisOCR2")
TEST_MODE = os.getenv("OVISOCR_TEST_MODE", "0").lower() in {"1", "true", "yes"}
MODEL_SOURCE = os.getenv(
    "OVISOCR_MODEL_PATH",
    str(LOCAL_MODEL_DEFAULT if LOCAL_MODEL_DEFAULT.is_dir() else MODEL_ID),
)
MAX_NEW_TOKENS = int(os.getenv("OVISOCR_MAX_NEW_TOKENS", "16384"))
MAX_PDF_PAGES = int(os.getenv("OVISOCR_MAX_PDF_PAGES", "50"))
PAGES_PER_GPU_REQUEST = max(
    1, min(5, int(os.getenv("OVISOCR_PAGES_PER_GPU_REQUEST", "4")))
)
GPU_SECONDS_PER_PAGE = max(15, int(os.getenv("OVISOCR_GPU_SECONDS_PER_PAGE", "30")))
GPU_DURATION_FLOOR = max(15, int(os.getenv("OVISOCR_GPU_DURATION_FLOOR", "45")))
GPU_DURATION_CEILING = max(
    GPU_DURATION_FLOOR,
    int(os.getenv("OVISOCR_GPU_DURATION_CEILING", "120")),
)
PDF_RENDER_SCALE = float(os.getenv("OVISOCR_PDF_RENDER_SCALE", "2.0"))
STREAM_MIN_CHARS = int(os.getenv("OVISOCR_STREAM_MIN_CHARS", "64"))
STREAM_MAX_INTERVAL = float(os.getenv("OVISOCR_STREAM_MAX_INTERVAL", "0.25"))
MIN_PIXELS = 448 * 448
MAX_PIXELS = 2880 * 2880


def server_config() -> tuple[int, str | None, str | None]:
    """Resolve the port, ASGI path prefix, and optional public proxy URL."""
    port = int(os.getenv("PORT", os.getenv("GRADIO_SERVER_PORT", "7860")))
    configured_root = (
        os.getenv("OVISOCR_ROOT_PATH", "").strip()
        or os.getenv("GRADIO_ROOT_PATH", "").strip()
    )
    dsw_id = os.getenv("OVISOCR_DSW_ID", "").strip()
    public_url = None
    root_path = None
    if configured_root.startswith(("http://", "https://")):
        public_url = configured_root
        path = urlsplit(configured_root).path.rstrip("/")
        root_path = path or None
    elif configured_root:
        root_path = configured_root.rstrip("/") or None
    elif dsw_id:
        public_url = (
            f"https://{dsw_id}-proxy-{port}."
            "dsw-gateway-cn-hangzhou.data.aliyun.com/"
        )
    return port, root_path, public_url


SERVER_PORT, ROOT_PATH, PUBLIC_URL = server_config()

OCR_PROMPT = (
    "\nExtract all readable content from the image in natural human reading order "
    "and output the result as a single Markdown document. For charts or images, "
    'represent them using an HTML image tag: <img src="images/bbox_{left}_{top}_{right}_{bottom}.jpg" />, '
    "where left, top, right, bottom are bounding box coordinates scaled to [0, 1000). "
    "Format formulas as LaTeX. Format tables as HTML: <table>...</table>. "
    "Transcribe all other text as standard Markdown. Preserve the original text "
    "without translation or paraphrasing."
)

BBOX_IMAGE_PATTERN = re.compile(
    r'<img\s+src=["\']images/bbox_(\d+)_(\d+)_(\d+)_(\d+)\.jpg["\']\s*/?>',
    flags=re.IGNORECASE,
)


class CachedStaticFiles(StaticFiles):
    """Serve immutable production assets from the browser cache after first load."""

    async def get_response(self, path: str, scope: dict[str, Any]) -> Any:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


UNMATERIALIZED_BBOX_IMAGE_PATTERN = re.compile(
    r'<img\b[^>]*\bsrc=["\']images/bbox_[^"\']+["\'][^>]*>',
    flags=re.IGNORECASE,
)

EXAMPLE_ASSETS = {
    path.name: (path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    for path in (DIST_DIR / "examples").iterdir()
    if path.is_file()
} if (DIST_DIR / "examples").is_dir() else {}

MOCK_MARKDOWN = r"""# 盈利预测、估值与评级

我们预测公司 2024—2026 年营业收入与归母净利润将保持稳健增长，当前股价对应估值如下。

<table>
  <thead><tr><th>项目</th><th>2023A</th><th>2024E</th><th>2025E</th><th>2026E</th></tr></thead>
  <tbody>
    <tr><td>营业收入（百万元）</td><td>9,423</td><td>10,516</td><td>11,873</td><td>13,441</td></tr>
    <tr><td>归母净利润（百万元）</td><td>1,267</td><td>1,452</td><td>1,681</td><td>1,946</td></tr>
    <tr><td>每股收益（元）</td><td>1.02</td><td>1.17</td><td>1.36</td><td>1.57</td></tr>
    <tr><td>市盈率</td><td>18.4</td><td>16.1</td><td>13.8</td><td>12.0</td></tr>
  </tbody>
</table>

## 财务摘要

净资产收益率采用 $ROE = \frac{NP}{E}$ 计算；预计 2025 年利润同比增速为：

\[
g = \frac{1{,}681 - 1{,}452}{1{,}452} \times 100\% = 15.8\%.
\]

<img src="images/bbox_120_130_880_420.jpg" />

资料来源：公司公告，研究团队整理。"""


processor = None
model = None


def _load_model() -> None:
    global processor, model
    if TEST_MODE:
        return

    from transformers import AutoProcessor, Qwen3_5ForConditionalGeneration

    local_only = Path(MODEL_SOURCE).is_dir()
    processor = AutoProcessor.from_pretrained(
        MODEL_SOURCE,
        min_pixels=MIN_PIXELS,
        max_pixels=MAX_PIXELS,
        local_files_only=local_only,
    )
    model = Qwen3_5ForConditionalGeneration.from_pretrained(
        MODEL_SOURCE,
        dtype=torch.bfloat16,
        attn_implementation=os.getenv("OVISOCR_ATTN_IMPLEMENTATION", "sdpa"),
        local_files_only=local_only,
    ).to("cuda")
    model.eval()


def clean_truncated_repeats(
    text: str,
    min_text_len: int = 8000,
    max_period: int = 200,
    min_period: int = 1,
    min_repeat_chars: int = 100,
    min_repeat_times: int = 5,
) -> str:
    """Remove a repeated suffix created when generation reaches its token ceiling."""
    n = len(text)
    if n < min_text_len:
        return text

    max_period = min(max_period, n - 1)
    for unit_len in range(min_period, max_period + 1):
        if text[n - 1] != text[n - 1 - unit_len]:
            continue
        match_len = 1
        idx = n - 2
        while idx >= unit_len and text[idx] == text[idx - unit_len]:
            match_len += 1
            idx -= 1
        total_len = match_len + unit_len
        repeat_times = total_len // unit_len
        tail_len = total_len % unit_len
        if repeat_times >= min_repeat_times and total_len >= min_repeat_chars:
            return text[: n - total_len + unit_len] + text[n - tail_len :]
    return text


def materialize_bbox_images(markdown: str, page_image: Image.Image) -> str:
    """Replace bbox image placeholders in rendered output with safe data-URI crops.

    Raw model Markdown is returned separately and remains unchanged.
    """
    width, height = page_image.size

    def replace(match: re.Match[str]) -> str:
        left, top, right, bottom = (int(value) for value in match.groups())
        x1 = max(0, min(width, round(left * width / 1000)))
        y1 = max(0, min(height, round(top * height / 1000)))
        x2 = max(0, min(width, round(right * width / 1000)))
        y2 = max(0, min(height, round(bottom * height / 1000)))
        if x2 <= x1 or y2 <= y1:
            return match.group(0)

        crop = page_image.crop((x1, y1, x2, y2)).convert("RGB")
        crop.thumbnail((1200, 1200), Image.Resampling.BILINEAR)
        buffer = io.BytesIO()
        # JPEG optimize performs an expensive extra pass and brings little value
        # for an in-browser visual-region preview. Browser-side lazy decoding also
        # keeps multi-page results responsive when several clips arrive together.
        crop.save(buffer, format="JPEG", quality=85, optimize=False)
        payload = base64.b64encode(buffer.getvalue()).decode("ascii")
        return (
            f'<img src="data:image/jpeg;base64,{payload}" alt="Visual region" '
            'loading="lazy" decoding="async" />'
        )

    return neutralize_unmaterialized_bbox_images(BBOX_IMAGE_PATTERN.sub(replace, markdown))


def neutralize_unmaterialized_bbox_images(markdown: str) -> str:
    """Render placeholder examples as code instead of issuing broken requests."""

    def replace(match: re.Match[str]) -> str:
        escaped = html.escape(match.group(0), quote=False)
        return f'<code class="unresolved-image-reference">{escaped}</code>'

    return UNMATERIALIZED_BBOX_IMAGE_PATTERN.sub(replace, markdown)


def stream_safe_markdown(markdown: str) -> str:
    """Avoid broken image requests until a page's bbox crops are materialized."""
    return neutralize_unmaterialized_bbox_images(
        BBOX_IMAGE_PATTERN.sub(
            '<div class="visual-placeholder">Preparing visual region…</div>',
            markdown,
        )
    )


def _file_path(file_data: FileData | dict[str, Any]) -> str:
    if isinstance(file_data, dict):
        path = file_data.get("path")
    else:
        path = getattr(file_data, "path", None)
    if not path:
        raise ValueError("No uploaded document was provided.")
    return str(path)


def generation_token_ids(active_processor: Any) -> dict[str, int]:
    """Use tokenizer stop IDs; this checkpoint's config and tokenizer differ."""
    tokenizer = active_processor.tokenizer
    return {
        "eos_token_id": int(tokenizer.eos_token_id),
        "pad_token_id": int(tokenizer.pad_token_id),
    }


def document_info(path: str) -> tuple[str, int]:
    suffix = Path(path).suffix.lower()
    try:
        with Path(path).open("rb") as file:
            header = file.read(5)
    except OSError as error:
        raise ValueError("The uploaded document could not be read.") from error

    # Browser uploads can arrive at Gradio as an extensionless temporary `blob`.
    if suffix == ".pdf" or header == b"%PDF-":
        with fitz.open(path) as document:
            total_pages = document.page_count
        if total_pages < 1:
            raise ValueError("The uploaded PDF has no pages.")
        if total_pages > MAX_PDF_PAGES:
            raise ValueError(
                f"This demo accepts up to {MAX_PDF_PAGES} PDF pages; received {total_pages}."
            )
        return "pdf", total_pages

    try:
        with Image.open(path) as source:
            source.verify()
    except Exception as error:
        raise ValueError("Please upload a valid PNG, JPEG, WebP, or PDF file.") from error
    return "image", 1


def load_document_page(path: str, document_type: str, page_index: int) -> Image.Image:
    if document_type == "pdf":
        with fitz.open(path) as document:
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(PDF_RENDER_SCALE, PDF_RENDER_SCALE),
                colorspace=fitz.csRGB,
                alpha=False,
            )
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)

    with Image.open(path) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


def page_preview_data_uri(page_image: Image.Image) -> str:
    preview = page_image.copy().convert("RGB")
    preview.thumbnail((1400, 1800), Image.Resampling.BILINEAR)
    buffer = io.BytesIO()
    preview.save(buffer, format="JPEG", quality=82, optimize=False)
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{payload}"


def _model_inputs(page_image: Image.Image) -> Any:
    if processor is None or model is None:
        raise RuntimeError("OvisOCR2 is not loaded.")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": page_image},
                {"type": "text", "text": OCR_PROMPT},
            ],
        }
    ]
    return processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
        enable_thinking=False,
    ).to(model.device)


def infer_stream(page_image: Image.Image) -> Iterator[str]:
    if TEST_MODE:
        for end in range(64, len(MOCK_MARKDOWN) + 64, 64):
            yield MOCK_MARKDOWN[:end]
        return
    if processor is None or model is None:
        raise RuntimeError("OvisOCR2 is not loaded.")

    from transformers import TextIteratorStreamer

    inputs = _model_inputs(page_image)
    streamer = TextIteratorStreamer(
        processor.tokenizer,
        skip_prompt=True,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )
    errors: list[BaseException] = []

    def generate() -> None:
        try:
            with torch.inference_mode():
                model.generate(
                    **inputs,
                    streamer=streamer,
                    max_new_tokens=MAX_NEW_TOKENS,
                    do_sample=False,
                    temperature=None,
                    top_p=None,
                    top_k=None,
                    **generation_token_ids(processor),
                )
        except BaseException as error:
            errors.append(error)
            streamer.on_finalized_text("", stream_end=True)

    worker = threading.Thread(target=generate, name="ovisocr2-generate", daemon=True)
    worker.start()
    text = ""
    last_yielded = ""
    last_yield_time = time.monotonic()
    for fragment in streamer:
        text += fragment
        now = time.monotonic()
        if (
            len(text) - len(last_yielded) >= STREAM_MIN_CHARS
            or now - last_yield_time >= STREAM_MAX_INTERVAL
        ):
            yield text
            last_yielded = text
            last_yield_time = now

    worker.join()
    if errors:
        raise RuntimeError("Model generation failed.") from errors[0]
    final_text = clean_truncated_repeats(text.strip())
    if final_text and final_text != last_yielded:
        yield final_text


def combine_pages(pages: list[dict[str, Any]], field: str) -> str:
    if len(pages) <= 1:
        return pages[0].get(field, "") if pages else ""
    return "\n\n---\n\n".join(
        f"<!-- Page {page['page_number']} -->\n\n{page.get(field, '')}" for page in pages
    )


def stream_payload(
    *,
    event: str,
    pages: list[dict[str, Any]],
    current_page: int,
    total_pages: int,
    document_type: str,
    started: float,
    page_preview: str | None = None,
    batch_complete: bool = False,
    batch_start_page: int | None = None,
    batch_end_page: int | None = None,
) -> dict[str, Any]:
    return {
        "event": event,
        "markdown": combine_pages(pages, "markdown"),
        "render_markdown": combine_pages(pages, "render_markdown"),
        "pages": pages,
        "current_page": current_page,
        "total_pages": total_pages,
        "document_type": document_type,
        "page_preview": page_preview,
        "batch_complete": batch_complete,
        "batch_start_page": batch_start_page,
        "batch_end_page": batch_end_page,
        "char_count": sum(len(page.get("markdown", "")) for page in pages),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "model": MODEL_ID,
        "backend": "mock" if TEST_MODE else "transformers",
        "mode": "base",
    }


def _gpu_duration(
    image_path: FileData | dict[str, Any], page_index: int = 0,
    page_count: int = PAGES_PER_GPU_REQUEST,
) -> int:
    configured_duration = os.getenv("OVISOCR_GPU_DURATION", "").strip()
    if configured_duration:
        return int(configured_duration)

    requested_count = max(1, min(PAGES_PER_GPU_REQUEST, int(page_count)))
    try:
        path = _file_path(image_path)
        _, total_pages = document_info(path)
        remaining_pages = max(1, total_pages - int(page_index))
        requested_count = min(requested_count, remaining_pages)
    except Exception:
        # Duration estimation must never prevent a request from reaching the
        # endpoint. The endpoint performs the authoritative file validation.
        pass

    return max(
        GPU_DURATION_FLOOR,
        min(GPU_DURATION_CEILING, requested_count * GPU_SECONDS_PER_PAGE),
    )


_load_model()
app = gr.Server()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:4173", "http://localhost:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.api(name="run_ocr", concurrency_limit=1, time_limit=300)
@spaces.GPU(duration=_gpu_duration)
def run_ocr(
    image_path: FileData,
    page_index: int = 0,
    page_count: int = PAGES_PER_GPU_REQUEST,
) -> Iterator[dict[str, Any]]:
    """Stream a bounded group of pages within one ZeroGPU reservation.

    Every page is rasterized and inferred independently and sequentially. The
    bounded group amortizes ZeroGPU scheduling while keeping long PDFs split
    across multiple leases.
    """
    started = time.perf_counter()
    path = _file_path(image_path)
    document_type, total_pages = document_info(path)
    page_index = int(page_index)
    if page_index < 0 or page_index >= total_pages:
        raise ValueError(
            f"Requested PDF page {page_index + 1}, but this document has {total_pages} pages."
        )

    requested_count = max(1, min(PAGES_PER_GPU_REQUEST, int(page_count)))
    batch_end_index = min(total_pages, page_index + requested_count)
    batch_start_page = page_index + 1
    batch_end_page = batch_end_index
    completed_pages: list[dict[str, Any]] = []
    print(
        f"[ocr] batch start pages {batch_start_page}-{batch_end_page}/{total_pages}",
        flush=True,
    )

    for current_index in range(page_index, batch_end_index):
        page_number = current_index + 1
        page_image = load_document_page(path, document_type, current_index)
        page_started = time.perf_counter()
        current = {
            "page_number": page_number,
            "markdown": "",
            "render_markdown": "",
            "status": "streaming",
            "elapsed_seconds": 0.0,
        }
        yield stream_payload(
            event="page_start",
            pages=[current],
            current_page=page_number,
            total_pages=total_pages,
            document_type=document_type,
            started=started,
            page_preview=page_preview_data_uri(page_image),
            batch_start_page=batch_start_page,
            batch_end_page=batch_end_page,
        )

        markdown = ""
        for partial in infer_stream(page_image):
            markdown = partial
            current = {
                "page_number": page_number,
                "markdown": markdown,
                "render_markdown": stream_safe_markdown(markdown),
                "status": "streaming",
                "elapsed_seconds": round(time.perf_counter() - page_started, 3),
            }
            yield stream_payload(
                event="stream",
                pages=[current],
                current_page=page_number,
                total_pages=total_pages,
                document_type=document_type,
                started=started,
                batch_start_page=batch_start_page,
                batch_end_page=batch_end_page,
            )

        markdown = markdown.strip()
        if not markdown:
            raise RuntimeError(f"The model returned an empty result for page {page_number}.")
        completed_page = {
            "page_number": page_number,
            "markdown": markdown,
            "render_markdown": materialize_bbox_images(markdown, page_image),
            "status": "complete",
            "elapsed_seconds": round(time.perf_counter() - page_started, 3),
        }
        completed_pages.append(completed_page)
        print(
            f"[ocr] page {page_number}/{total_pages} complete "
            f"({len(markdown)} chars, {completed_page['elapsed_seconds']}s)",
            flush=True,
        )
        yield stream_payload(
            event="page_complete",
            pages=[completed_page],
            current_page=page_number,
            total_pages=total_pages,
            document_type=document_type,
            started=started,
            batch_start_page=batch_start_page,
            batch_end_page=batch_end_page,
        )

    print(
        f"[ocr] batch complete pages {batch_start_page}-{batch_end_page}/{total_pages}",
        flush=True,
    )
    yield stream_payload(
        event="complete",
        pages=completed_pages,
        current_page=batch_end_page,
        total_pages=total_pages,
        document_type=document_type,
        started=started,
        batch_complete=True,
        batch_start_page=batch_start_page,
        batch_end_page=batch_end_page,
    )


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "model": MODEL_ID,
            "model_source": MODEL_SOURCE,
            "backend": "mock" if TEST_MODE else "transformers",
            "loaded": TEST_MODE or (processor is not None and model is not None),
            "max_pdf_pages": MAX_PDF_PAGES,
            "pages_per_gpu_request": PAGES_PER_GPU_REQUEST,
            "gpu_seconds_per_page": GPU_SECONDS_PER_PAGE,
            "gpu_duration_floor": GPU_DURATION_FLOOR,
            "gpu_duration_ceiling": GPU_DURATION_CEILING,
            "root_path": ROOT_PATH,
            "public_url": PUBLIC_URL,
        }
    )


@app.get("/examples/{filename}")
def example_asset(filename: str) -> Response:
    asset = EXAMPLE_ASSETS.get(filename)
    if asset is None:
        raise HTTPException(status_code=404, detail="Example not found")
    content, media_type = asset
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


if DIST_DIR.is_dir():
    for route, directory in (
        ("/assets", DIST_DIR / "assets"),
        ("/brand", DIST_DIR / "brand"),
        ("/vendor", DIST_DIR / "vendor"),
    ):
        if directory.is_dir():
            app.mount(route, CachedStaticFiles(directory=directory), name=route.strip("/").replace("/", "-"))


@app.get("/")
def homepage() -> FileResponse:
    index_path = DIST_DIR / "index.html"
    if not index_path.is_file():
        raise RuntimeError("Frontend build missing. Run `npm run build` before launching app.py.")
    return FileResponse(index_path, headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(
        DIST_DIR / "favicon.ico",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


if __name__ == "__main__":
    app.launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=SERVER_PORT,
        root_path=ROOT_PATH,
        show_error=True,
    )
