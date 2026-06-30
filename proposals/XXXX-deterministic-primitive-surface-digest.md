# SEP-XXXX: Deterministic Per-Primitive Digests

- **Status**: Draft
- **Type**: Standards Track
- **Created**: 2026-06-25
- **Author(s)**: Sam Morrow (@SamMorrowDrums)
- **Sponsor**: None (seeking sponsor)
- **PR**: https://github.com/modelcontextprotocol/specification/pull/{NUMBER}
- **Related**: [SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575) (Stateless MCP), [SEP-2567](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2567) (Sessionless MCP), [SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549) (TTL for List Results), [SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243) (HTTP Header Standardization), [SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414) (Request `_meta`)

## Abstract

This SEP gives every caller-visible primitive — each tool, prompt, resource, and
resource template — a deterministic, opaque **digest** of its own definition,
carried in that primitive's `_meta`. The digest is an
[ETag](https://www.rfc-editor.org/rfc/rfc7232) for a single primitive: an opaque
validator that a client compares only for equality.

Because the digest travels with the primitive in `*/list` results, a client
remembers the digest of each primitive it caches. When the client later acts on a
primitive — `tools/call`, `prompts/get`, `resources/read` — it **MAY** echo the
digest it planned against in the request `_meta`. This turns an ordinary request
into an optimistic conditional request (an MCP-native `If-Match`): the server can
detect that _this specific primitive_ changed underneath the caller and decline to
execute against a contract the client no longer shares — returning the current
digest — instead of running a tool whose input or **output schema** has drifted.
A server **MAY** instead serve the request and return the current digest. The
client, in turn, **MAY** fail open, fail closed, or prompt the user when a digest
no longer matches.

The mechanism is built for a stateless-first protocol
([SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575),
[SEP-2567](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2567)).
It needs no long-lived connection, no SSE stream, and no `subscriptions/listen`.
It composes with the caching utility
([SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)):
`ttlMs` remains the **freshness budget** that governs when a client re-lists,
while the per-primitive digest is the **validator** that governs whether an
individual call is still operating against the primitive the client planned for.
A digest's shareability follows the primitive's `cacheScope`. The change is
additive and fully backward compatible.

## Motivation

### The fundamental case: production server deployments

The case MCP has never had a working specification answer for is the most ordinary
one in production: **a server is redeployed and its primitives change.** A new
version adds, removes, or alters tools — including changing an `inputSchema` or
`outputSchema` — and every client that cached the old surface is now planning and
validating calls against a contract the live deployment no longer honors.

This is not MCP internal session state. It is a fact about the world: the
deployment of a server is not static, and a connected agent's view of the
primitive surface should be able to reflect that reality deterministically. Yet
the existing mechanisms do not deliver it for real, scaled deployments:

- **TTL alone is non-deterministic with respect to deploys.** A client that
  fetched `tools/list` one second before a rollout keeps using the old list for
  the remainder of its freshness budget — possibly minutes or hours — while every
  call is being served by a new deployment with a different surface. TTL tells the
  client how long it _may avoid re-listing_, not whether a primitive it is about to
  call has changed.
- **`list_changed` requires a connection nobody is holding.** A stateless client
  has no open `subscriptions/listen` stream to receive a push on, and — as the
  operational experience below shows — routing a deploy-driven notification back to
  the right connection across a scaled fleet is racy and was never practical.

A per-primitive digest closes exactly this gap: the moment a client calls a tool
whose definition changed in the new deployment, the echoed digest no longer
matches and the server can say so — before the call runs — with no session, no
subscription, and no cross-instance coordination.

### Other drivers: permission changes and schema drift

The same per-primitive validator covers two related changes that are likewise
"state of the world," not protocol state:

- **External authorization changed.** A caller gains or loses access to a tool, or
  a tool's visible definition is permission-filtered. Servers may vary the visible
  set by the authorization presented on the request (`server/tools`: the set
  "**MAY** vary by the authorization presented on the request"). When entitlements
  change, the digest of an affected primitive changes with them.
- **A running server can violate its own advertised schema.** When a deploy changes
  a tool's `outputSchema`, a client holding the old definition validates
  `structuredContent` against a contract the live server no longer honors — the
  server returns output valid under its _new_ schema that fails the client's _old_
  one. Worse, the model may have chosen arguments against a stale `inputSchema`.
  The per-primitive digest lets either side notice the drift on the specific
  primitive being used, before the call produces a confusing failure or an
  unintended side effect.

List-level _discovery_ of change — "has any primitive in this list changed?" — is
deliberately **not** this SEP's job; that is what `ttlMs` (re-list when stale) and,
optionally, `list_changed` are for. This SEP adds the one thing neither of those
can provide statelessly: a deterministic, per-call answer to "is the primitive I
am about to invoke still the one I planned against?"

### Operational experience: why the existing mechanisms did not solve this

Operating a large remote MCP server (the GitHub MCP server) surfaced three dead
ends when we tried to tell clients "the server changed, please refresh":

1. **We did not want to require a GET/stream just for deploy updates.** Standing up
   and holding a server-to-client stream solely so we could occasionally announce a
   deployment is disproportionate, and a stateless client will not hold it open
   anyway.
2. **`tools/list_changed` is not universally supported.** Many clients do not act
   on it today, and a stateless transport makes it opt-in via a subscription that
   most stateless callers will not take. A signal only some clients honor cannot be
   the system of record for "your tools are stale."
3. **Revoking a session to force renegotiation bricked the server in practice.** In
   testing with real clients, a revoked session id did not cause a clean
   re-handshake; it left the agent unable to access the server at all. Session
   identity was meant to be revocable to trigger renegotiation, but practically it
   was not a usable change-propagation tool — and the stateless direction removes
   sessions entirely.

Each path failed for the same reason: it tried to make change-propagation a
property of a _connection or session_. A per-primitive digest makes it a property
of the _primitive_, which is exactly the thing that changed.

### Why push notifications are especially awkward for scaled deployments

Even where a connection exists, delivering "the surface changed because we
deployed" over `list_changed` is hard to reason about at scale:

- The deployment event must be fanned out to the right connected callers. Without a
  session id to address (the stateless direction removes it), the server must
  either broadcast to all current connections or maintain a side-channel
  (a message queue) to find which connection to notify.
- Instances update at different times during a rolling deploy, so there is no
  single "change instant" to announce; different replicas would emit the
  notification at different moments, which is racy and confusing.

A pull-based, per-primitive digest sidesteps all of it: each instance simply stamps
the digest of the primitive it is serving. Correctness needs no cross-instance
coordination and no notion of a global change moment — a property the push model
cannot offer for a gradual rollout. Push remains the right tool for prompt,
low-latency invalidation on a connection a client is _already_ holding; the digest
is the right tool for stateless clients and for deploy-driven change.

## Specification

### Overview

Each caller-visible primitive carries a deterministic digest of its own definition
in its `_meta`. A client remembers the digest of each primitive it caches from
`*/list`. When the client acts on a primitive, it **MAY** echo the planned digest;
the server **MAY** use it as a precondition and reject (or tolerate) a changed
primitive. Single-primitive results also carry the current digest of the primitive
that was acted on, so a client stays in sync even on success.

### Per-primitive digest (`io.modelcontextprotocol/digest`)

One reserved `_meta` key, using the reserved `io.modelcontextprotocol/` prefix,
carries the validator:

| Key                              | Type     | Direction       | Meaning                                                                  |
| -------------------------------- | -------- | --------------- | ------------------------------------------------------------------------ |
| `io.modelcontextprotocol/digest` | `string` | server → client | Opaque deterministic digest of the definition of the primitive it is on. |

It is an opaque string. Clients **MUST** treat it as opaque and compare only for
equality; the value carries no parseable structure.

```json
{
  "name": "create_issue",
  "title": "Create issue",
  "inputSchema": {
    "type": "object",
    "properties": { "title": { "type": "string" } }
  },
  "_meta": {
    "io.modelcontextprotocol/digest": "sha256:0f1c…9ab2"
  }
}
```

### Where the digest appears

A server that emits per-primitive digests includes
`io.modelcontextprotocol/digest`:

- On each `Tool`, `Prompt`, `Resource`, and `ResourceTemplate` object returned by
  `tools/list`, `prompts/list`, `resources/list`, and
  `resources/templates/list` — in that primitive object's own `_meta`. This is the
  primary delivery path: digests arrive _in the list result_, one per enumerated
  primitive.
- On the result `_meta` of a single-primitive operation —
  `CallToolResult`, `GetPromptResult`, `ReadResourceResult` — where it is the
  **current** digest of the primitive that was acted on. This lets the client
  refresh its remembered digest after a call and notice drift even on a successful
  response.

It is intentionally **not** emitted as an aggregate over the whole surface and not
attached to unrelated results. The digest answers a question about one primitive;
list freshness and whole-surface discovery remain the domain of `ttlMs` and
`list_changed`.

Because every primitive type (`Tool`, `Prompt`, `Resource`, `ResourceTemplate`)
and every single-primitive result already defines an optional `_meta`, no
structural schema change is required. This SEP only **reserves the key** and its
meaning. The request-side key and error code below are the only additions.

### Determinism requirements

The digest is the load-bearing contract, so its computation is constrained. For a
given primitive:

1. **Pure function of the visible definition.** The digest **MUST** be computed
   solely from that primitive's definition as the requesting authorization context
   would observe it. It **MUST NOT** incorporate non-deterministic inputs such as
   timestamps, random salts, request IDs, per-instance identifiers, or map
   iteration order.
2. **Cross-instance stability.** All instances of a deployment serving the same
   definition of a primitive to the same authorization context **MUST** produce the
   same digest. Two replicas of the _same_ version cause no spurious mismatch; a
   replica of a _new_ version that changed the primitive produces a different
   digest.
3. **Sensitivity to any observable change.** The digest **MUST** change if any
   client-observable field of the primitive changes — name, title, description,
   input schema, output schema, annotations, icons, URI, MIME type, etc. Hashing
   only the name is insufficient: a redeploy that changes a tool's `inputSchema`
   while keeping its name **MUST** still change the digest.
4. **Collision resistance.** The digest **MUST** be produced by a
   collision-resistant function so a changed definition cannot map to an equal
   digest (which would silently hide the change). Servers **SHOULD** use SHA-256;
   non-cryptographic hashes (CRC, FNV, etc.) **MUST NOT** be used.
5. **Independent of pagination.** A primitive's digest depends only on that
   primitive, so it is identical regardless of which page of a paginated list the
   primitive appeared on.

### Recommended computation

So that independent implementations of the same logical server agree (and avoid
spurious churn behind a load balancer), servers **SHOULD** compute a primitive's
digest as: `"sha256:" + hex( SHA-256( RFC8785-canonical-JSON(primitive) ) )`, where
the canonical JSON is the primitive's full caller-visible definition serialized
with [RFC 8785 JSON Canonicalization](https://www.rfc-editor.org/rfc/rfc8785)
(sorted keys, no insignificant whitespace), **excluding** the `_meta` field itself.
Clients never need this recipe; it exists only so server operators and SDKs can
interoperate. The `"sha256:"` prefix is informational; clients **MUST NOT** parse
or depend on it and **MUST** compare the whole string for equality.

### Interaction with cache scope (public vs private)

A primitive's digest inherits the **`cacheScope`** of the result that carried it
([SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)):

- For a primitive delivered with `cacheScope: "public"` (identical for all callers),
  its digest is likewise public: it may be shared across callers and cached by
  shared gateways, proxies, and CDNs, and it will be identical for every caller.
- For a primitive delivered with `cacheScope: "private"` (filtered or
  user-specific), its digest is private: caches **MUST NOT** share it across
  authorization contexts, and clients **MUST** key their remembered digest by
  authorization context.

This makes the digest a drop-in companion to the existing caching model rather than
a parallel scoping concept: wherever a primitive may be cached, its digest may be
cached on exactly the same terms.

### Capability advertisement is an optional optimization

A server **MAY** advertise that it emits per-primitive digests, but a client
**MUST NOT** be required to check for the capability before relying on the field:

```typescript
export interface ServerCapabilities {
  // … existing fields …

  /**
   * OPTIONAL hint that the server emits `io.modelcontextprotocol/digest` on
   * caller-visible primitives and single-primitive results. Advertisement is an
   * optimization, not a precondition: clients SHOULD simply use the digest when
   * present and fall back to TTL/notifications when it is absent.
   */
  primitiveDigests?: {};
}
```

Consistent with treating server capabilities as an optional optimization rather
than a mandatory negotiation, the presence of `io.modelcontextprotocol/digest` on a
primitive is **self-describing**: a client that sees it uses it; a client that does
not see it falls back to TTL and/or notifications. A client **MAY** send
`expectedDigest` (below) without first confirming the capability and let the server
ignore it if unsupported. The capability exists only to let a client _know in
advance_ that the optimization is available; correctness never depends on it.

### Client requirements

1. Clients **MUST** treat the digest as opaque, comparing only for equality.
2. A client **SHOULD** retain, per `(server, authorization context)`, the digest of
   each primitive it caches from `*/list`. The authorization context is part of the
   key because private primitives are permission-filtered (see Security
   Implications).
3. When acting on a primitive whose digest it remembers, a client **MAY** include
   `io.modelcontextprotocol/expectedDigest` in the request `_meta` (see Reflection).
4. On any result carrying `io.modelcontextprotocol/digest` for a primitive the
   client caches, the client **SHOULD** update its remembered value. If it differs
   from the prior value, the client **MAY** replace the cached definition, diff it,
   surface the change to the user or model, or ignore it — but it is now _aware_.
5. A client **MUST NOT** infer anything from the absence of a digest when the server
   never indicated support; it simply relies on TTL/notifications as today.

### Reflection: optimistic conditional requests (client → server)

The digest is most useful flowing in both directions. A client **MAY** declare, on
a request that targets a specific primitive, which version it planned against:

| Key                                      | Type     | Direction       | Meaning                                                             |
| ---------------------------------------- | -------- | --------------- | ------------------------------------------------------------------- |
| `io.modelcontextprotocol/expectedDigest` | `string` | client → server | The digest of the target primitive the request was planned against. |

This is a transport-agnostic analogue of an HTTP `If-Match` precondition, scoped to
the single primitive being invoked. It is **opt-in**: a client that omits it gets
ordinary behavior. It is added to the request metadata:

```typescript
export interface RequestMetaObject extends MetaObject {
  // … existing reserved request keys …

  /**
   * OPTIONAL. The `io.modelcontextprotocol/digest` of the primitive this request
   * targets (e.g. the tool named in `tools/call`), as the client last observed
   * it. A server MAY treat this as an `If-Match` precondition and reject the
   * request with `DigestChangedError` if the primitive has since changed, or MAY
   * process it and return the current digest in the result `_meta`.
   */
  "io.modelcontextprotocol/expectedDigest"?: string;
}
```

When a request carries `expectedDigest`, the server **MAY** compare it to the
digest of the primitive it would currently serve the caller:

- If they **match**, the server processes the request normally.
- If they **differ**, the server **MAY** short-circuit and return a
  `DigestChangedError` (below) carrying the current digest, declining to execute
  against a contract the client no longer shares; **or** it **MAY** process the
  request anyway (e.g. for a version-tolerant or read-only operation) and return
  the current digest in the result `_meta`. Reflection is an enabler, not an
  obligation.

Servers **SHOULD** apply the precondition most aggressively to `tools/call`, where
executing under a changed `inputSchema`/`outputSchema` risks unintended side
effects or output the client cannot validate. Because the check happens _before_
execution, the server **terminates a stale call early** and hands the harness a
deterministic, machine-readable cue to re-fetch the primitive, re-plan, and
re-prompt the model with the updated contract — the "the server changed, redirect
the model" behavior that is otherwise impossible to deliver statelessly. Because
the precondition is per-primitive, an unrelated change elsewhere in the surface
does **not** trip a call to an unaffected tool.

#### New error: `DigestChangedError`

```typescript
/**
 * Error returned when a request carried an
 * `io.modelcontextprotocol/expectedDigest` that does not match the digest of the
 * target primitive the server would currently serve the caller, and the server
 * elected to reject rather than process the request against a changed contract.
 *
 * Analogous to HTTP 412 Precondition Failed. The client SHOULD re-fetch the
 * affected primitive, re-plan against the new definition, and retry with a new
 * JSON-RPC id.
 */
export const DIGEST_CHANGED = -32005;

export interface DigestChangedError extends Omit<Error, "code" | "data"> {
  code: typeof DIGEST_CHANGED;
  data: {
    /**
     * The current digest of the target primitive. The client SHOULD adopt this
     * as its expected digest after re-fetching the primitive's definition.
     */
    "io.modelcontextprotocol/digest": string;
  };
}
```

A client that receives `DigestChangedError` **MUST NOT** silently retry the
identical request; it **SHOULD** re-fetch the affected primitive, re-plan, and (if
still appropriate) retry with updated arguments and a **different** JSON-RPC `id`,
consistent with the existing tool-call retry rule. To avoid retry loops during a
rolling deploy, clients **SHOULD** bound retries and **MAY** fall back to issuing
the call without `expectedDigest` once re-synced.

#### Client failure modes (open / closed / prompt)

On a digest mismatch — whether discovered by the server (via `DigestChangedError`)
or by the client noticing a changed digest on a result — the client implementor
**MAY** choose its posture, and different clients legitimately differ:

- **Fail open** — proceed with the new definition (re-plan and continue). Suitable
  for low-risk, automatable flows.
- **Fail closed** — refuse to use a primitive whose contract changed mid-session.
  An ultra-sensitive client **MAY**, for example, hide tools whose digest changed
  until a human re-approves them.
- **Prompt** — surface the change to the user or model and let them decide.

This is deliberately a `MAY`: the protocol guarantees the _signal_ is available and
deterministic; policy belongs to the client.

### Optional: HTTP header mirroring for intermediaries and rolling upgrades

The digest lives in `_meta` (the JSON body) so it works over every transport,
including stdio. For the Streamable HTTP transport, a server **MAY** additionally
mirror the digest of a single-primitive operation into an HTTP header, and a client
**MAY** send `expectedDigest` as a request header, so that network intermediaries
(CDNs, proxies, gateways) can revalidate without parsing the body — in the spirit
of [SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)'s
header mirroring. Header mirroring is well defined only for **single-primitive**
requests/responses (`tools/call`, `prompts/get`, `resources/read`), where exactly
one digest applies; `*/list` responses enumerate many primitives and therefore keep
their per-primitive digests in the body.

This is what lets the validator survive **rolling upgrades within a still-fresh TTL
window**: even while a client is content to skip re-listing (its `ttlMs` has not
expired), the header lets an intermediary or the client itself observe — at call
time — that the targeted primitive's digest changed after a partial deploy, and
revalidate just that primitive. Whether to reuse standard `ETag`/`If-Match` headers
or a dedicated `Mcp-*` header is left as an open question.

### Interaction with TTL (SEP-2549)

The digest and `ttlMs` operate at different layers and compose:

- `ttlMs` is the **list freshness budget**: it governs when a client re-fetches a
  `*/list`. It is unchanged by this SEP.
- The per-primitive digest is the **call-time validator**: within a still-fresh TTL
  window, a client uses its cached list to _plan_ a call, and the echoed digest lets
  the server catch the case where _that specific primitive_ changed under the fresh
  budget — the deterministic gap TTL cannot close, now scoped precisely to the
  primitive actually used.

A client **MAY** also use a result-carried digest as a hint to re-list early (it is
already permitted to re-fetch before TTL expiry when it has reason to believe data
changed), but the digest does not replace or extend `ttlMs`.

### Interaction with notifications / subscriptions

The digest is the stateless, pull-side counterpart to push invalidation:

- A server **MAY** emit per-primitive digests with or without `listChanged`, and a
  client holding a `subscriptions/listen` stream may use both with no conflict.
- Consistent with the "capabilities as optional optimization" direction, a client
  need not pre-check a capability to benefit from either: it uses digests when
  present and may attempt a subscription and let the server report if unsupported.
- Any future consolidation of subscriptions into a single change-subscription RPC
  (the SEP-1442 direction) is the **push** side of the same problem and is out of
  scope here; the per-primitive digest deliberately requires no subscription at all.

### Message flow

```mermaid
sequenceDiagram
    participant H as Harness/Model
    participant C as Client
    participant S as Server

    C->>S: tools/list
    S-->>C: tools:[ create_issue {_meta.digest: "D1"}, … ], ttlMs
    Note over C: Cache create_issue, remember digest D1

    Note over S: New deployment changes create_issue inputSchema
    C->>S: tools/call create_issue (args) + expectedDigest "D1"
    Note over S: Live digest is now "D2"
    S-->>C: error DigestChangedError { data.digest: "D2" }
    Note over C: Stale contract — do not run against D1
    C->>S: tools/list  (re-sync just this primitive's definition)
    S-->>C: tools:[ create_issue {_meta.digest: "D2"}, … ]
    C->>H: tool contract changed; updated schema
    H->>C: re-planned call (new args)
    C->>S: tools/call create_issue (args') + expectedDigest "D2"
    S-->>C: { content:[…], _meta:{ digest: "D2" } }
```

## Rationale

### Why per-primitive rather than an aggregate surface digest?

An aggregate digest over the whole surface was considered. The advantage of an
aggregate is _discovery_: any response reveals that _something_ changed. But it
conflates two jobs — "should I re-list?" and "is this call still valid?" — and
invents a whole-surface synchronization concept that has no analogue in standard web
caching. A per-primitive digest instead maps cleanly onto an established pattern —
an **ETag per cacheable entity** — and keeps the validator's job tightly scoped to
the primitive actually being used. List-level discovery is already owned by
`ttlMs` (re-list when stale) and, optionally, `list_changed`. Splitting the
concerns this way means an unrelated change never trips a call to an unaffected
primitive, and the precondition is exactly as precise as it should be.

### Why a content digest rather than a server version string?

A server version string cannot represent **per-caller** permission filtering (two
callers on the same version can see different definitions of the same tool), is
prone to **false churn** (build metadata differs across a fleet; a config-only
change alters the surface without a version bump), and couples change detection to
release cadence rather than the observable definition. A content digest is exactly
stable when the definition is stable and changes exactly when it changes. Servers
**MAY** still expose a build version via `Implementation.version` for diagnostics;
it is simply not the change-detection signal.

### Embracing ETag semantics (and why the value lives in `_meta`)

This is intentionally ETag-like — an opaque validator compared for equality,
enabling `If-Match`-style conditional requests. The reason it is a dedicated
`io.modelcontextprotocol/digest` key in `_meta` rather than the HTTP `ETag` header
is twofold. First, MCP is transport-agnostic and must work over stdio, where no HTTP
headers exist; the signal must live in the body. Second, an HTTP `ETag` validates a
single HTTP response, but a `*/list` response carries _many_ primitives, each with
its own validator — one header cannot represent them. Keeping the per-primitive
digest in each primitive's `_meta` represents all of them naturally, while the
optional header mirroring (above) still offers the HTTP-native path for the
single-primitive operations where one `ETag`/`If-Match` does apply.

### Why capability advertisement is optional

Requiring a client to check a capability before using the digest would add a round
of negotiation for an additive, self-describing field. Following the principle that
server capabilities should be an optional optimization — a client should be able to
just _try_ an operation and let the server report if it is unsupported — the digest
is usable on sight and `expectedDigest` is safely ignorable by a server that does
not implement it. The capability flag remains only as an a-priori hint.

### Why reflect the digest back on requests?

Response-only detection is reactive: the client learns the primitive changed _after_
it has already issued a call against the stale contract. For `tools/call` that is
often too late — the tool may have executed a side effect, or returned
`structuredContent` the client now validates against the wrong `outputSchema`.
Echoing `expectedDigest` makes the call a precondition the server can evaluate
_before_ executing, the way HTTP `If-Match` prevents a lost update. It is strictly
opt-in, so simple clients pay nothing.

### Why this is the deployment story we never had

For "the server was redeployed," a per-primitive pull digest is easier to reason
about than `list_changed` for everyone involved: there is no connection to address,
no message queue to fan out across instances, and no need to invent a single change
instant for a gradual rollout. Each instance stamps the digest of the primitive it
serves; correctness needs no cross-instance coordination. This is precisely the
production-deployment case that GET streams, `list_changed`, and session revocation
each failed to solve in practice.

### Request bouncing during deploys

During a rolling deploy, old and new replicas may both serve traffic, so a client
may see a primitive's digest oscillate between old and new as requests land on
different instances. This is a _faithful_ reflection of reality — two definitions
are genuinely live — and resolves to one value once old instances drain. It is a
deployment/routing concern (standard connection draining and routing new connections
to new instances addresses it), is **out of scope** for MCP, and is not MCP internal
state. Strict reflection during this window can produce repeated
`DigestChangedError`s; the retry guidance above (bounded retries, fall back to
issuing without `expectedDigest` once re-synced) keeps it from becoming a loop.

## Backward Compatibility

This change is purely additive:

- Servers that do not emit the key behave exactly as today; clients fall back to TTL
  and/or notifications.
- Clients that do not understand the key ignore it, as `_meta` permits additional
  properties.
- No structural schema change is needed for the response side: every primitive type
  and single-primitive result already defines an optional `_meta`. The SEP reserves
  the `io.modelcontextprotocol/digest` key and its meaning.
- The request-side `io.modelcontextprotocol/expectedDigest` is optional and ignored
  by servers that do not implement reflection, so they process the request as today.
  `DigestChangedError` uses a new code (`-32005`) that does not collide with any
  existing error.
- The `primitiveDigests` capability is an optional hint; nothing requires it to be
  present, so its absence changes no existing behavior.

## Security Implications

- **A digest is exactly as private as the primitive it describes.** Its
  shareability follows the primitive's `cacheScope`: a `"public"` primitive's digest
  is shareable across callers (it leaks no more than the public definition already
  does); a `"private"` primitive's digest **MUST NOT** be shared across
  authorization contexts, and clients **MUST** key it by authorization context. This
  is identical to the confidentiality the caching utility already assigns to the
  primitive.
- **A digest is an information channel.** It reveals _that_ a specific primitive's
  visible definition changed and is stable per definition. An intermediary that can
  observe a victim's private digests could infer permission changes or fingerprint a
  tool. Servers and intermediaries **MUST** treat private digests with the same care
  as the underlying definitions.
- **Collision resistance is security-relevant.** With a non-collision-resistant
  function, a redeploy that swapped a benign primitive for a differently-behaving one
  could collide to the same digest and hide the change. Hence a cryptographic hash is
  required.
- **Not an integrity or authenticity mechanism.** The digest is unsigned and only
  helps an _honest_ server signal change. It does not protect against a malicious
  server that lies about (or fails to change) its digest. Clients **MUST NOT** treat
  a stable digest as a security guarantee about server behavior.
- **Reflection narrows a side-effect race.** Echoing `expectedDigest` lets an honest
  server refuse a `tools/call` whose schema changed out from under the caller,
  reducing the chance of executing a side-effecting tool under a contract the client
  did not agree to. This is a safety improvement, not a guarantee: it depends on a
  cooperating server, and a client **MUST NOT** rely on it to enforce authorization
  (the server's own per-request access checks remain authoritative).

## Reference Implementation

_No reference implementation yet._

---

## Open Questions

1. **Header mirroring shape.** For Streamable HTTP single-primitive operations,
   should the optional mirror reuse standard `ETag`/`If-Match` headers or a dedicated
   `Mcp-*` header, and how should it interact with SEP-2243's existing mirrored
   headers?
2. **Canonicalization recipe.** Should RFC 8785 canonicalization be normative (to
   guarantee cross-implementation agreement for the same logical server) or left
   server-defined (treating cross-instance agreement purely as an operator
   responsibility)?
3. **Resource content vs definition.** This SEP digests primitive _definitions_. The
   caching track also wants conditional reads of resource _content_ ("give me the
   resource only if changed since X"), which can change independently of the
   descriptor. Should content revalidation reuse this `_meta` ETag convention under a
   distinct key, or be a sibling proposal?
4. **Protocol-version interplay.** A protocol-version change can alter primitive
   schema shapes and therefore digests. Is "the digest changes on a version bump"
   acceptable (it is a real change to what the client observes), or should the digest
   be normalized against protocol version?
5. **Reflection scope.** Should `expectedDigest`/`DigestChangedError` be defined for
   all single-primitive methods (`tools/call`, `prompts/get`, `resources/read`) or
   begin with `tools/call`, where executing against a stale contract is most
   consequential?
6. **Deploy-time retry storms.** During a long rolling deploy a primitive's digest
   may oscillate, so strict reflection could cause repeated `DigestChangedError`s.
   What guidance (backoff, a "reflect once then proceed" mode, a grace window) best
   prevents pathological loops while preserving the safety benefit?
7. **Capability granularity.** Is a single `primitiveDigests` hint sufficient, or
   should support for request-side reflection be separately discoverable from
   support for response-side digests?

## Acknowledgments

Builds directly on the stateless/sessionless direction of SEP-2575 and SEP-2567, the
caching model of SEP-2549, the header-mirroring approach of SEP-2243, and the `_meta`
conventions of SEP-414. Shaped by Transports Working Group discussion of the Caching
& Optimization track — in particular feedback from Shaun Smith on per-primitive
ETags and conditional requests, and from Mark Roth on treating server capabilities
as an optional optimization and on the push-side subscription model.
