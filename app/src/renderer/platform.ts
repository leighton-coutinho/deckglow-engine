// The app's access to the machine: window.deckglow (preload) inside Electron,
// or the development server's /dev/ endpoints when the page is opened in a
// browser with `npm run web` (UI work without launching Electron).

import type { AppConfig, ContractInfo, DeckglowApi, ShowState } from '../shared/api.js';

declare global {
  interface Window { deckglow?: DeckglowApi }
}

function devApi(): DeckglowApi {
  const json = async <T>(url: string): Promise<T | null> => {
    const r = await fetch(url, { cache: 'no-store' });
    return r.ok ? ((await r.json()) as T) : null;
  };
  return {
    config: async () => (await json<AppConfig>('/dev/config'))!,
    token: async () => {
      const r = await fetch('/dev/token', { cache: 'no-store' });
      return r.ok ? (await r.text()).trim() || null : null;
    },
    contract: () => json<ContractInfo>('/dev/contract'),
    thumbnail: async (p) => `/dev/thumb?path=${encodeURIComponent(p)}`,
    saveShow: async (show: ShowState) => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([JSON.stringify(show, null, 2)], { type: 'application/json' }));
      a.download = 'show.deckglow.json';
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      return 'show.deckglow.json (download)';
    },
    openShow: () => new Promise((resolve, reject) => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.json,application/json';
      input.onchange = async () => {
        const f = input.files?.[0];
        if (!f) return resolve(null);
        try {
          const show = JSON.parse(await f.text());
          if (show?.schema !== 'deckglow.show/1') throw new Error('not a deckglow.show/1 show file');
          resolve({ path: f.name, show });
        } catch (e) {
          reject(e);
        }
      };
      input.click();
    }),
    smokeDone: async (result) => { console.log('smoke', JSON.stringify(result)); },
  };
}

export const api: DeckglowApi = window.deckglow ?? devApi();
export const inElectron = !!window.deckglow;
