# Cross-SDK Analysis: Stateless vs Stateful in MCP

> Comparison of C#, Python, TypeScript, and Go MCP SDK implementations  
> Goal: Identify commonalities and differences to inform a standard definition

---

## Executive Summary

All four SDKs agree on the **fundamental concept**: stateless mode creates ephemeral, per-request sessions that cannot support server→client requests (sampling, elicitation, roots). However, they diverge significantly in **how they implement it**, **what they guard against**, and **how much the developer must do manually**.

**Key finding**: There is strong consensus on *what* stateless means, but no consensus on *how* to implement it. A standard should codify the "what" while allowing flexibility in the "how."

---

## 1. Universal Agreements (Shared by All 4 SDKs)

### ✅ Core Principle
All SDKs agree: **stateless mode means no persistent session between HTTP requests**.

| Shared Behavior | C# | Python | TypeScript | Go |
|---|:---:|:---:|:---:|:---:|
| Each request gets a fresh transport/session | ✅ | ✅ | ✅ | ✅ |
| Streamable HTTP is the transport | ✅ | ✅ | ✅ | ✅ |
| Session ID is absent or unused for routing | ✅ | ✅ | ✅ | ✅ |
| No persistent SSE stream (GET) | ✅ | ✅ | ✅ | ✅ |
| Tools work in stateless mode | ✅ | ✅ | ✅ | ✅ |
| Prompts work in stateless mode | ✅ | ✅ | ✅ | ✅ |
| Resources work in stateless mode | ✅ | ✅ | ✅ | ✅ |
| Completions work in stateless mode | ✅ | ✅ | ✅ | ✅ |
| Logging works (within request context) | ✅ | ✅ | ✅ | ✅ |
| Progress notifications work (within request) | ✅ | ✅ | ✅ | ✅ |

### ❌ Features Blocked in Stateless Mode
All SDKs agree these features **require** stateful mode:

| Blocked Feature | Reason |
|---|---|
| **Sampling** (server→client) | No persistent connection for client to respond |
| **Elicitation** (server→client) | No persistent connection for client to respond |
| **Roots listing** (server→client) | No persistent connection for client to respond |
| **Unsolicited notifications** | No GET SSE stream to deliver them |
| **SSE stream resumability** | No persistent session to resume |

### 🔀 Initialization Handling
All SDKs skip the normal `initialize`→`initialized` handshake in stateless mode by pre-populating session state:

| SDK | Mechanism |
|---|---|
| C# | Sets `ClientCapabilities = null`; uses `KnownClientInfo` option |
| Python | `InitializationState.Initialized` — starts as already initialized |
| TypeScript | New server per request; no init handshake required |
| Go | Peeks at request body; pre-sets `ServerSessionState` if no `initialize` message found |

---

## 2. Key Differences

### 2.1 Configuration Model

| SDK | Configuration | Explicit Flag? |
|---|---|:---:|
| **C#** | `HttpServerTransportOptions.Stateless = true` | ✅ Yes |
| **Python** | `StreamableHTTPSessionManager(stateless=True)` | ✅ Yes |
| **Go** | `StreamableHTTPOptions.Stateless = true` | ✅ Yes |
| **TypeScript** | `sessionIdGenerator: undefined` + manual per-request lifecycle | ❌ No |

**Gap**: TypeScript is the only SDK without an explicit `stateless` boolean. Stateless behavior is an emergent property of how the developer wires things up. This makes it harder to reason about and enforce.

### 2.2 Session Manager

| SDK | Built-in Session Manager | Stateless Lifecycle |
|---|---|---|
| **C#** | `StatefulSessionManager` (for stateful); custom handler for stateless | Automatic — framework creates/destroys per request |
| **Python** | `StreamableHTTPSessionManager` handles both modes | Automatic — manager creates/destroys per request |
| **Go** | `StreamableHTTPHandler` handles both modes | Automatic — handler defers `session.Close()` |
| **TypeScript** | ❌ None built-in | **Manual** — developer must create/destroy server per request |

**Gap**: TypeScript puts the entire session lifecycle burden on the developer. All other SDKs handle it automatically.

### 2.3 Runtime Guards for Blocked Features

