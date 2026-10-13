#!/usr/bin/env python3
"""Capture Self-Forcing raw SSE, HLS revisions, MPEG-TS artifacts, and final MP4."""

import hashlib
import html
import json
import os
import re
import time
from fractions import Fraction
from pathlib import Path
from urllib.parse import urljoin

import av
import requests

SPACE = "multimodalart/self-forcing"
BASE = "https://multimodalart-self-forcing.hf.space"
ENDPOINT = "video_generation_handler_streaming"
OUT = Path(__file__).parent
PROMPT = "A small red paper boat sailing across a moonlit pond, cinematic, stable camera"
PAYLOAD = {"data": [PROMPT, 12345, 15]}
REQUEST = {
    "space": SPACE,
    "endpoint": f"/{ENDPOINT}",
    "transport": {
        "submit": f"POST /gradio_api/call/{ENDPOINT}",
        "stream": f"GET /gradio_api/call/{ENDPOINT}/{{event_id}}",
        "media_type": "text/event-stream",
        "media_delivery": "HLS playlist snapshots with MPEG-TS artifacts",
    },
    "payload": {"prompt": PROMPT, "seed": 12345, "fps": 15},
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


def strip_html(value):
    if isinstance(value, dict):
        value = value.get("value") or value.get("html") or json.dumps(value, sort_keys=True)
    elif value is None:
        value = ""
    elif not isinstance(value, str):
        value = str(value)
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(text).split())


def parse_progress(value):
    text = strip_html(value)
    result = {"text": text}
    block = re.search(r"Block\s+(\d+)\s*/\s*(\d+)", text, re.I)
    frame = re.search(r"Frame\s+(\d+)", text, re.I)
    percent = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if block:
        result.update({"block": int(block.group(1)), "blocks": int(block.group(2))})
    if frame:
        result["frame"] = int(frame.group(1))
    if percent:
        result["percent"] = float(percent.group(1))
    return result


def video_info(path, count_frames=False):
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        duration = None
        if stream.duration is not None and stream.time_base is not None:
            duration = float(stream.duration * stream.time_base)
        elif container.duration is not None:
            duration = float(container.duration / av.time_base)
        frame_count = None
        if count_frames:
            frame_count = sum(1 for _ in container.decode(stream))
        return {
            "codec": stream.codec_context.name,
            "width": stream.codec_context.width,
            "height": stream.codec_context.height,
            "fps": float(stream.average_rate) if stream.average_rate else None,
            "duration_seconds": round(duration, 6) if duration is not None else None,
            "frames": frame_count,
        }


def reconstruct_with_pyav(segment_paths, output_path, fps=15):
    """Decode discontinuous TS segments and write stable H.264 MP4 timestamps."""
    output = av.open(str(output_path), "w")
    stream = output.add_stream("libx264", rate=Fraction(fps, 1))
    stream.width = 832
    stream.height = 480
    stream.pix_fmt = "yuv420p"
    stream.time_base = Fraction(1, fps)
    stream.options = {"crf": "18", "preset": "medium"}
    frame_index = 0
    for path in segment_paths:
        with av.open(str(path)) as source:
            video = source.streams.video[0]
            for frame in source.decode(video):
                frame.pts = frame_index
                frame.time_base = Fraction(1, fps)
                for packet in stream.encode(frame):
                    output.mux(packet)
                frame_index += 1
    for packet in stream.encode():
        output.mux(packet)
    output.close()
    return frame_index


