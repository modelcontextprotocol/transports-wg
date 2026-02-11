# SEP-XXXX: Tasks are (not) Progress

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

However, in Streamable HTTP, combining these features creates ambiguous behavioral tradeoffs regarding the `input_required` status, which is not specified to be used with notifications in the first place - only with requests. If a server wishes to send progress notifications to a client, it must decide if those notifications should be sent on the GET stream used for background messages, side-channeled on the SSE stream during the `tasks/get` operation, or side-channeled during the `tasks/result` operation. In the case of the background stream and `tasks/result`, this forces the server to keep an active handler for the full duration of the task lifetime, and in the case of `tasks/get`, the server must be able to dequeue server-to-client events in a consistent order from any invocation of the `tasks/get` method.

To sidestep this complexity, this proposal introduces progress fields directly into tasks, allowing servers to simply always have a mechanism for communicating progress changes without navigating stream selection at all.

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

It has been previously-suggested to build progress support into tasks (for example [here](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/1732#discussion_r2501534339)), and the two features have always served recognizably-similar roles if you squint hard enough, with progress representing the simple use case of "I have a long-running operation and want to show a completion rate for it in my UI" and tasks representing the more complex use case of "and specifically, I want to dispatch background work that I'll choose to fetch the actual result for sometime after it completes."

Tasks serve a use case that progress could not meet in its current form, as notifications fundamentally imply some sort of active process on the server that is able to asynchronously dispatch those notifications in the first place. With tasks, an entire operation flow can be executed on stateless infrastructure (for example, a serverless function) by offloading execution to another system (such as an external job manager) without wasting compute by forcing a single instance to actively poll the upstream system internally to e.g. a tool call.

At the time that tasks were proposed, the distinctions between progress and tasks made it unreasonable to force tasks into the paradigm of progress, or to add progress fields to tasks, which would have rendered progress somewhat redundant. However, in light of the fact that communicating progress for a task is useful, combined with the complexities around streaming progress notifications back to the client from within a task (described in the Motivation section), it is clear now that duplicating a notion of progress into tasks would not render progress notifications redundant at all, and indeed there are use cases where progress is relevant despite not using tasks at all.

## Backward Compatibility

This change has no backwards-compatibility concerns.

## Security Implications

No new security implications are introduced by this proposal.

## Reference Implementation

To be provided.
