// MIDI mapping: which pad, key or knob does what. Pure logic - no Web MIDI,
// no DOM - so it is unit-tested under Node (test/midi.test.mjs).
//
// Buttons (TAKE a look, next/previous, Blackout, layer on/off) fire on a
// note-on, or when a CC crosses the middle (0-63 -> 64-127) - so buttons that
// send CCs work too, and holding one never repeats. Continuous actions (the
// performance faders, fade time) take CCs only: a note has no position.

import type { MidiBinding, MidiSettings } from '../shared/api.js';

export interface ActionDef {
  id: string;
  label: string;
  group: 'Looks' | 'Show' | 'Layers' | 'Faders';
  continuous: boolean;
}

export const PERFORMER_ACTIONS: [string, string][] = [
  ['masterIntensity', 'Master'], ['motionAmount', 'Motion'], ['flashAmount', 'Flash'],
  ['textureAmount', 'Texture'], ['toneAmount', 'Mood'], ['brandAmount', 'Name pulse'],
];
export const LAYER_ACTIONS: [string, string][] = [
  ['base_scene', 'Scene on/off'], ['hit_fx', 'Hits on/off'], ['brand_overlay', 'Name on/off'], ['finish_fx', 'Finish on/off'],
];

export const ACTIONS: ActionDef[] = [
  ...Array.from({ length: 16 }, (_, i): ActionDef => ({ id: `take:${i}`, label: `Take look ${i + 1}`, group: 'Looks', continuous: false })),
  { id: 'prev', label: 'Previous look', group: 'Looks', continuous: false },
  { id: 'next', label: 'Next look', group: 'Looks', continuous: false },
  { id: 'blackout', label: 'Blackout', group: 'Show', continuous: false },
  { id: 'fade', label: 'Fade time (0-10 s)', group: 'Show', continuous: true },
  ...LAYER_ACTIONS.map(([slot, label]): ActionDef => ({ id: `layer:${slot}`, label, group: 'Layers', continuous: false })),
  ...PERFORMER_ACTIONS.map(([name, label]): ActionDef => ({ id: `performer:${name}`, label, group: 'Faders', continuous: true })),
];
const BY_ID = new Map(ACTIONS.map((a) => [a.id, a]));

export interface MidiEvent {
  kind: 'note-on' | 'note-off' | 'cc';
  channel: number;      // 0-15
  number: number;       // note or controller, 0-127
  value: number;        // velocity or CC value, 0-127
}

export function parse(data: ArrayLike<number>): MidiEvent | null {
  if (!data || data.length < 3) return null;
  const status = data[0] & 0xf0, channel = data[0] & 0x0f, number = data[1] & 0x7f, value = data[2] & 0x7f;
  if (status === 0x90) return { kind: value > 0 ? 'note-on' : 'note-off', channel, number, value };
  if (status === 0x80) return { kind: 'note-off', channel, number, value };
  if (status === 0xb0) return { kind: 'cc', channel, number, value };
  return null;               // pitch bend, aftertouch, clock, sysex: not used
}

export function describe(b: MidiBinding | undefined): string {
  if (!b) return '-';
  return `${b.type === 'cc' ? 'CC' : 'Note'} ${b.number} · ch ${b.channel + 1}`;
}

export const sameControl = (a: MidiBinding, b: MidiBinding) => a.type === b.type && a.channel === b.channel && a.number === b.number;

export const defaultSettings = (): MidiSettings => ({ enabled: true, input: null, bindings: {} });

export interface MidiHandlers {
  press(actionId: string): void;
  value(actionId: string, v: number): void;      // 0..1
}

export type HandleResult =
  | { learned: string; binding: MidiBinding; replaced?: string }
  | { rejected: string }
  | { fired: string }
  | null;

export class MidiMapper {
  private learning: string | null = null;
  private ccHigh = new Map<string, boolean>();     // CC buttons: last side of the middle

  constructor(public settings: MidiSettings, private handlers: MidiHandlers) {}

  get learningAction(): string | null {
    return this.learning;
  }

  /** Arm MIDI learn for one action; null cancels. */
  learn(actionId: string | null): void {
    this.learning = actionId && BY_ID.has(actionId) ? actionId : null;
  }

  clear(actionId: string): void {
    delete this.settings.bindings[actionId];
  }

  /** One incoming MIDI message, from the device named `device`. */
  handle(data: ArrayLike<number>, device: string | null = null): HandleResult {
    if (!this.settings.enabled) return null;
    if (this.settings.input && device !== null && device !== this.settings.input) return null;
    const ev = parse(data);
    if (!ev) return null;
    if (this.learning) return this.learnFrom(ev);
    const key = (t: 'note' | 'cc') => `${t}:${ev.channel}:${ev.number}`;
    if (ev.kind === 'note-off') return null;
    const type = ev.kind === 'cc' ? 'cc' : 'note';
    for (const [id, b] of Object.entries(this.settings.bindings)) {
      if (b.type !== type || b.channel !== ev.channel || b.number !== ev.number) continue;
      const def = BY_ID.get(id);
      if (!def) continue;
      if (def.continuous) {
        if (type !== 'cc') continue;
        this.handlers.value(id, ev.value / 127);
        return { fired: id };
      }
      if (type === 'note') {
        this.handlers.press(id);
        return { fired: id };
      }
      const high = ev.value >= 64, was = this.ccHigh.get(key('cc')) ?? false;
      this.ccHigh.set(key('cc'), high);
      if (high && !was) {
        this.handlers.press(id);
        return { fired: id };
      }
      return null;
    }
    return null;
  }

  private learnFrom(ev: MidiEvent): HandleResult {
    const id = this.learning!;
    const def = BY_ID.get(id)!;
    if (ev.kind === 'note-off') return null;
    if (def.continuous && ev.kind !== 'cc') return { rejected: `${def.label} needs a knob or fader (a CC), not a pad or key` };
    const binding: MidiBinding = { type: ev.kind === 'cc' ? 'cc' : 'note', channel: ev.channel, number: ev.number };
    let replaced: string | undefined;
    for (const [other, b] of Object.entries(this.settings.bindings)) {
      if (other !== id && sameControl(b, binding)) {          // one control, one action
        delete this.settings.bindings[other];
        replaced = other;
      }
    }
    this.settings.bindings[id] = binding;
    this.learning = null;
    if (binding.type === 'cc') this.ccHigh.set(`cc:${binding.channel}:${binding.number}`, ev.value >= 64);
    return { learned: id, binding, replaced };
  }
}

/** The filled look after (step 1) or before (step -1) `current`, wrapping around. */
export function stepLook(filled: boolean[], current: number | null, step: 1 | -1): number | null {
  const n = filled.length;
  if (!filled.some(Boolean)) return null;
  let i = current ?? (step === 1 ? -1 : n);
  for (let k = 0; k < n; k++) {
    i = (i + step + n) % n;
    if (filled[i]) return i;
  }
  return null;
}
