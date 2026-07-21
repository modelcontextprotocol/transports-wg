#!/usr/bin/env python3
"""Capture Gemma's raw Gradio SSE text stream and final result."""

import json
import os
import re
import time
from pathlib import Path

import requests

SPACE = "huggingface-projects/gemma-4-12b-it"
BASE = "https://huggingface-projects-gemma-4-12b-it.hf.space"
OUT = Path(__file__).parent
PAYLOAD = {
    "text": (
        "Write exactly five short sentences describing an astronaut "
        "discovering a library on the moon. Answer directly."
    ),
    "files": None,
    "history": None,
    "thinking": False,
    "max_new_tokens": 160,
    "image_token_budget": 280,
    "system_prompt": "Return only the five-sentence answer. Do not explain your work.",
    "temperature": 0.2,
    "top_p": 0.9,
    "top_k": 40,
    "repetition_penalty": 1.0,
}
REQUEST = {
    "space": SPACE,
    "endpoint": "/chat",
    "transport": {
        "submit": "POST /gradio_api/call/v2/chat",
        "stream": "GET /gradio_api/call/chat/{event_id}",
        "media_type": "text/event-stream",
    },
    "payload": PAYLOAD,
}


def derive_delta(previous, current):
    if current.startswith(previous):
        return current[len(previous):], True
    return current, False


def main():
    token = os.environ.get("HF_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    (OUT / "request.json").write_text(json.dumps(REQUEST, indent=2) + "\n")
    start = time.monotonic()
    submit = requests.post(
        f"{BASE}/gradio_api/call/v2/chat",
        json=PAYLOAD,
        headers=headers,
        timeout=30,
    )
    submit.raise_for_status()
    event_id = submit.json()["event_id"]

    raw_sequence = 0
    current_event = None
    previous = {"content": "", "reasoning": ""}
    terminal_event = None
    content_update_times = []
    reasoning_update_count = 0

    with (
        requests.get(
            f"{BASE}/gradio_api/call/chat/{event_id}",
            headers={**headers, "Accept": "text/event-stream"},
            stream=True,
            timeout=(30, 300),
        ) as response,
        (OUT / "raw" / "events.jsonl").open("w") as raw_file,
    ):
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            elapsed = round(time.monotonic() - start, 6)
            raw = {
                "sequence": raw_sequence,
                "elapsed_seconds": elapsed,
                "line": line,
            }
            raw_file.write(json.dumps(raw) + "\n")
            raw_file.flush()
            raw_sequence += 1

            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
                terminal_event = current_event if current_event in {"complete", "error"} else terminal_event
                continue
            if not line.startswith("data:"):
                continue

            raw_data = line.split(":", 1)[1].strip()
            try:
                decoded = json.loads(raw_data)
            except json.JSONDecodeError:
                decoded = raw_data

            if current_event == "generating" and isinstance(decoded, list) and decoded:
                update = decoded[0]
                for channel in ("reasoning", "content"):
                    snapshot = update.get(channel, "")
                    if snapshot == previous[channel]:
                        continue
                    delta, append_only = derive_delta(previous[channel], snapshot)
                    if channel == "content":
                        content_update_times.append(elapsed)
                    else:
                        reasoning_update_count += 1
                    previous[channel] = snapshot
                    print(json.dumps({
                        "elapsed_seconds": elapsed,
                        "channel": channel,
                        "delta": delta,
                        "append_only": append_only,
                        "characters": len(snapshot),
                    }), flush=True)
        elapsed_total = round(time.monotonic() - start, 6)

    final_content = previous["content"]
    sentence_count = len(re.findall(r"[.!?](?:\s|$)", final_content))
    (OUT / "artifacts" / "final.txt").write_text(final_content + "\n")
    result = {
        "event_id": event_id,
        "terminal_event": terminal_event or "stream_closed",
        "elapsed_seconds": elapsed_total,
        "time_to_first_content_seconds": (
            content_update_times[0] if content_update_times else None
        ),
        "content_update_count": len(content_update_times),
        "reasoning_update_count": reasoning_update_count,
        "final_content": final_content,
        "final_content_characters": len(final_content),
        "final_content_sentences": sentence_count,
        "final_artifact": "artifacts/final.txt",
    }
    (OUT / "response.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)
    if (
        terminal_event != "complete"
        or not final_content
        or not content_update_times
        or sentence_count != 5
    ):
        raise SystemExit("capture did not produce a complete ordinary content stream")


if __name__ == "__main__":
    main()
