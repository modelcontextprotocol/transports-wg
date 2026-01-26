
# SEP-XXXX: Require Sampling and Elicitation Requests to Associate with Client Requests

## Status
**Proposed**

## Summary

This SEP clarifies that `sampling/createMessage` and `elicitation/create` requests **MUST** be sent only in association with an originating client request (e.g., during `tools/call`, `resources/read`, or `prompts/get` processing). Standalone server-initiated sampling or elicitation on independent communication streams are not supported and **SHOULD NOT** be implemented.

## Motivation

### Current Ambiguity

The current specification uses **SHOULD** language in the transport layer:

> "The server **MAY** send JSON-RPC _requests_ and _notifications_ before sending the JSON-RPC _response_. These messages **SHOULD** relate to the originating client _request_."

This creates ambiguity about whether servers can initiate sampling/elicitation requests:
- On standalone SSE streams (HTTP GET without prior client request)
- Independent of any client operation
- As "push" notifications to request user input or LLM completions

### Design Intent

The design intent of both sampling and elicitation has always been to operate **nested within** other MCP operations:

- **Sampling** enables servers to request LLM assistance while processing a tool call, resource request, or prompt
- **Elicitation** enables servers to gather additional user input needed to complete an operation
- Both are **reactive** capabilities, not proactive push mechanisms

The current specification already describes this pattern:

> "Sampling in MCP allows servers to implement agentic behaviors, by enabling LLM calls to occur _nested_ inside other MCP server features."

However, the normative requirements don't enforce this constraint.

### Simplification Benefits

Making this constraint explicit:

1. **Simplifies transport implementations** - Transports don't need to support arbitrary server-initiated request/response flows; they only need request-scoped bidirectional communication
2. **Clarifies user experience** - Users understand that sampling/elicitation happens *because* they initiated an action, not spontaneously
3. **Reduces security surface** - Prevents unexpected server-initiated prompts or LLM usage outside user-visible operations
4. **Aligns with practice** - Most (likely all) existing implementations already follow this pattern

## Specification Changes

### 1. Add Warning Blocks to Feature Documentation

**In `client/sampling.mdx` (after existing security warning):**

```markdown
<Warning>

**Request Association Requirement**

Servers **MUST** send `sampling/createMessage` requests only in association with an originating client request (e.g., during `tools/call`, `resources/read`, or `prompts/get` processing).

Standalone server-initiated sampling on independent communication streams (unrelated to any client request) is not supported and **MUST NOT** be implemented. Future transport implementations are not required to support this pattern.

</Warning>
```

**In `client/elicitation.mdx` (after existing security warning):**

```markdown
<Warning>

**Request Association Requirement**

Servers **MUST** send `elicitation/create` requests only in association with an originating client request (e.g., during `tools/call`, `resources/read`, or `prompts/get` processing).

Standalone server-initiated elicitation on independent communication streams (unrelated to any client request) is not supported and **MUST NOT** be implemented. Future transport implementations are not required to support this pattern.

</Warning>
```

### 2. Clarify Transport Layer Constraints

**In `basic/transports.mdx`, POST-initiated SSE streams (line ~121):**

```diff
- The server **MAY** send JSON-RPC _requests_ and _notifications_ before sending the
- JSON-RPC _response_. These messages **SHOULD** relate to the originating client
- _request_.
+ The server **MAY** send JSON-RPC _requests_ and _notifications_ before sending the
+ JSON-RPC _response_. These messages **SHOULD** relate to the originating client
+ _request_. In particular, `sampling/createMessage` and `elicitation/create` 
+ requests **MUST** only be sent in this context (associated with a client request).
```

**In `basic/transports.mdx`, GET-initiated standalone SSE streams (line ~147):**

```diff
- The server **MAY** send JSON-RPC _requests_ and _notifications_ on the stream.
- These messages **SHOULD** be unrelated to any concurrently-running JSON-RPC
- _request_ from the client.
+ The server **MAY** send JSON-RPC _requests_ and _notifications_ on the stream.
+ These messages **SHOULD** be unrelated to any concurrently-running JSON-RPC
+ _request_ from the client, **except** that `sampling/createMessage` and 
+ `elicitation/create` requests **MUST NOT** be sent on standalone streams.
```

## Backward Compatibility

### Impact Assessment

This change is expected to have **minimal to no impact** on existing implementations:

1. **Common usage patterns are preserved** - Sampling/elicitation within tool execution, resource reading, and prompt handling remain fully supported
2. **No known implementations affected** - Research conducted on GitHub has shown few implementations of this pattern in practice.
3. **stdio transport unaffected** - The stdio transport already operates in a request-scoped manner where all server messages naturally associate with client operations. 

**TODO** 

### What's Disallowed

The following pattern, which was never explicitly documented or recommended, is now explicitly prohibited:

```python
# ❌ PROHIBITED: Standalone server push
async def background_task():
    while True:
        await asyncio.sleep(60)
        # Try to initiate sampling without any client request context
        await session.create_message(...)  # NOT ALLOWED
```

### What Remains Supported

The canonical pattern remains fully supported:

```python
# ✅ SUPPORTED: Sampling during tool execution
@mcp.tool()
async def analyze_data(data: str, ctx: Context) -> str:
    # Request LLM analysis while processing the tool call
    result = await ctx.session.create_message(
        messages=[SamplingMessage(role="user", content=...)]
    )
    return result.content.text
```

## Implementation Guidance

### For Server Implementers

**No changes required** if your server:
- Only uses sampling/elicitation within tool handlers
- Only uses sampling/elicitation within resource/prompt handlers  
- Uses sampling/elicitation synchronously as part of processing a client request

**Changes required** if your server:
- Attempts to initiate sampling/elicitation on standalone HTTP GET streams
- Attempts to send sampling/elicitation requests independent of client operations
- Has background tasks that try to invoke sampling/elicitation

Alternative designs will need to be implemented for the "Changes Required" case.

### For Client Implementers

**No changes required** - Clients should already handle sampling/elicitation requests in the context of their own outbound requests. Potential to simplify implementations if out-of-band supported.

### For Transport Implementers

Future transport implementations can rely on the guarantee that:
- Sampling/elicitation requests only occur within the scope of a client-initiated request
- Transports don't need to support arbitrary server-initiated request/response flows on standalone channels
- Request correlation and lifecycle management is simplified

## Timeline

(This SEP intends to serve as a public notice of the change prior to future protocol versions that will not be compatible with this usage)

## Alternatives Considered

### 1. Soft Deprecation
Use **SHOULD NOT** language to discourage but not prohibit the pattern.

**Rejected because:** The behavior was never intentionally supported, and leaving it ambiguous prevents transport simplification.

### 2. Keep Current Ambiguity
Leave the existing **SHOULD** language unchanged.

**Rejected because:** This blocks future transport implementations and leaves implementers uncertain about whether the pattern is supported.

### 3. Create a Capability Flag
Add a `sampling.standalone` or similar capability for servers that want this behavior.

**Rejected because:** This adds complexity for a use case with no known demand, and contradicts the "nested" design principle.

## References

- Current sampling documentation: `/specification/draft/client/sampling.mdx`
- Current elicitation documentation: `/specification/draft/client/elicitation.mdx`
- Transport specification: `/specification/draft/basic/transports.mdx`
- User interaction model discussion in client concepts documentation
