# DeckGlow — working notes for agents

Read this before touching the TouchDesigner side. It records things that are not
derivable from the code and that cost real time to discover.

## What the product is

A reactive visuals system for DJs, split in two halves:

- **C++ engine** (this repo's `Headers/`, `SrcFiles/`, `ReactiveVisualEngine.cpp`)
  captures Windows system audio via WASAPI, runs an analysis pipeline
  (band energy → onset → tempo → beat clock → five macros) and publishes the
  result as OSC under `/rve/v2/...`.
- **TouchDesigner runtime** (`touchDesigner/`) is a *host*, not a patch. Scenes
  are `.tox` modules that drop into four fixed slots:
  `base_scene → hit_fx → brand_overlay → finish_fx`.

The design bet is that the runtime stays frozen so creator packs are content,
not alternate runtimes. The DJ never sees OSC addresses or CHOP wiring.

### The three specs are the contract

| Doc | Covers |
| --- | --- |
| [docs/V2_ARCHITECTURE.md](docs/V2_ARCHITECTURE.md) | Engine side: analysis modules, feature schema, OSC namespace |
| [docs/HYBRID_RUNTIME_ARCHITECTURE.md](docs/HYBRID_RUNTIME_ARCHITECTURE.md) | TD runtime layers, motion lanes, slot model |
| [docs/SCENE_MODULE_SPEC.md](docs/SCENE_MODULE_SPEC.md) | Module authoring contract. **§18 is the block plan.** |

When implementation and spec disagree, raise it rather than silently diverging —
§16 versioning rules matter once Block 8 freezes `deckglow.scene-module/1`.

## Current state

**Block 1 — engine input and motion adapter: done and verified.**

`touchDesigner/engine_input_block1.toe` contains:

```
/project1
  engine_in       Base COMP: oscin1 (port 9001), 8 Select CHOPs, test generators, live/test switch
  ENGINE_INPUT    Null CHOP — the single named terminal everything reads
  motion_adapter  Base COMP: 45 nodes producing 16 motion lanes
  MOTION_OUT      Null CHOP
```

Verified live: the live/test switch swaps cleanly, all 16 lanes carry correct
names and values, and the low-confidence tempo fallback engages (see Open
decisions).

**Block 2 — module host: done and verified.**

Built by script, not stored as hand-edited `.toe`. `/project1/module_host`
loads a `.tox`, wires only the inputs its slot type takes, applies the six
standard parameters, pulses `Reset`, warms two frames, then validates and
reports via a `Status` parameter. Bypass routes `out1` to the image input, or
black for `base_scene`.

Verified live: dynamic load, slot-correct wiring, `Intensity` forwarding into
the loaded module, bypass, repeatable unload/reload, and all 16 motion lanes
reaching inside the module with live values.

**Block 3 — `kinetic_stripes`: done and verified** (2026-11-05).

Verified live: the builder's lookup-image and lock checks passed, `module_host`
loaded it with `Status` `ok: 1280x720`, it reacts in test mode, and the idle
frame matches the proto's side by side. The exported `.tox` stores
`lookup_tex` locked with its image and contains no absolute paths. The saved
`.toe` now has `module_host` pointing at this module.

`tools/build_kinetic_stripes.py` builds the module in `/project1`, exports
`modules/kinetic_stripes/module.tox` + `thumbnail.png`, and removes the build
COMP. `module.json` and `assets/stripe_lookup.png` are checked in.

What was ported, and why only part of the proto. In the saved
`ReactiveVisualsTouchDesignerProtoOsc.8.toe`, `comp1` and `feedback1` are
**bypassed** and `level1` is **locked**, so the feedback trails and the
mid/high-driven noise never reached the screen. The live chain was:

```
ramp1 (stripes) ─ lookup2 (through the frozen level1 image) ─ level_onset_flash
  ─ transform2 (bar zoom) ─ xform_kick ─ 3 offset copies composited ─ out1
```

That is what the module reproduces. The frozen image was recovered from
`level1.data` with `tools/extract_locked_top.py` and is re-locked inside the
module, so the `.tox` references no external file. (Earlier notes said the proto
had a replicator: it is TouchDesigner's stock `/local/maps` MIDI replicator,
not part of the visual.)

| Proto (raw OSC) | Drives | Lane |
| --- | --- | --- |
| `bass` | ramp phase — stripes slide | `body_level` |
| `onset` | brightness `0.75 + 1.25x` | `impact_fast` |
| bar pulse → Trigger | zoom `1 + 1.0x` | `sync_bar_env` |
| `kick` | zoom `1 + 0.12x` | `impact_wide` |
| sin(beat phase) | x drift `±0.03` | `sync_sine` |

The proto constants are the six creative controls (`Stripeperiod`,
`Stripeshift`, `Flash`, `Barzoom`, `Kickzoom`, `Beatdrift`). The proto rendered
at TouchDesigner's default 256×256; the module renders at
`Outputwidth`×`Outputheight`.

The blue bands in the thumbnail are real, not a bug: Lookup TOP indexes each
channel separately, so ramp yellow `(1,1,0)` reads the grey noise at two
different positions and can come out blue.

To re-check after a rebuild: run the builder (it prints the lookup-image check
and the files it wrote), then in `module_host` set `Modulepath` to
`project.folder + '/modules/kinetic_stripes/module.tox'`, `Moduletype`
`base_scene`, pulse `Load` and expect `Status` `ok: 1280x720`. Turn on the
viewer flag on `module_host/out1`.

**Block 4 — `orb_burst`: done and verified** (2026-11-05).

`tools/build_orb_burst.py` builds and exports `modules/orb_burst/module.tox` +
`thumbnail.png`; `module.json` is checked in. The host builder now makes a
two-slot stack: `module_host` (base_scene) feeds its output into a new
`hit_host` (hit_fx) as `in0_image`, both reading `MOTION_OUT`.

```
in1_motion ─ motion ──(read by Python)── render/pool  Script CHOP, 32 slots
                                           ├ orbs_a  x y radius alpha
                                           └ orbs_b  r g b core
in0_image ─ render/in_image ─ render/orb_fx  GLSL TOP: soft discs + blend mode
                           └─ render/out_switch  exact pass-through ─ out1
```

- `impact_trigger` (rising edge) spawns `Spawncount` orbs into a fixed ring of
  32 slots, oldest reused — bounded by construction.
- Brightness per burst is `min(1, 2 × impact_fast)` at the trigger, so
  `flashAmount` and `masterIntensity` reach the orbs even though
  `impact_trigger` itself is unscaled. A burst at zero flash is skipped.
- `impact_wide` sustains alpha (`0.6 + 0.4 × impact_wide`) — persistence.
- Positions from `random.Random(Seed, burst number)`; Reset, `Moduleactive`
  and `Seed` changes clear the pool, so a seed replays the same orbs.
- Palette roles primary/secondary/accent from `in2_palette`, spec defaults
  when absent; `Colorize` lerps from white.
- `Moduleactive` off or `Fxamount × Intensity = 0` switches to the untouched
  input. Declares `usesPython: true`.

The pool logic was exercised outside TD with stand-in objects (bounded at 32
after 80 spawns, held trigger does not re-fire, zero flash spawns nothing,
orbs expire, Reset + same Seed replays identical positions).

Verified in TouchDesigner (2026-11-05): the export passed its shader and pool
checks; `thumbnail.png` shows eight soft orbs in the three default palette
colours, so the GLSL compile and the CHOP-to-uniform-array mapping work. Both
hosts load with `Status` `ok: 1280x720`, `hit_host` takes its image from
`module_host`, no errors anywhere. Confirmed by eye in test mode: orbs burst
over the stripes, `Fxamount 0` gives plain stripes, `Blendmode` switches the
look, and `flashAmount 0` stops the orbs.

Without a palette input and with `impact_wide` low, orbs sit at about 60%
brightness (`persist = 0.6 + 0.4 × impact_wide`), which reads slightly dim in
the thumbnail. A look tweak, not a fault.

**Block 5 — `clean_lockup`: done and verified** (2026-11-05).

The stack is now three slots: `module_host` → `hit_host` → `brand_host`
(brand_overlay). Brand data has no real source yet, so
`tools/build_brand_source.py` builds a stand-in: `brand_table` → `BRAND`
(Null DAT, the s8.2 key/value table) and `logo_art` (Text TOP "DG") → `LOGO`
(Null TOP). `build_module_host.py` wires them into `brand_host`'s
`in3_brand`/`in4_logo`, which reach the module as its `in2_brand`/`in3_logo`.
Run the brand source builder first.

```
in2_brand ─ render/layout  Python: reads keys, computes rects, cached per frame
              ├─ render/name_text, render/sub_text  Text TOPs sized to on-screen height
              └─ uniforms on render/lockup_fx
in0_image, in3_logo, name_text, sub_text ─ render/lockup_fx  GLSL Multi TOP
                                        └─ render/out_switch  pass-through ─ out1
```

- `mode` from the brand DAT: `logo`, `name`, `logo_and_name` — tokens the spec
  did not define, now written into SCENE_MODULE_SPEC §8.2. Without visible logo
  pixels it falls back to the name. An unwired In TOP still yields a blank
  texture, so "logo present" tests alpha — since 1.0.1 every frame, through
  `render/logo_probe` (Analyze, average) → `render/logo_alpha` (TOP to CHOP,
  immediate). 1.0.0 sampled with `numpyArray()` every 60 frames and showed the
  name-only fallback for ~1 s after every load before jumping to the logo;
  the Block 7 validator caught it.
- Vertical stack (logo, name, subtitle), anchored by `Placement` inside a safe
  area of `Safearea` × frame height on each edge; shrinks to fit. Default
  placement is `bottom_right` (the spec gives none).
- `brand_pulse` brightens by up to `1 + 1.5 × brand_pulse`; never
  `impact_trigger`.
- Soft dark backing behind glyphs and logo (8-tap ring, `Backing` control) for
  legibility on bright and dark images.
- Name in `primaryColor`, subtitle in `secondaryColor`, logo keeps its colours;
  brand `opacity` and `scale` apply to all. Declares `usesPython: true`.

The layout module was exercised outside TD with stand-ins (all placements stay
inside the safe area, no-logo fallback, logo-only centring, scale 5 shrinks to
fit, unknown mode, empty name, malformed colours/numbers).

Verified in TouchDesigner (2026-11-05), after two fixes found on the first run
(the Text TOP unit menu labels, and GLSL TOP's three-input limit — both in
*Getting parameter names and values right*): the export wrote `module.tox`
with no absolute paths and a thumbnail showing "DG", "DJ NAME" and "LIVE"
stacked bottom-right. All three hosts load with `Status` `ok: 1280x720` and no
errors, and the chain runs `module_host` → `hit_host` → `brand_host`. Placement,
`mode name`, a changed `displayName` and `Intensity 0` all behave by eye; the
diagnose run showed `mode name` with the logo rect empty and the name centred.
The saved `.toe`'s `brand_table` holds the owner's test edits
(`displayName KOUTINHO`, `mode name`), which the brand source builder keeps.

**The owner's lockup is just the name — no subtitle** (2026-11-05). The
stand-in brand table no longer has a `subtitle` row, and the clean_lockup
thumbnail is rendered from a fixed demo brand of its own (DJ NAME,
logo_and_name, no subtitle) so it never depends on `brand_table` edits.
`subtitle` stays an optional key in spec §8.2 and the module still draws one
if a row is present.

Look note, not a fault: the placeholder logo's square texture leaves space
above and below "DG".

**Block 6 — `projector_safe` and `/output`: done and verified** (2026-11-05),
except display routing (below).

Verified in TouchDesigner: the export passed its shader and background
checks; all four hosts load with `Status` `ok: 1280x720` and no errors, chained
`module_host` → `hit_host` → `brand_host` → `finish_host` → `output`, with
motion wired and `blackout_gate` reading 1. With defaults the finish reads
`uFinish (1, 1, 0, 1)` and `uMood (0, 0.006, 1)` — tint 0 because test-mode
tone is 0.5, punch `0.08 × impact_wide`. By eye on `OUTPUT`: the full picture
shows, Softness and Contrast change it, `Maxbrightness 0.5` halves it and
`Blackout` turns it black.

The stack is now complete: four slots plus the runtime's own safety stage.

```
module_host → hit_host → brand_host → finish_host → output → OUTPUT
(base)        (hit_fx)   (brand)      (finish_fx)   safety   Null TOP, the one
                                                             terminal a display reads
```

`projector_safe` (`tools/build_projector_safe.py`, finish_fx):

- `Softness` blends toward a Blur TOP (≈0.8% of frame height), modulated by
  `mood_softness`: `Softness × (0.6 + 0.8 × mood_softness)`.
- `Contrast` around 0.5, then `Brightness`, then a restrained lift
  `× (1 + Punch × impact_wide)`.
- Warmth tint `r × (1+t)`, `b × (1−t)`, `t = (mood_warmth − 0.5) × 0.2 × Warmth`.
- `Outputclamp` clamps to `0..1`; `Intensity` blends finished with untouched.
- With the spec defaults (1, 1, 0) it only moves by the small warmth and punch
  terms. No Python. The thumbnail is rendered over kinetic_stripes' thumbnail
  with Softness 0.35 / Contrast 1.25 to show the effect; the export keeps the
  spec defaults.

`/project1/output` (built by `build_module_host.py`, not a module): a GLSL TOP
that turns NaN/Inf to black, hard-clamps to `0..1`, multiplies by the
`blackout_gate` lane (1 when absent), a `Maxbrightness` ceiling and a manual
`Blackout` toggle, and forces alpha to 1 — then the flash limiter (see
*Decisions made*). All four custom parameters carry across rebuilds. It sits after `finish_host`, so a bypassed finish module can never
skip it (spec §10.4). Like every chain end, `OUTPUT` only cooks when
something views it.

**Display routing — done and verified** (2026-11-05): the owner ran the
build, open and Escape-to-close steps and reported everything working. The
saved `.toe` has `projector` showing `/project1/OUTPUT` on display 1. `tools/build_projector_window.py`
builds `/project1/projector`, a Window COMP showing `OUTPUT` (by name, so stack
rebuilds don't break it): borderless, filling the chosen display, always on
top, cursor only while moving, Escape closes. It picks the first non-primary
display; with a single display it uses the primary, so opening it covers the
editor. It is **never opened by the build** — `par.winopen.pulse()` opens a
separate window (testing), `par.performance.pulse()` opens Perform Mode, which
TouchDesigner's docs recommend for final output. Re-running keeps the chosen
display.

**Block 7 — scene library and quarantine validation: done and verified**
(2026-11-05). The owner approved the four first-party modules
(`library/approved.json`: kinetic_stripes 1.0.0, orb_burst 1.0.0,
clean_lockup 1.0.1, projector_safe 1.0.0); `stub_scene` stays unapproved.
`LoadApproved('hit_host', 'com.deckglow.orb_burst')` loaded, and
`LoadApproved` on the stub was refused.

Two parts. `tools/validate_static.py` is plain Python (§15.1) and runs
outside TouchDesigner too:

```bash
"C:/Program Files/Derivative/TouchDesigner/bin/python.exe" -I touchDesigner/tools/validate_static.py touchDesigner/modules
```

It checks every manifest rule in §5, paths kept inside the module folder, the
`runtimeApi` range against `RUNTIME_API 2.0.0`, the thumbnail's PNG signature
and 16:9 size, control declarations, duplicate ids, and — via `toeexpand` —
absolute paths baked into the `.tox`. Raw `.tox` files are compressed, so the
scan expands a temp copy; a `.tox` toeexpand cannot read fails. All five
modules pass; 26 deliberately broken cases (bad JSON, wrong schema, upper-case
id, excluded API range, 9 tags, bad controls, escaping/absolute entry, non-PNG
thumbnail, an injected `C:/Users/...` path inside a real `.tox`, an unreadable
`.tox`, duplicate ids) each fail the right check.

`tools/build_scene_library.py` builds `/project1/scene_library`:

```
scene_library
  static_checks  validate_static.py, embedded
  library        Python: Scan, ValidateAll, Validate, Approve, Revoke,
                 IsApproved, LoadApproved, Summary
  LIBRARY        one row per module: static / quarantine / approved
  RESULTS        every check from the last run
  quarantine     syn_motion (16 lanes), syn_image (gradient), syn_palette,
                 syn_brand, syn_logo, res_probe — and the module under test
```

`ValidateAll()` loads each module into quarantine in turn (about 10 s each,
driven by chained `run(..., delayFrames=n)`), wires synthetic inputs by slot
type, then: interface checks (§15.2: In operators by name, family and
connector index; `render`/`out1`; standard and slot parameters with the right
page, style and menu tokens; reserved names; declared controls matching
`Controls`-page parameters), runtime checks (§15.3: Idle stable, Drive sweep,
Hit bounded — and responding, for hit_fx — Sync motion for base scenes, Dense
cook time and no operator growth, Reset clears, Bypass exact pass-through for
non-base), and admission (§15.4: resolution matches `res_probe`, nothing
created or destroyed outside quarantine, cook time recorded). Frames are read
back with `numpyArray()` at 1/8 resolution and checked for NaN/Inf.

Reports land in `touchDesigner/validation/<folder>.json` — **read these
directly instead of asking the owner to paste output.** Approvals live in
`touchDesigner/library/approved.json`, per id *and version*: a new version is
`stale` until re-validated and re-approved. `LoadApproved(host, id)` is the
gated path into a host; a host's own `Modulepath` + `Load` stays as the
development path. The discovery, report and approval flow was tested outside
TD with stand-ins (refusals before validation and after a fail, stale on a
version bump, revoke).

**First run (2026-11-05) found a validator bug, not a module bug.** kinetic,
lockup and projector passed; stub warned "black at idle" as expected; but
`orb_burst` failed "hit response" with zero change and every cook time read
0.00 ms. Cause: lazy cooking again. Nothing in quarantine views the module, so
it only cooked when a frame was read back — and `impact_trigger` lasts one
frame, which nothing asked to cook, so the orb pool never saw it. Fix: the
runner now ticks every frame and force-cooks the module's `out1` each tick
(`_cook()`), and cook time is the wall time of that forced cook (CPU plus GPU
submission) with `childrenGPUCookTime` alongside.

**Second run, with the fix:** `orb_burst` passes (hit response 0.714, settles
30 frames after the envelope); `kinetic_stripes` and `projector_safe` pass;
`stub_scene` warns as expected; real cook times 0.19–0.58 ms avg, all far
under the 4 ms budget. **`clean_lockup` failed — a real module bug** that the
first run's lazy cooking had hidden: its logo check sampled every 60 frames,
so after load it showed the name-only fallback, then jumped to logo-and-name
mid-test (0.776 change in "hit bounded" and "reset clears", which drive
nothing the lockup reads). Fixed in clean_lockup 1.0.1 with a per-frame alpha
probe (see Block 5).

**Third run:** clean_lockup 1.0.1 passes — all 25 interface checks, idle
stable, hit bounded, reset clears (0.000), exact pass-through, isolation;
0.56 ms avg. All four first-party modules now pass quarantine; `stub_scene`
warns (black at idle) and is a test fixture, not for approval.

Rule worth keeping: **anything that tests a module must cook it every frame**,
or one-frame events and time-based state are invisible to the test.

Expected findings: `stub_scene` warns "black at idle" (a flat-colour
fixture), and `clean_lockup` shows no hit/sync response (info, not a
failure).

**Block 8 — freeze `deckglow.scene-module/1`: done** (2026-11-06).

After the four contract decisions (see *Decisions made*, 1–4 of 4), the
contract is frozen at runtime API `2.0.0`:

- `docs/SCENE_MODULE_SPEC.md` is marked **Frozen v1**, with §16.1 giving the
  change rules (additions → `2.1.0`; removals or changed meaning → `3.0.0`
  and `deckglow.scene-module/2`) and listing the decisions settled before it.
- `docs/contract/deckglow.scene-module-1.json` is the machine-readable
  contract: manifest fields and limits, slots, connectors, standard and slot
  parameters, reserved names, all 16 lanes with range, kind, centring and
  performer scaling, palette and brand tables, validation states.
- `tools/check_contract.py` (plain Python, outside TD) fails if the spec's
  §7/§9/§10 tables, `validate_static.py`, `build_scene_library.py`,
  `build_performer_controls.py`, `diagnose_performer_controls.py` or any
  module manifest disagree with that file. 85 checks pass; ten deliberate
  mutations of the contract (swapped/renamed lanes, an extra menu token, a
  newly required input, a lane no longer centred, a wrong performer mapping,
  a bumped API, a dropped reserved name, a changed limit, a wrong parameter
  style) are each caught.

**Run `check_contract.py` after touching the spec, the validator or any
runtime builder.** A failure means either the change is wrong or it is a
contract change that must follow §16.1.

The quarantine resolution test also gained `probe has content` (warn): the
probe frame must show the module's own content — not black for base scenes,
different from the input for the other slots — so a module that draws nothing
cannot pass `resolution independent` trivially. **Verified in TD**
(2026-11-06): every module shows content in the probe (kinetic mean 0.826;
lockup, orbs and finish differ from their input by 0.332, 0.619 and 0.082;
stub mean 0.418) and still passes `resolution independent`. orb_burst's
0.000 resolution score is therefore real — soft, fraction-sized orbs match
exactly — not an empty frame. All four first-party modules pass; stub warns
only for black at idle. `check_contract.py`: 85 checks, 0 problems.

**Creator packs — `deckglow.pack/1`: done and verified** (2026-11-06).

Verified end to end: the example pack installed (14 checks); in TouchDesigner
the palette source picked up `com.example.demo/sunset`, the library listed
`com.example.demo.flat_wash` with source `com.example.demo`, quarantine
passed it with a warning only for black at idle (as for the stub it is copied
from: no Python — 8 operators, 5 expressions allowed — no absolute paths,
probe has content, resolution independent, isolation), the owner approved it
and `LoadApproved` put it in `module_host` — a flat wash under the orbs and
lockup, no stripes. kinetic_stripes was loaded back and the `.toe` saved in
live mode. `library/approved.json` now also lists the example module; its
pack lives in the gitignored `Packs/`, so on a fresh checkout that approval
simply matches nothing until the pack is installed. Spec: [docs/PACK_FORMAT_SPEC.md](docs/PACK_FORMAT_SPEC.md).

Owner's decisions: **anyone can publish**, checked locally (quarantine plus
per-version approval, as for first-party; content hashes; a `signature`
field reserved for a future curated tier); **no Python in creator modules**;
**one `.dgpack` file** (a zip) installed into `touchDesigner/Packs/<pack id>/`
(gitignored — per-machine state).

- `pack.json`: schema, id (never under `com.deckglow`), version, runtimeApi,
  moduleContract, `modules` (folder, id, version — ids must start with the
  pack id), optional `palettes`, `files` (sha256 of every file), `signature`
  null.
- **No Python** is enforced on the `.tox` itself, expanded with toeexpand
  (`validate_static.py`, `policy='creator'`): no script / Execute / Timer /
  network / file-out / Window / Engine / Replicator operators, no `callbacks`
  or `externaltox` set, and every *active* expression must be a pure read
  (AST allowlist: `op`, `parent`, `me`, `math`, `absTime` and a few builtins;
  no `_` attributes or mutators like `module`, `run`, `destroy`). In `.parm`
  lines flag bit `0x1` is an active expression and `0x200` a bind; flag `16`
  alone is an expression stored but switched off (Movie File In's default
  `app.samplesFolder+'/Map/Banana.tif'`) and is skipped. Applied to the
  first-party modules as a check of the rule: kinetic_stripes,
  projector_safe and stub pass; orb_burst and clean_lockup (Python, exempt)
  are caught.
- `tools/pack_tool.py` — `build`, `verify`, `install [--force]`, `remove`,
  `list`. Verify checks archive safety (zip-slip, absolute paths, symlinks,
  encryption, duplicates, sizes), every `pack.json` rule, hashes, then each
  module with the static and creator checks. Install stages, then swaps in one
  step; a failing install leaves the old one untouched; same/lower version is
  refused unless forced. Installing approves nothing.
- The scene library discovers `Packs/` alongside `modules/`: pack modules are
  keyed `<pack id>/<folder>`, show their pack in a new `source` column, and
  reports are saved as `<pack id>__<folder>.json`. `build_palette_source.py`
  adds pack palettes to the library as `<pack id>/<name>`.
- Example: `touchDesigner/examples/packs/com.example.demo/` (the stub, renamed
  `com.example.demo.flat_wash`, plus a `sunset` palette) and its built
  `com.example.demo-1.0.0.dgpack`.

Tested outside TD: nine bad packs refused at build (reserved id, schema, API,
signature, namespace, version mismatch, unlisted module, stray file, bad
palette) plus a Python module; six hostile archives refused at verify
(tampered `.tox`, extra file, duplicate name, `../`, `C:/`, symlink, not a
zip); install, refused reinstall, upgrade, refused downgrade and `--force`,
untouched-on-failure, list, remove; library discovery, approval and
`LoadApproved` from `Packs/`.

**Desktop app — step 1 (runtime side): done and verified** (2026-11-07).
The owner chose a **desktop app** (planned: Electron + TypeScript, an
installer and setup wizard published from this repo). Step 1 is the runtime
half, independent of the app framework.

Verified against the running TouchDesigner by Claude with
`bridge_client.py demo`: **18 of 18 steps** — orbs and stripes off/on, the
background override (stripes and orbs off → a purple frame with only the
name), back to the palette, palette ember, name, master, max brightness, demo
mode at 128 BPM, two orb controls, the three refusals (unapproved, wrong slot,
strobe without the confirm phrase), the status stream (≈60 fps, 16 lanes,
limiter state) and `applyShow` restoring the starting show with no problems.
Both preview JPEGs are 480×270. Solid Background passed quarantine and is
approved. Two bugs found on the first run: the client skipped the `getState`
reply (it ignored every `state` message; broadcasts carry no `id`, so it now
matches on id only), and the preview came out 256×256 then 1280×720 — nothing
views the preview TOP, so `saveByteArray` read a stale texture; it is now a
Resolution TOP force-cooked before each save (lazy cooking again). A
background step failing with "palette_source has no background override"
means `build_palette_source.py` (and then `build_module_host.py` + `Load` on
each host) were not re-run.

- [docs/FRONTEND_MESSAGE_CONTRACT.md](docs/FRONTEND_MESSAGE_CONTRACT.md) —
  `deckglow.control/1` over WebSocket `ws://127.0.0.1:9980/`, localhost only,
  token from `touchDesigner/bridge_token.txt` (gitignored, created if
  missing). Named, field-validated messages (`setSlotEnabled`,
  `setSlotModule` gated by approval, `setControl` against declared controls,
  `setPerformer`, `setPalette`, `setBackground`, `setBrand`, `setOutput` —
  flash limit off needs a confirm phrase — `setEngine` live/demo + BPM,
  `projector`, `applyShow`, `subscribe` to status and JPEG preview).
  Show files are `deckglow.show/1`, the same object as the live state.
- `tools/bridge_protocol.py` — the pure-Python protocol (auth, validation,
  dispatch, `applyShow` ordering with output last), no TD imports, embedded in
  the bridge. Tested outside TD with a fake adapter: non-local refused,
  nothing before `hello`, three bad tokens close, 25 bad requests refused with
  the right code and none reaching the runtime, broadcasts to all clients.
- `tools/build_control_bridge.py` — `/project1/control_bridge`: Web Server
  DAT, the adapter onto existing operators (host `Moduleactive`/`Intensity`,
  `LoadApproved`, performer_controls, palette_source, brand_table, output,
  engine_in test generators, projector), status 4×/s and preview via
  `saveByteArray('.jpg')` from an Execute DAT. Slot parameters a frontend may
  set come from the frozen contract file.
- `tools/bridge_client.py` — standard-library WebSocket client (loopback-tested:
  handshake, masking, ping/pong, 16/64-bit lengths, binary). `demo` walks the
  app's switches, saves preview JPEGs and restores the starting show. **Claude
  can run it directly against a running TouchDesigner** — no pasting needed.
- **Background colour:** `palette_source` gains `Backgroundoverride` +
  `Backgroundcolor`, written into the palette's `background` role; every
  host's fallback (`black`) now shows that role, so an empty or switched-off
  base slot shows the background colour (black without a palette).
- **`solid_background`** (`tools/build_solid_background.py`,
  `com.deckglow.solid_background`): the palette background pulsing toward the
  palette primary on the beat, `bg + (primary − bg) × Breathe × sync_level`
  (`Breathe`, labelled Beat Pulse, default 0.15); exactly the background at
  idle. No Python — passes the creator rule. The first build scaled brightness
  with `body_level` and **failed quarantine's Sync test** (0 of 11 samples
  changed): a base scene must move with the beat lanes, and dimming the test
  palette's near-black background barely changes a pixel. A still colour needs
  no module — an empty or off base slot shows the background.
