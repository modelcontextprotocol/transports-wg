# Data-Layer Sessions for MCP

> **Status:** Early Draft  
> **Date:** 2026-02-23  
> **Track:** transport-wg/sessions  
> **Author(s):** Shaun Smith

## Abstract

This proposal introduces application level sessions within the MCP Data Layer. Sessions are created by the Client, and allow the Server to store an opaque state token.

This proposal should be reviewed alongside SEP-1442, and assumes that the `initialize` operation and associated StreamableHTTP session creation is deprecated.

[Further context to be added]

## Motivation

MCP Sessions are currently either implicit (STDIO), or constructed as a side effect of the transport connection (Streamable HTTP). 

Migrating sessions to the MCP data layer allows MCP applications to handle sessions as part of their domain logic, decoupled from the transport layer. This enables predictable session semantics, especially for Hosts that handle multiple "threads" of context within the application. The ability for MCP Servers to allocate resources on a per-session basis, or be able to provide rich functionality without server-side storage makes MCP suitable for increasingly sophisticated and scaled deployments. 

## Specification

### User Interaction Model

Sessions are designed to be **application-driven**, with host applications determining how and when to establish sessions based on their need.

It is normally expected that applications will establish one session per conversation thread or task, but this is not required. 

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

The Client **MUST** securely associate retained sessions with the issuing Server. The Client will typically establish identity through a mixture of _connection target_ and _user identity_. 

`expiresAt` is a hint, and may be updated by the Server in future responses. The Host **MAY** use the `expiresAt` to indicate potentially stale sessions to the User. 

`state` **MUST** be retained by the Client and sent with future requests for that session.

#### Using Sessions

To use a Session the Client request includes SessionMetadata in `_meta["io.modelcontextprotocol/session"]`:

1. The Server MUST treat that sessionId as the session context for processing the request.
1. Succesful responses MUST include \_meta["io.modelcontextprotocol/session"].
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

1. The Client **MUST** update the `state` value if updated by the Server. See note on [Ordering](#session-update-sequencing))
1. The Client **MAY** update the `expiresAt` value if updated by the Server.

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

1. Unknown sessions **MUST** result in a  `-32043 SESSION_NOT_FOUND` Error. The Client **SHOULD** treat the Session as permanently invalidated.
1. The Server **MAY** revoke a Session at any time by returning an  `-32043 SESSION_NOT_FOUND` Error.

### Data Types

#### SessionMetadata

_The following notes on sessionId are taken from the existing Streamable HTTP Transport guidance._

**sessionId:**
1. The `sessionId` **SHOULD** be globally unique and cryptographically secure (e.g., a securely generated UUID, a JWT, or a cryptographic hash).
1. The `sessionId` MUST only contain visible ASCII characters (ranging from 0x21 to 0x7E).
1. The client MUST handle the `sessionId` in a secure manner, see Session Hijacking mitigations for more details. (

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

There are no ordering guarantees for requests/responses, meaning a Last-Write-Wins strategy by default. Servers should be aware of this potential race condition and include appropriate mitigations if needed.

A future design may introduce a monotonic state sequence to allow the client to identify the ordering of state content. 

### Use of in-band Tool Call ID

A common workaround pattern is to use a session identifier within CallToolRequests to simulate sessions. This is often model controlled, with the session identifier being reproduced by the LLM. 

In practice, MCP Sessions may be used for other state control - for example availability of Tools, Prompts or Resources - therefore including the sessionId as part of the request/response cycle managed by the Host is the right choice.

### Use of a single `state` value rather than KV store.

A single opaque "state" value mirrors the MRTR design, reduces the chance of KV merge errors, and keeps client behaviour simple (simply echo bytes back). 

### Scope of Sessions

For 2025-11-25 specification STDIO servers, Sessions are inherent to the process lifecycle and all Requests and Responses are within the same "session scope".

For 2025-11-25 specification Streamable HTTP servers, Sessions are typically managed on a "per connection" basis, with the MCP Server choosing session usage at Initialization time and enforcing with HTTP status codes. Although technically feasible to gate different operations to require sessions or not, in practice usage is "all" or "nothing".  

With this design, it is possible for an MCP Server to support granualar session gating.

TODO -- enhance discussion here.

### resourceAllocation Tool Hint

**For discussion** - it may make sense to include a tool hint to indicate whether or not a Session is associated with expensive resources, hinting that deletion is preferred at the end of the immediate User interaction session.

## Backward Compatibility

TODO -- incorporate support matrix.


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

