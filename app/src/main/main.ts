// DeckGlow desktop app - main process.
//
// The renderer is a sandboxed page served from app://deckglow/ (never file://).
// It talks to the TouchDesigner runtime directly over the deckglow.control/1
// WebSocket; this process only does what a page must not: read the bridge
// token and module thumbnails from disk, and show file dialogs for show files.

import { app, BrowserWindow, dialog, ipcMain, net, protocol, session, shell } from 'electron';
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';
import type { AppConfig, ContractInfo, ControlDecl, ShowState } from '../shared/api';

const SHOW_SCHEMA = 'deckglow.show/1';
const RENDERER = path.join(__dirname, '..', 'web');   // dist/web: renderer/ and shared/
const PORT = Number(process.env.DECKGLOW_PORT || 9980);
const SMOKE = process.argv.find((a) => a.startsWith('--smoke='))?.slice('--smoke='.length) ?? null;

protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true } },
]);

/** The repository (or install) folder that holds touchDesigner/. */
function findRoot(): string | null {
  const fromEnv = process.env.DECKGLOW_ROOT;
  if (fromEnv && existsSync(path.join(fromEnv, 'touchDesigner'))) return path.resolve(fromEnv);
  let dir = app.getAppPath();
  for (let i = 0; i < 6; i++) {
    if (existsSync(path.join(dir, 'touchDesigner', 'engine_input_block1.toe'))) return dir;
    const up = path.dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  return null;
}

const ROOT = findRoot();
const TD_DIR = ROOT ? path.join(ROOT, 'touchDesigner') : null;

function inside(child: string, parent: string): boolean {
  const rel = path.relative(parent, child);
  return rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel);
}

function readToken(): string | null {
  if (!TD_DIR) return null;
  try {
    const t = readFileSync(path.join(TD_DIR, 'bridge_token.txt'), 'utf8').trim();
    return t || null;
  } catch {
    return null;
  }
}

function readContract(): ContractInfo | null {
  if (!ROOT) return null;
  try {
    const c = JSON.parse(readFileSync(path.join(ROOT, 'docs', 'contract', 'deckglow.scene-module-1.json'), 'utf8'));
    const slotParameters: Record<string, ControlDecl[]> = {};
    for (const [slot, spec] of Object.entries<any>(c.slots)) {
      slotParameters[slot] = (spec.parameters || []).map((p: any): ControlDecl => {
        const style = String(p.style).toLowerCase();
        const type = style === 'int' ? 'integer' : (style as ControlDecl['type']);
        return {
          parameter: p.name, type,
          min: p.range?.[0], max: p.range?.[1],
          default: p.default, options: p.tokens,
        };
      });
    }
    return {
      slotParameters,
      performer: c.performerControls,
      lanes: (c.lanes || []).map((l: any) => ({ name: l.name, range: l.range, kind: l.kind })),
    };
  } catch {
    return null;
  }
}

function thumbnail(p: unknown): string | null {
  if (typeof p !== 'string' || !TD_DIR) return null;
  const full = path.resolve(p);
  if (!inside(full, TD_DIR) || path.extname(full).toLowerCase() !== '.png') return null;
  try {
    if (statSync(full).size > 4 * 1024 * 1024) return null;
    return 'data:image/png;base64,' + readFileSync(full).toString('base64');
  } catch {
    return null;
  }
}

function checkShow(value: unknown): ShowState {
  if (!value || typeof value !== 'object' || (value as any).schema !== SHOW_SCHEMA) {
    throw new Error(`not a ${SHOW_SCHEMA} show file`);
  }
  return value as ShowState;
}

function registerIpc(win: BrowserWindow): void {
  const config: AppConfig = { url: `ws://127.0.0.1:${PORT}/`, root: ROOT, smoke: !!SMOKE, version: app.getVersion() };
  ipcMain.handle('deckglow:config', () => config);
  ipcMain.handle('deckglow:token', () => readToken());
  ipcMain.handle('deckglow:contract', () => readContract());
  ipcMain.handle('deckglow:thumbnail', (_e, p) => thumbnail(p));
  ipcMain.handle('deckglow:saveShow', async (_e, show) => {
    const s = checkShow(show);
    const r = await dialog.showSaveDialog(win, {
      title: 'Save show',
      defaultPath: path.join(app.getPath('documents'), 'show.deckglow.json'),
      filters: [{ name: 'DeckGlow show', extensions: ['json'] }],
    });
    if (r.canceled || !r.filePath) return null;
    writeFileSync(r.filePath, JSON.stringify(s, null, 2) + '\n', 'utf8');
    return r.filePath;
  });
  ipcMain.handle('deckglow:openShow', async () => {
    const r = await dialog.showOpenDialog(win, {
      title: 'Open show',
      defaultPath: app.getPath('documents'),
      filters: [{ name: 'DeckGlow show', extensions: ['json'] }],
      properties: ['openFile'],
    });
    if (r.canceled || !r.filePaths[0]) return null;
    const file = r.filePaths[0];
    if (statSync(file).size > 1024 * 1024) throw new Error('show file is larger than 1 MB');
    return { path: file, show: checkShow(JSON.parse(readFileSync(file, 'utf8'))) };
  });
  ipcMain.handle('deckglow:smokeDone', async (_e, result: { ok: boolean; steps: string[] }) => {
    if (!SMOKE) return;
    const image = await win.webContents.capturePage();
    const out = path.resolve(SMOKE);
    mkdirSync(path.dirname(out), { recursive: true });
    writeFileSync(out, image.toPNG());
    writeFileSync(out.replace(/\.png$/i, '') + '.json', JSON.stringify(result, null, 2) + '\n', 'utf8');
    console.log(`smoke: ${result.ok ? 'PASS' : 'FAIL'} - ${result.steps.length} steps, screenshot ${out}`);
    for (const s of result.steps) console.log('  ' + s);
    app.exit(result.ok ? 0 : 1);
  });
}

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1440, height: 900, minWidth: 1100, minHeight: 700,
    title: 'DeckGlow', backgroundColor: '#0b0c10', show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, sandbox: true, nodeIntegration: false,
      webSecurity: true, spellcheck: false,
      // A hidden or background window stops painting, and capturePage then returns
      // a stale frame - so the smoke run keeps rendering and shows without focus.
      backgroundThrottling: !SMOKE,
    },
  });
  win.once('ready-to-show', () => (SMOKE ? win.showInactive() : win.show()));
  registerIpc(win);
  // The page may never navigate away or open windows; external links go to the browser.
  win.webContents.on('will-navigate', (e, url) => { if (!url.startsWith('app://deckglow/')) e.preventDefault(); });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) void shell.openExternal(url);
    return { action: 'deny' };
  });
  if (SMOKE) {
    setTimeout(() => { console.log('smoke: FAIL - timed out after 45 s'); app.exit(2); }, 45000);
    win.webContents.on('console-message', (e) => console.log('renderer:', e.message));
  }
  void win.loadURL('app://deckglow/renderer/index.html');
}

app.whenReady().then(() => {
  protocol.handle('app', (request) => {
    const url = new URL(request.url);
    const file = path.normalize(path.join(RENDERER, decodeURIComponent(url.pathname)));
    if (url.host !== 'deckglow' || !inside(file, RENDERER)) return new Response('not found', { status: 404 });
    return net.fetch(pathToFileURL(file).toString());
  });
  // No camera, microphone, notifications or other permissions, ever.
  session.defaultSession.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));
  createWindow();
});

app.on('window-all-closed', () => app.quit());