def main():
    token = os.environ.get("HF_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    session = requests.Session()
    session.headers.update(headers)
    (OUT / "request.json").write_text(json.dumps(REQUEST, indent=2) + "\n")

    start = time.monotonic()
    submit = session.post(
        f"{BASE}/gradio_api/call/{ENDPOINT}", json=PAYLOAD, timeout=30
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
    last_progress = None
    progress_update_count = 0

    with (
        session.get(
            f"{BASE}/gradio_api/call/{ENDPOINT}/{event_id}",
            headers={"Accept": "text/event-stream", **headers},
            stream=True,
            timeout=(30, 600),
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
            if not isinstance(decoded, list) or len(decoded) < 2:
                continue

            video_data, status_html = decoded[0], decoded[1]
            progress = parse_progress(status_html)
            if progress != last_progress:
                progress_update_count += 1
                last_progress = progress

            descriptor = None
            if isinstance(video_data, dict):
                descriptor = video_data.get("video")
            if not isinstance(descriptor, dict) or not descriptor.get("url"):
                continue

            playlist_url = descriptor["url"]
            playlist_response = session.get(playlist_url, timeout=30)
            if playlist_response.status_code != 200:
                with (OUT / "raw" / "playlist_fetch_errors.jsonl").open("a") as error_file:
                    error_file.write(json.dumps({
                        "elapsed_seconds": elapsed,
                        "url": playlist_url,
                        "status_code": playlist_response.status_code,
                    }) + "\n")
                continue
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
                segment_response = session.get(urljoin(playlist_url, remote_uri), timeout=30)
                segment_response.raise_for_status()
                segment_bytes = segment_response.content
                index = len(segments)
                local_name = f"segment_{index:03d}.ts"
                local_path = OUT / "artifacts" / "segments" / local_name
                local_path.write_bytes(segment_bytes)
                remote_to_local[remote_uri] = local_name
                info = video_info(local_path, count_frames=True)
                segment = {
                    "index": index,
                    "elapsed_seconds": elapsed,
                    "artifact": str(local_path.relative_to(OUT)),
                    "mime_type": segment_response.headers.get("content-type", "video/mp2t"),
                    "bytes": len(segment_bytes),
                    "sha256": sha256(segment_bytes),
                    "declared_duration_seconds": entry["duration_seconds"],
                    "media_info": info,
                    "remote_uri": remote_uri,
                }
                segments.append(segment)
                print(json.dumps({
                    "elapsed_seconds": elapsed,
                    "segment": local_name,
                    "duration_seconds": entry["duration_seconds"],
                    "frames": info["frames"],
                    "bytes": len(segment_bytes),
                }), flush=True)

        elapsed_total = round(time.monotonic() - start, 6)

    if not revisions or not segments:
        raise SystemExit("no HLS media captured")

    final_remote = (OUT / revisions[-1]["artifact"]).read_text()
    final_local = final_remote
    for remote_uri, local_name in remote_to_local.items():
        final_local = final_local.replace(remote_uri, f"segments/{local_name}")
    final_playlist = OUT / "artifacts" / "final_playlist.m3u8"
    final_playlist.write_text(final_local)

    final_mp4 = OUT / "artifacts" / "final_video.mp4"
    reconstruction = "pyav-decode-reencode"
    reconstruct_with_pyav(
        [OUT / segment["artifact"] for segment in segments],
        final_mp4,
        fps=15,
    )

    result = {
        "event_id": event_id,
        "terminal_event": terminal_event or "stream_closed",
        "elapsed_seconds": elapsed_total,
        "time_to_first_video_seconds": segments[0]["elapsed_seconds"],
        "playlist_revision_count": len(revisions),
        "segment_count": len(segments),
        "progress_update_count": progress_update_count,
        "declared_video_duration_seconds": round(sum(
            segment["declared_duration_seconds"] or 0 for segment in segments
        ), 6),
        "segment_frame_count": sum(
            segment["media_info"]["frames"] or 0 for segment in segments
        ),
        "final_playlist": "artifacts/final_playlist.m3u8",
        "final_video": "artifacts/final_video.mp4",
        "final_video_sha256": sha256(final_mp4.read_bytes()),
        "reconstruction": reconstruction,
        "final_media_info": video_info(final_mp4, count_frames=True),
        "segments": segments,
        "playlist_revisions": revisions,
    }
    (OUT / "response.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "terminal_event", "elapsed_seconds", "time_to_first_video_seconds",
        "playlist_revision_count", "segment_count", "progress_update_count",
        "declared_video_duration_seconds", "segment_frame_count", "final_media_info"
    )}, indent=2), flush=True)
    if terminal_event != "complete" or len(segments) < 2:
        raise SystemExit("capture did not produce a complete multi-segment stream")


if __name__ == "__main__":
    main()
