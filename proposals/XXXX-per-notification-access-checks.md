# SEP-XXXX: Per-Notification Access Checks for Subscription Streams

- **Status**: Draft
- **Type**: Standards Track
- **Created**: 2026-10-29
- **Author(s)**: Ramjot Singh (@RamjotSingh)
- **Sponsor**: None (seeking sponsor)
- **PR**: TBD
- **Requires**: [#67][sep-ending] (Ending Subscription Streams When Authorization Ends)
- **Related**: [transports-wg#62][issue-62] (discussion); split from [#63][pr-63]

## Abstract

A server checks two things before it serves a request: that the access token is valid, and that the principal may access what the request asks for, such as a file whose ACL lists them or a conversation they belong to. [Ending Streams][sep-ending] applies the first check to `subscriptions/listen` streams for their whole life. This SEP applies the second: before writing a notification, the server applies the access checks it would apply to a request for the same information, and drops the notification if they fail. A stream that loses access to some of what it watches keeps the rest. A stream that loses access to all of it ends with `revoked`, preferably at a moment that does not reveal when a resource the principal can no longer read changed.

## Motivation

Access to a resource changes independently of tokens: a user is removed from an HR case, leaves a team, or loses a share. A request after the change is refused, but a stream opened before it keeps delivering `notifications/resources/updated` for the resource, revealing when a resource that the principal can no longer read changes. Notifications about sub-resources raise the same question without any change in access: a stream that watches a team can receive updates for a private channel in it, which the principal may never have been able to read.

Ending the stream is not the answer. A permission change on one resource would disconnect the client from all the others, and the end itself would tell the client that something it can no longer see just changed.

## Specification

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "NOT RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in BCP 14 ([RFC 2119][rfc2119], [RFC 8174][rfc8174]) when, and only when, they appear in all capitals.

### 1. Scope and definitions

This specification applies where [Ending Streams][sep-ending] applies, and uses its definitions of server and stream authorization.

- **Acknowledged entry**: a notification type that a stream's acknowledgment enables, or an item in one of its lists, such as a URI in `resourceSubscriptions`.

### 2. Checking each notification

1. Before writing a notification, a server MUST check that the stream authorization permits it, applying the access checks it would apply to a request for the same information, and MUST NOT write a notification that fails them. This includes notifications about sub-resources: a `notifications/resources/updated` for a URI below a listed one is dropped, with no other signal to the client, when the principal cannot read that URI. A server MAY cache the results of these checks as it would for requests.
2. The server drops the notifications that these checks keep off a stream, and MUST NOT write them to any other stream or subscription, as [Ending Streams][sep-ending] requires.

### 3. Losing access to entries

1. When the stream authorization no longer permits some of the stream's acknowledged entries, the server stops writing notifications for those entries, and the stream continues. A server MUST NOT end a stream because its authorization no longer permits part of what the stream carries.
2. When the stream authorization no longer permits any of the stream's acknowledged entries, the server MUST end the stream with `AuthorizationEnded` and reason `revoked` ([Ending Streams, section 5][sep-ending-5]). The meaning of `revoked` extends to this case: no acknowledged entry remains, and new credentials from the same grant are not expected to help.
3. A server that learns that no entry remains while processing a change to one of them SHOULD NOT end the stream at that moment, because the end would tell the client that a resource it can no longer read has just changed. It can instead end the stream when the stream would otherwise end for authorization reasons, such as at its authorization expiry, or at an earlier moment unrelated to the change. A server that learns of the loss from an access-change signal, rather than from a change to the resource, MAY end the stream at once.

### 4. Guidance for extensions (non-normative)

An extension whose subscriptions name a single target, such as an Events subscription, which names one event and its arguments ([SEP-3415][sep-3415]), has nothing left to deliver once access to that target is lost, so its long-lived request ends. When the server learns of the loss while processing a change to the target, it can end the request as [section 3](#3-losing-access-to-entries), rule 3 recommends: when it would otherwise end, or at a moment unrelated to the change. Ending it at once would tell the client that the target has just changed.

### 5. Changes to specification documents

- **Resources** (`server/resources`): in Subscriptions, state that the server checks each `notifications/resources/updated` against the stream's authorization, and drops those for URIs the principal cannot read.
- **Subscriptions** (`basic/patterns/subscriptions`): state that a stream continues when access to part of it is lost, and ends with `revoked` when none remains, preferably at a moment unrelated to any change.

### 6. Examples

A stream watches `file:///project/config.json` and `file:///hr/case-114.md`. The principal is removed from the HR case. The server learns of it when `case-114.md` next changes: it drops that change, stops writing notifications for `case-114.md`, and keeps delivering changes to `config.json`.

Had `case-114.md` been the stream's only entry, the server would have ended the stream with `revoked`. Following [section 3](#3-losing-access-to-entries), rule 3, it would do so not when the change arrived, but at the stream's authorization expiry, or earlier if it received a signal that the principal's access had changed.

## Rationale

### Check each notification, lazily

Streams do not change the authorization model. Applying to each notification the checks the server would apply to a request for the same information keeps sub-resources with their own permissions, such as a private channel in a team the principal belongs to, out of the stream without ending it. Checking when a notification is written is enough: a notification that fails the check is never delivered, whenever the access changed.

### Keep the stream when part of it is lost

Ending a stream when one of its entries is lost would turn a permission change on one resource into a disconnect for all the others, and would loop when the loss is finer than an acknowledgment can express, such as a single sub-resource.

### Avoid revealing when an unreadable resource changed

Servers that check lazily usually discover a loss of access when a change to the resource arrives. Ending the stream at that moment would tell the client that a resource it can no longer read has just changed, which is the information the check exists to withhold.

The rule is a recommendation, not a requirement. The end reveals that something changed, not what changed. And deferring it protects less than it seems: a stream whose authorization lasts a short time ends soon after the change anyway, and the client can still connect the two. Server implementors weigh that exposure against their data and the lifetime of their streams.

### Alternatives considered

- **End the stream when access to part of it is lost.** See [Keep the stream when part of it is lost](#keep-the-stream-when-part-of-it-is-lost).
- **Check only when the stream opens.** Leaves every change in access unenforced for the stream's lifetime.
- **Signal each dropped notification.** Would reveal when resources that the principal cannot read change.

## Backward Compatibility

There are no wire changes. Clients of every protocol version stop receiving notifications they are not authorized to receive. A stream whose last entry is lost ends as [Ending Streams][sep-ending] describes, which older clients see as a close without a response.

## Security Implications

- **What this changes.** A stream never delivers a notification that the principal could not obtain with a request.
- **Latency.** A loss of access is caught at the next notification about the resource, or sooner when the server receives an access-change signal.
- **Timing.** A server that follows [section 3](#3-losing-access-to-entries), rule 3 does not end a stream at the moment it discovers, while processing a change, that the stream has lost access to everything it watches. One that does reveals that a resource the principal can no longer read changed, but not what changed.

## Performance Implications

Per-notification access checks cost what the same checks cost for requests, and can be cached the same way.

## Reference Implementation

A [prototype][prototype-a] on a fork of the TypeScript SDK (branch `poc/authorization-lifetime`) implements this SEP. It predates the split: it implements the combined draft in [#63][pr-63], and its test names cite that draft's sections.

- **Server**: [`listenRouter.ts`][router-a] passes every notification through a pluggable access check, `authorize(authInfo, target)`. It stops delivering a denied entry and keeps the stream; when the last entry is lost during a change, it ends the stream only at the deadline. The control API `handler.subscriptions.recheckAccess()` stands in for an access-change signal.
- **Tests** ([server][server-tests-a]): "deny for one listed resource silently removes it and keeps the stream open"; "an access-change signal awaits async checks and ends a stream left with no entries with revoked"; "last-entry removal discovered on a change ends with revoked only at the deadline".
- **Demo** ([README][demo-a]): scenario 3, step 3. Access to the HR case is revoked during a change to it: stream A keeps receiving changes to `config.json`, notifications about the HR case stop, and stream B, whose only entry is the HR case, stays open past the change instead of revealing when it happened.

## Testing Plan

Conformance scenarios, for the [conformance repository][conformance]:

**Server, required**

1. Drops a notification about a resource that the principal cannot read, and keeps the stream open while other acknowledged entries remain.
2. When the principal loses access to every listed resource, ends the stream with reason `revoked`.

**Server, recommended**

1. Ends that stream at its authorization expiry, or at a moment unrelated to any change, rather than at the moment of a change to one of the resources.

[issue-62]: https://github.com/modelcontextprotocol/transports-wg/issues/62
[pr-63]: https://github.com/modelcontextprotocol/transports-wg/pull/63
[sep-ending]: https://github.com/modelcontextprotocol/transports-wg/pull/67
[sep-ending-5]: https://github.com/RamjotSingh/transports-wg/blob/sep/ending-streams-when-authorization-ends/proposals/XXXX-ending-streams-when-authorization-ends.md#5-ending-a-stream-for-authorization-reasons
[sep-3415]: https://github.com/modelcontextprotocol/modelcontextprotocol/pull/3415
[conformance]: https://github.com/modelcontextprotocol/conformance
[rfc2119]: https://www.rfc-editor.org/rfc/rfc2119
[rfc8174]: https://www.rfc-editor.org/rfc/rfc8174
[prototype-a]: https://github.com/RamjotSingh/typescript-sdk/blob/poc/authorization-lifetime/AUTHORIZATION-LIFETIME-PROTOTYPE.md
[router-a]: https://github.com/RamjotSingh/typescript-sdk/blob/poc/authorization-lifetime/packages/server/src/server/listenRouter.ts
[server-tests-a]: https://github.com/RamjotSingh/typescript-sdk/blob/poc/authorization-lifetime/packages/server/test/server/subscriptionLifetime.test.ts
[demo-a]: https://github.com/RamjotSingh/typescript-sdk/blob/poc/authorization-lifetime/examples/authorization-lifetime/README.md
