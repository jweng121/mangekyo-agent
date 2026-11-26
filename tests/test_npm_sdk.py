import shutil
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mangekyo.store import Store


def test_node_sdk_attaches_to_launcher_run(tmp_path):
    if not shutil.which('node'):
        pytest.skip('Node is unavailable')
    module = (Path(__file__).resolve().parent.parent / 'npm' / 'src' / 'index.js').as_uri()
    script = f'''
import {{ RunRecorder, traceCall }} from {module!r};
const recorder = new RunRecorder({{ agent: 'typescript-agent', label: 'integration' }});
const response = await traceCall(recorder, 'model', 'fixture-model',
  {{ prompt: 'hello' }}, async () => ({{ text: 'world' }}));
recorder.record('tool', {{ name: 'lookup', input: {{ key: 1 }}, result: 42 }});
recorder.output(response);
await recorder.flush();
'''
    run = subprocess.run(
        [sys.executable, '-m', 'mangekyo', '--home', str(tmp_path),
         'run', '--', 'node', '--input-type=module', '-e', script],
        capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    with Store(tmp_path) as store:
        runs = store.runs()
        assert len(runs) == 1
        assert runs[0]['status'] == 'completed'
        events = store.events(runs[0]['id'])
        assert any(event['kind'] == 'model' and
                   event['payload']['result'] == {'text': 'world'} for event in events)
        assert any(event['kind'] == 'tool' and
                   event['payload']['result'] == 42 for event in events)
        assert any(event['kind'] == 'output' and
                   event['payload']['output'] == {'text': 'world'} for event in events)


def test_openai_agents_processor_imports_real_sdk_span(tmp_path):
    if not shutil.which('node'):
        pytest.skip('Node is unavailable')
    package = Path(__file__).resolve().parent.parent / 'npm'
    if not (package / 'node_modules' / '@openai' / 'agents').exists():
        pytest.skip('OpenAI Agents SDK dev dependency is unavailable')
    env = os.environ.copy()
    env['MANGEKYO_COMMAND_JSON'] = json.dumps(
        [sys.executable, '-m', 'mangekyo', '--home', str(tmp_path)])
    env['PYTHONPATH'] = str(package.parent)
    script = '''
import { setTraceProcessors, withTrace, createGenerationSpan } from '@openai/agents';
import { MangekyoTraceProcessor } from './src/openai-agents.js';
setTraceProcessors([new MangekyoTraceProcessor({ agent: 'openai-fixture' })]);
await withTrace('fixture-workflow', async () => {
  const span = createGenerationSpan({ data: { model: 'fixture-model',
    input: [{ role: 'user', content: 'hi' }],
    output: [{ role: 'assistant', content: 'hello' }] } });
  span.start();
  span.end();
});
'''
    run = subprocess.run(['node', '--input-type=module', '-e', script],
                         cwd=package, env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    with Store(tmp_path) as store:
        runs = store.runs()
        assert len(runs) == 1
        events = store.events(runs[0]['id'])
        assert any(event['kind'] == 'model' and
                   event['payload']['model'] == 'fixture-model' for event in events)
