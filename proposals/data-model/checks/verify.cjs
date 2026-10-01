// Run: npx --yes --package=typescript@5.9.3 -- node checks/verify.cjs
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const original = fs.readFileSync(path.join(root, 'original.schema.ts'));
assert.equal(createHash('sha256').update(original).digest('hex'),
  'b2d3a00d4094e413a48628560fec60652169a3d2b427e8c629238e13f987723f');
for (const binding of ['stdio', 'streamable-http']) {
  assert.deepEqual(fs.readFileSync(path.join(root, `${binding}.schema.ts`)), original);
}
const proposed = fs.readFileSync(path.join(root, 'data-model.schema.ts'), 'utf8');
assert.doesNotMatch(proposed, /\bJSONRPC\w*\b|\bjsonrpc\s*:/);
assert.doesNotMatch(proposed, /\bRequestId\b|\brequestId\s*[?:]|\bkind\s*[?:]/);
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-data-model-check-'));
const tsc = process.argv[2] || 'tsc';
execFileSync(tsc, ['--strict', '--exactOptionalPropertyTypes', '--target', 'es2022',
  '--module', 'commonjs', '--outDir', dir,
  ...['original.schema.ts', 'data-model.schema.ts', 'stdio.schema.ts', 'streamable-http.schema.ts',
    'checks/compatibility.ts', 'checks/mapping.ts'].map(file => path.join(root, file))], {stdio: 'inherit'});
const { encodeRequest, encodeNotification, encodeResponse, encodeError, decode: dispatch } = require(path.join(dir, 'checks/mapping.js'));
const handlers = {
  request: (message, context) => ({message, context, encode: encodeRequest}),
  notification: (message, context) => ({message, context, encode: encodeNotification}),
  response: (message, context) => ({message, context, encode: encodeResponse}),
  error: (message, context) => ({message, context, encode: encodeError}),
};
const decode = (wire, context) => dispatch(wire, handlers, context);
const version = '2026-07-28';
const context = {protocolVersion: version, method: 'tools/call', requestId: 42};
const request = {
  jsonrpc: '2.0', id: 42, method: 'tools/call', params: {
    _meta: {
      'io.modelcontextprotocol/protocolVersion': version,
      'io.modelcontextprotocol/clientCapabilities': {},
      'io.modelcontextprotocol/clientInfo': {name: 'example', version: '1.0'},
      progressToken: 'weather-42',
    },
    name: 'weather', arguments: {city: 'Seattle'},
  },
};
const semantic = {
  protocolVersion: version, method: 'tools/call', metadata: {
    meta: {
      'io.modelcontextprotocol/clientCapabilities': {},
      'io.modelcontextprotocol/clientInfo': {name: 'example', version: '1.0'},
      progressToken: 'weather-42',
    },
  }, payload: {name: 'weather', arguments: {city: 'Seattle'}},
};
assert.deepEqual(decode(request), {message: semantic, context, encode: encodeRequest});
assert.deepEqual(encodeRequest(semantic, context), request);
assert.deepEqual(decode({...request, id: 'different'}).message, semantic);
assert.throws(() => encodeRequest(semantic), /context/);
const cases = [
  [request],
  [{...request, id: '42'}],
  [{...request, id: 0}],
  [{jsonrpc: '2.0', method: 'notifications/tools/list_changed'}, context],
  [{jsonrpc: '2.0', method: 'notifications/tools/list_changed', params: {}}, context],
  [{jsonrpc: '2.0', method: 'notifications/tools/list_changed', params: {_meta: {}}}, context],
  [{jsonrpc: '2.0', method: 'notifications/progress', params: {progressToken: 'weather-42', progress: 0}}, context],
  [{jsonrpc: '2.0', method: 'notifications/cancelled', params: {requestId: 42}}, context],
  [{jsonrpc: '2.0', method: 'notifications/cancelled', params: {requestId: 0, reason: 'Stopped'}}, {...context, requestId: 0}],
  [{jsonrpc: '2.0', method: 'notifications/tools/list_changed', params: {
    _meta: {'io.modelcontextprotocol/subscriptionId': 'sub-1'}}},
    {...context, requestId: 'sub-1', method: 'subscriptions/listen'}],
  [{jsonrpc: '2.0', id: 42, result: {resultType: 'complete', content: [], isError: true}}, context],
  [{jsonrpc: '2.0', id: 42, result: {resultType: 'complete', content: [], _meta: {}}}, context],
  [{jsonrpc: '2.0', id: 42, result: {resultType: 'input_required', requestState: 'opaque',
    inputRequests: {roots: {method: 'roots/list'}}}}, context],
  [{jsonrpc: '2.0', id: 42, result: {resultType: 'complete',
    _meta: {'io.modelcontextprotocol/subscriptionId': 42}}}, {...context, method: 'subscriptions/listen'}],
  [{jsonrpc: '2.0', id: 42, error: {code: -32602, message: 'Invalid arguments', data: {_meta: {nested: true}, value: null}}}, context],
  [{jsonrpc: '2.0', error: {code: -32700, message: 'Parse error'}}],
  [{jsonrpc: '2.0', id: 'unknown', error: {code: -32600, message: 'Invalid request'}}],
  [{...request, params: {...request.params, _meta: {...request.params._meta, 'com.example/trace': {nested: [1, null]}}}}],
];
for (const [wire, ctx] of cases) {
  const decoded = decode(wire, ctx);
  const {message: model, context: binding, encode} = decoded;
  assert.equal('kind' in model, false);
  assert.equal('requestId' in model, false);
  assert.equal('requestId' in model.metadata, false);
  assert.equal('kind' in model.metadata, false);
  if (encode === encodeNotification || encode === encodeResponse) {
    assert.equal('io.modelcontextprotocol/subscriptionId' in (model.metadata.meta || {}), false);
  }
  if (model.method === 'notifications/cancelled') assert.equal('requestId' in model.payload, false);
  assert.deepEqual(encode(model, binding), wire);
  assert.deepEqual(decode(encode(model, binding), ctx), decoded);
  // The same JSON object is the HTTP body/SSE data and the stdio line content.
  assert.deepEqual(JSON.parse(JSON.stringify(encode(model, binding)) + '\n'), wire);
}
assert.throws(() => decode({jsonrpc:'2.0', id:42, result:{resultType:'complete'}}), /context/);
assert.throws(() => decode({jsonrpc:'2.0', id:42, result:{resultType:'complete'}},
  {protocolVersion:version, method:'tools/call'}), /context/);
