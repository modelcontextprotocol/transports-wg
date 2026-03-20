# Go MCP SDK: Stateless vs Stateful Mode

> Analysis of [modelcontextprotocol/go-sdk](https://github.com/modelcontextprotocol/go-sdk) (`main` branch, March 2026)

## Configuration

```go
handler := mcp.NewStreamableHTTPHandler(func(*http.Request) *mcp.Server {
    return server
}, &mcp.StreamableHTTPOptions{
    Stateless: true,
})
```

### Key parameters affected by mode

| Parameter | Stateful | Stateless |
|---|---|---|
| `Stateless` | `false` (default) | `true` |
| `SessionTimeout` | Optional idle timeout | Ignored (sessions are ephemeral) |
| `EventStore` | Optional (enables resumability) | Usable but typically not set |
| `JSONResponse` | Optional | Optional |
| `GetSessionID` (on `ServerOptions`) | Generates unique IDs | May return empty string (no header) |

## Core Difference

| Aspect | Stateful (default) | Stateless |
|---|---|---|
| **Session tracking** | `Mcp-Session-Id` header; sessions stored in `StreamableHTTPHandler.sessions` map | Sessions created per request and closed via `defer session.Close()` |
| **Session lifetime** | Persists across requests; optional `SessionTimeout` for idle cleanup | Ephemeral — created, used, and closed within a single HTTP request |
| **Initialization** | Normal `initialize`→`initialized` handshake | Pre-initialized with default `ServerSessionState` (skips handshake if not in body) |
| **Load balancing** | Requires session affinity | No affinity needed |
| **Server→client requests** | ✅ Supported | ❌ Rejected — "no way for the client to respond" |

## HTTP Endpoints

| Endpoint | Stateful | Stateless |
|---|---|---|
| `POST /` | ✅ All JSON-RPC messages | ✅ All JSON-RPC messages (ephemeral session) |
| `GET /` | ✅ Standalone SSE stream for server→client messages | ❌ **405 Method Not Allowed** (with `Allow: POST` header) |
| `DELETE /` | ✅ Session termination (closes session, returns 204) | ⚠️ Mapped but no-ops (session may be nil in stateless) |

## Feature Support

| Feature | Stateful | Stateless |
|---|---|---|
| **Tools** (list, call) | ✅ | ✅ |
| **Prompts** (list, get) | ✅ | ✅ |
| **Resources** (list, read, templates, subscribe) | ✅ | ✅ |
| **Completions** | ✅ | ✅ |
| **Logging** (server→client notifications in request context) | ✅ | ✅ (within POST response) |
| **Progress notifications** | ✅ | ✅ (within POST response) |
| **Sampling** (server→client request) | ✅ | ❌ Rejected at transport level |
| **Elicitation** (server→client request) | ✅ | ❌ Rejected at transport level |
| **Roots** (server→client request) | ✅ | ❌ Rejected at transport level |
| **Unsolicited notifications** | ✅ Via GET SSE stream or request context | ⚠️ Only within POST request context (no GET stream) |
| **SSE resumability** (`EventStore`) | ✅ When configured | Technically possible but no persistent session to resume |
| **Session timeout** | ✅ Via `SessionTimeout` option | N/A (sessions are ephemeral) |
| **Change notifications** (tools/prompts/resources changed) | ✅ Sent to all sessions | ⚠️ Sessions are ephemeral; notifications may not reach anyone |

## Key Implementation Details

### StreamableHTTPHandler — The Central Controller

**File:** `mcp/streamable.go`

The `StreamableHTTPHandler` is an `http.Handler` that serves as the session manager (unlike TypeScript which has no built-in manager). Key behavior:

```go
func (h *StreamableHTTPHandler) ServeHTTP(w http.ResponseWriter, req *http.Request) {
    // ... security checks (DNS rebinding, CORS, Content-Type) ...

    // GET in stateless mode → 405
    if req.Method == http.MethodGet && h.opts.Stateless {
        w.Header().Set("Allow", "POST")
        http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
        return
    }

    // Session lookup
    sessionID := req.Header.Get("Mcp-Session-Id")
    sessInfo := h.sessions[sessionID]
    if sessInfo == nil && !h.opts.Stateless {
        http.Error(w, "session not found", http.StatusNotFound)
        return
    }
    // ... create new session if needed ...
}
```

### Stateless Session Pre-initialization

When creating a stateless session, the Go SDK peeks at the request body to check for `initialize`/`initialized` messages. If not present, it creates a pre-initialized `ServerSessionState`:

```go
if stateless {
    state := new(ServerSessionState)
    if !hasInitialize {
        state.InitializeParams = &InitializeParams{
            ProtocolVersion: protocolVersion,
        }
    }
    if !hasInitialized {
        state.InitializedParams = new(InitializedParams)
    }
    state.LogLevel = "info"
    connectOpts = &ServerSessionOptions{State: state}
}
```

This means stateless sessions **can** still process normal `initialize` requests — they're just not required.

### Server→Client Request Blocking

The `StreamableServerTransport` has a `Stateless` field. When set to `true`, server→client requests (sampling, elicitation, roots) are rejected because the transport knows there's no way for the client to respond:

> "A stateless server does not validate the Mcp-Session-Id header, and uses a temporary session with default initialization parameters. Any server→client request is rejected immediately as there's no way for the client to respond."

### Session ID and Stateless Interaction

Uniquely among the SDKs, the Go SDK notes that stateless servers **may still have logical session IDs**:

```go
// From the distributed example:
// Distributed MCP servers must be stateless, because there's no guarantee
// that subsequent requests for a session land on the same backend. However,
// they may still have logical session IDs, as can be seen with verbose logging.
```

The session ID in stateless mode is generated but not used for session routing — it's purely for logging/tracing purposes.

### SchemaCache for Stateless Performance

The Go SDK includes a `SchemaCache` option specifically designed for stateless deployments:

```go
// SchemaCache, if non-nil, caches JSON schemas to avoid repeated
// reflection. This is useful for stateless server deployments where
// a new [Server] is created for each request.
SchemaCache *SchemaCache
```

This is unique to the Go SDK — other SDKs don't have this optimization.

### Change Notification Debouncing

The Go SDK debounces change notifications (tools/prompts/resources list changed) with a 10ms delay. In stateless mode, these notifications are still sent but may not reach any client since sessions are ephemeral.

## Comparison with Other SDKs

| Aspect | Go | C# | Python | TypeScript |
|---|---|---|---|---|
| **Config flag** | `StreamableHTTPOptions.Stateless` | `HttpServerTransportOptions.Stateless` | `StreamableHTTPSessionManager(stateless=...)` | `sessionIdGenerator: undefined` |
| **Session manager** | `StreamableHTTPHandler` | `StatefulSessionManager` | `StreamableHTTPSessionManager` | ❌ Manual |
| **GET route in stateless** | 405 Method Not Allowed | 405 (unmapped) | Mapped but no persistent stream | 405 (manual) |
| **Init skip** | Peeks body; pre-initializes if needed | Pre-initialized | `InitializationState.Initialized` | N/A |
| **Schema caching** | ✅ `SchemaCache` for stateless perf | ❌ | ❌ | ❌ |
| **Session IDs in stateless** | Optional (for logging) | Empty string | `None` | Not generated |
| **Idle timeout** | `SessionTimeout` option | `IdleTimeout` (2hr default) | `session_idle_timeout` | Manual |

## When to Use Which

| Use Case | Mode |
|---|---|
| Distributed servers behind a load balancer | **Stateless** (`Stateless: true`) |
| Single-instance or session-affinity deployment | **Stateful** (default) |
| Server needs sampling/elicitation/roots | **Stateful** |
| High-throughput stateless with schema reflection | **Stateless** + `SchemaCache` |
| Simple tool server, no server→client requests | **Stateless** ✅ simplest |
