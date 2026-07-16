# Scene Module Specification

Status: Draft v1  
Contract id: `deckglow.scene-module/1`  
Target runtime: DeckGlow v2 TouchDesigner runtime

This document defines the authoring contract for visual modules loaded by the
hybrid runtime described in
[HYBRID_RUNTIME_ARCHITECTURE.md](HYBRID_RUNTIME_ARCHITECTURE.md).

The contract has two audiences:

- the DeckGlow runtime, which must load modules without custom wiring
- scene creators, who need a small, predictable surface for building visuals

The first-party modules and future approved creator packs use this same
contract. A creator pack groups modules; it does not receive a separate runtime
or direct access to the audio engine.

## 1. Scope

A scene module is one reusable visual unit that occupies exactly one runtime
slot:

```text
base_scene -> hit_fx -> brand_overlay -> finish_fx
```

This specification defines:

- module files and metadata
- TouchDesigner inputs and output
- motion and data contracts
- required public parameters
- lifecycle and bypass behavior
- creator-facing controls
- validation and compatibility rules

This specification does not define:

- how packs are downloaded or installed
- frontend-to-TouchDesigner messages
- licensing or marketplace policy
- low-level audio analysis

Those concerns belong to the later pack and frontend contracts.

## 2. Design Rules

Every approved module follows these rules:

1. It occupies one slot and performs only that slot's job.
2. It consumes prepared motion lanes, not raw OSC or raw audio features.
3. It has no knowledge of the modules before or after it.
4. It produces one complete image through `out1`.
5. It can be reset, warmed, enabled, and bypassed by the runtime.
6. It exposes controls only through declared custom parameters.
7. It does not modify operators outside its own component.

The runtime owns composition, switching, crossfades, projector output, preset
storage, and global DJ controls. A module owns only its visual behavior.

## 3. Terms

`module`

- a reusable `.tox` implementation for one slot

`module instance`

- a loaded copy of a module inside `current_stack` or `next_stack`

`scene preset`

- a saved combination of one module per slot, palette, branding, and control
  values

`motion lane`

- a scene-safe CHOP channel prepared by `/motion_adapter`

`standard parameter`

- a required parameter controlled by the runtime

`creative control`

- an optional, manifest-declared parameter shown to the DJ

## 4. Module Package

During development, one module is stored as:

```text
module_id/
  module.json
  module.tox
  thumbnail.png
  assets/
```

Rules:

- `module.json`, `module.tox`, and `thumbnail.png` are required.
- `assets/` is optional.
- All paths in the manifest are relative to the module directory.
- A module must not depend on files outside its module directory.
- The thumbnail should be a `16:9` PNG, with `640x360` recommended.
- The module directory can later be copied unchanged into a creator pack.

## 5. Module Manifest

`module.json` is the discovery and validation source of truth. It does not
replace the required TouchDesigner operator and parameter checks.

### 5.1 Required fields

```json
{
  "schema": "deckglow.scene-module/1",
  "id": "com.deckglow.stripes",
  "type": "base_scene",
  "displayName": "Kinetic Stripes",
  "author": "DeckGlow",
  "version": "1.0.0",
  "runtimeApi": ">=2.0.0 <3.0.0",
  "entry": "module.tox",
  "thumbnail": "thumbnail.png",
  "performanceTier": "standard",
  "tags": ["geometric", "high-contrast"],
  "controls": []
}
```

Field rules:

| Field | Rule |
| --- | --- |
| `schema` | Must equal `deckglow.scene-module/1`. |
| `id` | Stable lowercase reverse-domain id; never reused for another module. |
| `type` | One of `base_scene`, `hit_fx`, `brand_overlay`, `finish_fx`. |
| `displayName` | User-facing name, maximum 48 characters. |
| `author` | User-facing creator name, maximum 48 characters. |
| `version` | Semantic version for this module. |
| `runtimeApi` | Compatible DeckGlow runtime API range. |
| `entry` | Relative path to the module `.tox`. |
| `thumbnail` | Relative path to the preview PNG. |
| `performanceTier` | One of `light`, `standard`, `heavy`. |
| `tags` | Zero to eight lowercase discovery tags. |
| `controls` | Zero to eight creative control declarations. |

### 5.2 Optional fields

