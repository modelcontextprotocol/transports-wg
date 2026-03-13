# Data-Layer Sessions for MCP

> **Status:** Early Draft  
> **Date:** 2026-02-23  
> **Track:** transport-wg/sessions  
> **Author(s):** Shaun Smith

## Abstract

This proposal introduces application level sessions within the MCP Data Layer. Sessions are created by the Client, and allow the Server to send to the Client an opaque state token that will be sent back for each relevant request.

This proposal should be reviewed alongside SEP-1442. It is designed to align with stateless capability discovery and move session semantics into the MCP data layer. Deprecation or removal of legacy transport-level session establishment remains dependent on SEP-1442 (including the removal of `initialization` handshake).

## Motivation

MCP Sessions are currently either implicit (STDIO), or constructed as a side effect of the transport connection (Streamable HTTP). 

Migrating sessions to the MCP data layer allows MCP applications to handle sessions as part of their domain logic, decoupled from the transport layer. This enables predictable session semantics, especially for Hosts that handle multiple "threads" of context within the application. The ability for MCP Servers to allocate resources on a per-session basis, or be able to provide rich functionality without server-side storage makes MCP suitable for increasingly sophisticated and scaled deployments. 


## Use Cases and Scope

### Scope

The current Transport specification defines sessions as follows: 

> An MCP “session” consists of logically related interactions between a client and a server, beginning with the initialization phase.

With the removal of the `initalization` phase and associated lifecycle semantics, data-lyer sessions are scoped as follows:

Sessions allow Clients and Servers to bind a sequence of MCP requests into an application-defined context recognized by the Server. Sessions provide contextual association, not snapshot semantics. A session can scope:
 - processing state across multiple operations;
 - server-managed resources or allocations associated with that context;
 - subscriptions and delivery of server-initiated messages related to that context; and

Sessions may influence how the Server evaluates requests and responses, but it does not provide a guarantee of MCP Protocol State, including:
- Tool Lists
- Prompt Lists
- Resource Availability.

Examples:

- processing state across multiple operations;
  - Entries in to a journal via an `add` tool
- server-managed resources or allocations associated with that context;
  - A tool to create a remote sandbox that adds  a `resource` entry which allows reading log tails from a specific URI.
- subscriptions and delivery of server-initiated messages related to that context
  - Tool or Prompt list cache invalidation notifications

Existing `list_changed` notifications scoped to the Session continue to function as cache invalidation hints and not state transitions.

### Use Cases

Below are some sample use-cases where a session abstraction makes sense:

- Shopping Cart. Maintaining integrity between different Chat Threads/Conversations.
- Contextual Documentation Retrieval, Conversational Subagent. A Server that adjusts its Tool Call Results based on earlier queries to avoid repetition of content.
- Playwright Testing Server. Being able to manage multiple parallel sessions without confusion.
- Managed Runtime Environment (sandbox). Allocating a stateful runtime environment to allow the LLM to coordinate and execute code and instructions.

## Specification

### User Interaction Model

Sessions are designed to be **application-driven**, with host applications determining how and when to establish sessions based on their need.

It is normally expected that applications will establish one session per context window, but this is not required. 

MCP Servers may wish to offer capabilities in a mixture of authentication and session modalities. 

### Capabilities

Servers that support sessions MUST declare the `sessions` capability:

```json
{
  "capabilities": {
    "sessions": {}
  }
}
```

> For testing purposes MCP Clients that support sessions declare an `experimental/sessions` capability to simplify testing.

### Protocol Messages

#### Creating Sessions

Clients begin a session with an MCP Server by calling `sessions/create`.

**Request:**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "sessions/create"
}
```

**Response**:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "session": {
      "sessionId": "sess-a1b2c3d4e5f6",
      "expiresAt": "2026-02-27T15:30:00Z",
      "state": "bGFuZ3VhZ2U9ZW4="
    },
  }
}
```

