// Rate-limits the audio engine's console output on its way to the window.
//
// The engine rewrites one readout line ("Drive: ... BPM: ...\r") for every
// audio block - about 100 a second. Forwarding each one flooded the page with
// IPC messages, and the page refreshed Setup (spawning tasklist) on each: in
// minutes hundreds of tasklist processes exhausted Windows' threads,
// TouchDesigner fell to 6 fps and the window stopped repainting (2026-11-09).
//
// Here every other line (start-up messages, errors) passes through, but at
// most `maxPerFlush` per flush, and readout lines collapse into the newest one.
// No electron import: unit-tested under Node (test/linegate.test.mjs).

export const isReadout = (line: string) => /^Drive:\s/.test(line);

export class LineGate {
  private pending: string[] = [];
  private readout: string | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  dropped = 0;

  constructor(private emit: (line: string) => void, private intervalMs = 500, private maxPerFlush = 5) {}

  push(line: string): void {
    if (isReadout(line)) {
      if (this.readout !== null) this.dropped++;
      this.readout = line;                     // only the newest readout matters
    } else if (this.pending.length < this.maxPerFlush) {
      this.pending.push(line);
    } else {
      this.dropped++;
    }
    if (!this.timer) this.timer = setTimeout(() => this.flush(), this.intervalMs);
  }

  flush(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const out = [...this.pending, ...(this.readout !== null ? [this.readout] : [])];
    this.pending = [];
    this.readout = null;
    for (const l of out) this.emit(l);
  }
}
