export interface OpenAISpanLike {
  traceId: string;
  spanId: string;
  startedAt?: string | null;
  endedAt?: string | null;
  spanData: { type: string; [key: string]: unknown };
  error?: unknown;
}
export interface OpenAITraceLike {
  traceId: string;
  name?: string;
  workflowName?: string;
}
export class MangekyoTraceProcessor {
  constructor(options?: { agent?: string; label?: string; command?: string[] });
  onTraceStart(trace: OpenAITraceLike): Promise<void>;
  onSpanStart(span: OpenAISpanLike): Promise<void>;
  onSpanEnd(span: OpenAISpanLike): Promise<void>;
  onTraceEnd(trace: OpenAITraceLike): Promise<void>;
  forceFlush(): Promise<void>;
  shutdown(timeout?: number): Promise<void>;
}
