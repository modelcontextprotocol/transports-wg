# 2322-MRTR Design Question Overview

This document provides an design decision that has come up as part of implementing [SEP 2322-MRTR](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2322) that the Transport-WG is split on. 

## Question
Should requests for more information (i.e. the `IncompleteResult` response) be supported as a response type on to all ClientRequests, or should it be limited to a subset of Client Requests?

## Background
In the current protocol version `2025-11-25` and inclusive of the draft version with [SEP-2260](https://modelcontextprotocol.io/seps/2260-Require-Server-requests-to-be-associated-with-Client-requests) servers can send a `elicitation/create`, `sampling/createMessage`, or `roots/list` request in response to any `ClientRequest`. 

In MRTR this behavior is changing to have Servers send `IncompleteResult` responses to `ClientRequest`s in order to request more information. One point of discussion is should we restrict the use of the `IncompleteResult` response to a subset of `ClientRequest`s or should we support it as a response for all `ClientRequest`s.

## Option 1: Arguments for supporting `IncompleteResult` on all `ClientRequest`s
- Backwards compatibility with the current protocol version is preserved.
- It is simpler to implement in the Schema, one learning from Tasks is many edge cases were introduced by only supporting specific Requests & Responses.
- Does not constraing future MCP Server implementors in how they can use `IncompleteResult` responses to request more information from the Client. We may not be able to come up with a good example today of why you would use it for a certain method but does not mean there is not a valid one.
- The edge case of an MCP Server sending an `IncompleteResult` response to a `ClientRequest` that the host does not expect or want to support has minimal impact. The Client can just choose to ignore the request. This is functionaly equivalent to a user refusing to provide the input ot elicitation request.
- Conforms to [MCP Design Principles](https://modelcontextprotocol.io/community/design-principles) of Composability by providing common building blocks vs the speficicity of only supporting it for a subset of Requests & Responses.
- All new `ClientRequest`s added in the future would need to be evaluated for whether they should support `IncompleteResult` responses, which adds cognitive overhead to future design and implementation.

### Schema Changes Required
Below highlights the ClientRequest schema changes required to support MRTR
```typescript
/**
 * Common params for any request.
 *
 * @category Common Types
 */
export interface RequestParams {
  _meta?: RequestMetaObject;
  inputResponses?: InputResponses;
  /* Request state passed back to the server from the client.
   */
  requestState?: string;
}
```

## Option 2: Arguments for supporting `IncompleteResult` on a subset of `ClientRequest`s
- `Tasks` is only supported on a subset of Requests & Responses. 
- There are many `ClientRequest`s that don't have clear use cases where a Server would need to request more information from the Client. Examples include:  
    - `PingRequest`
    - `GetTaskRequest`
    - `CancelTaskRequest`
    - `SubscribeRequest`
    - `UnsubscribeRequest`
 
- Be explicit to client implementors on when they need to support `IncompleteResult` responses, and handle surfacing requests for more information in the UI.
- This is a breaking change, but we are already making a breaking change in MRTR. We do not have data on what MCP Servers due today in this regard, assumed to be low. 
- Hosts may not anticipate supporting gathering additional information on all responses, and this could lead to a worse user experience if they do not support it for all Requests & Responses.


### Schema Changes Required
Below highlights the ClientRequest schema changes required to support MRTR. This is the same pattern that Tasks support with `TaskAugmentedRequestParams`
```typescript
export interface RetryAugmentedRequestParams extends RequestParams {
  /* New field to carry the responses for the server's requests from the
   * IncompleteResult message.  For each key in the response's inputRequests
   * field, the same key must appear here with the associated response.
   */
  inputResponses?: InputResponses;
  /* Request state passed back to the server from the client.
   */
  requestState?: string;
}

// must then be added to RequestParams for specific ClientRequests like below.
export interface GetPromptRequestParams extends RetryAugmentedRequestParams {
  /**
   * The name of the prompt or prompt template.
   */
  name: string;
  /**
   * Arguments to use for templating the prompt.
   */
  arguments?: { [key: string]: string };
}
```

### Decision
Based on feedback from DSP & the Core Maintainers we will go with Option 2 and only support `IncompleteResult` responses for a subset of `ClientRequest`s. A table of which Requests we will support it for will be added to the SEP-2322.

The main reasons cited were
- Easier to add more broadly later.
- Matches how `Tasks` are currently supported.

