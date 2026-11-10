# Subscription Lifecycle Guidance

> **Working-group guidance draft.** Recommends SDK defaults using existing MCP
> mechanisms; does not add protocol conformance requirements.

`subscriptions/listen` should deliver notifications a client needs, not probe
server functionality or maintain an empty stream. This guidance concerns the
`subscriptions/listen` lifecycle in protocol revision `2026-07-28` and the
current draft, not the earlier HTTP GET subscription mechanism.

## Servers

- **Expose listening only when useful.** If no core or extension notification
  selector is supported, prefer not to expose `subscriptions/listen`. An
  unavailable method follows existing error rules: JSON-RPC `-32601`, with
  HTTP `404` over Streamable HTTP. An empty resource or tool list, or a period
  without events, does not mean notification support is unavailable.
- **Accept only supported, permitted notifications.** The acknowledgment
  reports the accepted subset of the request, including any accepted extension
  selectors. A refusal of a particular request is not method absence.
- **Complete empty subscriptions promptly.** If a valid request is accepted for
  processing but no notifications are accepted, send:
  1. An acknowledgment with `notifications: {}`.
  2. The normal successful completion result with `resultType: "complete"`.
  3. End the HTTP response stream, or release the logical subscription on stdio.

Follow the existing [subscription lifecycle][subscriptions] for these messages.
This ends only the subscription, not the client's connection to MCP.
Requests that fail validation or authorization can still be rejected with an
error rather than acknowledged.

## Clients

- **Subscribe only when the application needs notifications**, not just to find
  out whether listening is available.
- **Use discovery to avoid unnecessary automatic subscriptions.** If the
  advertised capabilities show no support for the notifications you need, skip
  listening. Discovery is not a prerequisite for an explicit application request.
- **Let an empty subscription finish.** Treat the server's completion result as
  a normal end, and do not immediately reopen the same subscription.

## Existing Specification Basis

These recommendations build on existing mechanisms:

- [Subscriptions][subscriptions]: accepted-subset acknowledgments,
  subscription-ID correlation, ordering, and server-initiated graceful completion.
- [Streamable HTTP][http]: method-not-found errors, response formats, and SSE
  response termination.
- [Discovery][discovery] and [caching][caching]: optional client discovery and
  rules for reusing discovery results.
- [Tools][tools], [prompts][prompts], and [resources][resources]: core notification
  capabilities; [extensions][extensions] define their own settings.

The current specification does not require every zero-selector server to omit
listening or every empty subscription to complete promptly. Those are SDK
recommendations here, not additional conformance requirements.

## SDK Findings from the Earlier Investigation

The following summary records upstream source inspection on 2026-08-04. The
earlier investigation reports live interoperability testing against pinned
revisions on 2026-07-31, but the harness and traces are not included in this
branch. The behaviors below were source-inspected and were not all rerun as
live tests; they have not been revalidated for this guidance update.

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

None of those inspected SDK revisions follows all of these recommendations.
Low-level Python demonstrates method absence, TypeScript demonstrates
capability-aware automatic preflight, and Go demonstrates finite completion of
an empty subscription.

[subscriptions]: https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions
[http]: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
[discovery]: https://modelcontextprotocol.io/specification/2026-07-28/server/discover
[caching]: https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching
[tools]: https://modelcontextprotocol.io/specification/2026-07-28/server/tools
[prompts]: https://modelcontextprotocol.io/specification/2026-07-28/server/prompts
[resources]: https://modelcontextprotocol.io/specification/2026-07-28/server/resources
[extensions]: https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning
