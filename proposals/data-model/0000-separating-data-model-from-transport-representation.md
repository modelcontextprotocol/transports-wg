# SEP-0000: Separating Data Model from Transport Representation

- **Status**: Unsubmitted draft
- **Type**: Standards Track
- **Created**: 2026-09-30
- **Author**: TBD
- **Sponsor / PR**: Not yet assigned

## Abstract

Separate MCP's data types from their transport representation. Requests,
notifications, responses, and errors share four fields: `protocolVersion`,
`method`, `metadata`, and `payload`. Each transport specification defines how
these types translate to and from its wire format, including how request IDs
are handled. Existing stdio and Streamable HTTP wire formats stay unchanged.

## Motivation

We are exploring adapting stdio to use HTTP. This could let stdio and Streamable
HTTP share more behavior and reduce duplication between JSON-RPC fields and HTTP
headers.

For example, a `tools/call` request over Streamable HTTP carries its protocol
version in two places:

```text
Header: MCP-Protocol-Version: 2026-07-28
Body:   params._meta["io.modelcontextprotocol/protocolVersion"] = "2026-07-28"
```

HTTP over stdio could carry that value only in the header. But removing the body
field would break `CallToolRequest` for SDKs that expose the current schema
directly, even though the tool call itself has not changed.

With a separate data model, both transports use `request.protocolVersion`.
Each transport specification defines where that value appears on the wire;
application types stay the same.
This SEP creates that separation. It does not change either existing wire format
or introduce HTTP over stdio.

## Specification

### Data model

The [proposed schema](./data-model.schema.ts) uses this common shape:

```typescript
interface MCPMessage<P = unknown, M extends Metadata = Metadata> {
  protocolVersion: string | undefined;
  method: string | undefined;
  metadata: M;
  payload: P;
}
```

- `protocolVersion` is the MCP version, not the JSON-RPC version.
- `method` names the operation. Responses use the original request's method.
- `metadata.meta` holds message-level metadata, except protocol version and
  transport IDs. Requests and notifications share `MessageMetadata`. Requests
  require client capabilities in `meta`; notifications may omit `meta`.
- `payload` holds the parameters, result, or error, without message-level `_meta`.
  Nested metadata, such as `Tool._meta`, stays in place. Nested MRTR input requests
  keep their existing `method` and `params` fields.

Requests, notifications, and successful responses require a version and method.
Errors may leave either undefined when the original request cannot be identified.

The message types are `MCPRequest`, `MCPNotification`, `MCPResponse`, and
`MCPErrorResponse`. The API operation MUST identify the message type;
implementations MUST NOT guess it from the method or payload.
TypeScript type names are not available at runtime.

The transport section of the specification defines how this data model is
translated to and from the wire format. Transport implementations MUST keep
request IDs and routing state outside the data model.
Cancellation and subscription messages use that state to identify their target.
A cancellation payload contains only the optional reason.

Method-specific types, capabilities, client identity, progress tokens, and error
`code`, `message`, and `data` keep their existing meaning and requirements. Tool
execution failures remain results with `isError`.

### Example: `tools/call`

Before, the request inherits JSON-RPC fields, and its parameters inherit `_meta`:

```typescript
// original.schema.ts (selected declarations)
interface JSONRPCRequest extends Request {
  jsonrpc: typeof JSONRPC_VERSION;
  id: RequestId;
}

interface RequestParams {
  _meta: RequestMetaObject;
}

interface CallToolRequest extends JSONRPCRequest {
  method: "tools/call";
  params: CallToolRequestParams;
}
```

After, metadata is separate from the payload, and the request has no transport ID:

```typescript
// data-model.schema.ts (selected declarations)
interface MessageMetadata {
  meta?: MetaObject;
}

interface MCPRequest<P = unknown> extends MCPMessage<P, MessageMetadata> {
  protocolVersion: string;
  method: string;
  metadata: MessageMetadata & { meta: RequestMetaObject };
}

interface RequestParams {}

interface CallToolRequest extends MCPRequest {
  method: "tools/call";
  payload: CallToolRequestParams;
}
```

`CallToolRequestParams` keeps `name`, `arguments`, `inputResponses`, and
`requestState`. Its `_meta` moves to `metadata.meta`, and the version moves to
`protocolVersion`. The transport implementation supplies `id` and rebuilds the
original `params` according to its transport specification.

### Transport Specifications

Each transport specification MUST define how the data model translates to and
from its wire format, including body fields, headers, and routing state. A wire
schema alone is not enough. The specifications below are independent: changing
one transport's translation does not change the other transport's requirements.

