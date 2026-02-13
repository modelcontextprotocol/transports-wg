# SEP-XXXX: Multi Round-Trip Requests

- **Status**: Draft
- **Type**: Standards Track
- **Created**: 2026-02-03
- **Author(s)**: Mark D. Roth (@markdroth), Caitie McCaffrey (@CaitieM20),
  Gabriel Zimmerman (@gjz22)
- **Sponsor**: None
- **PR**: https://github.com/modelcontextprotocol/specification/pull/{NUMBER}

## Abstract

This proposal specifies a simple way to handle server-initiated requests
in the context of a client-initiated request (e.g., an elicitation
request in the context of a tool call) without requiring a shared
storage layer shared across server instances or statefulness in
load balancing, which will significantly reduce the cost of operating
MCP servers at scale in the common case.  It also reduces the HTTP
transport's dependence on SSE streams, which cause problems in a lot of
environments that cannot support long-lived connections.

## Motivation

Note: This SEP is intended to provide a generic mechanism for handling
any server-initiated request in the context of any client-initiated
request.  However, for clarity, throughout this document, we will use
the example of an elicitation request in the context of a tool call.

We start with the observation that there are two types of MCP tools:
1. **Ephemeral**: No state is accumulated on the server side.
   - If server needs more info to process the tool call, it can start from
     scratch when it gets that additional info.
   - Examples: weather app, accessing email
2. **Persistent**: State is accumulated on the server side.
   - Server may generate a large amount of state before requesting more
     info from the client, and it may need to pick up that state to
     continue processing after it receives the info from the client.
   - Server may need to continue processing in the background while
     waiting for more info from the client, in which case server-side
     state is needed to track that ongoing processing.
   - Examples: accessing an agent, spinning up a VM and needing user
     interaction to manipulate the VM

The vast majority of MCP tools will be ephemeral, and it is extremely
common for tools to be deployed in a horizontally scaled, load balanced
service, so we need to optimize for this case.

Today, if a tool needs to send an elicitation request in order to make
progress, the workflow works like this:

1. Client sends tool call request.  For this example, let's assume that
   the load balancers happen to send this request to server instance A.
2. Server A opens an SSE stream and sends the elicitation response on that
   stream.
3. Client sends the elicitation response as a separate request, for which
   the load balancers will choose a server instance completely
   independently of the one they chose in step 1.  In this example,
   let's assume that the load balancers happen to send this request to
   server instance B.
4. Server A must somehow discover the elicitation result delivered to
   server B.
5. Server A then sends the tool call result on the SSE stream opened in
   step 2.

The difficult part here is step 4, which requires some sort of
statefulness on the server side.  The main way to solve this problem
today is to have a storage layer shared across all server instances, so
that multiple server instances can match up the elicitation response
on one server instance with the original ongoing tool call on a
different server instance.  

There are two main approaches that can be used to solve this problem today:
- **Shared Storage Layer Across Server Instances**: This allows multiple
  server instances to match up the elicitation response on one server
  instance with the original ongoing tool call on a different server
  instance.  This approach has a number of drawbacks:
  - It is extremely expensive, especially for ephemeral tools that may not
    already have a common storage layer (e.g., a weather tool).
  - It requires special code to figure out when the shared state can be
    cleaned up (e.g., did the client go away permanently, or is there
    just a temporary network problem?).
  - It requires special behavior in the tool implementation to integrate
    with the shared storage layer.  The MCP SDKs today do not have any
    special hooks for this sort of storage layer integration, which
    means that it's very hard to write in-line code via the SDKs.
- **Statefulness in Load Balancing**: With the use of cookies, it is
  possible for the load balancing layer to ensure that the elicitation
  request in step 3 is delivered to the same server instance that the
  original request was delivered to in step 1.  This approach, while
  often cheaper than a shared storage layer, has the following
  drawbacks:
  - It requires special configuration and behavior in the load
    balancers, which is often difficult to manage.
  - It breaks normal load balancing models, resulting in uneven load
    distribution, thus increasing the cost of running the service.
  - It requires special behavior in clients to propagate the cookies
    used for statefulness.
  - It requires the tool implementation to match up the elicitation
    request with the ongoing tool call.  (The MCP SDKs have some code to
    handle this, but it's still a very strange pattern in the HTTP
    world.)
  - It is not fault tolerant.  If the server instance goes down, all
    state is lost, and the tool call would need to start over from
    scratch.  (This doesn't necessarily matter for ephemeral tools,
    but it is an issue for persistent tools.)