assert.throws(() => decode({jsonrpc:'2.0', id:'42', result:{resultType:'complete'}}, context), /context/);
assert.throws(() => decode({jsonrpc:'2.0', method:'notifications/tools/list_changed'}), /context/);
assert.throws(() => decode({...request, params:{name:'weather'}}), /object/);
assert.throws(() => encodeRequest({...semantic, payload:{...semantic.payload, _meta:{}}}, context), /_meta/);
assert.throws(() => encodeRequest({...semantic, metadata:{...semantic.metadata,
  meta:{...semantic.metadata.meta, 'io.modelcontextprotocol/protocolVersion':version}}}, context), /Duplicate/);
assert.throws(() => decode({jsonrpc:'2.0', method:'notifications/cancelled', params:{requestId:'42'}}, context), /context/);
assert.throws(() => decode({jsonrpc:'2.0', method:'notifications/tools/list_changed',
  params:{_meta:{'io.modelcontextprotocol/subscriptionId':'42'}}}, context), /context/);
// Equal payload shapes still dispatch by the selected binding operation.
const ambiguous = {
  protocolVersion: version, method: 'tools/call', metadata: {},
  payload: {resultType: 'complete', code: -32602, message: 'domain data'},
};
assert.ok('result' in encodeResponse(ambiguous, context));
assert.ok('error' in encodeError(ambiguous, context));
assert.equal(decode(encodeResponse(ambiguous, context), context).encode, encodeResponse);
assert.equal(decode(encodeError(ambiguous, context), context).encode, encodeError);
console.log(`PASS: pinned source hash, byte-identical bindings, strict TypeScript compatibility, ${cases.length} round trips, and invalid mapping cases.`);
console.log(`Compiled verification artifacts: ${dir}`);
