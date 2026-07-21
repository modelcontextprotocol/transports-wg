# Structured OCR stream timeline

Producer: [`ATH-MaaS/OvisOCR2`](https://huggingface.co/spaces/ATH-MaaS/OvisOCR2)

Input: row 2 of `katanaml-org/invoices-donut-data-v1`, a one-item invoice with
field-level ground truth.

| Observation | Elapsed |
|---|---:|
| `page_start` | 7.763 s |
| First non-empty markdown snapshot | 7.765 s |
| Final 802-character markdown snapshot | 15.496 s |
| `page_complete` | 15.591 s |
| Application `complete` | 15.690 s |
| Transport terminal event | 15.791 s |

The raw SSE contains:

- one `page_start`
- 41 `stream` payloads
- 26 changing snapshots, 25 of them non-empty
- one `page_complete`
- an application `complete`
- a final transport completion payload that repeats the application result

The final markdown correctly recovers the invoice number, date, seller,
client, tax identifiers, IBAN, item description, quantities, and totals.

The model's `TextIteratorStreamer` emits fragments internally. The application
accumulates those fragments and yields complete markdown-so-far:

```python
text += fragment
yield text
```

The public API therefore exposes structured lifecycle events containing
cumulative markdown snapshots, not independent markdown deltas.
