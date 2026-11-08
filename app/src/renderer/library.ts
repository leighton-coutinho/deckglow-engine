// The library panel: modules with their validation and approval state, the
// creator packs installed on this computer, and the install / validate /
// approve / remove flows.
//
// Trust model (docs/PACK_FORMAT_SPEC.md): anyone can publish a pack, so
// installing approves nothing. Each module version is validated in
// TouchDesigner's quarantine and approved by the person, after they have seen
// the report; only approved modules appear in the layer menus.

import type { BridgeClient } from './bridge.js';
import { $, el, modal, toast } from './dom.js';
import type {
  DeckglowApi, InstalledPack, Library, LibraryModule, PackResult, ShowState, SlotName, ValidationReport,
} from '../shared/api.js';
import { SLOTS } from '../shared/api.js';

export interface LibraryCtx {
  bridge: BridgeClient;
  api: DeckglowApi;
  state: () => ShowState | null;
  slotTitle: (type: string) => string;
  /** Called whenever the module list changes (the layer menus redraw). */
  onLibrary: (lib: Library) => void;
}

type Phase = 'approved' | 'ready' | 'unvalidated' | 'failed' | 'blocked' | 'validating';

const PHASE: Record<Phase, { label: string; badge: string; hint: string }> = {
  approved: { label: 'Approved', badge: 'badge-ok', hint: 'Can be used in shows' },
  ready: { label: 'Validated', badge: 'badge-info', hint: 'Passed validation - review the report and approve it' },
  unvalidated: { label: 'Not validated', badge: 'badge-muted', hint: 'Validate it in TouchDesigner before it can be approved' },
  failed: { label: 'Failed', badge: 'badge-danger', hint: 'Failed validation - it cannot be used' },
  blocked: { label: 'Fails now', badge: 'badge-danger', hint: 'Approved earlier, but its latest validation failed' },
  validating: { label: 'Validating…', badge: 'badge-warn', hint: 'Running in TouchDesigner quarantine' },
};

const VALIDATE_NOTE = 'Validation loads the module into TouchDesigner’s quarantine for about 10 seconds. The show keeps running, but the picture can stutter - do it before the set, not during it.';