The Client **MUST NOT** send `io.modelcontextprotocol/session` with the sessions/create request.

The Client **MUST** securely associate retained sessions with the issuing Server. The Client will typically establish identity through a mixture of _connection target_ and _user identity_. In practice, that identity will typically be derived from configuration details such as server URL/origin, authentication context, and user/account identity.

`expiresAt` is a hint, and may be updated by the Server in future responses. The Host **MAY** use the `expiresAt` to indicate potentially stale sessions to the User. 

`state` **MUST** be retained by the Client and sent with future requests for that session.

#### Using Sessions

To use a Session the Client request includes SessionMetadata in `_meta["io.modelcontextprotocol/session"]`:

1. The Server MUST treat that sessionId as the session context for processing the request.
1. The `sessionId` in the response MUST exactly match the sessionId from the request.
1. The receiver MUST NOT substitute, rotate, or rewrite `sessionId` in the response.

**Request:**

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "search_code",
    "arguments": {
      "query": "def fizz_buzz()"
    },
    "_meta": {
      "io.modelcontextprotocol/session": {
        "sessionId": "sess-a1b2c3d4e5f6",
        "state": "bGFuZ3VhZ2U9ZW4="
      }
    }
  }
}
```

**Response:**

```json
{
  "jsonrpc": "2.0",
  // JSON-RPC RequestId is used for session association
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Found 3 matches."
      }
    ],
  }
}
```

#### Updating Session Metadata

Servers **MAY** update Session Metadata by including _meta["io.modelcontextprotocol/session"] in a response to a Client request:

**Response:**

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Found 3 matches."
      }
    ],
    "_meta": {
      "io.modelcontextprotocol/session": {
        "sessionId": "sess-a1b2c3d4e5f6",
        "state": "bGFuZ3VhZ2U9cHl0aG9u",
        "expiresAt": "2026-03-31T23:59:00Z"
      }
    }
  }
}
```

1. The Client **MUST** attempt to update the `state` value if updated by the Server. See note on [Ordering](#session-update-sequencing))
1. Servers **MUST NOT** include session metadata updates in notifications.
1. The Client **MAY** update the `expiresAt` value if updated by the Server.

#### Receiving Notifications

Clients can subscribe to notifications associated with one or more sessions using `messages/listen`. 

#### Receiving Notifications

Clients subscribe to server-initiated notifications using `messages/listen`. 

A `messages/listen` request is scoped to one of:

- **Single Session** — receives notifications relevant to that session.
- **Global** — receives broadcast notifications **not** scoped to any session.

The transport determines how those messages are delivered after registration. This proposal defines the logical scoping rules, not a transport-specific streaming mechanism.

##### Opening a Notification Listener

**Request (Session Scoped):**
```json
{
  "jsonrpc": "2.0",
  "id": 10,
  "method": "messages/listen",
  "params": {
    "_meta": {
      "io.modelcontextprotocol/session": {
        "sessionId": "sess-a1b2c3d4e5f6",
        "state": "bGFuZ3VhZ2U9ZW4="
      }
    }
  }
}
```

**Request (Global):**

```json
{
  "jsonrpc": "2.0",
  "id": 11,
  "method": "messages/listen",
  "params": {}
}
```

The server confirms the stream is open with a `notifications/messages/listen` notification as the **first event**:

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/messages/listen",
}
```

Subsequent events on this stream are notifications and server-to-client requests scoped to that session. For example, a resource update:

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/resources/updated",
  "params": {
    "uri": "file:///project/config.yaml"
  }
}
```


Global listeners receive **only** broadcast notifications that are not scoped to any session — for example, `notifications/tools/list_changed`. Session-scoped notifications such as resource updates are **never** delivered on a global listener.

##### Interaction with Resource Subscriptions

`messages/listen` is the **delivery channel**; `resources/subscribe` is the **subscription mechanism**.

