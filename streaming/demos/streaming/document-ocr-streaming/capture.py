#!/usr/bin/env python3
"""Capture OvisOCR2's raw Gradio SSE stream for one document image."""

import hashlib
import json
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
BASE = "https://ath-maas-ovisocr2.hf.space"
INPUT = HERE / "artifacts/input/invoice-test-2.jpg"
RAW = HERE / "raw"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    request_record = {
        "producer": "ATH-MaaS/OvisOCR2",
        "endpoint": "/run_ocr",
        "input": {
            "path": "artifacts/input/invoice-test-2.jpg",
            "sha256": hashlib.sha256(INPUT.read_bytes()).hexdigest(),
            "source_dataset": "katanaml-org/invoices-donut-data-v1",
            "config": "default",
            "split": "test",
            "row": 2,
        },
        "page_index": 0,
        "page_count": 1,
    }
    write_json(HERE / "request.json", request_record)

    started = time.monotonic()
    with INPUT.open("rb") as handle:
        upload = session.post(
            f"{BASE}/gradio_api/upload",
            files={"files": (INPUT.name, handle, "image/jpeg")},
            timeout=120,
        )
    upload.raise_for_status()
    uploaded_path = upload.json()[0]
    (RAW / "upload_response.json").write_text(upload.text + "\n")

    payload = {
        "image_path": {
            "path": uploaded_path,
            "meta": {"_type": "gradio.FileData"},
        },
        "page_index": 0,
        "page_count": 1,
    }
    submit = session.post(
        f"{BASE}/gradio_api/call/v2/run_ocr", json=payload, timeout=120
    )
    submit.raise_for_status()
    (RAW / "submit_response.json").write_text(submit.text + "\n")
    event_id = submit.json()["event_id"]

    observations = []
    current_event = None
    with session.get(
        f"{BASE}/gradio_api/call/run_ocr/{event_id}",
        stream=True,
        timeout=600,
    ) as response:
        response.raise_for_status()
        with (RAW / "sse.txt").open("w") as raw:
            for encoded in response.iter_lines():
                elapsed = time.monotonic() - started
                line = encoded.decode("utf-8")
                raw.write(f"{elapsed:.6f}\t{line}\n")
                raw.flush()
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    value = json.loads(line[5:].strip())
                    observations.append(
                        {
                            "elapsed_seconds": round(elapsed, 6),
                            "transport_event": current_event,
                            "data": value,
                        }
                    )

    write_json(RAW / "observations.json", observations)
    payloads = [
        observation["data"][0]
        for observation in observations
        if isinstance(observation["data"], list)
        and observation["data"]
        and isinstance(observation["data"][0], dict)
    ]
    stream_updates = [value for value in payloads if value.get("event") == "stream"]
    changing_stream_updates = []
    previous_markdown = None
    for value in stream_updates:
        markdown = value.get("markdown", "")
        if markdown != previous_markdown:
            changing_stream_updates.append(value)
            previous_markdown = markdown
    final = next(
        (value for value in reversed(payloads) if value.get("event") == "complete"),
        payloads[-1] if payloads else None,
    )
    if final:
        (HERE / "artifacts/output/final_payload.json").write_text(
            json.dumps(final, indent=2, ensure_ascii=False) + "\n"
        )
        pages = final.get("pages") or []
        if pages:
            (HERE / "artifacts/output/final_markdown.md").write_text(
                pages[0].get("markdown", "")
            )

    response_record = {
        "event_id": event_id,
        "terminal_seconds": round(time.monotonic() - started, 6),
        "transport_observations": len(observations),
        "application_events": [value.get("event") for value in payloads],
        "stream_updates": len(stream_updates),
        "changing_stream_updates": len(changing_stream_updates),
        "changing_nonempty_stream_updates": sum(
            bool(value.get("markdown")) for value in changing_stream_updates
        ),
        "first_stream_seconds": (
            next(
                observation["elapsed_seconds"]
                for observation in observations
                if isinstance(observation["data"], list)
                and observation["data"]
                and isinstance(observation["data"][0], dict)
                and observation["data"][0].get("event") == "stream"
            )
            if stream_updates
            else None
        ),
        "final": final,
    }
    write_json(HERE / "response.json", response_record)


if __name__ == "__main__":
    main()
