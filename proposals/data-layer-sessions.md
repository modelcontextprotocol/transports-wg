# Data-Layer Sessions for MCP

> **Status:** Early Draft  
> **Date:** 2026-02-23  
> **Track:** transport-wg/sessions  
> **Author(s):** Shaun Smith  

## Purpose

This is a **discussion starter**, not a finished design. It proposes a
minimal set of JSON-RPC API shapes for application-level sessions in MCP,
decoupled from the transport layer. The goal is to give the working group
something concrete to react to.

The core problem: MCP currently ties session identity to the transport
connection (`Mcp-Session-Id` header for Streamable HTTP, implicit for stdio).

The proposal is to introduce a session concept within the MCP Data Layer, 
using a lightweight _cookie_ style mechanism. 

> **See also:** [`data-layer-sessions-api-shapes.jsonc`](data-layer-sessions-api-shapes.jsonc)
> — flat quick-reference of all wire shapes.

## Reference Packages (for review)

To make discussion concrete, this proposal folder includes two small
Python reference packages that implement the data-layer session model:

- [`data-layer-sessions-client-python/`](data-layer-sessions-client-python/) —
  client-side cookie jar + request/response `_meta` handling.
- [`data-layer-sessions-server-python/`](data-layer-sessions-server-python/) —
  server-side session issuer + `session/create`, `session/resume`,
  `session/delete` handler registration.

These are intentionally compact and self-contained so reviewers can inspect
implementation behavior alongside wire shapes.

A simple Client/Server reference implementation is available.

## Design Principles

1. **Transport-agnostic.** Works identically over stdio and HTTP.
2. **Server-authoritative lifecycle, flexible payload ownership.** The server
   issues, updates, accepts/rejects, and revokes session tokens. The client
   echoes them. Session `data` may be server-defined, client-carried, or a
   hybrid, depending on application policy. (Adapted cookie semantics per
   RFC 6265.)
2. **Opt-in.** Sessions are discovered via capability negotiation during
   `initialize`. Servers that don't need sessions don't advertise them.
2. **Incremental.** A server can require sessions globally, per-tool, or not
   at all.

## Phase Scope

To keep this proposal straightforward for initial review, this draft splits
session functionality into two phases:

- **Phase 1 (in scope for this draft):** `session/create`, `session/resume`,
  `session/delete`, and cookie echo/revocation semantics.
- **Phase 2 (deferred):** `session/list` and `session/recover` semantics.

We can evaluate the core lifecycle first, then expand into
recovery/discovery workflows if we think necessary.

## Use Cases

The following are concrete scenarios from experimental client/server
integrations (including `fast-agent` + demo MCP servers) where data-layer
sessions are immediately useful:

1. **Global session gatekeeping**
   - Some servers require session establishment before any tool call.
   - Example: policy-enforced systems that need an explicit server-issued
     identity before tool execution.

2. **Selective per-tool session policy**
   - Public tools can run without a session, while stateful/sensitive tools
     require one.
   - Example: `public_echo` remains open; `session_counter_inc` requires a
     valid session cookie.

2. **Session-scoped stateful tools**
   - Tools maintain per-session state across multiple calls, either in
     server-side storage or in cookie-carried `data` payloads.
   - Example: notebook append/read/clear and hash KV verify workflows.

2. **Client-carried user preferences (lightweight state transfer)**
   - Clients can carry non-sensitive, low-volume preferences in session
     `data`, and servers can apply them without additional lookup calls.
   - Typical examples: `language`, `timezone`, display format preferences.

2. **Reconnect + resume semantics (same cookie, new transport)**
   - Client disconnects/reconnects and resumes server state by reusing
     `mcp/session` cookie.
   - This is the core value beyond transport-local `Mcp-Session-Id`.

2. **Session revocation + re-establishment**
   - Server revokes cookie (`mcp/session = null`); client clears local cookie
     and can create/select a new session.

2. **Operator-driven session control**
   - Runtime operators can create/resume/select/clear sessions explicitly
     (e.g., for debugging, incident response, or workflow recovery).

These use cases suggest sessions are not only a transport concern; they are a
practical application-layer primitive needed for real tool orchestration.

When using client-carried state in `data`, implementations should treat it as
advisory input unless explicitly trusted by policy.

## Capability Advertisement

During `initialize`, a server that supports sessions includes an
`experimental` capability:

