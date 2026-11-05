/** Compile-time projections combine semantic data with binding-owned IDs. */
import type * as M from "../data-model.schema";
import type * as W from "../original.schema";

type Assert<T extends true> = T;
type Equivalent<A, B> = [A] extends [B] ? [B] extends [A] ? true : false : false;
type RequestTarget<T extends M.MCPRequest> =
  T["method"] extends "tools/call" | "prompts/get" ? { name: T["name"] } :
  T["method"] extends "resources/read" ? { uri: T["name"] } : {};
type RequestWire<T extends M.MCPRequest> = {
  jsonrpc: "2.0";
  id: W.RequestId;
  method: T["method"];
  params: T["payload"] & RequestTarget<T> & {
    _meta: T["metadata"]["meta"] & { "io.modelcontextprotocol/protocolVersion": string };
  };
};
type NotificationParams<T extends M.MCPNotification> = Exclude<T["payload"], undefined> & {
  _meta?: Exclude<T["metadata"]["meta"], undefined> & {
    "io.modelcontextprotocol/subscriptionId"?: W.RequestId;
  };
} & (T["method"] extends "notifications/cancelled" ? { requestId: W.RequestId } : {});
type NotificationWire<T extends M.MCPNotification> = {
  jsonrpc: "2.0";
  method: T["method"];
} & (undefined extends T["payload"]
  ? { params?: NotificationParams<T> }
  : { params: NotificationParams<T> });
type ResultWire<T extends M.MCPResponse> = {
  jsonrpc: "2.0";
  id: W.RequestId;
  result: T["payload"] & (T["metadata"] extends { meta: infer Meta }
    ? { _meta: Meta & { "io.modelcontextprotocol/subscriptionId": W.RequestId } }
    : { _meta?: Exclude<T["metadata"]["meta"], undefined> });
};
type ErrorWire<T extends M.MCPErrorResponse> = {
  jsonrpc: "2.0";
  id?: W.RequestId;
  error: T["payload"];
};

type CheckNoMetadataKind = Assert<Equivalent<Extract<"kind", keyof M.MessageMetadata>, never>>;
type CheckNoMetadataID = Assert<Equivalent<Extract<"requestId", keyof M.MessageMetadata>, never>>;
type CheckNoEnvelopeKind = Assert<Equivalent<Extract<"kind", keyof M.MCPMessage>, never>>;
type CheckNoEnvelopeID = Assert<Equivalent<Extract<"requestId", keyof M.MCPMessage>, never>>;
type CheckNoEnvelopeName = Assert<Equivalent<Extract<"name", keyof M.MCPMessage>, never>>;
type CheckNoResponseName = Assert<Equivalent<Extract<"name", keyof M.MCPResponse>, never>>;
type CheckNoNotificationName = Assert<Equivalent<Extract<"name", keyof M.MCPNotification>, never>>;
type CheckRequiredToolName = Assert<Equivalent<Pick<M.CallToolRequest, "name">, { name: string }>>;
type CheckRequiredPromptName = Assert<Equivalent<Pick<M.GetPromptRequest, "name">, { name: string }>>;
type CheckRequiredResourceName = Assert<Equivalent<Pick<M.ReadResourceRequest, "name">, { name: string }>>;
type CheckNoToolPayloadName = Assert<Equivalent<Extract<"name", keyof M.CallToolRequest["payload"]>, never>>;
type CheckNoPromptPayloadName = Assert<Equivalent<Extract<"name", keyof M.GetPromptRequest["payload"]>, never>>;
type CheckNoResourcePayloadURI = Assert<Equivalent<Extract<"uri", keyof M.ReadResourceRequest["payload"]>, never>>;
type CheckOptionalNotificationMetadata = Assert<{} extends M.MCPNotification["metadata"] ? true : false>;
type CheckRequiredRequestMetadata = Assert<{} extends M.MCPRequest["metadata"] ? false : true>;
type CheckRequiredCapabilities = Assert<
  { meta: {} } extends M.MCPRequest["metadata"] ? false : true
>;

