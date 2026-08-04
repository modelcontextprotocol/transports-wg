# SEP-0000: Unavailable and Empty `subscriptions/listen` Requests

- **Status**: Draft
- **Type**: Standards Track
- **Created**: 2026-07-31
- **Author(s)**: Shaun Smith
- **Sponsor**: TBC
- **PR**: TBD

## Abstract

Some MCP servers do not provide subscription notifications. This SEP defines
what those servers return and when clients should avoid calling
`subscriptions/listen`.

A deployment that offers no subscription notification type does not make
`subscriptions/listen` available. It returns JSON-RPC
`-32601 Method not found`. Over Streamable HTTP, it also returns
`404 Not Found`. It does not acknowledge the request or open a subscription
stream.

Clients must not call `subscriptions/listen` just to find out whether it is
available. When current discovery is available, a client that opens
subscriptions automatically should skip the call if discovery advertises none
of the notification types it wants.

An unavailable method is different from an available method that accepts
nothing from a particular request. In the latter case, the server acknowledges
`notifications: {}`, sends the normal successful final result, and ends the
response body. It does not keep an empty subscription open.

Current SDKs do not yet follow one consistent approach. Low-level Python
servers can omit the method, while the high-level Python and TypeScript servers
expose it and keep an empty subscription open. Go exposes the method but
completes an empty subscription immediately. TypeScript checks advertised
capabilities before opening an automatic list-change subscription; Go checks
for locally configured handlers without comparing them with discovered server
capabilities, and Python opens subscriptions only when the application asks it
to.

## Motivation

There are three distinct outcomes:

1. the server does not make `subscriptions/listen` available;
2. the server makes the method available but accepts none of the notifications in a
   particular request; or
3. the server accepts at least one notification and opens a subscription.

These outcomes should not look the same on the wire. A missing method is not
the same as an authorization failure, invalid parameters, or an empty
acknowledged request.

Keeping an empty subscription open also serves no purpose. No matching event
can arrive, but the stream may still consume a task, queue, timer, connection
slot, and client-side lifecycle state.

This SEP therefore defines:

- how a server reports that `subscriptions/listen` is unavailable;
- when clients should skip the call;
- how the four core notification selectors relate to existing server
  capabilities; and
- how a server completes a request when it accepts no notifications.

## Specification

### Scope

This SEP covers these four core notification selectors:

- `toolsListChanged`;
- `promptsListChanged`;
- `resourcesListChanged`; and
- `resourceSubscriptions`.

Whether the method is available is a property of the server at the chosen
endpoint, protocol version, and deployment configuration. It does not become
unavailable merely because one client is unauthorized or one request contains
nothing the server will accept.

This SEP does not define a general subscriptions capability or a common rule
for extension selectors. Extensions (such as Tasks) remain responsible for saying how clients discover their notification support.

### How core capabilities map to listen requests

For the four core selectors, an existing server capability advertises each
kind of notification:

| Requested notification | Advertised when |
| --- | --- |
| `toolsListChanged` | `capabilities.tools.listChanged === true` |
| `promptsListChanged` | `capabilities.prompts.listChanged === true` |
| `resourcesListChanged` | `capabilities.resources.listChanged === true` |
| `resourceSubscriptions` | `capabilities.resources.subscribe === true` |

Only the literal value `true` advertises support. A missing object, a missing
field, `false`, or any other value does not.

`resources.subscribe: true` means that the server supports requests for
resource-update notifications. It does not say that a particular URI exists,
is visible to the client, or will be accepted.

Extensions need their own mapping. For example, Tasks adds a `taskIds`
selector, but the general Tasks capability does not say whether optional task
push notifications are enabled. This SEP therefore makes no inference from an
extension capability unless that extension defines one.

### When `subscriptions/listen` is unavailable

If a deployed server supports no core or extension listen selector, it
**MUST** treat `subscriptions/listen` as unavailable.

For a valid request in that state, the server:

- **MUST** return a JSON-RPC `-32601 Method not found` error whose `id` matches
  the request ID;
- over Streamable HTTP, **MUST** return HTTP `404 Not Found`;
- **MUST NOT** send `notifications/subscriptions/acknowledged`; and
- **MUST NOT** create subscription state or open a subscription SSE stream.

