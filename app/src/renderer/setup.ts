// Setup: a checklist from a fresh install to a working show. It opens by
// itself on the first run (or when something essential is missing) and from
// the header's Setup button. Rows refresh every 2 s while it is open.
//
//   1 TouchDesigner      installed? (DeckGlow cannot ship it - it has its own licence)
//   2 DeckGlow runtime   copied to Documents\DeckGlow, up to date
//   3 Connected          the project open in TouchDesigner, the app talking to it
//   4 Audio engine       running, and hearing music
//   5 Your name          what the Name layer shows
//   6 Projector          optional: the output window

import type { BridgeClient } from './bridge.js';
import { $, el, toast } from './dom.js';
import type { DeckglowApi, EngineEvent, RuntimeStatus, SetupInfo, ShowState } from '../shared/api.js';

export interface SetupCtx {
  api: DeckglowApi;
  bridge: BridgeClient;
  state: () => ShowState | null;
  status: () => RuntimeStatus | null;
}

type RowState = 'ok' | 'todo' | 'wait' | 'optional';

export function createSetup(ctx: SetupCtx) {
  let info: SetupInfo | null = null;
  let dialog: HTMLDialogElement | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;
  let busy = '';
  let launchedAt = 0;
  let nameInput: HTMLInputElement | null = null;
  const heard = { at: 0 };
  const engineLog: string[] = [];

  // Engine output is only shown (and only while Setup is open). Never refresh
  // per line: the engine prints ~100 readouts a second, and refreshing on each
  // flooded the system with process checks (2026-11-09).
  ctx.api.onEngine((ev: EngineEvent) => {
    if (ev.type === 'log') {
      if (/^Drive:\s/.test(ev.line) && engineLog.length && /^Drive:\s/.test(engineLog[engineLog.length - 1])) engineLog.pop();
      engineLog.push(ev.line);
      if (engineLog.length > 8) engineLog.shift();
      if (dialog?.open) render();
    } else {
      engineLog.push(`engine stopped (exit ${ev.code ?? '-'})`);
      void refresh();
    }
  });

  let refreshing: Promise<void> | null = null;
  function refresh(): Promise<void> {
    refreshing ??= (async () => {
      try {
        info = await ctx.api.setupInfo().catch(() => info);
        renderHeader();
        if (dialog?.open) render();
      } finally {
        refreshing = null;
      }
    })();
    return refreshing;
  }

  /** Called with each status message: notices that the engine is hearing sound. */
  function onStatus(st: RuntimeStatus): void {
    const l = st.lanes ?? {};
    if ((l.body_level ?? 0) > 0.02 || (l.impact_fast ?? 0) > 0.05) heard.at = Date.now();
  }

  const hearing = () => Date.now() - heard.at < 3000 && ctx.state()?.engine.mode === 'live';

  async function act(label: string, fn: () => Promise<unknown>, done?: string): Promise<void> {
    busy = label;
    render();
    try {
      await fn();
      if (done) toast(done, 'info');
    } catch (e) {
      toast((e as Error).message);
    } finally {
      busy = '';
      await refresh();
    }
  }

  function row(n: number, title: string, state: RowState, text: (Node | string)[], actions: (HTMLElement | null)[]): HTMLElement {
    const icon = { ok: '✓', todo: String(n), wait: '…', optional: '·' }[state];
    return el('div', { class: `setup-row setup-${state}`, dataset: { test: `setup-${n}` } },
      el('span', { class: 'setup-icon', text: icon }),
      el('div', { class: 'setup-body' }, el('strong', { text: title }), el('div', { class: 'setup-text' }, ...text)),
      el('div', { class: 'setup-actions' }, ...actions.filter(Boolean) as HTMLElement[]));
  }

  const btn = (label: string, onclick: () => void, primary = false, disabled = false) =>
    el('button', { class: `btn btn-small${primary ? ' btn-primary' : ''}`, text: busy === label ? `${label}…` : label, disabled: disabled || !!busy, onclick });
  const p = (text: string, cls = 'muted small') => el('p', { class: cls, text });
  const link = (href: string, text: string) => el('a', { href, target: '_blank', rel: 'noreferrer', text });

  function render(): void {
    if (!dialog || !info) return;
    const connected = ctx.bridge.isOpen;
    const s = ctx.state();
    const rows: HTMLElement[] = [];

    // 1 TouchDesigner
    const td = info.touchDesigner;
    rows.push(row(1, 'TouchDesigner', td.exe ? 'ok' : 'todo',
      td.exe ? [p(`${td.exe}${td.version ? ` - version ${td.version}` : ''}`)]
        : [p('DeckGlow draws its visuals in TouchDesigner, which is installed separately.', 'small'),
          el('p', { class: 'muted small' }, 'Download it from ', link('https://derivative.ca/download', 'derivative.ca'), ', install it, then come back here.')],
      [btn(td.exe ? 'Change…' : 'Find TouchDesigner.exe…', () => void act('Find', () => ctx.api.browseTouchDesigner()))]));

    // 2 runtime
    const rt = info.mode === 'repository'
      ? row(2, 'DeckGlow runtime', info.installed ? 'ok' : 'todo', [p(`Using the repository checkout at ${info.root}`)], [])
      : !info.installed
        ? row(2, 'DeckGlow runtime', 'todo', [p(`DeckGlow's TouchDesigner project, modules and tools go to ${info.root} - a folder TouchDesigner can write to (your packs, approvals and settings live there).`, 'small')],
          [btn('Install', () => void act('Install', () => ctx.api.installRuntime(), 'DeckGlow runtime installed'), true)])
        : info.updateAvailable
          ? row(2, 'DeckGlow runtime', 'todo', [p(`Version ${info.version ?? '?'} is installed; this app brings ${info.bundledVersion}. Updating replaces the project and first-party modules; your packs, approvals and current show are kept. Close TouchDesigner first.`, 'small')],
            [btn('Update', () => void act('Update', () => update(), 'Runtime updated - open DeckGlow in TouchDesigner; your show comes back once it connects'), true,
              info.touchDesignerRunning)])
          : row(2, 'DeckGlow runtime', 'ok', [p(`${info.root} - version ${info.version ?? '?'}`)], []);
    rows.push(rt);

    // 3 connected
    const starting = !connected && Date.now() - launchedAt < 60000;
    rows.push(row(3, 'DeckGlow open in TouchDesigner', connected ? 'ok' : starting ? 'wait' : 'todo',
      connected ? [p('The app is connected to the runtime.')]
        : starting ? [p('Starting TouchDesigner… the first start can take half a minute.')]
          : info.touchDesignerRunning ? [p('TouchDesigner is running, but not with DeckGlow\'s project - close it and press Open, or open the project yourself.', 'small')]
            : [p('Opens the DeckGlow project in TouchDesigner (with a fresh connection key).', 'small')],
      [connected ? null : btn('Open DeckGlow in TouchDesigner', () => void act('Open', async () => {
        await ctx.api.launchTouchDesigner();
        launchedAt = Date.now();
      }), true, !td.exe || !info.installed || info.updateAvailable)]));

    // 4 audio engine
    const eng = info.engine;
    const live = s?.engine.mode === 'live';
    rows.push(row(4, 'Audio engine', eng.running && hearing() ? 'ok' : eng.running ? 'wait' : 'todo',
      [eng.running
        ? p(hearing() ? 'Running and hearing music.' : live ? 'Running - play some music on this computer; the meters under the preview move with it.' : 'Running - switch the header from Demo beat to Live audio to use it.', 'small')
        : p(eng.exe ? 'Listens to this computer\'s sound output and sends the music\'s energy and beat to TouchDesigner.' : 'ReactiveVisualEngine.exe was not found.', 'small'),
      engineLog.length ? el('pre', { class: 'setup-log' }, engineLog.slice(-4).join('\n')) : ''],
      [eng.running && eng.startedByApp ? btn('Stop', () => void act('Stop', () => ctx.api.stopEngine()))
        : !eng.running ? btn('Start', () => void act('Start', () => ctx.api.startEngine()), true, !eng.exe) : null,
      connected && !live ? btn('Use live audio', () => void act('Live', () => ctx.bridge.request({ type: 'setEngine', mode: 'live' }))) : null]));

    // 5 name (one input for the dialog's life: rows redraw every 2 s while someone types)
    const name = nameInput ??= el('input', { type: 'text', maxlength: 48, placeholder: 'DJ NAME', 'aria-label': 'Your name' });
    if (document.activeElement !== name) name.value = s?.brand.displayName ?? '';
    name.disabled = !connected;
    rows.push(row(5, 'Your name', s?.brand.displayName && s.brand.displayName !== 'DJ NAME' ? 'ok' : 'optional',
      [p('What the Name layer shows. Change it any time in the Name card.', 'small'), name],
      [btn('Set', () => void act('Set', () => ctx.bridge.request({ type: 'setBrand', displayName: name.value.trim() || 'DJ NAME' }), 'Name set'), false, !connected)]));

    // 6 projector
    rows.push(row(6, 'Projector', 'optional', [p('Put the output on the projector or second screen: a window you can drag there, or TouchDesigner\'s Perform Mode (recommended for shows). Escape closes it.', 'small')],
      [btn('Window', () => void act('Window', () => ctx.bridge.request({ type: 'projector', action: 'open' })), false, !connected),
        btn('Perform', () => void act('Perform', () => ctx.bridge.request({ type: 'projector', action: 'perform' })), false, !connected)]));

    const body = dialog.querySelector('.setup-rows')!;
    body.replaceChildren(...rows);
  }

  async function update(): Promise<void> {
    if (ctx.bridge.isOpen) {                    // keep the show: restored after the next connect
      const show = (await ctx.bridge.request<any>({ type: 'getState' })).state;
      const all = await ctx.api.getSettings();
      await ctx.api.setSettings({ ...all, pendingRestore: show } as any);
    }
    await ctx.api.updateRuntime();
  }

  /** After connecting: put back a show saved before a runtime update. */
  async function restorePending(): Promise<void> {
    const all = await ctx.api.getSettings().catch(() => ({} as any));
    const show = (all as any).pendingRestore;
    if (!show) return;
    try {
      const r = await ctx.bridge.request<any>({ type: 'applyShow', show });
      toast(r.problems?.length ? `Show restored after the update, with ${r.problems.length} problem(s): ${r.problems.join('; ')}` : 'Show restored after the update', 'info');
      const next = { ...all };
      delete (next as any).pendingRestore;
      await ctx.api.setSettings(next);
    } catch (e) {
      toast(`Could not restore the show after the update: ${(e as Error).message}`);
    }
  }

  function open(): void {
    if (dialog?.open) return;
    dialog = el('dialog', { class: 'wide setup-dialog', dataset: { test: 'setup-dialog' } },
      el('h3', { text: 'Set up DeckGlow' }),
      el('p', { class: 'muted small', text: 'Work down the list. Each step turns green when it is done; the last two are optional.' }),
      el('div', { class: 'setup-rows' }),
      el('p', { class: 'hint', text: 'DeckGlow needs TouchDesigner, which has its own licence: the free Non-Commercial licence is for non-commercial use and limits the output to 1280×720 - paid shows need a Commercial licence.' }),
      el('div', { class: 'row end' },
        el('button', { class: 'btn', text: 'Close', onclick: () => dialog?.close() })));
    dialog.addEventListener('close', () => {
      if (timer) clearInterval(timer);
      timer = null;
      void ctx.api.getSettings().then((all) => ctx.api.setSettings({ ...all, setupSeen: true } as any)).catch(() => undefined);
      dialog?.remove();
      dialog = null;
      nameInput = null;
    });
    document.body.append(dialog);
    dialog.showModal();
    void refresh();
    timer = setInterval(() => { if (!document.hidden) void refresh(); }, 2000);
  }

  // ------------------------------------------------------------- header
  function renderHeader(): void {
    const b = $<HTMLButtonElement>('engine-toggle');
    if (!info) return;
    const running = info.engine.running;
    b.textContent = running ? 'Engine on' : 'Engine off';
    b.setAttribute('aria-pressed', String(running));
    b.title = running ? (info.engine.startedByApp ? 'The audio engine is running - click to stop it' : 'The audio engine is running (started outside the app)')
      : info.engine.exe ? 'Start the audio engine (listens to this computer\'s sound)' : 'ReactiveVisualEngine.exe not found - see Setup';
    b.disabled = running ? !info.engine.startedByApp : !info.engine.exe;
    $('setup-open').classList.toggle('needs-attention', !info.installed || !info.touchDesigner.exe || info.updateAvailable);
  }

  async function setup(autoOpen = true): Promise<void> {
    $('setup-open').addEventListener('click', open);
    $('engine-toggle').addEventListener('click', () => {
      if (!info) return;
      void (info.engine.running ? ctx.api.stopEngine() : ctx.api.startEngine()).catch((e: Error) => toast(e.message)).finally(() => void refresh());
    });
    await refresh();
    // the header's Engine button and Setup reminder; nothing to update while hidden
    setInterval(() => { if (!document.hidden) void refresh(); }, 10000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh(); });
    const all = await ctx.api.getSettings().catch(() => ({} as any));
    if (autoOpen && info && (!(all as any).setupSeen || !info.installed || !info.touchDesigner.exe || info.updateAvailable)) open();
  }

  return { setup, open, onStatus, restorePending, refresh, get info() { return info; } };
}
