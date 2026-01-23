# MCP Streamless Round-Trip Proposal Sketch

Author: [Mark Roth](mailto:roth@google.com)  
Last modified: 2025-12-02

# Background

For context, see [MCP Multi Round-Trip Requests Problem Statement](https://docs.google.com/document/d/1trA6-b8nrhE-yZQ2BPNltCSlxhkAmVQsG9a6pPzH6Fs/edit?usp=sharing).

This document describes an approach to that problem that does not require the use of SSE streams.  This makes it possible to use server-initiated requests like elicitations without needing to support SSE streams.

# Proposal

There is a common MCP use case that looks like this:

1. Client issues a tool call to an MCP server.  
2. In order to respond to that request, the server needs more info from the client, so it sends back a request for more info (e.g., a sampling or elicitation request).  
3. The client responds to the server's request for more info.  
4. The server can now respond to the original request from the client.

Today in MCP, this is handled as follows:

1. Client sends an HTTP request.  
2. Server responds to the HTTP request from step 1 by opening an SSE stream.  On that SSE stream, it sends the request for more info back to the client.  
3. Client sends a separate, independent HTTP request with the response to the server's request from step 2\.  
4. Server sends the response to the client's original request from step 1 on the SSE stream that it opened in step 2\.

This document proposes the following new approach for this use-case:

1. Client sends a CallToolRequest.  
2. Server sends back a single response (**not** an SSE stream) indicating that the request is incomplete and that an elicitation request is required.  
3. Client sends a new CallToolRequest, completely independent of the original one, which includes the response to the elicitation request from step 2\.  
4. Server sends back a CallToolResponse.

(Note that in concert with a cookie-ish mechanism similar to [SEP-1685](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1685), there could even be multiple round-trips (i.e., repeat steps 2 and 3 as many times as we want) before the tool call is finally complete.)

Steps 1 and 4 here are already supported today, but we need new mechanisms to handle steps 2 and 3\.

In the TS schema, this might look something like the following (not quite completely right, but provides the general idea):

```ts
// Similar to existing JSONRPCResultResponse.
// Used in cases where the server needs the results of one or more requests
// of its own before it can complete the client's request.
export interface JSONRPCIncompleteResultResponse {
  jsonrpc: typeof JSONRPC_VERSION;
  id: RequestId;
  // Requests issued by the server that must be complete before the
  // client can retry.
  dependent_requests: { [key: string]: ServerRequest };
}

// Existing type, modified to include JSONRPCIncompleteResultResponse.
export type JSONRPCResponse = JSONRPCResultResponse | JSONRPCErrorResponse | JSONRPCIncompleteResultResponse;

// Existing type, modified to encode responses to dependent requests.
export interface JSONRPCRequest extends Request {
  jsonrpc: typeof JSONRPC_VERSION;
  id: RequestId;
  // New field to carry the responses for the server's requests from the
  // JSONRPCIncompleteResultResponse message.  For each key in the
  // response's dependent_requests field, the same key must appear here
  // with the associated response.
  dependent_responses: { [key: string]: ClientResult };
}
```

Here's a concrete (albeit contrived) example of how this would look on the wire:

First, the client sends the initial call tool request:

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

The server responds with an incomplete response, indicating that the client needs to respond to an elicitation request **and** a sampling request in order for the tool call to complete:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "dependent_requests": {
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
    "capital_of_france" : {      "method": "sampling/createMessage",
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
}
```

The client then retries the original tool call, this time including the responses to the dependent server requests:

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
  "dependent_responses": {
    // Elicitation response.
    "github_login": {
      "result": {
        "action": "accept",
        "content": {
          "name": "octocat"
        }
      }
    },    // Sampling response.
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
}
```

Finally, the server completes the tool call:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
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

# Acknowledgement

The general approach of this proposal was shamelessly stolen from [SEP-1597](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1597).