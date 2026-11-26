import type { RunRecorder } from './index.js';
export interface ClaudeAgentMessageLike {
  type: string;
  subtype?: string;
  error?: unknown;
  errors?: string[];
  result?: string;
  structured_output?: unknown;
  message?: unknown;
}
export function recordClaudeAgentMessage(recorder: RunRecorder, item: ClaudeAgentMessageLike): void;
