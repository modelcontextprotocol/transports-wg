# Proposal: Negotiate HTTP/2 over STDIO through discovery

**Status:** Draft. See the [problem statement](problem-statement.md) and
[communication channel decision](communication-channel-decision.md).

## Proposal

The proposed 2027-03 revision requires HTTP, using HTTP/2 over STDIO locally.
Advertising it in `supportedVersions` lets the client switch directly to HTTP/2
without a separate capability or upgrade RPC.

**Compatible peers negotiate without restarting the server**, retaining existing
`stdio` configuration and avoiding repeated startup effects. The new revision
must allow JSON-RPC `server/discover` as a bootstrap exception; ordinary requests
require HTTP. The full HTTP/2 binding is separate work.

## Version key

| Version | Behavior on STDIO |
| --- | --- |
| **2025-11 — stateful** | JSON-RPC with `initialize` and `notifications/initialized`. |
| **2026-07 — stateless** | JSON-RPC with discovery and per-request metadata. |
| **2027-03 — HTTP/2** | Stateless MCP over HTTP/2, with JSON-RPC discovery available during migration. |

These are shorthand labels for `2025-11-25`, `2026-07-28`, and a proposed future
revision. **2027-03 is a placeholder, not an assigned specification version.**
Wire messages use full revision identifiers.

**Clients always prefer the newest mutually supported version:** 2027-03, then
2026-07, then 2025-11. Start discovery with the newest version the client supports;
a 2025-11-only client starts with `initialize`. Supporting a newer version does
not imply support for older versions.

## Handshake

```mermaid
sequenceDiagram
    participant C as Client
    participant S as Server
    C->>S: server/discover using 2027-03 over JSON-RPC
    S->>C: supportedVersions includes 2027-03
    Note over C,S: Client selects 2027-03
    C->>S: HTTP/2 client preface and SETTINGS
    S->>C: HTTP/2 SETTINGS
    Note over C,S: Acknowledge SETTINGS and continue MCP over HTTP/2
```

After receiving discovery's complete result, the client sends the standard
[HTTP/2 preface][http2] and SETTINGS. The preface selects framing; subsequent
requests declare 2027-03 through [per-request metadata][versions].

HTTP-capable servers recognize JSON-RPC or the HTTP/2 preface at startup.
When discovery is used, flush its response and terminating LF before accepting
the preface. Validate the preface before sending SETTINGS. Advertising 2027-03
alone never switches framing.

Switch only before initialization or application requests, with no pending
exchanges. Preserve partial reads and buffered bytes when handing the preface
to HTTP/2. During bootstrap, send no unsolicited stdout messages; diagnostics
stay on stderr.

## Backward compatibility

**HTTP** means only 2027-03, **STDIO** means only 2026-07 and/or 2025-11,
and **Both** means 2027-03 plus at least one older version. For example:

| Client supports | Server supports | Selected version | Result |
| --- | --- | --- | --- |
| 2027-03, 2026-07, 2025-11 | 2027-03, 2026-07, 2025-11 | 2027-03 | Switch to HTTP/2. |
| 2027-03, 2026-07, 2025-11 | 2026-07, 2025-11 | 2026-07 | Continue stateless JSON-RPC. |
| 2026-07, 2025-11 | 2027-03, 2026-07, 2025-11 | 2026-07 | Continue stateless JSON-RPC. |
| 2027-03, 2026-07, 2025-11 | 2025-11 | 2025-11 | Fall back to stateful initialization. |
| 2025-11 | 2027-03, 2026-07, 2025-11 | 2025-11 | Initialize directly. |
| 2027-03 | 2026-07, 2025-11 | None | Report incompatibility. |

The [existing compatibility flow][stdio] distinguishes 2026-07 discovery from
2025-11 initialization. This proposal adds the 2027-03 HTTP/2 path:

```mermaid
flowchart TD
    subgraph Existing["Existing: 2025-11 stateful and 2026-07 stateless"]
        Start["Select newest client-supported discovery version"] --> Discover["server/discover using selected version"]
        Discover --> Result{"Discovery outcome"}
        Result -->|Success| Shared{"Newest shared discovery version?"}
        Shared -->|2026-07| STDIO["Stateless JSON-RPC using 2026-07"]
        Shared -->|None| Fail["Report incompatibility"]
        Result -->|"UnsupportedProtocolVersionError (-32022)"| Retry{"Both support 2027-03 or 2026-07 from the error list?"}
        Retry -->|Yes, retry discovery using the newest| Discover
        Retry -->|No| Fail
        Result -->|Other recognized stateless error| Error["Report error"]
        Result -->|Unrecognized error or timeout| Stateful{"Client supports 2025-11?"}
        Stateful -->|No| Fail
        Stateful -->|Yes| Init["initialize requesting 2025-11"]
        Older["2025-11-only client"] --> Init
        Init --> Compatible{"Server accepts 2025-11?"}
        Compatible -->|No| Fail
        Compatible -->|Yes| Ready["notifications/initialized"]
        Ready --> Legacy["Stateful JSON-RPC using 2025-11"]
    end
    subgraph Transport["New: 2027-03 HTTP/2"]
        HTTP["HTTP/2 preface and SETTINGS"] --> New["Stateless MCP using 2027-03 over HTTP/2"]
    end
    Shared -->|2027-03| HTTP
```

- **Version error:** [`UnsupportedProtocolVersionError`][version-error] (`-32022`)
  includes the server's versions in `error.data.supported`. If a client requests
  2027-03 and the server lists 2026-07, retry discovery using 2026-07 if the client
  supports it. Choose the newest shared discovery version; if none exists,
  report incompatibility. This error does not trigger `initialize`.
- **Stateful fallback:** a discovery error unrecognized by the stateless protocol,
  or a timeout, can trigger 2025-11 initialization. This is not limited to
  `-32601` (Method not found). On initialization failure, stop without sending
  `notifications/initialized`. Established sessions are not migrated.
- **Process reuse:** fallback reuses the process when possible. Some 2025-11
  servers exit on discovery, so retain an explicit initialization-first option.

## Failure rules

- Query the running process rather than cached discovery. Ignore late discovery
  responses after stateful fallback begins.
- Once the client sends any preface bytes, it cannot return to JSON-RPC on those
  pipes. Invalid or truncated prefaces, EOF, or HTTP/2 startup failure close the
  connection. Bound discovery and HTTP/2 startup waits.

## Removing negotiation later

A client supporting only 2027-03 can skip JSON-RPC discovery and send the HTTP/2
preface and SETTINGS immediately. Servers supporting 2027-03 must accept this.
An older-only server will fail or time out, but the peers have no shared version
anyway. MCP version selection still happens over HTTP.

Before adoption, validate same-process switching, older-version fallback,
fragmented prefaces, combined reads, and failures in two SDKs.

[stdio]: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio#backward-compatibility
[versions]: https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning
[http2]: https://www.rfc-editor.org/rfc/rfc9113.html#section-3.4
[version-error]: https://modelcontextprotocol.io/specification/2026-07-28/schema#unsupportedprotocolversionerror
