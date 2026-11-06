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

**Blocks 4–8 remain.** See *Remaining work*.

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
| `build_module_host.py` | Builds `/project1/module_host`. Idempotent; carries `Modulepath` across rebuilds. |
| `build_stub_module.py` | Builds and exports `modules/stub_scene/module.tox`, a flat-colour test fixture. |
| `diagnose_module_host.py` | Read-only state dump of the host and loaded module. **Use this before guessing.** |
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
- **Menu token values are NOT in that JSON.** Mine them from real files: expand
  the 278 `.tox` files under `Samples\Palette` and grep the `.parm` files. That
  is how `preop 0 rise`, `convert 0 bound` and `outputresolution 0 custom` were
  confirmed.
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
4. **`orb_burst`** — first `hit_fx`; spawns bounded balls from `impact_trigger`.
   **This is the next block.**
5. **`clean_lockup`** — `brand_overlay` with logo, name and combined modes.
6. **`projector_safe`** — `finish_fx`, plus final hardware safety in `/output`.
7. **Quarantine validation and manifest discovery** — the `/scene_library` layer.
8. **Freeze `deckglow.scene-module/1`** before accepting creator modules.

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

Nine lanes are scaled, as HYBRID_RUNTIME_ARCHITECTURE defines them:

| Lane | × |
| --- | --- |
| `body_level` | `masterIntensity` |
| `body_drift` | `motionAmount` × `masterIntensity` |
| `impact_fast` | `flashAmount` × `masterIntensity` |
| `impact_wide` | `masterIntensity` |
| `sync_level` | `masterIntensity` |
| `texture_level` | `textureAmount` × `masterIntensity` |
| `texture_jitter` | `textureAmount` × `masterIntensity` |
| `mood_warmth` | `toneAmount` |
| `brand_pulse` | `brandAmount` × `masterIntensity` |

The other seven pass through. `clamp_lanes` limits every lane to `0..1` except
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
shifts the palette rather than the energy. `texture_jitter` is included (and
also follows `textureAmount`): busy detail such as grain and shimmer is the first
thing a VJ pulls back, and the unscaled timing lanes already keep the screen
alive at master `0`. Spec updated in
HYBRID_RUNTIME_ARCHITECTURE (lane meanings) and SCENE_MODULE_SPEC §9.1.

## Open decisions and known gaps

- **Fallback tempo mismatch.** Both runtime docs say `sync_phase` free-runs "at
  the last usable tempo". The implementation is a fixed 2 Hz LFO, so it always
  falls back to 120 BPM. Either correct the docs or wire `/rve/v2/tempo/bpm`
  into `engine_in` and drive the fallback LFO from it. Decide before Block 8.
- **`sync_bar_env` ignores `masterIntensity`, so `kinetic_stripes`' bar zoom —
  its biggest move, up to 2× — fires at full even with master at `0`.** It was
  grouped with the timing lanes, but it is an envelope (an amount), not a phase,
  so scaling it is safe. Recommended fix: add it to the master list in
  `build_performer_controls.py` and the lane spec. Owner's call.
- **`kinetic_stripes` uses no `texture_*` or `mood_*` lane**, because the proto's
  texture branch was locked and its palette is fixed. So `textureAmount` and
  `toneAmount` have no effect on this scene, and `Paletteindex` is present but
  unused. Faithful to what the proto rendered; revisit if the reference scene
  should demonstrate every lane family.
- **`texture_jitter` drifts rather than shimmers.** The spec calls it a
  "higher-frequency" lane, but `noise_tex` has `period 4`, so it wanders slowly.
  Check against what `kinetic_stripes` actually needs in Block 3.
- **`toneAmount` at `0` pins `mood_warmth` to `0`** (fully cool), not to a
  neutral `0.5`, and `mood_softness` (`1 - tone`) ignores it. Spec-literal;
  worth a second look if "less tone influence" should mean "more neutral".
- **Where performer controls are surfaced.** Decided that the adapter applies
  them, but not yet how a DJ sets them — a TouchDesigner UI panel, MIDI, or an
  external frontend. V2_ARCHITECTURE block 6 covers this; nothing depends on it
  until then.
- **`Paletteindex` is still per-module** while `paletteIndex` also exists as a
  global control. It survived the §9.1 cleanup because it selects rather than
  scales, so it does not have the double-multiply problem — but the overlap
  should be resolved before Block 8 freezes the contract.
- **Output is capped at 1280×720 by the TouchDesigner licence, not by a bug.**
  Non-Commercial TouchDesigner limits resolution to 1280×1280, so a 1920×1080
  request clamps to 1280 wide preserving aspect — exactly 1280×720. Confirmed
  by a bare Constant TOP outside any module with literal 1920×1080 parameters
  and the viewer active, reporting 720p in TouchDesigner's own info popup.
  Do not re-investigate: the parameters, expressions, menu value, global res
  multiplier, `resmult`, literal values, forced cooks and the viewer flag were
  all checked and are all correct.

  **Product implication worth raising with the owner.** The projector target in
  the architecture docs is 1080p, and [SCENE_MODULE_SPEC.md §15.4](docs/SCENE_MODULE_SPEC.md)
  makes "output resolution matches the stack" a live admission check. Neither
  is achievable on Non-Commercial. Shipping at 1080p needs a Commercial or Pro
  licence. Until then, develop against 1280×720 and treat the resolution check
  as informational rather than a gate.
- **Scripts hardcode absolute paths** containing a username. Fine on one
  machine; derive from `project.folder` when a second machine appears.
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
  for cross-checking against TD.
- Test mode (`engine_input_mode` Index `1`) needs no engine running — use it for
  scene development.