#### stdio

The [stdio wire schema](./stdio.schema.ts) describes the JSON-RPC objects.
Implementations MUST translate the data model as follows:

| Data-model field | Request | Notification | Successful response | Error response |
| --- | --- | --- | --- | --- |
| `method` | `method` | `method` | Transport state only | Transport state, if known |
| `payload` | `params` | `params`, if defined | `result` | `error` |
| `metadata.meta` | `params._meta` | `params._meta`, if present | `result._meta`, if present | Not added |
| `protocolVersion` | `params._meta["io.modelcontextprotocol/protocolVersion"]` | Transport state only | Transport state only | Transport state, if known |

On receipt, extract the request version into `protocolVersion`, the remaining
`params._meta` fields into `metadata.meta`, and the remaining `params` fields
into `payload`. Do not retain a second copy of the version in metadata.
Responses get their method and version from the stored request; notifications
get their version from transport state and their method from the wire message.

The stdio implementation MUST:

1. Add `jsonrpc: "2.0"` when encoding and remove it when decoding. Select the wire
   message type from the API operation. On receipt, use the wire envelope to
   dispatch to the correct request, notification, response, or error path.
2. Supply request and response IDs, omit notification IDs, and preserve absent
   error IDs. Preserve the distinction between string and numeric IDs. Keep
   cancellation targets and subscription IDs in transport state, restoring them
   to `params.requestId` and `_meta["io.modelcontextprotocol/subscriptionId"]`
   where required.
3. Preserve absent versus empty `params` and `_meta`: missing parameters become
   `payload: undefined`; `{}` stays `{}`. Omit absent fields rather than replacing
   them with `null`. Preserve error data, allowed extension fields, and nested
   metadata.
4. Reject conflicting copies of moved fields and missing or mismatched required
   routing state. Do not invent an ID, guess a method, default to the latest
   version, or turn a failed decode into a valid request. Uncorrelated errors may
   have unknown method/version; any received ID stays in transport state.

Framing and exchange rules are:

1. Encode each JSON-RPC object as one line followed by a newline. Escape newlines
   inside strings; pretty-printing MUST NOT add newlines within a message.
2. Send client requests and notifications to `stdin`; receive server responses
   and notifications from `stdout`. Diagnostics go to `stderr`. All metadata
   stays in the JSON body; there are no headers.
3. Decode one complete line at a time. Match responses by `id`, subscription
   notifications by subscription ID, and progress by its token before dispatch.
4. Cancel an exchange with `notifications/cancelled`, restoring its target ID to
   `params.requestId`. Receiving it cancels that exchange. Cancelling one request
   MUST NOT close the shared stdio channel.

This revision has no server-initiated wire requests; MRTR input requests stay
inside result payloads. The remaining lifecycle and security rules follow the
pinned [stdio specification][stdio-spec].

#### Streamable HTTP

The [Streamable HTTP wire schema](./streamable-http.schema.ts) describes the
JSON-RPC objects carried in HTTP bodies and SSE events.

##### JSON-RPC body fields

Implementations MUST set these fields from the data model, transport state, or
the fixed values listed below. Nested fields are added to the copied payload.

| JSON-RPC field | Source or fixed value | When to set |
| --- | --- | --- |
| `jsonrpc` | Fixed: `"2.0"` | Every message |
| `id` | Request ID from transport state | Requests and responses; omit for notifications and errors without an ID |
| `method` | `method` | Requests and notifications |
| `params` | Copy of `payload` | Requests; notifications when payload is defined |
| `params._meta` | Copy of `metadata.meta` | Requests; notifications when metadata is present |
| `params._meta["io.modelcontextprotocol/protocolVersion"]` | `protocolVersion` | Every request |
| `params._meta["io.modelcontextprotocol/subscriptionId"]` | Subscription ID from transport state | Subscription notifications that require it |
| `result` | Copy of `payload` | Successful responses |
| `result._meta` | Copy of `metadata.meta` | Successful responses when metadata is present |
| `result._meta["io.modelcontextprotocol/subscriptionId"]` | Subscription ID from transport state | Subscription results that require it |
| `error` | `payload` | Error responses |

Method-specific fields keep their names within `params`. For example,
`tools/call` copies `payload.name` to `params.name` and `payload.arguments` to
`params.arguments` when present.

The Streamable HTTP implementation MUST:

1. Add `jsonrpc: "2.0"` when encoding and remove it when decoding. Select the wire
   message type from the API operation. On receipt, use the wire envelope to
   dispatch to the correct request, notification, response, or error path.
