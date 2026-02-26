# Data-Layer Sessions for MCP

> **Status:** Early Draft  
> **Date:** 2026-02-23  
> **Track:** transport-wg/sessions  
> **Author(s):** Shaun Smith  

## Abstract

This proposal introduces a session concept within the MCP Data Layer, 
using a lightweight _cookie_ style mechanism. This allows applications to   

## Motivation

MCP Sessions are currently either implicit (STDIO), or constructed as a side effect of the transport connection (Streamable HTTP). 

It is assumed (but not required) that Host applications rather than the LLM are responsible for Session management.   

## Specification

### Capabilities

MCP Servers that support sessions advertise a `sessions` capability, indicating that they support `session/create`, `session/delete` and associated request and response semantics.

> For testing purposes, MCP Clients that support sessions use an `experimental/sessions` capability to simplify testing.


### session/create

Clients can begin a session with an MCP Server by calling `session/create`, optionally supplying a `title` for the session. The Server responds either by emitting a "cookie" style structure or returning an Error if session creation is not possible. 

The Error message **SHOULD** be descriptive of the reason for failure.

request

```
{title}
```

response

```
{session id}
//hint 
{expiry date} 
{opaque value}
```

The Client SHOULD associate retained cookies with the issuing Server .


The expiry date is a hint. Can be refreshed `servers/discovery`.

- The session ID SHOULD be globally unique and cryptographically secure (e.g., a securely generated UUID, a JWT, or a cryptographic hash).
- The session ID MUST only contain visible ASCII characters (ranging from 0x21 to 0x7E).
- The client MUST handle the session ID in a secure manner, see Session Hijacking mitigations for more details. (TODO -- update this as data layer/stdio mitigations are different)

The Session ID 

{label}

### session/delete

The Client SHOULD delete sessions where resources aren't required.

### request/*

_meta may contain 

### response/*

If the Session is not resumable


### Tool Annotation



## Rationale

### HTTP Cookies vs. Custom Implementation

To support non HTTP transports, an MCP Data Layer proposal has been selected.

### Use of in-band Tool Call ID

Session IDs are considered to be controlled by the Host application, rather than the Model - driving the design that identifiers are not revealed in tool calls etc.


## Backward Compatibility

### Existing MCP Servers

Some MCP Servers use SessionID for analytics (HF, GH). This usage is no longer . To associate tool calls

### Session Guidance

It is expected that 