Also, both of these approaches rely on the use of an SSE stream, which
causes problems in environments that cannot support long-lived
connections.

The goal of this SEP is to propose a simpler way to handle the pattern
of server-initiated requests within the context of a client-initiated
request.  Specifically, we need to make it cheaper to support this pattern
in the common case of an ephemeral tool in a horizontally scaled, load
balanced deployment.  This means that we need a solution that does not
depend on an SSE stream and does not require either a shared storage
layer or stateful load balancing, which in turn means that we need to
avoid dependencies between requests: servers must be able to process
each individual request using no information other than what is present
in that individual request.

Note that while the goal here is to optimize the common case of ephemeral
tools, we do want to continue to support persistent tools, which generally
already require a shared storage layer.

## Specification

This SEP proposes a new mechanism for handling server requests in the
context of a client request.  This new mechanism will have a slightly
different workflow for ephemeral tools and persistent tools, the latter
of which will leverage Tasks.  However, both workflows will use the same
data structures.

First, we introduce the notion of "input requests", which represents
a set of one or more server-initiated request to be sent to the client,
and "input responses", which represents the client's responses to
those requests.  The individual requests and responses are stored in a
map with string keys:

```typescript
export interface InputRequests { [key: string]: ServerRequest; }

export interface InputResponses { [key: string]: ClientResult; }
```

TODO: The above schema definitions are not quite right, because
ServerRequest and ServerResult include the JSON-RPC request id field,
which is not necessary here.  Figure out what schema refactoring is
needed to get the types without that field.

The keys are assigned by the server when issuing the requests.  The client
will send the response for each request using the corresponding key.
For example, a server might send the following input requests:

```json5
"input_requests": {
  // Elicitation request.
  "github_login": {
    "method": "elicitation/create",
    "params": {
      "mode": "form",
      "message": "Please provide your GitHub username",
      "requestedSchema": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string"
          }
        },
        "required": ["name"]
      }
    }
  },
  // Sampling request.
  "capital_of_france" : {
    "method": "sampling/createMessage",
    "params": {
      "messages": [
        {
          "role": "user",
          "content": {
            "type": "text",
            "text": "What is the capital of France?"
          }
        }
      ],
      "modelPreferences": {
        "hints": [
          {
            "name": "claude-3-sonnet"
          }
        ],
        "intelligencePriority": 0.8,
        "speedPriority": 0.5
      },
      "systemPrompt": "You are a helpful assistant.",
      "maxTokens": 100
    }
  }
}
```

The client would then send the responses in the following form:

```json5
"input_responses": {
  // Elicitation response.
  "github_login": {
    "result": {
      "action": "accept",
      "content": {
        "name": "octocat"
      }
    }
  },
  // Sampling response.
  "capital_of_france": {
    "result": {
      "role": "assistant",
      "content": {
        "type": "text",
        "text": "The capital of France is Paris."
      },
      "model": "claude-3-sonnet-20240307",
      "stopReason": "endTurn"
    }
  }
}
```

These types will be used in two different workflows, one for ephemeral
tools and another for persistent tools.

### Ephemeral Tool Workflow

For ephemeral tools, we will adopt the following workflow:

1. Client sends tool call request.
2. Server sends back a single response (**not** an SSE stream)
   indicating that the request is incomplete.  The response may include
   input requests that the client must complete.  It may also include
   some request state that the client must return back to the server.
   This terminates the original request.
3. Client sends a new tool call request, completely independent of the
   original one.  This new tool call includes responses to the input
   requests from step 2.  It also includes the request state specified by
   the server in step 2.
4. Server sends back a CallToolResponse.

Note that the requests in steps 1 and 3 are completely independent: the
server that processes the request in step 3 does not need any
information that is not directly present in the request.

