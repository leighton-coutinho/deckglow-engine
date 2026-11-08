// Looks and TAKE through the mock bridge (the runtime's real protocol code;
// the TAKE state machine itself is tested in touchDesigner/tools/test_look_logic.py).
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { findPython } from '../scripts/python.mjs';
import { BridgeClient, BridgeRequestError } from '../dist/web/renderer/bridge.js';

const PORT = 9989;
const MOCK = fileURLToPath(new URL('../../touchDesigner/tools/mock_bridge.py', import.meta.url));
const TOKEN = fileURLToPath(new URL('../../touchDesigner/bridge_token.txt', import.meta.url));
let mock;

const waitFor = async (what, pred, ms = 8000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (pred()) return; await new Promise((r) => setTimeout(r, 20)); }
  throw new Error(`timed out waiting for ${what}`);
};

before(async () => {
  mock = await new Promise((resolve, reject) => {
    const c = spawn(findPython(), ['-I', '-u', MOCK, '--port', String(PORT)], { stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    c.stdout.on('data', (d) => { out += d; if (out.includes('approved')) resolve(c); });
    c.on('exit', (code) => reject(new Error(`mock exited ${code}: ${out}`)));
  });
});
after(async () => { if (mock) await new Promise((r) => { mock.once('exit', r); mock.kill(); }); });

test('looks: save, TAKE with a fade on the beat, cut, refusals, show round trip', async () => {
  const phases = [];
  const c = new BridgeClient({
    url: `ws://127.0.0.1:${PORT}/`, token: async () => readFileSync(TOKEN, 'utf8').trim(), binaryType: 'arraybuffer',
    onState: (s) => { if (s.take) phases.push(s.take.phase); },
  });
  c.start();
  try {
    await waitFor('open', () => c.isOpen);
    assert.equal(c.state.looks.length, 16);
    assert.deepEqual(c.state.transition, { fade: 2, quantize: 'bar' });
    const refused = (msg, code) => assert.rejects(c.request(msg), (e) => e instanceof BridgeRequestError && e.code === code, code);

    await c.request({ type: 'saveLook', index: 0, name: 'Stripes' });
    await waitFor('saved', () => c.state.looks[0]?.name === 'Stripes');
    assert.equal(c.state.looks[0].look.slots.base_scene.module, 'com.deckglow.kinetic_stripes');
    assert.equal(c.state.looks[0].look.palette, 'deckglow');

    await c.request({ type: 'setSlotModule', slot: 'base_scene', module: 'com.deckglow.solid_background' });
    await c.request({ type: 'setSlotEnabled', slot: 'hit_fx', enabled: false });
    await c.request({ type: 'setPalette', name: 'ember' });
    await c.request({ type: 'setBackground', color: [0.25, 0, 0.35] });
    await c.request({ type: 'saveLook', index: 1, name: 'Wash' });
    await waitFor('saved 2', () => c.state.looks[1]?.look.palette === 'ember');

    await refused({ type: 'take', index: 5 }, 'empty_look');
    await refused({ type: 'take', index: 16 }, 'bad_field');
    await refused({ type: 'take', index: 0, quantize: 'phrase' }, 'bad_field');

    phases.length = 0;
    await c.request({ type: 'setEngine', mode: 'demo', bpm: 240 });         // a beat every 0.25 s
    await c.request({ type: 'take', index: 0, fade: 0.4, quantize: 'beat' });
    await refused({ type: 'take', index: 1 }, 'busy');                      // still loading
    await waitFor('look 1 on screen', () => c.state.take.phase === 'idle' && c.state.take.current === 0, 6000);
    const order = phases.filter((p, i) => p !== phases[i - 1]);
    assert.deepEqual(order.slice(order.indexOf('loading')), ['loading', 'armed', 'fading', 'idle'], order.join(' > '));
    assert.equal(c.state.slots.base_scene.module, 'com.deckglow.kinetic_stripes');
    assert.equal(c.state.slots.hit_fx.enabled, true);
    assert.equal(c.state.palette.name, 'deckglow');
    assert.equal(c.state.background, null);

    await c.request({ type: 'take', index: 1, fade: 0, quantize: 'now' });
    await waitFor('cut to look 2', () => c.state.take.phase === 'idle' && c.state.take.current === 1, 4000);
    assert.equal(c.state.slots.base_scene.module, 'com.deckglow.solid_background');
    assert.equal(c.state.slots.hit_fx.enabled, false);
    assert.deepEqual([c.state.palette.name, c.state.background], ['ember', [0.25, 0, 0.35]]);

    await c.request({ type: 'setTransition', fade: 3.5, quantize: 'now' });
    await waitFor('transition', () => c.state.transition.fade === 3.5 && c.state.transition.quantize === 'now');
    await c.request({ type: 'renameLook', index: 1, name: 'Purple wash' });
    await waitFor('renamed', () => c.state.looks[1].name === 'Purple wash');

    // a saved show carries the bank and transition; applyShow puts them back
    const show = JSON.parse(JSON.stringify(c.state));
    await c.request({ type: 'deleteLook', index: 0 });
    await c.request({ type: 'deleteLook', index: 1 });
    await c.request({ type: 'setTransition', fade: 1, quantize: 'bar' });
    await waitFor('cleared', () => !c.state.looks[0] && !c.state.looks[1]);
    const r = await c.request({ type: 'applyShow', show });
    assert.deepEqual(r.problems, []);
    await waitFor('bank back', () => c.state.looks[1]?.name === 'Purple wash' && c.state.looks[0]?.name === 'Stripes');
    assert.deepEqual(c.state.transition, { fade: 3.5, quantize: 'now' });
  } finally {
    c.stop();
  }
});