```json
{
  "description": "Beat-locked stripes with controlled texture movement.",
  "license": "Proprietary",
  "homepage": "https://example.com",
  "contentRating": "general",
  "capabilities": {
    "usesPython": false,
    "usesAudioFileIn": false,
    "supportsAlphaAssets": true
  }
}
```

Optional metadata must never be required for the module to render.

## 6. TouchDesigner Component Contract

The entry file contains one exported Base COMP. The instance name is assigned
by the runtime, so a module must not depend on its root component name.

### 6.1 Required internal operators

Every module contains:

```text
/module_root
  /render
  /out1
```

Operator rules:

- `render` is a Base COMP containing or organizing the render network.
- `out1` is an Out TOP and is the only public image output.
- type-specific In operators use the exact indexed names defined below
- Additional internal operators may use any names except reserved names.

Base scenes contain:

```text
/module_root/in0_motion
```

All image-processing slots contain:

```text
/module_root/in0_image
/module_root/in1_motion
```

Modules using palette, brand, or logo data contain the corresponding optional
In operators listed in the slot contract.

TouchDesigner orders component connectors alphanumerically by the names of its
internal In operators. The numeric name prefixes are therefore required; they
make the connector order deterministic after a module is exported and loaded.

### 6.2 Reserved names

These root-level names are reserved for the runtime contract:

```text
in0_image
in0_motion
in1_motion
in1_palette
in2_palette
in2_brand
in3_logo
render
out1
```

Creators must not repurpose a reserved name for another operator family.

### 6.3 Output contract

`out1` must:

- always produce a valid TOP while `Moduleactive` is on
- output a complete frame, not a control mask
- use the runtime render width and height
- preserve the input resolution for non-base modules
- avoid `NaN` and infinite pixel values
- remain display-referred RGB unless the module explicitly performs a finish
  operation

The runtime converts the output to its working pixel format. `RGBA16Float` is
recommended inside the runtime to avoid banding during composition.

## 7. Shared Motion Contract

The slot's motion In CHOP receives a one-sample CHOP containing all required
lanes:

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

All unipolar lanes use `0..1`. `sync_sine` is bipolar and uses `-1..1`.

`impact_trigger` is a one-frame, debounced pulse created centrally by the
motion adapter. Event-spawning modules must use this lane instead of performing
their own threshold detection on `hit` or `impact_fast`.

Forward-compatibility rules:

- runtimes may append motion lanes in a minor API release
- modules must ignore unknown lanes
- required lanes cannot be removed or change meaning until a major API release
- modules must not select channels using `*` in their final shipping network

## 8. Shared Data Inputs

### 8.1 Palette DAT

The optional palette In DAT is a table with this schema:

```text
role        r     g     b     a
background  0.02  0.02  0.03  1.0
primary     1.00  0.82  0.10  1.0
secondary   0.10  0.35  1.00  1.0
accent      1.00  1.00  1.00  1.0
```

Rules:

- values are normalized `0..1`
- `background`, `primary`, `secondary`, and `accent` are required roles
- runtimes may add roles; modules must ignore roles they do not use
- a module must still render if its palette input is absent, using internal
  defaults

### 8.2 Brand DAT

`in2_brand` is a two-column Table DAT:

```text
key             value
displayName     DJ NAME
subtitle        LIVE
mode            logo_and_name
primaryColor    1.0,0.82,0.1,1.0
secondaryColor  0.1,0.35,1.0,1.0
scale           1.0
opacity         1.0
```

Required keys are `displayName`, `mode`, `scale`, and `opacity`. Empty text is
valid. Unknown keys must be ignored.

`in3_logo` receives a prepared logo TOP from the branding runtime. The module
does not open the user's logo path directly.

## 9. Standard Parameters

All entry COMPs contain a custom page named `DeckGlow` with these exact
parameter names:

| Parameter | Type | Range/default | Runtime behavior |
| --- | --- | --- | --- |
| `Moduleactive` | Toggle | default `1` | Enables internal cooking and animation. |
| `Intensity` | Float | `0..1`, default `1` | Scales the module's overall visual contribution. |
| `Seed` | Integer | default `1` | Makes procedural variation repeatable. |
| `Reset` | Pulse | n/a | Clears temporal state and restarts deterministic animation. |
| `Outputwidth` | Integer | default `1920` | Requested render width for base scenes. |
| `Outputheight` | Integer | default `1080` | Requested render height for base scenes. |