```typescript
// Similar to existing JSONRPCResultResponse.
// Used in cases where the server needs the results of one or more requests
// of its own before it can complete the client's request.
export interface JSONRPCIncompleteResultResponse {
  jsonrpc: typeof JSONRPC_VERSION;
  id: RequestId;
  // Requests issued by the server that must be complete before the
  // client can retry.
  input_requests?: InputRequests;
  // Request state to be passed back to the server when the client retries.
  // Note: The client must treat this as an opaque blob; it must not
  // interpret it in any way.
  request_state?: string;
}

// Existing type, modified to include JSONRPCIncompleteResultResponse.
export type JSONRPCResponse = JSONRPCResultResponse | JSONRPCErrorResponse |
                              JSONRPCIncompleteResultResponse;

// Existing type, modified to encode responses to input requests.
export interface JSONRPCRequest extends Request {
  jsonrpc: typeof JSONRPC_VERSION;
  id: RequestId;
  // New field to carry the responses for the server's requests from the
  // JSONRPCIncompleteResultResponse message.  For each key in the
  // response's input_requests field, the same key must appear here
  // with the associated response.
  input_responses?: InputResponses;
  // Request state passed back to the server from the client.
  request_state?: string;
}
```

Note that this workflow eliminates the need for the
`URLElicitationRequiredError` error code.  That code will be removed
from the spec.

#### Example Flow for Ephemeral Tools

Note: This is a contrived example, just to illustrate the flow.

1. The client sends the initial call tool request:
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "get_weather",
    "arguments": {
      "location": "New York"
    }
  }
}
```

2. The server responds with an incomplete response, indicating that the
   client needs to respond to an elicitation request in order for the tool
   call to complete, and including request state to be passed back:
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "input_requests": {
    "github_login": {
      "method": "elicitation/create",
      "params": {
        "mode": "form",
        "message": "Please provide your GitHub username",
        "requestedSchema": {
          "type": "object",
          "properties": {
            "name": {
              "type": "string"
            }
          },
          "required": ["name"]
        }
      }
    }
  },
  "request_state": "foo"
}
```

3. The client then retries the original tool call, this time including the
   responses to the input server request and the request state:
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "get_weather",
    "arguments": {
      "location": "New York"
    }
  }
  "input_responses": {
    "github_login": {
      "result": {
        "action": "accept",
        "content": {
          "name": "octocat"
        }
      }
    }
  },
  "request_state": "foo"
}
```

4. Finally, the server completes the tool call:
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Current weather in New York:\nTemperature: 72°F\nConditions: Partly cloudy"
      }
    ],
    "isError": false
  }
}
```

#### Use Cases for Request State

The "request_state" mechanism provides a mechanism for doing multiple
round trips on the same logical request.

For example, let's say that you are doing a rolling upgrade of your
horizontally scaled server instances to deploy a new version of a tool
implementation.  The old version had two input requests with keys
"github_login" and "google_login".  However, in the new version of
the tool implementation, it still uses the "github_login" input
request, but it replaces the "google_login" input request with a new
"microsoft_login" input request.

