#!/usr/bin/env python3
"""Capture Qwen realtime ASR WebSocket deltas and reconciliation updates."""

import asyncio
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import requests
import soundfile as sf
import websockets

HERE = Path(__file__).parent
BASE = "https://evalstate-qwen-realtime-asr-evidence.hf.space"
WS_URL = "wss://evalstate-qwen-realtime-asr-evidence.hf.space/ws"
INPUT = (
    HERE.parent
    / "audio-asr-streaming-input/artifacts/input/1272-128104-0000.wav"
)
LOCAL_INPUT = HERE / "artifacts/input/1272-128104-0000.wav"
SR = 16000


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


async def capture() -> tuple[list[dict], float]:
    audio, source_rate = sf.read(INPUT, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if source_rate != SR:
        raise RuntimeError(f"Expected {SR} Hz input, got {source_rate}")
    # A half-second silence tail moves the 5.855-second utterance past the next
    # 1.5-second inference threshold, ensuring the final round observes all
    # source speech rather than stopping at the prior 4.61-second boundary.
    audio = np.concatenate([audio, np.zeros(SR // 2, dtype=np.float32)])
    sf.write(LOCAL_INPUT, audio, SR, subtype="PCM_16")

    messages: list[dict] = []
    started = time.monotonic()
    last_message = started

    async with websockets.connect(WS_URL, max_size=None) as socket:
        async def reader() -> None:
            nonlocal last_message
            async for encoded in socket:
                elapsed = time.monotonic() - started
                last_message = time.monotonic()
                messages.append(
                    {
                        "elapsed_seconds": round(elapsed, 6),
                        "message": json.loads(encoded),
                    }
                )

        reader_task = asyncio.create_task(reader())
        step = 4096
        for start in range(0, len(audio), step):
            await socket.send(audio[start : start + step].astype(np.float32).tobytes())
            await asyncio.sleep(step / SR)

        # Wait until at least one reconciled update has arrived and the
        # connection has then been idle long enough to exclude another round.
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            updates = [
                item for item in messages if item["message"].get("type") == "update"
            ]
            if updates and time.monotonic() - last_message >= 8:
                break
            await asyncio.sleep(0.25)
        reader_task.cancel()
        try:
            await reader_task
        except asyncio.CancelledError:
            pass

    return messages, time.monotonic() - started


def main() -> None:
    LOCAL_INPUT.parent.mkdir(parents=True, exist_ok=True)
    (HERE / "raw").mkdir(parents=True, exist_ok=True)
    (HERE / "artifacts/output").mkdir(parents=True, exist_ok=True)
    health = requests.get(f"{BASE}/health", timeout=60)
    health.raise_for_status()
    messages, terminal_seconds = asyncio.run(capture())

    with (HERE / "raw/ws_messages.jsonl").open("w") as handle:
        for item in messages:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    received_audio = requests.get(f"{BASE}/mic_last.wav", timeout=120)
    received_audio.raise_for_status()
    (HERE / "artifacts/output/server_received_audio.wav").write_bytes(
        received_audio.content
    )
    mic_info = requests.get(f"{BASE}/mic_info", timeout=60)
    mic_info.raise_for_status()
    write_json(HERE / "artifacts/output/server_received_audio_info.json", mic_info.json())

    request = {
        "producer": "okadahiroaki/qwen3-omni-realtime-asr-demo",
        "capture_space": "evalstate/qwen-realtime-asr-evidence",
        "transport": "WebSocket binary float32 audio and JSON messages",
        "input": {
            "path": "artifacts/input/1272-128104-0000.wav",
            "sha256": hashlib.sha256(LOCAL_INPUT.read_bytes()).hexdigest(),
            "source_dataset": "hf-internal-testing/librispeech_asr_demo",
            "config": "clean",
            "split": "validation",
            "row": 0,
            "source_speech_seconds": 5.855,
            "trailing_silence_seconds": 0.5,
        },
        "server_health": health.json(),
        "deployment": {
            "model": "Qwen/Qwen3-Omni-30B-A3B-Instruct",
            "hardware": "A100 80 GB",
            "source_server": "source/server.py",
            "container": "source/Dockerfile",
        },
    }
    write_json(HERE / "request.json", request)

    deltas = [
        item for item in messages if item["message"].get("type") == "delta"
    ]
    updates = [
        item for item in messages if item["message"].get("type") == "update"
    ]
    statuses = [
        item for item in messages if item["message"].get("type") == "status"
    ]
    rounds = []
    current_round = None
    for item in messages:
        message = item["message"]
        if message.get("type") == "status" and message.get("state") == "infer":
            current_round = {
                "audio_seconds": message.get("audio_sec"),
                "status_seconds": item["elapsed_seconds"],
                "deltas": [],
            }
            rounds.append(current_round)
        elif message.get("type") == "delta" and current_round is not None:
            current_round["deltas"].append(
                {
                    "elapsed_seconds": item["elapsed_seconds"],
                    "text": message.get("delta", ""),
                }
            )
        elif message.get("type") == "update" and current_round is not None:
            current_round["delta_text"] = "".join(
                delta["text"] for delta in current_round["deltas"]
            )
            current_round["update_seconds"] = item["elapsed_seconds"]
            current_round["update"] = message
    response = {
        "terminal_seconds": round(terminal_seconds, 6),
        "websocket_messages": len(messages),
        "status_messages": len(statuses),
        "delta_messages": len(deltas),
        "update_messages": len(updates),
        "first_delta_seconds": deltas[0]["elapsed_seconds"] if deltas else None,
        "first_update_seconds": updates[0]["elapsed_seconds"] if updates else None,
        "rounds": rounds,
        "updates": [item["message"] for item in updates],
        "final_confirmed": (
            updates[-1]["message"].get("confirmed") if updates else None
        ),
        "server_received_audio": mic_info.json(),
    }
    write_json(HERE / "response.json", response)
    if updates:
        (HERE / "artifacts/output/final_confirmed.txt").write_text(
            updates[-1]["message"].get("confirmed", "") + "\n"
        )


if __name__ == "__main__":
    main()
