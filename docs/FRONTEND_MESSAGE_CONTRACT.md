# Frontend Message Contract

Status: Draft v1 (2026-11-06)  
Protocol id: `deckglow.control/1`  
Show format: `deckglow.show/1`  
Runtime: `/project1/control_bridge` (`touchDesigner/tools/build_control_bridge.py`)  
Reference client: `touchDesigner/tools/bridge_client.py`

This is how a frontend — the DeckGlow desktop app — drives the TouchDesigner
runtime. The frontend never sees CHOPs, operator paths or OSC. It sends named
messages; the runtime validates every field and applies them to its own
operators. Nothing a frontend sends is ever evaluated as Python or as a
TouchDesigner expression (SCENE_MODULE_SPEC s11).

## 1. Transport

- WebSocket on `ws://127.0.0.1:9980/` (port is the bridge's `Port` parameter).
- **Localhost only.** Connections from any other address are closed at once.
- Text frames carry one JSON object each. Binary frames, runtime → frontend
  only, carry preview JPEGs.
- HTTP `GET /health` returns `200 deckglow`; every other HTTP request is 404.

## 2. Authentication

The first message must be `hello` with the session token:

```json
{"type": "hello", "token": "…", "client": "deckglow-app/0.1", "protocol": "deckglow.control/1"}
```

The token is the contents of `touchDesigner/bridge_token.txt` (created with
a random value if missing; gitignored). The desktop app writes a fresh token
there before it launches TouchDesigner. Any other message before a valid
`hello` gets an `unauthenticated` error; three bad hellos close the
connection.

Reply:

```json
{"type": "welcome", "protocol": "deckglow.control/1", "runtimeApi": "2.0.0",
 "moduleContract": "deckglow.scene-module/1", "state": { … show state … }}
```

## 3. Requests

Every request may carry an `id` (string or number); the reply echoes it.
Success is `{"type": "ack", "id": …}`; failure is
`{"type": "error", "id": …, "code": "…", "error": "human readable"}`. After
any change the runtime broadcasts the new `state` to every authenticated
client, so all windows stay in sync.

Slots are `base_scene`, `hit_fx`, `brand_overlay`, `finish_fx`.

| `type` | Fields | Effect |
| --- | --- | --- |
| `getState` | — | Replies `{"type": "state", "state": …}`. |
| `getLibrary` | optional `rescan` (bool) | Replies `{"type": "library", "modules": […], "palettes": […]}`: each module's id, type, version, name, source, approval and quarantine result, thumbnail path and declared controls. Uses the last scan; `rescan: true` re-reads every module (slow — seconds — so only after installing or changing one, never mid-show). |
| `setSlotEnabled` | `slot`, `enabled` (bool) | Turns the slot on, or bypasses it (empty base shows the background colour). |
| `setSlotIntensity` | `slot`, `value` 0..1 | The module's standard `Intensity`. |
| `setSlotModule` | `slot`, `module` (id or `null`) | Loads an **approved** module of that slot's type, or empties the slot. Unapproved, stale, failing or wrong-type modules are refused. |
| `setControl` | `slot`, `parameter`, `value` | A creative control declared in the loaded module's `module.json`, or a slot parameter from the frozen contract (e.g. `Fxamount`, `Blendmode`, `Placement`). Type and range are checked against the declaration. |
| `setPerformer` | `name`, `value` 0..1 | One of `masterIntensity`, `motionAmount`, `flashAmount`, `textureAmount`, `toneAmount`, `brandAmount`. |
| `setPalette` | `index` (int) or `name` (str) | Selects the runtime palette. |
| `setBackground` | `color` (`[r, g, b]` in 0..1) or `null` | Overrides the palette's `background` role — what an empty or switched-off base slot shows, and what Solid Background draws. `null` returns to the palette's own. |
| `setBrand` | any of `displayName` (≤48 chars), `mode` (`logo`, `name`, `logo_and_name`), `subtitle` (≤48 chars; `""` removes it), `scale` 0.1..5, `opacity` 0..1 | Edits the brand table. |
| `setOutput` | any of `blackout` (bool), `maxBrightness` 0..1, `flashLimit` (bool), `maxFlashes` 1..10 | The `/output` safety stage. Turning `flashLimit` off also requires `"confirm": "venue-allows-strobing"`. |
| `setEngine` | `mode` (`live` or `demo`), optional `bpm` 40..240 | `demo` uses the built-in test generators at that tempo — no audio engine needed. |
| `projector` | `action`: `open`, `perform` or `close` | The output window (`perform` = Perform Mode). |
| `applyShow` | `show` (a `deckglow.show/1` object) | Applies a whole saved show, field by field, in the order of section 5. Fields it cannot apply are reported, the rest still apply. |
| `subscribe` | optional `status` (bool), optional `preview` (`{"fps": 1..30, "width": 160..960}` or `false`) | Starts or stops `status` messages (4 per second) and preview frames. |

## 4. Runtime → frontend

| `type` | When | Content |
| --- | --- | --- |
| `welcome` | after a valid `hello` | protocol, versions, state |
| `ack` / `error` | after each request | `id`, and `code` + `error` on failure |
| `state` | after every change, to all clients | the show state (section 5) |
| `status` | 4 per second, to subscribers | `fps`; per slot `status` (the host's `Status`), `cookMs`; `limiter` (`held`, `transitions`, `gain`); `lanes` (all 16 motion lanes) |
| binary frame | at the subscribed rate | one JPEG of `OUTPUT`, scaled to the subscribed width |

Error codes: `bad_json`, `unauthenticated`, `unknown_type`, `bad_field`,
`not_approved`, `wrong_slot`, `not_loaded`, `unknown_control`, `confirm_required`,
`failed`.

## 5. Show state — `deckglow.show/1`

The same object is the live state (`getState`, `state` broadcasts) and a
saved show file (`applyShow`). The frontend saves it; the runtime never
writes show files.

```json
{
  "schema": "deckglow.show/1",
  "slots": {
    "base_scene":    {"module": "com.deckglow.kinetic_stripes", "enabled": true, "intensity": 1.0, "controls": {}},
    "hit_fx":        {"module": "com.deckglow.orb_burst",      "enabled": true, "intensity": 1.0, "controls": {"Spawncount": 6}},
    "brand_overlay": {"module": "com.deckglow.clean_lockup",   "enabled": true, "intensity": 1.0, "controls": {"Placement": "bottom_right"}},
    "finish_fx":     {"module": "com.deckglow.projector_safe", "enabled": true, "intensity": 1.0, "controls": {}}
  },
  "performer": {"masterIntensity": 1, "motionAmount": 1, "flashAmount": 1,
                "textureAmount": 1, "toneAmount": 1, "brandAmount": 1},
  "palette": {"index": 0, "name": "deckglow"},
  "background": null,
  "brand": {"displayName": "KOUTINHO", "mode": "name", "subtitle": "", "scale": 1.0, "opacity": 1.0},
  "output": {"blackout": false, "maxBrightness": 1.0, "flashLimit": true, "maxFlashes": 3},
  "engine": {"mode": "live", "bpm": 120}
}
```

`applyShow` order: `engine`, `palette`, `background`, `brand`, `performer`,
then each slot's `module`, `enabled`, `intensity` and `controls` (controls are
applied after the module has loaded), then `output` last — so a show can never
leave the safety stage in an older state than the picture. `controls` holds
only values that differ from the module's defaults; a module change clears
them.

## 6. Versioning

Adding an optional field or a new message type is a minor change; anything
that would make an existing valid message or show file invalid needs
`deckglow.control/2` / `deckglow.show/2`. Unknown fields in requests are
ignored; unknown fields in a show file are reported by `applyShow`.
