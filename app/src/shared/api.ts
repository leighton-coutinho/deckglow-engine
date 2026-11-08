// Types shared by the main process, the preload and the renderer.
// The show and message shapes follow docs/FRONTEND_MESSAGE_CONTRACT.md.

export const PROTOCOL = 'deckglow.control/1';
export const SHOW_SCHEMA = 'deckglow.show/1';
export const CONFIRM_STROBE = 'venue-allows-strobing';

export type SlotName = 'base_scene' | 'hit_fx' | 'brand_overlay' | 'finish_fx';
export const SLOTS: SlotName[] = ['base_scene', 'hit_fx', 'brand_overlay', 'finish_fx'];

export type ControlValue = number | boolean | string | number[];

export interface SlotState {
  module: string | null;
  enabled: boolean;
  intensity: number;
  controls: Record<string, ControlValue>;
}

export interface ShowState {
  schema: string;
  slots: Record<SlotName, SlotState>;
  performer: Record<string, number>;
  palette: { index?: number; name?: string };
  background: [number, number, number] | null;
  brand: { displayName?: string; mode?: string; subtitle?: string; scale?: number; opacity?: number };
  output: { blackout?: boolean; maxBrightness?: number; flashLimit?: boolean; maxFlashes?: number };
  engine: { mode?: 'live' | 'demo'; bpm?: number };
  /** The look bank: 16 entries, null where empty (present once the look runtime is built). */
  looks?: (LookEntry | null)[];
  transition?: Transition;
  take?: TakeState;
}

export const BANK_SIZE = 16;
export type Quantize = 'now' | 'beat' | 'bar';
export interface Transition { fade: number; quantize: Quantize }
/** A look: the Scene and Hits layers, palette and background (owner's choice, 2026-11-07). */
export interface Look {
  slots: Partial<Record<'base_scene' | 'hit_fx', SlotState>>;
  palette: string | null;
  background: [number, number, number] | null;
}
export interface LookEntry { name: string; look: Look }
export interface TakeState {
  phase: 'idle' | 'loading' | 'armed' | 'fading';
  index: number | null;
  current: number | null;
  problems: string[];
  progress?: number;
}

/** Saved by the main process in the app's settings file. */
export interface AppSettings {
  midi?: MidiSettings;
}
export interface MidiBinding { type: 'note' | 'cc'; channel: number; number: number }
export interface MidiSettings {
  enabled: boolean;
  /** Input device name, or null for every input. */
  input: string | null;
  bindings: Record<string, MidiBinding>;
}

/** A creative control as declared in a module.json. */
export interface ControlDecl {
  parameter: string;
  label?: string;
  type: 'float' | 'integer' | 'toggle' | 'menu' | 'color';
  min?: number;
  max?: number;
  default?: ControlValue;
  options?: string[];
  group?: string;
}

export interface LibraryModule {
  id: string;
  type: SlotName | string;
  version: string;
  displayName: string;
  source: string;
  static: string;
  quarantine: string;
  approved: string;
  thumbnail: string;
  controls: ControlDecl[];
}

export interface Library {
  modules: LibraryModule[];
  palettes: string[];
}

export interface RuntimeStatus {
  fps?: number;
  slots?: Record<string, { status?: string; cookMs?: number }>;
  limiter?: { held?: number | null; transitions?: number | null; gain?: number | null };
  lanes?: Record<string, number>;
  take?: TakeState & { active?: 'a' | 'b' };
}

/** The parts of the frozen module contract the app shows. */
export interface ContractInfo {
  slotParameters: Record<string, ControlDecl[]>;
  performer: string[];
  lanes: { name: string; range: [number, number]; kind: string }[];
}

export interface AppConfig {
  url: string;
  root: string | null;
  smoke: boolean;
  /** Smoke runs only: a pack file registered as if picked, to install and remove. */
  smokePack?: string | null;
  /** Smoke runs only: test the first-run install instead of the show. */
  smokeSetup?: boolean;
  /** With smokeSetup: also open TouchDesigner on the installed runtime and check it. */
  smokeLaunch?: boolean;
  version: string;
}