Resource subscriptions **MAY** be associated with a session.  If the `resources/subscribe` request includes session metadata, the resulting notifications/resources/updated notifications are delivered on that session's listen stream. If no session is specified, notifications are delivered on a global listener.

Servers SHOULD define a lifecycle policy for subscriptions — for example, scoping them to a session if one exists, or applying a TTL for sessionless subscriptions.

The typical flow:

1. The Client creates a session (`sessions/create`).
2. The Client opens a listener (`messages/listen` scoped to that session).
3. The Client subscribes to a resource (`resources/subscribe` with the session in `_meta`).
4. When the resource changes, the Server sends `notifications/resources/updated` on the session's listen stream.

Reconnection and missed-event recovery for the listen stream are handled at the **transport layer** (e.g., SSE `Last-Event-ID` for Streamable HTTP).

##### STDIO Transport Behaviour

For STDIO, `messages/listen` does not create a separate transport channel; it registers notification scope on the existing connection. The Server acknowledges the registration with `notifications/messages/listen`, after which it **MAY** send server-initiated messages for that registered scope over the same STDIO connection.

#### Deleting Sessions

Clients **SHOULD** delete sessions that are no longer required to allow the Server to reclaim unneeded resources. 

**Request:**

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "sessions/delete",
  "params": {
    "_meta": {
      "io.modelcontextprotocol/session": {
        "sessionId": "sess-a1b2c3d4e5f6"
      }
    }
  }
}
```

**Response:**

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {}
}
```

#### Errors

```json
 {
   "jsonrpc": "2.0",
   "id": 42,
   "error": {
     "code": -32043,
     "message": "Session not found",
     "data": {
       "sessionId": "sess-a1b2c3d4e5f6"
     }
   }
 }
```

1. The Server **MAY** respond with a `-32043 SESSION_NOT_FOUND` Error if it considers the Session identifier invalid.
1. Clients **SHOULD** consider the receipt of `-32043 SESSION_NOT_FOUND` to indicate that the Session is not recognised by the Server.
1. Servers and Clients **SHOULD** implement a policy to remove stale Server maintained session state.


### Data Types

#### SessionMetadata

_The following notes on sessionId are taken from the existing Streamable HTTP Transport guidance._

