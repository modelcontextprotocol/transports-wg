# SEP-XXXX: Task Progress

- **Status**: Proposal
- **Type**: Standards Track
- **Created**: 2026-01-30
- **Author(s)**: Luca Chang (@LucaButBoring)
- **Sponsor**: None
- **PR**: https://github.com/modelcontextprotocol/transports-wg/pull/11

## Abstract

**Tasks** were introduced in an experimental state in the `2025-11-25` specification release, serving as an alternate execution mode for certain request types (tool calls, elicitation, and sampling) to enable polling for the result of an augmented operation. Conversely, **progress** exists to receive information about the status of a long-running operation via JSON-RPC notifications. While their use cases are partially-overlapping, they are often mutually-exclusive, and using progress notifications on top of tasks adds unnecessary complexity to implementations, which now need to consider that progress notifications may span multiple requests in task operations. To simplify implementations, this proposal reintroduces request-scoped progress notifications and adds progress fields to task metadata, reducing the need to combine the two features.

## Motivation

*Note: For ease of understanding, we use client/server terminology throughout this proposal. In reality, this is a peer-to-peer flow in which either party may dispatch a request. The Tasks and Progress specifications use "requestor" and "receiver" to decouple themselves from the assumption that these features apply only to client requests.*

Today, tasks and progress notifications represent mirrored execution models:

- **Tasks** represent a client-driven, polling-based execution model, where the client needs to be active intermittently to execute polling requests to check the status of an operation, and to eventually retrieve the final result.
- **Progress** represents a server-driven, push-based execution model, where the client and server share a continuous, long-running response stream for the server to send notifications on, prior to the server returning a final result.

Each protocol feature can be used independently of the other; they can also be used together. Tasks were given a `statusMessage` field that mirrors progress's `message` field, but were deliberately not given an equivalent to progress's `progress` and `total` fields to attempt to avoid creating ambiguity between their use cases. It would have been a mistake for the two to differ _only_ by execution model when tasks also imply a degree of state management around results that progress notifications lack.

Additionally, a change was made to progress notifications to specify that in the case of task-augmented execution, progress tokens remain active for the entire polling lifecycle of a task, rather than only for the duration of the initial request (which may return either `CreateTaskResult` or a standard result type). This was intended to allow progress notifications to remain unique and compatible with tasks, even though tasks also benefit from a notion of progress but conflict with the progress feature's execution model.

Looking forward towards the stabilization of tasks as a protocol feature, there are opportunities to simplify their execution model by introducing a notion of progress into tasks directly. This enables tasks to communicate progress when polled without requiring its association with a separate notification message.

## Specification

`Task`, which is returned in the `task` field of `CreateTaskResult`, as the complete result of `tasks/get`, and in the optional task notifications, will gain optional `progress` and `progressTotal` fields:

```json
{
  "taskId": "bdc2fd8b-442e-40ff-abdb-f33986513750",
  "status": "working",
  "statusMessage": "Reticulating splines...",
  "progress": 6,
  "progressTotal": 7,
  "createdAt": "2026-01-30T18:22:00Z",
  "lastUpdatedAt": "2026-01-30T18:30:00Z",
  "ttl": 30000,
  "pollInterval": 5000
}
```

As with progress notifications, `progress` **MUST** be monotonically increasing, and `progressTotal` will remain optional as the total amount of work may be unknown. Both values may be floating-point numbers. *In addition* to these properties, we will define the following new behavior for `progressTotal` (and `total` in the progress specification), as it was previously underspecified:

1. `progressTotal` **MAY** be omitted, but if it is provided it **MUST** be greater than or equal to `progress`.
2. `progressTotal` **MAY** change between requests, but it **MUST** be monotonically increasing (similar to `progress`). A changing total may represent new work being discovered, for example.

To support use cases that leverage the existing task status notifications, we will modify the notification behavior requirements to allow them to be emitted on any task metadata update - not just when the `status` is changed:

```diff
- When a task status changes, receivers **MAY** send a `notifications/tasks/status` notification to inform the requestor of the change. This notification includes the full task state.
+ When a task's metadata changes, receivers **MAY** send a `notifications/tasks/status` notification to inform the requestor of the change. This notification includes the full task state.
```

## Rationale

### Why duplicate progress into tasks?

TODO

## Backward Compatibility

This change has no backwards-compatibility concerns.

## Security Implications

No new security implications are introduced by this proposal.

## Reference Implementation

To be provided.
