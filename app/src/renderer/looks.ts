// The Looks panel: 16 pads. A look is the Scene and Hits layers (with their
// controls), the palette and the background colour; the name, finish, output
// safety and performance faders stay as they are across looks.
//
// Click a pad to TAKE it: the runtime loads the look into its idle stack,
// waits for the next beat or bar (or not, with Now), and crossfades. Shift-
// click cuts (no fade, now). An empty pad saves what is on screen. Keys 1-9
// and 0 take looks 1-10; [ and ] step through the filled ones.

import type { BridgeClient } from './bridge.js';
import { $, el, modal, toast } from './dom.js';
import { stepLook } from './midi-map.js';
import type { Library, LookEntry, Quantize, RuntimeStatus, ShowState } from '../shared/api.js';
import { BANK_SIZE } from '../shared/api.js';

export interface LooksCtx {
  bridge: BridgeClient;
  state: () => ShowState | null;
  library: () => Library;
  thumbnail: (path: string) => Promise<string | null>;
}

const QUANTIZE: [Quantize, string][] = [['now', 'Now'], ['beat', 'Beat'], ['bar', 'Bar']];
const fmtFade = (s: number) => (s <= 0 ? 'cut' : `${s.toFixed(1)} s`);

export function createLooks(ctx: LooksCtx) {
  const pads: { root: HTMLButtonElement; img: HTMLImageElement; name: HTMLElement; bar: HTMLElement; key: string }[] = [];
  const thumbCache = new Map<string, string>();
  let fadeBusy = false;

  const send = (msg: Record<string, unknown>) => ctx.bridge.request(msg).catch((e: Error) => { toast(e.message); throw e; });
  const bank = (): (LookEntry | null)[] => ctx.state()?.looks ?? [];

  function take(index: number, cut = false): void {
    const s = ctx.state();
    if (!s?.looks) return toast('Looks need the look runtime - run build_look_runtime.py in TouchDesigner');
    if (!s.looks[index]) return toast(`Look ${index + 1} is empty - click it to save what is on screen there`);
    void send(cut ? { type: 'take', index, fade: 0, quantize: 'now' } : { type: 'take', index }).catch(() => undefined);
  }

  function step(dir: 1 | -1): void {
    const s = ctx.state();
    const next = stepLook(bank().map(Boolean), s?.take?.current ?? null, dir);
    if (next === null) return toast('No looks saved yet');
    take(next);
  }

  async function save(index: number, name?: string): Promise<void> {
    await send({ type: 'saveLook', index, name: name || `Look ${index + 1}` }).catch(() => undefined);
  }

  function edit(index: number): void {
    const entry = bank()[index];
    const name = el('input', { type: 'text', maxlength: 32, value: entry?.name ?? `Look ${index + 1}`, 'aria-label': 'Look name' });
    const d = modal(entry ? `Look ${index + 1}: ${entry.name}` : `Look ${index + 1}`, [
      el('p', { text: 'A look holds the Scene and Hits layers with their controls, plus the palette and background colour.' }),
      el('label', { class: 'row' }, el('span', { class: 'field-label', text: 'Name' }), name),
    ], [
      { value: 'cancel', label: 'Cancel' },
      ...(entry ? [{ value: 'clear', label: 'Clear', kind: 'danger' as const }, { value: 'rename', label: 'Rename' }] : []),
      { value: 'save', label: entry ? 'Replace with what is on screen' : 'Save what is on screen', kind: 'primary' as const },
    ], { testId: 'look-dialog' });
    void d.result.then(async (v) => {
      const n = name.value.trim() || `Look ${index + 1}`;
      if (v === 'save') await save(index, n);
      else if (v === 'rename') await send({ type: 'renameLook', index, name: n }).catch(() => undefined);
      else if (v === 'clear') await send({ type: 'deleteLook', index }).catch(() => undefined);
    });
  }

  function setup(): void {
    const grid = $('look-pads');
    for (let i = 0; i < BANK_SIZE; i++) {
      const img = el('img', { alt: '', onerror: () => { img.hidden = true; } });
      const name = el('span', { class: 'pad-name' });
      const bar = el('span', { class: 'pad-progress' });
      const menu = el('span', { class: 'pad-edit', role: 'button', tabindex: 0, title: 'Save, rename or clear', text: '⋯',
        onclick: (e: Event) => { e.stopPropagation(); edit(i); } });
      const root = el('button', { class: 'pad pad-empty', dataset: { test: `look-${i}` },
        title: `Look ${i + 1}${i < 10 ? ` (key ${(i + 1) % 10})` : ''} - shift-click to cut`,
        onclick: (e: MouseEvent) => { if (bank()[i]) take(i, e.shiftKey); else void save(i); } },
      el('span', { class: 'pad-thumb' }, img), el('span', { class: 'pad-num', text: String(i + 1) }), name, menu, bar);
      grid.append(root);
      pads.push({ root, img, name, bar, key: '' });
    }
    const fade = $<HTMLInputElement>('look-fade');
    let timer: ReturnType<typeof setTimeout> | null = null;
    fade.addEventListener('pointerdown', () => { fadeBusy = true; });
    fade.addEventListener('pointerup', () => setTimeout(() => { fadeBusy = false; }, 250));
    fade.addEventListener('input', () => {
      $('look-fade-value').textContent = fmtFade(Number(fade.value));
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => void send({ type: 'setTransition', fade: Number(fade.value) }).catch(() => undefined), 80);
    });
    const seg = $('look-quantize');
    for (const [q, label] of QUANTIZE) {
      seg.append(el('button', { role: 'radio', dataset: { q }, text: label, title: q === 'now' ? 'Start the fade at once' : `Start the fade on the next ${q}`,
        onclick: () => void send({ type: 'setTransition', quantize: q }).catch(() => undefined) }));
    }
    $('look-prev').addEventListener('click', () => step(-1));
    $('look-next').addEventListener('click', () => step(1));
    document.addEventListener('keydown', (e) => {
      const t = e.target as HTMLElement;
      if (e.ctrlKey || e.metaKey || e.altKey || t instanceof HTMLInputElement || t instanceof HTMLSelectElement || t instanceof HTMLTextAreaElement) return;
      if (document.querySelector('dialog[open]')) return;
      if (/^[0-9]$/.test(e.key)) { take((Number(e.key) + 9) % 10, e.shiftKey); e.preventDefault(); }
      else if (e.key === '[') step(-1);
      else if (e.key === ']') step(1);
    });
  }

  function update(s: ShowState): void {
    const has = Array.isArray(s.looks);
    $('looks-missing').hidden = has;
    $('look-pads').hidden = !has;
    if (!has) return;
    const take = s.take;
    for (let i = 0; i < BANK_SIZE; i++) {
      const p = pads[i], entry = s.looks![i];
      const phase = take && take.index === i && take.phase !== 'idle' ? take.phase : null;
      p.root.className = ['pad', entry ? 'pad-filled' : 'pad-empty', entry && take?.current === i ? 'pad-current' : '',
        phase ? `pad-${phase}` : ''].filter(Boolean).join(' ');
      p.name.textContent = entry ? entry.name : '+ save';
      if (!phase) p.bar.style.width = '0';
      const base = entry?.look.slots.base_scene?.module ?? null;
      const thumb = ctx.library().modules.find((m) => m.id === base)?.thumbnail ?? '';
      const key = `${thumb}|${entry?.look.background ?? ''}`;
      if (key !== p.key) {
        p.key = key;
        p.img.hidden = !thumb;
        p.root.style.setProperty('--pad-bg', entry?.look.background ? `rgb(${entry.look.background.map((c) => Math.round(c * 255)).join(',')})` : '');
        if (thumb) {
          const cached = thumbCache.get(thumb);
          if (cached) p.img.src = cached;
          else void ctx.thumbnail(thumb).then((u) => { if (u) { thumbCache.set(thumb, u); if (p.key === key) { p.img.src = u; p.img.hidden = false; } } });
        }
      }
    }
    if (s.transition) {
      if (!fadeBusy) $<HTMLInputElement>('look-fade').value = String(s.transition.fade);
      $('look-fade-value').textContent = fmtFade(s.transition.fade);
      for (const b of $('look-quantize').querySelectorAll<HTMLButtonElement>('button')) {
        b.setAttribute('aria-checked', String(b.dataset.q === s.transition.quantize));
      }
    }
    const t = s.take;
    $('look-status').textContent = !t || t.phase === 'idle'
      ? (t?.current !== null && t?.current !== undefined && s.looks![t.current] ? `On screen: ${s.looks![t.current]!.name}` : '')
      : `${{ loading: 'Loading', armed: `Waiting for the ${s.transition?.quantize === 'beat' ? 'beat' : 'bar'}`, fading: 'Fading to' }[t.phase as 'loading' | 'armed' | 'fading']} ${s.looks![t.index ?? 0]?.name ?? ''}…`;
    if (t?.problems?.length && t.phase === 'idle') toastOnce(t.problems.join('; '));
  }

  let lastProblems = '';
  const toastOnce = (text: string) => { if (text !== lastProblems) { lastProblems = text; toast(text); } };

  function onStatus(st: RuntimeStatus): void {
    const t = st.take;
    if (!t || t.index === null || t.index === undefined) return;
    const p = pads[t.index];
    if (p && t.phase === 'fading') p.bar.style.width = `${Math.round((t.progress ?? 0) * 100)}%`;
  }

  return { setup, update, onStatus, take, step, save };
}