- **Fixed on the way:** `LoadApproved` used to `Scan()` first, which runs
  toeexpand on every module and would stall the picture for seconds on every
  live module switch. It now uses the last scan; `getLibrary` takes
  `rescan: true` for after installs.

**Desktop app — step 2 (the app): done and verified** (2026-11-07).
`app/` — Electron 44.9.3 + TypeScript 6.0.3, no bundler, no runtime
dependencies; see [app/README.md](app/README.md). Preview, a switch, module
menu, intensity and controls per layer, palette, custom background, name,
six performance faders, output safety (max brightness, flashes/s, flash
limiter behind a confirm dialog), Blackout (also the B key), live/demo + BPM,
projector buttons, the library with thumbnails and approval state (only
approved modules can be used), show save/open, lane meters, fps.

- Every control sends a named request; the screen redraws from the runtime's
  broadcast state, never from what it sent — controls being dragged or typed
  into are left alone while held.
- `src/renderer/bridge.ts` is the client: token re-read on every connection
  (TD may recreate it), reconnect with backoff, subscriptions re-sent after a
  reconnect, `auth-failed` reported apart from `offline`.
- Main process reads the token, the frozen contract (slot parameters,
  performer names, lanes) and module thumbnails (PNGs inside `touchDesigner/`
  only); the page is sandboxed on `app://deckglow/` with a strict CSP.
