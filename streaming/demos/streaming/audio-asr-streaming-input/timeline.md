# Stateful streaming-input ASR timeline

Producer: [`gradio/stream_asr`](https://huggingface.co/spaces/gradio/stream_asr)

Input: LibriSpeech validation row `1272-128104-0000`, a 5.855-second
utterance split into three consecutive WAV chunks of 2.0, 2.0, and 1.855
seconds.

Ground truth:

> MISTER QUILTER IS THE APOSTLE OF THE MIDDLE CLASSES AND WE ARE GLAD TO
> WELCOME HIS GOSPEL

All calls used one Gradio queue/client session. This is material: independent
simple `/call` requests do not retain the hidden `gr.State`.

| Chunk | Cumulative time | Transcript snapshot |
|---:|---:|---|
| 1 | 31.366 s | `Mr. Quilter is the apostle.` |
| 2 | 62.961 s | `Mr. Quilter is the apostle of the middle classes, and we are glad` |
| 3 | 94.250 s | `Mr. Quilter is the apostle of the middle classes, and we are glad to welcome his gospel.` |

The second snapshot is not a pure append. It replaces the period after
`apostle` with ` of the middle classes, and we are glad`. This is ordinary
snapshot revision caused by retranscribing all accumulated audio.

The producer source does:

```python
stream = np.concatenate([stream, y]) if stream is not None else y
return stream, transcriber({"sampling_rate": sr, "raw": stream})["text"]
```

It therefore streams input chunks but returns a full transcript-so-far. The
suffix and replacement fields in `response.json` are local comparisons, not
producer-supplied deltas.

## Gradio client qualification

The deployed Space uses Gradio 6.20.0. Its queue sends the already-defined
`process_streaming` server message. `gradio_client` 2.5.0 recognizes that enum
but omits it from `Status.msg_to_status()`, causing a `KeyError`. `capture.py`
applies one compatibility mapping:

```python
process_streaming -> Status.ITERATING
```

No producer data or session behavior is changed.
