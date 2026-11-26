# Mangekyo Agent for Node.js and TypeScript

Capture local model, tool, and output evidence from Node.js agents and import it into [Mangekyo Agent](https://github.com/jweng121/mangekyo-agent). This package includes TypeScript declarations and has no runtime dependencies. It requires Node.js 18+ and a working `mangekyo` CLI installation on the same machine.

This package is prepared for npm but has not been published. From this repository, install it in a Node project with `npm install ./npm`. After publication, use `npm install mangekyo-agent-js`.

## Framework independent capture

```ts
import { RunRecorder, traceCall } from 'mangekyo-agent-js';

const recorder = new RunRecorder({ agent: 'my-agent', label: 'Answer a question' });
let status: 'completed' | 'failed' = 'completed';
try {
  const answer = await traceCall(recorder, 'model', 'my-provider',
    { prompt: 'Hello' }, () => model.generate('Hello'));
  const result = await traceCall(recorder, 'tool', 'lookup',
    { key: 'example' }, () => lookup('example'));
  recorder.output({ answer, result });
} catch (error) {
  status = 'failed';
  throw error;
} finally {
  await recorder.flush(status);
}
```

`traceCall` works with any provider, including Anthropic's `client.messages.create(...)`, OpenAI API calls, local models, and custom tools. It records the returned value or error. For streaming APIs, collect the final response and record it explicitly with `recorder.record('model', ...)`.

## OpenAI Agents SDK for TypeScript

The SDK's trace processor observes model, tool, and other spans. Add it once before agent runs:

```ts
import { addTraceProcessor, Agent, run } from '@openai/agents';
import { MangekyoTraceProcessor } from 'mangekyo-agent-js/openai-agents';

addTraceProcessor(new MangekyoTraceProcessor({ agent: 'my-openai-agent' }));
const agent = new Agent({ name: 'Assistant', instructions: 'Be helpful.' });
await run(agent, 'Hello');
```

`addTraceProcessor` keeps the SDK's existing exporters. Use the SDK's `setTraceProcessors([new MangekyoTraceProcessor(...)])` if you want only this local processor. Tracing must be enabled for the SDK run. The processor imports one Mangekyo trace when the SDK trace ends.

The SDK's Responses API spans can expose only a response ID, even when the underlying model produced text. In that case Mangekyo records the span and response ID, while model inputs and outputs remain missing. Chat Completions generation spans can include inputs and outputs when SDK tracing includes sensitive data.

## Claude Agent SDK for TypeScript

Record the messages already yielded by `query()`:

```ts
import { query } from '@anthropic-ai/claude-agent-sdk';
import { RunRecorder } from 'mangekyo-agent-js';
import { recordClaudeAgentMessage } from 'mangekyo-agent-js/claude-agent-sdk';

const recorder = new RunRecorder({ agent: 'my-claude-agent', label: 'Answer a question' });
let status: 'completed' | 'failed' = 'completed';
try {
  for await (const message of query({ prompt: 'Hello', options: { maxTurns: 2 } })) {
    recordClaudeAgentMessage(recorder, message);
    if (message.type === 'result' && message.is_error) status = 'failed';
  }
} catch (error) {
  status = 'failed';
  throw error;
} finally {
  await recorder.flush(status);
}
```

The adapter records assistant model messages, tool requests and results, and final output. It does not capture hidden model inputs that the SDK does not expose in the yielded message.

## Inspect the run

For a single process run, launch the Node program through Mangekyo:

```sh
mangekyo run -- node agent.mjs
mangekyo log
```

The package detects `MANGEKYO_RUN_ID` and the CLI command passed by `mangekyo run`, so captured events attach to that process run. When run directly, `flush()` creates a standalone local run through `mangekyo ingest`. In either case, imported snapshots are inspectable; live resume requires an adapter for the original runtime and is not provided by this npm package.

Trace content can include prompts, tool inputs, and outputs. Pass only data you intend to keep in the local store. Call `flush()` before the Node process exits; import failures reject the promise and leave the recorder's events in memory for a retry.
