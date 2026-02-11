**Authors:** Gabriel Zimmerman (gjz22)

**Status:** Draft

**Type:** Standards Track

## Abstract

This SEP proposes adding an optional `state` field to both `ServerRequest` and `ServerResponse` messages in the Model Context Protocol (MCP). The client MUST echo back the exact state value received in the request when sending the response. This change enables servers to implement stateless request flows, eliminating the requirement for durable state storage and significantly reducing operational complexity and cost. While this applies to all ServerRequests, the primary motivation is elicitation requests, where response times are unbounded and can range from seconds to hours, making stateful implementations particularly challenging for remote MCPs.

## Motivation

### Primary Use Case: Elicitation Requests in Remote Servers

While this SEP proposes adding state to all ServerRequest and ServerResponse messages, the primary driver is elicitation requests in remote MCP servers. Unlike other server requests such as sampling (which typically receive responses in seconds), elicitation requests have unbounded response times. A user may take minutes, hours, or even longer to respond to an elicitation prompt, making stateful server implementations particularly burdensome for remote MCP servers to the point of making them impractical for many architectures.

However, other server request flows may benefit from passing state to ensure the response does not need to go back to the original server that made the request and to remove the need for a durable store in case of disconnects.

### Multi-Round-Trip Request Flows

Beyond single request-response pairs, the `state` field enables servers to orchestrate multi-round-trip interactions where each step builds on the accumulated context from previous steps. A server can encode the results of prior elicitation rounds into the state, allowing subsequent requests to continue where the previous round left off — all without any server-side storage. This pattern is particularly valuable for complex workflows that require gathering multiple pieces of information through iterative elicitation, where the server must conditionally request additional input based on business rules triggered by earlier responses.

### Elicitation Protocol Flow

When a Remote MCP Server needs additional information from a user, it initiates an elicitation request through the following flow:

1. **Server sends elicitation request:** The server sends a ServerRequest using the `elicitation/create` method over an SSE (Server-Sent Events) stream, specifying what information is needed and the expected schema.

2. **Client presents UI:** The client displays an interface to the user (dialog, form, etc.) and waits for the user to respond. This may take seconds, minutes, or even longer depending on user availability.

3. **Client sends response:** Once the user provides input, the client sends a ServerResponse back to the server with the collected data.

4. **Server processes response:** The server uses the elicited information to continue its operation.

During this flow, if the SSE connection breaks (due to network issues, load balancer timeouts, or other failures), the Streamable HTTP transport supports reconnection using the `Last-Event-ID` mechanism. The client can reconnect and indicate the last event it successfully received, allowing the server to resume the stream.

### The Problem with Stateful Server Requests

The current MCP protocol requires servers to maintain state for server-initiated requests (ServerRequests) that await client responses (ServerResponses). This is particularly problematic for elicitation requests in Remote MCP Servers for two key reasons:

**First**, the SSE connection must remain open for the duration of the request. The server must maintain this connection from when it sends the request until it receives the response. For elicitation requests, this could be an arbitrary amount of time. *Solving this is the role of the Multi Round Trip Request SEP.*

**Second**, to support reconnection via the `Last-Event-ID` mechanism, the server must retain enough context to process the eventual ServerResponse even if the connection breaks and reconnects.

This requirement for durable state storage imposes significant operational burdens on server implementations:

### Architectural Complexity and Costs of Durable State

Implementing durable state storage requires substantial infrastructure and operational overhead:

- **Infrastructure Requirements:** Servers must deploy and manage a persistent data store (e.g., PostgreSQL, Redis, DynamoDB) with high availability, replication, and backup mechanisms. This is not a simple in-memory cache but must survive server restarts and failures.

- **Operational Complexity:** State synchronization in distributed deployments requires distributed locking or consensus protocols. Garbage collection logic is needed to clean up orphaned state, typically using TTL (time-to-live) mechanisms. However, TTLs create a fundamental tradeoff: short TTLs reduce storage costs but limit how long users have to respond to elicitation requests, while long TTLs accommodate slow users but increase storage requirements.

