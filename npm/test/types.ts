import { addTraceProcessor } from '@openai/agents';
import type { SDKMessage } from '@anthropic-ai/claude-agent-sdk';
import { RunRecorder, traceCall } from 'mangekyo-agent-js';
import { MangekyoTraceProcessor } from 'mangekyo-agent-js/openai-agents';
import { recordClaudeAgentMessage } from 'mangekyo-agent-js/claude-agent-sdk';

const recorder = new RunRecorder({ agent: 'test', label: 'type check' });
const processor = new MangekyoTraceProcessor();
addTraceProcessor(processor);
const message = null as unknown as SDKMessage;
recordClaudeAgentMessage(recorder, message);
const result: Promise<number> = traceCall(recorder, 'tool', 'count', {}, async () => 1);
void result;
