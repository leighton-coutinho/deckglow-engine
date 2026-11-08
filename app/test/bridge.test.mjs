// The app's bridge client against the mock bridge, which runs the runtime's
// real protocol code (touchDesigner/tools/bridge_protocol.py). Run: npm test
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { findPython } from '../scripts/python.mjs';
import { BridgeClient, BridgeRequestError } from '../dist/web/renderer/bridge.js';

const PORT = 9987;
const URL_ = `ws://127.0.0.1:${PORT}/`;
const MOCK = fileURLToPath(new URL('../../touchDesigner/tools/mock_bridge.py', import.meta.url));
const TOKEN_FILE = fileURLToPath(new URL('../../touchDesigner/bridge_token.txt', import.meta.url));
let mock = null;

function startMock() {
  return new Promise((resolve, reject) => {
    const child = spawn(findPython(), ['-I', '-u', MOCK, '--port', String(PORT)], { stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    const onData = (d) => { out += d; if (out.includes('approved')) resolve(child); };
    child.stdout.on('data', onData);
    child.stderr.on('data', (d) => { out += d; });
    child.on('exit', (code) => reject(new Error(`mock exited ${code}: ${out}`)));
  });
}
const stopMock = (child) => new Promise((resolve) => { child.once('exit', resolve); child.kill(); });

const waitFor = async (what, pred, ms = 5000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (pred()) return; await new Promise((r) => setTimeout(r, 25)); }
  throw new Error(`timed out waiting for ${what}`);
};
const token = async () => readFileSync(TOKEN_FILE, 'utf8').trim();

function client(extra = {}) {
  const seen = { conn: [], states: [], status: [], frames: [] };
  const c = new BridgeClient({
    url: URL_, token, binaryType: 'arraybuffer', client: 'deckglow-app/test', requestTimeoutMs: 3000,
    onConnection: (x) => seen.conn.push(x.phase), onState: (s) => seen.states.push(s),
    onStatus: (s) => seen.status.push(s), onPreview: (f) => seen.frames.push(f), ...extra,
  });
  return { c, seen };
}

before(async () => { mock = await startMock(); });
after(async () => { if (mock) await stopMock(mock); });

test('connects, authenticates and receives the show state', async () => {
  const { c, seen } = client();
  c.start();
  await waitFor('open', () => c.connection.phase === 'open');
  assert.equal(seen.states[0].schema, 'deckglow.show/1');
  assert.deepEqual(Object.keys(seen.states[0].slots), ['base_scene', 'hit_fx', 'brand_overlay', 'finish_fx']);
  c.stop();
});

test('a change is acked and comes back as broadcast state; getState replies resolve', async () => {
  const { c, seen } = client();
  c.start();
  await waitFor('open', () => c.isOpen);
  const ack = await c.request({ type: 'setSlotEnabled', slot: 'hit_fx', enabled: false });
  assert.equal(ack.type, 'ack');
  await waitFor('broadcast', () => seen.states.at(-1).slots.hit_fx.enabled === false);
  const r = await c.request({ type: 'getState' });
  assert.equal(r.type, 'state');
  assert.equal(r.state.slots.hit_fx.enabled, false);
  await c.request({ type: 'setSlotEnabled', slot: 'hit_fx', enabled: true });
  c.stop();
});

test('refusals reject with the runtime error code', async () => {
  const { c } = client();
  c.start();
  await waitFor('open', () => c.isOpen);
  const cases = [
    [{ type: 'setSlotIntensity', slot: 'hit_fx', value: 2 }, 'bad_field'],
    [{ type: 'setSlotModule', slot: 'base_scene', module: 'com.deckglow.stub' }, 'not_approved'],
    [{ type: 'setSlotModule', slot: 'hit_fx', module: 'com.deckglow.kinetic_stripes' }, 'wrong_slot'],
    [{ type: 'setOutput', flashLimit: false }, 'confirm_required'],
    [{ type: 'setControl', slot: 'hit_fx', parameter: 'Spawncount', value: 99 }, 'bad_field'],
    [{ type: 'eval', code: '1' }, 'unknown_type'],
  ];
  for (const [msg, code] of cases) {
    await assert.rejects(c.request(msg), (e) => e instanceof BridgeRequestError && e.code === code, JSON.stringify(msg));
  }
  c.stop();
});

test('library lists modules with approval and controls', async () => {
  const { c } = client();
  c.start();
  await waitFor('open', () => c.isOpen);
  const lib = await c.getLibrary();
  const orb = lib.modules.find((m) => m.id === 'com.deckglow.orb_burst');
  assert.equal(orb.approved, 'yes');
  assert.ok(orb.controls.some((x) => x.parameter === 'Spawncount'));
  assert.ok(lib.palettes.includes('ember'));
  assert.equal(lib.modules.find((m) => m.id === 'com.deckglow.stub').approved, 'no');
  c.stop();
});

test('status and preview subscriptions deliver, and survive a runtime restart', async () => {
  const { c, seen } = client();
  await c.subscribe({ status: true, preview: { fps: 10, width: 320 } });   // before connecting: kept for later
  c.start();
  await waitFor('status', () => seen.status.length > 0 && seen.frames.length > 0);
  assert.equal(Object.keys(seen.status[0].lanes).length, 16);
  assert.ok(seen.frames[0].byteLength > 100);

  await stopMock(mock);
  mock = null;
  await waitFor('offline', () => c.connection.phase === 'offline');
  await assert.rejects(c.request({ type: 'getState' }), (e) => e.code === 'offline');

  mock = await startMock();
  const before = seen.frames.length;
  try {
    // the client backs off up to 5 s between attempts, and a CI runner starts Python slowly
    await waitFor('reconnect', () => c.isOpen, 15000);
    await waitFor('frames resume', () => seen.frames.length > before + 2, 5000);
  } catch (e) {
    const tail = seen.conn.slice(-8).join(' > ');
    throw new Error(`${e.message} (connection phases: ${tail}; now ${JSON.stringify(c.connection)})`);
  } finally {
    c.stop();
  }
});

test('a wrong token is reported as auth-failed, not offline', async () => {
  const { c } = client({ token: async () => 'not-the-token' });
  c.start();
  await waitFor('auth-failed', () => c.connection.phase === 'auth-failed');
  assert.match(c.connection.reason, /refused the token/);
  c.stop();
});
