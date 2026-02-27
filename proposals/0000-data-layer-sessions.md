# Data-Layer Sessions for MCP

> **Status:** Early Draft  
> **Date:** 2026-02-23  
> **Track:** transport-wg/sessions  
> **Author(s):** Shaun Smith

## Abstract

This proposal introduces application level sessions within the MCP Data Layer. Sessions are created by the Client, and allow the Server to store an opaque state token.

[Further context to be added]

## Motivation

MCP Sessions are currently either implicit (STDIO), or constructed as a side effect of the transport connection (Streamable HTTP).

It is assumed (but not required) that Host applications rather than the LLM are responsible for Session management.

## Specification

### User Interaction Model

Sessions are designed to be **application-driven**, with host applications determining how to establish sessions based on their need.

It is normally expected that applications will establish one session per conversation thread or task, but this is not required.

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
      "expiresAt": "2026-02-27T15:30:00Z"
    },
    "_meta": {
      "io.modelcontextprotocol/session": {
        "sessionId": "sess-a1b2c3d4e5f6",
        "expiresAt": "2026-02-27T15:30:00Z"
      }
    }
  }
}
```

The Client **MUST NOT** send `io.modelcontextprotocol/session` data with the sessions/create request. 


#### Using Sessions

To use a Session the Client request includes `_meta["io.modelcontextprotocol/session"]`:

1. The receiver MUST treat that sessionId as the session context for processing the request.
1. Succesful responses MUST include \_meta["io.modelcontextprotocol/session"].
1. The `sessionId` in the response MUST exactly match the sessionId from the request.
1. The receiver MUST NOT substitute, rotate, or rewrite `sessionId` in the response.

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "search_code",
    "arguments": {
      "query": "SessionMetadata"
    },
    "_meta": {
      "io.modelcontextprotocol/session": {
        "sessionId": "sess-a1b2c3d4e5f6"
      }
    }
  }
}
```



The Client SHOULD associate retained cookies with the issuing Server .

The expiry date is a hint. Can be refreshed `servers/discovery`.

- The session ID SHOULD be globally unique and cryptographically secure (e.g., a securely generated UUID, a JWT, or a cryptographic hash).
- The session ID MUST only contain visible ASCII characters (ranging from 0x21 to 0x7E).
- The client MUST handle the session ID in a secure manner, see Session Hijacking mitigations for more details. (TODO -- update this as data layer/stdio mitigations are different)

The Error message **SHOULD** be descriptive of the reason for failure.

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
        "expiresAt": "2026-02-27T15:30:00Z"
      }
    }
  }
}
```


#### Deleting Sessions

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

Clients **SHOULD** delete sessions that are no longer required to allow the Server to reclaim unneeded resources.

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

Clients use Sessions by including the SessionMetadata in `io.modelcontextprotocol/session` in \_meta of the Request.

When a requested Session is unknown by the Server it returns a `-32043 SESSION_NOT_FOUND` Error. The Client **SHOULD** treat the Session as permanently invalidated.

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

To support non HTTP transports, an MCP Data Layer proposal has been selected.

### Use of in-band Tool Call ID

A common workaround pattern is to use a session identifier within CallToolRequests to simulate sessions. This is often model controlled, with the session identifier being reproduced by the LLM. 

In practice, MCP Sessions may be used for other state control - for example availability of Tools, Prompts or Resources - therefore including the sessionId as part of the request/response cycle managed by the Host is the right choice.

### Use of single `state` value

A single opaque "state" value mirrors the MRTR design, and reduces the chance of KV merge errors, and keeps client behaviour simple (echo bytes back).

## Backward Compatibility

### Existing MCP Servers


### Session Guidance

