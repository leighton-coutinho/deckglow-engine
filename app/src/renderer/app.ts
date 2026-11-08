// DeckGlow desktop app - the control surface.
//
// Everything here is a view of the runtime's show state: controls send named
// requests over deckglow.control/1 and are redrawn from the `state` the
// runtime broadcasts back, so the screen always shows what TouchDesigner is
// actually doing - also when another window or a show file changed it.

import { BridgeClient, BridgeRequestError, type Connection } from './bridge.js';
import { $, el, toast } from './dom.js';
import { createLibrary } from './library.js';
import { createLooks } from './looks.js';
import { createMidi } from './midi.js';
import { createSetup } from './setup.js';
import { api } from './platform.js';
import { runSetupSmoke, runSmoke } from './smoke.js';
import { CONFIRM_STROBE, SLOTS } from '../shared/api.js';
import type {
  ContractInfo, ControlDecl, ControlValue, Library, LibraryModule, RuntimeStatus, ShowState, SlotName,
} from '../shared/api.js';

// ------------------------------------------------------------------ labels
const SLOT_INFO: Record<SlotName, { title: string; hint: string }> = {
  base_scene: { title: 'Scene', hint: 'The moving background' },
  hit_fx: { title: 'Hits', hint: 'Effects on every hit' },
  brand_overlay: { title: 'Name', hint: 'Your name or logo' },
  finish_fx: { title: 'Finish', hint: 'Final look for the projector' },
};
const PERFORMER_LABELS: Record<string, [string, string]> = {
  masterIntensity: ['Master', 'Everything that reacts to the music'],
  motionAmount: ['Motion', 'How far things drift'],
  flashAmount: ['Flash', 'How hard hits flash'],
  textureAmount: ['Texture', 'Grain and shimmer'],
  toneAmount: ['Mood', 'Warm/cool and soft/sharp from the music'],
  brandAmount: ['Name pulse', 'How much the name pulses'],
};
const PARAM_LABELS: Record<string, string> = {
  Fxamount: 'Amount', Blendmode: 'Blend', Colorize: 'Palette colour', Logoopacity: 'Logo opacity',
  Nameopacity: 'Name opacity', Placement: 'Placement', Safearea: 'Margin', Contrast: 'Contrast',
  Brightness: 'Brightness', Softness: 'Softness', Outputclamp: 'Clamp to safe range',
};
const OPTION_LABELS: Record<string, string> = {
  over: 'Over', add: 'Add', screen: 'Screen', center: 'Centre', top_left: 'Top left',
  top_right: 'Top right', bottom_left: 'Bottom left', bottom_right: 'Bottom right',
};

// ------------------------------------------------------------------ helpers
/** Calls fn at most every `ms`, always delivering the last value. */
function throttle<A extends unknown[]>(fn: (...a: A) => void, ms: number): (...a: A) => void {
  let last = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pendingArgs: A | null = null;
  return (...a: A) => {
    pendingArgs = a;
    const wait = ms - (Date.now() - last);
    if (wait <= 0) {
      last = Date.now();
      fn(...a);
      pendingArgs = null;
    } else if (!timer) {
      timer = setTimeout(() => {
        timer = null;
        last = Date.now();
        if (pendingArgs) fn(...pendingArgs);
        pendingArgs = null;
      }, wait);
    }
  };
}

/** True while the user holds or types into an element - state updates leave it alone. */
const busy = new WeakSet<Element>();
function trackBusy(input: HTMLElement): void {
  input.addEventListener('pointerdown', () => busy.add(input));
  input.addEventListener('focus', () => { if (input instanceof HTMLInputElement && input.type === 'text') busy.add(input); });
  const release = () => setTimeout(() => busy.delete(input), 250);
  input.addEventListener('pointerup', release);
  input.addEventListener('pointercancel', release);
  input.addEventListener('blur', release);
}

