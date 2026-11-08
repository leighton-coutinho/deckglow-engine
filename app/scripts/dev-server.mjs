// `npm run web`: serves the built UI on http://127.0.0.1:5174/ for working on it in a
// browser, with /dev/ endpoints standing in for the Electron preload. Loopback only;
// thumbnails are limited to PNGs inside touchDesigner/, like the app's main process.
import { createServer } from 'node:http';
import { existsSync, readFileSync, statSync } from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const PORT = Number(process.env.DECKGLOW_WEB_PORT || 5174);
const BRIDGE_PORT = Number(process.env.DECKGLOW_PORT || 9980);
const WEB = fileURLToPath(new URL('../dist/web/', import.meta.url));
const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const TD = path.join(ROOT, 'touchDesigner');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.json': 'application/json', '.svg': 'image/svg+xml' };
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

createServer((req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  const send = (code, type, body) => { res.writeHead(code, { 'Content-Type': type, 'Cache-Control': 'no-store' }); res.end(body); };
  try {
    if (url.pathname === '/dev/config') return send(200, 'application/json', JSON.stringify({ url: `ws://127.0.0.1:${BRIDGE_PORT}/`, root: ROOT, smoke: false, version: 'web-dev' }));
    if (url.pathname === '/dev/token') return send(200, 'text/plain', existsSync(path.join(TD, 'bridge_token.txt')) ? readFileSync(path.join(TD, 'bridge_token.txt'), 'utf8') : '');
    if (url.pathname === '/dev/contract') return send(200, 'application/json', JSON.stringify(contract()));
    if (url.pathname === '/dev/thumb') {
      const p = path.resolve(url.searchParams.get('path') || '');
      if (!inside(p, TD) || path.extname(p).toLowerCase() !== '.png' || !existsSync(p)) return send(404, 'text/plain', 'not found');
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
}).listen(PORT, '127.0.0.1', () => console.log(`DeckGlow UI: http://127.0.0.1:${PORT}/  (bridge ws://127.0.0.1:${BRIDGE_PORT}/)`));
