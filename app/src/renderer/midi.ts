// The Controller card: Web MIDI input and MIDI learn. The mapping logic is
// midi-map.ts; this file is the device access, the card and the settings.
// MIDI lives in the app (owner's choice, 2026-11-07): the app must be open for
// a controller to work, and nothing in TouchDesigner changes.

import { $, el, toast } from './dom.js';
import { ACTIONS, MidiMapper, defaultSettings, describe, parse } from './midi-map.js';
import type { DeckglowApi, MidiSettings } from '../shared/api.js';

export interface MidiCtx {
  api: DeckglowApi;
  press(actionId: string): void;
  value(actionId: string, v: number): void;
}

export function createMidi(ctx: MidiCtx) {
  let mapper = new MidiMapper(defaultSettings(), ctx);
  let access: MIDIAccess | null = null;
  let showAllLooks = false;
  let saveTimer: ReturnType<typeof setTimeout> | null = null;

  const save = () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      const all = await ctx.api.getSettings().catch(() => ({}));
      await ctx.api.setSettings({ ...all, midi: mapper.settings }).catch((e: Error) => toast(`Could not save the MIDI mapping: ${e.message}`));
    }, 300);
  };

  /** One message from a device (also the smoke test's way in). */
  function handle(data: ArrayLike<number>, device: string | null): void {
    const ev = parse(data);
    if (ev) $('midi-monitor').textContent = `Last: ${ev.kind === 'cc' ? `CC ${ev.number} = ${ev.value}` : `${ev.kind === 'note-on' ? 'Note on' : 'Note off'} ${ev.number}`} · ch ${ev.channel + 1}${device ? ' · ' + device : ''}`;
    const r = mapper.handle(data, device);
    if (!r) return;
    if ('learned' in r) {
      const label = ACTIONS.find((a) => a.id === r.learned)?.label;
      toast(`${label} → ${describe(r.binding)}${r.replaced ? ` (moved from ${ACTIONS.find((a) => a.id === r.replaced)?.label})` : ''}`, 'info');
      save();
      render();
    } else if ('rejected' in r) {
      toast(r.rejected);
    }
  }

  async function connect(): Promise<void> {
    if (!('requestMIDIAccess' in navigator)) {
      $('midi-devices').textContent = 'This window has no Web MIDI.';
      return;
    }
    try {
      access = await navigator.requestMIDIAccess({ sysex: false });
    } catch (e) {
      $('midi-devices').textContent = `MIDI access was refused (${(e as Error).message}).`;
      return;
    }
    const attach = () => {
      for (const input of access!.inputs.values()) {
        input.onmidimessage = (m: MIDIMessageEvent) => { if (m.data) handle(m.data, input.name ?? null); };
      }
      renderDevices();
    };
    access.onstatechange = attach;
    attach();
  }

  function renderDevices(): void {
    const names = access ? [...access.inputs.values()].map((i) => i.name ?? 'unnamed') : [];
    const sel = $<HTMLSelectElement>('midi-input');
    const want = mapper.settings.input;
    sel.replaceChildren(el('option', { value: '', text: 'All MIDI inputs' }),
      ...names.map((n) => el('option', { value: n, text: n })),
      ...(want && !names.includes(want) ? [el('option', { value: want, text: `${want} (not connected)` })] : []));
    sel.value = want ?? '';
    $('midi-devices').textContent = names.length ? `${names.length} device${names.length === 1 ? '' : 's'}: ${names.join(', ')}` : 'No MIDI devices found - plug one in; it appears here.';
  }

  function render(): void {
    $<HTMLInputElement>('midi-enabled').checked = mapper.settings.enabled;
    const host = $('midi-map');
    const groups = ['Looks', 'Show', 'Layers', 'Faders'] as const;
    const learning = mapper.learningAction;
    host.replaceChildren(...groups.map((g) => {
      const rows = ACTIONS.filter((a) => a.group === g).filter((a) => showAllLooks || !/^take:(8|9|1[0-5])$/.test(a.id));
      return el('div', { class: 'midi-group' }, el('h4', { text: g }), ...rows.map((a) => {
        const b = mapper.settings.bindings[a.id];
        const isLearning = learning === a.id;
        return el('div', { class: `midi-row${isLearning ? ' midi-learning' : ''}`, dataset: { action: a.id } },
          el('span', { class: 'midi-label', text: a.label, title: a.continuous ? 'Needs a knob or fader (CC)' : 'A pad, key or button' }),
          el('span', { class: 'midi-binding muted small', text: isLearning ? (a.continuous ? 'Move a knob or fader…' : 'Press a pad or button…') : describe(b) }),
          el('button', { class: 'btn btn-small', text: isLearning ? 'Cancel' : 'Learn', dataset: { test: `learn-${a.id}` },
            onclick: () => { mapper.learn(isLearning ? null : a.id); render(); } }),
          el('button', { class: 'btn btn-small btn-quiet', text: '×', title: 'Clear', disabled: !b,
            onclick: () => { mapper.clear(a.id); save(); render(); } }));
      }), g === 'Looks' ? el('button', { class: 'btn btn-small btn-quiet', text: showAllLooks ? 'Show looks 1-8 only' : 'Show looks 9-16',
        onclick: () => { showAllLooks = !showAllLooks; render(); } }) : null);
    }));
  }

  async function setup(): Promise<void> {
    const stored = (await ctx.api.getSettings().catch(() => ({} as any))).midi as MidiSettings | undefined;
    mapper = new MidiMapper({ ...defaultSettings(), ...(stored ?? {}), bindings: { ...(stored?.bindings ?? {}) } }, ctx);
    $<HTMLInputElement>('midi-enabled').addEventListener('change', (e) => {
      mapper.settings.enabled = (e.target as HTMLInputElement).checked;
      save();
    });
    $<HTMLSelectElement>('midi-input').addEventListener('change', (e) => {
      mapper.settings.input = (e.target as HTMLSelectElement).value || null;
      save();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && mapper.learningAction) { mapper.learn(null); render(); }
    });
    render();
    renderDevices();
    await connect();
  }

  return {
    setup, handle,
    get mapper() { return mapper; },
    /** Save the mapping now and redraw (after changing mapper.settings directly). */
    persist: () => { save(); render(); },
  };
}
