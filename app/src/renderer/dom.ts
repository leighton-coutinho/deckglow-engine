// Small DOM helpers shared by the app's panels.

type Child = Node | string | null | undefined | false;

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K, props: Record<string, any> = {}, ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(node.dataset, v);
    else if (k in node && typeof v !== 'string') (node as any)[k] = v;
    else node.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of children) if (c) node.append(c);
  return node;
}

export const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

export function toast(text: string, kind: 'error' | 'info' = 'error'): void {
  const t = el('div', { class: `toast toast-${kind}`, role: kind === 'error' ? 'alert' : 'status', text });
  $('toasts').append(t);
  setTimeout(() => { t.classList.add('gone'); setTimeout(() => t.remove(), 400); }, kind === 'error' ? 6000 : 4000);
}

/** A modal built on <dialog>. Resolves with the value of the button pressed, or 'cancel'. */
export function modal(title: string, body: Node[], buttons: { value: string; label: string; kind?: 'danger' | 'primary'; disabled?: boolean }[],
  opts: { wide?: boolean; testId?: string } = {}): { dialog: HTMLDialogElement; result: Promise<string>; buttons: Record<string, HTMLButtonElement> } {
  const btns: Record<string, HTMLButtonElement> = {};
  const row = el('div', { class: 'row end' }, ...buttons.map((b) => {
    const node = el('button', { value: b.value, class: `btn${b.kind ? ' btn-' + b.kind : ''}`, text: b.label, disabled: b.disabled });
    btns[b.value] = node;
    return node;
  }));
  const dialog = el('dialog', { class: opts.wide ? 'wide' : undefined, dataset: opts.testId ? { test: opts.testId } : undefined },
    el('form', { method: 'dialog' }, el('h3', { text: title }), ...body, row));
  document.body.append(dialog);
  const result = new Promise<string>((resolve) => {
    dialog.addEventListener('close', () => { resolve(dialog.returnValue || 'cancel'); setTimeout(() => dialog.remove(), 0); });
  });
  dialog.showModal();
  return { dialog, result, buttons: btns };
}