- **Scalability Limitations:** The state store becomes a bottleneck, limiting horizontal scaling. Geographic distribution requires either expensive global replication or sticky routing with poor user experience.

- **Reliability Concerns:** The state store becomes a critical dependency and single point of failure. State corruption or catastrophic failures require complex recovery procedures.

- **Development Burden:** Developers must write and maintain state storage abstraction layers, connection pooling, transaction handling, and migration scripts. Testing requires integration tests with real databases and complex fixtures.

### The Stateless Alternative

With a `state` field, servers can encode all necessary context directly in any ServerRequest. This would allow the server to break the SSE connection (discussed in other SEPs). When the client returns this opaque state in the ServerResponse, the server can immediately process the response without consulting any external storage. This transforms server-initiated requests from stateful, distributed transactions into simple, self-contained request-response pairs.

Benefits include:
- **Trivial horizontal scaling** - any server can handle any response
- **Simplified deployments** - no state migration concerns
- **Improved reliability** - no state store to fail
- **Reduced latency** - no database queries
- **Lower development costs** - no state management code to write or maintain

## Specification

### Protocol Requirements

1. **Server Behavior:**
   - Servers MAY include a `state` field in any ServerRequest (including `elicitation/create`, `sampling/createMessage`, etc.).
   - The state value MUST be treated as an opaque string by clients.
   - Servers SHOULD encode all context needed to process the response in the `state` field when using stateless mode.

2. **Client Behavior:**
   - Clients MUST echo back the exact `state` value received in any ServerRequest when sending the corresponding ServerResponse.
   - Clients MUST NOT inspect, parse, modify, or make any assumptions about the state contents.
   - If a ServerRequest does not contain a `state` field, the client MUST NOT include one in the ServerResponse.

3. **State Content:**
   - The `state` field contains an opaque string that is meaningful only to the server.
   - Servers are free to encode the state in any format (e.g., plain JSON, base64-encoded JSON, encrypted JWT, serialized binary, etc.).
   - The state MAY be human-readable (e.g., plain JSON) for ease of debugging and development, or it MAY be encrypted/signed for security. Regardless of format, servers MUST always validate and handle potentially tampered state from the client, as the client is an untrusted intermediary.

### Integration with Multi-Round-Trip Requests — TO BE DISCUSSED

The [Multi-Round-Trip Requests (MRTR) proposal](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/XXXX) introduces `JSONRPCIncompleteResultResponse` messages that carry `dependent_requests` — an object containing server-initiated requests that the client must fulfill before retrying the original call. When combining MRTR with the `state` field, there are two options for where state lives:

**Option 1: State shared across all requests**

State is a single field within `dependent_requests`, shared across all requests in that round. This keeps state management simple — one opaque blob per round-trip, representing the server's entire continuation context:

```json
{
  "id": 2,
  "dependent_requests": {
    "state": { "workItemId": 4522, "fields": { "System.State": "Resolved" } },
    "requests": [
      {
        "params": {
          "message": "How was this bug resolved?",
          "requestedSchema": { ... }
        }
      }
    ]
  }
}
```

The client echoes the state back in `dependent_responses` on the retry:

```json
{
  "id": 3,
  "method": "tools/call",
  "params": { ... },
  "dependent_responses": {
    "state": { "workItemId": 4522, "fields": { "System.State": "Resolved" } },
    "responses": [
      {
        "result": { "action": "accept", "content": { "resolution": "Duplicate" } }
      }
    ]
  }
}
```

**Option 2: State per individual request**

Each request within `dependent_requests.requests` carries its own `state` field, and the client echoes each one back in the corresponding entry in `dependent_responses.responses`. This allows the server to associate different state with different requests in the same round:

```json
{
  "id": 2,
  "dependent_requests": {
    "requests": [
      {
        "state": { "workItemId": 4522, "fields": { "System.State": "Resolved" } },
        "params": {
          "message": "How was this bug resolved?",
          "requestedSchema": { ... }
        }
      },
      {
        "state": { "approvalContext": "manager-sign-off" },
        "params": {
          "message": "Does the manager approve this resolution?",
          "requestedSchema": { ... }
        }
      }
    ]
  }
}
```

The client echoes each state back in the corresponding response:

```json
{
  "id": 3,
  "method": "tools/call",
  "params": { ... },
  "dependent_responses": {
    "responses": [
      {
        "state": { "workItemId": 4522, "fields": { "System.State": "Resolved" } },
        "result": { "action": "accept", "content": { "resolution": "Duplicate" } }
      },
      {
        "state": { "approvalContext": "manager-sign-off" },
        "result": { "action": "accept", "content": { "approved": true } }
      }
    ]
  }
}
```

**Tradeoffs:**

- **Option 1** is simpler — one state per round-trip, less bookkeeping for clients, and the server can encode everything it needs in a single blob. However, if different requests are handled by different subsystems on the server, a single shared state may be awkward.
- **Option 2** is more flexible — each request is self-contained with its own state, which maps cleanly to the non-MRTR case where each `ServerRequest` carries its own `state`. However, it requires clients to track and echo back multiple state values per round-trip.

### Schema Changes

The `state` field is added as an optional top-level property on `ServerRequest` and `ServerResult`:

```typescript
interface ServerRequest {
  jsonrpc: "2.0";
  id: string | number;
  method: string;
  state?: string | Record<string, unknown>;  // ← new
  params?: { ... };
}

interface ServerResult {
  jsonrpc: "2.0";
  id: string | number;
  state?: string | Record<string, unknown>;  // ← new
  result: { ... };
}
```

On the wire, this looks like:

```json
// Server → Client request
{
  "jsonrpc": "2.0",
  "id": 100,
  "method": "elicitation/create",
  "state": "...",           // ← top-level
  "params": { ... }
}

// Client → Server response
{
  "jsonrpc": "2.0",
  "id": 100,
  "state": "...",           // ← top-level
  "result": { ... }
}
```

The `state` field is a top-level field of the JSON-RPC message rather than a sub-field of `params` or `result`. State enables stateless multi-round-trip request flows — a core capability for remote MCP servers. Placing it at the top level of the message reflects its importance as a transport-level concern, ensures universal applicability across all message types, and simplifies access patterns in server and client code.

### Example Usage: Multi-Round-Trip Elicitation with Azure DevOps Custom Rules

