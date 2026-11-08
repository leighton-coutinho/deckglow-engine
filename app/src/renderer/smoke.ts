// `npm run smoke`: drives the real controls in the real window against a
// running runtime (TouchDesigner or the mock bridge), checks every change
// comes back in the broadcast state, restores the starting show, then the
// main process screenshots the window and exits 0 (pass) or 1 (fail).

import type { BridgeClient } from './bridge.js';
import type { DeckglowApi, Library, MidiSettings, ShowState } from '../shared/api.js';

export interface PackSmoke {
  api: DeckglowApi;
  pack: string | null;
  panel: { load: (rescan?: boolean) => Promise<void>; loadPacks: () => Promise<void> };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function waitFor(what: string, pred: () => boolean, ms = 8000): Promise<void> {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (pred()) return;
    await sleep(50);
  }
  throw new Error(`timed out waiting for ${what}`);
}

function q<T extends HTMLElement>(sel: string): T {
  const n = document.querySelector<T>(sel);
  if (!n) throw new Error(`no element ${sel}`);
  return n;
}

function setInput(input: HTMLInputElement | HTMLSelectElement, value: string, event: 'input' | 'change'): void {
  input.value = value;
  input.dispatchEvent(new Event(event, { bubbles: true }));
}

/** Clicks a switch only if it is not already in the wanted position - like a person would. */
function setSwitch(sel: string, on: boolean): void {
  const box = q<HTMLInputElement>(sel);
  if (box.checked !== on) box.click();
}

export interface MidiSmoke {
  mapper: { settings: MidiSettings; learn(id: string | null): void };
  handle(data: ArrayLike<number>, device: string | null): void;
  persist(): void;
}