type CheckHeaderMismatchError = Assert<Equivalent<ErrorWire<M.HeaderMismatchError>, W.HeaderMismatchError>>;
type CheckUnsupportedProtocolVersionError = Assert<Equivalent<ErrorWire<M.UnsupportedProtocolVersionError>, W.UnsupportedProtocolVersionError>>;
type CheckMissingRequiredClientCapabilityError = Assert<Equivalent<ErrorWire<M.MissingRequiredClientCapabilityError>, W.MissingRequiredClientCapabilityError>>;
type CheckCancelledNotification = Assert<Equivalent<NotificationWire<M.CancelledNotification>, W.CancelledNotification>>;
type CheckDiscoverRequest = Assert<Equivalent<RequestWire<M.DiscoverRequest>, W.DiscoverRequest>>;
type CheckDiscoverResultResponse = Assert<Equivalent<ResultWire<M.DiscoverResultResponse>, W.DiscoverResultResponse>>;
type CheckProgressNotification = Assert<Equivalent<NotificationWire<M.ProgressNotification>, W.ProgressNotification>>;
type CheckPaginatedRequest = Assert<Equivalent<RequestWire<M.PaginatedRequest>, W.PaginatedRequest>>;
type CheckListResourcesRequest = Assert<Equivalent<RequestWire<M.ListResourcesRequest>, W.ListResourcesRequest>>;
type CheckListResourcesResultResponse = Assert<Equivalent<ResultWire<M.ListResourcesResultResponse>, W.ListResourcesResultResponse>>;
type CheckListResourceTemplatesRequest = Assert<Equivalent<RequestWire<M.ListResourceTemplatesRequest>, W.ListResourceTemplatesRequest>>;
type CheckListResourceTemplatesResultResponse = Assert<Equivalent<ResultWire<M.ListResourceTemplatesResultResponse>, W.ListResourceTemplatesResultResponse>>;
type CheckReadResourceRequest = Assert<Equivalent<RequestWire<M.ReadResourceRequest>, W.ReadResourceRequest>>;
type CheckReadResourceResultResponse = Assert<Equivalent<ResultWire<M.ReadResourceResultResponse>, W.ReadResourceResultResponse>>;
type CheckResourceListChangedNotification = Assert<Equivalent<NotificationWire<M.ResourceListChangedNotification>, W.ResourceListChangedNotification>>;
type CheckSubscriptionsListenRequest = Assert<Equivalent<RequestWire<M.SubscriptionsListenRequest>, W.SubscriptionsListenRequest>>;
type CheckSubscriptionsListenResultResponse = Assert<Equivalent<ResultWire<M.SubscriptionsListenResultResponse>, W.SubscriptionsListenResultResponse>>;
type CheckSubscriptionsAcknowledgedNotification = Assert<Equivalent<NotificationWire<M.SubscriptionsAcknowledgedNotification>, W.SubscriptionsAcknowledgedNotification>>;
type CheckResourceUpdatedNotification = Assert<Equivalent<NotificationWire<M.ResourceUpdatedNotification>, W.ResourceUpdatedNotification>>;
type CheckListPromptsRequest = Assert<Equivalent<RequestWire<M.ListPromptsRequest>, W.ListPromptsRequest>>;
type CheckListPromptsResultResponse = Assert<Equivalent<ResultWire<M.ListPromptsResultResponse>, W.ListPromptsResultResponse>>;
type CheckGetPromptRequest = Assert<Equivalent<RequestWire<M.GetPromptRequest>, W.GetPromptRequest>>;
type CheckGetPromptResultResponse = Assert<Equivalent<ResultWire<M.GetPromptResultResponse>, W.GetPromptResultResponse>>;
type CheckPromptListChangedNotification = Assert<Equivalent<NotificationWire<M.PromptListChangedNotification>, W.PromptListChangedNotification>>;
type CheckListToolsRequest = Assert<Equivalent<RequestWire<M.ListToolsRequest>, W.ListToolsRequest>>;
type CheckListToolsResultResponse = Assert<Equivalent<ResultWire<M.ListToolsResultResponse>, W.ListToolsResultResponse>>;
type CheckCallToolResultResponse = Assert<Equivalent<ResultWire<M.CallToolResultResponse>, W.CallToolResultResponse>>;
type CheckCallToolRequest = Assert<Equivalent<RequestWire<M.CallToolRequest>, W.CallToolRequest>>;
type CheckToolListChangedNotification = Assert<Equivalent<NotificationWire<M.ToolListChangedNotification>, W.ToolListChangedNotification>>;
type CheckLoggingMessageNotification = Assert<Equivalent<NotificationWire<M.LoggingMessageNotification>, W.LoggingMessageNotification>>;
type CheckCompleteRequest = Assert<Equivalent<RequestWire<M.CompleteRequest>, W.CompleteRequest>>;
type CheckCompleteResultResponse = Assert<Equivalent<ResultWire<M.CompleteResultResponse>, W.CompleteResultResponse>>;
