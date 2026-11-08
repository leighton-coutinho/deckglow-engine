// Exposes a small, fixed API to the sandboxed page as window.deckglow.
// No Node, no ipcRenderer, no arbitrary channels reach the page.

import { contextBridge, ipcRenderer, webUtils } from 'electron';
import type { DeckglowApi } from '../shared/api';

const api: DeckglowApi = {
  config: () => ipcRenderer.invoke('deckglow:config'),
  token: () => ipcRenderer.invoke('deckglow:token'),
  contract: () => ipcRenderer.invoke('deckglow:contract'),
  thumbnail: (p) => ipcRenderer.invoke('deckglow:thumbnail', p),
  saveShow: (show) => ipcRenderer.invoke('deckglow:saveShow', show),
  openShow: () => ipcRenderer.invoke('deckglow:openShow'),
  smokeDone: (result) => ipcRenderer.invoke('deckglow:smokeDone', result),
  pickPack: () => ipcRenderer.invoke('deckglow:pickPack'),
  // The path comes from a real dropped File; a page cannot make one up.
  packFromFile: (file) => ipcRenderer.invoke('deckglow:dropPack', webUtils.getPathForFile(file)),
  inspectPack: (p) => ipcRenderer.invoke('deckglow:inspectPack', p),
  installPack: (p, force) => ipcRenderer.invoke('deckglow:installPack', p, force),
  removePack: (id) => ipcRenderer.invoke('deckglow:removePack', id),
  listPacks: () => ipcRenderer.invoke('deckglow:listPacks'),
  getSettings: () => ipcRenderer.invoke('deckglow:getSettings'),
  setSettings: (s) => ipcRenderer.invoke('deckglow:setSettings', s),
};

contextBridge.exposeInMainWorld('deckglow', api);
