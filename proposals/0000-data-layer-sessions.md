# Data-Layer Sessions for MCP

> **Status:** Early Draft  
> **Date:** 2026-02-23  
> **Track:** transport-wg/sessions  
> **Author(s):** Shaun Smith  

## Abstract

## Motivation


## Specification

### Capabilities

Clients and Servers that support Sessions expose the `sessions` capability.


### session/create

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

The Client SHOULD retain  

The expiry date is a hint. Can be refreshed `servers/discovery`.


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

A 

## Backward Compatibility

### Existing MCP Servers

Some MCP Servers use SessionID for analytics (HF, GH). This usage is no longer . To associate tool calls

### Session Guidance

It is expected that 


