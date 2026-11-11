# SEP-XXXX: Refusing Subscription Filters That Are Not Wholly Permitted

- **Status**: Draft
- **Type**: Standards Track
- **Created**: 2026-10-29
- **Author(s)**: Ramjot Singh (@RamjotSingh)
- **Sponsor**: None (seeking sponsor)
- **PR**: TBD
- **Related**: [transports-wg#62][issue-62] (discussion); split from [#63][pr-63]

## Abstract

When a `subscriptions/listen` request lists a resource that the principal may not access, the specification does not say what the server does. It might acknowledge the entry and then deliver nothing for it, or leave it out of the acknowledgment, which clients may not notice. This SEP makes the request all or nothing: the server refuses it with `-32602` (Invalid params), names the entries it does not permit in `data.denied`, and opens no stream. The refusal is an ordinary JSON-RPC error, which the server sends to clients of every protocol version.

## Motivation

The acknowledgment already omits notification types that the server does not support ([Subscriptions: Acknowledgment][subs-ack]), and a server could omit entries the principal may not access in the same way. But a client that does not compare the acknowledgment with its request would then believe it is watching resources that it is not, and a client that does compare learns only that something is missing, not why.

The question comes up whenever access changes between two requests: a client that re-establishes a stream after its token expired ([Ending Streams][sep-ending]) asks again for everything it watched before, and may no longer be allowed all of it.

## Specification

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "NOT RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in BCP 14 ([RFC 2119][rfc2119], [RFC 8174][rfc8174]) when, and only when, they appear in all capitals.

### 1. Scope

This specification applies to `subscriptions/listen` requests authorized with an MCP access token, which today means requests on Streamable HTTP. It does not apply to stdio, where implementations retrieve credentials from the environment ([Overview: Auth][overview-auth]).

The refusal is a JSON-RPC error, and its meaning does not depend on the transport. On Streamable HTTP, a server MUST send it with HTTP status `200`, and a client acts on the JSON-RPC message, not on the status. The token errors that the Authorization specification defines over HTTP are unchanged ([Authorization: Error Handling][auth-errors]).

### 2. Refusing a filter

A stream opens with all of its filter, or not at all.

1. When a `subscriptions/listen` request lists an entry that the request's authorization does not permit, the server MUST NOT acknowledge the rest of the filter. It responds to the request with a `SubscriptionDeniedError` ([section 4](#4-schema-changes)): error code `-32602` (Invalid params), with `data.denied` listing the entries it does not permit, in the form of a `SubscriptionFilter`. No stream opens.
2. The error is an ordinary JSON-RPC error response, the same on every transport; on Streamable HTTP its status is `200`, not `403`. The server sends it whatever protocol version the client uses, and whether or not it has committed the HTTP response.
3. This error is for entries the principal may not access. When the token lacks a scope that an entry requires, the server instead responds with the `insufficient_scope` challenge that the Authorization specification defines ([Authorization: Step-Up Authorization Flow][auth-stepup]).
4. An access check that fails or is unavailable is not a refusal: the server acknowledges the entry.
5. The acknowledgment still omits notification types that the server does not support ([Subscriptions: Acknowledgment][subs-ack]).

An entry is a notification type that the filter enables, or an item in one of its lists, such as a URI in `resourceSubscriptions`.

### 3. Client handling

1. A client whose request is refused SHOULD report the entries listed in `data.denied` to the application, and MAY open the stream again without them.
2. A client MUST NOT start interactive authorization because of the refusal: no new token lets a principal access a resource it may not access.

### 4. Schema changes

Additions to `schema/draft/schema.ts`:

```typescript
/**
 * Sent in response to a subscriptions/listen request whose filter lists
 * entries that the request's authorization does not permit. The server opens
 * no stream and sends no acknowledgment.
 *
 * @category Errors
 */
export interface SubscriptionDeniedError extends Omit<
  JSONRPCErrorResponse,
  "error"
> {
  error: InvalidParamsError & {
    data: {
      /**
       * The requested entries that the authorization does not permit.
       */
      denied: SubscriptionFilter;
    };
  };
}
```

`SubscriptionDeniedError` uses the existing `-32602` (Invalid params), which every protocol version defines, as `resources/read` does for a resource that does not exist ([Resources: Error Handling][resources-errors]). The documentation of `InvalidParamsError` adds subscriptions to the contexts it lists.

### 5. Changes to specification documents

- **Subscriptions** (`basic/patterns/subscriptions`): in Acknowledgment, state that the acknowledgment is never narrowed for authorization reasons, and that a filter listing entries the authorization does not permit is refused with `SubscriptionDeniedError`.
- **Streamable HTTP** (`basic/transports/streamable-http`): in Receiving Messages, state that the refusal is sent with HTTP status `200`.
- **Schema** and **Changelog**: the addition above.

### 6. Examples

A request for a stream on `file:///project/config.json` and a resource that the user can no longer read is refused, and no stream opens:

```json
{
  "jsonrpc": "2.0",
  "id": 9,
  "error": {
    "code": -32602,
    "message": "Not permitted",
    "data": {
      "denied": { "resourceSubscriptions": ["file:///hr/case-114.md"] }
    }
  }
}
```

The client can open the stream again on `file:///project/config.json` alone, and tell the application that it no longer receives changes to the other resource.

## Rationale

### Refuse rather than narrow

Refusing the request and naming the entries makes the change explicit, at the cost of one more request. A narrowed acknowledgment would be easy to miss and would not say why. The refusal reveals no more than requests for the same information would, because the server applies the same access checks.

### Use an error code every version defines

The refusal is a JSON-RPC error, so it is the same on every transport. It is not an HTTP `403`. In the Authorization specification, `403` concerns the token, and with `insufficient_scope` it asks the client to obtain more scope, which cannot help when the principal may not access a resource at all; and a `403` can lead a client to interactive authorization. The error uses `-32602`, which every protocol version defines, so the server refuses clients of every version in the same way. A new code would be defined only by the revision that adopts this SEP, and could not be sent to older clients.

### Alternatives considered

- **Acknowledge the permitted part of a filter.** The client may not notice what is missing, and cannot tell why. See [Refuse rather than narrow](#refuse-rather-than-narrow).
- **Refuse a filter with HTTP `403`, or with a new error code.** See [Use an error code every version defines](#use-an-error-code-every-version-defines).
- **Reuse `Forbidden` from the Events extension.** [SEP-3415][sep-3415] requests `Forbidden` (`-32024`) as a general-purpose code for reuse across MCP. A new code exists only from the revision that defines it, so a server could not send it to the clients of earlier versions that this refusal has to reach. SEP-3415 itself leaves open whether its codes should be `InvalidParams` with typed `data` instead, which is what this SEP uses.

## Backward Compatibility

An older client whose filter lists an entry it may not access receives `-32602` instead of an acknowledgment: an ordinary request error, which it can handle without understanding `data.denied`. Clients whose filters are wholly permitted see no change.

## Security Implications

- **Refusals name entries.** A refused request learns which of the entries it asked for the principal may not access. That is no more than requests for the same information reveal, since the server applies the same access checks.
- **No prompts.** A refusal never leads to interactive authorization ([section 3](#3-client-handling), rule 2).

## Performance Implications

A refused client pays one more request to open the stream without the entries it may not access.

## Reference Implementation

A [prototype][prototype-a] on a fork of the TypeScript SDK (branch `poc/authorization-lifetime`) implements this SEP. It predates the split: it implements the combined draft in [#63][pr-63], and its test names cite that draft's sections.

- **Server**: when a stream opens, [`listenRouter.ts`][router-a] checks each entry of the filter through the same pluggable access check it applies to notifications, `authorize(authInfo, target)`, and refuses the request with `-32602` and `data.denied` if any entry is denied.
- **Tests** ([server][server-tests-a]): "a filter with entries the authorization does not permit is refused with -32602 naming them in data.denied, and no stream opens"; "a client of an earlier protocol version gets the same refusal"; "without the denied entries the same filter is acknowledged in full, including an entry whose check is unavailable"; "a filter with no permitted entry is refused with -32602 naming every entry, and no stream opens".
- **Demo** ([README][demo-a]): scenario 3, step 4. After its deadline, stream A reopens with its old filter and is refused, naming `case-114.md`; the client reopens it on `config.json` alone and reports the change in coverage. Stream B is refused the same way, and the client reports the loss without prompting.

## Testing Plan

Conformance scenarios, for the [conformance repository][conformance]:

**Server, required**

1. Answers a `subscriptions/listen` request that lists a resource the principal cannot read, alongside one it can, with error `-32602` whose `data.denied` lists exactly that resource, sent with HTTP status `200` and without an acknowledgment; acknowledges the same filter without that resource in full.
2. Gives the same refusal to a request that declares an older protocol version.

**Client, required**

1. When a request is refused with `data.denied`, reports the entries listed to the application, without prompting the user.

[issue-62]: https://github.com/modelcontextprotocol/transports-wg/issues/62
[pr-63]: https://github.com/modelcontextprotocol/transports-wg/pull/63
[sep-ending]: https://github.com/modelcontextprotocol/transports-wg/pull/67
[subs-ack]: https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions#acknowledgment
[auth-errors]: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization#error-handling
[auth-stepup]: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization#step-up-authorization-flow
[overview-auth]: https://modelcontextprotocol.io/specification/2026-07-28/basic/index#auth
[resources-errors]: https://modelcontextprotocol.io/specification/2026-07-28/server/resources#error-handling
[sep-3415]: https://github.com/modelcontextprotocol/modelcontextprotocol/pull/3415
[conformance]: https://github.com/modelcontextprotocol/conformance
[rfc2119]: https://www.rfc-editor.org/rfc/rfc2119
[rfc8174]: https://www.rfc-editor.org/rfc/rfc8174
[prototype-a]: https://github.com/RamjotSingh/typescript-sdk/blob/poc/authorization-lifetime/AUTHORIZATION-LIFETIME-PROTOTYPE.md
[router-a]: https://github.com/RamjotSingh/typescript-sdk/blob/poc/authorization-lifetime/packages/server/src/server/listenRouter.ts
[server-tests-a]: https://github.com/RamjotSingh/typescript-sdk/blob/poc/authorization-lifetime/packages/server/test/server/subscriptionLifetime.test.ts
[demo-a]: https://github.com/RamjotSingh/typescript-sdk/blob/poc/authorization-lifetime/examples/authorization-lifetime/README.md
