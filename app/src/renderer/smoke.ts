// `npm run smoke`: drives the real controls in the real window against a
// running runtime (TouchDesigner or the mock bridge), checks every change
// comes back in the broadcast state, restores the starting show, then the
// main process screenshots the window and exits 0 (pass) or 1 (fail).

import type { BridgeClient } from './bridge.js';
import type { DeckglowApi, Library, ShowState } from '../shared/api.js';

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

export async function runSmoke(bridge: BridgeClient, frames: () => number, lib: () => Library, packs?: PackSmoke): Promise<{ ok: boolean; steps: string[] }> {
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
