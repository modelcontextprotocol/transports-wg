# Python MCP SDK: Stateless vs Stateful Mode

> Analysis of [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) (`main` branch, March 2026)

## Configuration

### Via StreamableHTTPSessionManager (low-level)

```python
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

session_manager = StreamableHTTPSessionManager(
    app=server,
    stateless=True,  # default: False
)
```

### Via FastMCP (high-level)

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("My Server")
mcp.run(transport="streamable-http")  # stateless configured via session manager
```

### Key parameters affected by mode

| Parameter | Stateful | Stateless |
|---|---|---|
| `stateless` | `False` (default) | `True` |
| `mcp_session_id` | UUID hex string per session | `None` — no session ID |
| `event_store` | Optional (enables resumability) | Forced to `None` |
| `session_idle_timeout` | Optional (e.g. 1800s) | **RuntimeError** if set |
| `retry_interval` | Optional (SSE polling) | Ignored (no event store) |

## Core Difference

| Aspect | Stateful (default) | Stateless |
|---|---|---|
| **Session tracking** | `Mcp-Session-Id` header; sessions stored in `_server_instances` dict | No session ID; fresh transport per request |
| **Session lifetime** | Persists across requests until idle timeout, DELETE, or shutdown | Transport created → request handled → `terminate()` called |
| **Initialization state** | Starts as `NotInitialized`, progresses through handshake | Starts as `Initialized` (skips init handshake) |
| **Load balancing** | Requires session affinity (sticky sessions) | No affinity needed — any instance can serve any request |
| **Service scope** | Single `Server.run()` loop per session; shared state | New `Server.run()` per request; no shared state |

## HTTP Endpoints

| Endpoint | Stateful | Stateless |
|---|---|---|
| `POST /` | ✅ All JSON-RPC messages; session correlated via `Mcp-Session-Id` | ✅ All JSON-RPC messages (each request independent) |
| `GET /` | ✅ Standalone SSE stream for unsolicited server→client messages | ✅ Mapped but **no persistent stream** (transport terminates after request) |
| `DELETE /` | ✅ Explicit session termination | Returns **405 Method Not Allowed** (`mcp_session_id` is `None`) |

> **Note:** Unlike the C# SDK which unmaps GET/DELETE routes entirely in stateless mode, the Python SDK keeps them mapped but they effectively no-op or error since there's no session to interact with.

## Feature Support

| Feature | Stateful | Stateless |
|---|---|---|
| **Tools** (list, call) | ✅ | ✅ |
| **Prompts** (list, get) | ✅ | ✅ |
| **Resources** (list, read, templates, subscribe) | ✅ | ✅ |
| **Completions** | ✅ | ✅ |
| **Logging** (server→client notifications) | ✅ | ✅ |
| **Progress notifications** | ✅ | ✅ |
| **Ping** | ✅ | ✅ |
| **Sampling** (`create_message`) | ✅ | ❌ `StatelessModeNotSupported` |
| **Elicitation** (`elicit_form` / `elicit_url`) | ✅ | ❌ `StatelessModeNotSupported` |
| **Roots** (`list_roots`) | ✅ | ❌ `StatelessModeNotSupported` |
| **Unsolicited notifications** (e.g. `tools/list_changed`) | ✅ Via GET SSE stream | ⚠️ No persistent stream; effectively dropped |
| **SSE resumability** (`EventStore` + `Last-Event-ID`) | ✅ When `event_store` provided | ❌ No event store in stateless mode |
| **Session idle timeout** | ✅ Via `session_idle_timeout` param | ❌ `RuntimeError` if configured |
| **Tasks** (experimental) | ✅ | ⚠️ Depends on implementation; session-level checks may block |
| **JSON response mode** (`is_json_response_enabled`) | ✅ | ✅ |

## Why These Restrictions?

The `StatelessModeNotSupported` exception docstring explains it clearly:

> *"Server-to-client requests (sampling, elicitation, list_roots) are not supported in stateless HTTP mode because there is no persistent connection for bidirectional communication."*

In stateless mode, each request creates a fresh transport that's terminated immediately after handling. There's no long-lived session to route server→client requests back through. Any response to a server-initiated request might arrive at a completely different process.

## Key Implementation Details

### StatelessModeNotSupported Exception
**File:** `src/mcp/shared/exceptions.py`

```python
class StatelessModeNotSupported(RuntimeError):
    def __init__(self, method: str):
        super().__init__(
            f"Cannot use {method} in stateless HTTP mode. "
            "Stateless mode does not support server-to-client requests. "
            "Use stateful mode (stateless_http=False) to enable this feature."
        )
