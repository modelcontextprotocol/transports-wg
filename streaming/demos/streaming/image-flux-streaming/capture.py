import json
import shutil
import time
from pathlib import Path
from gradio_client import Client

SPACE = "evalstate/flux-streaming-denoising"
OUT = Path(__file__).parent
REQUEST = {
    "space": SPACE,
    "api_name": "/infer_streaming",
    "prompt": "a tiny astronaut hatching from a translucent blue egg on the moon, cinematic lighting",
    "seed": 12345,
    "randomize_seed": False,
    "width": 768,
    "height": 768,
    "num_inference_steps": 4,
}
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "artifacts" / "chunks").mkdir(exist_ok=True)
(OUT / "request.json").write_text(json.dumps(REQUEST, indent=2) + "\n")
client = Client(SPACE, verbose=False, download_files=str(OUT / "raw" / "downloads"))
job = client.submit(
    REQUEST["prompt"], REQUEST["seed"], REQUEST["randomize_seed"],
    REQUEST["width"], REQUEST["height"], REQUEST["num_inference_steps"],
    api_name=REQUEST["api_name"],
)
start = time.monotonic()
records = []
with (OUT / "raw" / "client_yields.jsonl").open("w") as log:
    for index, output in enumerate(job):
        elapsed = round(time.monotonic() - start, 3)
        image, used_seed, status = output
        source = None
        if isinstance(image, dict):
            source = image.get("path") or image.get("url")
        elif image:
            source = str(image)
        saved = None
        if source and Path(source).exists():
            suffix = Path(source).suffix or ".webp"
            target = OUT / "artifacts" / "chunks" / f"chunk_{index:02d}{suffix}"
            shutil.copy2(source, target)
            saved = str(target.relative_to(OUT))
        rec = {
            "index": index,
            "elapsed_seconds": elapsed,
            "used_seed": used_seed,
            "status": status,
            "image": saved,
            "source": source,
        }
        records.append(rec)
        log.write(json.dumps(rec) + "\n")
        log.flush()
        print(json.dumps(rec), flush=True)
elapsed = round(time.monotonic() - start, 3)
result = job.result()
response = {
    "elapsed_seconds": elapsed,
    "chunk_count": len(records),
    "final_status": records[-1]["status"] if records else None,
    "final_image": records[-1]["image"] if records else None,
    "result_repr": repr(result),
}
(OUT / "response.json").write_text(json.dumps(response, indent=2) + "\n")
if records and records[-1]["image"]:
    shutil.copy2(OUT / records[-1]["image"], OUT / "artifacts" / "final_image.webp")
print(json.dumps(response), flush=True)
