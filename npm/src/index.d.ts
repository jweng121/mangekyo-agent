export type RunStatus = 'completed' | 'failed' | 'interrupted';
export type TraceEvent = { kind: string; payload: Record<string, unknown> } | {
  kind: 'snapshot'; name: string; context: Record<string, unknown>;
};
export interface TraceDocument {
  schema_version: 1;
  agent: string;
  label: string;
  status: RunStatus;
  events: TraceEvent[];
}
export interface ImportResult {
  run_id: string;
  status: RunStatus | 'running';
  events: number;
  capabilities: { trace: boolean; checkpoint_inspection: boolean; live_resume: false };
}
export class RunRecorder {
  constructor(options: { agent: string; label: string; command?: string[] });
  readonly agent: string;
  readonly label: string;
  readonly events: TraceEvent[];
  record(kind: string, payload: Record<string, unknown>): this;
  snapshot(name: string, context: Record<string, unknown>): this;
  output(value: unknown): this;
  document(status?: RunStatus): TraceDocument;
  flush(status?: RunStatus): Promise<ImportResult>;
}
export function traceCall<T>(recorder: RunRecorder, kind: 'model' | 'tool', name: string,
  input: unknown, call: () => Promise<T> | T): Promise<T>;
