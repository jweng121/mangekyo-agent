import assert from 'node:assert/strict';
import { test } from 'node:test';
import { RunRecorder, traceCall } from '../src/index.js';
import { MangekyoTraceProcessor } from '../src/openai-agents.js';
import { recordClaudeAgentMessage } from '../src/claude-agent-sdk.js';

test('recorder emits the portable trace contract', () => {
  const recorder = new RunRecorder({ agent: 'test-agent', label: 'task' });
  recorder.record('tool', { name: 'lookup', input: { id: 1 }, result: 'ok' });
  recorder.snapshot('after-lookup', { found: true });
  recorder.output({ answer: 42 });
  assert.deepEqual(recorder.document().events.map((event) => event.kind), ['tool', 'snapshot', 'output']);
  assert.equal(recorder.document().schema_version, 1);
});

test('provider independent wrapper records a failing call and rethrows', async () => {
  const recorder = new RunRecorder({ agent: 'test-agent', label: 'task' });
  await assert.rejects(traceCall(recorder, 'model', 'test-provider', { prompt: 'hi' },
    () => { throw new Error('offline'); }), /offline/);
  assert.equal(recorder.document('failed').events[0].payload.error.message, 'offline');
});

test('OpenAI span adapter retains model and tool evidence', async () => {
  const processor = new MangekyoTraceProcessor();
  await processor.onTraceStart({ traceId: 'trace_1', name: 'Example' });
  await processor.onSpanEnd({ traceId: 'trace_1', spanId: 'span_1',
    spanData: { type: 'generation', model: 'test-model', input: [{ role: 'user', content: 'hi' }],
      output: [{ role: 'assistant', content: 'hello' }], usage: { input_tokens: 1, output_tokens: 1 } } });
  await processor.onSpanEnd({ traceId: 'trace_1', spanId: 'span_2',
    spanData: { type: 'function', name: 'lookup', input: '{"id":1}', output: 'ok' } });
  const events = processor.traces.get('trace_1').document().events;
  assert.equal(events[0].kind, 'model');
  assert.equal(events[0].payload.model, 'test-model');
  assert.equal(events[1].kind, 'tool');
  assert.equal(events[1].payload.result, 'ok');
});

test('Claude Agent SDK messages capture model, tool, and result', () => {
  const recorder = new RunRecorder({ agent: 'claude-agent', label: 'task' });
  recordClaudeAgentMessage(recorder, { type: 'assistant', message: { model: 'claude-test',
    content: [{ type: 'tool_use', id: 'tool_1', name: 'lookup', input: { id: 1 } }] } });
  recordClaudeAgentMessage(recorder, { type: 'user', message: { content: [
    { type: 'tool_result', tool_use_id: 'tool_1', content: 'ok' }] } });
  recordClaudeAgentMessage(recorder, { type: 'result', subtype: 'success', result: 'done' });
  assert.deepEqual(recorder.document().events.map((event) => event.kind),
    ['model', 'tool_start', 'tool', 'output']);
  assert.equal(recorder.document().events[2].payload.name, 'lookup');
});