| SDK | Guard Mechanism | Error Type |
|---|---|---|
| **C#** | `ClientCapabilities == null` check; throws `InvalidOperationException` | Framework exception |
| **Python** | Explicit `self._stateless` flag; raises `StatelessModeNotSupported` | **Dedicated exception class** |
| **Go** | Transport-level rejection; server→client requests fail immediately | Transport error |
| **TypeScript** | ❌ **No explicit guards** | Transport closed → generic error |

**Gap**: Only Python has a dedicated, named exception for stateless mode violations. C# uses an existing exception type. Go rejects at transport level. TypeScript has no guards at all — the failure is a generic transport error when the closed connection can't deliver the message.

**Recommendation for standard**: SDKs SHOULD provide explicit runtime errors when stateless-incompatible features are attempted, with a clear error message indicating that the feature requires stateful mode.

### 2.4 HTTP Route Handling

| SDK | GET route in stateless | DELETE route in stateless |
|---|---|---|
| **C#** | **Unmapped entirely** (no route registered) | **Unmapped entirely** |
| **Python** | Mapped but returns error/no-op | Mapped but returns error/no-op |
| **Go** | Returns **405 Method Not Allowed** with `Allow: POST` header | Mapped but effectively no-op (session may be nil) |
| **TypeScript** | **Developer manually returns 405** | **Developer manually returns 405** |

**Gap**: No consistent behavior. C# is strictest (routes don't exist). Go follows HTTP spec (405 + Allow header). Python keeps routes but they fail. TypeScript delegates to the developer entirely.

**Recommendation for standard**: Stateless servers SHOULD return 405 Method Not Allowed for GET and DELETE requests, with an `Allow: POST` response header (following RFC 9110 §15.5.6).

### 2.5 Session ID in Stateless Mode

| SDK | Session ID in Stateless |
|---|---|
| **C#** | Empty string (`""`) internally |
| **Python** | `None` |
| **Go** | **Optional — can have logical session IDs** for logging/tracing |
| **TypeScript** | Not generated |

**Gap**: Go uniquely allows session IDs in stateless mode for observability purposes. Other SDKs use absent/null/empty session IDs.

**Recommendation for standard**: Stateless servers MUST NOT send the `Mcp-Session-Id` header in responses. Servers MAY use internal session identifiers for logging/tracing purposes, but these MUST NOT be exposed to clients.

### 2.6 Change Notifications (ListChanged)

| SDK | ListChanged notifications in stateless |
|---|---|
| **C#** | **Skipped** — notification handlers not registered |
| **Python** | Not explicitly addressed |
| **Go** | Debounced and sent, but unlikely to reach any client |
| **TypeScript** | Server has no awareness of mode |

**Gap**: Only C# explicitly skips registering ListChanged handlers in stateless mode. Go still sends them (wastefully). This should be standardized.

### 2.7 Known Client Info (Pre-configuration)

| SDK | Pre-configure client capabilities? |
|---|---|
| **C#** | ✅ `McpServerOptions.KnownClientInfo` |
| **Python** | ❌ |
| **Go** | Partial — `ProtocolVersion` from header |
| **TypeScript** | ❌ |

**Gap**: Only C# allows pre-configuring expected client capabilities for stateless mode. This is useful when a server knows its clients and wants to tailor responses.

### 2.8 Performance Optimizations for Stateless

| SDK | Stateless-specific optimization |
|---|---|
| **C#** | `ScopeRequests = false` (uses `HttpContext.RequestServices` directly) |
| **Python** | None noted |
| **Go** | `SchemaCache` — caches JSON schemas to avoid repeated reflection |
| **TypeScript** | None noted |

---

## 3. Proposed Standard Definition

Based on the cross-SDK analysis, here is a proposed standard:

### 3.1 Stateless Mode MUST

1. **Not maintain session state between HTTP requests** — each POST creates an independent processing context
2. **Not send the `Mcp-Session-Id` response header** — clients MUST NOT expect session continuity
3. **Support all read-only MCP operations**: tools (list, call), prompts (list, get), resources (list, read, templates), completions, ping
4. **Support in-request notifications**: logging and progress notifications within the scope of a POST response
5. **Reject server→client requests** with a clear error: sampling, elicitation, roots listing
6. **Return 405 Method Not Allowed** for GET and DELETE HTTP methods (with `Allow: POST` header)

### 3.2 Stateless Mode SHOULD

