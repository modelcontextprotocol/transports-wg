# MRTR And Tasks Message Structure Proposal

## Overview
This document provides an overview of how the [Multi-Round-Trip Request Proposal](https://github.com/modelcontextprotocol/transports-wg/pull/7/changes#diff-c42674696a4c91ccc0d2daf8425dbcb52201ec1ef75921ae1e4865b5b911018d) (MRTR) fits with the Tasks by walking thorugh an example with Elicitations.

It also raises open questions and proposed solutions for discussion on what the return type should be for Tool Requests that require Elicitation or Sampling to complete.

## Tasks Background
The [Tasks](https://modelcontextprotocol.io/specification/draft/basic/utilities/tasks) Utilities allows requests to be augmented with a Promise like mechanism. `Tasks` have a Status Lifecycle including `Working`, `Input Requried`, `Completed`, `Failed`, and `Cancelled`.

The `Input Required` status allows a Tool or Capability to indicate that additional input is required from the user to complete the task. This is where an Elicitation or Sampling request can be made by the server.

When the client encounters an `Input Required` status it SHOULD call `tasks/result`. This allows the server to then return an `Elicitation` or `Sampling` request to the client. This fits well with the proposal to eliminate unsolicited `Elicitation` and `Sampling` requests from the server to the client.

### Example Flow with Elicitations
The below example uses an Echo Tool with an optional input parameter, when missing Elicitation is used to request the input from the user before completing the request. 

1. <b>Client Request</b> to invoke EchoTool.
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "echo",
        "task": {
            "ttl": 60000
        }
    }
}
```

2. <b>Server Response</b> with a `Task`
```json
{
    "id":  1,
    "jsonrpc":  "2.0",
    "result": {
        "task": {
            "taskId":"echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5",
            "status":  "Working",
            "statusMessage": "Task has been created for echo tool invocation.",
            "createdAt":  "2026-01-27T03:32:48.3148180Z",
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
    "params": {
        "taskId": "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5"
    }
}
``` 

4. <b>Server Response</b> with Task status `InputRequired`
```json
{
    "id":  2,
    "jsonrpc":  "2.0",
    "result":  
    {
        "taskId":  "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5",
        "status":  "input_require",
        "statusMessage":  "Input Required to Proceed call tasks/result",
        "createdAt":  "2026-01-27T03:38:07.7534643Z",
        "ttl":  60000,
        "pollInterval":  100
    },
}
```

5. <b>Client Request</b> sends message `tasks/result` to discover what input is required to proceed.
```json
{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tasks/result",
    "params": {
        "taskId": "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5"
    }
}
```

6. <b>Server Response</b> returns `elicitation/create` to request additional input
```json
{
    "id":  3,
    "jsonrpc":  "2.0",
    "method":  "elicitation/create",
    "params":  {
        "mode":  "form",
        "message":  "Please provide the input string to echo back",
        "requestedSchema":  
        {
            "type":  "object",
            "properties":  
            {
                "input": {"type":  "string"}
            },
            "required": ["input"]
        }
    },
    "_meta":  
    {
        "io.modelcontextprotocol/related-task":  
        {
            "taskId":  "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5"
        }
    } 
}
```

7. <b>Client Request</b> presents the Elicitation to the user and collects the input, then sends message to the server.
```json
{
    "jsonrpc": "2.0",
    "id": 4,
    "result": {
        "action": "accept",
            "content": {
            "input": "Hello World!"
        },
        "_meta": {
            "io.modelcontextprotocol/related-task": {
                "taskId": "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5"
            }
        }
    }
}
```

8. <b>Server Response</b> .Currently there is no required response to this message, but the server can now proceed to complete the `Task` using the provided input, and the `Task` status changes to `Working`

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
    "id":  5,
    "jsonrpc":  "2.0",
    "result":  
    {
        "taskId":  "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5",
        "status":  "Completed",
        "statusMessage":  "Task has been completed successfully, call get/result",
        "createdAt":  "2026-01-27T03:38:07.7534643Z",
        "ttl":  60000,
        "pollInterval":  100
    },
}
```

11. <b>Client Request</b> calls `tasks/result` to get the final result of the `Task` from the server.
Client Message
```json
{
    "id":  6,
    "jsonrpc":  "2.0",
    "method":  "tasks/result",
    "params":  
    {
        "taskId":  "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5"
    },
}
```
12. <b>Server Response</b> with the final result of the `Task`
```json
{
    "id":  6,
    "jsonrpc":  "2.0",
    "result":  
    {
        "isError":  false,
        "content":  
        [{
            "type":  "text",
            "text":  "Echo: Hello World!"
        }],
        "_meta":  
        {
            "io.modelcontextprotocol/related-task":  
            {
                "taskId":  "echo_dc792e24-01b5-4c0a-abcb-0559848ca3c5"
            }
        }
    },
}
```

## Discussion Points
Both Tool Calls and Task Results should follow the same pattern when requesting additional input via Elicitation or Sampling. Having different mechanisms and messaging pattern leads to complexity in implementation and confusion.

In both implementations a request for more information is treated as a special result. This can be viewed as a recoverable error case. In Tasks the request for more input is retrieved via the `tasks/result` message, while in Tool Calls it is returned directly as the result of the `tools/call` message.

Given the below options for response types should be considered.

### Option One - MRTR & Tasks return existing Elicitaiton or Sampling Messagees.
Today this is what Tasks does. The response to a `tasks/result` call when additional input is required is to return an `elicitation/create` or `sampling/createMessage` message.

<b>Pros:</b> Smaller changes to existing implementations.

<b>Cons:</b> Message structure does not align with the `result` message structure used by Completed Results and Error Messages. 

### Option Two - MRTR & Tasks return a Result Wrapper around Elicitation & Sampling
This would involve defining a new [`ToolResult`](https://modelcontextprotocol.io/specification/draft/server/tools#tool-result) Content type that wraps an Elicitation or Sampling request. 

This could look like, and would replace the response in step 6 above:
```json
{
    "id":  3,
    "jsonrpc":  "2.0",
    "result":{
        "content": [
            {  
                "type": "elicitation",
                "mode":  "form",
                "message":  "Please provide the input string to echo back",
                "requestedSchema":  
                {
                    "type":  "object",
                    "properties":  
                    {
                        "input": {"type":  "string"}
                    },
                    "required": ["input"]
                }
            }],
        "isError": false,
    }
}
```

Pros: 
- Consistent message structure for all Result types from Tasks & Tools which simplifies the SDK implementations. 
- Consistent handling of isError or other future result metadata fields.
- With Tasks this structure would allow for partial results & additional input to requested on the same get/results 
- Supports multiple Elicitation & Sampling requests at the same time.  

Cons: Larger change to existing implementations. 
- Requires deprecating the existing `Elicitation` and `Sampling` messages returned by Tasks since out of band messages are no longer needed. 
- Need to `ToolResult` Content schema as a `Utilities` `Results` schema to indicate it's not just for `Tools` since they are already being used by `Tasks` and will now be extended further.
