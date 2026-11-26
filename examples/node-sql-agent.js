// Framework-free Node agent emitting the same trace document as Python agents.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const tables = ['bookings', 'invoices'];
const selected = 'invoices'; // Deliberate wrong decision for the demo.
const trace = {
  schema_version: 1,
  events: [
    { kind: 'tool', payload: { name: 'list_tables', input: {}, result: tables } },
    { kind: 'snapshot', name: 'after-discovery', context: { tables } },
    { kind: 'tool', payload: { name: 'select_table', input: { question: 'Count bookings' }, result: { table: selected } } },
    { kind: 'output', payload: { output: { table: selected, count: 1 } } },
  ],
};

const home = process.env.MANGEKYO_HOME;
const command = process.env.MANGEKYO_COMMAND_JSON;
if (!home || !command || !process.env.MANGEKYO_RUN_ID) {
  throw new Error('Launch this example with mangekyo run -- node examples/node-sql-agent.js');
}
const file = path.join(home, `node-trace-${process.pid}.json`);
fs.writeFileSync(file, JSON.stringify(trace));
try {
  const [program, ...prefix] = JSON.parse(command);
  const imported = spawnSync(program, [...prefix, 'ingest', file], { encoding: 'utf8' });
  if (imported.status !== 0) throw new Error(imported.stderr || 'Trace import failed');
  process.stdout.write(imported.stdout);
} finally {
  fs.unlinkSync(file);
}