/** pack.json details shown before installing (pack_tool.py --json). */
export interface PackMeta {
  id: string; displayName?: string; author?: string; version: string; description?: string;
  license?: string | null; homepage?: string | null; runtimeApi?: string; signature?: unknown;
  modules: { folder: string; id: string; version: string }[];
  palettes: number;
}
export interface PackCheck { status: 'pass' | 'warn' | 'fail'; check: string; detail: string }
/** One pack_tool.py --json result. */
export interface PackResult {
  ok: boolean; command: string; message?: string; code?: string; status?: string;
  checks?: PackCheck[]; pack?: PackMeta | null; installed?: string | null; previous?: string | null;
  packs?: InstalledPack[]; log?: string[];
}
export interface InstalledPack {
  id: string; version: string; installed: string; from?: string; modules: PackMeta['modules']; pack: PackMeta | null;
}

/** A quarantine report as the bridge sends it (getReport, validation done). */
export interface ValidationReport {
  module: string; version: string; type: string; result: 'pass' | 'warn' | 'fail';
  started?: string; finished?: string; touchdesigner?: string;
  performance: { cook_ms_avg?: number; cook_ms_peak?: number; [k: string]: unknown };
  checks: { stage: string; check: string; status: string; detail: string }[];
}

/** Where the runtime and engine are, and what setup still has to do (main/runtime.ts). */
export interface SetupInfo {
  mode: 'repository' | 'installed' | 'custom';
  root: string | null;
  installed: boolean;
  version: string | null;
  bundledVersion: string | null;
  updateAvailable: boolean;
  project: string | null;
  touchDesigner: { exe: string | null; version: string | null };
  touchDesignerRunning: boolean;
  engine: { exe: string | null; running: boolean; startedByApp: boolean };
}
export type EngineEvent = { type: 'log'; line: string } | { type: 'exit'; code: number | null };

/** What the preload exposes as window.deckglow. Every call goes through IPC. */
export interface DeckglowApi {
  config(): Promise<AppConfig>;
  /** Re-read on every connection, so a token TouchDesigner re-created is picked up. */
  token(): Promise<string | null>;
  contract(): Promise<ContractInfo | null>;
  /** A module thumbnail as a data: URL, or null. Only PNGs inside the runtime folder. */
  thumbnail(path: string): Promise<string | null>;
  saveShow(show: ShowState): Promise<string | null>;
  openShow(): Promise<{ path: string; show: ShowState } | null>;
  smokeDone(result: { ok: boolean; steps: string[] }): Promise<void>;
  /** Creator packs - pack_tool.py run by the main process. Only files the person
   *  picked in the dialog, or dropped on the window, can be inspected or installed. */
  pickPack(): Promise<string | null>;
  packFromFile(file: File): Promise<string | null>;
  inspectPack(path: string): Promise<PackResult>;
  installPack(path: string, force: boolean): Promise<PackResult>;
  removePack(id: string): Promise<PackResult>;
  listPacks(): Promise<PackResult>;
  /** App settings (MIDI mapping), kept in the app's user-data folder. */
  getSettings(): Promise<AppSettings>;
  setSettings(settings: AppSettings): Promise<void>;
  /** Setup: the runtime folder, TouchDesigner and the audio engine. */
  setupInfo(): Promise<SetupInfo>;
  installRuntime(): Promise<string>;
  updateRuntime(): Promise<{ root: string; backup: string }>;
  launchTouchDesigner(): Promise<{ rotatedToken: boolean }>;
  browseTouchDesigner(): Promise<string | null>;
  startEngine(): Promise<void>;
  stopEngine(): Promise<void>;
  engineLog(): Promise<string[]>;
  onEngine(cb: (ev: EngineEvent) => void): void;
}