1. **Provide explicit runtime errors** when stateless-incompatible features are attempted (not generic transport failures)
2. **Skip the `initialize`/`initialized` handshake** — servers should accept requests without prior initialization
3. **Accept `initialize` requests** if sent — for clients that don't know the server is stateless
4. **Not register change notification handlers** — there's no one to notify
5. **Support the `Mcp-Protocol-Version` header** for version negotiation without initialization

### 3.3 Stateless Mode MAY

1. Use internal session identifiers for logging/tracing (but not expose them to clients)
2. Pre-configure expected client capabilities via server options
3. Implement caching optimizations for repeated schema generation
4. Support `initialize`/`initialized` for compatibility with clients that always send them

### 3.4 Stateful Mode MUST

1. **Generate and send `Mcp-Session-Id` header** after initialization
2. **Validate `Mcp-Session-Id` on subsequent requests** — reject unknown session IDs
3. **Support the full `initialize`→`initialized` handshake**
4. **Support GET for SSE streaming** (standalone server→client channel)
5. **Support DELETE for session termination**
6. **Support all MCP features** including server→client requests (sampling, elicitation, roots)

### 3.5 Stateful Mode SHOULD

1. Implement session timeout/idle cleanup
2. Support SSE stream resumability via event stores
3. Send ListChanged notifications when tools/prompts/resources are modified
4. Provide session migration support for graceful upgrades

---

## 4. Summary Matrix

| Dimension | C# | Python | Go | TypeScript |
|---|---|---|---|---|
| **Explicit `stateless` flag** | ✅ | ✅ | ✅ | ❌ |
| **Built-in session manager** | ✅ | ✅ | ✅ | ❌ |
| **Auto per-request lifecycle** | ✅ | ✅ | ✅ | ❌ (manual) |
| **Dedicated stateless exception** | ❌ (uses existing) | ✅ (`StatelessModeNotSupported`) | ❌ (transport-level) | ❌ (no guards) |
| **GET → 405 in stateless** | ✅ (unmapped) | ⚠️ (partial) | ✅ | ⚠️ (manual) |
| **DELETE → 405 in stateless** | ✅ (unmapped) | ⚠️ (partial) | ⚠️ (no-op) | ⚠️ (manual) |
| **Skips init handshake** | ✅ | ✅ | ✅ | ✅ |
| **Blocks sampling** | ✅ | ✅ | ✅ | ⚠️ (implicit) |
| **Blocks elicitation** | ✅ | ✅ | ✅ | ⚠️ (implicit) |
| **Blocks roots** | ✅ | ✅ | ✅ | ⚠️ (implicit) |
| **Skips ListChanged** | ✅ | ❌ | ❌ | ❌ |
| **Stateless perf optimization** | ✅ (scope) | ❌ | ✅ (cache) | ❌ |
| **Pre-configure client info** | ✅ | ❌ | Partial | ❌ |
| **Session ID in stateless** | `""` | `None` | Optional | Not generated |

---

## 5. Recommendations for Standard

### High Priority (Strong consensus, should standardize immediately)
1. ✅ **Stateless = no persistent session** — universal agreement
2. ✅ **Server→client requests blocked** — universal agreement
3. ✅ **Tools/prompts/resources/completions always work** — universal agreement
4. ⚠️ **GET/DELETE return 405** — Go does this correctly; standardize it

### Medium Priority (Partial consensus, needs discussion)
5. ⚠️ **Explicit `stateless` configuration flag** — 3/4 SDKs have it; TypeScript should add one
6. ⚠️ **Explicit runtime guards** — 3/4 SDKs have them; TypeScript should add guards
7. ⚠️ **No `Mcp-Session-Id` in stateless responses** — Go's "optional for logging" approach needs resolution
8. ⚠️ **Built-in session manager** — 3/4 SDKs have one; TypeScript should consider adding one

### Lower Priority (SDK-specific innovations worth evaluating)
9. 💡 **Dedicated exception type** (Python's `StatelessModeNotSupported`) — clear DX, worth standardizing
10. 💡 **Known client info** (C#'s `KnownClientInfo`) — useful for pre-configured deployments
11. 💡 **Schema caching** (Go's `SchemaCache`) — performance optimization for stateless
12. 💡 **Skip ListChanged registration** (C# approach) — avoids waste in stateless mode