```

Unlike the C# SDK (which uses `InvalidOperationException` and guards via `ClientCapabilities == null`), the Python SDK has a **dedicated exception type** for this error.

### Session Manager Dispatch
**File:** `src/mcp/server/streamable_http_manager.py`

```python
async def handle_request(self, scope, receive, send):
    if self.stateless:
        await self._handle_stateless_request(scope, receive, send)
    else:
        await self._handle_stateful_request(scope, receive, send)
```

**Stateless path:**
1. Creates `StreamableHTTPServerTransport(mcp_session_id=None, event_store=None)`
2. Starts `Server.run(..., stateless=True)` in a new task
3. Handles the HTTP request
4. Calls `transport.terminate()` immediately after

**Stateful path:**
1. Checks `Mcp-Session-Id` header
2. If existing session → routes to its transport
3. If new → creates transport with UUID session ID, stores in `_server_instances`
4. Manages idle timeout via `anyio.CancelScope`

### ServerSession Initialization Skip
**File:** `src/mcp/server/session.py`

```python
def __init__(self, ..., stateless: bool = False):
    self._stateless = stateless
    self._initialization_state = (
        InitializationState.Initialized if stateless
        else InitializationState.NotInitialized
    )
```

In stateless mode, the session starts pre-initialized — the client still sends an `initialize` request but the server doesn't enforce the handshake ordering.

### Guards in ServerSession Methods

Each server→client request method checks `self._stateless`:

```python
async def create_message(self, ...):   # sampling
    if self._stateless:
        raise StatelessModeNotSupported(method="sampling")

async def list_roots(self):
    if self._stateless:
        raise StatelessModeNotSupported(method="list_roots")

async def elicit_form(self, ...):
    if self._stateless:
        raise StatelessModeNotSupported(method="elicitation")

async def elicit_url(self, ...):
    if self._stateless:
        raise StatelessModeNotSupported(method="elicitation")
```

## Comparison with C# SDK

| Aspect | C# SDK | Python SDK |
|---|---|---|
| **Config property** | `HttpServerTransportOptions.Stateless` | `StreamableHTTPSessionManager(stateless=...)` |
| **Session ID** | Empty string internally | `None` |
| **Error type** | `InvalidOperationException` | `StatelessModeNotSupported` (dedicated) |
| **Guard mechanism** | `ClientCapabilities == null` check | Explicit `self._stateless` flag |
| **GET/DELETE routes** | Unmapped entirely (405) | Mapped but effectively no-op/error |
| **SSE legacy endpoints** | `/sse` and `/message` disabled | N/A (Python SDK doesn't have legacy SSE in stateless) |
| **Change notifications** | Notification handlers not registered | No special handling; dropped silently if no GET stream |
| **Idle timeout** | Unused in stateless | `RuntimeError` if configured with stateless |
| **Session migration** | `ISessionMigrationHandler` (stateful only) | Not implemented |
| **Web framework** | ASP.NET Core | Starlette/ASGI |
| **Blocked features** | Sampling, elicitation, roots, tasks, unsolicited notifications | Sampling, elicitation, roots (same core set) |

## When to Use Which

| Use Case | Mode |
|---|---|
| Horizontally scaled API behind a load balancer | **Stateless** |
| Single-instance or session-affinity deployment needing full MCP features | **Stateful** |
| Server needs sampling, elicitation, or roots from client | **Stateful** |
| Server pushes unsolicited notifications (e.g., dynamic tool lists) | **Stateful** |
| Simple tool-serving server (no server→client requests needed) | **Stateless** ✅ simplest |
| Need SSE resumability for unreliable connections | **Stateful** + `EventStore` |
