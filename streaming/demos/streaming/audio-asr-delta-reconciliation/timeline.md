# Realtime ASR delta and reconciliation timeline

Producer source:
[`okadahiroaki/qwen3-omni-realtime-asr-demo`](https://huggingface.co/spaces/okadahiroaki/qwen3-omni-realtime-asr-demo)

The Hub repository is a static code distribution, so its backend was
temporarily deployed unchanged on an A100 80 GB with the official
`Qwen/Qwen3-Omni-30B-A3B-Instruct` BF16 checkpoint. The model checkpoint was
65.68 GiB and occupied 59.19 GiB of GPU memory after loading. Container-only
adjustments are preserved in `source/Dockerfile`. The temporary Space was
permanently deleted after capture.

Input: the same 5.855-second LibriSpeech utterance used by
`audio-asr-streaming-input`, followed by 0.5 seconds of silence so the
1.5-second scheduler performs a final inference over all speech.

| Round audio | Status | First delta | Reconciled update | Result |
|---:|---:|---:|---:|---|
| 1.5 s | 1.863 s | 2.484 s | 2.563 s | `[spk_0] Mister Quilter is the` |
| 3.1 s | 3.427 s | 3.496 s | 3.642 s | `[spk_0] Mr. Quilter is the apostle of the middle classes.` |
| 4.6 s | 4.983 s | 5.608 s | 5.668 s | provisional tail: `And we are glad to welcome him.` |
| 6.1 s | 6.522 s | 7.447 s | 7.515 s | corrected tail: `And we are glad to welcome his gospel.` |

Raw WebSocket evidence:

- 4 `status` messages
- 12 `delta` messages
- 4 `update` messages
- first delta at 2.484 seconds
- final reconciled update at 7.515 seconds

Final confirmed transcript:

> [spk_0] Mr. Quilter is the apostle of the middle classes. And we are glad
> to welcome his gospel.

## Semantic distinction

Within a round, each `delta` is appendable to that round's provisional text.
At the next `status: infer`, provisional display text is reset. The following
`update` replaces the pending transcript region with a reconciled
`confirmed` snapshot.

This produced two visible corrections:

1. `Mister Quilter` became `Mr. Quilter`.
2. `welcome him` became `welcome his gospel`.

The twelve deltas must therefore not be concatenated globally as permanent
text. `response.json` groups them by round and retains each corresponding
update.
