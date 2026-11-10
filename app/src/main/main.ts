// DeckGlow desktop app - main process.
//
// The renderer is a sandboxed page served from app://deckglow/ (never file://).
// It talks to the TouchDesigner runtime directly over the deckglow.control/1
// WebSocket; this process only does what a page must not: read the bridge
// token and module thumbnails from disk, show file dialogs, run pack_tool.py,
// install the runtime, and start TouchDesigner and the audio engine.

import { app, BrowserWindow, dialog, ipcMain, net, protocol, session, shell } from 'electron';
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFile } from 'node:child_process';
import { Runtime } from './runtime';
import type { AppConfig, AppSettings, ContractInfo, ControlDecl, PackResult, ShowState } from '../shared/api';

const SHOW_SCHEMA = 'deckglow.show/1';
const RENDERER = path.join(__dirname, '..', 'web');   // dist/web: renderer/ and shared/
const PORT = Number(process.env.DECKGLOW_PORT || 9980);
const SMOKE = process.argv.find((a) => a.startsWith('--smoke='))?.slice('--smoke='.length) ?? null;
// --smoke-pack=<file.dgpack>: the smoke run also installs and removes this pack, as if picked
const SMOKE_PACK = SMOKE ? process.argv.find((a) => a.startsWith('--smoke-pack='))?.slice('--smoke-pack='.length) ?? null : null;

protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true } },
]);

// ------------------------------------------------------------ settings
// The MIDI mapping and other per-computer choices; DECKGLOW_SETTINGS for tests.
const SETTINGS_FILE = process.env.DECKGLOW_SETTINGS || path.join(app.getPath('userData'), 'settings.json');

function readSettings(): AppSettings & Record<string, any> {
  try {
    const v = JSON.parse(readFileSync(SETTINGS_FILE, 'utf8'));
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {};
  } catch {
    return {};
  }
}

function writeSettings(value: Record<string, unknown>): void {
  const text = JSON.stringify(value ?? {}, null, 2);
  if (!value || typeof value !== 'object' || Array.isArray(value) || text.length > 256 * 1024) throw new Error('settings must be a small object');
  mkdirSync(path.dirname(SETTINGS_FILE), { recursive: true });
  writeFileSync(SETTINGS_FILE, text + '\n', 'utf8');
}

// The runtime folder (repository in development, Documents\DeckGlow once
// installed) can change while the app runs - setup installs it - so every use
// asks the Runtime instead of keeping a path from startup.
const runtime = new Runtime(readSettings);
const rootDir = () => runtime.root;
const tdDir = () => runtime.tdDir;

function inside(child: string, parent: string): boolean {
  const rel = path.relative(parent, child);
  return rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel);
}

function readToken(): string | null {
  const td = tdDir();
  if (!td) return null;
  try {
    const t = readFileSync(path.join(td, 'bridge_token.txt'), 'utf8').trim();
    return t || null;
  } catch {
    return null;
  }
}