**sessionId:**
1. The `sessionId` **SHOULD** be globally unique and cryptographically secure (e.g., a securely generated UUID, a JWT, or a cryptographic hash).
1. The `sessionId` MUST only contain visible ASCII characters (ranging from 0x21 to 0x7E).
1. The client MUST handle the `sessionId` in a secure manner, see [Session Hijacking](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices#session-hijacking) mitigations for more details.

**expiresAt:**
1. `expiresAt` is a hint that Clients **MAY** use to inform Users of potentially stale sessions.
1. Servers may update the `expiresAt` hint on any response.

**state:**

_The following notes on state are paraphrased from SEP (MRTR)_

state:

1. state is an opaque, server-issued token that enables stateless server processing.
1. Clients MUST treat state as opaque and MUST echo the exact value on subsequent requests in that session.
1. Servers SHOULD protect state according to their security requirements, ranging from plaintext (development only) to signed or encrypted tokens (production).
1.  See **SEP-XXXX Multi Round-Trip Requests** requestState guidance for canonical encoding, validation, size and security requirements.

### Schema

Session association metadata uses `_meta["io.modelcontextprotocol/session"]` with value type SessionMetadata.

```ts
/**
 * Describes an MCP Session.
 * Include this in the `_meta` field under the key `io.modelcontextprotocol/session`.
 */
export interface SessionMetadata {
  /**
   * The session identifier.
   */
  sessionId: string;

  /**
   * ISO 8601 timestamp hint for session expiry
   */
  expiresAt?: string;

  /**
   * Opaque server-issued session state token.
   * Clients MUST treat this value as opaque and MUST NOT inspect or modify it.
   */
  state?: string;

}
```

Sessions are created and deleted via `sessions/create` and `sessions/delete` requests:

```ts
 /**
  * A request to create a new session.
  *
  * @category `sessions/create`
  */
 export interface CreateSessionRequest extends JSONRPCRequest {
   method: "sessions/create";
   params?: RequestParams;
 }

 /**
  * The result returned by the server for a {@link CreateSessionRequest | sessions/create} request.
  *
  * @category `sessions/create`
  */
 export interface CreateSessionResult extends Result {
   session: SessionMetadata;
 }

 /**
  * A successful response from the server for a {@link CreateSessionRequest | sessions/create} request.
  *
  * @category `sessions/create`
  */
 export interface CreateSessionResultResponse extends JSONRPCResultResponse {
   result: CreateSessionResult;
 }

 /**
  * A request to delete an existing session.
  *
  * @category `sessions/delete`
  */
 export interface DeleteSessionRequest extends JSONRPCRequest {
   method: "sessions/delete";
   params?: RequestParams;
 }

 /**
  * A successful response from the server for a {@link DeleteSessionRequest | sessions/delete} request.
  *
  * @category `sessions/delete`
  */
 export interface DeleteSessionResultResponse extends JSONRPCResultResponse {
   result: EmptyResult;
 }
```


```ts
/** @internal */
export const SESSION_NOT_FOUND = -32043;

/**
 * An error response indicating that the supplied session does not exist.
 *
 * @example Session not found
 * {@includeCode ./examples/SessionNotFoundError/session-not-found.json}
 *
 * @category Errors
 */
export interface SessionNotFoundError extends Omit<
  JSONRPCErrorResponse,
  "error"
> {
  error: Error & {
    code: typeof SESSION_NOT_FOUND;
    data: {
      /**
       * The session identifier provided by the caller.
       */
      sessionId: string;
      [key: string]: unknown;
    };
  };
}
```

## Other Work

### SEP-2243 HTTP Standardization

When _meta["io.modelcontextprotocol/session"] is present and using the StreamableHttp transport, the sessionId should be included as `Mcp-Session-Id` in the HTTP Headers.

## Rationale

### HTTP Cookies vs. Custom Implementation

HTTP cookies (RFC 6265) provide an existing stateless session mechanism with automatic client-side storage and per-request transmission. The header pattern is well-understood and battle-tested. 
 
This proposal adopts a similar pattern (server-issued opaque tokens that clients return unmodified) but implements it in the JSON-RPC message layer rather than HTTP Headers, enabling consistent session semantics across non-HTTP transports.

### Session Update Sequencing

Because MCP clients may execute multiple requests concurrently (e.g., parallel tool calling), there are no inherent ordering guarantees for request/response cycles. This creates a Last-Write-Wins race condition if the server relies entirely on the client-echoed state token to manage highly mutable data. Additionally Client state saving error conditions are not known to the Server.

To resolve this, servers dealing with concurrent mutations SHOULD NOT rely on the state token. Instead, the server SHOULD use the sessionId as a lookup key for a server-side state management mechanism (e.g., a database, cache, or in-memory store).  

Using server-side state naturally delegates concurrency control to the server environment, keeping the MCP client implementation simple and eliminating the need for sequence tracking within the protocol layer. The state token remains available strictly for simple, stateless server deployments where concurrent mutations are not expected.  


### Use of in-band Tool Call ID

A common workaround pattern is to use a session identifier within CallToolRequests to simulate sessions. This is often model controlled, with the session identifier being reproduced by the LLM. 

In practice, MCP Sessions may be used for other state control - for example availability of Tools, Prompts or Resources - therefore including the sessionId as part of the request/response cycle managed by the Host is the right choice.

### Use of a single `state` value rather than KV store.

A single opaque "state" value mirrors the MRTR design, reduces the chance of KV merge errors, and keeps client behaviour simple (simply echo bytes back). 

### Scope of Sessions

For 2025-11-25 specification STDIO servers, Sessions are inherent to the process lifecycle and all Requests and Responses are within the same "session scope".

For 2025-11-25 specification Streamable HTTP servers, Sessions are typically managed on a "per connection" basis, with the MCP Server choosing session usage at Initialization time and enforcing with HTTP status codes. Although technically feasible to gate different operations to require sessions or not, in practice usage is "all" or "nothing".  

With this design, it is possible for an MCP Server to support granular session gating.

The TypeScript SDK in particular places a significant burden on the MCP Server developer to control "sessions". Client SDKs tend to combine the "connect" and current "initialize" operations leaving session establishment to the transport layer.

For MCP Servers, developer experience could be simplified by using standard patterns in the SDK to suggest that Sessions are either:
 - Required - the SDK will provide hooks and ensure that requests are completed within the context of a Session.
 - Not Required - the SDK will not enforce sessions for MCP operations.
 - Managed - the MCP Server Author will handle the allocation of sessions (similar to existing Typescript SDK)

 Clients can use the following patterns, and discover whether Sessions are required by making a call or probing the proposed `/discover` endpoint:
 - Single - the Client will provide a single Session for the connection, or no session if not required. This is similar to existing behaviour.
 - Managed - the Client will provide an explicit `session.create` operation to return a token, an interface for storage and a reusable token for Client management. 

Because MCP clients may execute multiple requests concurrently (e.g., parallel tool calling), there are no inherent ordering guarantees for request/response cycles. This creates a Last-Write-Wins race condition if the server relies entirely on the client-echoed state token to manage highly mutable data.

To resolve this, servers dealing with concurrent mutations SHOULD NOT rely on the state token. Instead, the server SHOULD use the sessionId as a lookup key for a server-side state management mechanism (e.g., a database, cache, or in-memory store).

Using server-side state naturally delegates concurrency control to the server environment, keeping the MCP client implementation simple and eliminating the need for sequence tracking within the protocol layer. The state token remains available strictly for simple, stateless server deployments where concurrent mutations are not expected.
### Notifications for Multiple Sessions

One `messages/listen` stream per session is a deliberate choice:

1. SSE streams are immutable once opened — session lists cannot be modified without reconnection.
1. HTTP/2 multiplexing makes concurrent streams inexpensive for HTTP transports.

## Backward Compatibility

### Servers without session support

If a client attempts to invoke `sessions/create` on a server that does not advertise the `sessions` capability, the server MUST reject the request with a standard JSON-RPC `-32601 Method not found` error.

If a client sends session metadata to a server that does not support this extension, the server SHOULD reject the request using existing JSON-RPC or application-defined error handling.

## Test Vectors

### Session Creation

**Request:**
```json
{"jsonrpc":"2.0","id":1,"method":"sessions/create"}
```

**Valid Response:**
```json
{"jsonrpc":"2.0","id":1,"result":{"session":{"sessionId":"sess-abc123","expiresAt":"2026-03-01T00:00:00Z","state":"eyJrIjoidiJ9"}}}
```

### Session Usage

**Request with session:**
```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"echo","arguments":{"msg":"hi"},"_meta":{"io.modelcontextprotocol/session":{"sessionId":"sess-abc123","state":"eyJrIjoidiJ9"}}}}
```

**Response with updated state:**
```json
{"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"hi"}],"_meta":{"io.modelcontextprotocol/session":{"sessionId":"sess-abc123","state":"eyJrIjoidjIifQ==","expiresAt":"2026-03-01T00:00:00Z"}}}}
```

### Session Not Found

**Request with invalid session:**
```json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"echo","arguments":{},"_meta":{"io.modelcontextprotocol/session":{"sessionId":"sess-invalid"}}}}
```

**Error Response:**
```json
{"jsonrpc":"2.0","id":3,"error":{"code":-32043,"message":"Session not found","data":{"sessionId":"sess-invalid"}}}
```
