import { RunRecorder } from './index.js';

function spanEvent(span) {
  const data = span.spanData;
  if (!data || typeof data !== 'object') return null;
  const common = { trace_id: span.traceId, span_id: span.spanId,
    started_at: span.startedAt, ended_at: span.endedAt };
  if (data.type === 'generation') {
    return { kind: 'model', payload: { ...common, model: data.model,
      input: data.input, output: data.output, usage: data.usage,
      ...(span.error ? { error: span.error } : {}) } };
  }
  if (data.type === 'response') {
    return { kind: 'model', payload: { ...common, response_id: data.response_id,
      input: data._input, output: data._response,
      ...(span.error ? { error: span.error } : {}) } };
  }
  if (data.type === 'function') {
    return { kind: 'tool', payload: { ...common, name: data.name,
      input: data.input, result: data.output,
      ...(span.error ? { error: span.error } : {}) } };
  }
  return { kind: 'sdk_span', payload: { ...common, span_type: data.type,
    name: data.name, ...(span.error ? { error: span.error } : {}) } };
}

/** Implements the OpenAI Agents SDK TracingProcessor interface without a hard dependency. */
export class MangekyoTraceProcessor {
  constructor({ agent = 'openai-agents-js', label = 'Agent workflow', command } = {}) {
    this.agent = agent;
    this.label = label;
    this.command = command;
    this.traces = new Map();
  }

  async onTraceStart(trace) {
    this.traces.set(trace.traceId, new RunRecorder({ agent: this.agent,
      label: trace.name || trace.workflowName || this.label, command: this.command }));
  }

  async onSpanStart() {}

  async onSpanEnd(span) {
    let recorder = this.traces.get(span.traceId);
    if (!recorder) {
      recorder = new RunRecorder({ agent: this.agent, label: this.label, command: this.command });
      this.traces.set(span.traceId, recorder);
    }
    const event = spanEvent(span);
    if (event) recorder.record(event.kind, event.payload);
  }

  async onTraceEnd(trace) {
    const recorder = this.traces.get(trace.traceId) ||
      new RunRecorder({ agent: this.agent, label: this.label, command: this.command });
    if (!recorder.events.length) recorder.record('sdk_trace', { trace_id: trace.traceId });
    await recorder.flush(recorder.events.some((event) => event.payload?.error) ? 'failed' : 'completed');
    this.traces.delete(trace.traceId);
  }

  async forceFlush() {}
  async shutdown() {}
}
