const toolNames = new WeakMap();

/** Record one message emitted by @anthropic-ai/claude-agent-sdk query(). */
export function recordClaudeAgentMessage(recorder, item) {
  if (!item || typeof item !== 'object') return;
  if (item.type === 'assistant' && item.message) {
    const message = item.message;
    recorder.record('model', { provider: 'anthropic', model: message.model,
      output: message.content, usage: message.usage,
      ...(item.error ? { error: item.error } : {}) });
    for (const block of message.content || []) {
      if (block.type !== 'tool_use') continue;
      let names = toolNames.get(recorder);
      if (!names) { names = new Map(); toolNames.set(recorder, names); }
      names.set(block.id, block.name);
      recorder.record('tool_start', { provider: 'anthropic', framework_run_id: block.id,
        name: block.name, input: block.input });
    }
  } else if (item.type === 'user') {
    const content = item.message?.content;
    for (const block of Array.isArray(content) ? content : []) {
      if (block.type !== 'tool_result') continue;
      recorder.record('tool', { provider: 'anthropic', framework_run_id: block.tool_use_id,
        name: toolNames.get(recorder)?.get(block.tool_use_id),
        result: block.content, ...(block.is_error ? { error: true } : {}) });
    }
  } else if (item.type === 'result') {
    if (item.subtype === 'success') recorder.output(item.structured_output ?? item.result);
    else recorder.record('sdk_result', { provider: 'anthropic', subtype: item.subtype,
      error: item.errors || item.subtype });
  }
}