If the first request goes to an old version of the server but the second
attempt (that includes the input responses) goes to a new version
of the server, then the server will see the result for "github_login",
which it needs, but it won't see the result for "microsoft_login".
(It will also see the result for "google_login", but it no longer needs
that, so it doesn't matter.)  At this point, the server needs to send a
new input request for "microsoft_login", but it also doesn't want
to lose the answer that it's already gotten for "github_login", so it
would use the kind of state proposed in 1685 to retain that information
without having to store the state on the server side.

The workflow here would look like this:

1. Client sends tool call request that hits a server instance running
   the old version.
2. Server sends back an incomplete response indicating the input
   requests for "github_login" and "google_login".
3. Client sends a new tool call request that includes the responses to
   the input requests for "github_login" and "google_login".  This
   time it hits a server instance running the new version.
4. Server sends back another incomplete response indicating the
   input request for "microsoft_login", which the client has not
   already provided.  However, the response also includes request state
   containing the already-provided "github_login" response, so that the
   client does not need to prompt the user for the same information a
   second time.
5. Client sends a third tool call request that includes the response to
   the "microsoft_login" input request as well as echoing back the
   request state provided by the server in step 4.
6. Server now sees the "github_login" info in the request state and the
   "microsoft_login" state in the input responses, so the request
   now contains everything the server needs to perform the tool call and
   send back a complete response.

Note that the data stored in request state does not actually need to
contain information related to input requests; it may instead be
data generated by the server in response to the original request, which
the server may want to reuse when the request is retried.  This can be
used even without any input requests as a mechanism for shedding load.
If a server instance is mid-computation but becomes overloaded, it may
return an incomplete response with the current state of its computation
in "request_state" (note: this incomplete response would not necessarily
have any input requests).  The client will then retry the original
request with that request state attached, which will allow a different
server instance to pick up the computation from where the original
server instance left off.

### Persistent Tool Workflow

The persistent tool workflow will leverage Tasks. [`Tasks`](https://modelcontextprotocol.io/specification/draft/basic/utilities/tasks) already provide a mechanism to indicate that more information is needed to complete the request. The `input_required` Task Status allows the server to indicate that additional information is needed to complete processing the task. 

The workflow for `Tasks` is as follows:

1. Server sets Task Status to `input_required` 
2. Client retrieves the Task Status by calling `tasks/get` and sees that more information is needed.
3. Client calls `task/result` 
4. Server returns the `InputRequets` object. The Server can pause processing the request at this point.
5. Client sends `InputResponses` object to server along with `Task` metadata field.
6. Server resumes processing sets TaskStatus back to `Working`.

Since `Tasks` are likely longer running, have state associated with them, and are likely more costly to compute, the request for more information does not end the originally requested operation (e.g., the tool call). Instead, the server can resume processing once the necessary information is provided.

The above workflow and below example do not leverage any of the optional Task Status Notifications although this SEP does not preclude their use.

#### Example Flow for Persistent Tools
The below example walks through the entire Task Message flow for a Echo Tool which can request additional information from the client via Elicitation.

1. <b>Client Request</b> to invoke EchoTool.
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params":{
        "name": "echo",
        "task":{
            "ttl": 60000
        }
    }
}
```

2. <b>Server Response</b> with a `Task`
```json
{
    "id": 1,
    "jsonrpc": "2.0",
    "result":{
        "task":{
            "taskId": "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5",
            "status": "Working",
            "statusMessage": "Task has been created for echo tool invocation.",
            "createdAt": "2026-01-27T03:32:48.3148180Z",
            "ttl": 60000,
            "pollInterval": 100
        }
    }
}
```

3. <b>Client Request</b> periodically checks the status of the `Task` using `tasks/get`.
```json
{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tasks/get",
    "params":{
        "taskId": "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5"
    }
}
``` 

4. <b>Server Response</b> with Task status `input_required`
```json
{
    "id": 2,
    "jsonrpc": "2.0",
    "result":{
      "taskId": "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5",
      "status": "input_required",
      "statusMessage": "Input Required to Proceed call tasks/result",
      "createdAt": "2026-01-27T03:38:07.7534643Z",
      "ttl": 60000,
      "pollInterval": 100
    },
}
```

5. <b>Client Request</b> sends message `tasks/result` to discover what input is required to proceed.
```json
{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tasks/result",
    "params":{
      "taskId": "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5"
    }
}
```

6. <b>Server Response</b> returns `input_requests` to request additional input
```json
{
    "id": 3,
    "jsonrpc": "2.0",
    "input_requests":{
      "echo_input":{
        "method": "elicitation/create",
        "params":{
          "mode": "form",
          "message": "Please provide the input string to echo back",
          "requestedSchema":{
            "type": "object",
            "properties":{
              "input": { "type": "string"}
            },
            "required": ["input"]
          }
        }
      }
    },
    "_meta":{
      "io.modelcontextprotocol/related-task":{
        "taskId": "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5"
      }
    } 
}
```

7. <b>Client Request</b> presents the Elicitation to the user and collects the input, then sends message to the server.
```json
{
    "jsonrpc": "2.0",
    "id": 4,
    "input_responses":{
      "echo_input":{
        "result":{
          "action": "accept",
          "content":{
            "input": "Hello World!"
          }
        }
      }
    }, 
    "_meta":{
      "io.modelcontextprotocol/related-task":{
        "taskId": "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5"
      }
    }
}
```

8. <b>Server Response</b> Currently there is no required response to this message, but the server can now proceed to complete the `Task` using the provided input, and the `Task` status changes to `Working`

9. <b>Client Request</b> continues to poll the input status using `tasks/get` until server responds with Task Status of `Completed`
Client Request
```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tasks/get",
  "params": {
      "taskId": "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5"
  }
}
```
10. <b>Server Response</b> with Task status `Completed`
```json
{
  "id": 5,
  "jsonrpc": "2.0",
  "result":{
    "taskId": "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5",
    "status": "Completed",
    "statusMessage": "Task has been completed successfully, call get/result",
    "createdAt": "2026-01-27T03:38:07.7534643Z",
    "ttl": 60000,
    "pollInterval": 100
  },
}
```

11. <b>Client Request</b> calls `tasks/result` to get the final result of the `Task` from the server.
Client Message
```json
{
  "id": 6,
  "jsonrpc": "2.0",
  "method": "tasks/result",
  "params":{
    "taskId":  "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5"
  },
}
```
12. <b>Server Response</b> with the final result of the `Task`
```json
{
  "id": 6,
  "jsonrpc": "2.0",
  "result":{
    "isError": false,
    "content":[{
        "type": "text",
        "text": "Echo: Hello World!"
    }],
    "_meta":{
      "io.modelcontextprotocol/related-task":{
        "taskId": "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5"
      }
    }
  },
}
```


### Interactions Between Ephemeral and Persistent Workflows

If a tool implementation needs the client to respond to a set of
input requests before it can even start processing but then later
needs to do persistent processing, it can start using the ephemeral
workflow and then switch to the persistent workflow by creating a task
at that point.  This avoids the need for the server to store state until
it actually has the information needed to start processing the request.
This workflow would look like this:

1. Client sends tool call request with task metadata.
2. Server sends back `input_requests` response indicating that more information is needed to process the request. This terminates the original request.
3. Client sends a new tool call request, completely independent of the
   original one, which includes the `input_responses` object along with the task metadata.
4. Server sends back a task ID, indicating that it will be processing the
   request in the background.  All subsequent interaction will be done
   via the Tasks API.

Note that the opposite is not true: Once a tool implementation returns a
task, it has committed to storing state on the server side for the
duration of the task, and there is no way to transition back to the
ephemeral model.  All subsequent interactions must be performed via the
Tasks API.

## Rationale

We considered a bidirectional stream approach to replace SSE streams.
However, that approach would have made the wire protocol more
complicated (e.g., it would have required HTTP/2 or HTTP/3).  Also, it
would not have eliminated problems for environments that cannot support
long-lived connections, nor would it have addressed fault tolerance
issues.

There was discussion about whether the input requests should be a
map or just a single object, possibly leveraging some field inside of
the requests (e.g., the elicitation ID) to differentiate between them.
We decided that the map makes sense, since it structurally guarantees
the uniqueness of keys, which will avoid the need for explicit checks in
SDKs and applications to avoid conflicts.

## Backward Compatibility

Today there may be ephemeral tools written in an in-line but async
fashion to wait for the elicitation response before sending the tool
call response on the original SSE stream:

```python
def my_tool():
  do_mutation1()
  await elicit_more_info()
  do_mutation2()
```

For new tools, we want to instead suggest that they be written like
this:

```python
def my_tool(request):
  github_login = request.input_responses().get('github_login', None)
  if github_login is None:
    return IncompleteResponse({'github_login': elicitation_request})
  result = GetResult(github_login)
  return Result(result)
```

However, we need to consider how to avoid breaking things for existing
tools that are written the old way.  Ideally, we will be able to modify
the SDKs to support the old tool implementations via some sort of
backward compatibility layer.

## Security Implications

This proposal is not expected to introduce any security implications.

## Reference Implementation

TBD

### Acknowledgments

Thanks to Luca Chang (@LucaButBoring) for his valuable input on how to
integrate input requests into Tasks.
