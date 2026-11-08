// The runtime's protocol code (bridge_protocol.py) against a fake adapter: auth,
// 31 refusals, broadcasts, applyShow ordering, library management.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { findPython } from '../scripts/python.mjs';

test('bridge_protocol.py passes its offline test', () => {
  const script = fileURLToPath(new URL('../../touchDesigner/tools/test_bridge_protocol.py', import.meta.url));
  const out = execFileSync(findPython(), ['-I', script], { encoding: 'utf8' });
  assert.match(out, /ALL OK\s*$/);
});