- **`touchDesigner/tools/mock_bridge.py`** — a stand-in bridge running the
  real `bridge_protocol.py` with an in-memory show, the real library and
  approvals; `bridge_client.py demo` passes 18/18 against it. It refuses to
  start if anything answers on its port: on Windows it could otherwise bind
  `127.0.0.1:9980` beside TD's `0.0.0.0:9980` and silently take the
  loopback clients.

Verified: `npm test` 6/6 against the mock (handshake, broadcasts, getState,
six refusal codes, library, subscriptions surviving a runtime restart, wrong
token); `npm run smoke` 14/14 in the real Electron window against the mock
**and against the running TouchDesigner** — real switches, sliders, menus,
the flash-limiter dialog and Blackout, every change seen in broadcast state,
starting show restored; the screenshot shows TD's real output. UI checked by
eye in the browser pane via `npm run web`. Bugs found on the way: `hidden`
overridden by `display: grid`; the page taller than the window (grid row
needed `minmax(0, 1fr)`, and the switches' absolutely positioned checkboxes
had no positioned ancestor); smoke screenshots were stale because a hidden
Electron window stops painting (smoke runs now show inactive with
`backgroundThrottling` off).

Not yet: the app launching TouchDesigner and writing a fresh token first (the
contract's intended order), installer/setup wizard, crossfades, MIDI.

**Desktop app — step 3 (library and packs): done and verified** (2026-11-07). The app installs and removes
`.dgpack` packs and takes each module through validate → review → approve.

- **Trust model unchanged:** installing approves nothing; validation alone
  approves nothing; the approve button sits next to the report and is refused
  (`not_validated` / `validation_failed`) without a passing report for the
  current version. A pack whose module is on a layer cannot be removed.
- **Packs are the main process's job, not the bridge's:** `pack_tool.py
  --json` (new flag: one JSON object per command — `ok`, `message`, `checks`,
  `pack` details, `installed`, `code` such as `already_installed`). The main
  process only inspects/installs files picked in its dialog or dropped on the
  window (preload `webUtils.getPathForFile`), and removes only well-formed
  non-`com.deckglow` ids. `DECKGLOW_PACKS` redirects installs for tests.
- **Bridge additions** (minor, still `deckglow.control/1`): `validateModule`
  (acks at once; `validation` running/done broadcasts — the bridge's Frame
  loop watches the scene library's `_job`/`_queue` and reports 3 idle frames
  after it drains, when `_next()` has rescanned), `getReport` (the quarantine
  report trimmed to stage/check/status/detail), `approveModule`,
  `revokeModule`, a `libraryChanged` broadcast, and error codes
  `unknown_module`, `busy`, `not_validated`, `validation_failed`. Protocol
  handlers can now queue broadcasts (`self._notes`); `notify()` builds one.
- **Pack palettes follow installs:** `palette_logic.RefreshPacks()` (moved out
  of the builder) re-reads `Packs/*/pack.json` palettes, drops those of
  removed packs, never touches the show's own rows, and keeps the selected
  palette selected by name. `getLibrary rescan` calls it. Tested with stand-in
  objects outside TD.
- **Mock bridge** now has validate (simulated 1.5 s; uses the real report on
  disk when one matches), report, approve, revoke — all in memory — finds
  pack modules in `Packs/<id>/modules/<folder>/` (it looked one level too high
  before and never saw packs), lists pack palettes, uses the real approval
  strings (`stale (1.0.0)`, `blocked (fails now)`) and `first-party` source.
  `--packs <dir>` for a test install folder.
- `touchDesigner/tools/test_bridge_protocol.py` — the protocol's offline test,
  now in the repo (it had lived in a scratchpad) and run by `npm test`.

Verified outside TD: `npm test` 12/12 (library flow on a throwaway pack; the
runtime's `approved.json` and `validation/` proven untouched); Electron smoke
19/19 with `--smoke-pack` (inspect, an unpicked file refused, install, rescan,
remove through the real IPC); UI checked by eye in the browser pane — review
dialog with the real Stub Scene report, validate again, approve with a note,
install of the example pack, refused removal while on a layer, removal.

**Verified in TouchDesigner** (after rebuilding palette_source, the stack and
the bridge): a throwaway pack (`com.example.libtest`, the example pack
renamed) went through 25 checks against the live runtime — installed into
`Packs/`, rescan listed it not validated in 0.4 s with its palette added,
loading and approving refused, a second validation refused `busy`, a real
quarantine run broadcast running/done (warn — black at idle — after 5.4 s, 48
checks, report written), approved, loaded onto Scene (`ok: 1280x720`), Scene
restored, revoked, pack removed, module and palette gone, selected palette
unchanged, and `approved.json` byte-identical afterwards (the test report was
deleted). The Electron smoke against TD passed 19/19 including the pack round
trip through the real IPC. The script is not in the repo: it writes to the
real `Packs/`, `validation/` and `approved.json` (and puts them back), which
is not something `npm test` should do.

**Desktop app — step 4 (looks, TAKE crossfades, MIDI): done and verified**
(2026-11-07). Owner's choices: a
look is **Scene + Hits + colours** (module, on/off, intensity, controls of
both picture layers, palette, background) — name, finish, output safety and
performance faders are show-wide and never move on a TAKE; **MIDI lives in
the app** (Web MIDI), so the app must be open for a controller to work.

- **Two picture stacks** (`build_look_runtime.py`, HYBRID_RUNTIME_ARCHITECTURE
  "As built"): stack B `module_host_b` → `hit_host_b` beside stack A,
  `look_switch` (one stack while idle — the parked one never cooks) /
  `look_cross` (both while fading) → `LOOK_OUT` → `brand_host`. Per-stack
  palettes `PALETTE_A`/`PALETTE_B` = Switch DAT of the live `PALETTE` or a
  frozen copy (`look_frozen_a/b`), so the outgoing look keeps its colours.
  `build_module_host.py` now always builds both stacks and calls
  `looks/look_logic.Wire()` when the look runtime exists;
  `build_palette_source.py` calls `Wire()` too (so a palette rebuild no
  longer needs a stack rebuild once looks exist).
- **TAKE** (`look_logic`): refused before anything changes if the look is
  empty or a module is not approved; freezes the outgoing palette, selects
  the look's palette/background, loads the idle stack via `LoadApproved`
  (reuses a module already there with a `Reset` pulse), applies on/off,
  intensity and controls at frame 3 (hosts' `Finish()` runs at 2),
  force-cooks the idle stack while it warms (lazy cooking), waits for the
  beat (`MOTION_OUT sync_phase` wrap) or bar (`ENGINE_INPUT bar_phase` wrap)
  but **never more than 4 s**, fades over `Transitiontime` (0 = cut), swaps
  `Activestack`. A TAKE while fading completes the first at once; while armed
  replaces it; while loading is refused `busy`. `Phase` is a plain
  parameter set by the logic — as an expression reading storage,
  `look_switch` would have no cook dependency to follow.
- **Remembered controls** moved from the bridge's storage (per slot) to
  `looks` storage per host, so a look captures them and a TAKE re-applies
  them. Live edits go to the on-screen host (`_host_name(slot)` →
  `ActiveHost`); `brand_overlay`/`finish_fx` stay single.
- **Bridge/protocol** (minor, still `deckglow.control/1`): `saveLook`,
  `renameLook`, `deleteLook`, `take`, `setTransition`; error `empty_look`;
  state gains `looks` (16, null = empty), `transition`, `take`; status gains
  `take` (with `progress`); the bridge rebroadcasts state when `looks.Version`
  changes. Show files carry the bank and transition; `applyShow` validates
  every look field by field (`_look`/`_bank`: slots only base/hit, module id
  pattern, parameter-name pattern, value types and ranges) — 8 malformed
  banks are reported and none applied. `take` in a show file is ignored.
- **App:** Looks card (16 pads with thumbnails and background tint, fade
  slider, Now/Beat/Bar, ‹ ›, keys 1-0 and `[` `]`, shift-click = cut, empty
  pad = save, ⋯ = save/rename/clear). Controller card: input menu, last-
  message monitor, MIDI learn per action, clear. `midi-map.ts` is pure:
  buttons fire on note-on or a CC crossing 64 (once per press), faders take
  CCs only (learning a note for one is rejected), one control maps to one
  action. Main process: settings file in userData (`DECKGLOW_SETTINGS`), and
  the permission handlers now allow `midi` from `app://deckglow` only, never
  sysex — everything else is still refused.
- Not done: MIDI output (pad lights), soft takeover for jumping faders, and
  per-look brand/finish (not wanted).

Verified outside TD: `npm test` 21/21 (adds `looks.test.mjs` through the
mock — loading → armed → fading → idle on the beat, cut, refusals, bank
through a show round trip; `midi.test.mjs` 7; `test_look_logic.py` with
stand-in hosts/palette/library/clock — 8 groups incl. frozen palettes, warm
cooks, beat vs bar, 4 s timeout, mid-fade TAKE, missing palette, reuse).
Electron smoke 22/22 against the mock: pad saves, TAKE with fade, cut, empty
look refused, MIDI learn + Blackout pad + Master knob via synthetic messages,
mapping and show restored. UI checked in the browser pane (Web MIDI refused
there, as expected outside Electron).

**Verified in TouchDesigner** (after rebuilding the stack, the look runtime
and the bridge): the bridge reports 16 empty pads, transition 2 s on the bar,
stack A on screen. Electron smoke 22/22 against TD (pad save, TAKE with a
fade, cut, empty look refused, MIDI learn + pad + knob, show and mapping
restored). A real crossfade between two distinct looks (purple Solid
Background, ember palette, Hits off → Kinetic Stripes + orbs, deckglow):
loading 0.13 s, then the bar wait hit the 4 s cap (live mode, no music, so
the bar clock stood still — as designed), a 3 s fade with 22 preview frames
mid-blend, then exactly the saved look; a cut back took 0.77 s. The preview
frame during loading was still purple although the live palette had already
switched — the frozen outgoing palette works — and the name stayed steady
through the fade. Repeated cuts swap the stacks A → B → A, each reporting
`ok: 1280x720`. The test looks were removed and the show restored. A test
script of mine left its socket timeout short and its final restore timed out
on the client side; TouchDesigner had applied it anyway (checked).

**Desktop app — step 5 (packaging, setup, CI): done and verified on this
machine** (2026-11-07); CI's engine job passes on GitHub, the test job's fix
is not pushed yet, and the release workflow has not run. See the top-level
[README.md](README.md) and [app/README.md](app/README.md) "Setup and
packaging".

- **The runtime is relocatable** — it had absolute paths of this computer
  baked in. Host `Modulepath` is stored relative to `project.folder`
  (`LoadApproved` writes it so; host `Load()` resolves it; the bridge's
  `_manifest_at` and `look_logic._module_id` too). The bridge's token file
  is `project.folder/bridge_token.txt` at run time, not a path baked at build.
  **`control_bridge` `Startup()` runs on every project open** (Execute DAT
  `onStart`, 30 frames later): maps any absolute `Modulepath` to this folder
  (by the part after `touchDesigner/`, else `Packs/`/`modules/`), rescans the
  library (the saved scan in the `.toe` holds the saving computer's
  folders), refreshes pack palettes, reloads hosts whose module file is not
  where the project expected, then re-applies remembered controls.
  `validate_static.find_toeexpand()` searches `DECKGLOW_TOEEXPAND`, the
  default install and `Program Files/Derivative/TouchDesigner*/bin`.
- **Engine Release build** links the C++ runtime statically (`/MT`, Release
  x64 only): 334 KB, imports only kernel32/ole32/ws2_32 — no Visual C++
  Redistributable needed. It quits on Enter on stdin (the app uses that).
- **App** `src/main/runtime.ts`: runtime folder (repository in a checkout;
  `Documents\DeckGlow` installed; `DECKGLOW_RUNTIME_DIR`/`DECKGLOW_ROOT`
  overrides), install (copy the bundled runtime), update (program parts
  replaced, old ones to `backups/runtime-<time>/`; Packs, approvals with
  first-party entries refreshed, pack reports, token kept; refused while TD
  runs; the renderer saves the show to settings `pendingRestore` first and
  re-applies it on the next connect), TouchDesigner discovery (+ version via
  file properties), **launch with a fresh token only when TD is not running**,
  engine start/stop with its output streamed to the page; pack_tool runs on
  TD's own `python.exe` with `DECKGLOW_TOEEXPAND` set.
- **Setup wizard** (`setup.ts`): six-row checklist (TouchDesigner, runtime,
  connected, audio engine + "hearing music", your name, projector), refreshes
  every 2 s, opens itself on the first run or when something essential is
  missing (never in smoke runs). Header gains Engine and Setup buttons.
- **Installer** — electron-builder 26.18.0, per-user NSIS (no admin),
  unsigned; `npm run stage` copies the program only (first-party modules,
  approvals and reports; no Stub Scene, packs, token, backups, autosaves).
  The shipped `.toe` is the repository's — **save it in TD after rebuilding
  before staging a release**. It still carries the owner's brand edits
  (KOUTINHO); Setup's name row is where a new DJ replaces it.
- **GitHub Actions**: `ci.yml` (engine Release build with a v143 toolset
  fallback, `npm test`, `check_contract.py`) and `release.yml` (tag `v*` =
  `app/package.json` version → tests, `npm run dist`, **draft** release via
  `gh`). Pack/library tests skip with a reason where `toeexpand` is absent.
  **First CI run (2026-11-08):** the engine built on `windows-latest` with
  the v145 toolset directly (no fallback), 334,336 bytes like here; `npm
  test` failed because the runner's Node 22 takes `node --test test/` as a
  file path (Node 26 here accepts a folder) — the script now passes the glob
  `"test/*.test.mjs"`. Actions moved off the deprecated Node 20 majors
  (checkout/setup-node/setup-python/upload-artifact v7, setup-msbuild v3).
  **Second run:** 15 pass, 5 skip (toeexpand) as intended, but the
  "survive a runtime restart" test timed out waiting to reconnect on Node 22
  (passes on Node 26 here). Suspected cause: Node 22's WebSocket reports a
  refused connection with `error` and no `close`, and `bridge.ts` only
  retried on `close`. The client now ends each attempt exactly once on
  close, a pre-open error or a 5 s open timeout; the test waits 15 s and
  reports the connection phases if it still fails. Not confirmed on Node 22
  (fetching a Node 22 binary here was refused).
- No licence file in the repo — the owner's decision.

Verified so far: `npm test` 21/21; dev smoke 24/24 against the mock (adds
engine start → "Listening to system audio" → stop, and the setup checklist);
packaged `release/win-unpacked` `--smoke-setup` 5/5 (installed mode, Install
copies the bundled runtime to a temp folder, row turns green, contract read
from the installed copy, second install refused); `_relocate` 6/6 cases
outside TD; workflows parse as YAML.

**Verified end to end on an installed copy** (after rebuilding the scene
library, stack, look runtime and bridge in the repository's project,
running `Startup()` once and saving): the packaged app
(`release/win-unpacked`) with `DECKGLOW_RUNTIME_DIR` on an empty temp
folder passed `--smoke-setup --smoke-launch` 8/8 - Install copied the
runtime, "Open DeckGlow in TouchDesigner" wrote a fresh token and opened
the copy, the app connected, every module's files came from the installed
folder with all four layers `ok: 1280x720`, the bundled engine started and
stopped. Then the full show smoke from the packaged app against that copy:
24/24 (switches, looks fade and cut, MIDI, show restore, engine, setup
checklist all green). `npm run dist` builds
`release/DeckGlow-Setup-0.1.0.exe` (121 MB, nearly all Electron); the
installer itself was not run here (it would install to the user's account).
Testing quirk, not an app bug: when a shell pipes the app's stdout (`| grep`),
the TouchDesigner the app launches inherits the pipe and the pipeline never
ends - redirect to a file instead.

### Which file is current

`touchDesigner/engine_input_block1.toe` is canonical. TouchDesigner writes
incremental saves (`engine_input_block1.6.toe`) and a `Backup/` folder; those
are noise. `engine_input.toe` is the pre-Block-1 original, kept for reference.
Consider gitignoring `touchDesigner/Backup/` and the numbered saves.

## Working on the TouchDesigner side

Two methods. Pick by what you are building.

### Method A — Python scripts run inside TouchDesigner (preferred)

Anything involving **custom parameters, Python, or callbacks must use this.**
Scripts live in `touchDesigner/tools/` and are run from the textport (Alt+T):

```python
exec(open(r'C:\path\to\touchDesigner\tools\build_module_host.py').read())
```

| Script | Purpose |
| --- | --- |
| `build_module_host.py` | Builds the whole stack (and the second picture stack `module_host_b` → `hit_host_b` for looks; calls `looks` `Wire()` when it exists): `module_host` → `hit_host` → `brand_host` (plus `BRAND`/`LOGO`) → `finish_host` → `output` (safety) → `OUTPUT`. Idempotent; carries `Modulepath`/`Moduletype` and the output's `Maxbrightness`/`Blackout`. Pulse `Load` on each host after rebuilding. |
| `build_tempo_fallback.py` | Adds `tempo_bpm` to `engine_in` and replaces the fixed 120 BPM fallback with `phase_keeper` (last usable tempo, no phase jump). Idempotent; keeps `test_bpm`. |
| `diagnose_tempo_fallback.py` | Read-only. Prints the keeper's mode and held tempo, then measures `sync_phase` speed over 1 s and reports PASS if it matches. |
| `build_control_bridge.py` | Builds `/project1/control_bridge`, the `deckglow.control/1` WebSocket server the desktop app talks to. Run after the stack, palette, brand, library and projector builders. |
| `bridge_protocol.py` | Plain Python: the protocol logic, embedded in the bridge, tested outside TD with a fake adapter. |
| `bridge_client.py` | Standard-library WebSocket client, **outside** TD: `state`, `send '<json>'`, `preview out.jpg`, `demo`. |
| `mock_bridge.py` | Plain Python, **outside** TD: a stand-in control bridge (real protocol code, in-memory show) for developing the app without TouchDesigner. `--port` to move it; refuses a port already in use. |
| `test_bridge_protocol.py` | Plain Python, **outside** TD: the protocol's offline test with a fake adapter (also run by the app's `npm test`). |
| `build_look_runtime.py` | Builds `/project1/looks` (look bank, transition settings, TAKE state machine), the mixer (`look_switch`/`look_cross` → `LOOK_OUT` → `brand_host`) and the per-stack palettes. Run after `build_module_host.py`, then rebuild the control bridge. Keeps the bank, remembered controls and active stack. |
| `test_look_logic.py` | Plain Python, **outside** TD: the TAKE state machine with stand-in hosts and a clock (also run by `npm test`). |
| `build_solid_background.py` | Builds and exports `modules/solid_background/` (palette background, pulsing toward primary on the beat). |
| `pack_tool.py` | Plain Python, **outside** TD: `build` / `verify` / `install` / `remove` / `list` creator packs (`.dgpack`). Installs into `touchDesigner/Packs/`. `--json` for one machine-readable result (what the desktop app reads). |
| `check_contract.py` | Plain Python, **outside** TD: fails if the spec, validator, runtime builders or manifests drift from `docs/contract/deckglow.scene-module-1.json`. Run after any change to those. |
| `validate_static.py` | Plain Python, also runs **outside** TD: §15.1 static package checks for every module under a folder. Exits 1 on any failure. |
| `build_scene_library.py` | Builds `/project1/scene_library`: discovery, quarantine (§15.2–15.4), JSON reports in `validation/`, per-version approvals in `library/approved.json`, and the gated `LoadApproved`. |
| `build_projector_window.py` | Builds `/project1/projector`, the Window COMP that shows `OUTPUT` full-screen on a display. Never opens it; prints the open/close commands and the detected displays. |
| `build_projector_safe.py` | Builds and exports `modules/projector_safe/module.tox` and `thumbnail.png` (rendered over kinetic_stripes' thumbnail, so Block 3 must be exported). |
| `build_stub_module.py` | Builds and exports `modules/stub_scene/module.tox`, a flat-colour test fixture. |
| `diagnose_module_host.py` | Read-only state dump of every host and its loaded module, including orb pool, shader and lockup layout state. **Use this before guessing.** |
| `build_palette_source.py` | Stand-in runtime palette: `palette_source` (`Paletteindex`, editable `library`) → `/project1/PALETTE`. Keeps rows and index. Run before `build_module_host.py`. |
| `build_brand_source.py` | Stand-in branding runtime: `/project1/BRAND` (brand DAT) and `/project1/LOGO` (placeholder logo TOP). Keeps edited table rows across rebuilds. Run before `build_module_host.py`. |
| `build_clean_lockup.py` | Builds and exports `modules/clean_lockup/module.tox` and `thumbnail.png`. Needs `LOGO`; uses its own demo brand table for the thumbnail. |
| `build_orb_burst.py` | Builds and exports `modules/orb_burst/module.tox` and `thumbnail.png`. Checks the shader compiled and the pool produced orbs before saving. |
| `build_performer_controls.py` | Adds `performer_controls` + `engine_controls` before the adapter and patches `motion_adapter` in place (lane scaling, output clamp). Idempotent; carries control values. Runs the diagnose script itself. |
| `diagnose_performer_controls.py` | Read-only. Recomputes each scaled lane from its source and reports PASS/FAIL, plus lane order and clamp range. |
| `build_kinetic_stripes.py` | Builds and exports `modules/kinetic_stripes/module.tox` and `thumbnail.png`. Finishes in two deferred stages (load, then lock the lookup image). |
| `extract_locked_top.py` | Runs **outside** TD. Converts a locked TOP's `.data` from an expanded `.toe` into a PNG. |

Why: custom parameters serialize as opaque magic type codes (`772804868`,
`-1374678769`) whose *field layout differs between files from the same
install*. Hand-authoring them silently corrupts. TD's Python API generates them
correctly and fails with a visible traceback instead.

**The logic inside a built COMP is baked into a Text DAT at build time.** After
editing a builder script you must re-run it — pulsing a parameter uses the old
DAT text. This caught us repeatedly.

### Method B — editing the .toe directly

For plain operator networks with no custom parameters. The official tools ship
with TouchDesigner:

```bash
"C:/Program Files/Derivative/TouchDesigner/bin/toeexpand.exe" file.toe   # -> file.toe.dir/ + file.toe.toc
"C:/Program Files/Derivative/TouchDesigner/bin/toecollapse.exe" file.toe.dir
```

Both print success text but **return exit code 1** — read the output, not the code.

Expanded files are plain text: `name.n` holds operator type, `tile X Y W H`,
flags, `inputs { }`; `name.parm` holds `paramname <flags> <value>` lines between
two `?` lines (flag `0` = constant, `17` = expression). Absent lines mean default.

**Close TouchDesigner first** or it will overwrite your work on its next save.

### Four silent failure modes

All fail with no error, or a warning plus exit code 0:

1. **`toecollapse` builds from the `.toc`, not a directory scan.** Files not
   listed are dropped silently.
2. **The `.toc` must use bare LF.** One CRLF line and collapse prints
   "Unable to find file" and still exits 0. Note `.gitattributes` sets
   `* text=auto`, which would corrupt expanded files if ever committed.
3. **Per node, `.n` must precede `.parm`, which must precede data files**
   (`.chop`, `.ts`). Alphabetical sorting puts `oscin1.chop` first and TD then
   reports "Unexpected node duplication" on load.
4. **COMP wiring is not in the `inputs` block** — see below.

### Wiring across a COMP boundary

Naming a COMP in a CHOP's `inputs` block does nothing; the node ends up with no
input and errors "Not enough sources specified". The real representation is
two-sided:

- **COMP output → consumer**: the consumer's `inputs` names a path *through*
  the COMP: `inputs { 0 <tab>engine_in/out1 }`
- **Producer → COMP input**: a separate `<comp>.network` file beside `<comp>.n`:

```
1
compinputs
{
0 	ENGINE_INPUT
	in0_engine
	CHOP
}
end
```

This cannot be learned from sample `.tox` files — a `.tox` never stores its root
COMP's external connections.

The same rule applies in the Python API: passing a COMP as a connection *source*
raises `td.tdError: Invalid number or type of arguments`. Use
`dst.inputConnectors[0].connect(src_comp.outputConnectors[0])`. A COMP as the
*destination* is fine.

### Getting parameter names and values right

- **Internal names**: `C:\Program Files\Derivative\TouchDesigner\Config\TDParameterHelp.json`
  → `["help"]["CHOPs"]["logicCHOP"]["parameters"]`. Parse with Python;
  PowerShell 5.1's `ConvertFrom-Json` chokes on its duplicate case-insensitive keys.
- **Menu token values are NOT in that JSON.** They *are* in the offline help
  that ships with TouchDesigner:
  `Samples\Learn\OfflineHelp\https.docs.derivative.ca\<Operator>.htm` lists
  each menu as `Label token` pairs (e.g. `GLSL_TOP.htm`: `vec4 vec4`,
  `Uniform Array uniformarray`). Strip tags and grep. The same folder has the
  Python class docs (`ScriptCHOP_Class.htm`). Mining expanded `.tox` files
  under `Samples\Palette` also works and is how `preop 0 rise`,
  `convert 0 bound` and `outputresolution 0 custom` were first confirmed.
- **Menu labels are not always what the help text says.** The Text TOP's
  `fontsizexunit` help reads "Pixels, Fraction, Fraction Aspect or Points",
  but its live `menuLabels` are `px`, `f`, `a`, `pt`. When setting a menu
  whose token is unknown, match against both `menuNames` and `menuLabels` and
  accept several spellings (`menu_pick` in `build_brand_source.py`), and let
  it raise with the real options listed — that is how this was found.
- **The GLSL TOP has exactly three inputs.** Connecting a fourth raises
  `IndexError: list index out of range` on `inputConnectors[3]`. Use the GLSL
  Multi TOP (`glslmultiTOP`) for more — same pixel shader, Vectors and Arrays
  parameters. Multi-input ops expose one spare connector at a time, so fall
  back to `src.outputConnectors[0].connect(dst)` and check `dst.inputs`.
- **A Script CHOP only cooks when its inputs change** unless its callbacks
  return `CookLevel.WHEN_USED` (every frame while used) from
  `onGetCookLevel`. Anything time-based — fades, lifetimes — needs that.
- Multi-value parameters take suffixes (`lag1`/`lag2`, `resolutionw`/`resolutionh`,
  `colorr`/`colorg`/`colorb`), except Logic CHOP bounds which are
  `boundmin`/`boundmax`. The JSON lists only the logical base name.

### TouchDesigner initialises asynchronously

Anything queried synchronously after creating or loading a COMP reports
pre-cook state — resolution, `outputConnectors`, channel counts. The spec's
two-frame warm-up ([SCENE_MODULE_SPEC.md §12](docs/SCENE_MODULE_SPEC.md) steps
6–7) exists for this. `module_host` defers wiring and validation into a
`Finish()` called via `run(..., delayFrames=2)`. Do the same for anything new.

### TouchDesigner cooks lazily — "no output" is usually "nothing asked for it"

TouchDesigner only evaluates operators something needs. A terminal node with
nothing downstream — no display, no window, no export, no active viewer — may
never cook, so it renders nothing and reports default properties.

`module_host/out1` is exactly this case: it is the end of the chain and nothing
consumes it yet (the `/output` layer is Block 6). **To see it, click the small
blue circle at the node tile's bottom-right — the viewer-active flag.** That
creates the cook request.

If someone reports "the output is black", check this before debugging the
chain. It cost a round here. The same applies to any property read off an
un-cooked TOP: width, height and connector lists can all report defaults.
`diagnose_module_host.py` reads live values and is the faster check either way.

## Remaining work

From [SCENE_MODULE_SPEC.md §18](docs/SCENE_MODULE_SPEC.md):

3. ~~`kinetic_stripes`~~ — done (see *Current state*).
4. ~~`orb_burst`~~ — done (see *Current state*).
5. ~~`clean_lockup`~~ — done (see *Current state*).
6. **`projector_safe`** — `finish_fx`, plus final hardware safety in `/output`.
   ~~Done~~ — verified, including the flash limiter and the `projector`
   Window COMP.
7. ~~Quarantine validation and manifest discovery~~ — done (see *Current state*).
8. ~~Freeze `deckglow.scene-module/1`~~ — done (see *Current state*). The
   decisions it needed:
   ~~fallback tempo~~ (done, verified), ~~`Paletteindex` overlap~~ (done: the
   runtime owns it, verified), ~~`toneAmount` semantics~~ (done: centred mood
   lanes, verified), ~~the 1080p licence question~~ (done: the contract is
   resolution-independent, verified).

All eight blocks of SCENE_MODULE_SPEC §18 are complete. The creator pack
format (`deckglow.pack/1`) is built — see *Current state*.

Beyond that: the two-stack crossfade runtime, branding runtime, performer
controls, show profiles and packaging (see V2_ARCHITECTURE blocks 5–9).

## Decisions made

**Performer controls live in the motion adapter, not in modules** (2026-11-04).

The adapter applies `masterIntensity`, `motionAmount`, `flashAmount`,
`textureAmount`, `toneAmount` and `brandAmount` once, before a module sees a
lane. Modules receive pre-scaled lanes and expose no matching parameters.
`Motionamount`/`Textureamount`/`Toneamount` (base scene), `Flashamount`
(hit fx) and `Brandpulseamount` (brand overlay) were removed from the spec —
a control at both levels meant a performer at `0.5` and a module at `0.5`
silently produced `0.25`.

Chosen over the alternative (runtime pushes values into each module's
parameters) because the runtime then guarantees a performer control works
regardless of module quality, which matters once creator packs ship modules the
runtime did not author. Written up in
[SCENE_MODULE_SPEC.md §9.1](docs/SCENE_MODULE_SPEC.md).

**Implemented by script and verified live** (2026-11-05).
`build_performer_controls.py` builds it; it had to land before Block 3 so
`kinetic_stripes` — the reference every later module gets copied from — is
written against final lane semantics. Layout:

```
/project1
  ENGINE_INPUT ──┐
                 ├─ engine_controls (Merge) ─ motion_adapter ─ MOTION_OUT
  performer_controls (Constant, six amounts, default 1.0) ┘

/project1/motion_adapter
  lane_<x> + ctl_<amount> ─ scale_<x> (Math mul) ─ motion_merge ─ clamp_lanes ─ out1
```

Ten lanes are scaled, as HYBRID_RUNTIME_ARCHITECTURE defines them:

| Lane | × |
| --- | --- |
| `body_level` | `masterIntensity` |
| `body_drift` | `motionAmount` × `masterIntensity` |
| `impact_fast` | `flashAmount` × `masterIntensity` |
| `impact_wide` | `masterIntensity` |
| `sync_level` | `masterIntensity` |
| `sync_bar_env` | `masterIntensity` |
| `texture_level` | `textureAmount` × `masterIntensity` |
| `texture_jitter` | `textureAmount` × `masterIntensity` |
| `brand_pulse` | `brandAmount` × `masterIntensity` |
| `mood_warmth` | centred: `0.5 + (x − 0.5) × toneAmount` |
| `mood_softness` | centred: `0.5 + (x − 0.5) × toneAmount` |

The other five pass through. The two mood lanes are Expression CHOPs
(`scale_mood_*`), not Math multiplies — see decision 3 below. `clamp_lanes` limits every lane to `0..1` except
`sync_sine`.

`motion_adapter` itself is still the hand-built Block 1 network in the `.toe`;
the script owns only `ctl_*`, `scale_*`, `clamp_lanes` and the input wiring of
`motion_merge` and `out1`. Save the `.toe` after running it.

Verified live in test mode for the master-fader version (2026-11-05): with
`masterIntensity` at `0.5` all nine scaled lanes PASS, the eight master lanes
halved (`body_level 0.65 → 0.325`, `texture_level 0.45 → 0.225`, and so on) and
`mood_warmth` held at `0.5`. `brand_pulse`'s source read `0.2146 = 0.25 ×
impact_wide 0.8585`, confirming it is not double-scaled by the master through
`impact_wide`.

**`sync_bar_env` added to the master list afterwards, verified in test mode**
(2026-11-05): ten PASS rows at master `0.5`, and `kinetic_stripes`' bar zoom
visibly shrinks with master turned down. Then run end to end with the real
engine and music (live mode, `engine_input_mode` index `0`): `kinetic_stripes`
moves with the track through `module_host`.

Test mode is the easiest place to check: `engine_in/test_levels` holds
`drive 0.65`, `density 0.45`, `tone 0.5`. The saved `.toe` has
`engine_input_mode` at index `0` (live); set `par.index = 1` for test mode. An
earlier live-mode run showed identical values across runs minutes apart — most
likely oscin holding the last values from a stopped engine.

To re-check: run the builder (it prints a PASS/FAIL table two frames later), or
change a value on `performer_controls` (`par.const0value`..`const5value`) and
run `diagnose_performer_controls.py`.

**`masterIntensity` is a master fader** (2026-11-05). It multiplies every energy
lane on top of that lane's own amount (table above), rather than scaling only
`body_level` as the original lane definitions said. Chosen because a DJ
turning "master" down expects flashes and texture to calm too; scaling only
`body_level` left hits punching at full. Stacking `flashAmount × masterIntensity`
is deliberate and is not the double-multiply problem §9.1 removed, which was
the *same* control applied at two levels. Timing lanes are excluded because a
scaled phase ramp sweeps halfway and stops; colour lanes because scaling them
shifts the palette rather than the energy. Envelopes are not timing:
`sync_bar_env` was first grouped with the phase lanes, which left
`kinetic_stripes`' 2× bar zoom firing at full with master at `0`, so it was
moved onto the master list. `texture_jitter` is included (and
also follows `textureAmount`): busy detail such as grain and shimmer is the first
thing a VJ pulls back, and the unscaled timing lanes already keep the screen
alive at master `0`. Spec updated in
HYBRID_RUNTIME_ARCHITECTURE (lane meanings) and SCENE_MODULE_SPEC §9.1.

**`/output` limits flashing for photosensitivity, on by default** (2026-11-05).

The safety stage counts "general flashes" in what is actually shown — an
opposing change of ≥ 10% in relative luminance where the darker side is below
0.80, the WCAG 2.3.1 / broadcast definition — and keeps them to `Maxflashes`
(default 3) per rolling second. It only ever dims: once the next rise would
break the budget, the frame is held just above the current trough until an old
transition ages out. A rise is allowed only when its fall also fits, because
a fall from a peak cannot be prevented by dimming.

```
/project1/output
  safety (GLSL: NaN, clamp, gates) ─┬─ flash_limit (Level, × gain) ─ out1
                                     └─ measure (Analyze average) ─ luma (TOP to CHOP,
                                        immediate) ─ limiter (Script CHOP) ─ gain
```

Chosen over leaving it to venues (strobe warnings) because projector visuals
play to rooms where nobody knows who is watching, and over limiting the
trigger lanes because a module can flash on its own; `/output` is the one
place that holds regardless of module quality — the same reasoning as the
performer controls. `Flashlimit` off is meant as a deliberate per-venue choice
(a venue that permits strobing and posts warnings), later a show-profile
setting, not a performance knob. Both parameters carry across rebuilds.

Tested outside TD on synthetic 60 fps signals: 6 Hz and 10 Hz strobes held to
3 flashes/s; 2 Hz (a flash per beat at 120 BPM), slow fades, sub-10% flicker
and flicker entirely above 0.80 untouched; `Maxflashes 1` holds to 1; gain
never exceeds 1. A strobe at exactly 3 Hz sits on the budget and is
occasionally held.

In TouchDesigner (2026-11-05), with test-mode hits sped to 8 Hz and
`kinetic_stripes` `Flash 2`: the limiter built and runs without errors, and a
diagnose snapshot read `transitions 6` (the 3-flash budget, full) with
`held 1` — it was blocking the next rise. That frame was at a trough
(`luma = shown = 0.2306`, `gain 1.0`), so nothing needed dimming at that
instant; real strobes are counted, since 6 transitions were registered.
Confirmed by eye: the 8 Hz strobe is visibly calmer with `Flashlimit` on than
off. **Verified.**

**The tempo fallback keeps the last usable tempo** (2026-11-05, Block 8
decision 1 of 4). Block 1 had a fixed 2 Hz LFO: always 120 BPM, and a phase
jump on every switch, so beat-locked motion jumped and ran at the wrong speed
through every breakdown not at 120. Chosen over correcting the docs because it
is what the contract already promised and breakdowns keep the track's tempo.
`tools/build_tempo_fallback.py` adds `tempo_bpm` to `engine_in` (live from
`/rve/v2/tempo/bpm`, a `test_bpm` constant of 120 in test mode) and replaces
the old chain in `motion_adapter` (`sel_beat_phase` … `add_phase`, ten nodes)
with `phase_keeper`, a Script CHOP feeding `lane_sync_phase`, `ex_sine` and
`ex_tri`. Confident (≥ 0.20, ≥ 0.25 to re-lock): phase = engine beat phase and
the BPM is remembered. Not: phase carries on from where it was at that BPM
(120 if none yet; BPM outside 40–240 ignored; a stalled frame advances at most
0.1 s). Tested outside TD: no jump entering, during or leaving a 128 BPM
breakdown, 174 held, 120 default, no flapping on wobbling confidence.
**Verified in TouchDesigner** (test mode): confident at 120 → `live`, measured
120.00 BPM, PASS; tempo set to 128 then confidence dropped to 0 →
`free-run`, held 128, measured 128.00 BPM, largest frame jump 0.0000, PASS.
The re-lock step was not separately diagnosed in TD (covered by the offline
test). `sync_bar_env` still follows the engine's
bar phase directly and has no fallback; the spec promises none.

**The runtime owns the palette** (2026-11-05, Block 8 decision 2 of 4). The
contract required a per-module `Paletteindex` on every base scene while the
architecture also had a show-level `paletteIndex`, `setPalette(paletteId)` and
a `palettes/` folder in packs — two owners, no rule for which wins. Chosen:
one show-level selection feeds the same palette table to every module that
takes one, so layers share a colour scheme; modules read the table and never
choose between palettes. `Paletteindex` is removed from §10.1 (base scenes
now have no slot-specific parameters), §8.1 states the rule, and quarantine
warns "obsolete Paletteindex" if a module still has one. kinetic_stripes →
1.1.0 and stub → 0.2.0 drop it; kinetic needs re-validating and re-approving.

`tools/build_palette_source.py` builds the stand-in runtime palette:
`palette_source` (custom par `Paletteindex`, wraps around the library) holding
an editable `library` table (deckglow, ember, ice, mono; "r,g,b" per role) and
writing the §8.1 table, out to `/project1/PALETTE`, which
`build_module_host.py` wires into `module_host` and `hit_host` input 2. A
Parameter Execute and a DAT Execute rewrite the table on index change or
library edits. kinetic_stripes ignores the palette (fixed proto look), so
changing it recolours `orb_burst` only — making the stripes follow it is a
separate look decision.

**Verified in TouchDesigner:** kinetic_stripes 1.1.0 re-exported and passes
quarantine with no "obsolete Paletteindex" warning (so the new `.tox` really
lacks it) and is re-approved at 1.1.0; stub 0.2.0 warns only for black at
idle; the other three still pass. The saved `.toe` wires `PALETTE` into
`module_host` and `hit_host` input 2, and switching `Paletteindex` recoloured
the orbs (owner reported all steps fine). The first kinetic re-export failed
with "Error creating file" on `thumbnail.png`, most likely because another app
had it open; the builder now reports that case instead of a traceback.

**The mood lanes are centred; `toneAmount` fades them to neutral**
(2026-11-06, Block 8 decision 3 of 4). Multiplying `mood_warmth` by
`toneAmount` pinned it at `0` — fully cool — when tone influence was turned
off, so `projector_safe` tinted the picture blue (tint −0.030 at Warmth 0.3),
and `mood_softness` ignored the knob entirely. Chosen: both mood lanes scale
around `0.5`, `0.5 + (x − 0.5) × toneAmount`, so `1` is unchanged and `0` is
neutral whatever the music does. The new contract rule (spec §7, lane
meanings): mood lanes are centred and modules treat `0.5` as "no mood".
`build_performer_controls.py` builds them as Expression CHOPs reading
`ctl_toneAmount`; the checker expects the centred values. No module changes
(`projector_safe` already measured warmth from 0.5), so nothing needs
re-approval. **Verified in TouchDesigner** (2026-11-06, test mode with tone
set to 0.8): `toneAmount 0.5` → `mood_warmth 0.65`, `mood_softness 0.35`;
`toneAmount 0` → both `0.5`; all eleven lanes PASS both times. The saved `.toe`
has `toneAmount 1`, test tone 0.5 and live mode restored. (Test mode's tone is
exactly 0.5, so the change is invisible there unless tone is moved first.)

**The contract is resolution-independent** (2026-11-06, Block 8 decision 4 of
4). The TouchDesigner Non-Commercial licence caps images at 1280×1280 (a
1920×1080 request renders at 1280×720), while the docs assumed 1080p and
§15.4 required "output resolution matches the stack". Chosen: the contract
names no resolution. The runtime chooses the output size (later per show or
projector); modules render at whatever they are given, size everything as a
fraction of the frame and read their real working size from their image; the
admission check compares against what the stack actually renders. New spec
§6.4 says so, and §9, §14, §15.3 and §15.4 point at it. Every existing module
was already built this way.

Enforced, not just stated: quarantine now renders each module in a fixed busy
state (`PROBE_STATE`, after Reset and one hit) at the stack size and again at
640×360 — a smaller request for base scenes, a smaller input image for the
other slots — and requires `second resolution` to be exactly 640×360 and
`resolution independent` (mean change across a 32×18 block grid) under 0.05.
Tested outside TD: frame-fraction stripes and orbs score 0.000, fixed-pixel
ones 0.076 and 0.350, so a pixel-sized module fails. Also, an approval no
longer survives a later failed validation of the same version: `IsApproved`
and `LoadApproved` refuse it and the library shows `blocked (fails now)`.

**Verified in TouchDesigner** (2026-11-06): every module renders exactly
640×360 at the second size and passes `resolution independent` — mean block
change kinetic_stripes 0.004 (peak 0.043), clean_lockup 0.000 (peak 0.033,
text), orb_burst, projector_safe and stub 0.000. All four first-party modules
still pass, so their approvals stand. One gap: the check does not prove the
probe frame actually had content (orb_burst's 0.000 peak is consistent with
soft, fraction-sized orbs, and its hit stage in the same run spawned orbs at
0.714, but the probe itself is not compared with idle). Adding "probe differs
from idle" would close it.

**Separate business decision for the owner, not part of the contract:**
TouchDesigner Non-Commercial is for non-commercial use, so paid DJ shows
likely need a Commercial licence — which also lifts the resolution cap.
Every DJ running DeckGlow would need a suitable licence too.

## Open decisions and known gaps

- **`kinetic_stripes` uses no `texture_*` or `mood_*` lane**, because the proto's
  texture branch was locked and its palette is fixed. So `textureAmount` and
  `toneAmount` have no effect on this scene, and it ignores the runtime
  palette. Faithful to what the proto rendered; revisit if the reference scene
  should demonstrate every lane family.
- **`texture_jitter` drifts rather than shimmers.** The spec calls it a
  "higher-frequency" lane, but `noise_tex` has `period 4`, so it wanders slowly.
  Check against what `kinetic_stripes` actually needs in Block 3.
- **The flash limiter measures the whole-frame average only**, so a flash
  confined to part of the screen (a big orb burst in one corner) is diluted
  and may pass. A 4×4 grid of measurements would catch it. It reduces risk; it
  is not a certification — broadcast content still needs a proper flash test.
- **Where performer controls are surfaced.** Decided that the adapter applies
  them, but not yet how a DJ sets them — a TouchDesigner UI panel, MIDI, or an
  external frontend. V2_ARCHITECTURE block 6 covers this; nothing depends on it
  until then.
- **Output is capped at 1280×720 by the TouchDesigner licence, not by a bug.**
  Non-Commercial TouchDesigner limits resolution to 1280×1280, so a 1920×1080
  request clamps to 1280 wide preserving aspect — exactly 1280×720. Confirmed
  by a bare Constant TOP outside any module with literal 1920×1080 parameters
  and the viewer active, reporting 720p in TouchDesigner's own info popup.
  Do not re-investigate: the parameters, expressions, menu value, global res
  multiplier, `resmult`, literal values, forced cooks and the viewer flag were
  all checked and are all correct.

  Resolved for the contract by Block 8 decision 4 (resolution independence,
  see *Decisions made*); the licence itself remains the owner's business
  decision.
- **The TD control bridge listens on all interfaces** (`0.0.0.0:9980`): the
  Web Server DAT has no bind-address parameter. The protocol closes every
  non-loopback connection at once and requires the token, but Windows may
  show a firewall prompt; block it there. Revisit if the Web Server DAT gains
  an address setting.
- ~~**Scripts hardcode absolute paths**~~ - the runtime is relocatable since
  step 5 (relative `Modulepath`, run-time token path, `Startup()` on open).
  Builder docstrings still show this machine's `exec(open(r'C:\Users\...'))`
  lines; adjust the path when running them elsewhere.
- `touchDesigner/Backup/` and numbered incremental saves are tracked and are noise.

## Conventions

- COMPs lowercase (`engine_in`, `motion_adapter`); Null CHOP terminals
  UPPERCASE (`ENGINE_INPUT`, `MOTION_OUT`). Keeps `op('ENGINE_INPUT')`
  unambiguous.
- Scenes read motion lanes only — never raw OSC, never `hit` directly when an
  `impact_*` lane exists, never their own beat oscillators.
- Engine OSC port is **9001** (`Headers/app/RuntimeOptions.h`); the suggested
  config in V2_ARCHITECTURE has 9000/9001 swapped relative to the code. The code
  and the patch agree; the doc is wrong.
- Run the engine with music already playing:
  `x64\Debug\ReactiveVisualEngine.exe`. It prints a live macro readout useful
  for cross-checking against TD. From PowerShell it needs the call operator —
  `& "...\ReactiveVisualEngine.exe"`; a bare quoted path just echoes the string.
- Test mode (`engine_input_mode` Index `1`) needs no engine running — use it for
  scene development. Its generators in `engine_in` are fixed levels
  (`test_levels`: drive 0.65, density 0.45, tone 0.5) plus LFOs: `hit` a 2 Hz
  pulse, `beat_phase` a 2 Hz ramp (120 BPM), `bar_phase` a 0.5 Hz ramp.
- **Live mode (Index `0`) with no engine running shows no movement.** `oscin1`
  has nothing to receive and holds its last values. That is expected, not a
  fault — start the engine with music playing.
