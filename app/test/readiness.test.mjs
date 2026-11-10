// "TouchDesigner is starting / busy" through the mock bridge, which simulates
// the runtime's startup (not ready until Startup() is done) and a main-thread
// stall (nothing answered, no status) the way TouchDesigner behaves while it
// opens the project.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { findPython } from '../scripts/python.mjs';
import { BridgeClient } from '../dist/web/renderer/bridge.js';

const MOCK = fileURLToPath(new URL('../../touchDesigner/tools/mock_bridge.py', import.meta.url));
const TOKEN = fileURLToPath(new URL('../../touchDesigner/bridge_token.txt', import.meta.url));
const mocks = [];

const waitFor = async (what, pred, ms = 10000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (pred()) return; await new Promise((r) => setTimeout(r, 20)); }
  throw new Error(`timed out waiting for ${what}`);
};

const startMock = (port, args) => new Promise((resolve, reject) => {
  const c = spawn(findPython(), ['-I', '-u', MOCK, '--port', String(port), ...args], { stdio: ['ignore', 'pipe', 'pipe'] });
  let out = '';
  c.stdout.on('data', (d) => { out += d; if (out.includes('approved')) { mocks.push(c); resolve(c); } });
  c.on('exit', (code) => reject(new Error(`mock exited ${code}: ${out}`)));
});
after(() => { for (const m of mocks) { m.stdout.destroy(); m.stderr.destroy(); m.kill(); m.unref(); } });

const client = (port, seen) => new BridgeClient({
  url: `ws://127.0.0.1:${port}/`, token: async () => readFileSync(TOKEN, 'utf8').trim(), binaryType: 'arraybuffer',
  busyAfterMs: 1000, onReadiness: (r) => seen.push(r),
});

test('readiness: starting until the runtime says ready, then ready', async () => {
  const t0 = Date.now();
  await startMock(9984, ['--startup-seconds', '2']);
  const seen = [];
  const events = [];
  const c = client(9984, seen);
  const opts = c['opts'];
  opts.onEvent = (m) => events.push(m);
  c.start();
  try {
    await waitFor('open', () => c.isOpen);
    assert.equal(c.readiness, 'starting', 'welcome said not ready');
    await c.subscribe({ status: true });
    // a request is still answered while starting
    const r = await c.request({ type: 'getState' });
    assert.equal(r.type, 'state');
    await waitFor('ready', () => c.readiness === 'ready');
    assert.ok(Date.now() - t0 >= 1900, 'ready only after the startup time');
    assert.ok(events.some((m) => m.type === 'runtime' && m.ready === true), 'a runtime broadcast announced it');
    assert.deepEqual(seen, ['starting', 'ready']);
  } finally {
    c.stop();
  }
});

test('readiness: busy while the runtime stalls, requests answered late, then ready', async () => {
  const t0 = Date.now();
  await startMock(9983, ['--stall', '2.5,5']);
  const seen = [];
  const c = client(9983, seen);
  c.start();
  try {
    await waitFor('open', () => c.isOpen);
    await c.subscribe({ status: true });
    assert.equal(c.readiness, 'ready');
    await waitFor('stall', () => Date.now() - t0 > 2700);
    const sent = Date.now();
    const reply = c.request({ type: 'getState' });           // made during the stall
    await waitFor('busy', () => c.readiness === 'busy');
    assert.ok(Date.now() - t0 < 5000, 'busy reported during the stall');
    const r = await reply;                                     // not lost: answered when it ends
    assert.equal(r.type, 'state');
    assert.ok(Date.now() - sent > 1000, 'the reply waited for the stall');
    await waitFor('ready again', () => c.readiness === 'ready');
    assert.deepEqual(seen, ['busy', 'ready']);
  } finally {
    c.stop();
  }
});

test('readiness: no busy while not subscribed to status (window hidden)', async () => {
  await startMock(9982, ['--stall', '1.5,4']);
  const seen = [];
  const c = client(9982, seen);
  c.start();
  try {
    await waitFor('open', () => c.isOpen);
    await new Promise((r) => setTimeout(r, 3500));
    assert.deepEqual(seen, [], 'no status expected, so silence is not busy');
  } finally {
    c.stop();
  }
});