const hex = (rgb: number[]) => '#' + rgb.map((c) => Math.round(Math.max(0, Math.min(1, c)) * 255).toString(16).padStart(2, '0')).join('');
const rgbOf = (h: string): [number, number, number] =>
  [1, 3, 5].map((i) => Math.round((parseInt(h.slice(i, i + 2), 16) / 255) * 1000) / 1000) as [number, number, number];
const fmt = (v: number, step: number) => (step >= 1 ? String(Math.round(v)) : v.toFixed(step >= 0.1 ? 1 : 2));

// --------------------------------------------------------------- the app
let bridge: BridgeClient;
let contract: ContractInfo | null = null;
let library: Library = { modules: [], palettes: [] };
let state: ShowState | null = null;
let libraryPanel: ReturnType<typeof createLibrary>;
let looksPanel: ReturnType<typeof createLooks>;
let midi: ReturnType<typeof createMidi>;
let setupPanel: ReturnType<typeof createSetup> | undefined;
let lastStatus: RuntimeStatus | null = null;

async function send(msg: Record<string, unknown>, quiet = false): Promise<any> {
  try {
    return await bridge.request(msg);
  } catch (e) {
    if (!quiet) {
      const err = e as BridgeRequestError;
      toast(err.code === 'offline' ? 'Not connected to TouchDesigner' : err.message);
    }
    throw e;
  }
}
const fire = (msg: Record<string, unknown>) => { send(msg).catch(() => undefined); };

// A slider row: label, range input, value readout.
interface SliderSpec {
  key: string; label: string; hint?: string; min: number; max: number; step: number;
  get: (s: ShowState) => number | undefined; set: (v: number) => void; test?: string;
}
function slider(spec: SliderSpec) {
  const input = el('input', { type: 'range', min: spec.min, max: spec.max, step: spec.step, 'aria-label': spec.label, dataset: spec.test ? { test: spec.test } : undefined });
  const out = el('output', { class: 'value' });
  const send = throttle(spec.set, 60);
  input.addEventListener('input', () => { out.textContent = fmt(Number(input.value), spec.step); send(Number(input.value)); });
  trackBusy(input);
  const row = el('div', { class: 'slider', title: spec.hint }, el('span', { class: 'slider-label', text: spec.label }), input, out);
  const update = (s: ShowState) => {
    const v = spec.get(s);
    if (v === undefined || busy.has(input)) return;
    input.value = String(v);
    out.textContent = fmt(v, spec.step);
  };
  return { row, update };
}

const updaters: ((s: ShowState) => void)[] = [];

// -------------------------------------------------------------- header
function setupHeader(): void {
  for (const b of document.querySelectorAll<HTMLButtonElement>('#engine-mode button')) {
    b.addEventListener('click', () => fire({ type: 'setEngine', mode: b.dataset.mode, bpm: Number($<HTMLInputElement>('engine-bpm').value) || 120 }));
  }
  const bpm = $<HTMLInputElement>('engine-bpm');
  trackBusy(bpm);
  bpm.addEventListener('change', () => {
    const v = Math.max(40, Math.min(240, Math.round(Number(bpm.value) || 120)));
    bpm.value = String(v);
    fire({ type: 'setEngine', mode: state?.engine.mode ?? 'demo', bpm: v });
  });
  for (const b of document.querySelectorAll<HTMLButtonElement>('[data-projector]')) {
    b.addEventListener('click', () => fire({ type: 'projector', action: b.dataset.projector }));
  }
  const blackout = $<HTMLButtonElement>('blackout');
  blackout.addEventListener('click', () => fire({ type: 'setOutput', blackout: !(state?.output.blackout) }));
  document.addEventListener('keydown', (e) => {
    const t = e.target as HTMLElement;
    if (e.key.toLowerCase() === 'b' && !e.ctrlKey && !e.metaKey && !(t instanceof HTMLInputElement) && !(t instanceof HTMLSelectElement)) blackout.click();
  });
  updaters.push((s) => {
    for (const b of document.querySelectorAll<HTMLButtonElement>('#engine-mode button')) {
      b.setAttribute('aria-checked', String(b.dataset.mode === s.engine.mode));
    }
    if (!busy.has(bpm) && s.engine.bpm) bpm.value = String(Math.round(s.engine.bpm));
    bpm.disabled = s.engine.mode !== 'demo';
    blackout.setAttribute('aria-pressed', String(!!s.output.blackout));
    $('badge-blackout').hidden = !s.output.blackout;
  });
}

