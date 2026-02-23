# Data-Layer Sessions for MCP

> **Status:** Strawman  
> **Date:** 2026-02-23  
> **Track:** Sessions  
> **Author(s):** Shaun Smith  

## Purpose

This is a **discussion starter**, not a finished design. It proposes a
minimal set of JSON-RPC API shapes for application-level sessions in MCP,
decoupled from the transport layer. The goal is to give the working group
something concrete to react to.

The core problem: MCP currently ties session identity to the transport
connection (`Mcp-Session-Id` header for Streamable HTTP, implicit for stdio).
When a connection drops, application state is lost. Servers that need
multi-turn state — scratch-pads, sandboxes, conversation context — have no
standard way to offer it.

> **See also:** [`data-layer-sessions-api-shapes.jsonc`](data-layer-sessions-api-shapes.jsonc)
> — flat quick-reference of all wire shapes.

## Design Principles

1. **Transport-agnostic.** Works identically over stdio and HTTP.
2. **Server-authoritative.** The server issues, updates, and revokes session
   tokens. The client echoes them. (Adapted cookie semantics per RFC 6265.)
3. **Opt-in.** Sessions are discovered via capability negotiation during
   `initialize`. Servers that don't need sessions don't advertise them.
4. **Incremental.** A server can require sessions globally, per-tool, or not
   at all.

## Capability Advertisement

During `initialize`, a server that supports sessions includes an
`experimental` capability:

```jsonc
// Server → Client (InitializeResult)
{
  "capabilities": {
    "experimental": {
      "session": {
        "version": 1,
        "features": ["create", "list", "delete"]
      }
    }
  }
}
```

`features` lists the `session/*` methods the server supports. A minimal
server might only support `["create"]`.

**Open question:** Should `version` be a single integer, or should this
use the spec's existing versioning approach?

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

### `session/list`

Follows the standard MCP pagination pattern (`cursor` / `nextCursor`),
consistent with `tools/list`, `resources/list`, `prompts/list`, etc.

```jsonc
// Client → Server (first page)
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "session/list"
}

// Client → Server (subsequent page)
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "session/list",
  "params": {
    "cursor": "eyJvZmZzZXQiOjEwfQ=="
  }
}

// Server → Client
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "sessions": [
      {
        "id": "sess-a1b2c3d4e5f6",
        "expiry": "2026-02-23T14:30:00Z",
        "data": { "title": "Code Review Session" }
      }
    ],
    "nextCursor": "eyJvZmZzZXQiOjEwfQ=="
  }
}
```

When no `nextCursor` is present, there are no more results. The `params`
object is optional on the first request (following `PaginatedRequestParams`).

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
| **B: Convention key** — use `"mcp/session"` as an opaque key in the `_meta` bag (current proposal) | No schema changes needed; works immediately as `experimental`; extensible | No schema validation; novel use of the extensibility bag for a protocol-level concept |

The `mcp/` prefix is **reserved for MCP spec use** per the `MetaObject`
naming rules — so `"mcp/session"` is valid as a spec-defined key. Third
parties MUST NOT define keys under the `mcp/` prefix.

**Open question:** If this moves from `experimental` to a first-class spec
feature, should the cookie become a named property (Path A)? Or is the
convention-key approach (Path B) sufficient given that `_meta` is explicitly
designed as an extensibility point?

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
    "code": -32002,
    "message": "Session required. Call session/create first."
  }
}
```

The code `-32002` is in the JSON-RPC server-defined range (`-32000` to
`-32099`). MCP already uses `-32042` for `URL_ELICITATION_REQUIRED`. If
adopted, this would need a named constant (e.g. `SESSION_REQUIRED`).

**Open question:** Is `-32002` the right code? Should the error carry
structured `data` (like `URLElicitationRequiredError` does with its
`elicitations` array)?

## Selective Enforcement

Servers MAY require sessions for all tools, some tools, or no tools. The
mechanism for advertising which tools require sessions is left open:

- Option A: A `sessionRequired` field in tool metadata.
- Option B: Servers just return `-32002` and clients react.
- Option C: A server-level policy declaration in capabilities.

**Open question:** Which approach (or combination) best serves both
human developers and LLM-driven tool selection?

## Interaction with Transport-Level Sessions

Streamable HTTP already has `Mcp-Session-Id` for transport routing. This
proposal operates at a different layer:

| Concern | Transport (`Mcp-Session-Id`) | Data-layer (`mcp/session`) |
|---|---|---|
| Scope | Single connection | Across connections |
| Set by | Transport layer | Application logic |
| Survives reconnect | No | Yes |
| Works over stdio | N/A | Yes |

The two are complementary. A load balancer can route on `Mcp-Session-Id`
while the application maintains state via `mcp/session`.

**Open question:** Should `mcp/session` be mirrored into an HTTP header
for routing affinity? If so, what are the size constraints?

## Schema Compatibility Notes

This proposal was reviewed against the MCP draft schema
(`schema/draft/schema.json`, DRAFT-2026-v1). Key compatibility points:

- **Method naming** follows `{namespace}/{verb}` (`session/create`,
  `session/list`, `session/delete`), consistent with `tools/call`,
  `resources/read`, `tasks/cancel`.
- **`experimental` capability** is `Record<string, object>` with
  `additionalProperties: true` — the proposed shape is valid.
- **`_meta` on requests** (`RequestMetaObject`) and **results**
  (`MetaObject`) are both open objects — arbitrary keys are allowed.
- **`Result`** has `"additionalProperties": {}` — custom fields like
  `deleted`, `sessions`, `id`, `expiry` are valid.
- **`session/list`** uses `PaginatedRequestParams` / `nextCursor`, matching
  all other list methods.
- **If formalized**, each method would need the standard 4-definition tuple
  (`*Request`, `*RequestParams`, `*Result`, `*ResultResponse`) and
  registration in the `ClientRequest` / `ServerResult` union types.

## Open Questions Summary

1. **Versioning** — integer in capability vs. spec-level versioning?
2. **Error code** — `-32002` or a named constant? Structured `data` payload?
3. **Selective enforcement** — how should servers declare per-tool requirements?
4. **HTTP header mirroring** — should `mcp/session` also appear as a header?
5. **Cookie size** — what constraints on the `data` field?
6. **Security** — signing/encryption of session tokens? Server-side only
   vs. client-verifiable?
7. **Fork/branch** — should `session/fork` be in scope, or deferred?
8. **Relationship to MRTR** — how does this interact with the multi-round-trip
   requests track's need for state passthrough?
9. **Cookie placement** — named `_meta` property (like `progressToken`) or
   convention key (`"mcp/session"`)? See [Placement](#session-cookie-placement).
10. **Revocation signal** — `null` value, key absence, or dedicated method?
    See [Revocation](#revocation-via-null).

## Prior Art

- **RFC 6265** (HTTP Cookies) — foundation for cookie semantics
- **Sessions Track Brief** (this repo) — working group discussion context
- **MRTR Track Brief** (this repo) — overlapping state-passthrough needs
- **`fast-agent` experimental sessions** — working prototype of this design
  over both stdio and Streamable HTTP transports