function readContract(): ContractInfo | null {
  const root = rootDir();
  if (!root) return null;
  try {
    const c = JSON.parse(readFileSync(path.join(root, 'docs', 'contract', 'deckglow.scene-module-1.json'), 'utf8'));
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
  const td = tdDir();
  if (typeof p !== 'string' || !td) return null;
  const full = path.resolve(p);
  const roots = [td, ...(process.env.DECKGLOW_PACKS ? [path.resolve(process.env.DECKGLOW_PACKS)] : [])];
  if (!roots.some((r) => inside(full, r)) || path.extname(full).toLowerCase() !== '.png') return null;
  try {
    if (statSync(full).size > 4 * 1024 * 1024) return null;
    return 'data:image/png;base64,' + readFileSync(full).toString('base64');
  } catch {
    return null;
  }
}

// ------------------------------------------------------------ packs
const PACK_ID = /^[a-z][a-z0-9]*(\.[a-z0-9][a-z0-9_-]*)+$/;
const pickedPacks = new Set<string>();      // only these files may be inspected or installed

/** pack_tool.py runs on TouchDesigner's own Python, next to its toeexpand. */
function tdTools(): { python: string; toeexpand: string | null } {
  const exe = runtime.touchDesignerExe();
  const bin = exe ? path.dirname(exe) : null;
  const py = [process.env.DECKGLOW_PYTHON, bin && path.join(bin, 'python.exe')].find((c) => c && existsSync(c));
  const tx = bin && existsSync(path.join(bin, 'toeexpand.exe')) ? path.join(bin, 'toeexpand.exe') : null;
  return { python: py || (process.platform === 'win32' ? 'python' : 'python3'), toeexpand: tx };
}

function packTool(args: string[]): Promise<PackResult> {
  const td = tdDir();
  if (!td) return Promise.resolve({ ok: false, command: args[0], message: 'the DeckGlow runtime is not installed - open Setup' });
  const tool = path.join(td, 'tools', 'pack_tool.py');
  // DECKGLOW_PACKS: a test install folder (default touchDesigner/Packs, where TD looks)
  const where = process.env.DECKGLOW_PACKS ? ['--packs', process.env.DECKGLOW_PACKS] : [];
  const { python, toeexpand } = tdTools();
  const env = { ...process.env, ...(toeexpand ? { DECKGLOW_TOEEXPAND: toeexpand } : {}) };
  return new Promise((resolve) => {
    execFile(python, ['-I', tool, '--json', ...where, ...args], { timeout: 180000, windowsHide: true, maxBuffer: 8 * 1024 * 1024, env },
      (err, stdout, stderr) => {
        const line = stdout.trim().split(/\r?\n/).pop() || '';
        try {
          resolve(JSON.parse(line) as PackResult);
        } catch {
          resolve({ ok: false, command: args[0], code: 'error',
            message: (err ? `${err.message}. ` : '') + (stderr.trim().split(/\r?\n/).pop() || 'pack_tool.py gave no result') });
        }
      });
  });
}

function registerPack(p: unknown): string | null {
  if (typeof p !== 'string' || !p || path.extname(p).toLowerCase() !== '.dgpack') return null;
  const full = path.resolve(p);
  try {
    if (!statSync(full).isFile()) return null;
  } catch {
    return null;
  }
  pickedPacks.add(full);
  return full;
}

function pickedPack(p: unknown): string {
  if (typeof p !== 'string' || !pickedPacks.has(p)) throw new Error('choose the pack file first');
  return p;
}

function checkShow(value: unknown): ShowState {
  if (!value || typeof value !== 'object' || (value as any).schema !== SHOW_SCHEMA) {
    throw new Error(`not a ${SHOW_SCHEMA} show file`);
  }
  return value as ShowState;
}

function registerIpc(win: BrowserWindow): void {
  const config = (): AppConfig => ({
    url: `ws://127.0.0.1:${PORT}/`, root: rootDir(), smoke: !!SMOKE, version: app.getVersion(),
    smokePack: SMOKE_PACK ? registerPack(SMOKE_PACK) : null,
    // --smoke-setup: only the first-run install, no runtime needed
    smokeSetup: !!SMOKE && process.argv.includes('--smoke-setup'),
    smokeLaunch: !!SMOKE && process.argv.includes('--smoke-launch'),
  });
  ipcMain.handle('deckglow:config', () => config());
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
  ipcMain.handle('deckglow:pickPack', async () => {
    const r = await dialog.showOpenDialog(win, {
      title: 'Install a creator pack',
      defaultPath: app.getPath('downloads'),
      filters: [{ name: 'DeckGlow pack', extensions: ['dgpack'] }],
      properties: ['openFile'],
    });
    return r.canceled || !r.filePaths[0] ? null : registerPack(r.filePaths[0]);
  });
  ipcMain.handle('deckglow:dropPack', (_e, p) => registerPack(p));
  ipcMain.handle('deckglow:inspectPack', (_e, p) => packTool(['verify', pickedPack(p)]));
  ipcMain.handle('deckglow:installPack', (_e, p, force) => packTool(['install', pickedPack(p), ...(force === true ? ['--force'] : [])]));
  ipcMain.handle('deckglow:removePack', (_e, id) => {
    if (typeof id !== 'string' || !PACK_ID.test(id) || id.startsWith('com.deckglow')) throw new Error('not a pack id');
    return packTool(['remove', id]);
  });
  ipcMain.handle('deckglow:listPacks', () => packTool(['list']));
  ipcMain.handle('deckglow:getSettings', () => readSettings());
  ipcMain.handle('deckglow:setSettings', (_e, value) => {
    // the runtime folder and TouchDesigner path are set by setup only
    const keep = readSettings();
    writeSettings({ ...value, runtimeDir: keep.runtimeDir, touchDesignerExe: keep.touchDesignerExe });
  });

  // ------------------------------------------------- setup and launching
  ipcMain.handle('deckglow:setupInfo', () => runtime.info());
  ipcMain.handle('deckglow:installRuntime', () => runtime.install());
  ipcMain.handle('deckglow:updateRuntime', () => runtime.update());
  ipcMain.handle('deckglow:launchTouchDesigner', () => runtime.launchTouchDesigner());
  ipcMain.handle('deckglow:browseTouchDesigner', async () => {
    const r = await dialog.showOpenDialog(win, {
      title: 'Find TouchDesigner.exe',
      defaultPath: path.join(process.env.ProgramFiles || 'C:/Program Files', 'Derivative'),
      filters: [{ name: 'TouchDesigner', extensions: ['exe'] }],
      properties: ['openFile'],
    });
    const f = r.filePaths?.[0];
    if (r.canceled || !f) return null;
    if (path.basename(f).toLowerCase() !== 'touchdesigner.exe') throw new Error('choose TouchDesigner.exe (in TouchDesigner\'s bin folder)');
    writeSettings({ ...readSettings(), touchDesignerExe: f });
    return f;
  });
  ipcMain.handle('deckglow:startEngine', () => runtime.startEngine());
  ipcMain.handle('deckglow:stopEngine', () => runtime.stopEngine());
  ipcMain.handle('deckglow:engineLog', () => runtime.engineLogTail());
  runtime.onEngine = (ev) => { if (!win.isDestroyed()) win.webContents.send('deckglow:engine', ev); };

  // smoke runs only: drive the window the way a person does, then measure it
  ipcMain.handle('deckglow:smokeWindow', (_e, action: string) => {
    if (!SMOKE) throw new Error('smoke runs only');
    if (action === 'minimize') win.minimize();
    else if (action === 'restore') { win.restore(); win.showInactive(); }
    else if (action === 'maximize') win.maximize();
    else if (action === 'unmaximize') win.unmaximize();
    const b = win.getContentBounds();
    return { width: b.width, height: b.height, minimized: win.isMinimized(), maximized: win.isMaximized() };
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
  // Tell the page when nobody can see it, so it stops the preview and status
  // streams. The page's own document.hidden is not enough: it never changes
  // when backgroundThrottling is off (the smoke run turns it off).
  const visible = (v: boolean) => () => { if (!win.isDestroyed()) win.webContents.send('deckglow:windowVisible', v); };
  win.on('minimize', visible(false));
  win.on('hide', visible(false));
  win.on('restore', visible(true));
  win.on('show', visible(true));
  // The page may never navigate away or open windows; https links go to the browser.
  win.webContents.on('will-navigate', (e, url) => { if (!url.startsWith('app://deckglow/')) e.preventDefault(); });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) void shell.openExternal(url);
    return { action: 'deny' };
  });
  if (SMOKE) {
    const limit = process.argv.includes('--smoke-launch') ? 180 : 60;     // a TouchDesigner cold start is slow
    setTimeout(() => { console.log(`smoke: FAIL - timed out after ${limit} s`); app.exit(2); }, limit * 1000);
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
  // MIDI from the app's own page (a DJ controller) and nothing else: no
  // system-exclusive MIDI, camera, microphone, notifications or the rest.
  const allowed = (perm: string, origin: string, details?: any) =>
    perm === 'midi' && origin.startsWith('app://deckglow') && !details?.sysex;
  session.defaultSession.setPermissionRequestHandler((wc, perm, cb, details) =>
    cb(allowed(perm, (details as any)?.requestingUrl ?? wc.getURL(), details)));
  session.defaultSession.setPermissionCheckHandler((_wc, perm, origin, details) => allowed(perm, origin, details));
  createWindow();
});

// An engine the app started stops with the app; TouchDesigner keeps running.
let quitting = false;
app.on('before-quit', (e) => {
  if (quitting) return;
  quitting = true;
  e.preventDefault();
  void runtime.stopEngine().finally(() => app.quit());
});
app.on('window-all-closed', () => app.quit());