`-32601` is only for a method the server does not make available. A server
**MUST NOT** use it for client-specific authorization or policy decisions, an
empty request, invalid parameters, rate or capacity limits, overload, or
temporary unavailability.

This SEP does not require a particular non-SSE JSON framing for the `404`.
Existing transport rules still apply. Whether a future specification should
require one finite JSON error body remains an open question.

### When clients should call `subscriptions/listen`

Clients **MUST NOT** call `subscriptions/listen` when the call's only purpose
is to find out whether the method is available.

A client that opens subscriptions automatically and requests only core
notifications **SHOULD NOT** call `subscriptions/listen` when current discovery
advertises none of the notification types it plans to request.

For `resourceSubscriptions`, the client also needs at least one URI that it
intends to request. Discovery describes possible support; it does not grant
access to a URI or guarantee that the server will accept the request.

A discovery result is current for this purpose only when it applies to the
same endpoint, protocol version, deployment configuration, authorization
context, and negotiated extensions.

A client that has a real need for subscription notifications **MAY** still
call the method when:

- the application explicitly asks for a subscription;
- the client has no applicable discovery result; or
- the available discovery result may be stale.

In those cases, the client must handle the response normally.

Over Streamable HTTP, a client recognizes the unavailable-method signal only
when the `404` contains a valid JSON-RPC `-32601` error with the request's ID.
A proxy-generated `404`, an HTML response, or a `404` from a legacy endpoint
does not carry that meaning.

A matching method-not-found response does not make the rest of an otherwise
usable MCP session fail. The client:

- **MUST NOT** wait for an acknowledgment;
- **MUST NOT** immediately retry the same listen request in a loop; and
- **MUST NOT** end the MCP session solely because this method is unavailable.

### What the server may acknowledge

For the four core selectors:

- the server may acknowledge a Boolean selector as `true` only when the client
  requested `true` and the mapped capability was advertised as `true`;
- a missing or `false` Boolean selector requests nothing; and
- every acknowledged `resourceSubscriptions` URI must appear in the client's
  request, and `capabilities.resources.subscribe` must be `true`.

An empty URI array requests nothing.

Authorization, visibility, policy, quota, resource existence, and temporary
availability may further reduce what the server accepts. They do not make an
available method disappear.

If the server accepts none of the requested notifications, the acknowledged
filter **MUST** be `{}`.

### Completing an empty subscription

When the method is available but the server accepts no requested
notifications, it **MUST**:

1. send `notifications/subscriptions/acknowledged` first, with
   `params.notifications` equal to `{}` and
   `params._meta["io.modelcontextprotocol/subscriptionId"]` equal to the listen
   request ID;
2. send no subscription event for that subscription;
3. send the successful final `SubscriptionsListenResult` with
   `resultType: "complete"`;
4. set the final result's
   `result._meta["io.modelcontextprotocol/subscriptionId"]` and JSON-RPC `id`
   to the listen request ID; and
5. release all state held for that subscription.

The server does not wait for an event before sending the final result.
An empty acknowledged filter is a completed subscription, not an idle one.

These ordering rules apply to one subscription ID. Messages for other
subscriptions may appear between the acknowledgment and final result on a
shared stdio channel.

Over Streamable HTTP, the server **MUST** use a successful
`text/event-stream` response containing, in this order:

1. an SSE message carrying the acknowledgment;
2. an SSE message carrying the final JSON-RPC result; and
3. normal completion of the SSE response body.

Ending the response body ends that request stream. It does not require the
server to close the underlying TCP or TLS connection.

On stdio, the server sends the acknowledgment and final result as
newline-delimited JSON-RPC messages, then clears the logical subscription
state.

The client **MUST** treat the valid final result as graceful completion,
whether it arrives before the HTTP response body ends or on a shared stdio
channel. It **SHOULD NOT** automatically recreate the same empty subscription.

## Rationale

The proposal keeps three states visible:

| State | Outcome |
| --- | --- |
| Method unavailable | matching `404/-32601`; no acknowledgment or stream |
| Nothing accepted | acknowledgment `{}`, final result, response completion |
| One or more notifications accepted | acknowledgment, then an active subscription |

Using `-32601` only for a missing method preserves its normal JSON-RPC meaning.
An empty accepted request follows the regular subscription lifecycle and ends
with an explicit result rather than an unexplained transport loss.

