// `npm run web`: serves the built UI on http://127.0.0.1:5174/ for working on it in a
// browser, with /dev/ endpoints standing in for the Electron preload. Loopback only;
// thumbnails are limited to PNGs inside touchDesigner/, like the app's main process.
import { createServer } from 'node:http';
import { execFile } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { findPython } from './python.mjs';

const PORT = Number(process.env.DECKGLOW_WEB_PORT || 5174);
const BRIDGE_PORT = Number(process.env.DECKGLOW_PORT || 9980);
const WEB = fileURLToPath(new URL('../dist/web/', import.meta.url));
const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const TD = path.join(ROOT, 'touchDesigner');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.json': 'application/json', '.svg': 'image/svg+xml' };
const PACKS = process.env.DECKGLOW_PACKS || '';           // a test install dir; default touchDesigner/Packs
const uploads = new Set();                                    // pack files the page uploaded
const PACK_ID = /^[a-z][a-z0-9]*(\.[a-z0-9][a-z0-9_-]*)+$/;
const inside = (child, parent) => { const r = path.relative(parent, child); return r && !r.startsWith('..') && !path.isAbsolute(r); };

function contract() {
  const c = JSON.parse(readFileSync(path.join(ROOT, 'docs/contract/deckglow.scene-module-1.json'), 'utf8'));
  const slotParameters = {};
  for (const [slot, spec] of Object.entries(c.slots)) {
    slotParameters[slot] = (spec.parameters || []).map((p) => {
      const style = String(p.style).toLowerCase();
      return { parameter: p.name, type: style === 'int' ? 'integer' : style, min: p.range?.[0], max: p.range?.[1], default: p.default, options: p.tokens };
    });
  }
  return { slotParameters, performer: c.performerControls, lanes: c.lanes.map((l) => ({ name: l.name, range: l.range, kind: l.kind })) };
}

function packTool(args) {
  const tool = path.join(TD, 'tools', 'pack_tool.py');
  const extra = PACKS ? ['--packs', PACKS] : [];
  return new Promise((resolve) => execFile(findPython(), ['-I', tool, '--json', ...extra, ...args], { timeout: 180000, windowsHide: true },
    (err, stdout, stderr) => {
      try { resolve(JSON.parse(stdout.trim().split(/\r?\n/).pop())); } catch { resolve({ ok: false, command: args[0], message: String(err || stderr) }); }
    }));
}

function readBody(req, limit = 64 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    const parts = []; let n = 0;
    req.on('data', (c) => { n += c.length; if (n > limit) { reject(new Error('too large')); req.destroy(); } else parts.push(c); });
    req.on('end', () => resolve(Buffer.concat(parts)));
    req.on('error', reject);
  });
}

async function packs(url, req, send) {
  const json = (obj) => send(200, 'application/json', JSON.stringify(obj));
  const op = url.pathname.slice('/dev/pack/'.length);
  if (op === 'upload' && req.method === 'POST') {
    const name = path.basename(url.searchParams.get('name') || 'pack.dgpack');
    if (!name.toLowerCase().endsWith('.dgpack')) return send(400, 'text/plain', 'not a .dgpack');
    const dir = path.join(tmpdir(), 'deckglow-dev-packs', randomBytes(6).toString('hex'));
    mkdirSync(dir, { recursive: true });
    const file = path.join(dir, name);
    writeFileSync(file, await readBody(req));
    uploads.add(file);
    return json({ path: file });
  }
  const p = url.searchParams.get('path') || '';
  if (op === 'inspect') return uploads.has(p) ? json(await packTool(['verify', p])) : send(403, 'text/plain', 'not uploaded');
  if (op === 'install' && req.method === 'POST') {
    return uploads.has(p) ? json(await packTool(['install', p, ...(url.searchParams.get('force') === '1' ? ['--force'] : [])])) : send(403, 'text/plain', 'not uploaded');
  }
  if (op === 'remove' && req.method === 'POST') {
    const id = url.searchParams.get('id') || '';
    return PACK_ID.test(id) && !id.startsWith('com.deckglow') ? json(await packTool(['remove', id])) : send(400, 'text/plain', 'not a pack id');
  }
  if (op === 'list') return json(await packTool(['list']));
  return send(404, 'text/plain', 'not found');
}

createServer(async (req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  const send = (code, type, body) => { res.writeHead(code, { 'Content-Type': type, 'Cache-Control': 'no-store' }); res.end(body); };
  try {
    if (url.pathname === '/dev/config') return send(200, 'application/json', JSON.stringify({ url: `ws://127.0.0.1:${BRIDGE_PORT}/`, root: ROOT, smoke: false, version: 'web-dev' }));
    if (url.pathname === '/dev/token') return send(200, 'text/plain', existsSync(path.join(TD, 'bridge_token.txt')) ? readFileSync(path.join(TD, 'bridge_token.txt'), 'utf8') : '');
    if (url.pathname === '/dev/contract') return send(200, 'application/json', JSON.stringify(contract()));
    if (url.pathname.startsWith('/dev/pack/')) return await packs(url, req, send);
    // the repo's example pack, so the install flow can be driven from a script
    if (url.pathname === '/dev/fixture/example.dgpack') return send(200, 'application/octet-stream', readFileSync(path.join(TD, 'examples/packs/com.example.demo-1.0.0.dgpack')));
    if (url.pathname === '/dev/thumb') {
      const p = path.resolve(url.searchParams.get('path') || '');
      const ok = inside(p, TD) || (PACKS && inside(p, path.resolve(PACKS)));
      if (!ok || path.extname(p).toLowerCase() !== '.png' || !existsSync(p)) return send(404, 'text/plain', 'not found');
      return send(200, 'image/png', readFileSync(p));
    }
    if (url.pathname === '/') { res.writeHead(302, { Location: '/renderer/index.html' }); return res.end(); }
    const rel = decodeURIComponent(url.pathname.slice(1));
    const file = path.normalize(path.join(WEB, rel));
    if (!inside(file, WEB) || !existsSync(file) || !statSync(file).isFile()) return send(404, 'text/plain', 'not found');
    return send(200, TYPES[path.extname(file)] || 'application/octet-stream', readFileSync(file));
  } catch (e) {
    return send(500, 'text/plain', String(e));
  }
}).listen(PORT, '127.0.0.1', () => console.log(`DeckGlow UI: http://127.0.0.1:${PORT}/  (bridge ws://127.0.0.1:${BRIDGE_PORT}/${PACKS ? ', packs ' + PACKS : ''})`));
