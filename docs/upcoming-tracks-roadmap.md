# Transports WG: Upcoming Tracks Roadmap

This document is a high-level outline of the tracks the Transports Working Group
expects to take up next. Each track gets a short brief: the goal (what problem
it solves), the core idea of the solution, key requirements, and the open
questions we still need to answer. As tracks mature, each brief should graduate
into a full problem statement or proposal under `proposals/`.

Tracks are listed in rough priority order.

Related work already in flight:

* [Multi Round-Trip Requests:
  Brief](../proposals/multi-round-trip-requests-track-brief.md)
* [Sessions Reintroduction Problem
  Statement](sessions-reintroduction-problem-statement.md)
* Caching & Optimization Track (TTLs and ETags for resources and list responses)
  — several tracks below interact with it and are cross-referenced.

---

## 1. Tool Versioning

**Goal:** Eliminate skew between the tool definition a client has cached and the
tool the server actually executes. As caching (TTLs/ETags) makes long-lived
cached `tools/list` results normal, clients need a way to know *which version*
of a tool they are calling, and servers need a way to detect calls made against
stale definitions.

**Core Idea:** Carry the ETag mechanism from the Caching & Optimization track
down to the individual tool definition. Each tool in `tools/list` gets an opaque
version identifier; clients echo it on `tools/call`; the server can then detect
a mismatch and respond with a standard "stale tool definition" error that tells
the client to refresh, rather than silently executing with different semantics
than the model saw.

**Key Requirements:**

* A standard per-tool version field in tool definitions (opaque, like an ETag —
  not required to be ordered or semantic).
* An echo mechanism on `tools/call` (likely `_meta`) carrying the version the
  client believes it is calling.
* Defined mismatch semantics: a standard error code/shape that signals "re-fetch
  the tool list and retry", distinguishable from tool execution errors.
* Coherent layering with list-level caching: list ETag/TTL governs when to
  re-fetch; per-tool versions govern call-time validity.

**Open Questions:**

* Opaque hash vs. semantic version? An opaque hash is simplest and matches ETag
  semantics; semver would let servers express compatible vs. breaking changes
  but invites misuse.
* Is echoing the version on `tools/call` required or optional? Optional
  preserves backwards compatibility but weakens the guarantee.
* Mismatch behavior: hard failure, or server MAY accept if the change is
  compatible? Who decides compatibility?
* What exactly is hashed — the whole definition (description edits invalidate)
  or just the machine-relevant parts (schema, annotations)? Note interaction
  with i18n: localized descriptions must not change the version, or every
  language gets a different one.
* Does the same mechanism generalize to prompts and resources?

---

## 2. Pluggable Transports

**Goal:** Allow MCP to run over transports beyond stdio and Streamable HTTP
(e.g., gRPC, WebSockets, in-process/embedded) without forking SDKs or
re-specifying protocol behavior per transport. Organizations with existing RPC
infrastructure should be able to carry MCP over it while application code stays
unchanged.

**Core Idea:** Separate protocol semantics from transport bindings. Define an
abstract transport contract — the guarantees any conforming transport must
provide (message framing, ordering, request/response correlation,
bidirectional/server-initiated messages, a metadata channel) — and have SDKs
expose that contract as a stable interface. Custom transports plug in beneath
the SDK; the spec describes required semantics rather than a single wire format.

**Key Requirements:**

* A formal transport contract: what a transport MUST provide (delivery,
  ordering, duplex messaging, metadata/headers) and what is optional.
* Stable, consistent SDK transport interfaces across languages, so a transport
  implementation written against the contract works with unmodified
  server/client application code.
* A way for the protocol layer to detect optional transport features (e.g.,
  server push, resumability, metadata channel) and degrade gracefully.
* Guidance for mapping the MCP lifecycle (initialization, shutdown,
  reconnection) onto a new transport.
* Ideally, a conformance checklist or test suite for third-party transports.

**Open Questions:**

* Where is the line between transport-defined and protocol-defined behavior?
  Sessions, resumability, and auth currently lean on HTTP-specific mechanisms.
* How do we handle transports without a natural metadata/header channel —
  require `_meta` mirroring everywhere, or make headers optional?
* Do we need a naming/registry scheme for transports (URI schemes, capability
  identifiers) so clients and servers can agree on one?
* Relationship to the HTTP-over-stdio track: if HTTP semantics become the
  canonical binding, does "pluggable transport" reduce to "anything that can
  carry HTTP", or do we keep a lower-level message contract?
* How do we recover the previously deferred pluggable transports PR and
  reconcile it with the unified proposal (see 2026-05-27 meeting notes)?

---

## 3. HTTP over STDIO

**Goal:** Reduce the behavioral divergence between the stdio and Streamable HTTP
transports. Today stdio has a pile of bespoke behavior (framing, lifecycle, no
headers), which means every HTTP-native feature — headers, status codes,
caching, compression, auth, language negotiation — needs a second,
stdio-specific design or simply doesn't work locally.