function showConnection(c: Connection): void {
  const pill = $('connection');
  const texts: Record<Connection['phase'], string> = {
    connecting: 'Connecting…', open: 'Connected', offline: 'TouchDesigner offline',
    'auth-failed': 'Token refused', stopped: 'Stopped',
  };
  // no token file at all means nothing is set up yet, not a refused key
  pill.textContent = c.phase === 'auth-failed' && /no bridge token/.test(c.reason) ? 'Not set up' : texts[c.phase];
  pill.className = 'pill ' + (c.phase === 'open' ? 'pill-ok' : c.phase === 'connecting' ? 'pill-wait' : 'pill-bad');
  pill.title = 'reason' in c ? `${c.reason} - retrying in ${(c.retryInMs / 1000).toFixed(1)} s` : '';
  document.body.classList.toggle('offline', c.phase !== 'open');
  if (c.phase !== 'open') $('fps').textContent = '';
}

// --------------------------------------------------------------- layers
function controlDecls(slot: SlotName, mod: LibraryModule | undefined): ControlDecl[] {
  const slotParams = (contract?.slotParameters[slot] ?? []).map((d) => ({ ...d, label: PARAM_LABELS[d.parameter] ?? d.parameter }));
  return [...slotParams, ...(mod?.controls ?? [])];
}

function controlInput(slot: SlotName, d: ControlDecl): { node: HTMLElement; update: (s: ShowState) => void } {
  const label = d.label ?? d.parameter;
  const current = (s: ShowState): ControlValue | undefined => s.slots[slot]?.controls?.[d.parameter] ?? d.default;
  const setVal = (value: ControlValue) => fire({ type: 'setControl', slot, parameter: d.parameter, value });
  if (d.type === 'float' || d.type === 'integer') {
    const step = d.type === 'integer' ? 1 : ((d.max ?? 1) - (d.min ?? 0)) / 100;
    const s = slider({
      key: d.parameter, label, min: d.min ?? 0, max: d.max ?? 1, step,
      get: (st) => current(st) as number | undefined,
      set: (v) => setVal(d.type === 'integer' ? Math.round(v) : Math.round(v * 10000) / 10000),
    });
    return { node: s.row, update: s.update };
  }
  if (d.type === 'toggle') {
    const box = el('input', { type: 'checkbox', onchange: () => setVal(box.checked) });
    const node = el('label', { class: 'switch' }, box, el('span', { class: 'track' }), el('span', { text: label }));
    return { node, update: (s) => { box.checked = !!current(s); } };
  }
  if (d.type === 'menu') {
    const sel = el('select', { 'aria-label': label, onchange: () => { if (sel.value) setVal(sel.value); } },
      d.default === undefined ? el('option', { value: '', text: 'Module default' }) : null,
      ...(d.options ?? []).map((o) => el('option', { value: o, text: OPTION_LABELS[o] ?? o })));
    return { node: el('div', { class: 'row' }, el('span', { class: 'field-label', text: label }), sel), update: (s) => { sel.value = String(current(s) ?? ''); } };
  }
  // colour
  const pick = el('input', { type: 'color', 'aria-label': label });
  const sendColour = throttle((v: string) => setVal(rgbOf(v)), 80);
  pick.addEventListener('input', () => sendColour(pick.value));
  trackBusy(pick);
  return {
    node: el('div', { class: 'row' }, el('span', { class: 'field-label', text: label }), pick),
    update: (s) => { const v = current(s); if (Array.isArray(v) && !busy.has(pick)) pick.value = hex(v); },
  };
}

let slotKeys: Record<string, string> = {};
const slotUpdaters: Record<string, ((s: ShowState) => void)[]> = {};

