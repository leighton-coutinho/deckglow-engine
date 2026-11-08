# DeckGlow desktop app

The control surface a DJ uses: a live preview of the projector output, a
switch per layer (Scene, Hits, Name, Finish), the background colour, palette,
name, performance faders, output safety, the module library and show files.

It drives the TouchDesigner runtime over `deckglow.control/1`
([docs/FRONTEND_MESSAGE_CONTRACT.md](../docs/FRONTEND_MESSAGE_CONTRACT.md)) and
holds no show logic of its own: every control sends a named request, and the
screen is redrawn from the state the runtime broadcasts back.

Electron 44 + TypeScript 6, no bundler and no runtime dependencies.

## Run it

You need Node.js 22 or newer, and TouchDesigner with the DeckGlow project
open and its control bridge built (`touchDesigner/tools/build_control_bridge.py`).

```powershell
cd app
npm install
npm start
```

The app finds the runtime folder by walking up from itself to
`touchDesigner/engine_input_block1.toe` (override with `DECKGLOW_ROOT`), reads
the bridge token from `touchDesigner/bridge_token.txt` on every connection,
and connects to `ws://127.0.0.1:9980/` (override with `DECKGLOW_PORT`). If
TouchDesigner is closed it says so and keeps retrying.

## Work on it without TouchDesigner

`npm run mock` starts `touchDesigner/tools/mock_bridge.py`, a stand-in bridge
that runs the runtime's **real** protocol code (`bridge_protocol.py`) with an
in-memory show, the real module library and approvals, and a preview that
shows the base module's thumbnail or the background colour. It refuses to
start while TouchDesigner's bridge holds the port.

```powershell
npm run mock        # terminal 1
npm start           # terminal 2
```

`npm run web` serves the same UI at `http://127.0.0.1:5174/` for working on it
in a browser; `/dev/` endpoints stand in for the Electron preload.

## Checks

| Command | What it proves |
| --- | --- |
| `npm test` | The bridge client against the mock: handshake, broadcasts, `getState` replies, six refusal codes, library, status and preview subscriptions surviving a runtime restart, wrong token reported as such. |
| `npm run smoke` | The real window against whatever runtime is running (TouchDesigner or the mock): clicks the real switches, sliders, menus, the flash-limiter dialog and Blackout, checks each change comes back in the broadcast state, restores the starting show, then saves a screenshot and log to `out/smoke.png` / `out/smoke.json`. Exit code 0 = pass. |

## How it is put together

```
src/main/main.ts      main process: window, app:// scheme, token/contract/thumbnail reads, show dialogs
src/main/preload.ts   window.deckglow - a fixed IPC API, nothing else reaches the page
src/shared/api.ts     show, library and API types shared by both sides
src/renderer/
  bridge.ts           deckglow.control/1 client: auth, request ids, reconnect, subscriptions
  app.ts              the control surface
  platform.ts         window.deckglow, or the dev server in a browser
  smoke.ts            the smoke run
```

Security: the page is sandboxed (`contextIsolation`, `sandbox`, no Node), served
from `app://deckglow/` with a strict CSP that allows WebSocket connections to
`127.0.0.1` only; navigation and new windows are blocked and every permission
request is refused. Thumbnails are read only as PNGs inside `touchDesigner/`.
Show files are checked for `"schema": "deckglow.show/1"` before the runtime
sees them, and the runtime validates every field again.

## Not yet

- Launching TouchDesigner, and writing a fresh token before it starts (the
  contract's intended order) - for now, open the project yourself.
- Installer and setup wizard, crossfades/looks, MIDI.