**Core Idea:** Instead of maintaining two transport designs, run HTTP itself
over the stdin/stdout pipe: the subprocess speaks the same Streamable HTTP
binding it would speak over a socket, just with the byte stream attached to
pipes. stdio becomes "a connection like any other", and the spec converges on a
single transport binding with one behavior model.

**Key Requirements:**

* A framing choice (HTTP/1.1 vs. HTTP/2 over the pipe) that supports concurrent
  in-flight requests and server-initiated messages — plain HTTP/1.1
  request/response over a single pipe pair is not enough.
* Full parity for metadata: headers must work identically to network HTTP so
  features like i18n (`Accept-Language`) and caching (`ETag`) apply unchanged.
* A detection/negotiation story: clients must be able to tell whether a spawned
  server speaks legacy newline-delimited JSON-RPC or HTTP-over-stdio, with a
  long deprecation path for the former.
* Implementation burden must stay small — local stdio servers are often tiny
  scripts; requiring a full HTTP/2 stack may be prohibitive outside major SDK
  languages.
* Compatibility with the ongoing stdio process-lifecycle work (crash-only
  restarts, stderr conventions).

**Open Questions:**

* HTTP/1.1 with a bidirectional convention vs. HTTP/2 multiplexing? HTTP/2 gives
  real streams but a much heavier dependency.
* How do server-initiated requests map onto HTTP's client-initiated model — a
  reverse HTTP channel over the same pipes, or SSE streams as in Streamable
  HTTP?
* Does this actually reduce complexity, or relocate it (an HTTP parser in every
  hello-world stdio server)? What does the minimal conforming server look like?
* Is this a new named transport, a stdio v2 revision, or an optional binding
  negotiated at startup?
* Does auth over local pipes inherit HTTP auth semantics, or is it explicitly
  out of scope as it is for stdio today?

---

## 4. Streaming

**Goal:** Let servers return large or incremental results — database queries
with thousands of rows, generated images, long documents — as a stream of chunks
instead of a single terminal response. Today the entire result must be buffered
on both sides and the client sees nothing until the call completes.

**Core Idea:** Extend tool results (and potentially other responses) with
partial/chunked delivery over the existing streaming machinery: a call yields an
ordered sequence of result chunks followed by a terminal message with final
status. Chunking is content-block oriented so both structured data and binary
content work, and the semantics are transport-independent (SSE carries it
naturally; stdio needs the same model — see the HTTP-over-stdio track).

**Key Requirements:**

* Chunk framing with ordering guarantees and a distinguishable terminal message
  carrying final status.
* Cancellation mid-stream, in both directions, with defined cleanup semantics.
* A clear boundary with tasks: when should a long-running call be a task vs. a
  stream, and how does streaming a *task's* output work? (Raised in the
  2026-06-24 meeting; cancellation interaction is the sharp edge.)
* Resumability: what happens when a stream is interrupted — redelivery from an
  offset, restart, or failure?
* A backpressure/flow-control position, even if the position is "none, bounded
  by transport" — unbounded streams to a slow consumer must not be undefined
  behavior.

**Open Questions:**

* Is streaming a new mechanism or an extension of tasks? The WG flagged that
  auto-streaming may conflict with existing task cancellation cases; simplifying
  tasks may be in scope.
* Partial results on error: is a stream that fails midway a failed call, a
  partial success, or client's choice?
* What guidance do clients get on spooling vs. forwarding chunks to the model as
  they arrive?
* Binary content chunking: base64 inflation is significant — should this track
  align with the Gzip/compression work?

---

## 5. Internationalization

