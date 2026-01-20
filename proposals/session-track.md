**Sessions Track: Brief**

**Goal** To decouple session state from the underlying transport connection, allowing for robust, long-lived application state that survives connection drops and scales horizontally across stateless servers.

**Core Principle: Adapted Cookie Semantics**

* **RFC 6265 as a Foundation:** We will use **RFC 6265 (HTTP Cookies)** as a functional starting point to determine necessary adaptations for MCP.  
* **Payload Integration:** Session data will primarily be included as a dedicated field within the JSON-RPC payload. We will look to **SEP-1655** and **SEP-1685** for inspiration on structuring this metadata.

**Key Requirements**

* **Routing Compatibility & Size Constraints:** To allow load balancers to route requests based on session affinity, we may need to copy the session identifier/token into an HTTP header. This introduces strict **size constraints**; the session token must remain small enough to fit within standard header limits (typically \~4KB), prohibiting large state blobs from being stored directly in the token.  
* **Security & Integrity:** Servers utilizing cookies must encrypt or sign the data to prevent client-side tampering. We will evaluate including a standard mechanism for signing/encryption directly in the spec.  
* **Expert Review:** We will consult security experts to review the design for known vulnerabilities common in standard cookie implementations.

**Key Design Decision: Lifecycle Management**

* **Implicit vs. Explicit:** We must decide between allowing lazy initialization (Implicit) versus requiring a formal setup handshake (Explicit).  
  * *Consideration:* The need to **copy or fork** session data (e.g., branching an agent's state) strongly suggests preferring an **Explicit** mechanism (e.g., `session/create`, `session/fork`) to ensure these operations are predictable and race-free.

---

## Prior Art

This section is for summarising the relevant parts of how other Agent systems and specifications handle Sessions.

### Agent Client Protocol (Specification)

Sessions are created by the Client (Host) and resumable, with the option of the Agent replaying messages to rehydrate Client state. There is no "close" operation. 

Sessions are well specified with a unique session identifier, multiplexing and sequences of Prompt Turns between Client and Agent. Sessions in ACP are a user level abstraction. ACP is currently STDIO only with an HTTP transport "in progress". 

#### In-flight Proposals

##### Session Listing

https://agentclientprotocol.com/rfds/session-list

##### Session Forking

https://agentclientprotocol.com/rfds/session-fork

##### MCP/ACP transport (MCP over ACP)

https://agentclientprotocol.com/rfds/mcp-over-acp

Text courtesy of https://github.com/secretiveshell

> your IDE can provide tools to the agent, for example you might install a zed extension for prettier, and the prettier zed extension can expose MCP tools to the agent
> 
> previously you would have
> 1) zed spawns ACP server (fast agent) as a sub process
> 2) ACP server spawns MCP server as subprocess
> 3) MCP server talks to zed via some other side channel
> this is basically a circular dependency chain
> 
> with this proposal you can have:
> 1) zed spawn ACP server (fast agent)
> 2) zed embed the MCP server into the same ACP client process
> 3) fast agent connects to the MCP server over the existing ACP transport

> which means you skip the whole extra MCP server process
> https://agentclientprotocol.com/rfds/mcp-over-acp#routing-by-id
> in fact it even lets zed handle multiple MCP servers via multiplexing, so you could have zed IDE install MCP servers similar to the vscode extension store, and then have those MCP servers configured in fast agent automatically by just connecting to all the MCP servers exposed by the MCP over ACP bridge
> its literally just a wrapper to send mcp frames over an ACP connection


### Claude Code


### Intra-Inference

#### Responses / Open Resonses

[Protocol](https://www.openresponses.org/) uses "Response Chaining" and state machines for lifecycle management. `previous_response_id`, `next_response_id` and `sequence_id`  describe sequencing with `conversation_id` allowing grouping and potential persistence.

Protocol uses "Response Chaining" and state machines for lifecycle management.
`previous_response_id` and `next_response_id` describe sequencing, with conversation (object containing id) allowing grouping. 

Client may set a `store` flag to persist state, reflected by the Server. No explicit guarantees apply.

#### Anthropic

#### Gemini

### `fast-agent`

Sub-agents only retain state within the tool loop.

Agents hosted as MCP Servers can have an instance type of `connection`, `request` or `shared`.

### Tool Generates association identifier.

A Tool Call returns a unique identifier, and requests that the identifier be returned in subsequent tool calls. 

This pattern is potentially unreliable due to LLM generation being potentially unreliable but works in practice. 

Promoting this technique to a determenistic side-channel is a possibility.

### Use Cases

#### Sandbox VM

An LLM creates a temporary sandbox compute instance, and over the course of several generations calls tools to manipulate the state of the sandbox.

In this scenario, the sandbox would normally be relatively short-lived with either a termination call or timeout quiescing or destroying it.

The sandbox will usually have an identifier that needs associating to the conversation (see `Tool Generates association identifier` or through a 1:1 connection mapping). 

Each inference turn is independent of previous turns: the sandbox state is inferred from the message history. Reassociation with the sandbox needs to be either within message content or associated metadata.

Replaying messages to reproduce state in this case should be a Client responsibility (rather than a Server responsibility). 




