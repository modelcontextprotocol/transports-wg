# TypeScript MCP SDK: Stateless vs Stateful Mode

> Analysis of [modelcontextprotocol/typescript-sdk](https://github.com/modelcontextprotocol/typescript-sdk) (`main` branch, March 2026)

## Configuration

### Stateless mode — Manual transport wiring

The TypeScript SDK does **not** have a built-in `stateless` boolean flag. Instead, stateless behavior is achieved by setting `sessionIdGenerator: undefined` on `NodeStreamableHTTPServerTransport` and creating a **new server + transport per request**:

```typescript
// From examples/server/src/simpleStatelessStreamableHttp.ts
app.post('/mcp', async (req, res) => {
    const server = getServer();  // new server per request
    const transport = new NodeStreamableHTTPServerTransport({
        sessionIdGenerator: undefined  // no session ID = stateless
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
    res.on('close', () => {
        transport.close();
        server.close();
    });
});
```

### Stateful mode — Session manager handles routing

```typescript
const transport = new NodeStreamableHTTPServerTransport({
    sessionIdGenerator: () => randomUUID(),  // generates session IDs
    eventStore: new InMemoryEventStore(),     // optional resumability
});
```

### Key architectural difference

Unlike C#, Python, and Go — which have a `stateless: boolean` property on a session manager or transport options — the TypeScript SDK uses **the absence of `sessionIdGenerator`** to signal stateless mode. The developer is responsible for wiring up the per-request lifecycle manually.

## Core Difference

| Aspect | Stateful | Stateless |
|---|---|---|
| **Session tracking** | `Mcp-Session-Id` header; session map maintained | No session ID; `sessionIdGenerator: undefined` |
| **Session lifetime** | Persists across requests; managed by developer code | New server + transport per HTTP request; closed after response |
| **Wiring** | Built-in session map in transport | **Manual**: developer creates/destroys server per request |
| **Load balancing** | Requires session affinity | No affinity needed |

## HTTP Endpoints

| Endpoint | Stateful | Stateless |
|---|---|---|
| `POST /mcp` | ✅ All JSON-RPC messages | ✅ All JSON-RPC messages (fresh server each time) |
| `GET /mcp` | ✅ Standalone SSE stream | ❌ **Developer returns 405** manually |
| `DELETE /mcp` | ✅ Session termination | ❌ **Developer returns 405** manually |

> **Key difference**: The TypeScript SDK does NOT automatically disable GET/DELETE routes. The stateless example manually returns 405 for these methods. This is left entirely to the application developer.

## Feature Support

| Feature | Stateful | Stateless |
|---|---|---|
| **Tools** (list, call) | ✅ | ✅ |
| **Prompts** (list, get) | ✅ | ✅ |
| **Resources** (list, read, templates) | ✅ | ✅ |
| **Completions** | ✅ | ✅ |
| **Logging** (via `ctx.mcpReq.log()`) | ✅ | ✅ (within request context) |
| **Progress notifications** | ✅ | ✅ (within request context) |
| **Sampling** (server→client request) | ✅ | ⚠️ **No explicit guard** — would fail at transport level |
| **Elicitation** (server→client request) | ✅ | ⚠️ **No explicit guard** — would fail at transport level |
| **Roots** (server→client request) | ✅ | ⚠️ **No explicit guard** — would fail at transport level |
| **Unsolicited notifications** | ✅ Via GET SSE stream | ❌ No GET stream available |
| **SSE resumability** (`EventStore`) | ✅ When event store provided | ❌ No event store in stateless pattern |
| **Session timeout** | Developer-managed | N/A (transport closed per request) |

## Why No Explicit Guards?

Unlike C# (`InvalidOperationException`) and Python (`StatelessModeNotSupported`), the TypeScript SDK has **no runtime guards** that throw when attempting sampling/elicitation/roots in stateless mode. Instead:

1. The transport is closed after each request, so there's no persistent connection for server→client requests
2. Any attempt to send a server→client request would fail because the transport is already closed
3. The failure mode is a transport error rather than a clear "stateless mode not supported" error

This is a **significant difference** from other SDKs — the TypeScript SDK relies on the developer understanding what won't work, rather than enforcing it.

## Key Implementation Details

### `NodeStreamableHTTPServerTransport`

The transport class is the core building block. Key configuration:

- **`sessionIdGenerator`**: Function returning a session ID string, or `undefined` for stateless
- **`eventStore`**: Optional `EventStore` for SSE resumability
- **`onsessioninitialized`**: Callback after initialization handshake

When `sessionIdGenerator` is `undefined`:
- No `Mcp-Session-Id` header is sent in responses
- The transport doesn't validate session IDs on incoming requests
- No session state is maintained between requests

### No Session Manager

Unlike C# (`StatefulSessionManager`), Python (`StreamableHTTPSessionManager`), and Go (`StreamableHTTPHandler`), the TypeScript SDK **does not have a built-in session manager**. Session lifecycle is managed by the application code:

- In stateful mode: the developer typically maintains a `Map<string, ServerSession>` 
- In stateless mode: the developer creates and destroys everything per request

### McpServer class

The `McpServer` class has no awareness of stateless vs stateful mode. It's a pure protocol handler. The distinction is entirely at the transport layer.

## Comparison with Other SDKs

| Aspect | TypeScript | C# | Python | Go |
|---|---|---|---|---|
| **Stateless flag** | `sessionIdGenerator: undefined` | `Stateless = true` | `stateless=True` | `Stateless: true` |
| **Explicit property** | ❌ No boolean flag | ✅ | ✅ | ✅ |
| **Session manager** | ❌ Manual | ✅ `StatefulSessionManager` | ✅ `StreamableHTTPSessionManager` | ✅ `StreamableHTTPHandler` |
| **Runtime guards** | ❌ None | ✅ `InvalidOperationException` | ✅ `StatelessModeNotSupported` | ✅ Rejected at transport |
| **GET/DELETE disabling** | ❌ Manual 405s | ✅ Routes unmapped | ✅ Effectively no-ops | ✅ Returns 405 |
| **Per-request lifecycle** | ✅ Manual | ✅ Automatic | ✅ Automatic | ✅ Automatic |

## When to Use Which

| Use Case | Mode |
|---|---|
| Horizontally scaled, no session affinity | **Stateless** (set `sessionIdGenerator: undefined`, new server per request) |
| Full MCP features with persistent sessions | **Stateful** (set `sessionIdGenerator`, manage session map) |
| Server needs sampling/elicitation/roots | **Stateful** |
| Simple tool server behind a load balancer | **Stateless** ✅ simplest |
