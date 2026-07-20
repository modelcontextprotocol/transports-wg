# Gemma ordinary text-content stream

This capture calls the public `huggingface-projects/gemma-4-12b-it` Gradio
Server endpoint with thinking disabled and preserves every raw SSE line.

## Result

- Terminal event: `complete`
- Time to first ordinary content: **4.141 seconds**
- Ordinary content updates: **44**
- Reasoning updates: **0**
- Completion time: **7.074 seconds**
- Final answer length: **252 characters**
- Requested and returned sentence count: **5**

## Semantics

The producer sends cumulative snapshots:

```text
"The "
"The astronaut "
"The astronaut stepped "
```

Comparing successive snapshots shows the newly appended suffix:

```text
"The "
"astronaut "
"stepped "
```

The producer itself sends only the cumulative form. `raw/events.jsonl`
preserves every value exactly as received, including unchanged repeats.

## Final content

> The astronaut stepped through a heavy stone archway. Rows of ancient books
> lined the silent walls. Dust motes danced in the beam of his flashlight. He
> touched a leather spine and felt a strange warmth. Knowledge from a lost
> world waited in the shadows.

## Evidence

- `request.json` — exact endpoint and generation parameters
- `raw/events.jsonl` — every SSE line with arrival time
- `response.json` — terminal event, metrics, and final content
- `artifacts/final.txt` — independently readable final text
- `capture.py` — complete reproduction client
- `source/api_info.json` — endpoint description at capture time
- `source/space_info.json` — producer revision/runtime metadata