```jsonc
// Server → Client (InitializeResult)
{
  "capabilities": {
    "experimental": {
      "session": {
        "features": ["create", "resume", "delete"]
      }
    }
  }
}
```

`features` lists the `session/*` methods the server supports. A minimal
server might only support `["create"]`.

No per-capability `version` field is included — no existing MCP capability
uses one. Versioning is handled at the protocol level via `protocolVersion`
during `initialize`. If the session capability shape needs breaking changes
in the future, those would be gated on a new protocol version.

## Session Lifecycle Methods

### `session/create`

The `session/create` result returns the session object in the result body
(like any other method result) **and** sets the cookie in `_meta` for the
echo cycle. See [Session Cookie: Placement](#session-cookie-placement) for
the design discussion on where the cookie lives.

```jsonc
// Client → Server
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "session/create",
  "params": {
    "hints": {
      "label": "my-agent-workspace",
      "data": { "title": "Code Review Session" }
    }
  }
}

// Server → Client
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "id": "sess-a1b2c3d4e5f6",
    "expiry": "2026-02-23T14:30:00Z",
    "data": { "title": "Code Review Session" },
    "_meta": {
      "mcp/session": {
        "id": "sess-a1b2c3d4e5f6",
        "expiry": "2026-02-23T14:30:00Z"
      }
    }
  }
}
```

The result body contains the full session object (for the client to inspect).
The `_meta` cookie contains the opaque token the client echoes on subsequent
requests — the server controls what goes in the cookie and may include less
data than the result body.

### `session/resume`

`session/resume` re-activates an existing session by ID and returns the
canonical cookie payload for subsequent echo.

```jsonc
// Client → Server
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "session/resume",
  "params": {
    "id": "sess-a1b2c3d4e5f6"
  }
}

// Server → Client
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "id": "sess-a1b2c3d4e5f6",
    "expiry": "2026-02-23T14:30:00Z",
    "data": { "title": "Code Review Session" },
    "_meta": {
      "mcp/session": {
        "id": "sess-a1b2c3d4e5f6",
        "expiry": "2026-02-23T14:30:00Z"
      }
    }
  }
}
```

If the requested session cannot be resumed, the server SHOULD return an
error (e.g., session not found / invalid / expired).

### `session/delete`

```jsonc
// Client → Server
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "session/delete",
  "params": { "id": "sess-a1b2c3d4e5f6" }
}

// Server → Client
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "deleted": true,
    "_meta": { "mcp/session": null }
  }
}
```

See [Revocation via `null`](#revocation-via-null) for the design discussion
on using `null` as a signal.

## Session Cookie Echo

Once a session is established, the client includes the session cookie in
`_meta` on every request. The server echoes (or updates) it in every
response.

```jsonc
// Client → Server (tools/call with session)
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "notebook_append",
    "arguments": { "text": "remember this" },
    "_meta": {
      "mcp/session": {
        "id": "sess-a1b2c3d4e5f6"
      }
    }
  }
}

// Server → Client
{
  "jsonrpc": "2.0",
  "id": 4,
  "result": {
    "content": [{ "type": "text", "text": "appended" }],
    "_meta": {
      "mcp/session": {
        "id": "sess-a1b2c3d4e5f6",
        "expiry": "2026-02-23T15:00:00Z"
      }
    }
  }
}
```

### Session Cookie: Placement

> **Implementation note:** The reference packages included with this
> proposal (`data-layer-sessions-client-python/`,
> `data-layer-sessions-server-python/`) are **overlay libraries** that
> layer on top of an unmodified MCP Python SDK. They inject and extract
> `_meta["mcp/session"]` by hand, without requiring any SDK changes.
> This is deliberate — it allows reviewers to evaluate the wire-level
> behaviour immediately, without gating on SDK or schema modifications.
>
> If this proposal progresses to a first-class spec feature, the
> expectation is that the session cookie would migrate from a convention
> key to a **named property** on `RequestMetaObject` and `MetaObject`,
> with typed support in the SDKs (see Path A below).

The cookie echo mechanism uses `_meta` to carry session state across all
request/response pairs. This raises a design question about how the cookie
key is defined.

The MCP schema today has **one** protocol-defined key in `_meta`:
`progressToken`, defined as a **named property** on `RequestMetaObject`.
This proposal uses a **convention key** (`"mcp/session"`) in the open
`_meta` bag instead.

Both approaches are schema-legal. The trade-offs:

| Approach | Pro | Con |
|---|---|---|
| **A: Named property** — add `session` to `RequestMetaObject` and `MetaObject` schema definitions, like `progressToken` | Schema-validatable; typed in SDKs; consistent with `progressToken` precedent | Requires schema changes; tighter coupling to spec release cycle |
| **B: Convention key** — use `"mcp/session"` as an opaque key in the `_meta` bag (current proposal + demos) | No schema changes needed; works immediately as `experimental`; extensible; demos can run on stock SDK | No schema validation; novel use of the extensibility bag for a protocol-level concept |

The `mcp/` prefix is **reserved for MCP spec use** per the `MetaObject`
naming rules — so `"mcp/session"` is valid as a spec-defined key. Third
parties MUST NOT define keys under the `mcp/` prefix.

**Recommended path:** Start with **Path B** (convention key under
`experimental`) for prototyping and interoperability testing, then promote
to **Path A** (named schema property) when the feature moves from
experimental to first-class. The reference packages are structured to make
this migration straightforward — the `_meta` injection/extraction is
isolated in `model.py` in both client and server packages.

### Revocation via `null`

A server revokes a session by returning `"mcp/session": null`:

```jsonc
{
  "_meta": { "mcp/session": null }
}
```

The client SHOULD clear its stored cookie and MAY re-establish a session.

**Design note:** The `MetaObject` schema is `"type": "object"` with no
constraints on property value types, so `null` is technically valid. However,
no existing MCP usage puts `null` in `_meta` — this would be a novel
pattern. Alternatives:

- **Option A (current):** `null` signals revocation. Simple, expressive.
- **Option B:** Omit `"mcp/session"` entirely to signal revocation. Ambiguous
  — absence could mean "no change" rather than "revoked."
- **Option C:** Use a dedicated `session/revoke` notification. Explicit, but
  adds a method.

## Error Handling

A server that requires a session for a particular operation returns a
JSON-RPC error:

```jsonc
{
  "jsonrpc": "2.0",
  "id": 5,
  "error": {
    "code": -32043,
    "message": "Session required. Call session/create or session/resume first."
  }
}
```

### Error Code Selection

The code `-32043` is in the JSON-RPC implementation-defined server error
range (`-32000` to `-32099`). The following codes in this range are already
allocated or claimed in the MCP ecosystem:

| Code | Name | Where | Crosses wire? |
|---|---|---|---|
| `-32000` | `CONNECTION_CLOSED` | Python SDK | No (SDK-internal) |
| `-32001` | `REQUEST_TIMEOUT` | Python SDK, TS SDK | No (SDK-internal) |
| `-32002` | Resource not found | Spec docs (`server/resources.mdx`) | Yes |
| `-32042` | `URL_ELICITATION_REQUIRED` | Schema (`schema.ts`), both SDKs | Yes (formal) |

The `-3204x` neighbourhood is used for **protocol-level conditions
requiring structured client action** (URL elicitation, session
establishment). This contrasts with `-3200x` which the SDKs have
informally claimed for internal transport/connection conditions, and
`-32002` which the spec docs already use for resource-not-found errors.

If adopted, `-32043` would be defined as a named constant
(e.g. `SESSION_REQUIRED`) in `schema.ts` alongside
`URL_ELICITATION_REQUIRED`, and propagated to both SDKs.

**Open question:** Should the error carry structured `data` (like
`URLElicitationRequiredError` does with its `elicitations` array)?
For example, the error `data` could include available session features
or a hint about which method(s) to call.

## Selective Enforcement

Servers MAY require sessions for all tools, some tools, or no tools. The
mechanism for advertising which tools require sessions is left open:

- Option A: Servers just return `-32043` and clients react.
- Option B: A `sessionRequired` field in tool metadata.
- Option C: A server-level policy declaration in capabilities.

**Open question:** Which approach (or combination) best serves both
human developers and LLM-driven tool selection?

## Interaction with Transport-Level Sessions

Streamable HTTP currently has `Mcp-Session-Id` for transport routing. This
proposal operates at a different layer:

| Concern | Transport (`Mcp-Session-Id`) | Data-layer (`mcp/session`) |
|---|---|---|
| Scope | Single connection | Across connections |
| Set by | Transport layer | Application logic |
| Survives reconnect | No | Yes |
| Works over stdio | N/A | Yes |

### Trajectory: Data-Layer Sessions Supersede Transport Sessions

As MCP moves toward stateless transports, the transport-level
`Mcp-Session-Id` increasingly functions as a **routing hint** rather than
a session identity. This proposal's data-layer session ID is the natural
replacement for application-level session semantics.

The intended evolution:

1. **Today:** `Mcp-Session-Id` is both a routing key and a (fragile)
   session identity. Losing the transport connection loses the session.
2. **With this proposal:** `mcp/session` carries durable session identity
   in the JSON-RPC payload. `Mcp-Session-Id` is demoted to a
   transport-routing concern only.
2. **Future:** The data-layer session ID is mirrored into an HTTP header
   (e.g. `Mcp-Session-Id` itself, or a new `Mcp-Session` header) so that
   load balancers and proxies can route on it without body parsing —
   following the pattern established by
   **[SEP-2243: HTTP Header Standardization](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)**.

SEP-2243 defines the mechanism for surfacing JSON-RPC payload fields as
HTTP headers (`Mcp-Method`, `Mcp-Tool-Name`, etc.) and includes validation
rules for header/body consistency. The data-layer session ID is a natural
candidate for the same treatment: the client would include the session ID
both in `_meta["mcp/session"]` and in an HTTP header, enabling
infrastructure routing without deep packet inspection.

**Open question:** Should the header reuse `Mcp-Session-Id` (replacing
the transport meaning) or introduce a new header name (e.g.
`Mcp-Data-Session`) to avoid ambiguity during the transition?

## Implementation-Informed Considerations

Early implementation work suggests the following considerations (non-normative):

- **Capability gating works in practice.** Clients can ignore unknown
  experimental capabilities and continue normal MCP operation.
- **Auto-create + explicit controls both matter.** Automatic `session/create`
  supports low-friction startup, while explicit controls (`create/resume/delete/clear`)
  support operator workflows and debugging.
- **Client-side cookie persistence is valuable.** A local cookie jar enables
  reconnect bootstrap and reduces redundant `session/create` calls.
- **Identity-aware storage helps multi-server environments.** Keying by server
  identity (when available) reduces collisions and supports disconnected views.
- **Invalidation tracking is useful.** Marking rejected cookies as invalidated
  avoids repeatedly selecting known-bad session IDs during resume.
- **Expiry is advisory unless enforced.** Demo servers stamp `expiry` metadata,
  but enforcement policy remains server-defined.

These considerations do **not** lock in protocol choices; they provide
practical guidance for SEP scope and interoperability testing.

## Open Questions Summary

1. **Error code** — `-32043` (proposed) or a different code? Formal error code registry needed? Structured `data` payload?
2. **Selective enforcement** — how should servers declare per-tool requirements?
3. **HTTP header mirroring** — should `mcp/session` also appear as a header?
4. **SEP-2243 alignment** — should the data-layer session ID be mirrored
   into an HTTP header following the SEP-2243 pattern? If so, reuse
   `Mcp-Session-Id` or new header name?
5. **Cookie size** — what constraints on the `data` field?
6. **Security** — signing/encryption of session tokens? Server-side only
   vs. client-verifiable?
7. **Phase 2 shape** — how should `session/list` and `session/recover` be
   specified once Phase 1 stabilizes?
8. **Relationship to MRTR** — how does this interact with the multi-round-trip
   requests track's need for state passthrough?
9. **Cookie placement** — named `_meta` property (like `progressToken`) or
    convention key (`"mcp/session"`)? See [Placement](#session-cookie-placement).
10. **Revocation signal** — `null` value, key absence, or dedicated method?
    See [Revocation](#revocation-via-null).
11. **Client persistence semantics** — should local cookie jars / resume behavior
    be guidance-only, or should minimal interoperability expectations be defined?

## Prior Art

- **RFC 6265** (HTTP Cookies) — foundation for cookie semantics
- **Sessions Track Brief** (this repo) — working group discussion context
- **MRTR Track Brief** (this repo) — overlapping state-passthrough needs
- **[SEP-2243: HTTP Header Standardization](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)** —
  defines the pattern for mirroring JSON-RPC fields into HTTP headers for
  infrastructure routing; directly relevant for surfacing session IDs to
  load balancers
- **`fast-agent` experimental sessions** — working prototype of this design
  over both stdio and Streamable HTTP transports, including jar-based resume and
  operator session controls