export async function runSmoke(bridge: BridgeClient, frames: () => number, lib: () => Library, packs?: PackSmoke,
  midi?: MidiSmoke): Promise<{ ok: boolean; steps: string[] }> {
  const steps: string[] = [];
  let ok = true;
  const st = () => bridge.state as ShowState;
  const step = async (label: string, fn: () => Promise<void> | void) => {
    try {
      await fn();
      steps.push(`ok   ${label}`);
    } catch (e) {
      ok = false;
      steps.push(`FAIL ${label}: ${(e as Error).message}`);
    }
  };

  await step('connects and authenticates', () => waitFor('connection', () => bridge.connection.phase === 'open', 15000));
  if (!ok) return { ok, steps };
  const start: ShowState = JSON.parse(JSON.stringify(st()));
  await step('library lists approved modules', () => waitFor('library', () => lib().modules.some((m) => m.approved === 'yes')));
  await step('preview frames arrive', () => waitFor('preview', () => frames() >= 3));
  await step('layer cards drawn for all four slots', () => waitFor('slot cards', () => document.querySelectorAll('[data-slot]').length === 4));

  await step('Hits switch on, then off', async () => {
    setSwitch('[data-test="slot-hit_fx-enabled"]', true);
    await waitFor('hit_fx enabled', () => st().slots.hit_fx.enabled === true);
    setSwitch('[data-test="slot-hit_fx-enabled"]', false);
    await waitFor('hit_fx disabled', () => st().slots.hit_fx.enabled === false);
  });
  await step('Scene switch off', async () => {
    setSwitch('[data-test="slot-base_scene-enabled"]', false);
    await waitFor('base disabled', () => st().slots.base_scene.enabled === false);
  });
  await step('custom background purple', async () => {
    setSwitch('[data-test="bg-custom"]', false);
    setInput(q<HTMLInputElement>('[data-test="bg-color"]'), '#40005a', 'input');
    setSwitch('[data-test="bg-custom"]', true);
    await waitFor('background', () => Array.isArray(st().background) && Math.abs(st().background![2] - 0.353) < 0.01);
  });
  await sleep(600);
  await step('master slider to 0.5', async () => {
    setInput(q<HTMLInputElement>('[data-test="performer-masterIntensity"]'), '0.5', 'input');
    await waitFor('master', () => st().performer.masterIntensity === 0.5);
  });
  await step('name typed', async () => {
    const name = q<HTMLInputElement>('[data-test="brand-name"]');
    setInput(name, 'SMOKE TEST', 'change');
    await waitFor('name', () => st().brand.displayName === 'SMOKE TEST');
  });
  await step('palette menu', async () => {
    const sel = q<HTMLSelectElement>('[data-test="palette"]');
    const other = [...sel.options].map((o) => o.value).find((v) => v !== st().palette.name);
    if (!other) throw new Error('only one palette');
    setInput(sel, other, 'change');
    await waitFor('palette', () => st().palette.name === other);
  });
  await step('flash limiter stays on without confirmation', async () => {
    const box = q<HTMLInputElement>('[data-test="flash-limit"]');
    box.click();
    await sleep(300);
    const dialog = q<HTMLDialogElement>('#strobe-dialog');
    if (!dialog.open) throw new Error('no confirmation dialog');
    dialog.close('cancel');
    await sleep(300);
    if (st().output.flashLimit !== true) throw new Error('flash limit changed without confirmation');
  });
  await step('blackout toggles', async () => {
    q<HTMLButtonElement>('[data-test="blackout"]').click();
    await waitFor('blackout on', () => st().output.blackout === true);
    q<HTMLButtonElement>('[data-test="blackout"]').click();
    await waitFor('blackout off', () => st().output.blackout === false);
  });
  await step('both switches back on', async () => {
    setSwitch('[data-test="slot-base_scene-enabled"]', true);
    setSwitch('[data-test="slot-hit_fx-enabled"]', true);
    await waitFor('slots on', () => st().slots.base_scene.enabled && st().slots.hit_fx.enabled);
  });
  if (Array.isArray(st().looks)) {
    // pads 15 and 16 (indices 14, 15); the starting show restores the bank afterwards
    const take = (index: number, fade: number) => bridge.request({ type: 'take', index, fade, quantize: 'now' });
    const settled = (index: number) => () => st().take?.phase === 'idle' && st().take?.current === index;
    await step('looks: an empty pad saves what is on screen', async () => {
      if (st().looks![14]) await bridge.request({ type: 'deleteLook', index: 14 });
      await waitFor('pad 15 empty', () => !st().looks![14]);
      q<HTMLButtonElement>('[data-test="look-14"]').click();
      await waitFor('look saved', () => st().looks![14]?.look.slots.hit_fx?.enabled === true);
    });
    await step('looks: save a second look (Hits off)', async () => {
      setSwitch('[data-test="slot-hit_fx-enabled"]', false);
      await waitFor('hits off', () => st().slots.hit_fx.enabled === false);
      await bridge.request({ type: 'saveLook', index: 15, name: 'Smoke B' });
      await waitFor('saved', () => st().looks![15]?.name === 'Smoke B');
    });
    await step('looks: TAKE look 15 with a fade (loading, fading, done)', async () => {
      const seen = new Set<string>();
      const watch = setInterval(() => seen.add(st().take?.phase ?? ''), 20);
      await take(14, 0.6);
      await waitFor('look 15 on screen', settled(14), 10000);
      clearInterval(watch);
      if (!seen.has('fading')) throw new Error(`no fading phase seen (${[...seen].join(', ')})`);
      if (st().slots.hit_fx.enabled !== true) throw new Error('Hits should be back on');
    });
    await step('looks: cut to look 16', async () => {
      await take(15, 0);
      await waitFor('look 16 on screen', settled(15), 10000);
      if (st().slots.hit_fx.enabled !== false) throw new Error('Hits should be off in look 16');
      if (!q('[data-test="look-15"]').classList.contains('pad-current')) throw new Error('pad 16 not marked current');
    });
    await step('looks: an empty look is refused', async () => {
      const r = await bridge.request({ type: 'take', index: 13 }).then(() => 'taken', (e) => e.code);
      if (st().looks![13] === null && r !== 'empty_look') throw new Error(`expected empty_look, got ${r}`);
    });
  }
  if (midi) {
    const before = JSON.stringify(midi.mapper.settings);
    const m = midi.mapper;
    m.settings.enabled = true;
    m.settings.input = null;
    await step('midi: learn a pad for Blackout, press it twice', async () => {
      m.learn('blackout');
      midi.handle([0x99, 60, 100], 'Smoke Pad');
      if (m.settings.bindings.blackout?.number !== 60) throw new Error('not learned');
      midi.handle([0x99, 60, 100], 'Smoke Pad');
      await waitFor('blackout on', () => st().output.blackout === true);
      midi.handle([0x89, 60, 0], 'Smoke Pad');
      midi.handle([0x99, 60, 100], 'Smoke Pad');
      await waitFor('blackout off', () => st().output.blackout === false);
    });
    await step('midi: learn a knob for Master, turn it', async () => {
      m.learn('performer:masterIntensity');
      midi.handle([0xb0, 21, 127], 'Smoke Pad');
      midi.handle([0xb0, 21, 32], 'Smoke Pad');
      await waitFor('master follows the knob', () => Math.abs(st().performer.masterIntensity - 32 / 127) < 0.01);
    });
    await step('midi: mapping restored', async () => {
      Object.assign(m.settings, JSON.parse(before));
      m.settings.bindings = JSON.parse(before).bindings;
      midi.persist();
    });
  }
  await step('restore the starting show', async () => {
    const r: any = await bridge.request({ type: 'applyShow', show: start });
    if (r.problems?.length) throw new Error(r.problems.join('; '));
    await waitFor('restored', () => JSON.stringify(st().performer) === JSON.stringify(start.performer)
      && st().brand.displayName === start.brand.displayName && JSON.stringify(st().background) === JSON.stringify(start.background));
  });
  if (packs?.pack) {
    // the real IPC path: main process -> pack_tool.py --json (DECKGLOW_PACKS for a test folder)
    const file = packs.pack;
    let id = '';
    let moduleIds: string[] = [];
    await step('pack: checks pass (inspectPack)', async () => {
      const r = await packs.api.inspectPack(file);
      if (!r.ok || !r.pack) throw new Error(r.message ?? 'verify failed');
      id = r.pack.id;
      moduleIds = r.pack.modules.map((m) => m.id);
    });
    await step('pack: unpicked files are refused', async () => {
      const r = await packs.api.inspectPack(file + '.other').then(() => 'accepted', () => 'refused');
      if (r !== 'refused') throw new Error('main process inspected a file nobody picked');
    });
    await step('pack: installs (installPack)', async () => {
      const r = await packs.api.installPack(file, true);
      if (!r.ok) throw new Error(r.message ?? 'install failed');
    });
    await step('pack: listed, and its modules join the library on rescan', async () => {
      const l = await packs.api.listPacks();
      if (!l.packs?.some((p) => p.id === id)) throw new Error('not listed');
      await packs.panel.load(true);
      if (!moduleIds.every((m) => lib().modules.some((x) => x.id === m))) throw new Error('modules missing after rescan');
    });
    await step('pack: removes, and leaves the library', async () => {
      const r = await packs.api.removePack(id);
      if (!r.ok) throw new Error(r.message ?? 'remove failed');
      await packs.panel.load(true);
      await packs.panel.loadPacks();
      if (moduleIds.some((m) => lib().modules.some((x) => x.id === m))) throw new Error('modules still listed');
    });
  }
  await sleep(1200);                                // a fresh preview frame for the screenshot
  return { ok, steps };
}
