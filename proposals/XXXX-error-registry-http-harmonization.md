# SEP-XXXX: Error Condition Registry and HTTP Harmonization

- **Status**: Draft
- **Type**: Standards Track
- **Created**: 2026-09-03
- **Author(s)**: Stephen Tyree (@tyree731)
- **Sponsor**: None
- **PR**: None

## Abstract

The MCP specification defines a variety of JSON-RPC error codes, and
HTTP statuses, with no general rules connecting them. As a result of this
lack of specificity, different SDKs surface identical failures in
different ways, and clients often cannot distinguish certain categories
of errors across different SDKs.

This SEP defines a normative registry of error conditions, assigning each
error condition a JSON-RPC code with typed `error.data`, an HTTP status,
and a retry classification. These assignments follow RFC 9205's
recommendation against one-to-one error-to-HTTP-status mappings, require
errors to have in-band data in pursuit of cross-transport support, and
make clear that clients MUST determine the relevant conditions from the
response body. The registry binds the five standard JSON-RPC codes, adopts
SEP-3304's -32023/RateLimited, and allocates four new codes from the
reserved sub-range, Unavailable, RequestTooLarge, StaleState, and
UnsupportedFeature, together with common data members.

This SEP additionally defines the transport binding surrounding the
registry. The set of statuses able to carry a protocol error is closed at
five, successful results are bound to HTTP 200, errors arising after a
streaming response has begun are delivered in-band, and statuses arriving
with no parsable error body are treated as local observations rather than
peer errors, closing a path where infrastructure-generated statuses
trigger fallback to the deprecated HTTP+SSE transport. Cache directives
cover the heuristically cacheable bound statuses, a retry-safety assertion
makes automatic retry of non-idempotent requests possible to specify, and
authorization, legacy-verb, and notification conditions receive explicit
status-only standing. Extensions are barred from allocating within the
reserved sub-range, and conformance test cases are keyed to each rule.

## Motivation

### Neither error vocabulary is complete, and nothing connects them

The 2026-07-28 specification defines JSON-RPC error codes and their schema
in `basic/index#error-codes`, and prescribes HTTP statuses in
`basic/transports/streamable-http` and `basic/authorization/index`. Of the
64 HTTP status codes, the specification mentions only seven, with seven
MCP response conditions carrying both an HTTP status and in-band code, all
of them HTTP status 400 and 404. In the other direction, `-32700` (Parse Error),
`-32600` (Invalid Request), and `-32603` (Internal Error), carrying no
HTTP status binding, with the entire 5xx HTTP status code class appearing
nowhere in the MCP specification. For example, handler-produced `-32603` errors from
the primary SDKs all use HTTP 200, but transport-internal failures sometimes use
HTTP 500 with `-32603` (Python, Ruby SDKs), HTTP 500 with `-32000` (Typescript), and
sometimes elsewise.

### The specification imposes obligations it provides no way to express