Rules:

- the internal parameter names and capitalization are part of the API
- the runtime may write these parameters at any time
- `Reset` must not change saved creative control values
- the same `Seed` and control values should produce equivalent procedural
  behavior after `Reset`
- non-base modules preserve their input dimensions; `Outputwidth` and
  `Outputheight` remain present for a uniform API

## 10. Slot Contracts

### 10.1 Base Scene

Manifest type: `base_scene`

Connector order:

| Index | Operator | Family | Required |
| --- | --- | --- | --- |
| `0` | `in0_motion` | CHOP | Yes |
| `1` | `in1_palette` | DAT | No |

Additional required parameters on a custom page named `Scene`:

| Parameter | Type | Range/default |
| --- | --- | --- |
| `Motionamount` | Float | `0..1`, default `1` |
| `Textureamount` | Float | `0..1`, default `1` |
| `Toneamount` | Float | `0..1`, default `1` |
| `Paletteindex` | Integer | minimum `0`, default `0` |

Behavior:

- owns the main composition and visual identity
- uses `body_*`, `sync_*`, `texture_*`, and `mood_*` lanes
- remains visually meaningful at idle, with all motion lanes at zero
- does not render a DJ name or logo
- does not depend on a hit effect for its basic composition

When inactive, a base scene may stop expensive cooking. It must resume after
`Reset` without retaining state from its previous activation.

### 10.2 Hit Effect

Manifest type: `hit_fx`

Connector order:

| Index | Operator | Family | Required |
| --- | --- | --- | --- |
| `0` | `in0_image` | TOP | Yes |
| `1` | `in1_motion` | CHOP | Yes |
| `2` | `in2_palette` | DAT | No |

Additional required parameters on a custom page named `Hit FX`:

| Parameter | Type | Range/default |
| --- | --- | --- |
| `Flashamount` | Float | `0..1`, default `0.5` |
| `Fxamount` | Float | `0..1`, default `1` |
| `Blendmode` | Menu | `over`, `add`, `screen`, default `over` |
| `Colorize` | Float | `0..1`, default `1` |

Behavior:

- uses `impact_trigger` for discrete events such as spawning balls or rings
- uses `impact_fast` and `impact_wide` for event shape and persistence
- may use `sync_*` for rhythmic motion after an event
- does not replace the base composition during normal operation
- passes `in0_image` through unchanged when `Moduleactive` is off or
  `Intensity`/`Fxamount` is zero
- bounds particle counts and feedback history to prevent unbounded growth

Example `orb_burst` creative controls could be `Ballsize`, `Lifetime`,
`Spawncount`, and `Spread`. These are module-specific and must be declared in
the manifest.

### 10.3 Brand Overlay

Manifest type: `brand_overlay`

Connector order:

| Index | Operator | Family | Required |
| --- | --- | --- | --- |
| `0` | `in0_image` | TOP | Yes |
| `1` | `in1_motion` | CHOP | Yes |
| `2` | `in2_brand` | DAT | Yes |
| `3` | `in3_logo` | TOP | No |

Additional required parameters on a custom page named `Brand`:

| Parameter | Type | Range/default |
| --- | --- | --- |
| `Logoopacity` | Float | `0..1`, default `1` |
| `Nameopacity` | Float | `0..1`, default `1` |
| `Placement` | Menu | `center`, `top_left`, `top_right`, `bottom_left`, `bottom_right` |
| `Safearea` | Float | `0..0.25`, default `0.05` |
| `Brandpulseamount` | Float | `0..1`, default `0.25` |

Behavior:

- supports logo-only, text-only, and combined modes
- reads prepared text values from `in2_brand` and prepared pixels from
  `in3_logo`
- uses `brand_pulse`, never `impact_trigger`, for restrained reactive emphasis
- keeps the logo/name inside the configured safe area
- maintains legibility against both bright and dark inputs
- passes `in0_image` through unchanged when inactive or intensity is zero

The branding runtime, not the module, owns file selection, image decoding, and
font availability.

### 10.4 Finish Effect

Manifest type: `finish_fx`