**Goal:** Give clients a standard way to request human-readable strings in a
particular language and servers a standard way to declare which language they
returned. Today there is no mechanism at all, which forces ad-hoc solutions and
discourages investment in localized MCP servers.
(Tracked in [transports-wg#42](https://github.com/modelcontextprotocol/transports-wg/pull/42).)

**Core Idea:** Web-aligned, stateless, per-request language negotiation: clients
send `params._meta["io.modelcontextprotocol/acceptLanguage"]` (RFC 9110
`Accept-Language` semantics) and servers respond with
`result._meta["io.modelcontextprotocol/contentLanguage"]`. On Streamable HTTP
these mirror into the real HTTP headers, with mismatches rejected. Because
negotiation is per-request, language can change mid-conversation with no
renegotiation or session state.

**Key Requirements:**

* RFC 9110 `Accept-Language` matching semantics, not a custom scheme.
* Explicit enumeration of what may be translated, in three buckets: display-only
  fields (titles, notifications) MUST be translatable; model-facing hints
  (descriptions) MAY be, with caveats; machine-interpreted values (names, URIs,
  enum tokens) MUST NOT be.
* Graceful degradation: requests carrying a language preference MUST NOT fail
  against servers that don't implement i18n.
* Consistency rules between `_meta` fields and HTTP headers when both are
  present.

**Open Questions:**

* Error code alignment: the proposal provisionally uses `-32005` for header
  mismatch while another PR moved error codes to the `32020+` range.
* MUST vs. SHOULD: when a server *has* a localized form, is returning it
  mandatory?
* Interaction with the caching track: language becomes a cache key (`Vary:
  Accept-Language`); list ETags and tool versions must not vary by language, or
  must account for it explicitly.
* Translating model-facing text changes agent behavior — do we need guidance on
  evaluating tool-selection quality across languages?

---

## 6. Capabilities for Tools

**Goal:** Remove the ambiguity SEP-1442 introduced when client capabilities
moved from initialization to per-request `_meta`: servers no longer know, at
`tools/list` time, which capabilities the client will declare on later
`tools/call` requests — so they cannot deterministically decide which tools to
expose or how those tools should behave.
(Tracked in [transports-wg#31](https://github.com/modelcontextprotocol/transports-wg/pull/31).)

**Core Idea:** Define the scope of per-request capabilities. The current
proposal is *global scope*: capabilities declared on any request are assumed to
apply to all requests from that client, so a `tools/list` can be filtered
accordingly. Alternatives under discussion: tool-level capability annotations
(tools declare what they need; the client filters), and related-request
capabilities.

**Key Requirements:**

* Deterministic `tools/list` results given a declared capability set — no
  server-side guessing.
* A clear client obligation: if the client's capability set changes, it must
  refresh cached lists (reframing suggested in review: this is a client-refresh
  responsibility, not a server-persistence assumption, keeping the protocol
  stateless).
* Privacy by design: clients must not be forced to disclose their full
  capability set to arbitrary servers — capability disclosure is a
  fingerprinting vector (raised in PR review, with the HTTP user-agent history
  as the cautionary tale).
* No requirement for servers to remember per-client capabilities across
  requests.

**Open Questions:**

* Global scope vs. tool-level annotations vs. related-request capabilities — the
  PR carries a comparison matrix; tool-level annotations preserve client
  discretion but push filtering to the client.
* How does "scope" language square with a stateless protocol? The
  refresh-obligation framing may replace scope language entirely.
* Interaction with the caching track: capability-dependent lists make the
  capability set a cache key — how do list ETags/TTLs account for it?
* Can a client under-declare and upgrade later (progressive disclosure), and
  what does that do to cached lists?

---

## 7. Sessions

> **Note — deprioritized pending stronger use cases.** The WG is not committing
> effort to a sessions design until more compelling use cases are documented
> that cannot be met by narrower mechanisms (correlation/routing IDs, the MRTR
> pass-through-client state, caching). Sessions were deliberately removed from
> the protocol, and core maintainers have set a high bar: a very strong,
> concrete case is required to reintroduce anything session-shaped. Until that
> case exists, this track stays a problem-statement exercise — see the
> [Sessions Reintroduction Problem
> Statement](sessions-reintroduction-problem-statement.md) — not a design
> effort.

**Goal:** Serve the real needs that keep pulling people back toward sessions —
load-balancer affinity for stateful servers, observability and correlation,
per-conversation tool scoping, cross-protocol interop with A2A `contextId`,
persistent memory — without reintroducing the lifecycle complexity that got
sessions removed from the protocol.
(See the [Sessions Reintroduction Problem
Statement](sessions-reintroduction-problem-statement.md) and the [sessions vs.
sessionless decision](sessions-vs-sessionless-decision.md).)

**Core Idea:** Old-style sessions conflated two distinct primitives: a
wire-visible correlation/routing identifier (what load balancers and tracing
need) and a state-scoping context (what progressive discovery and memory need).
Work from the documented use cases and decide which primitive(s) the protocol
actually needs — possibly neither requires reintroducing full protocol-level
session lifecycle.

**Key Requirements:**

* Cover the use-case categories in the problem statement; any proposal should
  state explicitly which categories it does and does not address.
* Explicit lifecycle boundaries — creation, expiry, termination. Core
  maintainers have been clear that undefined session lifetimes were a primary
  reason sessions were removed, and that a very strong case is required to bring
  anything back.
* Sessionless operation remains first-class: servers that don't need state must
  not pay for those that do.
* Routing-friendliness: whatever identifier exists must be visible to
  infrastructure (header-level on HTTP), not buried in the JSON-RPC body.
* Coherence with the MRTR track's pass-state-through-client mechanism —
  cookie-like state and session identifiers overlap, and we should not ship two
  competing mechanisms.

**Open Questions:**

* Identifier, context, or both? And is the identifier purely opaque correlation,
  or does it carry scoping semantics?
* Who generates the ID — client or server — and what does that imply for routing
  and trust?
* Optionality: capability-gated, or universal? What happens when one side
  supports it and the other doesn't?
* Overlap with MRTR cookies and with tasks: three mechanisms currently gesture
  at "state that outlives a request" — do they converge?
* Cross-protocol alignment: should the identifier be compatible with (or
  mappable to) A2A `contextId`?


