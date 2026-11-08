// The app's access to the machine: window.deckglow (preload) inside Electron,
// or the development server's /dev/ endpoints when the page is opened in a
// browser with `npm run web` (UI work without launching Electron).

import type { AppConfig, ContractInfo, DeckglowApi, PackResult, ShowState } from '../shared/api.js';

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
    // packs: the dev server keeps uploaded files and runs pack_tool.py on them
    pickPack: () => new Promise((resolve) => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.dgpack';
      input.onchange = async () => resolve(input.files?.[0] ? await upload(input.files[0]) : null);
      input.click();
    }),
    packFromFile: (file) => upload(file),
    inspectPack: async (p) => (await json<PackResult>(`/dev/pack/inspect?path=${encodeURIComponent(p)}`))!,
    installPack: async (p, force) => (await post<PackResult>(`/dev/pack/install?path=${encodeURIComponent(p)}${force ? '&force=1' : ''}`))!,
    removePack: async (id) => (await post<PackResult>(`/dev/pack/remove?id=${encodeURIComponent(id)}`))!,
    listPacks: async () => (await json<PackResult>('/dev/pack/list'))!,
    // in a browser the settings live in this origin's localStorage
    getSettings: async () => {
      try { return JSON.parse(localStorage.getItem('deckglow-settings') || '{}'); } catch { return {}; }
    },
    setSettings: async (s) => {
      try { localStorage.setItem('deckglow-settings', JSON.stringify(s)); } catch { /* private window */ }
    },
    // setup and launching need the desktop app
    setupInfo: async () => ({
      mode: 'repository', root: null, installed: true, version: null, bundledVersion: null, updateAvailable: false,
      project: null, touchDesigner: { exe: null, version: null }, touchDesignerRunning: false,
      engine: { exe: null, running: false, startedByApp: false },
    }),
    installRuntime: async () => { throw new Error('setup runs in the desktop app'); },
    updateRuntime: async () => { throw new Error('setup runs in the desktop app'); },
    launchTouchDesigner: async () => { throw new Error('launching TouchDesigner needs the desktop app'); },
    browseTouchDesigner: async () => null,
    startEngine: async () => { throw new Error('starting the engine needs the desktop app'); },
    stopEngine: async () => undefined,
    engineLog: async () => [],
    onEngine: () => undefined,
  };
}

async function post<T>(url: string, body?: BodyInit): Promise<T | null> {
  const r = await fetch(url, { method: 'POST', body });
  return r.ok ? ((await r.json()) as T) : null;
}

async function upload(file: File): Promise<string | null> {
  if (!file.name.toLowerCase().endsWith('.dgpack')) return null;
  const r = await post<{ path: string }>(`/dev/pack/upload?name=${encodeURIComponent(file.name)}`, file);
  return r?.path ?? null;
}

export const api: DeckglowApi = window.deckglow ?? devApi();
export const inElectron = !!window.deckglow;
