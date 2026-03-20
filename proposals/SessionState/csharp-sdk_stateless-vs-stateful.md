# MCP C# SDK: Stateless vs Stateful Mode
## Configuration
Set via `HttpServerTransportOptions.Stateless` (default: `false`):
```csharp
builder.Services.AddMcpServer()
    .WithHttpTransport(options => options.Stateless = true);
```
## Core Difference
| Aspect | Stateful (default) | Stateless |
|---|---|---|
| **Session ID** | `Mcp-Session-Id` header on every response; tracked in `StatefulSessionManager` | No session ID; empty string internally |
| **Session lifetime** | Persists across requests; managed by idle timeout (default 2hr) | One session created **per HTTP request**, then discarded |
| **Load balancing** | Requires session affinity (sticky sessions) | No affinity needed — any instance can serve any request |
| **Service scope** | New DI scope per request (configurable) | Uses `HttpContext.RequestServices` directly — scoped services come from ASP.NET Core request scope |
## HTTP Endpoints
| Endpoint | Stateful | Stateless |
|---|---|---|
| `POST /` | ✅ All JSON-RPC messages | ✅ All JSON-RPC messages (each request is independent) |
| `GET /` | ✅ Unsolicited server→client SSE stream | ❌ **Not mapped** (405) |
| `DELETE /` | ✅ Session termination | ❌ **Not mapped** (405) |
| `GET /sse` (legacy SSE) | ✅ Mapped | ❌ **Not mapped** (404) |
| `POST /message` (legacy SSE) | ✅ Mapped | ❌ **Not mapped** (404) |
## Feature Support
| Feature | Stateful | Stateless |
|---|---|---|
| **Tools** (list, call) | ✅ | ✅ |
| **Prompts** (list, get) | ✅ | ✅ |
| **Resources** (list, read, templates) | ✅ | ✅ |
| **Completions** | ✅ | ✅ |
| **Logging** (server→client in response) | ✅ | ✅ |
| **Progress notifications** (in response) | ✅ | ✅ |
| **Sampling** (server→client request) | ✅ | ❌ `InvalidOperationException` |
| **Elicitation** (server→client request) | ✅ | ❌ `InvalidOperationException` |
| **Roots** (server→client request) | ✅ | ❌ `InvalidOperationException` |
| **Tasks** (async task management) | ✅ | ❌ `InvalidOperationException` |
| **Unsolicited notifications** (e.g. `tools/changed`) | ✅ Auto-registered on collection changes | ❌ Not registered; `SendNotificationAsync` throws |
| **Client capabilities** | ✅ Populated from `initialize` | ❌ **Always `null`** — server cannot know client capabilities |
| **Session migration** (`ISessionMigrationHandler`) | ✅ Cross-instance restore | ❌ N/A |
| **SSE resumability** (`EventStreamStore` + `Last-Event-ID`) | ✅ | ❌ Rejected with 400 |
| **Polling** (`EnablePollingAsync`) | ✅ | ❌ `InvalidOperationException` |
## Why These Restrictions?
All disabled features share one trait: they require **server→client communication outside the POST response**. In stateless mode, responses to server-initiated requests (sampling, elicitation, roots) might arrive at a different process. Unsolicited notifications have no open GET stream to write to. Since the server doesn't track sessions, it can't correlate follow-up messages.
## Key Implementation Details
- **`StreamableHttpServerTransport.Stateless`** — transport-level flag that guards `SendMessageAsync()`, `HandleGetRequestAsync()`, and `HandlePostRequestAsync()` for server→client requests
- **`McpServerImpl` constructor** (line 102) — skips registering `ToolListChanged`/`PromptListChanged`/`ResourceListChanged` notification handlers when stateless
- **`ClientCapabilities` = `null`** in stateless mode — the guard used by `ThrowIfSamplingUnsupported()`, `ThrowIfRootsUnsupported()`, `ThrowIfElicitationUnsupported()`, and `ThrowIfTasksUnsupported()`
- **`McpServerOptions.KnownClientInfo`** — can pre-populate client info for stateless servers that encode knowledge in the session ID
## When to Use Which
| Use Case | Mode |
|---|---|
| Horizontally scaled API behind a load balancer | **Stateless** |
| Single-instance or session-affinity deployment needing full MCP features | **Stateful** |
| Server needs to request sampling/elicitation/roots from client | **Stateful** |
| Server pushes unsolicited notifications (e.g., dynamic tool lists) | **Stateful** |
| Simple tool-serving server (no server→client requests needed) | **Stateless** ✅ simplest