Connector order:

| Index | Operator | Family | Required |
| --- | --- | --- | --- |
| `0` | `in0_image` | TOP | Yes |
| `1` | `in1_motion` | CHOP | Yes |

Additional required parameters on a custom page named `Finish`:

| Parameter | Type | Range/default |
| --- | --- | --- |
| `Contrast` | Float | `0..2`, default `1` |
| `Brightness` | Float | `0..2`, default `1` |
| `Softness` | Float | `0..1`, default `0` |
| `Outputclamp` | Toggle | default `1` |

Behavior:

- owns final visual polish, not scene geometry
- may use `mood_warmth`, `mood_softness`, and a restrained `impact_wide`
- preserves input dimensions
- passes `in0_image` through unchanged when inactive or intensity is zero
- never bypasses the runtime's final projector safety stage

## 11. Creative Controls

A module may expose up to eight extra controls. This limit keeps the DJ-facing
UI understandable and presets portable.

Each creative control:

- is a custom parameter on a page named `Controls`
- is declared in `module.json`
- uses a stable parameter name across patch releases
- has a safe default
- can be changed while the module is live
- is stored in scene presets by parameter name

Supported v1 control types:

```text
float
integer
toggle
menu
color
```

Example:

```json
{
  "controls": [
    {
      "parameter": "Ballsize",
      "label": "Ball Size",
      "type": "float",
      "min": 0.02,
      "max": 0.4,
      "default": 0.12,
      "group": "Shape"
    },
    {
      "parameter": "Spawncount",
      "label": "Balls Per Hit",
      "type": "integer",
      "min": 1,
      "max": 12,
      "default": 4,
      "group": "Emission"
    }
  ]
}
```

The frontend builds controls from this metadata. It never edits internal
operator parameters or executes creator-provided expressions.

## 12. Lifecycle

The runtime manages modules in this order:

1. Load the `.tox` into the inactive stack.
2. Connect all required inputs.
3. Apply standard parameters and saved creative controls.
4. Set `Moduleactive` to `1`.
5. Pulse `Reset`.
6. Warm the module for at least two frames.
7. Confirm that `out1` is valid and at the requested resolution.
8. Crossfade the inactive stack into the live output.
9. Set old-stack modules to `Moduleactive = 0` after the transition.
10. Park or unload the old instances.

Modules must not perform visible scene switching internally. The runtime owns
all stack transitions.

### 12.1 State rules

- Feedback, particle, timer, and cache state must clear on `Reset`.
- Loading a preset must not require rebuilding the module network.
- A module must tolerate parameters being applied before its first cooked
  frame.
- A module must not assume the TouchDesigner timeline starts at frame zero.
- Temporal behavior should use elapsed time or prepared motion lanes, not a
  hard-coded project frame range.

### 12.2 Missing-input behavior

The validator rejects a module with a missing required input. During authoring:

- a base scene should render a static safe fallback if motion is absent
- hit, brand, and finish modules should pass through `in0_image` if auxiliary
  data is absent
- missing optional palette or logo inputs must not produce an error

## 13. Isolation and Safety

Approved modules may use TouchDesigner Python internally, but they must not:

- write to the filesystem
- access the network
- launch processes
- install packages
- load arbitrary external `.tox` files at runtime
- navigate upward and modify operators outside their own root COMP
- change global project, window, audio, OSC, or output settings
- evaluate Python or expressions received from a frontend message

Assets must be loaded only from the module directory or through prepared
runtime inputs. Modules with Python declare `capabilities.usesPython = true`
and receive additional review before approval.

## 14. Performance Contract

The product target is stable `60 fps` at the configured projector resolution.
The complete four-slot stack must leave time for TouchDesigner UI, transitions,
and output routing.

Performance tiers describe intended cost, not a guarantee across all hardware:

| Tier | Intended use |
| --- | --- |
| `light` | Suitable for two-stack transitions on entry-level show hardware. |
| `standard` | Suitable for normal single-stack playback at 1080p. |
| `heavy` | Requires stronger hardware or reduced render resolution. |

Rules:

- particle pools, feedback buffers, and history lengths have fixed limits
- inactive modules stop expensive optional cooking where practical
- modules do not force a resolution larger than the runtime request
- performance is measured in an isolated test scene and in a four-slot stack
- the library records measured hardware, resolution, frame rate, and cook cost
  separately from the creator-declared tier

