// Where DeckGlow's TouchDesigner runtime and audio engine live, and how the
// app installs, updates and starts them.
//
// Development (a repository checkout): the runtime is the repository itself
// (touchDesigner/ and docs/ next to app/), the engine is x64/Release (or
// Debug). Installed: the installer ships a read-only copy in
// resources/runtime and resources/engine; setup copies the runtime to a
// folder TouchDesigner can write to (Documents\DeckGlow by default) - packs,
// approvals, validation reports and the bridge token are written there.

import { app } from 'electron';
import { execFile, spawn, type ChildProcess } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, statSync, writeFileSync } from 'node:fs';
import * as path from 'node:path';
import { LineGate, isReadout } from './linegate';

export interface RuntimeInfo {
  mode: 'repository' | 'installed' | 'custom';
  root: string | null;              // the folder holding touchDesigner/ and docs/
  installed: boolean;               // installed mode: has setup copied the runtime yet
  version: string | null;           // runtime.json of the root
  bundledVersion: string | null;    // runtime.json shipped with this app
  updateAvailable: boolean;
  project: string | null;           // the .toe
  touchDesigner: { exe: string | null; version: string | null };
  touchDesignerRunning: boolean;
  engine: { exe: string | null; running: boolean; startedByApp: boolean };
  processChecks: number;
}

const PROJECT = path.join('touchDesigner', 'engine_input_block1.toe');
const BUNDLED = app.isPackaged ? path.join(process.resourcesPath, 'runtime') : null;
const DEFAULT_RUNTIME = path.join(app.getPath('documents'), 'DeckGlow');

// --- what an update replaces, and what it keeps (the person's data) ---------
// Replaced: the program - tools, first-party modules, docs, examples, the
// project file (after the app has saved the show, so it can be restored).
// Kept: Packs/ (installed creator packs), library/approved.json (approvals;
// first-party entries are refreshed from the bundle), validation/ reports of
// packs, the bridge token, anything else the person added.
const REPLACE = ['touchDesigner/tools', 'touchDesigner/modules', 'touchDesigner/examples', 'docs'];

