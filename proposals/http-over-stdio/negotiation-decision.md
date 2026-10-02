# How to negotiate HTTP over STDIO

Select HTTP over STDIO through a user-specified transport named `stdio-v2`.
Client configuration determines the framing before communication begins. Start
experimentally and plan to replace `stdio` through the MCP deprecation process.
This decision does not itself deprecate `stdio`.

The [communication channel decision](communication-channel-decision.md)
retains stdin and stdout and recommends investigating HTTP/2. This decision
addresses how the client and server agree on the transport: through a startup
protocol exchange or through explicit configuration. MCP version and capability
negotiation remain separate concerns.

## Why agreement is needed before communication

Clients currently distinguish `streamable-http` and `stdio`. Existing `stdio`
servers expect newline-delimited JSON-RPC; HTTP uses different framing. Both
sides need to agree on what bytes to send and parse. For HTTP/2, the client must
send an HTTP/2 connection preface, which a legacy STDIO server cannot interpret
as JSON-RPC.

[Transports WG PR #55](https://github.com/modelcontextprotocol/transports-wg/pull/55)
discusses startup negotiation approaches and their compatibility tradeoffs.
The choice here is where that agreement happens.

## Option 1: Negotiate in the startup protocol

Keep the `stdio` transport identifier and let the client and server choose
between existing JSON-RPC framing and HTTP during startup. In the approach
discussed, an environment variable advertises client support for HTTP, and the
server signals whether it accepts. The variable offers a mode; it does not
establish agreement by itself.

This needs a defined bootstrap exchange. One possible design starts in legacy
JSON-RPC framing, agrees to switch, then starts HTTP on the same pipes. It must
define the exact switch point and prevent either side from sending messages
in the old framing afterward. Sending HTTP first instead requires a recovery
path when the server only understands JSON-RPC.

**Pros**

- Existing client configuration can remain `stdio`; compatible clients and
  servers could adopt HTTP automatically.
- A defined fallback could let updated clients continue working with older
  servers without requiring users to choose a transport.

**Cons**

- Requires a bootstrap format, acceptance signal, switch rules, and handling
  for unsupported modes. Dual-mode implementations must support this exchange
  as well as their normal protocol startup.
- Transport fallback would combine with negotiation between older stateful MCP
  and newer stateless MCP. Designs that retry by restarting could create a
  chain of launches, adding latency and potentially repeating startup effects.


## Option 2: Select the transport through user configuration

Introduce `stdio-v2` alongside `stdio`. The user selects the transport in client
configuration using the server's documented launch instructions. The client
then starts the server in the matching mode and speaks that framing from the
first protocol bytes.

This makes agreement explicit outside the protocol exchange. A server that
supports both modes still needs a defined launch mechanism to select one; the
transport identifier alone does not configure the server process. That
mechanism remains to be specified.

**Pros**

- Makes the expected framing known before startup, including whether to send
  an HTTP/2 preface if that wire format is adopted.
- Avoids transport probing, switching, and restart-based fallback. A mismatch
  is a configuration or compatibility error to report.
- Leaves existing `stdio` configurations on their existing framing and allows
  client and server support for `stdio-v2` to be introduced explicitly.

**Cons**

- Users must update configuration and launch instructions when migrating;
  compatible installations do not upgrade automatically.
- Both client and server must support the selected mode. Incorrect configuration
  needs a clear error and cannot be silently repaired through negotiation.
- SDKs and clients may support three transport identifiers during migration,
  along with both local framing implementations.