This example demonstrates how `state` enables a multi-round-trip elicitation flow driven by [Azure DevOps custom rules](https://learn.microsoft.com/en-us/azure/devops/organizations/settings/work/custom-rules?view=azure-devops). The scenario involves an `update_work_item` tool that transitions a Bug work item to "Resolved." ADO custom rules require specific fields when certain state transitions occur, and the server uses iterative elicitation to gather them — accumulating context in `state` across rounds so that the final update can be executed without any server-side storage.

> **Note:** With the Multi-Round-Trip Requests SEP, the original tool call arguments (work item ID, fields, etc.) are preserved across subsequent calls and do not need to be encoded in `state`. The `state` field only needs to carry context accumulated from prior elicitation rounds.

**Background — ADO Custom Rules in effect:**
- *Rule 1:* When State changes to "Resolved" → require the "Resolution" field (e.g., Fixed, Won't Fix, Duplicate, By Design).
- *Rule 2:* When Resolution is "Duplicate" → require the "Duplicate Of" field (a link to the original work item).

#### Round 1 — Tool call triggers state change, server elicits Resolution

The client invokes the `update_work_item` tool to resolve Bug #4522:

```json
// Client → Server: tool call
{
  "method": "tools/call",
  "params": {
    "name": "update_work_item",
    "arguments": {
      "workItemId": 4522,
      "fields": {
        "System.State": "Resolved"
      }
    }
  }
}
```

The server recognizes that setting State to "Resolved" triggers Rule 1, which requires a Resolution value. Rather than failing the call, the server initiates an elicitation request. Since the tool call arguments are already preserved by the Multi-Round-Trip Requests mechanism, the state does not need to include them:

```json
// Server → Client: elicitation request (round 1)
{
  "method": "elicitation/create",
  "params": {
    "message": "Resolving Bug #4522 requires a resolution. How was this bug resolved?",
    "requestedSchema": {
      "type": "object",
      "properties": {
        "resolution": {
          "type": "string",
          "enum": ["Fixed", "Won't Fix", "Duplicate", "By Design"],
          "description": "Resolution type for this bug"
        }
      },
      "required": ["resolution"]
    }
  }
}
```

The user selects "Duplicate":

```json
// Client → Server: elicitation response (round 1)
{
  "result": {
    "action": "accept",
    "content": {
      "resolution": "Duplicate"
    }
  }
}
```

#### Round 2 — Resolution triggers another rule, server elicits Duplicate Of

The server merges the user's response and sees that Resolution = "Duplicate" triggers Rule 2, requiring a "Duplicate Of" link. It sends another elicitation request, encoding the accumulated elicitation result in `state` so it is available regardless of which server instance handles the next response:

```json
// Server → Client: elicitation request (round 2)
{
  "method": "elicitation/create",
  "state": {
    "Microsoft.VSTS.Common.ResolvedReason": "Duplicate"
  },
  "params": {
    "message": "Since this is a duplicate, which work item is the original?",
    "requestedSchema": {
      "type": "object",
      "properties": {
        "duplicateOfId": {
          "type": "number",
          "description": "Work item ID of the original bug"
        }
      },
      "required": ["duplicateOfId"]
    }
  }
}
```

The user provides the original work item ID, and the client echoes back the state:

```json
// Client → Server: elicitation response (round 2)
{
  "state": {
    "Microsoft.VSTS.Common.ResolvedReason": "Duplicate"
  },
  "result": {
    "action": "accept",
    "content": {
      "duplicateOfId": 4301
    }
  }
}
```

#### Final — Server completes the update

The server decodes the state, merges the final response, and now has all required fields. It completes the tool call and returns the result to the client — without ever having stored anything between rounds:

```json
// Server → Client: tool result
{
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Bug #4522 resolved as Duplicate of Bug #4301. State set to Resolved and duplicate link created."
      }
    ]
  }
}
```

**Key takeaway:** Across both elicitation rounds, the server held no in-memory or persisted state. The `state` field carried the accumulated context through the client, and any server instance could have handled any individual round. If the SSE connection dropped between rounds, reconnection and routing to a different server instance would work seamlessly.

## Rationale

### Design Decisions

**1. Top-Level JSON-RPC Field**

The `state` field is placed at the top level of the JSON-RPC message rather than inside `params` (for requests) or `result` (for responses). Not all ServerRequests have `params` (e.g., `ping`, `roots/list`), so nesting state there would limit applicability. State is not domain-specific data — it is a transport-level mechanism that enables stateless multi-round-trip request flows, a core capability for remote MCP servers. Placing it at the top level alongside `jsonrpc`, `method`, and `id` reflects its role as a protocol-level concern and ensures universal applicability across all message types.

**2. No Capability Negotiation Required**

Unlike some protocol extensions, the `state` field does not require capability negotiation during initialization. The echo-back behavior is a simple, universal contract: if a `state` field is present in a ServerRequest, the client echoes it in the ServerResponse. If absent, the client omits it. This keeps the protocol simple and avoids the complexity of conditional behavior based on capability declarations. Clients that predate this change will naturally ignore unknown fields without breaking, and servers that need state can detect its absence in the response and fall back gracefully. Servers SHOULD NOT include `state` in requests to clients whose negotiated protocol version predates the introduction of the `state` field.

**3. Optional Field**

The `state` field is optional because servers can choose not to use it. Existing servers that use server-side state management can continue to operate without changes. New servers can opt into stateless mode by including the `state` field. Servers may also choose to use state selectively — for example, only for elicitation requests where response times are unbounded, while continuing to use server-side state management for faster ServerRequests like sampling.

**4. Opaque String**

The state is defined as an opaque string rather than a structured object to give servers maximum flexibility in how they encode context. Servers can choose:
- Plain JSON for human-readable debugging
- Base64-encoded JSON for compactness
- Encrypted tokens for security
- Signed JWTs to prevent tampering
- Binary serialization for compactness

**5. Strict Echo Requirement**

Clients MUST return the exact state without modification. This is critical because:
- Any modification could corrupt the encoded context
- Servers may include checksums or signatures for tamper detection
- It keeps the client implementation simple — no parsing or logic required

**6. Server-Controlled**

Only servers can initiate stateless mode (by including state in the request). Clients cannot force a server to be stateless. This gives servers full control over their architecture.

## Backward Compatibility

This proposal is fully backward compatible:

- **Existing Servers:** Can continue to ignore the `state` field and use server-side state management for all ServerRequests. No changes required.

- **Existing Clients:** Clients that do not yet recognize the `state` field will simply not echo it back. Servers can detect the absence of state in the response and fall back to server-side stateful processing. No capability negotiation is required, so there is no handshake to break.

## Security Implications

**1. State Tampering and Information Disclosure**

Since the `state` field passes through the client (who echoes it back), malicious or compromised clients could attempt to modify it to gain unauthorized access, bypass authorization checks, or corrupt server logic. Additionally, the `state` field may contain information (file paths, work item IDs, user context, etc.) that is visible to the client. For many use cases this is acceptable or even desirable (e.g., debugging), but for sensitive data it poses a disclosure risk.

**Mitigation:** Servers MUST always validate state received from the client, as the client is an untrusted intermediary. Servers that require tamper protection SHOULD use cryptographic signatures (e.g., HMAC) or authenticated encryption (e.g., AES-GCM), which addresses both tampering and disclosure in a single mechanism. Servers using plain JSON state MUST treat the decoded values as untrusted input and validate them the same way they would validate any client-supplied data. Servers should evaluate their threat model and choose the appropriate level of protection.

**2. Replay Attacks**

A malicious actor could capture a valid `state` value and replay it to trigger unintended operations.

**Mitigation:** Include timestamps or nonces in the state and reject expired or duplicate states. Implement short time-to-live (TTL) for state values.

## Migration Path

For servers transitioning from stateful to stateless server requests:

1. **Phase 1 - Dual Mode:** Implement state encoding/decoding but continue writing to the database as well. This allows validation that the stateless approach works correctly.

2. **Phase 2 - Stateless Primary:** Use the `state` field as the primary mechanism, falling back to database lookup only if state is missing or invalid.

3. **Phase 3 - Stateless Only:** Remove database dependencies entirely once confident in the stateless implementation.

4. **Phase 4 - Cleanup:** Remove state management infrastructure, reduce operational costs.

Note: Servers may choose to implement stateless mode only for elicitation requests initially, as these have unbounded response times and benefit most from stateless architecture. Other ServerRequests like sampling can continue to use server-side state management if response times are predictably short.

## Conclusion

Adding an optional `state` field to ServerRequest and ServerResponse messages is a simple protocol change that enables significant architectural simplification. While this applies to all server-initiated requests, the primary benefit is for elicitation requests where response times are unbounded and for multi-round-trip workflows where servers must iteratively gather information across multiple elicitation rounds. Servers can eliminate the need for durable state storage, reducing costs by hundreds or thousands of dollars monthly while improving scalability, reliability, and operational simplicity. The change is fully backward compatible and gives servers the flexibility to choose between stateful and stateless implementations based on their requirements.