function renderSlots(s: ShowState): void {
  const host = $('slots');
  for (const slot of SLOTS) {
    const st = s.slots[slot];
    const mod = library.modules.find((m) => m.id === st?.module);
    const key = `${st?.module}|${library.modules.length}|${!!contract}`;
    if (slotKeys[slot] === key) continue;
    slotKeys[slot] = key;
    const ups: ((s: ShowState) => void)[] = [];

    const enabled = el('input', { type: 'checkbox', dataset: { test: `slot-${slot}-enabled` }, onchange: () => fire({ type: 'setSlotEnabled', slot, enabled: enabled.checked }) });
    ups.push((x) => { enabled.checked = !!x.slots[slot]?.enabled; });

    const choices = library.modules.filter((m) => m.type === slot && m.approved === 'yes');
    const select = el('select', { 'aria-label': `${SLOT_INFO[slot].title} module`, dataset: { test: `slot-${slot}-module` } },
      el('option', { value: '', text: '— Empty —' }),
      ...choices.map((m) => el('option', { value: m.id, text: m.displayName })),
      st?.module && !choices.some((m) => m.id === st.module) ? el('option', { value: st.module, text: `${st.module} (not in the approved library)` }) : null);
    select.value = st?.module ?? '';
    select.addEventListener('change', async () => {
      select.disabled = true;
      try {
        await send({ type: 'setSlotModule', slot, module: select.value || null });
      } catch {
        select.value = bridge.state?.slots[slot]?.module ?? '';
      } finally {
        select.disabled = false;
      }
    });

    const status = el('span', { class: 'slot-status muted small', dataset: { slotStatus: slot } });
    const intensity = slider({
      key: 'intensity', label: 'Intensity', min: 0, max: 1, step: 0.01, test: `slot-${slot}-intensity`,
      get: (x) => x.slots[slot]?.intensity, set: (v) => fire({ type: 'setSlotIntensity', slot, value: v }),
    });
    ups.push(intensity.update);

    const controls = mod ? controlDecls(slot, mod).map((d) => controlInput(slot, d)) : [];
    for (const c of controls) ups.push(c.update);
    const reset = mod && el('button', {
      class: 'btn btn-quiet btn-small', text: 'Reset controls', title: 'Reload the module with its default controls',
      onclick: () => fire({ type: 'setSlotModule', slot, module: mod.id }),
    });
    const details = controls.length ? el('details', { class: 'controls' },
      el('summary', { text: `Controls (${controls.length})` }),
      el('div', { class: 'sliders' }, ...controls.map((c) => c.node)), reset) : null;

    const card = el('div', { class: 'slot', dataset: { slot } },
      el('div', { class: 'slot-head' },
        el('label', { class: 'switch', title: 'On / off' }, enabled, el('span', { class: 'track' })),
        el('div', { class: 'slot-title' }, el('strong', { text: SLOT_INFO[slot].title }), el('span', { class: 'muted small', text: SLOT_INFO[slot].hint })),
        select),
      el('div', { class: 'slot-body' }, intensity.row, status),
      details);
    const old = host.querySelector(`[data-slot="${slot}"]`);
    const wasOpen = (old?.querySelector('details') as HTMLDetailsElement | null)?.open;
    if (details && wasOpen) (details as HTMLDetailsElement).open = true;
    if (old) old.replaceWith(card); else host.append(card);
    slotUpdaters[slot] = ups;
  }
  for (const slot of SLOTS) for (const u of slotUpdaters[slot] ?? []) u(s);
  for (const slot of SLOTS) {
    host.querySelector(`[data-slot="${slot}"]`)?.classList.toggle('slot-off', !s.slots[slot]?.enabled || !s.slots[slot]?.module);
  }
}

