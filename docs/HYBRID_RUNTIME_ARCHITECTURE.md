# Hybrid Runtime Architecture

This document defines the concrete TouchDesigner-side runtime for the macro-driven DJ visual system.

The exact authoring and validation contract for modules loaded by this runtime
is defined in [SCENE_MODULE_SPEC.md](SCENE_MODULE_SPEC.md).

It is intentionally biased toward:

- small club and projector use
- fast DJ setup
- stable scene behavior
- simple branding
- future compatibility with approved creator packs

The key design decision is:

- the C++ engine owns audio capture, low-level analysis, and macro generation
- TouchDesigner owns scene assembly, branding, transitions, and visual rendering
- scenes do not read raw audio analysis directly by default
- all default scenes consume one prepared motion contract

## Goals

The runtime must:

- make it easy to add scenes without rewiring the project
- keep scene motion consistent across different visual styles
- let DJs add their name/logo quickly
- allow modular hit effects such as orb bursts, flashes, and glitches
- support a future pack system without changing the runtime contract

The runtime must avoid:

- every scene interpreting macros differently
- direct scene switching in the live output path
- hidden dependencies between scenes and global controls
- arbitrary third-party modules touching the main output graph

## Design Principles

The runtime follows five rules:

1. One canonical engine input contract.
2. One canonical motion-adapter contract.
3. One fixed slot model for rendering.
4. Scene modules are isolated from one another.
5. Future creator packs are allowed only through approved slot contracts.

## Runtime Layers

The TouchDesigner project should be structured as:

```text
/project1
  /engine_in
  /macro_bus
  /motion_adapter
  /runtime_state
  /scene_runtime
    /current_stack
      /base_scene
      /hit_fx
      /brand_overlay
      /finish_fx
    /next_stack
      /base_scene
      /hit_fx
      /brand_overlay
      /finish_fx
    /transition
  /scene_library
  /ui
  /output
  /debug
```

Each layer has one job:

- `/engine_in`: receive OSC from the C++ engine
- `/macro_bus`: normalize the five engine macros into stable local channels
- `/motion_adapter`: derive scene-safe motion lanes from the macro bus
- `/runtime_state`: store current scene ids, control values, palette, brand config, and setlist state
- `/scene_runtime`: load, warm, blend, and unload active visual modules
- `/scene_library`: discover installed scenes, hit effects, and brand styles
- `/ui`: local TouchDesigner control surface and optional bridge to external frontend
- `/output`: final safety clamp, projector-safe finishing, and display routing
- `/debug`: raw channel inspection and performance diagnostics

## Engine Input Contract

The runtime should treat the engine as an external service that provides:

```text
/rve/v2/macro/drive
/rve/v2/macro/hit
/rve/v2/macro/sync
/rve/v2/macro/density
/rve/v2/macro/tone
```

Raw channels such as `/audio/*`, `/tempo/*`, and `/structure/*` remain available in `/debug`, but the default runtime should not depend on them for scene behavior.

## Macro Bus

`/macro_bus` is the stable local handoff point for all scenes.

Suggested local channel names:

```text
drive
hit
sync
density
tone
```

Suggested supporting local controls:

```text
masterIntensity
motionAmount
flashAmount
textureAmount
toneAmount
brandAmount
transitionTime
paletteIndex
```

Rules:

- `drive`, `hit`, `sync`, `density`, and `tone` always stay normalized to `0..1`
- user controls are multiplied in later layers, not written back into the raw macro channels
- all scene modules read the same local macro names

## Motion Adapter

The motion adapter is the most important stability layer in the system.

Its job is to turn the five macro controls into a richer but standardized set of motion lanes.
Scenes consume these lanes instead of inventing their own meaning for each macro.

Suggested channels:

```text
body_level
body_drift
impact_fast
impact_wide
impact_trigger
sync_phase
sync_sine
sync_triangle
sync_bar_env
texture_level
texture_jitter
mood_warmth
mood_softness
brand_pulse
blackout_gate
```

### Motion Lane Meanings

`body_level`

- sustained scene energy
- derived from `drive * masterIntensity`
- use for main translation, scale breathing, or base brightness

`body_drift`

- slower continuous motion lane
- derived from `drive` and `motionAmount`
- use for gentle offset, slow tunnel flow, or camera drift

`impact_fast`

- quick transient envelope
- derived from `hit * flashAmount`
- use for flashes, stabs, bloom spikes, orb spawns

`impact_wide`

