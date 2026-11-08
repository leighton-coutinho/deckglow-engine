// Exposes a small, fixed API to the sandboxed page as window.deckglow.
// No Node, no ipcRenderer, no arbitrary channels reach the page.

import { contextBridge, ipcRenderer } from 'electron';
import type { DeckglowApi } from '../shared/api';

const api: DeckglowApi = {
  config: () => ipcRenderer.invoke('deckglow:config'),
  token: () => ipcRenderer.invoke('deckglow:token'),
  contract: () => ipcRenderer.invoke('deckglow:contract'),
  thumbnail: (p) => ipcRenderer.invoke('deckglow:thumbnail', p),
  saveShow: (show) => ipcRenderer.invoke('deckglow:saveShow', show),
  openShow: () => ipcRenderer.invoke('deckglow:openShow'),
  smokeDone: (result) => ipcRenderer.invoke('deckglow:smokeDone', result),
};

contextBridge.exposeInMainWorld('deckglow', api);