// ---------------------------------------------------------------- colour
function setupColour(): void {
  const palette = $<HTMLSelectElement>('palette');
  palette.addEventListener('change', () => fire({ type: 'setPalette', name: palette.value }));
  const custom = $<HTMLInputElement>('bg-custom');
  const colour = $<HTMLInputElement>('bg-color');
  custom.addEventListener('change', () => fire({ type: 'setBackground', color: custom.checked ? rgbOf(colour.value) : null }));
  const sendColour = throttle((v: string) => fire({ type: 'setBackground', color: rgbOf(v) }), 80);
  colour.addEventListener('input', () => { if (custom.checked) sendColour(colour.value); });
  trackBusy(colour);
  updaters.push((s) => {
    if (palette.options.length !== library.palettes.length) {
      palette.replaceChildren(...library.palettes.map((p) => el('option', { value: p, text: p })));
    }
    if (s.palette.name) palette.value = s.palette.name;
    custom.checked = !!s.background;
    if (s.background && !busy.has(colour)) colour.value = hex(s.background);
  });
}

// ------------------------------------------------------------------ name
function setupBrand(): void {
  const name = $<HTMLInputElement>('brand-name');
  trackBusy(name);
  const commit = () => { if (name.value !== (state?.brand.displayName ?? '')) fire({ type: 'setBrand', displayName: name.value }); };
  name.addEventListener('change', commit);
  name.addEventListener('keydown', (e) => { if (e.key === 'Enter') name.blur(); });
  const mode = $<HTMLSelectElement>('brand-mode');
  mode.addEventListener('change', () => fire({ type: 'setBrand', mode: mode.value }));
  const sliders = [
    slider({ key: 'scale', label: 'Size', min: 0.1, max: 3, step: 0.05, get: (s) => s.brand.scale, set: (v) => fire({ type: 'setBrand', scale: v }) }),
    slider({ key: 'opacity', label: 'Opacity', min: 0, max: 1, step: 0.01, get: (s) => s.brand.opacity, set: (v) => fire({ type: 'setBrand', opacity: v }) }),
  ];
  $('brand-sliders').append(...sliders.map((s) => s.row));
  updaters.push((s) => {
    if (!busy.has(name) && document.activeElement !== name) name.value = s.brand.displayName ?? '';
    if (s.brand.mode) mode.value = s.brand.mode;
    for (const x of sliders) x.update(s);
  });
}

// ------------------------------------------------------- performer/output
function setupPerformer(): void {
  const names = contract?.performer ?? Object.keys(PERFORMER_LABELS);
  const sliders = names.map((n) => slider({
    key: n, label: PERFORMER_LABELS[n]?.[0] ?? n, hint: PERFORMER_LABELS[n]?.[1], min: 0, max: 1, step: 0.01, test: `performer-${n}`,
    get: (s) => s.performer[n], set: (v) => fire({ type: 'setPerformer', name: n, value: v }),
  }));
  $('performer').append(...sliders.map((s) => s.row));
  updaters.push((s) => { for (const x of sliders) x.update(s); });
}

function setupOutput(): void {
  const sliders = [
    slider({ key: 'maxBrightness', label: 'Max brightness', hint: 'A ceiling for the whole picture', min: 0, max: 1, step: 0.01, get: (s) => s.output.maxBrightness, set: (v) => fire({ type: 'setOutput', maxBrightness: v }) }),
    slider({ key: 'maxFlashes', label: 'Flashes / s', hint: 'How many flashes per second the limiter allows', min: 1, max: 10, step: 1, get: (s) => s.output.maxFlashes, set: (v) => fire({ type: 'setOutput', maxFlashes: Math.round(v) }) }),
  ];
  $('output-sliders').append(...sliders.map((s) => s.row));
  const limit = $<HTMLInputElement>('flash-limit');
  const dialog = $<HTMLDialogElement>('strobe-dialog');
  const confirmBox = $<HTMLInputElement>('strobe-confirm');
  confirmBox.addEventListener('change', () => { $<HTMLButtonElement>('strobe-ok').disabled = !confirmBox.checked; });
  limit.addEventListener('change', () => {
    if (limit.checked) { fire({ type: 'setOutput', flashLimit: true }); return; }
    limit.checked = true;                       // stays on unless confirmed
    confirmBox.checked = false;
    $<HTMLButtonElement>('strobe-ok').disabled = true;
    dialog.showModal();
  });
  dialog.addEventListener('close', () => {
    if (dialog.returnValue === 'ok' && confirmBox.checked) fire({ type: 'setOutput', flashLimit: false, confirm: CONFIRM_STROBE });
  });
  updaters.push((s) => {
    for (const x of sliders) x.update(s);
    limit.checked = s.output.flashLimit !== false;
    document.body.classList.toggle('strobe-allowed', s.output.flashLimit === false);
  });
}

