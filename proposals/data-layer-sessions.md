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
    "_meta": {
      "mcp/session": {
        "id": "sess-a1b2c3d4e5f6",
        "expiry": "2026-02-23T14:30:00Z",
        "data": { "title": "Code Review Session" }
      }
    }
  }
}
```

### `session/delete`

```jsonc
// Client → Server
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "session/delete",
  "params": { "id": "sess-a1b2c3d4e5f6" }
}

// Server → Client
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "deleted": true,
    "_meta": { "mcp/session": null }
  }
}
```

### `session/list`

```jsonc
// Client → Server
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "session/list"
}

// Server → Client
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "sessions": [
      {
        "id": "sess-a1b2c3d4e5f6",
        "expiry": "2026-02-23T14:30:00Z",
        "data": { "title": "Code Review Session" }
      }
    ]
  }
}
```

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

### Revocation

A server revokes a session by returning `"mcp/session": null`:

```jsonc
{
  "_meta": { "mcp/session": null }
}
```

The client SHOULD clear its stored cookie and MAY re-establish a session.

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

**Open question:** Is `-32002` the right code? Should we define a
named error code in the spec?

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

## Open Questions Summary

1. **Versioning** — integer in capability vs. spec-level versioning?
2. **Error code** — `-32002` or a named constant?
3. **Selective enforcement** — how should servers declare per-tool requirements?
4. **HTTP header mirroring** — should `mcp/session` also appear as a header?
5. **Cookie size** — what constraints on the `data` field?
6. **Security** — signing/encryption of session tokens? Server-side only
   vs. client-verifiable?
7. **Fork/branch** — should `session/fork` be in scope, or deferred?
8. **Relationship to MRTR** — how does this interact with the multi-round-trip
   requests track's need for state passthrough?

## Prior Art

- **RFC 6265** (HTTP Cookies) — foundation for cookie semantics
- **Sessions Track Brief** (this repo) — working group discussion context
- **MRTR Track Brief** (this repo) — overlapping state-passthrough needs
- **`fast-agent` experimental sessions** — working prototype of this design
  over both stdio and Streamable HTTP transports
