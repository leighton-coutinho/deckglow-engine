// The engine-output rate limiter (src/main/linegate.ts). Regression for
// 2026-11-09: ~100 readout lines a second reached the window one by one, each
// refreshing Setup and spawning tasklist, until Windows ran out of threads.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { LineGate, isReadout } from '../dist/main/linegate.js';

const readout = (i) => `Drive: 0.${i}  Hit: 0.100  Sync: 0.200  BPM: 128.000  Conf: 0.900  Beat: 0.${i}  SR: 48000`;

test('a burst of readouts reaches the window as the newest one only', () => {
  const out = [];
  const g = new LineGate((l) => out.push(l), 10000);
  for (let i = 0; i < 1000; i++) g.push(readout(i));
  g.flush();
  assert.deepEqual(out, [readout(999)]);
  assert.equal(g.dropped, 999);
});

test('messages pass through, capped per flush, before the newest readout', () => {
  const out = [];
  const g = new LineGate((l) => out.push(l), 10000, 3);
  g.push('Listening to system audio and sending reactive values via OSC');
  g.push(readout(1));
  g.push('Press ENTER to quit');
  for (let i = 0; i < 5; i++) g.push(`warning ${i}`);
  g.push(readout(2));
  g.flush();
  assert.deepEqual(out, ['Listening to system audio and sending reactive values via OSC', 'Press ENTER to quit', 'warning 0', readout(2)]);
  assert.ok(isReadout(readout(0)) && !isReadout('Listening to system audio'));
});

test('it flushes by itself after the interval, at most once per interval', async () => {
  const out = [];
  const g = new LineGate((l) => out.push(l), 50);
  const end = Date.now() + 300;
  while (Date.now() < end) {            // a busy engine: a line every millisecond for 300 ms
    g.push(readout(Date.now() % 1000));
    await new Promise((r) => setTimeout(r, 1));
  }
  await new Promise((r) => setTimeout(r, 80));
  assert.ok(out.length >= 4 && out.length <= 8, `${out.length} emits for 300 ms at a 50 ms interval`);
});
