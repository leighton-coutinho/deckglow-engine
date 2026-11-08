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
  version: string;
}

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
}
