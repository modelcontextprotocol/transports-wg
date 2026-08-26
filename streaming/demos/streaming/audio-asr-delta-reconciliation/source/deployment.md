# Temporary runtime deployment

The producer Hub repository is `sdk: static`; it distributes the realtime
FastAPI/WebSocket server but does not run it.

For this evidence capture, `source/server.py` and `source/index.html` were
deployed without application changes on:

- Space: `evalstate/qwen-realtime-asr-evidence`
- Hardware: A100 80 GB
- Model: `Qwen/Qwen3-Omni-30B-A3B-Instruct`
- vLLM: 0.25.1
- Transformers: 5.14.1

Observed startup facts:

- checkpoint size: 65.68 GiB
- model GPU memory after load: 59.19 GiB
- model architecture: `Qwen3OmniMoeForConditionalGeneration`

`Dockerfile` contains only deployment adaptations:

- start the producer's FastAPI app instead of vLLM's OpenAI server
- provide writable cache/home paths for the Space runtime UID
- make `/app` writable because the producer intentionally stores
  `mic_last.wav` beside `server.py`

The Space was permanently deleted immediately after the successful capture.
