#!/usr/bin/env python3
"""Capture MOSS-VL-Realtime's raw Gradio SSE video-analysis stream."""

import hashlib
import json
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
BASE = "https://evalstate-moss-vl-realtime-evidence.hf.space"
INPUT = HERE / "artifacts/input/51397874-651f-4c75-aa5c-5c61dceb1e3e.mp4"
RAW = HERE / "raw"
PROMPT = (
    "Describe what becomes visible and what moves as this short video progresses. "
    "Answer in one concise sentence."
)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    request_record = {
        "producer": "OpenMOSS-Team/openmoss-team-moss-vl-realtime",
        "capture_space": "evalstate/moss-vl-realtime-evidence",
        "capture_space_change": (
            "Only @spaces.GPU(duration=180) was changed to duration=80 because "
            "the original deployment rejected its effective 270-second request."
        ),
        "endpoint": "/analyze",
        "input": {
            "path": f"artifacts/input/{INPUT.name}",
            "sha256": hashlib.sha256(INPUT.read_bytes()).hexdigest(),
            "source_dataset": "zirui3/tiny-video-samples",
            "dataset_license": "MIT",
            "clip_duration_seconds": 5.088416667,
        },
        "prompt": PROMPT,
        "max_new_tokens": 128,
        "temperature": 0.0,
        "top_p": 1.0,
        "repetition_penalty": 1.0,
        "video_fps": 2.0,
        "max_frames": 16,
    }
    write_json(HERE / "request.json", request_record)

    started = time.monotonic()
    with INPUT.open("rb") as handle:
        upload = session.post(
            f"{BASE}/gradio_api/upload",
            files={"files": (INPUT.name, handle, "video/mp4")},
            timeout=120,
        )
    upload.raise_for_status()
    uploaded_path = upload.json()[0]
    (RAW / "upload_response.json").write_text(upload.text + "\n")
    payload = {
        "video": {"path": uploaded_path, "meta": {"_type": "gradio.FileData"}},
        "prompt": PROMPT,
        "image": None,
        "max_new_tokens": 128,
        "temperature": 0.0,
        "top_p": 1.0,
        "repetition_penalty": 1.0,
        "video_fps": 2.0,
        "max_frames": 16,
    }
    submit = session.post(
        f"{BASE}/gradio_api/call/v2/analyze", json=payload, timeout=120
    )
    submit.raise_for_status()
    (RAW / "submit_response.json").write_text(submit.text + "\n")
    event_id = submit.json()["event_id"]

    observations = []
    current_event = None
    with session.get(
        f"{BASE}/gradio_api/call/analyze/{event_id}",
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
                    observations.append(
                        {
                            "elapsed_seconds": round(elapsed, 6),
                            "transport_event": current_event,
                            "data": json.loads(line[5:].strip()),
                        }
                    )

    write_json(RAW / "observations.json", observations)
    updates = [
        observation
        for observation in observations
        if isinstance(observation["data"], list)
        and len(observation["data"]) == 2
        and isinstance(observation["data"][0], str)
        and isinstance(observation["data"][1], dict)
    ]
    final = updates[-1]["data"] if updates else None
    response_record = {
        "event_id": event_id,
        "terminal_seconds": round(time.monotonic() - started, 6),
        "content_updates": len(updates),
        "first_non_placeholder_seconds": next(
            (
                update["elapsed_seconds"]
                for update in updates
                if update["data"][0]
                and not update["data"][0].startswith("…")
            ),
            None,
        ),
        "statuses": [update["data"][1].get("status") for update in updates],
        "frames_processed": [
            update["data"][1].get("frames_processed") for update in updates
        ],
        "changing_answers": sum(
            updates[index]["data"][0] != updates[index - 1]["data"][0]
            for index in range(1, len(updates))
        ),
        "final": final,
    }
    write_json(HERE / "response.json", response_record)
    if final:
        (HERE / "artifacts/final_answer.txt").write_text(final[0] + "\n")


if __name__ == "__main__":
    main()