export function createLibrary(ctx: LibraryCtx) {
  let library: Library = { modules: [], palettes: [] };
  let packs: InstalledPack[] = [];
  let validating: string | null = null;
  const thumbs = new Map<string, string>();
  const reportCache = new Map<string, ValidationReport | null>();
  let openDetails: { id: string; refresh: () => void } | null = null;

  const phase = (m: LibraryModule): Phase => {
    if (validating === m.id) return 'validating';
    if (m.approved === 'yes') return 'approved';
    if (m.approved.startsWith('blocked')) return 'blocked';
    if (m.quarantine === 'fail' || m.static === 'fail') return 'failed';
    if (m.quarantine === 'pass' || m.quarantine === 'warn') return 'ready';
    return 'unvalidated';
  };
  const sourceLabel = (m: LibraryModule) => (m.source && m.source !== 'first-party' ? m.source : 'DeckGlow');

  // ------------------------------------------------------------ loading
  async function load(rescan = false): Promise<void> {
    try {
      library = await ctx.bridge.getLibrary(rescan);
    } catch {
      return;
    }
    reportCache.clear();
    ctx.onLibrary(library);
    render();
    openDetails?.refresh();
  }

  async function loadPacks(): Promise<void> {
    const r = await ctx.api.listPacks().catch(() => null);
    packs = r?.ok ? r.packs ?? [] : [];
    renderPacks();
  }

  async function report(id: string): Promise<ValidationReport | null> {
    if (reportCache.has(id)) return reportCache.get(id)!;
    const r = await ctx.bridge.request<any>({ type: 'getReport', module: id });
    reportCache.set(id, r.report ?? null);
    return r.report ?? null;
  }

  function onEvent(m: { type: string; [k: string]: any }): void {
    if (m.type === 'validation') {
      if (m.phase === 'running') {
        validating = m.module;
        $('validation-banner').hidden = false;
        $('validation-banner').textContent = `Validating ${nameOf(m.module)} in TouchDesigner quarantine… (about 10 s)`;
      } else {
        validating = null;
        $('validation-banner').hidden = true;
        reportCache.set(m.module, m.report ?? null);
        const result = m.result as string;
        toast(result === 'fail' ? `${nameOf(m.module)} failed validation - see its report`
          : `${nameOf(m.module)} passed validation${result === 'warn' ? ' with warnings' : ''} - review and approve it`,
        result === 'fail' ? 'error' : 'info');
      }
      render();
      openDetails?.refresh();
    } else if (m.type === 'libraryChanged') {
      void load(false);
    }
  }

  const nameOf = (id: string) => library.modules.find((x) => x.id === id)?.displayName ?? id;

  // ------------------------------------------------------------ actions
  async function validate(m: LibraryModule): Promise<void> {
    try {
      await ctx.bridge.request({ type: 'validateModule', module: m.id });
    } catch (e) {
      toast((e as Error).message);
    }
  }

  async function approve(m: LibraryModule, note: string): Promise<boolean> {
    try {
      await ctx.bridge.request({ type: 'approveModule', module: m.id, note });
      toast(`Approved ${m.displayName} ${m.version} - it is now in the ${ctx.slotTitle(m.type)} menu`, 'info');
      return true;
    } catch (e) {
      toast((e as Error).message);
      return false;
    }
  }

  async function revoke(m: LibraryModule): Promise<void> {
    const inUse = slotUsing(m.id);
    const ask = modal(`Revoke approval for ${m.displayName}?`, [
      el('p', { text: 'It leaves the layer menus and cannot be loaded until it is approved again.' }),
      inUse ? el('p', { text: `It stays on the ${ctx.slotTitle(inUse)} layer until you switch that layer to something else.` }) : null,
    ].filter(Boolean) as Node[], [{ value: 'cancel', label: 'Keep it' }, { value: 'ok', label: 'Revoke', kind: 'danger' }]);
    if ((await ask.result) !== 'ok') return;
    try {
      await ctx.bridge.request({ type: 'revokeModule', module: m.id });
      toast(`Revoked ${m.displayName}`, 'info');
    } catch (e) {
      toast((e as Error).message);
    }
  }

  const slotUsing = (id: string): SlotName | null => {
    const s = ctx.state();
    return s ? SLOTS.find((slot) => s.slots[slot]?.module === id) ?? null : null;
  };

  // ------------------------------------------------------- module cards
  function render(): void {
    const host = $('library');
    const order = (m: LibraryModule) => SLOTS.indexOf(m.type as SlotName);
    const mods = [...library.modules].sort((a, b) => order(a) - order(b) || a.displayName.localeCompare(b.displayName));
    host.replaceChildren(...mods.map(card));
    if (!mods.length) host.append(el('p', { class: 'hint', text: ctx.bridge.isOpen ? 'No modules found - install a pack.' : 'Connect to TouchDesigner to see the library.' }));
  }

  function card(m: LibraryModule): HTMLElement {
    const ph = phase(m);
    const img = el('img', { alt: '', loading: 'lazy', onerror: () => { img.hidden = true; } });
    const cached = thumbs.get(m.thumbnail);
    if (cached) img.src = cached;
    else void ctx.api.thumbnail(m.thumbnail).then((u) => { if (u) { thumbs.set(m.thumbnail, u); img.src = u; } });
    const busy = validating !== null;
    const actions: HTMLElement[] = [];
    if (ph === 'approved') {
      actions.push(el('button', { class: 'btn btn-small', text: 'Use', title: `Load into the ${ctx.slotTitle(m.type)} layer`,
        dataset: { test: `use-${m.id}` },
        onclick: () => ctx.bridge.request({ type: 'setSlotModule', slot: m.type, module: m.id }).catch((e: Error) => toast(e.message)) }));
    } else if (ph === 'ready') {
      actions.push(el('button', { class: 'btn btn-small btn-primary', text: 'Review…', dataset: { test: `review-${m.id}` }, onclick: () => details(m) }));
    } else if (ph !== 'validating') {
      actions.push(el('button', { class: 'btn btn-small', text: 'Validate', disabled: busy || !ctx.bridge.isOpen, title: VALIDATE_NOTE,
        dataset: { test: `validate-${m.id}` }, onclick: () => validate(m) }));
    }
    actions.push(el('button', { class: 'btn btn-small btn-quiet', text: 'Details', onclick: () => details(m) }));
    const stale = m.approved.startsWith('stale');
    return el('div', { class: `module module-${ph}`, title: PHASE[ph].hint, dataset: { module: m.id, phase: ph } },
      el('div', { class: 'thumb' }, img, el('span', { class: `badge ${PHASE[ph].badge} thumb-badge`, text: stale && ph !== 'ready' ? 'New version' : PHASE[ph].label })),
      el('div', { class: 'module-meta' },
        el('strong', { text: m.displayName }),
        el('span', { class: 'muted small', text: `${ctx.slotTitle(m.type)} · ${m.version} · ${sourceLabel(m)}` }),
        el('div', { class: 'module-actions' }, ...actions)));
  }

  // ------------------------------------------------------ details dialog
  function details(m0: LibraryModule): void {
    const box = el('div', { class: 'details' }, el('p', { class: 'muted', text: 'Loading the report…' }));
    const note = el('input', { type: 'text', maxlength: 200, placeholder: 'Note (optional) - e.g. checked by eye at home', 'aria-label': 'Approval note' });
    const d = modal(m0.displayName, [box], [
      { value: 'close', label: 'Close' },
      { value: 'revoke', label: 'Revoke approval', kind: 'danger' },
      { value: 'validate', label: 'Validate again' },
      { value: 'approve', label: 'Approve this version', kind: 'primary' },
    ], { wide: true, testId: 'module-dialog' });
    d.dialog.querySelector('form')!.addEventListener('submit', (e) => {
      const v = (e as SubmitEvent).submitter as HTMLButtonElement | null;
      if (v?.value === 'approve' || v?.value === 'validate' || v?.value === 'revoke') {
        e.preventDefault();           // keep the dialog; act, then refresh it
        const m = library.modules.find((x) => x.id === m0.id) ?? m0;
        if (v.value === 'approve') void approve(m, note.value).then((ok) => { if (ok) d.dialog.close('done'); });
        else if (v.value === 'validate') void validate(m);
        else void revoke(m);
      }
    });

    const refresh = async () => {
      const m = library.modules.find((x) => x.id === m0.id) ?? m0;
      const ph = phase(m);
      let rep: ValidationReport | null = null;
      try {
        rep = ctx.bridge.isOpen ? await report(m.id) : null;
      } catch { /* shown below */ }
      const current = rep && rep.version === m.version ? rep : null;
      d.buttons.approve.hidden = ph === 'approved';
      d.buttons.approve.disabled = !(ph === 'ready' && current && current.result !== 'fail');
      d.buttons.revoke.hidden = !(ph === 'approved' || ph === 'blocked' || m.approved.startsWith('stale'));
      d.buttons.validate.disabled = validating !== null || !ctx.bridge.isOpen;
      d.buttons.validate.textContent = current ? 'Validate again' : 'Validate';
      const issues = current?.checks.filter((c) => c.status !== 'pass') ?? [];
      const all = current?.checks ?? [];
      const showAll = el('details', {}, el('summary', { text: `All ${all.length} checks` }),
        el('ul', { class: 'checks' }, ...all.map(checkRow)));
      box.replaceChildren(...nodes(
        el('div', { class: 'detail-head' },
          el('span', { class: `badge ${PHASE[ph].badge}`, text: PHASE[ph].label }),
          el('span', { class: 'muted small', text: `${m.id} · ${m.version} · ${ctx.slotTitle(m.type)} · from ${sourceLabel(m)}` })),
        el('p', { class: 'muted', text: PHASE[ph].hint + '.' }),
        current
          ? el('div', { class: 'report' },
            el('p', {}, el('strong', { text: `Validation ${current.result === 'pass' ? 'passed' : current.result === 'warn' ? 'passed with warnings' : 'failed'}` }),
              el('span', { class: 'muted small', text: `  ${current.finished ?? ''}${current.touchdesigner ? ' · TouchDesigner ' + current.touchdesigner : ''}` })),
            perfLine(current),
            issues.length ? el('ul', { class: 'checks' }, ...issues.map(checkRow)) : el('p', { class: 'muted small', text: 'Every check passed.' }),
            all.length ? showAll : null)
          : el('p', { class: 'muted', text: rep ? `The last report is for version ${rep.version}; this is ${m.version}. Validate this version.` : 'No validation report for this version yet.' }),
        validating === m.id ? el('p', { class: 'banner', text: 'Validating now… (about 10 s)' }) : null,
        ph === 'ready' && current ? el('div', { class: 'approve-box' },
          el('p', { class: 'small', text: 'Approving lets this exact version be used in shows. Anyone can publish packs, so approve only what you have looked at - load it after approving and check it on screen before the set.' }),
          note) : null,
        ph !== 'approved' && !current ? el('p', { class: 'hint', text: VALIDATE_NOTE }) : null,
      ));
    };
    openDetails = { id: m0.id, refresh: () => { void refresh(); } };
    d.result.then(() => { if (openDetails?.id === m0.id) openDetails = null; });
    void refresh();
  }

  const checkRow = (c: ValidationReport['checks'][number]) =>
    el('li', { class: `chk chk-${c.status}` }, el('span', { class: 'check-status', text: c.status }),
      el('span', { class: 'check-name', text: `${c.stage} · ${c.check}` }), el('span', { class: 'check-detail muted small', text: c.detail }));
  const perfLine = (r: ValidationReport) => {
    const avg = r.performance?.cook_ms_avg, peak = r.performance?.cook_ms_peak;
    return avg !== undefined ? el('p', { class: 'muted small', text: `Cook time ${avg} ms average, ${peak} ms peak (budget 4 ms)` }) : null;
  };

  // ----------------------------------------------------------- packs
  function renderPacks(): void {
    const host = $('packs');
    host.replaceChildren(...packs.map((p) => el('div', { class: 'pack-row', dataset: { pack: p.id } },
      el('div', { class: 'pack-meta' },
        el('strong', { text: p.pack?.displayName ?? p.id }),
        el('span', { class: 'muted small', text: `${p.id} · ${p.version} · ${p.modules.length} module${p.modules.length === 1 ? '' : 's'}${p.pack?.author ? ' · by ' + p.pack.author : ''} · installed ${p.installed.slice(0, 10)}` })),
      el('button', { class: 'btn btn-small btn-quiet', text: 'Remove', dataset: { test: `remove-${p.id}` }, onclick: () => removePack(p) }))));
    if (!packs.length) host.append(el('p', { class: 'hint', text: 'No creator packs installed.' }));
  }

  async function installFrom(path: string | null): Promise<void> {
    if (!path) return;
    const body = el('div', { class: 'details' }, el('p', { class: 'muted', text: 'Checking the pack…' }));
    const force = el('input', { type: 'checkbox' });
    const forceRow = el('label', { class: 'check', hidden: true }, force, el('span', { text: 'Reinstall over the installed version' }));
    const d = modal('Install a creator pack', [body, forceRow], [
      { value: 'cancel', label: 'Cancel' }, { value: 'install', label: 'Install', kind: 'primary', disabled: true },
    ], { wide: true, testId: 'pack-dialog' });
    const r = await ctx.api.inspectPack(path).catch((e: Error): PackResult => ({ ok: false, command: 'verify', message: e.message }));
    if (!d.dialog.open) return;
    const p = r.pack;
    const fails = (r.checks ?? []).filter((c) => c.status === 'fail');
    const warns = (r.checks ?? []).filter((c) => c.status === 'warn');
    const newer = !!(r.installed && p && cmpVer(p.version, r.installed) <= 0);
    body.replaceChildren(...nodes(
      p ? el('div', { class: 'detail-head' },
        el('strong', { text: `${p.displayName ?? p.id} ${p.version}` }),
        el('span', { class: 'muted small', text: `${p.id}${p.author ? ' · by ' + p.author : ''}${p.license ? ' · ' + p.license : ''}` })) : null,
      p?.description ? el('p', { text: p.description }) : null,
      p ? el('p', { class: 'small', text: `${p.modules.length} module${p.modules.length === 1 ? '' : 's'} (${p.modules.map((x) => x.id).join(', ')})${p.palettes ? `, ${p.palettes} palette${p.palettes === 1 ? '' : 's'}` : ''}.` }) : null,
      el('p', { class: r.ok ? 'small ok-text' : 'small danger-text', text: r.ok
        ? `Passed ${r.checks?.length ?? 0} safety checks${warns.length ? ` (${warns.length} warning${warns.length === 1 ? '' : 's'})` : ''}: safe archive, file hashes match, no Python, no absolute paths.`
        : `It cannot be installed: ${r.message ?? 'the pack failed its checks'}.` }),
      fails.length || warns.length ? el('ul', { class: 'checks' }, ...[...fails, ...warns].map((c) => checkRow({ stage: 'pack', ...c }))) : null,
      r.installed ? el('p', { class: 'small', text: `Version ${r.installed} is installed.${newer ? ' This file is not newer.' : ' This will upgrade it.'}` }) : null,
      el('p', { class: 'hint', text: p?.signature ? 'Signed pack.' : 'Unsigned: anyone can publish packs. Installing only adds its modules to the library - each one must still pass validation and be approved by you before it can be used.' }),
    ));
    forceRow.hidden = !newer;
    const updateBtn = () => { d.buttons.install.disabled = !r.ok || (newer && !force.checked); };
    force.addEventListener('change', updateBtn);
    updateBtn();
    if ((await d.result) !== 'install') return;
    const res = await ctx.api.installPack(path, force.checked).catch((e: Error): PackResult => ({ ok: false, command: 'install', message: e.message }));
    if (!res.ok) return toast(`Not installed: ${res.message ?? 'unknown error'}`);
    await loadPacks();
    const name = `${p?.displayName ?? p?.id} ${p?.version}`;
    if (!ctx.bridge.isOpen) return toast(`Installed ${name}. Connect TouchDesigner and press Rescan to see its modules.`, 'info');
    await rescan();
    const mine = library.modules.filter((m) => p?.modules.some((x) => x.id === m.id));
    const waiting = mine.filter((m) => m.approved !== 'yes');
    toast(waiting.length
      ? `Installed ${name}. ${waiting.length} module${waiting.length === 1 ? '' : 's'} need${waiting.length === 1 ? 's' : ''} validating and approving before use: ${waiting.map((m) => m.displayName).join(', ')}.`
      : `Installed ${name}. ${mine.length === 1 ? 'Its module is' : 'Its modules are'} already approved for this version.`, 'info');
  }

  async function removePack(p: InstalledPack): Promise<void> {
    const ids = new Set(p.modules.map((x) => x.id));
    const s = ctx.state();
    const used = s ? SLOTS.filter((slot) => ids.has(s.slots[slot]?.module ?? '')) : [];
    if (used.length) {
      toast(`${p.pack?.displayName ?? p.id} is in use on the ${used.map(ctx.slotTitle).join(' and ')} layer - switch ${used.length === 1 ? 'it' : 'them'} to another module first.`);
      return;
    }
    const ask = modal(`Remove ${p.pack?.displayName ?? p.id}?`, [
      el('p', { text: `Its ${p.modules.length} module${p.modules.length === 1 ? '' : 's'} and any palettes leave the library. You can install the pack again later; its approvals are kept but only count for the same version.` }),
    ], [{ value: 'cancel', label: 'Keep it' }, { value: 'ok', label: 'Remove', kind: 'danger' }], { testId: 'remove-dialog' });
    if ((await ask.result) !== 'ok') return;
    const res = await ctx.api.removePack(p.id).catch((e: Error): PackResult => ({ ok: false, command: 'remove', message: e.message }));
    if (!res.ok) return toast(`Not removed: ${res.message}`);
    toast(`Removed ${p.pack?.displayName ?? p.id}`, 'info');
    await loadPacks();
    if (ctx.bridge.isOpen) await rescan();
  }

  async function rescan(): Promise<void> {
    const b = $<HTMLButtonElement>('rescan');
    b.disabled = true;
    b.textContent = 'Scanning…';
    try {
      await load(true);
    } finally {
      b.disabled = false;
      b.textContent = 'Rescan';
    }
  }

  // ------------------------------------------------------------ setup
  function setup(): void {
    $('rescan').addEventListener('click', () => { void rescan(); });
    $('pack-install').addEventListener('click', async () => installFrom(await ctx.api.pickPack()));
    // drop a .dgpack anywhere on the window
    let depth = 0;
    const overlay = $('drop-overlay');
    const hasFiles = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].includes('Files');
    window.addEventListener('dragenter', (e) => { if (hasFiles(e)) { depth++; overlay.hidden = false; } });
    window.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) overlay.hidden = true; });
    window.addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
    window.addEventListener('drop', async (e) => {
      e.preventDefault();
      depth = 0;
      overlay.hidden = true;
      const f = e.dataTransfer?.files?.[0];
      if (!f) return;
      if (!f.name.toLowerCase().endsWith('.dgpack')) return toast('Only DeckGlow packs (.dgpack) can be dropped here');
      await installFrom(await ctx.api.packFromFile(f));
    });
    renderPacks();
    render();
  }

  return {
    setup, load, loadPacks, onEvent, render, install: installFrom,
    get library() { return library; },
    get validating() { return validating; },
  };
}

const nodes = (...xs: (Node | null | undefined | false)[]): Node[] => xs.filter(Boolean) as Node[];

function cmpVer(a: string, b: string): number {
  const pa = a.split(/[.+-]/).map(Number), pb = b.split(/[.+-]/).map(Number);
  for (let i = 0; i < 3; i++) if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) - (pb[i] || 0);
  return 0;
}