// --------------------------------------------------------------- library
// The library panel (library.ts) owns the module list; layer menus redraw from it.
function onLibrary(lib: Library): void {
  library = lib;
  slotKeys = {};
  if (state) applyState(state);
}

// ----------------------------------------------------------------- show
function setupShow(): void {
  $('show-save').addEventListener('click', async () => {
    if (!bridge.state) return toast('Not connected to TouchDesigner');
    try {
      const fresh = (await send({ type: 'getState' })).state as ShowState;
      const where = await api.saveShow(fresh);
      if (where) toast(`Saved ${where}`, 'info');
    } catch (e) {
      if (!(e instanceof BridgeRequestError)) toast(`Could not save: ${(e as Error).message}`);
    }
  });
  $('show-open').addEventListener('click', async () => {
    try {
      const picked = await api.openShow();
      if (!picked) return;
      const r = await send({ type: 'applyShow', show: picked.show });
      if (r.problems?.length) toast(`Loaded with ${r.problems.length} problem(s): ${r.problems.join('; ')}`);
      else toast(`Loaded ${picked.path}`, 'info');
    } catch (e) {
      if (!(e instanceof BridgeRequestError)) toast(`Could not open: ${(e as Error).message}`);
    }
  });
}

// -------------------------------------------------------- status/preview
const LANE_SHORT: Record<string, string> = {
  body_level: 'body', body_drift: 'drift', impact_fast: 'hit', impact_wide: 'hit+', impact_trigger: 'trig',
  sync_level: 'beat', sync_phase: 'phase', sync_sine: 'sine', sync_triangle: 'tri', sync_bar_env: 'bar',
  texture_level: 'tex', texture_jitter: 'jitter', mood_warmth: 'warm', mood_softness: 'soft',
  brand_pulse: 'name', blackout_gate: 'gate',
};
const laneBars: Map<string, HTMLElement> = new Map();
function setupLanes(): void {
  const lanes = contract?.lanes ?? [];
  const host = $('lanes');
  for (const l of lanes) {
    const bar = el('span', { class: 'fill' });
    host.append(el('div', { class: `lane lane-${l.kind}`, title: l.name }, el('div', { class: 'meter' }, bar), el('span', { class: 'lane-name', text: LANE_SHORT[l.name] ?? l.name })));
    laneBars.set(l.name, bar);
  }
}
const laneRange = new Map<string, [number, number]>();

function applyStatus(st: RuntimeStatus): void {
  if (st.fps !== undefined) $('fps').textContent = `${st.fps.toFixed(0)} fps`;
  for (const [name, v] of Object.entries(st.lanes ?? {})) {
    const bar = laneBars.get(name);
    if (!bar) continue;
    const [lo, hi] = laneRange.get(name) ?? [0, 1];
    bar.style.transform = `scaleY(${Math.max(0, Math.min(1, (v - lo) / (hi - lo || 1)))})`;
  }
  $('badge-limiter').hidden = !(st.limiter?.held && st.limiter.held > 0.5);
  for (const [slot, s] of Object.entries(st.slots ?? {})) {
    const node = document.querySelector<HTMLElement>(`[data-slot-status="${slot}"]`);
    if (node) node.textContent = s.status ?? '';
  }
}