- longer impact envelope
- derived from a softened version of `hit`
- use for zoom punches, ripple growth, streak persistence

`impact_trigger`

- one-frame, debounced event pulse
- derived centrally from `hit`
- use for discrete spawns such as balls, rings, and particle bursts

`sync_phase`

- repeating `0..1` timing lane
- derived from `sync`
- use for sweeps, scanner positions, repeated oscillators

`sync_sine`

- bipolar beat-locked motion lane
- use for rotation, wobble, pan, or cyclic reveal

`sync_triangle`

- cleaner linear motion lane
- use for scan bars, wipes, and repeating travel

`sync_bar_env`

- slower rhythmic accent envelope
- derived from smoothed sync peaks
- use for stronger phrase-like movement without exposing raw bar pulses

`texture_level`

- busyness lane
- derived from `density * textureAmount`
- use for noise opacity, distortion amount, particle count, or line density

`texture_jitter`

- higher-frequency texture helper
- derived from `density`
- use sparingly for shimmer, grain, or micro-motion

`mood_warmth`

- slow palette guidance lane
- derived from `tone * toneAmount`
- use for warm-vs-cool or bright-vs-dark palette selection

`mood_softness`

- complementary finish lane
- use for blur-vs-sharpen, contrast softness, or edge hardness

`brand_pulse`

- restrained branding accent lane
- derived mostly from `impact_wide` with a low ceiling
- use for tasteful logo brightness or name emphasis

`blackout_gate`

- final safety/structure lane
- defaults to `1`
- later can be reduced by reliable breakdown or silence logic

### Motion Adapter Rules

- scenes should never read `hit` directly if an `impact_*` lane exists
- event-spawning modules should use `impact_trigger` instead of deriving their
  own hit threshold
- scenes should never derive their own beat oscillators if `sync_*` lanes exist
- scenes should not use `tone` to drive large geometry changes
- branding should use `brand_pulse`, not raw `hit`

## Slot Model

The runtime should always assemble output from four slots:

```text
base_scene -> hit_fx -> brand_overlay -> finish_fx
```

This applies to both the current and next stack.

### Why the slot model stays clean

- base scenes own the main visual identity
- hit effects own event responses
- brand overlays own logo/name presentation
- finish effects own polish and projector-safe finishing

No slot should do another slot's job.

## Stack Model

Use a two-stack runtime:

```text
/scene_runtime/current_stack
/scene_runtime/next_stack
```

Scene changes should work like this:

1. Load requested modules into `next_stack`.
2. Apply current macro bus and user controls.
3. Warm the next stack for a short pre-roll.
4. Crossfade from `current_stack` to `next_stack`.
5. Swap roles.
6. Unload or park the old stack.

This avoids live graph mutation on the active output path.

## Module Types

The hybrid-first runtime supports four approved module types.

### 1. Base Scene Module

Purpose:

- define the main visual language

Examples:

- stripes
- tunnel
- particle field
- grid pulse
- logo wash

Required inputs:

- motion-adapter CHOP with all standardized lanes
- optional palette/settings DAT or parameter page

Required output:

- `out1` TOP

Required custom parameters:

- `Intensity`
- `Motionamount`
- `Textureamount`
- `Toneamount`
- `Paletteindex`

Restrictions:

- should not render logo/name directly
- should not assume any particular hit effect exists
- should be visually meaningful with only `body_*`, `sync_*`, `texture_*`, and `mood_*`

### 2. Hit Effect Module

Purpose:

- add event-driven reactions on top of the base scene

Examples:

- orb burst
- radial flash
- glitch slice
- ripple ring
- particle spark

Required inputs:

- input TOP from the base scene
- motion-adapter CHOP

Required output:

- `out1` TOP

Required custom parameters:

- `Flashamount`
- `Fxamount`
- `Blendmode`
- `Colorize`

Restrictions:

- must respond mainly to `impact_fast`, `impact_wide`, and optionally `sync_*`
- should not replace the whole base look
- must work correctly when disabled or bypassed

### 3. Brand Overlay Module

Purpose:

- apply the DJ's logo, name, or identity treatment

Examples:

- corner bug
- lower-third lockup
- center hero logo
- logo echo

Required inputs:

- input TOP from the previous slot
- brand asset paths or prepared brand TOPs
- motion-adapter CHOP

Required output:

- `out1` TOP

Required custom parameters:

- `Logoopacity`
- `Nameopacity`
- `Placement`
- `Safearea`
- `Brandpulseamount`

Restrictions:

- default mode should remain readable on a projector
- should support logo-only, text-only, and combined modes
- should use `brand_pulse` sparingly

### 4. Finish Effect Module

Purpose:

- final polish before output

Examples:

- bloom/contrast finish
- monochrome finish
- CRT/glow finish
- projector-safe wash

Required inputs:

- input TOP from the previous slot
- motion-adapter CHOP

Required output:

- `out1` TOP

Required custom parameters:

- `Contrast`
- `Brightness`
- `Softness`
- `Outputclamp`

Restrictions:

- should not introduce scene-specific geometry
- should be safe to bypass globally

## Branding Runtime

Branding should be treated as a global data system, not a per-scene hack.

Suggested global brand inputs:

```text
brand.logoPath
brand.displayName
brand.subtitle
brand.primaryColor
brand.secondaryColor
brand.mode
brand.scale
brand.opacity
```

Default asset support:

- `PNG` with alpha for logos
- optional alpha-capable motion logo format later
- `Text TOP` for DJ name rendering

Safe default modes:

- logo only
- text only
- logo + name lockup

## Scene Library

`/scene_library` should discover installed modules from disk and build a runtime table.

Suggested local library tables:

- `base_scenes`
- `hit_effects`
- `brand_modules`
- `finish_effects`
- `palettes`
- `setlists`

Each row should include:

- id
- type
- display name
- author
- version
- path
- thumbnail
- performance tier
- tags
- enabled

## Frontend Actions

The runtime should expose a small command surface, whether controlled by an internal TouchDesigner UI or a later external frontend.

Suggested actions:

- `loadBaseScene(sceneId)`
- `loadHitEffect(effectId)`
- `loadBrandModule(moduleId)`
- `loadFinishEffect(moduleId)`
- `setPalette(paletteId)`
- `setBrandLogo(path)`
- `setBrandName(text)`
- `setControl(name, value)`
- `transitionToCurrentSelection()`
- `savePreset(presetId)`
- `loadPreset(presetId)`

Suggested preset contents:

- selected base scene
- selected hit effect
- selected brand module
- selected finish effect
- palette
- user control values
- brand text/logo config

## TouchDesigner UI

The in-project UI should be split into:

- runtime view
- scene browser
- branding panel
- control panel
- debug panel

The control panel should stay small:

- scene selection
- hit effect selection
- brand style selection
- palette selection
- `intensity`
- `motion`
- `flash`
- `texture`
- `tone`
- `logo prominence`
- transition trigger

## Future Creator Pack Compatibility

Later approved creator packs should not change the runtime shape.

They should only supply modules that fit approved slot contracts:

- base scene
- hit effect
- brand overlay
- finish effect

This is the main reason to choose the hybrid-first architecture:

- the runtime is fixed
- creator packs are content, not alternate runtimes

Future pack discovery model:

```text
Packs/
  creator_pack_name/
    pack.json
    scenes/
    hit_fx/
    brand_fx/
    finish_fx/
    palettes/
    assets/
```

The runtime can adopt pack installation later without changing:

- macro bus
- motion adapter
- stack model
- slot contracts

## Validation Rules

Every module should be validated before it enters the live runtime.

Minimum checks:

- correct module type
- required `out1` output exists
- required custom parameters exist
- manifest is readable
- thumbnail exists or fallback is assigned
- performance tier is declared

Optional later checks:

- estimated GPU cost
- supported branding modes
- compatible runtime version

## Repo Implications

This runtime architecture changes how the project should evolve:

- the C++ side should continue to own macro quality, not scene semantics
- the TouchDesigner side should become a runtime host, not a single monolithic scene
- documentation should separate engine contracts from runtime/module contracts

Suggested next implementation docs:

- [SCENE_MODULE_SPEC.md](SCENE_MODULE_SPEC.md)
- `PACK_FORMAT_SPEC.md`
- `FRONTEND_MESSAGE_CONTRACT.md`

## Recommended Implementation Order

1. Build `/macro_bus` and `/motion_adapter` in the TouchDesigner base patch.
2. Turn the current stripes setup into the first `base scene` module.
3. Add one `hit_fx` module, for example `orb_burst`.
4. Add one `brand_overlay` module, for example `corner_bug`.
5. Add one `finish_fx` module, for example `projector_safe_contrast`.
6. Build the two-stack runtime and crossfade system.
7. Build an in-TouchDesigner scene browser and branding panel.
8. Freeze the slot contracts before attempting creator packs.

At that point, the system is ready for approved creator-pack work without requiring a structural rewrite.
