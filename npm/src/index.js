import { spawn } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function commandFromEnvironment() {
  const configured = process.env.MANGEKYO_COMMAND_JSON;
  if (!configured) return ['mangekyo'];
  const command = JSON.parse(configured);
  if (!Array.isArray(command) || !command.length || command.some((part) => typeof part !== 'string')) {
    throw new Error('MANGEKYO_COMMAND_JSON must be a nonempty JSON string array');
  }
  return command;
}

function runIngest(command, file) {
  return new Promise((resolve, reject) => {
    const child = spawn(command[0], [...command.slice(1), 'ingest', file], { windowsHide: true });
    let stdout = '';
    let stderr = '';
    child.stdout.setEncoding('utf8').on('data', (chunk) => { stdout += chunk; });
    child.stderr.setEncoding('utf8').on('data', (chunk) => { stderr += chunk; });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code !== 0) return reject(new Error(`Mangekyo ingest failed (${code}): ${stderr.trim() || stdout.trim()}`));
      try { resolve(JSON.parse(stdout)); }
      catch (error) { reject(new Error(`Mangekyo ingest returned invalid JSON: ${error.message}`)); }
    });
  });
}

/** Explicit, opt-in recorder for Node.js agent applications. */
export class RunRecorder {
  constructor({ agent, label, command } = {}) {
    if (typeof agent !== 'string' || !agent.trim()) throw new TypeError('agent must be a nonempty string');
    if (typeof label !== 'string' || !label.trim()) throw new TypeError('label must be a nonempty string');
    this.agent = agent;
    this.label = label;
    this.command = command;
    this.events = [];
  }

  record(kind, payload) {
    if (typeof kind !== 'string' || !kind.trim()) throw new TypeError('kind must be a nonempty string');
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new TypeError('payload must be an object');
    this.events.push({ kind, payload });
    return this;
  }

  snapshot(name, context) {
    if (typeof name !== 'string' || !name.trim()) throw new TypeError('name must be a nonempty string');
    if (!context || typeof context !== 'object' || Array.isArray(context)) throw new TypeError('context must be an object');
    this.events.push({ kind: 'snapshot', name, context });
    return this;
  }

  output(value) { return this.record('output', { output: value }); }

  document(status = 'completed') {
    if (!['completed', 'failed', 'interrupted'].includes(status)) throw new TypeError('Invalid run status');
    if (!this.events.length) throw new Error('Cannot import an empty trace');
    // JSON round-trip checks that the trace is serializable before launching Mangekyo.
    return JSON.parse(JSON.stringify({ schema_version: 1, agent: this.agent, label: this.label,
      status, events: this.events }));
  }

  async flush(status = 'completed') {
    const document = this.document(status);
    const directory = await mkdtemp(join(tmpdir(), 'mangekyo-js-'));
    const file = join(directory, 'trace.json');
    try {
      await writeFile(file, JSON.stringify(document), { encoding: 'utf8', mode: 0o600 });
      const result = await runIngest(this.command || commandFromEnvironment(), file);
      this.events.length = 0;
      return result;
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  }
}

/** Capture one awaited model or tool call from any JavaScript SDK. */
export async function traceCall(recorder, kind, name, input, call) {
  if (kind !== 'model' && kind !== 'tool') throw new TypeError('kind must be model or tool');
  if (typeof call !== 'function') throw new TypeError('call must be a function');
  try {
    const result = await call();
    recorder.record(kind, { name, input, result });
    return result;
  } catch (error) {
    recorder.record(kind, { name, input, error: {
      type: error?.name || 'Error', message: String(error?.message || error) } });
    throw error;
  }
}
