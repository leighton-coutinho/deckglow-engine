# DeckGlow desktop app

The control surface a DJ uses: a live preview of the projector output, a
switch per layer (Scene, Hits, Name, Finish), the background colour, palette,
name, performance faders, output safety, the module library and show files.

**Looks** - 16 pads under the preview. A look is the Scene and Hits layers
(with their controls), the palette and the background colour; the name,
finish, output safety and performance faders stay as they are. Click a pad to
fade to it (Now, on the next Beat or the next Bar; fade 0-10 s), shift-click
to cut, click an empty pad to save what is on screen. Keys 1-0 take looks
1-10, `[` and `]` step through them, `B` is Blackout.

**Controller** - MIDI in the app (Web MIDI; system-exclusive messages are
never requested). Learn: click Learn next to an action, then touch a pad, key
or knob. Pads/keys/CC buttons take looks, step next/previous, toggle
Blackout or a layer; knobs and faders (CCs) drive the six performance faders
and the fade time. The mapping is saved in the app's settings file (in the
user-data folder; `DECKGLOW_SETTINGS` for tests). The app must be open for a
controller to work.

The library installs and removes creator packs (`.dgpack`, from the Install
button or dropped on the window), and validates, reviews and approves each
module version. Installing approves nothing: a module reaches the layer menus
only after it passed quarantine in TouchDesigner and the person approved it
after seeing the report.

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

Packs install into `touchDesigner/Packs/`, where TouchDesigner looks for them,
through `touchDesigner/tools/pack_tool.py` (run with TouchDesigner's bundled
Python, or `DECKGLOW_PYTHON`). `DECKGLOW_PACKS` points installs at another
folder - for tests; TouchDesigner will not see packs there.

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
| `npm test` | 21 tests. Looks through the mock: save, a TAKE on the beat passing loading → armed → fading → idle, a cut, refusals, the bank surviving a show round trip. MIDI mapping: parsing, learn, pads, CC buttons firing once per press, faders, one control per action, device filter, next/previous. The look runtime's TAKE state machine (`test_look_logic.py`). And the earlier ones: The bridge client against the mock: handshake, broadcasts, `getState` replies, six refusal codes, library, status and preview subscriptions surviving a runtime restart, wrong token reported as such. Packs: `pack_tool.py --json` verify / install / refused reinstall / list / broken archive on a throwaway pack, then refused approval, validate (running and done events), approve, load, revoke through the mock, and proof that `approved.json` and `validation/` were not touched. The protocol's own offline test (`test_bridge_protocol.py`). |
| `npm run smoke` | The real window against whatever runtime is running (TouchDesigner or the mock): clicks the real switches, sliders, menus, the flash-limiter dialog and Blackout, checks each change comes back in the broadcast state; with the look runtime, saves two looks on pads 15-16, fades to one and cuts to the other; learns and plays MIDI bindings with synthetic messages (set `DECKGLOW_SETTINGS` to keep it off your real mapping; it restores the mapping either way); restores the starting show and look bank, then saves a screenshot and log to `out/smoke.png` / `out/smoke.json`. Exit code 0 = pass. Add `--smoke-pack=<file.dgpack>` (with `DECKGLOW_PACKS` set to a test folder) to also inspect, install, rescan and remove that pack through the real IPC, and check an unpicked file is refused. |

## How it is put together

```
src/main/main.ts      main process: window, app:// scheme, token/contract/thumbnail reads, show dialogs
src/main/preload.ts   window.deckglow - a fixed IPC API, nothing else reaches the page
src/shared/api.ts     show, library and API types shared by both sides
src/renderer/
  bridge.ts           deckglow.control/1 client: auth, request ids, reconnect, subscriptions
  app.ts              the control surface
  library.ts          library and packs: install, remove, validate, review, approve, revoke
  looks.ts            the 16 look pads, transition settings, TAKE, keyboard
  midi.ts             Web MIDI input and the Controller card
  midi-map.ts         the MIDI mapping logic (pure; unit-tested)
  dom.ts              element, toast and dialog helpers
  platform.ts         window.deckglow, or the dev server in a browser
  smoke.ts            the smoke run
```

Security: the page is sandboxed (`contextIsolation`, `sandbox`, no Node), served
from `app://deckglow/` with a strict CSP that allows WebSocket connections to
`127.0.0.1` only; navigation and new windows are blocked and every permission
request is refused. Thumbnails are read only as PNGs inside `touchDesigner/`.
Show files are checked for `"schema": "deckglow.show/1"` before the runtime
sees them, and the runtime validates every field again. The main process
inspects or installs only pack files the person picked in its dialog or
dropped on the window (the preload turns a real dropped `File` into its path;
a page cannot invent one), and removes only well-formed, non-`com.deckglow`
pack ids.

## Not yet

- Launching TouchDesigner, and writing a fresh token before it starts (the
  contract's intended order) - for now, open the project yourself.
- Installer and setup wizard.
- MIDI output (lighting a controller's pads to show the current look), soft
  takeover for faders that jump when the controller and the app disagree.
