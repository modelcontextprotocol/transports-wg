# SEP-0000: Tasks are Progress

- **Status**: Proposal
- **Type**: Standards Track
- **Created**: 2026-01-30
- **Author(s)**: Luca Chang (@LucaButBoring)
- **Sponsor**: None
- **PR**: https://github.com/modelcontextprotocol/transports-wg/pull/{NUMBER}

## Abstract

**Tasks** were introduced in an experimental state in the `2025-11-25` specification release, serving as an alternate execution mode for certain request types (tool calls, elicitation, and sampling) to enable polling for the result of an augmented operation. Conversely, **progress** exists to receive information about the status of a long-running operation via JSON-RPC notifications. This proposal consolidates progress notifications into tasks, creating a unified and cohesive way for clients and servers to share updates with each other.

## Motivation

*Note: For ease of understanding, we use client/server terminology throughout this proposal. In reality, this is a peer-to-peer flow in which either party may dispatch a request. The Tasks and Progress specifications use "requestor" and "receiver" to decouple themselves from the assumption that these features apply only to client requests.*

Today, tasks and progress notifications represent mirrored execution models:

- **Tasks** represent a client-driven, polling-based execution model, where the client needs to be active intermittently to execute polling requests to check the status of an operation, and to eventually retrieve the final result.
- **Progress** represents a server-driven, push-based execution model, where the client and server share a continuous, long-running response stream for the server to send notifications on, prior to the server returning a final result.

Each protocol feature can be used independently of the other; they can also be used together. Tasks were given a `statusMessage` field that mirrors progress's `message` field, but were deliberately not given an equivalent to progress's `progress` and `total` fields to attempt to avoid creating ambiguity between their use cases. It would have been a mistake for the two to differ _only_ by execution model when tasks also imply a degree of state management around results that progress notifications lack.

However, [Multi Round-Trip Requests (MRTR)](https://github.com/modelcontextprotocol/transports-wg/pull/7) violate the assumptions that progress notifications are built on, and under MRTR semantics it becomes impossible for progress notifications to continue to represent meaningful state (as every request becomes stateless). Being able to report progress updates is still useful for UX purposes such as suggesting how many longer a slow operation may take, and that use case should not be invalidated. Instead, MRTR creates an opportunity for MCP to commit to tasks as a unified solution for all persistent operations by interpreting progress notifications as a subset of this and removing them entirely.

## Specification

`Task`, which is returned in the `task` field of `CreateTaskResponse`, as the complete result of `tasks/get`, and in the optional task notifications, will gain optional `progress` and `progressTotal` fields:

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

As with progress notifications, `progress` **MUST** be monotonically increasing, and `progressTotal` will remain optional as the total amount of work may be unknown. Both values may be floating-point numbers. *In addition* to these properties, we will define the following new behavior for `progressTotal`, as it was previously underspecified:

1. `progressTotal` **MAY** be omitted, but if it is provided it **MUST** be greater than or equal to `progress`.
2. `progressTotal` **MAY** change between requests, but it **MUST** be monotonically increasing (similar to `progress`). A changing total may represent new work being discovered, for example.

The Progress specification, the associated `ProgressNotification` and `ProgressNotificationParams` types, and the reserved `_meta.progressToken` field will be completely removed from the protocol.

## Rationale

### Why get rid of something that exists?

It has been previously-suggested to build progress support into tasks (for example [here](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/1732#discussion_r2501534339)), and the two features have always served recognizably-similar roles if you squint hard enough, with progress representing the simple use case of "I have a long-running operation and want to show a completion rate for it in my UI" and tasks representing the more complex use case of "and specifically, I want to dispatch background work that I'll choose to fetch the actual result for sometime after it completes."

Tasks serve a use case that progress could not meet in its current form, as notifications fundamentally imply some sort of active process on the server that is able to asynchronously dispatch those notifications in the first place. With tasks, an entire operation flow can be executed on stateless infrastructure (for example, a serverless function) by offloading execution to another system (such as an external job manager) without wasting compute by forcing a single instance to actively poll the upstream system internally to e.g. a tool call.

At the time that tasks were proposed, the distinctions between progress and tasks made it unreasonable to force tasks into the paradigm of progress, or to add progress fields to tasks (which would have rendered progress somewhat redundant). While we could have taken the latter approach and proactively removed progress, the experimental nature of tasks combined with a reluctance to make any breaking changes led to a "safer" solution that favored making tasks less useful to allow other existing features to exist largely unchanged. Regardless, there wasn't much of a need to "change what worked," as it were — even if something could be removed, there was never any urgent need to remove it.

With the shift to MRTR, this changes: Progress notifications no longer work as originally-designed, so MCP is forced to either somehow shim their logic on top of MRTR semantics or remove them altogether. The former option would be both surprising and semantically-incorrect (progress resets after responding to an elicitation/sampling request). Consolidating progress into tasks respects the use cases of progress without being forced to maintain it in a vestigal state.

## Backward Compatibility

From a protocol standpoint, this proposal introduces no backwards-incompatible behavior. No special behavior is necessary for the removal of Progress; clients should cease to send it, and if a server implements this specification and encounters a request with `_meta.progressToken`, it will simply ignore it. This is consistent with how progress notifications were already handled: The client could not assume that it would actually receive progress notifications just because it provided a progress token in its request.

From an application-developer's standpoint, however, this is obviously breaking — progress notifications won't exist anymore. Applications leveraging progress notifications as a signaling mechanism are encouraged to adopt tasks instead. As an interim implementation on the client side, applications can treat existing progress notifications and task progress as equivalent, wiring task progress into existing UI components etc., with progress handlers being fully-removed at a later point in time.

## Security Implications

No new security implications are introduced by this proposal.

## Reference Implementation

To be provided.
