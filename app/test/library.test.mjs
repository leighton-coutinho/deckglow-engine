// Creator packs and the library flows, end to end without TouchDesigner:
// pack_tool.py --json (what the app's main process runs) on a throwaway pack,
// then validate / approve / load / revoke through the mock bridge, which runs
// the runtime's real protocol code. Nothing touches the runtime's own files:
// the pack installs into a temp folder and the mock keeps approvals in memory.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { findPython } from '../scripts/python.mjs';
import { BridgeClient, BridgeRequestError } from '../dist/web/renderer/bridge.js';

const TD = fileURLToPath(new URL('../../touchDesigner/', import.meta.url));
const PACK_TOOL = path.join(TD, 'tools', 'pack_tool.py');
const MOCK = path.join(TD, 'tools', 'mock_bridge.py');
const PORT = 9988;
const ID = 'com.example.libtest';
const MODULE = `${ID}.flat_wash`;
let tmp, packFile, packsDir, mock, fingerprint;

const py = (args) => {
  try {
    return JSON.parse(execFileSync(findPython(), ['-I', PACK_TOOL, '--json', ...args], { encoding: 'utf8' }).trim().split(/\r?\n/).pop());
  } catch (e) {           // exit status 1 still prints the JSON result
    return JSON.parse(String(e.stdout).trim().split(/\r?\n/).pop());
  }
};

/** A hash of everything the runtime keeps about approvals and validation. */
function runtimeFiles() {
  const h = createHash('sha256');
  h.update(readFileSync(path.join(TD, 'library', 'approved.json')));
  for (const f of readdirSync(path.join(TD, 'validation')).sort()) h.update(f).update(readFileSync(path.join(TD, 'validation', f)));
  return h.digest('hex');
}

const waitFor = async (what, pred, ms = 8000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (pred()) return; await new Promise((r) => setTimeout(r, 25)); }
  throw new Error(`timed out waiting for ${what}`);
};