| Obligation                                                                                            | Level       | Signal available | Defined in                                                                                                                                                                                                                                                                 |
|-------------------------------------------------------------------------------------------------------|-------------|------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| "Servers MUST: ... Rate limit tool invocations"                                                       | MUST/SHOULD | None.            | [Tools § Security Considerations](https://modelcontextprotocol.io/specification/2026-07-28/server/tools#security-considerations); companion MUST in [Completion § Security](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/completion#security) |
| Reject an unsupported extension "with an appropriate error"                                           | MUST        | None.            | [Versioning § Extension Negotiation](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning#extension-negotiation)                                                                                                                                      |
| "Handle unsupported [JSON Schema] dialects gracefully by returning an appropriate error"              | MUST        | None.            | [Base Protocol § Implementation Requirements](https://modelcontextprotocol.io/specification/2026-07-28/basic/index#implementation-requirements)                                                                                                                            |
| Reject `requestState` that fails integrity; reject replay, expiry, and request-mismatch presentations | MUST        | None.            | [MRTR § Server Requirements (Basic Workflow)](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr#server-requirements-basic-workflow)                                                                                                             |

### Status-only semantics are invisible outside of HTTP

We map all error conditions to both in-band JSON-RPC data and the HTTP transport as
stdio has no error channel above JSON-RPC, clients "SHOULD NOT assume `stderr` output
indicates error conditions", and exit codes are never mentioned. Further generalized,
custom transport over any reliable byte stream "SHOULD reuse the stdio framing"
(`basic/transports`). Thus, our mapping covers HTTP status codes and metadata, but
must include in-band error data to match.

### Where in-band codes exist, they are overloaded

HTTP status 400 carries ten distinct conditions using four different codes. `-32602`
covers at least eleven documented conditions with untyped data and no sub-code, with
its listed examples being strings ("Unknown tool: invalid_tool_name", "Invalid cursor").
Error message strings are not a machine interface. A client receiving `-32602` today
cannot distinguish "your parameters are wrong" from "your continuation token
expired", these conditions requiring different responses. The two codes that do
carry typed data, `-32021` (MissingRequiredClientCapabilityError) and `-32022`
(UnsupportedProtocolVersionError), are the two clients can more easily act on.

### SDK Divergence

SEP-3304's survey of ten SDKs shows the result for a single status, with an HTTP 429
being sometimes preserved as a structured field, collapsed to -32603, stringified into a
message, classified as transient alongside a 500, or silently dropped. This divergence
is not a bug in the implementation of the standard by SDKs, as it stems from a lack of
specificity in the standard itself.

## Specification

### 1. Definitions

**Condition.** A named failure circumstance defined by the MCP specification, for example,
"the request names an RPC method the server does not implement," or "the client presented
an expired cursor." Conditions, not HTTP status codes, are the unit of this registry.
One registry entry may represent a circumstance HTTP would express through several
different statuses, and one status may carry several distinct conditions.

**Protocol error.** A failure of the MCP exchange itself, reported as a JSON-RPC error
response containing an `error` member carrying an integer `code`, a human-readable
`message`, and optional `data` ([Base Protocol § Error Responses](https://modelcontextprotocol.io/specification/2026-07-28/basic/index#error-responses)).
Protocol errors are the subject of this registry.

**Tool execution error.** A failure occurring inside a successfully executed request, for
instance an upstream API failure, invalid input the model can correct, or a business-logic
refusal. These are reported in the tool result with `isError: true` ([Tools § Error Handling](https://modelcontextprotocol.io/specification/2026-07-28/server/tools#error-handling);
[SEP-1303](https://modelcontextprotocol.io/seps/1303-input-validation-errors-as-tool-execution-errors)).
A tool execution error is not a protocol error, it MUST NOT be reported as a JSON-RPC
error response, and it does not alter the HTTP status, which remains that of a
successful exchange. Nothing in this registry applies to tool execution errors.
Each error definition in §7 carries a boundary rule restating this for its condition.

**Local error.** An error an implementation generates about its own operation or its own
observation of the transport path, for instance an SDK-level timeout, a failed connection,
or an HTTP status received with no parsable JSON-RPC body. Local errors are not received
from the peer, and implementations surfacing them in JSON-RPC-shaped structures MUST
ensure they "cannot be mistaken for errors received from the peer" ([Base Protocol § Error Codes](https://modelcontextprotocol.io/specification/2026-07-28/basic/index#error-codes)).
This registry assigns no codes to local errors.

**Registry code.** A JSON-RPC error code with a row in the registry (§2): the standard
JSON-RPC 2.0 codes as MCP uses them (`-32700`, `-32600` to `-32603`), and codes the MCP
specification allocates from its reserved sub-range (`-32020` to `-32099`).

**Bound status.** The single HTTP status a registry row assigns to its code. On
Streamable HTTP, the bound status is what a conforming server sends when emitting that
code (§3). It is a coarse duplicate of the condition for the benefit of generic HTTP
components, such as caches, gateways, retry middleware, and dashboards. It is never
the authoritative statement of the condition; only the body is (§3).

**Generic fallback.** A registry row designated in §2 as the code for a condition that
has no specific entry, selected by fault class. There exists one for client-caused
conditions, one for server-caused conditions not known to be transient, and one for
transient unavailability.

**Retry classification.** The registry column stating whether and how a client may
retry after receiving a code, drawn from the closed vocabulary in §5. The classification
is registry metadata, derivable from the code, and it is not a wire field.

**Established response.** An HTTP response whose status line and header section have
already been sent, for instance, a `text/event-stream` response that has begun streaming.
Once a response is established, no status code can be sent or changed. An error
discovered afterwards can only be delivered in-band (§3).

**Intermediary.** HTTP infrastructure on the path between a client and an MCP server, for
instance reverse proxies, API gateways, CDNs, and load balancers, some of which may
reject or answer requests with statuses of their own, and are "not required to return
a JSON-RPC error response" ([Streamable HTTP § Server Validation](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http#server-validation)).
A status of intermediary origin is indistinguishable from an origin server's status
except by the response body, which motivates the included client rules (§3).

### 2. The Error Registry

The registry below is the normative mapping between conditions, JSON-RPC codes, bound
statuses, retry classifications, and `data` shapes. Upon acceptance, it is to be recorded
alongside the error-code definitions in the specification and schema and it will become,
rather than prose distributed across the specification's pages, the authoritative statement
of these assignments. Full shapes and rules for each row are given in §7. Every bound
status is drawn from the closed status set defined in §3.

Codes marked with an asterisk are illustrative placeholders: the specification allocates
codes from the reserved sub-range sequentially ([Base Protocol § Error Codes](https://modelcontextprotocol.io/specification/2026-07-28/basic/index#error-codes)),
and the final integers are assigned at acceptance. `-32023` is claimed by draft [SEP-3304](https://modelcontextprotocol.io/seps/3304-rate-limited-errors)
and is used here as that SEP defines it.

| Name                              | Code      | HTTP status | Retry classification | `error.data`                                                                           | Defined in                                                                                                                                                                                                        |
|-----------------------------------|-----------|-------------|----------------------|----------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ParseError`                      | `-32700`  | `400`       | retry-after-change   | none                                                                                   | [JSON-RPC 2.0 §5.1](https://www.jsonrpc.org/specification#error_object); [§7.1](#71-parseerror-and-invalidrequest)                                                                                                |
| `InvalidRequest`                  | `-32600`  | `400`       | retry-after-change   | none                                                                                   | [JSON-RPC 2.0 §5.1](https://www.jsonrpc.org/specification#error_object); [§7.1](#71-parseerror-and-invalidrequest)                                                                                                |
| `MethodNotFound`                  | `-32601`  | `404`       | do-not-retry         | optional `{ method?, requiredCapability? }`                                            | [JSON-RPC 2.0 §5.1](https://www.jsonrpc.org/specification#error_object); [§7.2](#72-methodnotfound)                                                                                                               |
| `InvalidParams`                   | `-32602`  | `400`       | retry-after-change   | optional `{ reason?, uri?, name?, field? }`                                            | [JSON-RPC 2.0 §5.1](https://www.jsonrpc.org/specification#error_object); [§7.3](#73-invalidparams)                                                                                                                |
| `InternalError`                   | `-32603`  | `500`       | do-not-retry         | optional `{ errorId? }`                                                                | [JSON-RPC 2.0 §5.1](https://www.jsonrpc.org/specification#error_object); [§7.4](#74-internalerror)                                                                                                                |
| `HeaderMismatch`                  | `-32020`  | `400`       | retry-after-change   | none                                                                                   | [current schema](https://modelcontextprotocol.io/specification/2026-07-28/schema#headermismatcherror); [§7.5](#75-headermismatch-missingrequiredclientcapability-and-unsupportedprotocolversion)                  |
| `MissingRequiredClientCapability` | `-32021`  | `400`       | retry-after-change   | required `{ requiredCapabilities }`                                                    | [current schema](https://modelcontextprotocol.io/specification/2026-07-28/schema#missingrequiredclientcapabilityerror); [§7.5](#75-headermismatch-missingrequiredclientcapability-and-unsupportedprotocolversion) |
| `UnsupportedProtocolVersion`      | `-32022`  | `400`       | retry-after-change   | required `{ supported, requested }`                                                    | [current schema](https://modelcontextprotocol.io/specification/2026-07-28/schema#unsupportedprotocolversionerror); [§7.5](#75-headermismatch-missingrequiredclientcapability-and-unsupportedprotocolversion)      |
| `RateLimited`                     | `-32023`  | `429`       | retry-after-delay    | required `{ retryAfterMs }`                                                            | [SEP-3304](https://modelcontextprotocol.io/seps/3304-rate-limited-errors); [§7.6](#76-ratelimited)                                                                                                                |
| `Unavailable`                     | `-32024`* | `503`       | retry-after-delay    | required `{ reason, retryAfterMs }`; optional `{ notProcessed?, requiresUserAction? }` | this SEP, [§7.7](#77-unavailable)                                                                                                                                                                                 |
| `RequestTooLarge`                 | `-32025`* | `400`       | retry-after-change   | required `{ part }`; optional `{ limitBytes?, actualBytes?, location? }`               | this SEP, [§7.8](#78-requesttoolarge)                                                                                                                                                                             |
| `StaleState`                      | `-32026`* | `400`       | retry-after-change   | required `{ kind, reason }`; optional `{ restart?, retryAfterMs? }`                    | this SEP, [§7.9](#79-stalestate)                                                                                                                                                                                  |
| `UnsupportedFeature`              | `-32027`* | `400`       | retry-after-change   | required `{ kind, feature }`; optional `{ supported? }`                                | this SEP, [§7.10](#710-unsupportedfeature)                                                                                                                                                                        |

The registry also records, for completeness, the code space it does not use. These
restate the existing policy of [Base Protocol § Error Codes](https://modelcontextprotocol.io/specification/2026-07-28/basic/index#error-codes)
and change nothing:

| Range or code        | Standing                                                                                                                                                                       |
|----------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `-32002`             | Retired (resource not found, 2025-11-25 and earlier). Servers MUST NOT emit it; clients SHOULD continue accepting it from servers implementing earlier versions. Never reused. |
| `-32042`             | Retired (URL elicitation, 2025-11-25 only). MUST NOT be emitted; never reused.                                                                                                 |
| `-32000` to `-32019` | Legacy sub-range. No new allocations; receivers MUST NOT assume any cross-implementation meaning.                                                                              |

#### 2.1 Generic fallbacks

A server encountering a condition with no specific registry entry MUST use the fallback
row for its fault class. These fallbacks are what keep the registry small, as a new
condition needs a new code only when the client's corrective action differs from every
existing row's, not merely because the condition is distinct.

| Condition class                           | Fallback                  | HTTP status |
|-------------------------------------------|---------------------------|-------------|
| Client-caused, no specific entry          | `-32602` `InvalidParams`  | `400`       |
| Server-caused, not known to be transient  | `-32603` `InternalError`  | `500`       |
| Server-caused, known to be transient      | `-32024`* `Unavailable`   | `503`       |
| Bytes that do not parse as JSON           | `-32700` `ParseError`     | `400`       |
| JSON that is not a valid JSON-RPC request | `-32600` `InvalidRequest` | `400`       |

#### 2.2 Conditions deliberately without registry entries

The following carry no registry code, each for reasons given in §8: authorization
failures (`401`, `403`, and the malformed-authorization `400`), accepted and rejected
notifications (`202` and `400`), legacy HTTP verbs on the MCP endpoint (`405`), client
cancellations and local timeouts (no wire representation by design), and tool execution
errors of every kind (`isError: true`, per §1).

### 3. Transport Binding Rules

These rules bind the registry to the transports. They define how a protocol error is
represented on every transport, which HTTP status accompanies it on Streamable HTTP, and
how clients interpret responses in the presence of intermediaries. Rules are grouped by
the party they bind.

#### 3.1 Server rules

| ID   | Rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
|------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| TR-1 | For every protocol error, on every transport, the server MUST send a JSON-RPC error response whose `code` is a registry code. Where no specific entry applies, the server MUST use the generic fallback for the condition class (§2.1).                                                                                                                                                                                                                                                                                                                                                                         |
| TR-2 | On Streamable HTTP, the response status MUST be the bound status of the code (§2). For an error whose code has no registry row, for instance an application-defined code, the status MUST be `400` for a client-caused condition and `500` for a server-caused one.                                                                                                                                                                                                                                                                                                                                             |
| TR-3 | The set of statuses that may carry a JSON-RPC error response is closed: `400`, `404`, `429`, `500`, and `503`. Servers MUST NOT use any other status for that purpose. `401`, `403`, and `405` remain status-only signals and carry no registry code (§8).                                                                                                                                                                                                                                                                                                                                                      |
| TR-4 | Servers MUST NOT use a `2xx` status to carry a JSON-RPC error response, except within an established response, per TR-5.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| TR-5 | An error discovered after the response is established MUST be delivered as a JSON-RPC error object within the stream. The status is necessarily the already-sent `200`.                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| TR-6 | On Streamable HTTP, a response carrying a JSON-RPC result MUST use status `200 OK`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| TR-7 | On Streamable HTTP, a server rejecting a JSON-RPC notification it cannot accept MUST respond with status `400 Bad Request`, replacing the open-ended "an HTTP error status code (e.g., `400 Bad Request`)" of [Streamable HTTP § Sending Messages](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http#sending-messages), and SHOULD include a JSON-RPC error response with `id` omitted whose `code` is the applicable registry code. On stdio, the server MUST NOT respond to a notification ([JSON-RPC 2.0 §4.1](https://www.jsonrpc.org/specification#notification)). |

#### 3.2 Client rules

| ID    | Rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
|-------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| TR-8  | When a response carries a parsable JSON-RPC error object, clients MUST determine the condition from `error.code` and `error.data`, and MUST NOT infer it from the HTTP status. This applies equally to an error object delivered within an established response (TR-5).                                                                                                                                                                                                                                                                                                   |
| TR-9  | When a `4xx` or `5xx` status arrives with no parsable JSON-RPC error object, clients MUST treat the failure as a local error (§1) of unknown provenance. Clients MUST apply the class fallback of [RFC 9110 §15](https://www.rfc-editor.org/rfc/rfc9110.html#section-15), treating an unrecognized status as the `x00` of its class, and MUST NOT attribute any registry code to the peer.                                                                                       |
| TR-10 | Clients MUST attempt the deprecated HTTP+SSE fallback probe of [Streamable HTTP § Backward Compatibility](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http#backward-compatibility) only when the received status is literally `400`, `404`, or `405`. Clients MUST NOT use the `x00` class fallback of TR-9 to decide whether to probe, and MUST NOT probe when the response carries a `Retry-After` header or a `429` or `5xx` status. |
| TR-11 | A JSON-RPC error whose `code` lies in `-32020` to `-32099` but is unknown to the client MUST be treated as do-not-retry, unless `error.data.retryAfterMs` is present, in which case the client MAY treat it as retry-after-delay, subject to jitter and clamping (§5). Clients MUST ignore `data` members they do not recognize.                                                                                                                                                 |

Without TR-10, a status from infrastructure, for instance a `429` from a CDN rate
limiter, is read as `400` under the class fallback by a client that does not recognize
it, and the current specification text then permits a fallback to the deprecated
HTTP+SSE transport. TR-10 closes that downgrade path.

#### 3.3 Shared and intermediary rules

| ID    | Rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
|-------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| TR-12 | `error.message` is human-readable prose. Clients MUST NOT parse it or branch on its content. Servers MUST NOT vary `error.code`, or any machine-readable member of `error.data`, with the natural language of the response.                                                                                                                                                                                                                                                  |
| TR-13 | The existing intermediary carve-out is retained unchanged: intermediaries MUST return an appropriate HTTP error status for validation failures but "are not required to return a JSON-RPC error response" ([Streamable HTTP § Server Validation](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http#server-validation)). Intermediaries MUST NOT synthesize a JSON-RPC error object attributing a registry code to the origin server. |
| TR-14 | Where an HTTP status and a JSON-RPC error object are both present, the body governs. Servers MUST NOT emit a status and a body that the registry maps to different conditions. Clients encountering such a disagreement MUST act on the body, and MAY surface the inconsistency.                                                                                                                                                                                             |

#### 3.4 Applicability across transports

TR-1, TR-8, TR-11, TR-12, and TR-14 apply verbatim on every transport. TR-2 through
TR-7, TR-9, TR-10, and TR-13 are conditional on Streamable HTTP and have no effect on
stdio or on custom byte-stream bindings. The semantics live in the in-band layer that
every binding has, and the status layer only mirrors them where it exists.

### 4. Cache Interaction

HTTP cache behavior is inherited from HTTP by reference. Per [RFC 9205 §4.6](https://www.rfc-editor.org/rfc/rfc9205.html#section-4.6),
this specification does not restate the cache semantics of any status code. Three rules are
needed because the inherited behavior is not always ideal.

| ID   | Rule                                                                                                                                                                                                                                                                                                                           |
|------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| CA-1 | Servers SHOULD send `Cache-Control: no-store` on every HTTP response carrying a JSON-RPC error object.                                                                                                                                                                                                                         |
| CA-2 | Servers MUST send `Cache-Control: no-store` on any non-`2xx` response whose status is heuristically cacheable under [RFC 9110 §15.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.1). For the bindings in this specification, these are `404` (`-32601`, §7.2) and the legacy-verb `405` (§8).                       |
| CA-3 | Servers MUST NOT attach explicit freshness information, or a `Content-Location` field equal to the request target, to a response carrying a JSON-RPC error object. These are the two conditions that make a response to POST cacheable at all ([RFC 9110 §9.3.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.3.3)).  |

The hazardous place is `405`. It is heuristically cacheable, and MCP binds it to `GET`
and `DELETE` on the MCP endpoint, whose responses are ordinarily cacheable, so without
CA-2 a shared cache may legitimately store a `405` and serve it to later clients,
including clients that would have been served correctly. The `404` case in CA-2 is
for defense-in-depth rather than a live hazard, as it only arises from `POST`, which is
cacheable only with explicit freshness information and a matching `Content-Location`,
which CA-3 forbids. This rule then exists to protect deployments that attach freshness headers
globally.

`200` is also on the heuristic list and is deliberately outside CA-2. Successful MCP
responses utilize `POST`, where the heuristic path does not exist, and cache policy for
successful results belongs to the caching utility (`ttlMs`, `cacheScope`;
[SEP-2549](https://modelcontextprotocol.io/seps/2549-TTL-for-list-results)) and the
primitive-versioning track rather than to an error registry. The same scoping covers the
established-response case of TR-5, namely when an error delivered mid-stream necessarily
travels in a `200` whose header section was sent long before the error existed, so no
directive can be added retroactively. The protections there are the method gate of
[RFC 9110 §9.3.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.3.3) and CA-3,
which a server MUST therefore honor at header time for any response that may come to
carry an error.

The remaining directions are favorable and need no rules. `400`, `500`, and `503` are
not heuristically cacheable, and `429` responses "MUST NOT be stored by a cache"
([RFC 6585 §4](https://www.rfc-editor.org/rfc/rfc6585.html#section-4)), a prohibition a
`RateLimited` binding inherits with no MCP restatement needed.

### 5. Retry Classification

Every registry row carries exactly one value from the following closed vocabulary. The
classification states whether and how a client may retry after receiving the code, and
is the registry's answer to the roadmap requirement that each error carry retry
guidance.

| Value              | Meaning                                                                 | Client behavior                                                                                                                                                                                                                                                                                                                        |
|--------------------|-------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| retry-now-safe     | The request was provably not applied, and no delay is indicated.        | MAY retry immediately, even though the underlying HTTP method is non-idempotent. Reserved: no error defined by this specification uses it today. It exists so that a future condition with the "not processed" shape of HTTP/2 `REFUSED_STREAM` ([RFC 9113 §8.7](https://www.rfc-editor.org/rfc/rfc9113.html#section-8.7)) has a slot. |
| retry-after-delay  | The condition is transient; the same request will likely succeed later. | SHOULD retry after `data.retryAfterMs` (§6), with jitter, clamped to a locally configured maximum.                                                                                                                                                                                                                                     |
| retry-after-change | The request as sent will never succeed.                                 | MUST NOT retry the request unchanged; MUST change the request, or the client state it depends on, first.                                                                                                                                                                                                                               |
| do-not-retry       | Retrying cannot help and may cause harm.                                | MUST NOT retry automatically; surface the failure.                                                                                                                                                                                                                                                                                     |
| re-auth-then-retry | The credential is the problem.                                          | SHOULD obtain a suitable credential, per the `WWW-Authenticate` challenge, and retry; SHOULD bound the number of attempts. Used only by the status-only authorization conditions (§8), which carry no registry code.                                                                                                                   |

#### 5.1 The classification is registry metadata, not a wire field

The classification is derivable from `error.code` and is deliberately not carried in
`error.data`. A wire copy would duplicate a fact the code already determines, and
[RFC 9457 §5](https://www.rfc-editor.org/rfc/rfc9457.html#section-5) names what such
duplication costs, namely "the possibility of disagreement between the two. Their relative
precedence is not clear." It would also be attacker-influenced input inviting servers,
or intermediaries, to mark unsafe conditions retryable. The forward-compatibility need a
wire field would serve, namely what a client does with a code it has never seen, is met
by TR-11: an unknown code from the reserved sub-range defaults to do-not-retry, with
`retryAfterMs` as the single opt-in escape to retry-after-delay.

#### 5.2 Usefulness versus safety

The classification states whether a retry is likely to be useful. Whether an automatic
retry is safe is a separate question, because MCP requests ride `POST`, which is
neither safe nor idempotent, and a client "SHOULD NOT automatically retry a request with
a non-idempotent method unless it has some means to know that the request semantics are
actually idempotent ... or some means to detect that the original request was never
applied" ([RFC 9110 §9.2.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2)).
That means is `data.notProcessed` (§6): a retry-after-delay error whose sender asserts
`notProcessed: true` may be retried automatically after the delay; one without the
assertion SHOULD NOT be retried automatically unless the client knows the request is
idempotent, or the operator has opted in.

### 6. Common `data` Members

Two members are defined once and are available to the `data` of every registry error.
Individual error definitions state whether each is required, optional, or absent for
their condition, and add their own members; §7 gives each full shape.

```ts
/**
 * Members that MAY appear in the `data` of any error defined by this specification.
 * Individual error definitions MAY make them required, and MAY add their own members.
 * Receivers MUST ignore members they do not recognize.
 */
export interface CommonErrorData {
  /**
   * Milliseconds the client SHOULD wait before the retry, or restart, that the
   * error's definition contemplates. On a code unknown to the client, the presence
   * of this member is the opt-in to retry-after-delay handling (TR-11).
   * @minimum 0
   */
  retryAfterMs?: number;

  /**
   * True only if the sender can guarantee the request had no observable effect.
   * Senders MUST NOT set this to true otherwise. When true, a client MAY retry
   * the request automatically even though the underlying transport request is
   * not idempotent (§5.2).
   */
  notProcessed?: boolean;
}
```

| ID   | Rule                                                                                                                                                                                                                                                                                         |
|------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| CM-1 | Servers MUST NOT set `notProcessed: true` unless they can guarantee the request had no observable effect.                                                                                                                                                                                    |
| CM-2 | Durations in `error.data` are integer milliseconds with `@minimum 0`, following the established `ttlMs` and `pollIntervalMs` convention ([SEP-2549](https://modelcontextprotocol.io/seps/2549-TTL-for-list-results); [SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension)). |
| CM-3 | An individual error definition MAY strengthen a common member from optional to required for its condition, and MUST NOT weaken, rename, or repurpose one.                                                                                                                                    |

`notProcessed` is modeled on the only comparable guarantee in the HTTP protocol suite,
HTTP/2's handling of refused streams. Quote: "Requests that have not been processed have
not failed; clients MAY automatically retry them, even those with non-idempotent methods,"
paired with the matching obligation, "A server MUST NOT indicate that a stream has not
been processed unless it can guarantee that fact" ([RFC 9113 §8.7](https://www.rfc-editor.org/rfc/rfc9113.html#section-8.7)).
CM-1 is that obligation, imported. HTTP itself offers no equivalent for a status code:
`Retry-After` carries no processing guarantee, and outside HTTP/2's connection machinery
only `421` and `425` assert one. Without this member, a conforming client could not
automatically retry any MCP request at all (§5.2).

`retryAfterMs` is attacker-influenced input wherever it appears; the jitter and clamp
requirements of the retry-after-delay row (§5) apply to every use of it.

### 7. Error Definitions

Each definition below gives the condition, the shape of `error.data` where one exists,
party-scoped rules, and the boundary with tool execution errors. Bound statuses restate
the registry (§2) and are everywhere subject to TR-5's established-response exception,
which individual rules do not restate. Rules whose party is *Specification* are text
changes this SEP makes to the specification rather than conformance requirements on
implementations.

#### 7.1 ParseError and InvalidRequest

`-32700 ParseError` is the condition that the request bytes do not parse as JSON;
`-32600 InvalidRequest` is the condition that parsed JSON is not a valid JSON-RPC
request object, for instance a wrong or missing `jsonrpc` member, a missing `method`, or
wrong member types. Both codes exist today and work on every transport; only their
statuses were unstated. Neither defines `data` members. Retry classification:
retry-after-change.

| ID   | Party         | Rule                                                                                                                                                                                                                                                                   |
|------|---------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| PE-1 | Server        | For HTTP, servers MUST respond with status `400` when emitting `-32700` or `-32600`.                                                                                                                                                                                   |
| PE-2 | Server        | Where the request could not be parsed far enough to recover the JSON-RPC `id`, servers MUST omit `id` from the error response, as the transport already permits for rejected notifications and invalid `Origin` responses.                                             |
| PE-3 | Server        | Servers MUST NOT echo the unparsable input, or any fragment of it, in `message` or `data`.                                                                                                                                                                             |
| PE-4 | Specification | The transport page SHOULD name `-32600`'s trigger explicitly. It is currently the only error type in the schema with no example, no narrative, and no page instructing anyone to emit it, and a defined code that nothing tells anyone to emit is a code nobody emits. |
| PE-5 | Client        | Clients MUST NOT retry the request unchanged, and MUST NOT treat these statuses as legacy-transport signals except per TR-10.                                                                                                                                          |

These conditions cannot arise inside a tool, so no boundary rule is needed. On stdio the
two codes are the only signal available for a malformed line, which is why their unbound
status never caused visible harm there and why binding it costs nothing.

#### 7.2 MethodNotFound

`-32601 MethodNotFound` covers two conditions: a genuinely unknown RPC method, and a
method gated behind a server capability the server did not advertise, for instance
calling `prompts/list` when the `prompts` capability was not advertised. The
specification today binds `404` to the first condition only; this SEP extends the
binding to both, because one code with two conditions and a status on only one of them
is the inconsistency a registry exists to remove. Retry classification: do-not-retry.

```ts
export const METHOD_NOT_FOUND = -32601;

/**
 * The requested method does not exist or is not available on this server, either
 * because it is genuinely unknown or because it is gated behind a server capability
 * the server did not advertise. For HTTP, the response status code MUST be
 * `404 Not Found` in both cases.
 */
export interface MethodNotFoundError extends Error {
  code: typeof METHOD_NOT_FOUND;
  data?: {
    /** The method name that was not found. */
    method?: string;
    /** The server capability that would enable the method, when capability-gated. */
    requiredCapability?: string;
  };
}
```

| ID   | Party         | Rule                                                                                                                                                                                                                                 |
|------|---------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| MN-1 | Server        | For HTTP, servers MUST respond with status `404` when emitting `-32601`, including for the capability-gated condition.                                                                                                               |
| MN-2 | Server        | Servers MUST send `Cache-Control: no-store` with these responses (CA-2).                                                                                                                                                             |
| MN-3 | Server        | Servers SHOULD include `data.requiredCapability` for the capability-gated condition, so a client can distinguish "no such method" from "not enabled here". Servers treating their capability configuration as sensitive MAY omit it. |
| MN-4 | Specification | The specification SHOULD use one name for `-32601` throughout; the completion page currently glosses it as "Capability not supported" while the schema calls it "Method not found".                                                  |
| MN-5 | Client        | Clients MUST NOT retry automatically, and MUST NOT treat a `404` as a legacy-transport signal when its body carries `-32601`, per the existing rule that the body distinguishes a modern server from a legacy one.                   |

The boundary with tools is unchanged and already correct in the specification: errors in
finding a tool, or in the server's support for tool calls at all, are protocol errors;
only errors from the tool's own execution are tool execution errors.

#### 7.3 InvalidParams

`-32602 InvalidParams` is the generic client-fault code and the widest one, covering at
least eleven documented conditions today with untyped `data`. This SEP binds `400` for
every `-32602` condition, where today only the missing-`_meta` condition is bound, and
adds an optional typed `data` whose `reason` member is an open vocabulary. Registry-defined
`reason` values: `"unknown_tool"`, `"invalid_tool_arguments"`, `"unknown_prompt"`,
`"missing_prompt_argument"`, `"resource_not_found"`, `"invalid_log_level"`,
`"missing_meta"`, `"elicitation_mode_unsupported"`, `"sampling_content_invalid"`.
Retry classification: retry-after-change.

```ts
export const INVALID_PARAMS = -32602;

/**
 * The method parameters are invalid or malformed. For HTTP, the response status
 * code MUST be `400 Bad Request`.
 */
export interface InvalidParamsError extends Error {
  code: typeof INVALID_PARAMS;
  data?: {
    /**
     * Open-vocabulary discriminator for which validation failed. Receivers MUST
     * ignore values they do not recognize.
     */
    reason?: string;
    /** The resource URI, when `reason` is `"resource_not_found"`. */
    uri?: string;
    /** The tool or prompt name, when the failure identifies one. */
    name?: string;
    /** JSON pointer to the offending member, when the failure identifies one. */
    field?: string;
  };
}
```

| ID   | Party  | Rule                                                                                                                                                                                                            |
|------|--------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| IP-1 | Server | For HTTP, servers MUST respond with status `400` when emitting `-32602`, for every condition.                                                                                                                   |
| IP-2 | Server | Servers SHOULD include `data.reason`, and MUST use a registry-defined value where one applies.                                                                                                                  |
| IP-3 | Server | Servers MUST include `data.uri` when `reason` is `"resource_not_found"`, promoting the field the specification's example already shows but does not schematize.                                                 |
| IP-4 | Server | Servers MUST NOT emit `-32602` for an invalid or expired pagination cursor, an unknown or expired task identifier, or rejected multi-round-trip request state; those conditions are `-32026 StaleState` (§7.9). |
| IP-5 | Server | Servers MUST NOT emit `-32602` for argument content that fails validation against a tool's own `inputSchema`; that is a tool execution error, per the boundary below.                                           |
| IP-6 | Client | Clients MUST ignore unrecognized `reason` values and unrecognized `data` members, and MUST NOT branch on `message` (TR-12).                                                                                     |
| IP-7 | Client | Clients MUST NOT retry the request unchanged.                                                                                                                                                                   |

The boundary with tools, which the specification currently states in two conflicting
ways, is drawn at the schema line: a request that fails validation against the
*protocol* schema, for instance a malformed `CallToolRequest`, a missing required
`_meta` member, or an `arguments` member of the wrong type, is a protocol error
(`-32602`); a valid `CallToolRequest` whose argument content fails the tool's own
`inputSchema`, or fails during execution, is a tool execution error (`isError: true`),
where SEP-1303 placed it so the model can see and correct it. An unknown tool name
stays `-32602`, since a model cannot invent a tool the server does not have. The
`"invalid_tool_arguments"` reason value accordingly applies only to protocol-schema
failures of the `arguments` member itself, never to content-level failures against an
`inputSchema` (IP-5).

`uri`, `name`, and `field` reflect attacker-influenced input back to the client: clients
MUST NOT dereference `uri` or render it as a live link. A server enforcing
per-principal resource visibility MAY report `"resource_not_found"` for a resource the
caller is not permitted to see, and MUST NOT use a distinguishable `reason` for the
permission case, matching the refusal-masking that
[RFC 9110 §15.5.4](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.4) permits.

#### 7.4 InternalError

`-32603 InternalError` is today a sink, as it is prescribed at SHOULD level for resources,
prompts, completion, and logging, has no bound status, and absorbs conditions that
belong elsewhere. This SEP binds `500` and gives the code a sharp meaning: an
unexpected condition, not known to be transient, that the client cannot act on. Without
this classification, every transient condition keeps collapsing into `-32603` and clients
keep guessing. Retry classification: do-not-retry.

```ts
export const INTERNAL_ERROR = -32603;

/**
 * An unexpected condition on the receiver, not known to be transient, that the
 * client cannot act on. Where the condition IS known to be transient, senders MUST
 * use Unavailable; where it is a rate limit, RateLimited. For HTTP, the response
 * status code MUST be `500 Internal Server Error`.
 */
export interface InternalError extends Error {
  code: typeof INTERNAL_ERROR;
  data?: {
    /**
     * An opaque identifier the operator can correlate with server-side logs.
     * MUST NOT encode any detail of the failure.
     */
    errorId?: string;
  };
}
```

| ID   | Party  | Rule                                                                                                                                                                                   |
|------|--------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| IE-1 | Server | For HTTP, servers MUST respond with status `500` when emitting `-32603`.                                                                                                               |
| IE-2 | Server | Servers MUST NOT emit `-32603` for a condition they know to be transient (`-32024`, §7.7), for a rate limit (`-32023`, §7.6), or for any condition with a specific registry entry.     |
| IE-3 | Server | Servers MUST NOT include stack traces, internal host names, query text, credentials, or upstream error bodies in `message` or `data`; `errorId` is the sanctioned correlation channel. |
| IE-4 | Server | Servers MUST NOT emit `-32603` for a failure originating inside a tool; those remain tool execution errors.                                                                            |
| IE-5 | Client | Clients MUST NOT retry `-32603` automatically.                                                                                                                                         |
| IE-6 | Client | Clients SHOULD surface `errorId` to the operator verbatim and MUST NOT parse it.                                                                                                       |

`500` is the class fallback for every unrecognized `5xx` and for invalid status codes,
and it is the status most likely to be synthesized by a crashing framework or a sidecar,
so a client cannot infer from a bodiless `500` that the MCP server even ran. TR-9 governs
that case. Note that this binding changes shipped behavior: current SDK server transports
deliver handler-produced `-32603` inside a `200`; see Backward Compatibility.

#### 7.5 HeaderMismatch, MissingRequiredClientCapability, and UnsupportedProtocolVersion

`-32020`, `-32021`, and `-32022` are already completely bound: `400` at MUST level for
each, with required typed `data` on `-32021` (`requiredCapabilities`) and `-32022`
(`supported`, `requested`). The registry records them unchanged. They are also the
model this SEP generalizes from, as the two codes with required typed `data` are the two
that clients can act on without guessing, and `-32022` carries the specification's only
defined retry contract, select a mutually supported version from `data.supported` and
retry.

| ID   | Party         | Rule                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
|------|---------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| HM-1 | Specification | The schema doc comment for `HeaderMismatch` and the transport page SHOULD state that this condition can only arise on a transport with a header layer, and therefore never on stdio. The reserved sub-range thus knowingly contains a transport-conditional code; stating it converts an accident of history into policy, and gives later transport-conditional members, for instance `RequestTooLarge`'s `"headers"` part (§7.8), a precedent to lean on. |

#### 7.6 RateLimited

`-32023 RateLimited` is defined by [SEP-3304](https://modelcontextprotocol.io/seps/3304-rate-limited-errors)
and enters the registry as that SEP specifies it, with the deltas this registry imposes:

- **`data` shape.** The registry records `required { retryAfterMs }` only. The quota
  members of the SEP-3304 draft (`limit`, `remaining`) are not part of the registry row:
  their HTTP counterparts are unregistered field names whose defining draft has not
  stabilized, and quota reporting can be added by amendment if that work completes.
- **Status binding.** The registry binds `429`; SEP-3304's flat requirement to respond
  `429` is subject to TR-4 and TR-5, so a rate limit encountered after the response is
  established is delivered in-stream rather than making the correct behavior
  non-conformant.
- **Retry.** Classification retry-after-delay; the jitter and clamp requirements of §5
  apply. A server that emits `-32023` has, definitionally, not executed the request, so
  the retry-safety guarantee of §5.2 holds by rule rather than requiring
  `data.notProcessed`; SEP-3304 as amended states the matching server obligation.
- **Bodiless `429`.** A `429` with no parsable JSON-RPC error object is a local error
  under TR-9, MUST NOT be reported as a peer-sent `-32023`, and MUST NOT trigger the
  legacy-transport probe (TR-10). `Retry-After`, if present, MAY inform the local delay.
- **Caching.** `429` responses inherit RFC 6585 §4's storage prohibition by reference.

The boundary rule is from SEP-3304's own, namely that a rate limit encountered by an
upstream API inside a tool is a tool execution error; and `-32023` is for a limit the MCP
server itself applies to the caller.

#### 7.7 Unavailable

`-32024 Unavailable` (illustrative) is the condition that the receiver cannot process
the request now, but the condition is transient. It covers the `503`-shaped conditions
(overload, maintenance, shutdown), the `507`-shaped condition (capacity exhaustion), and
the server-side half of the deadline condition, where the receiver abandons a request
against its own time budget. It is also the generic fallback for transient server
faults (§2.1). Retry classification: retry-after-delay.

The current specification is weakest exactly here. On unexpected termination a stdio
client is told to restart the process, with no code, no reason, and no backoff guidance
([stdio § Unexpected Termination](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio#unexpected-termination)),
and a server shutting down cleanly has no way to say "I am going away, come back in five
seconds". `-32024` with `reason: "shutting_down"` gives it one, and it is the only such
mechanism available on a pipe.

```ts
export const UNAVAILABLE = -32024;

/**
 * The receiver cannot process the request now, but the condition is transient.
 * This error is for the receiver's own condition; a dependency failure encountered
 * inside a tool is a tool execution error. For HTTP, the response status code MUST
 * be `503 Service Unavailable`.
 */
export interface UnavailableError extends Error {
  code: typeof UNAVAILABLE;
  data: {
    /**
     * Why the receiver is unavailable. Receivers MUST treat values they do not
     * recognize as `"other"`.
     */
    reason:
      | "overloaded"              // transient load shedding
      | "maintenance"             // planned unavailability
      | "shutting_down"           // the process is terminating
      | "dependency_unavailable"  // a dependency of the protocol layer, not of a tool
      | "deadline_exceeded"       // the receiver abandoned the request against its own budget
      | "capacity"                // storage or quota exhaustion; see requiresUserAction
      | "other";
    /** Milliseconds the client SHOULD wait before retrying. @minimum 0 */
    retryAfterMs: number;
    /**
     * True only if the receiver can guarantee the request had no observable effect
     * (§6, CM-1). MUST NOT be true when reason is "deadline_exceeded", where the
     * outcome is by definition unknown.
     */
    notProcessed?: boolean;
    /**
     * True if an automatic retry is inappropriate and the retry should be gated on
     * a fresh user action. Default false.
     */
    requiresUserAction?: boolean;
  };
}
```

| ID   | Party  | Rule                                                                                                                                                                                               |
|------|--------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| UA-1 | Server | Servers MUST include both `reason` and `retryAfterMs` whenever they emit `-32024`.                                                                                                                 |
| UA-2 | Server | For HTTP, servers MUST respond with status `503`.                                                                                                                                                  |
| UA-3 | Server | For HTTP, servers SHOULD set `Retry-After` to the integer decimal `ceil(retryAfterMs / 1000)`, so the header never indicates a shorter delay than the body, and MUST NOT use the `HTTP-date` form. |
| UA-4 | Server | Servers MUST NOT emit `-32024` for a condition they know to be permanent; that is `-32603`, or the applicable specific code.                                                                       |
| UA-5 | Server | Servers MUST NOT set `notProcessed: true` when `reason` is `"deadline_exceeded"`.                                                                                                                  |
| UA-6 | Server | Servers MUST NOT emit `-32024` for a dependency failure encountered inside a tool; those remain tool execution errors.                                                                             |
| UA-7 | Server | A server shutting down SHOULD emit `-32024` with `reason: "shutting_down"` for in-flight and newly arriving requests before closing the transport, on stdio as well as HTTP.                       |
| UA-8 | Client | When `requiresUserAction` is true, clients MUST NOT retry automatically; the retry MUST be gated on a fresh user action.                                                                           |
| UA-9 | Client | Clients receiving an unrecognized `reason` MUST treat it as `"other"` and honour `retryAfterMs`.                                                                                                   |

One code with a typed `reason`, rather than separate codes per condition, follows the
allocation rule of §2.1, the corrective action, wait `retryAfterMs` and retry, is the
same for every value, and a `reason` vocabulary can grow without an allocation and
without breaking older clients. `requiresUserAction` imports the one forbid-automatic-retry
rule in the HTTP status registry, `507`'s rule that a request resulting from a user
action "MUST NOT be repeated until it is requested by a separate user action"
([RFC 4918 §11.5](https://www.rfc-editor.org/rfc/rfc4918.html#section-11.5)), as a field
rather than a status, which is the only form that can reach a stdio client.
`"deadline_exceeded"` is the one value where retry safety cannot be asserted, as the
request may have taken effect; UA-5 keeps the guarantee honest.

`502` and `504` are deliberately not bound to this code. Both are, by definition, an
intermediary's report about a third party: the server the client believes it is
addressing is fine, and the one that failed never spoke. An MCP origin server cannot
honestly emit them, and a client receiving one, routinely bodiless from load balancers
and CDNs, is in TR-9 territory: a transient path failure of unknown provenance, never
attributed to the peer. The `reason` member is an information oracle, disclosing
operational state such as maintenance windows and capacity, and servers MAY always answer
`"other"`.

#### 7.8 RequestTooLarge

`-32025 RequestTooLarge` (illustrative) is the condition that the receiver refuses a
request because some part of it exceeds a limit the receiver enforces. The condition
arises on every transport, for instance an over-long message line on stdio, and MCP's
own header-mirroring design (`Mcp-Method`, `Mcp-Name`, `Mcp-Param-{Name}`) is what makes
oversized header sections reachable on HTTP. SEP-2243 declined to specify size limits
and pointed clients at the standard `413`/`431` statuses instead, and that guidance
never reached the specification text, leaving the condition entirely unspecified today.
Retry classification: retry-after-change.

```ts
export const REQUEST_TOO_LARGE = -32025;

/**
 * The receiver refuses the request because some part of it exceeds a limit the
 * receiver enforces. For HTTP, the response status code MUST be `400 Bad Request`.
 */
export interface RequestTooLargeError extends Error {
  code: typeof REQUEST_TOO_LARGE;
  data: {
    /** Which part of the request exceeded a limit. */
    part: "message" | "body" | "headers" | "field";
    /** The limit that was exceeded, in bytes. @minimum 0 */
    limitBytes?: number;
    /** The observed size, in bytes, if the receiver measured it. @minimum 0 */
    actualBytes?: number;
    /**
     * When part is "headers" or "field", the header field name or JSON pointer
     * that was too large. MUST NOT contain the oversized value itself.
     */
    location?: string;
  };
}
```

| ID   | Party  | Rule                                                                                                                                                                                                                                                          |
|------|--------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| TL-1 | Server | Servers MUST include `part` whenever they emit `-32025`.                                                                                                                                                                                                      |
| TL-2 | Server | For HTTP, servers MUST respond with status `400`.                                                                                                                                                                                                             |
| TL-3 | Server | Servers SHOULD include `limitBytes` when the limit is a stable, published property of the deployment, and MAY omit it otherwise.                                                                                                                              |
| TL-4 | Server | Servers MUST NOT include the oversized value, or any part of it, in `message`, `location`, or any other `data` member.                                                                                                                                        |
| TL-5 | Server | Where the request could not be parsed far enough to recover the JSON-RPC `id`, servers MUST omit `id`, as PE-2 provides.                                                                                                                                      |
| TL-6 | Server | Servers MUST NOT emit `-32025` for a size limit encountered inside a tool, for instance an oversized file or an oversized upstream response; those remain tool execution errors.                                                                              |
| TL-7 | Client | Clients MUST NOT retry the request unchanged, and SHOULD use `part` and `location` to choose a remedy: split a paginated call, shorten arguments, or, when `part` is `"headers"`, stop mirroring the offending `Mcp-Param-{Name}` value and rely on the body. |
| TL-8 | Client | Clients SHOULD treat `limitBytes` as advisory and MUST NOT assume it applies to any other server or any other network hop.                                                                                                                                    |

`413` and `431` are deliberately not bound. Both are overwhelmingly emitted by reverse
proxies and load balancers before the application sees the request, and header limits
are per-hop by nature: "any request or response could encounter a hop with a lower,
unknown limit" ([RFC 9113 §10.5.1](https://www.rfc-editor.org/rfc/rfc9113.html#section-10.5.1)).
Binding them would assign application semantics to statuses the application does not
control. Infrastructure will continue to emit them, and clients handle a bodiless
`413`/`431` under TR-9, with the same remedy as TL-7 but attribution to the path rather
than the peer. Where the MCP server itself enforces the limit and can author a body,
`400` with `-32025` is the interoperable answer. The `"headers"` part is
transport-conditional in the same way `-32020` is, and leans on the policy HM-1 states.
HTTP's own trick of distinguishing a permanent cap from transient pressure by the
presence of `Retry-After` on a `413` is declined, as a semantic carried by header
presence is what stdio cannot see, and the registry has two codes that say it
explicitly, `-32025` for the permanent cap and `-32024` for transient pressure.

#### 7.9 StaleState

`-32026 StaleState` (illustrative) is the condition that the client echoed back an
opaque, server-issued token and the server will not honor it. MCP has four such tokens:
pagination cursors, Tasks task identifiers, MRTR `requestState`, and stateful-tool
handles. The first three currently collapse into `-32602` or into nothing at all, and the
fourth is deliberately excluded, as the specification already places expired tool
handles at the tool-execution level so the model can recover by creating a new one.
Retry classification: retry-after-change, where the change is fully specified: discard
the token and restart the interaction, rather than re-send it.

The code exists because the corrective actions are opposite. `-32602` means the request
is malformed, so fix the parameters and re-send; a stale token means the request was
well-formed and the client's continuation state is dead, so discard it and start over.
A client cannot distinguish these today, and the MRTR rejection conditions in the
Motivation have no representation at all.

```ts
export const STALE_STATE = -32026;

/**
 * A server-issued token, cursor, or continuation state the client presented is no
 * longer usable. For HTTP, the response status code MUST be `400 Bad Request`.
 */
export interface StaleStateError extends Error {
  code: typeof STALE_STATE;
  data: {
    /** Which kind of server-issued state was rejected. */
    kind: "cursor" | "request_state" | "task" | "other";
    /**
     * Why it was rejected. "rejected" is the deliberately uninformative value for
     * integrity, replay, and principal-mismatch failures; see SS-5.
     */
    reason: "expired" | "unknown" | "superseded" | "rejected";
    /**
     * True if the client must restart the interaction from the beginning rather
     * than adjust and re-send. Default true for kind "cursor".
     */
    restart?: boolean;
    /**
     * Milliseconds after which a restarted interaction is expected to succeed,
     * where the server knows. @minimum 0
     */
    retryAfterMs?: number;
  };
}
```

| ID    | Party  | Rule                                                                                                                                                                                                                                         |
|-------|--------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| SS-1  | Server | Servers MUST include `kind` and `reason` whenever they emit `-32026`.                                                                                                                                                                        |
| SS-2  | Server | For HTTP, servers MUST respond with status `400`.                                                                                                                                                                                            |
| SS-3  | Server | Servers MUST emit `-32026` in place of `-32602` for an invalid or expired pagination cursor, an unknown or expired task identifier, and `requestState` that fails verification, replay, expiry, or request-match checks.                   |
| SS-4  | Client | Clients MUST continue to accept `-32602` for these conditions from servers implementing earlier revisions, the same transition discipline the specification applies to `-32002`.                                                             |
| SS-5  | Server | Servers MUST use `reason: "rejected"`, never a more specific value, for integrity, replay, and principal-mismatch failures of `requestState`, and MUST NOT disclose which check failed.                                                      |
| SS-6  | Server | Servers MUST NOT echo the rejected token, or any decoded part of it, in `message` or `data`.                                                                                                                                                 |
| SS-7  | Server | Servers MUST NOT emit `-32026` for an expired or unknown stateful-tool handle; the specification places that at the tool-execution level.                                                                                                    |
| SS-8  | Client | On `restart: true`, or `kind: "cursor"` with `restart` absent, clients MUST NOT re-send the same token and SHOULD discard cached pages and re-fetch from the beginning, as the caching utility already prescribes for an invalidated cursor. |
| SS-9  | Client | On `kind: "request_state"`, clients MUST NOT re-present the state and MUST treat the multi-round-trip interaction as failed; they MAY re-issue the originating request with a new request ID.                                                |
| SS-10 | Client | Clients MUST NOT count `-32026` toward circuit-breaking or backoff state; it is a state error, not a load signal.                                                                                                                            |

`409` and `410` are deliberately not bound, although they are the statuses HTTP would
use for these conditions. `410` is heuristically cacheable, and every MCP call shares
one request URI, so a cached "gone" answered for one client's cursor could be replayed
against a different client's; `409` adds no machine-readable fact that `reason` does not
carry better. `notProcessed` is never asserted here, as the server rejecting stale state
has not performed the requested work, but earlier turns of the interaction may have had
effects, so a blanket assertion would mislead. SS-5 exists because a server that
distinguishes integrity failure from wrong principal from expiry hands an attacker a
verification oracle for forging or replaying `requestState`; the uninformative value
mirrors the refusal-masking [RFC 9110 §15.5.4](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.4)
permits. SS-6 keeps the error from becoming a decoding oracle, or from leaking a signed
token into client logs.

#### 7.10 UnsupportedFeature

`-32027 UnsupportedFeature` (illustrative) is the condition that the receiver cannot
process the request because a feature it names, a protocol extension or a JSON Schema
dialect, is not supported. It closes the two normative requirements in the Motivation
that currently instruct implementations to return "an appropriate error" and name no
code, and it is the registry's answer to how extensions signal unsupported features
without allocating codes (§9). No status maps to this row: HTTP's analogue, `510 Not
Extended`, was obsoleted when RFC 2774 moved to Historic, and
[RFC 9205 §4.6](https://www.rfc-editor.org/rfc/rfc9205.html#section-4.6) requires
registered codes used with their registered semantics. Retry classification:
retry-after-change.

```ts
export const UNSUPPORTED_FEATURE = -32027;

/**
 * The receiver cannot process the request because a named feature, a protocol
 * extension or a JSON Schema dialect, is not supported. A required client
 * capability is MissingRequiredClientCapability (-32021); an unadvertised server
 * capability is MethodNotFound (-32601). For HTTP, the response status code MUST
 * be `400 Bad Request`.
 */
export interface UnsupportedFeatureError extends Error {
  code: typeof UNSUPPORTED_FEATURE;
  data: {
    /** What kind of feature is unsupported. */
    kind: "extension" | "schema_dialect" | "other";
    /**
     * Stable identifier of the unsupported feature: the extension's reverse-DNS
     * name (for instance `io.modelcontextprotocol/tasks`) or the dialect URI.
     */
    feature: string;
    /** Identifiers of comparable features the receiver does support, if any. */
    supported?: string[];
  };
}
```

| ID   | Party  | Rule                                                                                                                                                                                                                                                                                                                  |
|------|--------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| UF-1 | Server | Servers MUST include `kind` and `feature` whenever they emit `-32027`.                                                                                                                                                                                                                                                |
| UF-2 | Server | For HTTP, servers MUST respond with status `400`.                                                                                                                                                                                                                                                                     |
| UF-3 | Both   | A party that supports an extension its peer does not MUST either revert to core protocol behavior or reject the request with `-32027`. This replaces "an appropriate error" in [Versioning § Extension Negotiation](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning#extension-negotiation). |
| UF-4 | Server | A receiver that cannot handle a request's JSON Schema dialect MUST reject it with `-32027` and `kind: "schema_dialect"`. This replaces "an appropriate error" in [Base Protocol § Implementation Requirements](https://modelcontextprotocol.io/specification/2026-07-28/basic/index#implementation-requirements).     |
| UF-5 | Server | Servers MUST NOT use `-32027` where a more specific code applies: `-32021` for an undeclared client capability, `-32601` for an unadvertised server capability, `-32022` for a protocol version.                                                                                                                      |
| UF-6 | Client | Clients MUST treat `-32027` as non-retryable for the request as sent, and SHOULD fall back to the core protocol behavior the extension documents.                                                                                                                                                                     |
| UF-7 | Client | Clients MUST ignore `supported` entries they do not recognize.                                                                                                                                                                                                                                                        |

`supported` mirrors the shape of `-32022`'s `data.supported`, the specification's
existing precedent for "here is what I can do instead". `feature` and `supported`
enumerate what a deployment implements, so a server MAY omit `supported` or list only
the feature actually requested; and an attacker-supplied `feature` value is reflected
content, so clients MUST NOT dereference it or use it to select code paths beyond exact
string comparison against features they already implement.

### 8. Statuses Without Registry Codes

Some conditions the specification binds to a status deliberately receive no registry
code. This section states each exclusion and its reason, so that the absence reads as a
decision rather than an omission.

#### 8.1 Authorization

`401`, `403`, and the malformed-authorization `400` remain status-only. No registry code
is assigned to any authorization condition; their retry classification,
re-auth-then-retry, is registry metadata only. Four points keep them at the status layer.
The stdio exclusion is designed rather than accidental, as stdio implementations "SHOULD
NOT follow this specification, and instead retrieve credentials from the environment" ([Authorization § Protocol Requirements](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization#protocol-requirements)),
so unlike rate limiting there is no cross-transport parity gap. The `WWW-Authenticate`
challenge is the payload, it is required at MUST level, and it is end-to-end, as a proxy
"MUST NOT modify" it ([RFC 9110 §11.6.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-11.6.1)).
A `401` is frequently produced by an identity-aware proxy that never sees the MCP body,
so an in-band code would be absent exactly when the condition is most common. And an
in-band duplicate of `resource_metadata` or `scope` would be a second, independently
mutable source for security-critical values, and a path for anything that can influence the
body, for instance a transforming proxy or a compromised application tier, to steer a
client's token acquisition toward an attacker-chosen authorization server.

| ID   | Party         | Rule                                                                                                                                                                                                                                                                                              |
|------|---------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| AU-1 | Specification | The specification SHOULD state explicitly that a `401`, `403`, or malformed-authorization `400` response MAY carry a JSON-RPC error body, and that no registry code is assigned to these conditions.                                                                                              |
| AU-2 | Client        | Where an authorization status carries both a `WWW-Authenticate` challenge and a body, the header is authoritative. Clients MUST derive every challenge parameter, `resource_metadata`, `scope`, `error`, and `error_description`, from the header, and MUST NOT derive any of them from the body. |
| AU-3 | Client        | Clients MUST NOT infer a registry code, a retry delay, or an authorization endpoint from an authorization status or its body.                                                                                                                                                                     |
| AU-4 | Server        | Servers MUST NOT place credentials, tokens, authorization-server URLs, or scope grants in an error body on these statuses.                                                                                                                                                                        |
| AU-5 | Server        | Where a server includes a body on the `403` for an invalid `Origin`, it SHOULD be a JSON-RPC error response with `id` omitted and code `-32600`; per AU-3, clients MUST NOT treat it as a registry condition.                                                                                     |
| AU-6 | Specification | The specification SHOULD carry the stdio exclusion statement into the registry section, so the status-only standing of authorization reads as a decision. Authorization over non-HTTP bindings, if it is ever needed, belongs to the Pluggable Transports track.                                  |

#### 8.2 Legacy verbs

`405` for a `GET` or `DELETE` at the MCP endpoint remains status-only, and no code would
be meaningful: no MCP message is being processed when a legacy verb arrives. Two
conformance fixes attach to it.

| ID   | Party  | Rule                                                                                                                                                                                                                                                                                                                                                                                                                                   |
|------|--------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| MV-1 | Server | A server responding `405` MUST include the `Allow` header field. This is not a new requirement: [RFC 9110 §15.5.6](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.6) and [§10.2.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.1) already make it a MUST for origin servers, but MCP prescribes the status without mentioning the obligation, so implementations miss it. Stated by reference, not restatement. |
| MV-2 | Server | A server responding `405` MUST include `Cache-Control: no-store` (CA-2).                                                                                                                                                                                                                                                                                                                                                               |

#### 8.3 Notifications

`202` for an accepted notification is status-only permanently, not provisionally: "The
Server MUST NOT reply to a Notification" ([JSON-RPC 2.0 §4.1](https://www.jsonrpc.org/specification#notification)),
and HTTP agrees from its own side that there is "no facility in HTTP for re-sending a
status code from an asynchronous operation" ([RFC 9110 §15.3.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.3.3)).
This SEP accepts the asymmetry rather than inventing a notification-acknowledgement channel.
The rejection path is closed by TR-7: status `400`, with an optional `id`-omitted body
carrying a registry code. On stdio a rejected notification remains unsignalled, which is
required by JSON-RPC rather than a gap; senders SHOULD NOT rely on notifications for
anything whose loss they must detect.

#### 8.4 Cancellations and local timeouts

Cancellation produces neither a result nor an error on either transport, as over HTTP a
client disconnect is cancellation, and over stdio invalid cancellation notifications are
ignored. Timeouts raised inside an SDK are the specification's canonical local error and
remain uncoded; the remedy is local cancellation. The one adjacent condition that is
wire-visible, a server abandoning a request against its own deadline, is
`-32024 reason: "deadline_exceeded"` (§7.7).

#### 8.5 Redirection statuses

The `3xx` class is out of scope for an error registry: a redirect is not a failure, and
TR-9 accordingly does not apply to it. Client handling of redirects on the MCP endpoint,
which raises method-rewriting and credential-forwarding hazards independent of error
semantics, is deferred to a companion proposal.

### 9. Allocation Rules

The criterion for a new specification code restates §2.1: a condition earns an
allocation only when the client's corrective action differs from every existing row's,
and typed `data` on an existing code cannot carry the distinction. Everything else about
the code space is a rule below. Codes allocated outside the registry interact with the
transport binding through TR-2, as an application-defined code has no registry row, so its
status is `400` or `500` by fault class.

| ID   | Party          | Rule                                                                                                                                                                                                                                                                                                                                                                     |
|------|----------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| AL-1 | Specification  | New specification codes are allocated sequentially from the reserved sub-range `-32020` to `-32099` and recorded in the schema, per [Base Protocol § Error Codes](https://modelcontextprotocol.io/specification/2026-07-28/basic/index#error-codes). Every allocation carries a complete registry row: name, code, bound status, retry classification, and `data` shape. |
| AL-2 | Extension      | Extensions MUST NOT allocate codes in `-32020` to `-32099`. An extension expressing that a feature is unsupported MUST use `-32027` with a `feature` identifier it owns (§7.10).                                                                                                                                                                                         |
| AL-3 | Extension      | An extension with a genuinely new condition, one meeting the criterion above but outside the core protocol, SHOULD allocate outside the JSON-RPC reserved range (`-32768` to `-32000`), as the specification already directs for application codes, and MUST document the fallback behavior for clients that do not implement the extension.                             |
| AL-4 | Implementation | Implementations MUST NOT allocate new codes in `-32000` to `-32019` and SHOULD NOT use that sub-range at all.                                                                                                                                                                                                                                                            |
| AL-5 | Implementation | Purely local errors, for instance SDK timeouts, connection failures, and the bodiless statuses of TR-9, remain uncoded. Where an implementation surfaces one in a JSON-RPC-shaped structure, it MUST be distinguishable from an error received from the peer (§1).                                                                                                       |
| AL-6 | Specification  | A code, once allocated, is never reused, even after retirement; `-32002` and `-32042` are the precedent (§2).                                                                                                                                                                                                                                                            |

AL-2 is what keeps the reserved sub-range's guarantee intact, as receivers may rely on
every code in it having exactly its specified meaning only if no party other than the
specification can mint one. Extensions lose nothing by the prohibition, as `-32027`'s
namespaced `feature` identifier gives them the expressiveness an integer would, at no
cost to the shared namespace; this is the same trade RFC 9457 makes by keying problems
on a URI the definer owns rather than on a scarce shared code.

### 10. Conformance Test Cases

Per [SEP-2484](https://modelcontextprotocol.io/seps/2484-conformance-tests-required-for-final-seps),
the rule identifiers of §§3-9 are the test unit: the full matrix is one test per MUST-level
rule, keyed by rule ID. The tables below define the edge cases the suite MUST additionally
cover, where behavior is easy to get wrong or the rules interact.

#### Status binding

| Test Case                         | Setup                                                       | Expected Behavior                                                                                  |
|-----------------------------------|-------------------------------------------------------------|----------------------------------------------------------------------------------------------------|
| Handler internal error            | Request handler fails unexpectedly; response is JSON, not a stream                          | Status `500`, body `-32603` (IE-1, TR-2). Not `200`.                                               |
| Resource not found                | `resources/read` for unknown URI                            | Status `400`, body `-32602`, `data.reason: "resource_not_found"`, `data.uri` present (IP-1, IP-3)  |
| Capability-gated method           | `prompts/list` without advertised `prompts` capability      | Status `404`, body `-32601`, `Cache-Control: no-store` (MN-1, MN-2)                                |
| Successful result                 | Any successful request                                      | Status `200` (TR-6)                                                                                |
| Application-defined code          | Server emits a code outside the registry for a client fault | Status `400` (TR-2)                                                                                |
| Error in established stream       | Rate limit or internal error after SSE headers sent         | JSON-RPC error object delivered in-stream; no disconnect required; status was already `200` (TR-5) |
| Error in unstarted response       | Any protocol error before headers sent                      | Status is never `2xx` (TR-4), and is drawn only from `{400, 404, 429, 500, 503}` (TR-3)            |

#### Client behavior on statuses and bodies

| Test Case                              | Input                                          | Expected Behavior                                                                                                                          |
|----------------------------------------|------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| Body governs over status               | Status `500` with a parsable `-32602` body     | Client treats the condition as `-32602` (TR-8, TR-14)                                                                                      |
| Bodiless `429`                         | `429`, no JSON-RPC body, `Retry-After: 7`      | Treated as local error; delay MAY use header; MUST NOT be reported as peer `-32023`; MUST NOT trigger the legacy probe (TR-9, TR-10, §7.6) |
| Bodiless unrecognized `4xx`            | `418`, no body                                 | Class fallback to `400`-shaped local error; no registry code attributed; no legacy probe (TR-9, TR-10)                                     |
| Modern `404`                           | `404` with `-32601` body                       | No legacy-transport probe (MN-5); bodiless `404` MAY probe (TR-10)                                                                         |
| Unknown reserved-range code            | `-32077` (hypothetical), no `retryAfterMs`     | do-not-retry (TR-11)                                                                                                                       |
| Unknown reserved-range code with delay | `-32077` with `data.retryAfterMs: 2000`        | MAY retry after ~2s with jitter, clamped (TR-11, §5)                                                                                       |
| Unknown `data` member                  | Any registry error with an unrecognized member | Member ignored; condition handling unchanged (TR-11)                                                                                       |
| Localized message                      | Same error, `message` in another language      | Behavior identical; nothing parsed from `message` (TR-12)                                                                                  |

#### Caching and headers

| Test Case                 | Setup                              | Expected Behavior                                                                           |
|---------------------------|------------------------------------|---------------------------------------------------------------------------------------------|
| Legacy `GET`              | `GET` to the MCP endpoint          | `405` with `Allow` present (MV-1) and `Cache-Control: no-store` (MV-2)                      |
| Error response headers    | Any error response                 | No explicit freshness information; no `Content-Location` equal to the request target (CA-3) |
| `Retry-After` consistency | `-32024` with `retryAfterMs: 1500` | If `Retry-After` is sent, it is `2`, never `1` and never an `HTTP-date` (UA-3)              |

#### Retry safety

| Test Case                | Setup                                                         | Expected Behavior                                                              |
|--------------------------|---------------------------------------------------------------|--------------------------------------------------------------------------------|
| Deadline with guarantee  | `-32024`, `reason: "deadline_exceeded"`, `notProcessed: true` | Non-conformant server (UA-5); client ignores the guarantee                     |
| Load-shed with guarantee | `-32024`, `reason: "overloaded"`, `notProcessed: true`        | Client MAY auto-retry after the delay (§5.2)                                   |
| No guarantee             | `-32024` without `notProcessed`                               | No automatic retry unless idempotence is known or the operator opted in (§5.2) |
| User-gated retry         | `-32024`, `requiresUserAction: true`                          | No automatic retry under any setting (UA-8)                                    |
| Unrecognized reason      | `-32024`, `reason: "quantum_flux"`                            | Treated as `"other"`; `retryAfterMs` honoured (UA-9)                           |

#### Boundaries and oracles

| Test Case                        | Setup                                                                 | Expected Behavior                                                                                                               |
|----------------------------------|-----------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------|
| Tool argument content            | Valid `CallToolRequest`; `arguments` violate the tool's `inputSchema` | Tool execution error, `isError: true`, in a `200`; not `-32602` (IP-5)                                                          |
| Malformed tool request           | `arguments` member is a string, not an object                         | `-32602` with `400`; protocol-schema failure (§7.3 boundary)                                                                    |
| Upstream rate limit in tool      | Tool's own API returns 429 to the server                              | Tool execution error; not `-32023` (§7.6 boundary)                                                                              |
| `requestState` integrity failure | Tampered `requestState` presented                                     | `-32026`, `kind: "request_state"`, `reason` exactly `"rejected"` (SS-5); rejected token absent from `message` and `data` (SS-6) |
| Expired cursor                   | Stale cursor presented to a current server                            | `-32026`, `kind: "cursor"`; client discards cached pages and restarts (SS-8)                                                    |
| Old server, stale cursor         | `-32602` "Invalid cursor" from a pre-registry server                  | Client accepts and recovers; no error on the client side (SS-4)                                                                 |
| Oversized `Mcp-Param` value      | Header exceeding the server's limit                                   | `-32025`, `part: "headers"` or `"field"`; the oversized value appears nowhere in the response (TL-4)                            |
| Specific code precedence         | Request requiring an undeclared client capability                     | `-32021`, not `-32027` (UF-5)                                                                                                   |

## Backward Compatibility

The compatibility story runs in two directions, namely clients to servers and vice versa.

### New clients against existing servers

The client rules are deliberately status-agnostic, which makes a conforming client
backward compatible automatically. TR-8 determines the condition from the body
regardless of status, so a `-32603` delivered inside a `200` by a current server parses
identically to one delivered inside a `500` by a conforming one. SS-4 requires clients
to keep accepting `-32602` for stale-state conditions from older servers, the same
discipline the specification already applies to `-32002`. No behavior a current server
exhibits becomes an error for a new client.

### New servers against existing clients

New codes ride statuses existing clients already handle generically, and every code this
SEP allocates is in the sub-range reserved to the specification, which no existing
client may rely on. An older client that does not recognize `-32024` through `-32027`
sees a JSON-RPC error with an unknown code inside a `400`, `429`, or `503`, and behaves
as it does today for any unrecognized error.

The primary change of importance is status placement. A survey of the ten SDK server transports
conducted for this SEP (main branches, 2026-09-03) found that every SDK today delivers a
handler-produced `-32603` inside a `200`; under IE-1 it arrives inside a `500`. The
survey also found that current SDK clients handle non-`2xx` bodies inconsistently,
variously parsing, stringifying, or dropping them, so during transition a new server
paired with an old client may surface a generic HTTP failure where it previously
surfaced a parsed error object. The failure classification does not change, `-32603` is
do-not-retry in either representation, but detail is lost. SDKs SHOULD therefore ship
the client-side rules, in particular TR-8's body-first parsing, before or together with
the server-side status changes.

### Changes to shipped behavior, enumerated

| Change                                                                            | Who changes                                            | Current shipped behavior                                                                                                    |
|-----------------------------------------------------------------------------------|--------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| `-32603` bound to `500` (IE-1)                                                    | All ten SDK server transports                          | All deliver handler-produced `-32603` in `200`; transport-internal failures diverge five ways across the SDKs               |
| `-32601` bound to `404` for the capability-gated condition (MN-1)                 | SDKs without a code-to-status map                      | Four SDKs (C#, Go, Rust, Ruby) already map every `-32601` to `404`; the rest deliver it in `200`                            |
| `-32602` bound to `400` for every condition (IP-1)                                | Most SDKs                                              | Go and Ruby already map `-32602` to `400`; C# maps only the `-3202x` codes; the rest deliver it in `200`                    |
| Tool `inputSchema` content failures move to `isError: true` (IP-5, §7.3 boundary) | Servers validating tool arguments in shared middleware | The specification currently states the boundary both ways; deployed behavior is split                                       |
| Stale-state conditions move from `-32602` to `-32026` (SS-3)                      | Servers implementing this revision                     | New servers emit `-32026`; clients keep accepting the old shape (SS-4), following the `-32002` to `-32602` precedent        |
| Rejected notifications: open-ended status -> `400` (TR-7)                         | None in practice                                       | This revision defines no client-to-server notifications over Streamable HTTP, so the rule has no current trigger            |
| Success -> `200` (TR-6)                                                           | None                                                   | Universal current behavior, now stated                                                                                      |

TR-2 and TR-3 generalize a pattern four SDKs already implement rather than inventing
one; the survey is attached to this SEP's pull request as supporting evidence.

### Operational visibility

Deployments monitoring the MCP endpoint will see protocol errors move out of the `200`
bucket into `4xx` and `5xx` rates. This is the intended effect, it is what makes generic
dashboards, gateways, and retry middleware correct, but operators upgrading a server
should expect error-rate graphs to change shape without any change in underlying
behavior.

## Security Implications

The rules of §§3-8 carry their security reasoning inline; this section collects the
threat model they answer.

- **Retry timing is attacker-controlled input.** A malicious or compromised server can
  pin a client down with a large `retryAfterMs`, on any code that carries it. The clamp
  and jitter requirements of §5 apply to every use, and synchronized retries after
  identical delays, the thundering-herd problem, are mitigated by the same jitter.
- **A false "not processed" assertion is a data-integrity attack.** A server that sets
  `notProcessed: true` without the guarantee induces clients to duplicate non-idempotent
  work. CM-1 states the obligation in RFC 9113 §8.7's terms, UA-5 forbids the assertion
  where the outcome is unknowable, and the conformance suite tests both.
- **Bodiless statuses are path-attacker territory.** Anything on the network path can
  synthesize a status without a body. TR-9's attribution rule prevents an on-path actor
  from making a server appear to have emitted a protocol error it never sent, TR-13
  prevents intermediaries minting registry-attributed errors, and TR-10 closes the
  downgrade vector in which a synthesized `429`, read as `400` under the class fallback,
  induces fallback to the deprecated HTTP+SSE transport.
- **The status line is rewritable; the body is the anchor.** A transforming intermediary
  that alters a status cannot change the effective error, because TR-14 makes the body
  govern and TR-8 forbids clients inferring conditions from the status.
- **Error responses are oracles unless constrained.** SS-5's uniform `"rejected"` denies
  an attacker a verification oracle for forging or replaying `requestState`; SS-6
  prevents the error channel becoming a decoding oracle or leaking signed tokens into
  logs; §7.3's `resource_not_found` masking permits refusal-hiding per RFC 9110
  §15.5.4's allowance; and the fingerprinting members, `limitBytes`, `supported`, and
  `reason`, are optional or may be answered with `"other"` for exactly this reason.
- **Error bodies are a disclosure channel.** IE-3 keeps stack traces, host names, query
  text, credentials, and upstream bodies out of `-32603`; PE-3 and TL-4 forbid echoing
  unparsable or oversized input, which would otherwise create reflected-content and
  log-poisoning hazards; `errorId` is opaque by rule.
- **Reflected members are data, not instructions.** `uri`, `name`, `field`, `feature`,
  and `supported` reflect attacker-influenced input; clients MUST NOT dereference them,
  render them as live links, or use them to select code paths beyond exact comparison.
- **Authorization values stay in the authenticated channel.** AU-2 keeps every challenge
  parameter header-authoritative, denying body-level attackers a path to steer token
  acquisition toward a hostile authorization server; AU-3 prevents an in-band retry
  delay from pinning a client's re-authentication loop; AU-4 keeps grant material out of
  bodies that get logged.
- **Shared caches must not replay errors across principals.** CA-2 closes the one
  binding where silence produces a storable error, the legacy-verb `405`; CA-3 closes
  the explicit-opt-in path for POST responses.
- **A shutdown notice is a small oracle.** UA-7's `shutting_down` signal marginally
  increases what a probing attacker learns about restarts; this is accepted in exchange
  for removing the current restart-and-hope behavior on stdio.

## Reference Implementation

TODO.

## Acknowledgements

TODO.
