// deckglow.control/1 client (docs/FRONTEND_MESSAGE_CONTRACT.md).
//
// Plain WebSocket, no Node APIs, so the same file runs in the app's page and
// under Node's built-in WebSocket for the tests. It authenticates with the
// token, matches replies to requests by id (state broadcasts carry no id),
// reconnects with backoff, and re-sends its subscriptions after every reconnect.

import { PROTOCOL } from '../shared/api.js';
import type { Library, RuntimeStatus, ShowState } from '../shared/api.js';

export type Connection =
  | { phase: 'connecting'; attempt: number }
  | { phase: 'open'; runtimeApi?: string }
  | { phase: 'offline'; reason: string; retryInMs: number }
  | { phase: 'auth-failed'; reason: string; retryInMs: number }
  | { phase: 'stopped' };

export class BridgeRequestError extends Error {
  constructor(public code: string, message: string) {
    super(message);
    this.name = 'BridgeRequestError';
  }
}

export interface BridgeOptions {
  url: string;
  token: () => Promise<string | null>;
  client?: string;
  binaryType?: 'blob' | 'arraybuffer';
  requestTimeoutMs?: number;
  onConnection?: (c: Connection) => void;
  onState?: (s: ShowState) => void;
  onStatus?: (s: RuntimeStatus) => void;
  onPreview?: (frame: Blob | ArrayBuffer) => void;
  /** Other runtime-initiated messages: validation progress, libraryChanged. */
  onEvent?: (m: { type: string; [k: string]: any }) => void;
}

type Pending = { resolve: (m: any) => void; reject: (e: Error) => void; timer: ReturnType<typeof setTimeout> };

export interface Subscription {
  status: boolean;
  preview: { fps: number; width: number } | false;
}

export class BridgeClient {
  private ws: WebSocket | null = null;
  private nextId = 1;
  private pending = new Map<number, Pending>();
  private attempt = 0;
  private stopped = true;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private authenticated = false;
  private subs: Subscription = { status: false, preview: false };
  state: ShowState | null = null;
  connection: Connection = { phase: 'stopped' };

  constructor(private opts: BridgeOptions) {}

  get isOpen(): boolean {
    return this.authenticated && this.ws?.readyState === WebSocket.OPEN;
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.ws?.close();
    this.ws = null;
    this.setConnection({ phase: 'stopped' });
  }

  /** Subscriptions persist across reconnects. */
  async subscribe(next: Partial<Subscription>): Promise<void> {
    this.subs = { ...this.subs, ...next };
    if (this.isOpen) await this.request({ type: 'subscribe', ...next });
  }

  /** Sends a request; resolves with the reply, rejects with BridgeRequestError on an error reply. */
  request<T = any>(msg: Record<string, unknown>): Promise<T> {
    if (!this.isOpen) return Promise.reject(new BridgeRequestError('offline', 'not connected to the runtime'));
    return this.rawRequest<T>(msg);
  }

  // ------------------------------------------------------------- internals
  private setConnection(c: Connection): void {
    this.connection = c;
    this.opts.onConnection?.(c);
  }

  private rawRequest<T>(msg: Record<string, unknown>): Promise<T> {
    const id = this.nextId++;
    const ws = this.ws;
    return new Promise<T>((resolve, reject) => {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        reject(new BridgeRequestError('offline', 'not connected to the runtime'));
        return;
      }
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new BridgeRequestError('timeout', `no reply to ${String(msg.type)}`));
      }, this.opts.requestTimeoutMs ?? 10000);
      this.pending.set(id, { resolve, reject, timer });
      ws.send(JSON.stringify({ ...msg, id }));
    });
  }

  private async connect(): Promise<void> {
    if (this.stopped) return;
    this.attempt++;
    this.setConnection({ phase: 'connecting', attempt: this.attempt });
    let token: string | null = null;
    try {
      token = await this.opts.token();
    } catch {
      token = null;
    }
    if (!token) {
      this.retry('auth-failed', 'no bridge token found (touchDesigner/bridge_token.txt) - build the control bridge first');
      return;
    }
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.opts.url);
    } catch (e) {
      this.retry('offline', String(e));
      return;
    }
    ws.binaryType = this.opts.binaryType ?? 'blob';
    this.ws = ws;
    let authFailure: string | null = null;

    ws.onopen = async () => {
      try {
        const welcome = await this.rawRequest<any>({
          type: 'hello', token, client: this.opts.client ?? 'deckglow-app/0.1', protocol: PROTOCOL,
        });
        if (welcome.type !== 'welcome') throw new BridgeRequestError('protocol', 'unexpected reply to hello');
        this.authenticated = true;
        this.attempt = 0;
        this.state = welcome.state;
        this.setConnection({ phase: 'open', runtimeApi: welcome.runtimeApi });
        if (welcome.state) this.opts.onState?.(welcome.state);
        if (this.subs.status || this.subs.preview) {
          await this.rawRequest({ type: 'subscribe', status: this.subs.status, preview: this.subs.preview });
        }
      } catch (e) {
        authFailure = e instanceof BridgeRequestError && e.code === 'unauthenticated'
          ? 'the runtime refused the token - TouchDesigner may have made a new one; retrying'
          : `handshake failed: ${(e as Error).message}`;
        ws.close();
      }
    };

    ws.onmessage = (ev: MessageEvent) => {
      if (typeof ev.data !== 'string') {
        this.opts.onPreview?.(ev.data as Blob | ArrayBuffer);
        return;
      }
      let m: any;
      try {
        m = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (m.id !== undefined && m.id !== null && this.pending.has(m.id)) {
        const p = this.pending.get(m.id)!;
        this.pending.delete(m.id);
        clearTimeout(p.timer);
        if (m.type === 'error') p.reject(new BridgeRequestError(m.code, m.error));
        else p.resolve(m);
        if (m.type === 'state' && m.state) {      // a getState reply is also fresh state
          this.state = m.state;
          this.opts.onState?.(m.state);
        }
        return;
      }
      if (m.type === 'state' && m.state) {
        this.state = m.state;
        this.opts.onState?.(m.state);
      } else if (m.type === 'status' && m.status) {
        this.opts.onStatus?.(m.status);
      } else if (typeof m.type === 'string') {
        this.opts.onEvent?.(m);
      }
    };

    ws.onclose = () => {
      const wasOpen = this.authenticated;
      this.authenticated = false;
      if (this.ws === ws) this.ws = null;
      for (const [, p] of this.pending) {
        clearTimeout(p.timer);
        p.reject(new BridgeRequestError('offline', 'connection closed'));
      }
      this.pending.clear();
      if (this.stopped) return;
      if (authFailure) this.retry('auth-failed', authFailure);
      else this.retry('offline', wasOpen ? 'the runtime closed the connection' : 'TouchDesigner is not running, or the control bridge is not built');
    };

    ws.onerror = () => { /* onclose follows and handles it */ };
  }

  private retry(phase: 'offline' | 'auth-failed', reason: string): void {
    if (this.stopped) return;
    const retryInMs = phase === 'auth-failed' ? 3000 : Math.min(5000, 400 * 2 ** Math.min(this.attempt, 4));
    this.setConnection({ phase, reason, retryInMs });
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = setTimeout(() => { this.retryTimer = null; void this.connect(); }, retryInMs);
  }

  // ------------------------------------------------------------- helpers
  getLibrary(rescan = false): Promise<Library> {
    return this.request<any>({ type: 'getLibrary', rescan }).then((r) => ({ modules: r.modules, palettes: r.palettes }));
  }
}