The runtime may block a `heavy` module on a hardware profile configured for
`light` modules only.

## 15. Validation

Modules enter the live library only after passing all validation stages.

### 15.1 Static package checks

- required files exist
- manifest JSON parses
- id, version, type, and runtime range are valid
- referenced paths remain inside the module directory
- thumbnail dimensions and format are valid
- no more than eight controls are declared
- every declared control has a matching custom parameter

### 15.2 TouchDesigner interface checks

- entry `.tox` loads in a quarantine component
- required In operators exist with correct families and indices
- `render` and `out1` exist with correct families
- all standard and type-specific parameters exist with correct types
- no reserved operator name is misused
- module type matches its connector and parameter contract

### 15.3 Runtime behavior checks

The validator runs synthetic states:

| Test | Motion state | Expected result |
| --- | --- | --- |
| Idle | all reactive lanes `0`, `blackout_gate = 1` | Valid, stable frame. |
| Drive | `body_level` and `body_drift` sweep `0..1` | No errors or invalid pixels. |
| Hit | one `impact_trigger`, shaped impact envelopes | One bounded response. |
| Sync | `sync_phase` sweeps and wraps | Continuous rhythmic motion. |
| Dense | texture lanes at `1` | Stable frame rate and bounded resources. |
| Reset | stateful content, then `Reset` | Temporal state clears. |
| Bypass | inactive or zero intensity | Pass-through for non-base slots. |

For pass-through modules, a small format-conversion tolerance is acceptable,
but bypass must not introduce a visible effect.

### 15.4 Live admission checks

- output resolution matches the stack
- output remains valid through a warm-up window
- module does not modify operators outside quarantine
- measured performance is recorded
- module is explicitly approved before its id is enabled

## 16. Compatibility and Versioning

There are three independent versions:

- module schema: shape of `module.json`
- runtime API: connectors, lanes, parameters, and lifecycle
- module version: creator's content release

Compatibility rules:

- adding optional metadata is a schema minor change
- adding a motion lane is a runtime API minor change
- removing or changing a lane, connector, or required parameter is a runtime
  API major change
- creators increment the module major version when presets cannot migrate
- the runtime never loads a module outside its declared `runtimeApi` range

Preset migration is by stable module id and parameter name. Renaming a creative
parameter requires an explicit migration map in a future manifest revision.

## 17. First-Party Reference Modules

The first implementation should prove all four contracts with:

```text
base_scene:     kinetic_stripes
hit_fx:         orb_burst
brand_overlay:  clean_lockup
finish_fx:      projector_safe
```

Acceptance goals:

- `kinetic_stripes` is the current polished stripes patch moved behind the base
  scene contract
- `orb_burst` spawns bounded colored balls from `impact_trigger`
- `clean_lockup` supports logo, name, and logo-plus-name modes
- `projector_safe` provides restrained contrast, softness, and output clamping
- any module can be replaced without editing another module

## 18. Implementation Blocks

Implement and review the contract one block at a time:

1. Add the canonical motion input and synthetic test CHOP to the TouchDesigner
   project, including `impact_trigger`.
2. Build a reusable module-wrapper COMP that connects inputs, applies standard
   parameters, pulses reset, and checks `out1`.
3. Export the current stripes network as the `kinetic_stripes` base module.
4. Build `orb_burst` as the first event-driven hit module.
5. Build `clean_lockup` with prepared logo TOP and brand DAT inputs.
6. Build `projector_safe` and put final hardware safety after it in `/output`.
7. Add quarantine validation and manifest-driven discovery.
8. Freeze `deckglow.scene-module/1` before accepting creator modules.

The pack format should be designed only after these four reference modules pass
the same validator. This lets creator packs package a proven contract instead
of defining behavior that the runtime has not exercised.

## 19. TouchDesigner References

The connector and operator portions of this contract follow Derivative's
documentation:

- [Component inputs and outputs](https://docs.derivative.ca/Component)
- [In CHOP](https://docs.derivative.ca/In_CHOP)
- [In TOP](https://docs.derivative.ca/In_TOP)
- [In DAT](https://docs.derivative.ca/In_DAT)