2. Supply request and response IDs, omit notification IDs, and preserve absent
   error IDs. Preserve the distinction between string and numeric IDs. Keep
   subscription IDs in transport state, restoring them to
   `_meta["io.modelcontextprotocol/subscriptionId"]` where required. Match
   responses and subscription IDs against the POST's stored request, and
   progress notifications by their token, before dispatch.
3. Preserve absent versus empty `params` and `_meta`: missing parameters become
   `payload: undefined`; `{}` stays `{}`. Omit absent fields rather than replacing
   them with `null`. Preserve error data, allowed extension fields, and nested
   metadata.
4. Reject conflicting copies of moved fields and missing or mismatched required
   routing state. Do not invent an ID, guess a method, default to the latest
   version, or turn a failed decode into a valid request. Responses get their
   method and version from the stored request; notifications get their version
   from transport state and their method from the wire message. Uncorrelated
   errors may have unknown method/version; any received ID stays in transport
   state.

##### HTTP request headers

Send each request as a separate POST containing one JSON-RPC object.
Implementations MUST set these headers from the data model or the fixed values
listed below:

| HTTP header | Data-model source or fixed value | When to set |
| --- | --- | --- |
| `Content-Type` | Fixed: `application/json` | Every request |
| `Accept` | Fixed: `application/json, text/event-stream` | Every request |
| `MCP-Protocol-Version` | `protocolVersion` | Every request |
| `Mcp-Method` | `method` | Every request |
| `Mcp-Name` | `payload.name` | `tools/call`, `prompts/get` |
| `Mcp-Name` | `payload.uri` | `resources/read` |
| `Mcp-Param-{Name}` | Value at the annotated property path in `payload.arguments`; `{Name}` comes from `x-mcp-header` in the tool's input schema | `tools/call`, when the annotated argument is present and non-null |

Parameter extraction, omitted/null values, conversion to strings, and Base64
encoding MUST follow the pinned [header rules][http-header-rules]. Decode and
check headers against the body before dispatch. Missing, malformed, or mismatched
required MCP headers produce HTTP 400 and `HeaderMismatch` (`-32020`); headers MUST
NOT override body values. After validation, extract the request version from
`params._meta["io.modelcontextprotocol/protocolVersion"]` into `protocolVersion`,
the remaining `_meta` fields into `metadata.meta`, and the remaining `params`
fields into `payload`. Do not retain a second copy of the version in metadata.
The two wire copies become one data-model field. Capabilities and client
identity map between `metadata.meta` and `params._meta`; they have no header
mapping.

For `application/json`, decode one response object. For `text/event-stream`,
encode and decode notifications and the final response as SSE event data. Ignore
SSE comments and check response IDs against the POST's stored request.
`subscriptions/listen` keeps its SSE response open for subscription notifications.

Closing a request's SSE stream signals cancellation; implementations MUST NOT
also send `notifications/cancelled`. This revision defines no core
client-to-server HTTP notifications. If an extension permits notification POSTs,
acceptance returns HTTP 202 with no body, which MUST NOT create an `MCPResponse`.

Other status, lifecycle, and security rules follow the pinned
[Streamable HTTP specification][http-spec]. HTTP failures without a valid MCP
error body remain transport failures. This revision has no server-initiated wire
requests; MRTR input requests stay inside result payloads.

[stdio-spec]: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/046fa30efd374370afb87ef830bd788eac5f217e/docs/specification/draft/basic/transports/stdio.mdx
[http-spec]: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/046fa30efd374370afb87ef830bd788eac5f217e/docs/specification/draft/basic/transports/streamable-http.mdx
[http-header-rules]: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/046fa30efd374370afb87ef830bd788eac5f217e/docs/specification/draft/basic/transports/streamable-http.mdx#request-metadata

## Rationale

Removing only `jsonrpc` would still tie application types to the placement of
`params`, `result`, and `error`. Separating metadata and payload lets each
transport specification define their placement. Separate API operations
distinguish requests from responses: both can refer to `tools/call`, so the method
alone is not enough.

## Backward Compatibility

Wire formats and version negotiation stay unchanged. Code using wire-shaped
types can continue using the wire schemas. Code adopting the data model must
translate messages according to the transport specification. No SDK tier
requirements are added.

## Security Implications

Transport implementations MUST validate metadata, match messages to the correct
request, and reject conflicting header/body values before dispatch. Client
identity remains self-reported metadata, not proof of identity. Existing authentication and
authorization rules still apply.
