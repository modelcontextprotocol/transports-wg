/**
 * Message-object mapping prototype. Callers validate method-specific schemas and
 * resolve exchange context. IDs belong only to this JSON-RPC binding; a decoded
 * message must travel with its context (or remain attached to its exchange).
 * HTTP framing, authentication, and the exchange registry are outside this example.
 */
import type * as Model from "../data-model.schema";
import type * as Wire from "../original.schema";

const versionKey = "io.modelcontextprotocol/protocolVersion";
const subscriptionKey = "io.modelcontextprotocol/subscriptionId";
const has = (value: object, key: string) => Object.prototype.hasOwnProperty.call(value, key);

/** Binding-owned state; never part of MCPMessage or its metadata. */
export interface BindingContext {
  protocolVersion?: string;
  method?: string;
  requestId?: Wire.RequestId;
  cancellationTargetId?: Wire.RequestId;
  subscriptionId?: Wire.RequestId;
}

/** Runtime classification is supplied by the dispatch path, not message fields. */
export interface MessageHandlers<T> {
  request(message: Model.MCPRequest, context: BindingContext): T;
  notification(message: Model.MCPNotification, context: BindingContext): T;
  response(message: Model.MCPResponse, context: BindingContext): T;
  error(message: Model.MCPErrorResponse, context: BindingContext): T;
}

function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Expected an object");
  }
  return value as Record<string, unknown>;
}

function id(value: unknown): Wire.RequestId {
  if (typeof value !== "string" && typeof value !== "number") {
    throw new Error("Binding context requires an ID");
  }
  return value;
}

function payload(value: unknown): Record<string, unknown> {
  const fields = object(value);
  if (has(fields, "_meta")) throw new Error("Message-level _meta belongs in metadata.meta");
  return fields;
}

function restoreMeta(meta: Model.MetaObject | undefined, context: BindingContext) {
  if (meta && has(meta, subscriptionKey)) throw new Error("Subscription ID belongs in binding context");
  if (meta === undefined && context.subscriptionId === undefined) return {};
  return { _meta: {
    ...meta,
    ...(context.subscriptionId !== undefined ? { [subscriptionKey]: context.subscriptionId } : {}),
  } };
}

function extractMeta(fields: Record<string, unknown>, context: BindingContext) {
  const { _meta, ...body } = fields;
  if (!has(fields, "_meta")) return { body, metadata: {} };
  const { [subscriptionKey]: subscriptionId, ...meta } = object(_meta);
  if (subscriptionId !== undefined) context.subscriptionId = id(subscriptionId);
  return { body, metadata: { meta } };
}

function requireContext(message: Model.MCPMessage): void {
  if (typeof message.protocolVersion !== "string" || typeof message.method !== "string") {
    throw new Error("Message requires resolved context");
  }
}

export function encodeRequest(message: Model.MCPRequest, context: BindingContext = {}): Wire.JSONRPCRequest {
  requireContext(message);
  if (has(message.metadata.meta, versionKey)) throw new Error("Duplicate protocol version");
  return {
    jsonrpc: "2.0", id: id(context.requestId), method: message.method,
    params: {
      ...payload(message.payload),
      _meta: { ...message.metadata.meta, [versionKey]: message.protocolVersion },
    },
  };
}

export function encodeNotification(message: Model.MCPNotification, context: BindingContext = {}): Wire.JSONRPCNotification {
  requireContext(message);
  if (message.payload === undefined) {
    if (has(message.metadata, "meta") || context.subscriptionId !== undefined ||
        message.method === "notifications/cancelled") {
      throw new Error("Metadata or cancellation requires a present payload object");
    }
    return { jsonrpc: "2.0", method: message.method };
  }
  const fields = payload(message.payload);
  if (message.method === "notifications/cancelled" && has(fields, "requestId")) {
    throw new Error("Cancellation ID belongs in binding context");
  }
  return {
    jsonrpc: "2.0", method: message.method,
    params: {
      ...fields,
      ...(message.method === "notifications/cancelled" ? { requestId: id(context.cancellationTargetId) } : {}),
      ...restoreMeta(message.metadata.meta, context),
    },
  };
}

export function encodeResponse(message: Model.MCPResponse, context: BindingContext = {}): Wire.JSONRPCResultResponse {
  requireContext(message);
  if (message.method === "subscriptions/listen" &&
      id(context.subscriptionId) !== id(context.requestId)) {
    throw new Error("Mismatched subscription context");
  }
  return {
    jsonrpc: "2.0", id: id(context.requestId),
    result: { ...payload(message.payload), ...restoreMeta(message.metadata.meta, context) } as Wire.Result,
  };
}

export function encodeError(message: Model.MCPErrorResponse, context: BindingContext = {}): Wire.JSONRPCErrorResponse {
  return {
    jsonrpc: "2.0",
    ...(context.requestId !== undefined ? { id: id(context.requestId) } : {}),
    error: message.payload,
  };
}

export function decode<T>(wire: Wire.JSONRPCMessage, handlers: MessageHandlers<T>, supplied: BindingContext = {}): T {
  if (wire.jsonrpc !== "2.0") throw new Error("Invalid representation version");
  // Carry context per message; do not mutate the caller's exchange registry.
  const context = { ...supplied };
  delete context.cancellationTargetId;
  delete context.subscriptionId;
  if ("method" in wire) {
    if ("id" in wire) {
      const { _meta, ...fields } = object(wire.params);
      const { [versionKey]: protocolVersion, ...meta } = object(_meta);
      if (typeof protocolVersion !== "string") throw new Error("Missing protocol version");
      return handlers.request({
        protocolVersion, method: wire.method,
        metadata: { meta: meta as Model.RequestMetaObject }, payload: fields,
      }, { requestId: id(wire.id), protocolVersion, method: wire.method });
    }
    if (typeof context.protocolVersion !== "string") throw new Error("Notification context required");
    const { body, metadata } = extractMeta(wire.params === undefined ? {} : object(wire.params), context);
    if (wire.method === "notifications/cancelled") {
      context.cancellationTargetId = id(body.requestId);
      if (context.requestId !== context.cancellationTargetId) throw new Error("Mismatched cancellation context");
      delete body.requestId;
    }
    if (context.subscriptionId !== undefined && context.subscriptionId !== context.requestId) {
      throw new Error("Mismatched subscription context");
    }
    return handlers.notification({ protocolVersion: context.protocolVersion, method: wire.method,
      metadata, payload: wire.params === undefined ? undefined : body,
    }, context);
  }
  if (context.requestId !== undefined && wire.id !== context.requestId) {
    throw new Error("Mismatched response context");
  }
  if ("result" in wire && context.requestId === undefined) {
    throw new Error("Response correlation context required");
  }
  if (wire.id !== undefined) context.requestId = id(wire.id);
  else delete context.requestId;
  if ("result" in wire) {
    if (typeof context.protocolVersion !== "string" || typeof context.method !== "string") {
      throw new Error("Response context required");
    }
    const { body, metadata } = extractMeta(wire.result, context);
    if (context.method === "subscriptions/listen" &&
        id(context.subscriptionId) !== id(context.requestId)) {
      throw new Error("Mismatched subscription context");
    }
    return handlers.response({ protocolVersion: context.protocolVersion, method: context.method,
      metadata, payload: body as Model.Result,
    }, context);
  }
  return handlers.error({ protocolVersion: context.protocolVersion, method: context.method,
    metadata: {}, payload: wire.error,
  }, context);
}