let previewUrl: string | null = null;
let previewFrames = 0;
function applyPreview(frame: Blob | ArrayBuffer): void {
  const blob = frame instanceof Blob ? frame : new Blob([frame]);
  const url = URL.createObjectURL(blob);
  const img = $<HTMLImageElement>('preview');
  img.onload = () => { if (previewUrl && previewUrl !== url) URL.revokeObjectURL(previewUrl); previewUrl = url; };
  img.src = url;
  previewFrames++;
  $('preview-empty').hidden = true;
}

// ------------------------------------------------------------------ state
function applyState(s: ShowState): void {
  state = s;
  renderSlots(s);
  for (const u of updaters) u(s);
  looksPanel?.update(s);
}

// ---------------------------------------------------------------- MIDI
// Controller actions reach the runtime exactly as the on-screen controls do.
const midiPerformer = throttle((name: string, v: number) => fire({ type: 'setPerformer', name, value: Math.round(v * 1000) / 1000 }), 40);
const midiFade = throttle((v: number) => fire({ type: 'setTransition', fade: Math.round(v * 100) / 10 }), 80);
function midiPress(id: string): void {
  const s = state;
  if (id.startsWith('take:')) looksPanel.take(Number(id.slice(5)));
  else if (id === 'next') looksPanel.step(1);
  else if (id === 'prev') looksPanel.step(-1);
  else if (id === 'blackout') fire({ type: 'setOutput', blackout: !s?.output.blackout });
  else if (id.startsWith('layer:')) {
    const slot = id.slice(6) as SlotName;
    fire({ type: 'setSlotEnabled', slot, enabled: !s?.slots[slot]?.enabled });
  }
}
function midiValue(id: string, v: number): void {
  if (id.startsWith('performer:')) midiPerformer(id.slice(10), v);
  else if (id === 'fade') midiFade(v);
}

async function main(): Promise<void> {
  const config = await api.config();
  contract = await api.contract();
  for (const l of contract?.lanes ?? []) laneRange.set(l.name, l.range);
  setupHeader();
  setupColour();
  setupBrand();
  setupPerformer();
  setupOutput();
  setupShow();
  setupLanes();

  bridge = new BridgeClient({
    url: config.url,
    token: () => api.token(),
    client: `deckglow-app/${config.version}`,
    onConnection: (c) => {
      showConnection(c);
      if (c.phase === 'open') {
        void libraryPanel.load();
        void bridge.subscribe({ status: true, preview: { fps: 15, width: 640 } }).catch(() => undefined);
        void setupPanel?.restorePending();
      }
      libraryPanel.render();
      void setupPanel?.refresh();
    },
    onState: applyState,
    onStatus: (st) => { lastStatus = st; applyStatus(st); looksPanel?.onStatus(st); setupPanel?.onStatus(st); },
    onPreview: applyPreview,
    onEvent: (m) => libraryPanel.onEvent(m),
  });
  libraryPanel = createLibrary({
    bridge, api, state: () => state, onLibrary,
    slotTitle: (t) => SLOT_INFO[t as SlotName]?.title ?? t,
  });
  libraryPanel.setup();
  void libraryPanel.loadPacks();
  looksPanel = createLooks({ bridge, state: () => state, library: () => library, thumbnail: (p) => api.thumbnail(p) });
  looksPanel.setup();
  midi = createMidi({ api, press: midiPress, value: midiValue });
  await midi.setup();
  setupPanel = createSetup({ api, bridge, state: () => state, status: () => lastStatus });
  bridge.start();
  void setupPanel.setup(!config.smoke);      // opens by itself on a first run (never in a smoke run)
  (window as any).__deckglow = { bridge, get previewFrames() { return previewFrames; }, get library() { return library; }, libraryPanel, looksPanel, midi };
  if (config.smokeSetup) {
    void runSetupSmoke(api, setupPanel, config.smokeLaunch ? { bridge, library: () => library, status: () => lastStatus } : undefined)
      .then((r) => api.smokeDone(r));
  } else if (config.smoke) {
    void runSmoke(bridge, () => previewFrames, () => library, { api, pack: config.smokePack ?? null, panel: libraryPanel }, midi)
      .then((r) => api.smokeDone(r));
  }
}

void main();
