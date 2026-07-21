#!/usr/bin/env python3
"""Capture Kokoro HLS playlist revisions and every newly available AAC segment."""

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin

import av
import imageio_ffmpeg
import requests

SPACE = "evalstate/kokoro-tts-streaming-demo"
BASE = "https://evalstate-kokoro-tts-streaming-demo.hf.space"
OUT = Path(__file__).parent
TEXT = (
    "Streaming audio should become useful before a long tool call has finished. "
    "This first passage explains why early playback reduces perceived latency for a listener.\n\n"
    "The second passage is deliberately longer, giving the speech pipeline enough material to produce another independently playable segment. "
    "A client can begin presenting it while later synthesis continues.\n\n"
    "The third passage describes ordering. Every media segment needs a stable sequence number so the receiver can assemble the spoken result without gaps, duplication, or accidental reordering.\n\n"
    "The fourth passage concerns supervision. If the voice, wording, or pronunciation is wrong, a user should be able to stop generation after hearing an early segment instead of waiting for the entire recording.\n\n"
    "The fifth and final passage closes the demonstration. The completed artifact should match the ordered stream of earlier audio segments and remain independently playable after the remote job has ended."
)
PAYLOAD = {"data": [TEXT, "af_heart", 1, True]}
REQUEST = {
    "space": SPACE,
    "endpoint": "/generate_all",
    "transport": {
        "submit": "POST /gradio_api/call/generate_all",
        "stream": "GET /gradio_api/call/generate_all/{event_id}",
        "media_type": "text/event-stream",
        "media_delivery": "HLS playlist snapshots with AAC artifacts",
    },
    "payload": {
        "text": TEXT,
        "voice": "af_heart",
        "speed": 1,
        "use_gpu": True,
    },
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def parse_playlist(text):
    entries = []
    duration = None
    for line in text.splitlines():
        if line.startswith("#EXTINF:"):
            duration = float(line.split(":", 1)[1].split(",", 1)[0])
        elif line and not line.startswith("#"):
            entries.append({"uri": line, "duration_seconds": duration})
            duration = None
    return entries


def media_info(path):
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        duration = None
        if stream.duration is not None and stream.time_base is not None:
            duration = float(stream.duration * stream.time_base)
        elif container.duration is not None:
            duration = float(container.duration / av.time_base)
        return {
            "codec": stream.codec_context.name,
            "sample_rate": stream.codec_context.sample_rate,
            "channels": stream.codec_context.channels,
            "duration_seconds": round(duration, 6) if duration is not None else None,
        }


def main():
    token = os.environ.get("HF_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    session = requests.Session()
    session.headers.update(headers)
    (OUT / "request.json").write_text(json.dumps(REQUEST, indent=2) + "\n")

    start = time.monotonic()
    submit = session.post(
        f"{BASE}/gradio_api/call/generate_all", json=PAYLOAD, timeout=30
    )
    submit.raise_for_status()
    event_id = submit.json()["event_id"]

    raw_sequence = 0
    current_event = None
    terminal_event = None
    revision_hashes = set()
    revisions = []
    remote_to_local = {}
    segments = []

    with (
        session.get(
            f"{BASE}/gradio_api/call/generate_all/{event_id}",
            headers={"Accept": "text/event-stream", **headers},
            stream=True,
            timeout=(30, 300),
        ) as response,
        (OUT / "raw" / "events.jsonl").open("w") as raw_file,
    ):
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            elapsed = round(time.monotonic() - start, 6)
            raw_file.write(json.dumps({
                "sequence": raw_sequence,
                "elapsed_seconds": elapsed,
                "line": line,
            }) + "\n")
            raw_file.flush()
            raw_sequence += 1

            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
                if current_event in {"complete", "error"}:
                    terminal_event = current_event
                continue
            if not line.startswith("data:"):
                continue

            decoded = json.loads(line.split(":", 1)[1].strip())
            if current_event == "error":
                continue
            if not isinstance(decoded, list) or not decoded:
                continue

            descriptor = decoded[0]
            playlist_url = descriptor["url"]
            playlist_response = session.get(playlist_url, timeout=30)
            playlist_response.raise_for_status()
            playlist_bytes = playlist_response.content
            digest = sha256(playlist_bytes)
            if digest not in revision_hashes:
                revision_index = len(revisions)
                revision_path = OUT / "raw" / "playlists" / f"revision_{revision_index:03d}.m3u8"
                revision_path.write_bytes(playlist_bytes)
                entries = parse_playlist(playlist_response.text)
                revision = {
                    "index": revision_index,
                    "elapsed_seconds": elapsed,
                    "event": current_event,
                    "artifact": str(revision_path.relative_to(OUT)),
                    "sha256": digest,
                    "segment_count": len(entries),
                    "declared_duration_seconds": round(sum(
                        entry["duration_seconds"] or 0 for entry in entries
                    ), 6),
                    "source_sequence": raw_sequence - 1,
                    "remote_url": playlist_url,
                }
                revisions.append(revision)
                revision_hashes.add(digest)
                with (OUT / "raw" / "playlist_revisions.jsonl").open("a") as revision_file:
                    revision_file.write(json.dumps(revision) + "\n")

            for entry in parse_playlist(playlist_response.text):
                remote_uri = entry["uri"]
                if remote_uri in remote_to_local:
                    continue
                segment_url = urljoin(playlist_url, remote_uri)
                segment_response = session.get(segment_url, timeout=30)
                segment_response.raise_for_status()
                segment_bytes = segment_response.content
                index = len(segments)
                local_name = f"segment_{index:03d}.aac"
                local_path = OUT / "artifacts" / "segments" / local_name
                local_path.write_bytes(segment_bytes)
                remote_to_local[remote_uri] = local_name
                is_separator = (entry["duration_seconds"] or 0) == 0
                info = None
                if not is_separator:
                    info = media_info(local_path)
                segment = {
                    "index": index,
                    "elapsed_seconds": elapsed,
                    "artifact": str(local_path.relative_to(OUT)),
                    "mime_type": segment_response.headers.get("content-type", "audio/aac"),
                    "bytes": len(segment_bytes),
                    "sha256": sha256(segment_bytes),
                    "declared_duration_seconds": entry["duration_seconds"],
                    "separator": is_separator,
                    "media_info": info,
                    "remote_uri": remote_uri,
                }
                segments.append(segment)
                print(json.dumps({
                    "elapsed_seconds": elapsed,
                    "segment": local_name,
                    "duration_seconds": entry["duration_seconds"],
                    "bytes": len(segment_bytes),
                    "separator": is_separator,
                }), flush=True)

        elapsed_total = round(time.monotonic() - start, 6)

    if not revisions:
        raise SystemExit("no playlist revisions captured")

    # Rewrite the final remote playlist to stable local artifact names.
    final_remote = (OUT / revisions[-1]["artifact"]).read_text()
    final_local = final_remote
    for remote_uri, local_name in remote_to_local.items():
        final_local = final_local.replace(remote_uri, f"segments/{local_name}")
    final_playlist = OUT / "artifacts" / "final_playlist.m3u8"
    final_playlist.write_text(final_local)

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    final_wav = OUT / "artifacts" / "final_audio.wav"
    command = [
        ffmpeg, "-y", "-loglevel", "error", "-allowed_extensions", "ALL",
        "-i", str(final_playlist), "-c:a", "pcm_s16le", str(final_wav),
    ]
    completed = subprocess.run(command, text=True, capture_output=True)
    (OUT / "raw" / "ffmpeg_command.json").write_text(json.dumps({
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }, indent=2) + "\n")
    if completed.returncode:
        raise SystemExit(f"ffmpeg reconstruction failed: {completed.stderr}")

    playable = [segment for segment in segments if not segment["separator"]]
    result = {
        "event_id": event_id,
        "terminal_event": terminal_event or "stream_closed",
        "elapsed_seconds": elapsed_total,
        "time_to_first_audio_seconds": playable[0]["elapsed_seconds"] if playable else None,
        "playlist_revision_count": len(revisions),
        "segment_count": len(segments),
        "playable_segment_count": len(playable),
        "separator_segment_count": len(segments) - len(playable),
        "declared_audio_duration_seconds": round(sum(
            segment["declared_duration_seconds"] or 0 for segment in playable
        ), 6),
        "final_playlist": "artifacts/final_playlist.m3u8",
        "final_audio": "artifacts/final_audio.wav",
        "final_audio_sha256": sha256(final_wav.read_bytes()),
        "final_media_info": media_info(final_wav),
        "segments": segments,
        "playlist_revisions": revisions,
    }
    (OUT / "response.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "terminal_event", "elapsed_seconds", "time_to_first_audio_seconds",
        "playlist_revision_count", "playable_segment_count",
        "declared_audio_duration_seconds", "final_media_info"
    )}, indent=2), flush=True)
    if terminal_event != "complete" or len(playable) < 2:
        raise SystemExit("capture did not produce a complete multi-segment stream")


if __name__ == "__main__":
    main()
