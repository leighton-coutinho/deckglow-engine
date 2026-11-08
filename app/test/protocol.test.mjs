// The runtime's own plain-Python tests, run from npm test:
//  - bridge_protocol.py against a fake adapter: auth, refusals, broadcasts,
//    applyShow ordering, library management, looks and TAKE messages
//  - the look runtime's TAKE state machine with stand-in hosts and a clock
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { findPython } from '../scripts/python.mjs';

for (const name of ['test_bridge_protocol.py', 'test_look_logic.py']) {
  test(`${name} passes`, () => {
    const script = fileURLToPath(new URL(`../../touchDesigner/tools/${name}`, import.meta.url));
    const out = execFileSync(findPython(), ['-I', script], { encoding: 'utf8' });
    assert.match(out, /ALL OK\s*$/);
  });
}
