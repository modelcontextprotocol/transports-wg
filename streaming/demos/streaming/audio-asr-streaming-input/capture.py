#!/usr/bin/env python3
"""Drive gradio/stream_asr as one stateful Gradio queue/client session."""

import hashlib
import json
import time
from pathlib import Path

import gradio_client
from gradio_client import Client, handle_file
from gradio_client.utils import ServerMessage, Status

HERE = Path(__file__).parent
CHUNKS = [HERE / f"artifacts/input/chunk-{index}.wav" for index in range(1, 4)]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def patch_process_streaming_status() -> None:
    """Work around gradio_client 2.5.0 omitting one known enum from its map."""
    original = Status.msg_to_status

    def compatible(message: str) -> Status:
        if message == ServerMessage.process_streaming:
            return Status.ITERATING
        return original(message)

    Status.msg_to_status = staticmethod(compatible)


def common_prefix_length(left: str, right: str) -> int:
    length = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        length += 1
    return length


def main() -> None:
    patch_process_streaming_status()
    client = Client("gradio/stream_asr", verbose=False)
    started = time.monotonic()
    calls = []
    previous = ""

    for index, chunk in enumerate(CHUNKS, 1):
        call_started = time.monotonic()
        result = client.predict(
            new_chunk=handle_file(chunk),
            api_name="/predict",
        )
        call_completed = time.monotonic()
        elapsed = call_completed - started
        prefix_length = common_prefix_length(previous, result)
        suffix = result[len(previous) :] if result.startswith(previous) else None
        calls.append(
            {
                "chunk": index,
                "input_path": f"artifacts/input/{chunk.name}",
                "input_sha256": hashlib.sha256(chunk.read_bytes()).hexdigest(),
                "call_seconds": round(call_completed - call_started, 6),
                "elapsed_seconds": round(elapsed, 6),
                "transcript_snapshot": result,
                "extends_previous_snapshot": result.startswith(previous),
                "locally_derived_suffix": suffix,
                "common_prefix_characters": prefix_length,
                "replaced_previous_tail": previous[prefix_length:],
                "replacement_and_append": result[prefix_length:],
            }
        )
        previous = result

    request = {
        "producer": "gradio/stream_asr",
        "endpoint": "/predict",
        "interaction": "three sequential calls in one gradio_client queue session",
        "session_hash": client.session_hash,
        "input_source": {
            "dataset": "hf-internal-testing/librispeech_asr_demo",
            "config": "clean",
            "split": "validation",
            "row": 0,
            "original": "artifacts/input/1272-128104-0000.flac",
            "pcm_copy": "artifacts/input/1272-128104-0000.wav",
        },
        "chunks": [f"artifacts/input/{chunk.name}" for chunk in CHUNKS],
        "ground_truth": json.loads(
            (HERE / "artifacts/input/ground_truth.json").read_text()
        ),
        "client": {
            "gradio_client_version": gradio_client.__version__,
            "compatibility_patch": (
                "Map the already-defined process_streaming server message to "
                "Status.ITERATING; gradio_client 2.5.0 otherwise raises KeyError."
            ),
        },
    }
    write_json(HERE / "request.json", request)
    with (HERE / "raw/client_calls.jsonl").open("w") as handle:
        for call in calls:
            handle.write(json.dumps(call, ensure_ascii=False) + "\n")

    response = {
        "terminal_seconds": round(time.monotonic() - started, 6),
        "session_hash": client.session_hash,
        "content_updates": len(calls),
        "snapshots": calls,
        "final_transcript": previous,
        "all_snapshots_extend_previous": all(
            call["extends_previous_snapshot"] for call in calls
        ),
    }
    write_json(HERE / "response.json", response)
    (HERE / "artifacts/final_transcript.txt").write_text(previous + "\n")


if __name__ == "__main__":
    main()