function startMock() {
  return new Promise((resolve, reject) => {
    const child = spawn(findPython(), ['-I', '-u', MOCK, '--port', String(PORT), '--packs', packsDir], { stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    child.stdout.on('data', (d) => { out += d; if (out.includes('approved')) resolve(child); });
    child.stderr.on('data', (d) => { out += d; });
    child.on('exit', (code) => reject(new Error(`mock exited ${code}: ${out}`)));
  });
}

before(() => {
  fingerprint = runtimeFiles();
  tmp = mkdtempSync(path.join(tmpdir(), 'deckglow-libtest-'));
  packsDir = path.join(tmp, 'packs');
  const src = path.join(tmp, 'src', ID);
  cpSync(path.join(TD, 'examples', 'packs', 'com.example.demo'), src, { recursive: true });
  const pj = JSON.parse(readFileSync(path.join(src, 'pack.json'), 'utf8'));
  Object.assign(pj, { id: ID, displayName: 'Library Test Pack', author: 'DeckGlow tests' });
  pj.modules[0].id = MODULE;
  writeFileSync(path.join(src, 'pack.json'), JSON.stringify(pj, null, 2));
  const mj = path.join(src, 'modules', 'flat_wash', 'module.json');
  writeFileSync(mj, JSON.stringify({ ...JSON.parse(readFileSync(mj, 'utf8')), id: MODULE, displayName: 'Test Wash' }, null, 2));
  packFile = path.join(tmp, `${ID}-1.0.0.dgpack`);
  const built = py(['build', src, '-o', packFile]);
  assert.equal(built.ok, true, JSON.stringify(built.log));
});

after(async () => {
  if (mock) await new Promise((r) => { mock.once('exit', r); mock.kill(); });
  rmSync(tmp, { recursive: true, force: true });
});

test('pack_tool --json: verify shows what the person needs to decide', () => {
  const r = py(['--packs', packsDir, 'verify', packFile]);
  assert.equal(r.ok, true);
  assert.equal(r.status, 'pass');
  assert.equal(r.pack.id, ID);
  assert.equal(r.pack.displayName, 'Library Test Pack');
  assert.equal(r.pack.author, 'DeckGlow tests');
  assert.deepEqual(r.pack.modules.map((m) => m.id), [MODULE]);
  assert.equal(r.pack.palettes, 1);
  assert.equal(r.installed, null);
  assert.ok(r.checks.length >= 10);
});

test('pack_tool --json: install, refuse a reinstall, list', () => {
  const r = py(['--packs', packsDir, 'install', packFile]);
  assert.equal(r.ok, true, r.message);
  assert.match(r.message, /installed com\.example\.libtest 1\.0\.0/);
  const again = py(['--packs', packsDir, 'install', packFile]);
  assert.equal(again.ok, false);
  assert.equal(again.code, 'already_installed');
  assert.equal(py(['--packs', packsDir, 'verify', packFile]).installed, '1.0.0');
  const list = py(['--packs', packsDir, 'list']);
  assert.deepEqual(list.packs.map((p) => p.id), [ID]);
  assert.equal(list.packs[0].pack.displayName, 'Library Test Pack');
});

test('pack_tool --json: a broken archive is refused with its checks', () => {
  const bad = path.join(tmp, 'broken.dgpack');
  writeFileSync(bad, 'not a zip');
  const r = py(['--packs', packsDir, 'verify', bad]);
  assert.equal(r.ok, false);
  assert.ok(r.checks.some((c) => c.status === 'fail' && c.check === 'archive'));
  assert.equal(py(['--packs', packsDir, 'remove', 'com.example.nothere']).code, 'not_installed');
});

test('library: installed module needs validating, then approving, before it can be used', async () => {
  mock = await startMock();
  const events = [];
  const c = new BridgeClient({
    url: `ws://127.0.0.1:${PORT}/`, token: async () => readFileSync(path.join(TD, 'bridge_token.txt'), 'utf8').trim(),
    binaryType: 'arraybuffer', onEvent: (m) => events.push(m),
  });
  c.start();
  try {
    await libraryFlow(c, events);
  } finally {
    c.stop();                 // or its reconnect timer keeps the test process alive
  }
});

async function libraryFlow(c, events) {
  await waitFor('open', () => c.isOpen);
  const find = async () => (await c.getLibrary()).modules.find((m) => m.id === MODULE);

  let m = await find();
  assert.equal(m.source, ID);
  assert.equal(m.approved, 'no');
  assert.equal(m.quarantine, 'not run');
  assert.ok((await c.getLibrary()).palettes.includes(`${ID}/sunset`), 'pack palette in the palette list');

  const refused = async (msg, code) => assert.rejects(c.request(msg), (e) => e instanceof BridgeRequestError && e.code === code, `${msg.type} -> ${code}`);
  await refused({ type: 'setSlotModule', slot: 'base_scene', module: MODULE }, 'not_approved');
  await refused({ type: 'approveModule', module: MODULE }, 'not_validated');
  await refused({ type: 'approveModule', module: 'com.example.nothere.x' }, 'unknown_module');
  assert.equal((await c.request({ type: 'getReport', module: MODULE })).report, null);

  await c.request({ type: 'validateModule', module: MODULE });
  await refused({ type: 'validateModule', module: MODULE }, 'busy');
  await waitFor('running', () => events.some((e) => e.type === 'validation' && e.phase === 'running' && e.module === MODULE));
  await waitFor('done', () => events.some((e) => e.type === 'validation' && e.phase === 'done'));
  const done = events.find((e) => e.type === 'validation' && e.phase === 'done');
  assert.equal(done.result, 'pass');
  assert.equal(done.report.version, '1.0.0');
  await waitFor('libraryChanged', () => events.some((e) => e.type === 'libraryChanged' && e.module === MODULE));
  m = await find();
  assert.equal(m.quarantine, 'pass');
  assert.equal(m.approved, 'no', 'validation alone approves nothing');
  assert.equal((await c.request({ type: 'getReport', module: MODULE })).report.result, 'pass');

  const before = events.length;
  await c.request({ type: 'approveModule', module: MODULE, note: 'test' });
  await waitFor('libraryChanged after approve', () => events.slice(before).some((e) => e.type === 'libraryChanged'));
  assert.equal((await find()).approved, 'yes');
  await c.request({ type: 'setSlotModule', slot: 'base_scene', module: MODULE });
  await waitFor('loaded in the Scene layer', () => c.state.slots.base_scene.module === MODULE);
  await c.request({ type: 'setSlotModule', slot: 'base_scene', module: 'com.deckglow.kinetic_stripes' });

  await c.request({ type: 'revokeModule', module: MODULE });
  assert.equal((await find()).approved, 'no');
  await refused({ type: 'setSlotModule', slot: 'base_scene', module: MODULE }, 'not_approved');
}

test('remove the pack; the runtime\'s own approval and report files were never touched', async () => {
  const r = py(['--packs', packsDir, 'remove', ID]);
  assert.equal(r.ok, true);
  assert.deepEqual(py(['--packs', packsDir, 'list']).packs, []);
  assert.equal(runtimeFiles(), fingerprint, 'approved.json and validation/ unchanged');
});
