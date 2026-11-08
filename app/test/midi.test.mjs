// The MIDI mapping logic (src/renderer/midi-map.ts), without a controller.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MidiMapper, parse, stepLook, defaultSettings, describe } from '../dist/web/renderer/midi-map.js';

function mapper() {
  const log = [];
  const m = new MidiMapper(defaultSettings(), { press: (id) => log.push(['press', id]), value: (id, v) => log.push(['value', id, v]) });
  return { m, log };
}

test('parse: note on/off, velocity-0 note-on is an off, CC, others ignored', () => {
  assert.deepEqual(parse([0x91, 36, 100]), { kind: 'note-on', channel: 1, number: 36, value: 100 });
  assert.equal(parse([0x90, 36, 0]).kind, 'note-off');
  assert.equal(parse([0x80, 36, 64]).kind, 'note-off');
  assert.deepEqual(parse([0xb0, 7, 127]), { kind: 'cc', channel: 0, number: 7, value: 127 });
  assert.equal(parse([0xe0, 0, 64]), null);        // pitch bend
  assert.equal(parse([0xf8]), null);               // clock
});

test('learn a pad for a TAKE, then pressing it fires; releasing does not', () => {
  const { m, log } = mapper();
  m.learn('take:2');
  assert.deepEqual(m.handle([0x90, 40, 90]), { learned: 'take:2', binding: { type: 'note', channel: 0, number: 40 }, replaced: undefined });
  assert.equal(m.learningAction, null);
  assert.equal(describe(m.settings.bindings['take:2']), 'Note 40 · ch 1');
  m.handle([0x80, 40, 0]);
  m.handle([0x90, 40, 127]);
  m.handle([0x90, 40, 0]);
  m.handle([0x90, 41, 127]);                       // another pad: unmapped
  m.handle([0x91, 40, 127]);                       // same note, other channel: unmapped
  assert.deepEqual(log, [['press', 'take:2']]);
});

test('a fader needs a CC; its value arrives as 0..1', () => {
  const { m, log } = mapper();
  m.learn('performer:masterIntensity');
  assert.match(m.handle([0x90, 36, 100]).rejected, /needs a knob or fader/);
  assert.equal(m.learningAction, 'performer:masterIntensity', 'still learning after a rejected note');
  assert.equal(m.handle([0xb0, 7, 10]).learned, 'performer:masterIntensity');
  m.handle([0xb0, 7, 127]);
  m.handle([0xb0, 7, 0]);
  assert.deepEqual(log, [['value', 'performer:masterIntensity', 1], ['value', 'performer:masterIntensity', 0]]);
});

test('a CC button fires once per press (crossing the middle), never while held', () => {
  const { m, log } = mapper();
  m.learn('blackout');
  m.handle([0xb2, 20, 127]);                        // learned while pressed: counts as high
  m.handle([0xb2, 20, 127]);                        // still held
  m.handle([0xb2, 20, 0]);
  m.handle([0xb2, 20, 127]);
  m.handle([0xb2, 20, 90]);
  m.handle([0xb2, 20, 10]);
  m.handle([0xb2, 20, 64]);
  assert.deepEqual(log, [['press', 'blackout'], ['press', 'blackout']]);
});

test('one control maps to one action: learning it again moves it', () => {
  const { m } = mapper();
  m.learn('next');
  m.handle([0x90, 50, 100]);
  m.learn('prev');
  const r = m.handle([0x90, 50, 100]);
  assert.equal(r.replaced, 'next');
  assert.deepEqual(Object.keys(m.settings.bindings), ['prev']);
});

test('disabled, or a different input device, does nothing', () => {
  const { m, log } = mapper();
  m.learn('blackout');
  m.handle([0x90, 1, 100], 'Pad A');
  m.settings.input = 'Pad A';
  m.handle([0x90, 1, 100], 'Pad B');
  m.handle([0x90, 1, 100], 'Pad A');
  m.settings.enabled = false;
  m.handle([0x90, 1, 100], 'Pad A');
  m.learn('nonsense');
  assert.equal(m.learningAction, null, 'unknown actions cannot be learned');
  assert.deepEqual(log, [['press', 'blackout']]);
});

test('next / previous look skip empty slots and wrap', () => {
  const filled = [true, false, true, false, false, false, false, false, false, false, false, false, false, false, false, true];
  assert.equal(stepLook(filled, 0, 1), 2);
  assert.equal(stepLook(filled, 2, 1), 15);
  assert.equal(stepLook(filled, 15, 1), 0);
  assert.equal(stepLook(filled, 0, -1), 15);
  assert.equal(stepLook(filled, null, 1), 0);
  assert.equal(stepLook(filled, null, -1), 15);
  assert.equal(stepLook(new Array(16).fill(false), 3, 1), null);
});