function readJson(file: string): any {
  try {
    return JSON.parse(readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

function repoRoot(): string | null {
  let dir = app.getAppPath();
  for (let i = 0; i < 6; i++) {
    if (existsSync(path.join(dir, PROJECT)) && existsSync(path.join(dir, 'app', 'package.json'))) return dir;
    const up = path.dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  return null;
}

/** semver-ish compare of "1.2.3" strings. */
export function cmpVersion(a: string | null, b: string | null): number {
  const pa = (a || '0').split(/[.+-]/).map((x) => Number(x) || 0), pb = (b || '0').split(/[.+-]/).map((x) => Number(x) || 0);
  for (let i = 0; i < 3; i++) if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) - (pb[i] || 0);
  return 0;
}

export class Runtime {
  private engineProc: ChildProcess | null = null;
  private engineLog: string[] = [];
  private tdVersionCache = new Map<string, string | null>();
  onEngine: (ev: { type: 'log'; line: string } | { type: 'exit'; code: number | null }) => void = () => undefined;

  constructor(private settings: () => Record<string, any>) {}

  get root(): string | null {
    const env = process.env.DECKGLOW_ROOT;
    if (env && existsSync(path.join(env, 'touchDesigner'))) return path.resolve(env);
    if (!app.isPackaged) return repoRoot();
    const dir = this.settings().runtimeDir || process.env.DECKGLOW_RUNTIME_DIR || DEFAULT_RUNTIME;
    return dir;
  }

  get mode(): RuntimeInfo['mode'] {
    if (process.env.DECKGLOW_ROOT) return 'custom';
    return app.isPackaged ? 'installed' : 'repository';
  }

  get tdDir(): string | null {
    const r = this.root;
    return r && existsSync(path.join(r, PROJECT)) ? path.join(r, 'touchDesigner') : null;
  }

  // ------------------------------------------------------------ discovery
  touchDesignerExe(): string | null {
    const s = this.settings().touchDesignerExe;
    for (const c of [process.env.DECKGLOW_TD, s]) if (c && existsSync(c)) return c;
    const base = path.join(process.env.ProgramFiles || 'C:/Program Files', 'Derivative');
    const found = [path.join(base, 'TouchDesigner', 'bin', 'TouchDesigner.exe')];
    try {
      for (const d of readdirSync(base).filter((d) => d.startsWith('TouchDesigner')).sort().reverse()) {
        found.push(path.join(base, d, 'bin', 'TouchDesigner.exe'));
      }
    } catch { /* no Derivative folder */ }
    return found.find((f) => existsSync(f)) ?? null;
  }

  /** TouchDesigner's file version, e.g. "2025.32280" (Windows file properties). */
  touchDesignerVersion(exe: string | null): Promise<string | null> {
    if (!exe) return Promise.resolve(null);
    if (this.tdVersionCache.has(exe)) return Promise.resolve(this.tdVersionCache.get(exe)!);
    return new Promise((resolve) => {
      execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
        `(Get-Item -LiteralPath '${exe.replace(/'/g, "''")}').VersionInfo.ProductVersion`],
      { windowsHide: true, timeout: 15000 }, (err, out) => {
        const v = err ? null : out.trim() || null;
        this.tdVersionCache.set(exe, v);
        resolve(v);
      });
    });
  }

  engineExe(): string | null {
    const c: string[] = [];
    if (process.env.DECKGLOW_ENGINE) c.push(process.env.DECKGLOW_ENGINE);
    if (app.isPackaged) c.push(path.join(process.resourcesPath, 'engine', 'ReactiveVisualEngine.exe'));
    const repo = repoRoot();
    if (repo) c.push(path.join(repo, 'x64', 'Release', 'ReactiveVisualEngine.exe'), path.join(repo, 'x64', 'Debug', 'ReactiveVisualEngine.exe'));
    return c.find((f) => existsSync(f)) ?? null;
  }

  // One tasklist for every question, never two at once, and reused for 2 s:
  // checking each program with its own tasklist, on every refresh, is how
  // hundreds of them piled up (see linegate.ts).
  private procCache: { at: number; names: Set<string> } | null = null;
  private procInflight: Promise<Set<string>> | null = null;
  /** tasklist processes started so far - the smoke test checks this stays small */
  processChecks = 0;

  private processes(fresh = false): Promise<Set<string>> {
    if (!fresh && this.procCache && Date.now() - this.procCache.at < 2000) return Promise.resolve(this.procCache.names);
    if (this.procInflight) return this.procInflight;
    this.processChecks++;
    this.procInflight = new Promise((resolve) => {
      execFile('tasklist.exe', ['/NH', '/FO', 'CSV'], { windowsHide: true, timeout: 10000, maxBuffer: 8 * 1024 * 1024 },
        (err, out) => {
          const names = new Set<string>();
          if (!err) for (const line of out.split(/\r?\n/)) {
            const m = /^"([^"]+)"/.exec(line);
            if (m) names.add(m[1].toLowerCase());
          }
          this.procCache = { at: Date.now(), names };      // a failure is cached too: no retry storm
          this.procInflight = null;
          resolve(names);
        });
    });
    return this.procInflight;
  }

  private async running(image: string, fresh = false): Promise<boolean> {
    return (await this.processes(fresh)).has(image.toLowerCase());
  }

  async info(): Promise<RuntimeInfo> {
    const root = this.root;
    const version = root ? readJson(path.join(root, 'runtime.json'))?.version ?? null : null;
    const bundledVersion = BUNDLED ? readJson(path.join(BUNDLED, 'runtime.json'))?.version ?? null : null;
    const installed = !!this.tdDir;
    const exe = this.touchDesignerExe();
    const [tdRunning, engineRunning, tdVersion] = await Promise.all([
      this.running('TouchDesigner.exe'), this.running('ReactiveVisualEngine.exe'), this.touchDesignerVersion(exe)]);
    return {
      mode: this.mode, root, installed, version, bundledVersion,
      updateAvailable: this.mode === 'installed' && installed && !!bundledVersion && cmpVersion(bundledVersion, version) > 0,
      project: installed ? path.join(root!, PROJECT) : null,
      touchDesigner: { exe, version: tdVersion },
      touchDesignerRunning: tdRunning,
      // our own engine is known without asking Windows (and without a stale list)
      engine: { exe: this.engineExe(), running: !!this.engineProc || engineRunning, startedByApp: !!this.engineProc },
      processChecks: this.processChecks,
    };
  }

  // ------------------------------------------------------- install/update
  /** First run (installed app): copy the bundled runtime to the runtime folder. */
  install(): string {
    if (!BUNDLED || !existsSync(BUNDLED)) throw new Error('this app has no bundled runtime (development checkout)');
    const root = this.root!;
    if (existsSync(path.join(root, PROJECT))) throw new Error(`a DeckGlow runtime is already in ${root}`);
    mkdirSync(root, { recursive: true });
    cpSync(BUNDLED, root, { recursive: true });
    return root;
  }

  /** Replace the program parts with the bundled ones, keeping the person's data. TouchDesigner must be closed. */
  async update(): Promise<{ root: string; backup: string }> {
    if (!BUNDLED) throw new Error('this app has no bundled runtime (development checkout)');
    if (await this.running('TouchDesigner.exe', true)) throw new Error('close TouchDesigner first - it would overwrite the new project when it saves');
    const root = this.root!;
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const backup = path.join(root, 'backups', `runtime-${stamp}`);
    mkdirSync(backup, { recursive: true });
    for (const rel of [...REPLACE, PROJECT, 'runtime.json']) {
      const from = path.join(root, rel), fresh = path.join(BUNDLED, rel);
      if (!existsSync(fresh)) continue;
      if (existsSync(from)) renameSync(from, path.join(backup, rel.replace(/[\\/]/g, '__')));
      cpSync(fresh, from, { recursive: true });
    }
    // approvals: the person's own, with the bundle's first-party entries refreshed
    const mine = readJson(path.join(root, 'touchDesigner', 'library', 'approved.json')) ?? { approved: {} };
    const theirs = readJson(path.join(BUNDLED, 'touchDesigner', 'library', 'approved.json')) ?? { approved: {} };
    for (const [id, a] of Object.entries<any>(theirs.approved || {})) if (id.startsWith('com.deckglow.')) (mine.approved ||= {})[id] = a;
    mkdirSync(path.join(root, 'touchDesigner', 'library'), { recursive: true });
    writeFileSync(path.join(root, 'touchDesigner', 'library', 'approved.json'), JSON.stringify(mine, null, 2) + '\n');
    // first-party validation reports from the bundle; pack reports stay
    const vdir = path.join(BUNDLED, 'touchDesigner', 'validation');
    if (existsSync(vdir)) cpSync(vdir, path.join(root, 'touchDesigner', 'validation'), { recursive: true });
    return { root, backup };
  }

  // ------------------------------------------------------- TouchDesigner
  /** Open the project in TouchDesigner, with a fresh bridge token written first
   *  (FRONTEND_MESSAGE_CONTRACT s2). If TouchDesigner is already running the
   *  token is left alone: its bridge read the current one when it started. */
  async launchTouchDesigner(): Promise<{ rotatedToken: boolean }> {
    const exe = this.touchDesignerExe();
    if (!exe) throw new Error('TouchDesigner was not found - install it, or choose TouchDesigner.exe in setup');
    const td = this.tdDir;
    if (!td) throw new Error('the DeckGlow runtime is not installed yet');
    const running = await this.running('TouchDesigner.exe', true);
    if (!running) writeFileSync(path.join(td, 'bridge_token.txt'), randomBytes(24).toString('base64url'));
    const child = spawn(exe, [path.join(td, 'engine_input_block1.toe')], { detached: true, stdio: 'ignore', cwd: td });
    child.unref();
    return { rotatedToken: !running };
  }

  // -------------------------------------------------------------- engine
  async startEngine(): Promise<void> {
    if (this.engineProc) return;
    if (await this.running('ReactiveVisualEngine.exe', true)) throw new Error('the audio engine is already running (started outside the app)');
    const exe = this.engineExe();
    if (!exe) throw new Error('the audio engine (ReactiveVisualEngine.exe) was not found');
    const p = spawn(exe, [], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], cwd: path.dirname(exe) });
    this.engineProc = p;
    this.procCache = null;                   // the process list just changed
    // ~100 readout lines a second: collapsed and sent at most twice a second
    const gate = new LineGate((l) => {
      if (isReadout(l) && this.engineLog.length && isReadout(this.engineLog[this.engineLog.length - 1])) this.engineLog.pop();
      this.engineLog.push(l);
      if (this.engineLog.length > 50) this.engineLog.shift();
      this.onEngine({ type: 'log', line: l });
    });
    // Output arrives in arbitrary chunks: keep the unfinished end of each chunk
    // until its line ends, or half a readout would pass the gate as a message.
    let partial = '';
    const onData = (buf: Buffer) => {
      const parts = (partial + buf.toString('utf8')).split(/[\r\n]+/);
      partial = parts.pop() ?? '';
      if (partial.length > 4096) partial = '';           // a line that never ends
      for (const line of parts) {
        const l = line.trim();
        if (l) gate.push(l);
      }
    };
    p.stdout?.on('data', onData);
    p.stderr?.on('data', onData);
    p.on('exit', (code) => {
      gate.flush();
      if (this.engineProc === p) this.engineProc = null;
      this.procCache = null;
      this.onEngine({ type: 'exit', code });
    });
  }

  stopEngine(): Promise<void> {
    const p = this.engineProc;
    if (!p) return Promise.resolve();
    return new Promise((resolve) => {
      const done = () => { clearTimeout(t); resolve(); };
      p.once('exit', done);
      try { p.stdin?.write('\n'); } catch { /* already closing */ }   // the engine quits on Enter
      const t = setTimeout(() => { p.kill(); }, 2500);
    });
  }

  engineLogTail(): string[] {
    return [...this.engineLog];
  }
}

export function fileExists(p: string): boolean {
  try {
    return statSync(p).isFile();
  } catch {
    return false;
  }
}