Capability checks prevent clients from opening subscriptions that discovery
already shows will be useless. They do not replace authorization and do not
promise that the server will accept a particular selector or URI.

### Current SDK behavior (non-normative)

The following summary is based on current upstream source inspected on
2026-08-04. The repository's live interoperability evidence was collected
against pinned revisions on 2026-07-31. It demonstrates the different server
lifecycles, but the current behaviors below are source-inspected and were not
all rerun as live tests.

- **Python SDK (`a4f4ccd`)**: A low-level server can omit the listen handler,
  which produces `404/-32601`. The high-level `MCPServer` always installs the
  handler. If it acknowledges an actually empty filter, it keeps that
  subscription open until it is cancelled or closed. The client does not open
  listen streams automatically. An explicit `Client.listen()` checks the
  protocol version, but not the advertised notification capabilities.
- **TypeScript SDK (`cc4b416`)**: The standard server always exposes the route
  and keeps an acknowledged empty SSE subscription open. Its automatic
  `listChanged` mode intersects configured handlers with the server's
  advertised core capabilities and skips the call when the intersection is
  empty. An explicit `listen()` call does not perform that check. A matching
  `404/-32601` is currently surfaced as an HTTP-shaped `SdkHttpError`.
- **Go SDK (`7256941`)**: The standard server always exposes the method. It
  filters the request against its capabilities and, when the result is empty,
  sends the acknowledgment and final result immediately. The client opens an
  automatic listen stream when local list-change handlers are configured, but
  does not first intersect them with discovered server capabilities. Its
  current HTTP transport attempts to decode a JSON-RPC error body before
  treating a bare `404` as a missing session.

No current SDK implements the whole proposal. Low-level Python demonstrates
method absence, TypeScript demonstrates capability-aware automatic preflight,
and Go demonstrates finite completion of an empty subscription.

## Backward Compatibility

This proposal changes servers that expose a listen method even though they
support no selectors, or that keep empty subscriptions open. It also changes
clients that call the method automatically without checking discovery, treat
every `404` as method absence, or make the entire session fail when listening
is unavailable.

Adoption should target a new protocol revision. During migration, clients may
encounter older servers that acknowledge an empty filter and leave the stream
open. Clients without current, applicable discovery may continue to call the
method and handle the result.

## Security Implications

Avoiding empty long-lived streams reduces denial-of-service exposure from
subscription slots, tasks, queues, timers, and buffered events.

Discovery may differ between authorization or tenant contexts. Clients must
not reuse it outside the context where it was obtained, and servers must still
authorize each request. A server must not disguise a request-specific denial
as `-32601`.

Implementations should limit URI counts, filter size, concurrent streams, and
buffered events. They should also avoid revealing whether an unauthorized URI
exists.

## Reference Implementation

Reference implementation: TBD.

The implementation should pin its protocol revision and commit. It should
demonstrate capability preflight, matching method absence, an empty
acknowledgment, matching subscription metadata, a successful final result, and
response-body completion.

## Testing Plan

Tests should cover:

- a server that does not make listening available;
- matching and proxy-generated `404` responses;
- missing or stale discovery;
- Boolean and URI-array filtering;
- empty and non-empty acknowledged filters;
- ordering for each subscription ID;
- matching acknowledgment and final-result metadata;
- `resultType: "complete"`;
- response-body completion without closing the connection; and
- continued use of the MCP session after listening is unavailable.

## Open Questions

1. Should a deployment with no enabled core or extension selector be required
   to make `subscriptions/listen` unavailable, even if its SDK has installed a
   route for the method?
2. Should the protocol add one capability for `subscriptions/listen`, or
   should each core and extension selector continue to have its own discovery
   mapping?
3. How should Tasks advertise optional `taskIds` push notifications separately
   from general Tasks support?
4. Should every empty acknowledged filter complete immediately, including one
   made empty by authorization or policy, or should those cases be handled
   differently?
5. Should method availability be fixed for a deployment, as proposed here, or
   may it vary by authorization or tenant?
6. Should Streamable HTTP require one finite JSON error body for a matching
   `404/-32601` response?
7. Should the acknowledgment schema require the subscription ID that the
   normative text already requires?
