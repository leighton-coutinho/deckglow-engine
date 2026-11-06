# Creator Pack Format Specification

Status: Draft v1 (2026-11-06)  
Format id: `deckglow.pack/1`  
Module contract: [`deckglow.scene-module/1`](SCENE_MODULE_SPEC.md) (frozen), runtime API `2.0.0`  
Tooling: `touchDesigner/tools/pack_tool.py`

A creator pack is how modules made outside DeckGlow reach a DJ. It is
**content, not an alternate runtime** (HYBRID_RUNTIME_ARCHITECTURE): a pack
supplies modules that fit the four frozen slot contracts, and optionally
palettes. It never changes the motion adapter, the stack, `/output` or the
contract.

## 1. Decisions

Settled by the owner on 2026-11-06:

| Question | Decision |
| --- | --- |
| Who can publish | **Anyone.** Every pack is checked on the DJ's machine, every module goes through quarantine and needs the DJ's approval per version. Content hashes detect tampering. A signature field is reserved so DeckGlow-curated packs can be added later without a format change. |
| Python in creator modules | **Not allowed.** TouchDesigner Python can read files and use the network, and quarantine cannot contain it. Creator modules may use only pure-read parameter expressions (section 6). First-party modules are exempt. |
| Delivery | **One `.dgpack` file** — a zip with `pack.json`, its modules and palettes. DeckGlow verifies it, then unpacks it into `Packs/`. |

## 2. Layout

Inside the `.dgpack` (a standard zip):

```text
pack.json
modules/
  <folder>/          one directory per module, exactly the SCENE_MODULE_SPEC s4 package
    module.json
    module.tox
    thumbnail.png
    assets/          optional, per module
palettes/            optional
  <name>.json
```

Rules:

- `pack.json` is at the root; every other file is under `modules/` or
  `palettes/`
- each module directory is self-contained (SCENE_MODULE_SPEC s4); there are no
  pack-level shared assets
- no other top-level files or directories

Installed, the pack lives at `touchDesigner/Packs/<pack id>/` with the same
layout, plus an `installed.json` written by the installer.

## 3. `pack.json`

```json
{
  "schema": "deckglow.pack/1",
  "id": "com.example.neon",
  "displayName": "Neon Pack",
  "author": "Example Studio",
  "version": "1.0.0",
  "runtimeApi": ">=2.0.0 <3.0.0",
  "moduleContract": "deckglow.scene-module/1",
  "modules": [
    {"folder": "neon_grid", "id": "com.example.neon.grid", "version": "1.0.0"}
  ],
  "palettes": ["palettes/neon.json"],
  "files": {
    "modules/neon_grid/module.json": "sha256:…",
    "modules/neon_grid/module.tox": "sha256:…"
  },
  "signature": null,
  "description": "Optional.",
  "license": "Optional.",
  "homepage": "Optional."
}
```

| Field | Rule |
| --- | --- |
| `schema` | Must equal `deckglow.pack/1`. |
| `id` | Lowercase reverse-domain id, unique to the creator. `com.deckglow` and anything under it is reserved for first-party content. |
| `displayName`, `author` | 1–48 characters. |
| `version` | Semantic version of the pack release. |
| `runtimeApi` | Range the pack supports; must include the running runtime. |
| `moduleContract` | Must equal `deckglow.scene-module/1`. |
| `modules` | 1–64 entries. `folder` names a directory under `modules/`; `id` and `version` must equal that module's `module.json`. Every module id must start with the pack id plus a dot (`com.example.neon.grid`), so a pack cannot claim another creator's ids. |
| `palettes` | Optional list of paths under `palettes/`. |
| `files` | `sha256:<hex>` for **every** file in the pack except `pack.json`. No file may be missing or extra. |
| `signature` | Reserved; must be `null` in v1. A future curated tier will put a signature over the canonical `pack.json` here. |
| `description`, `license`, `homepage` | Optional strings. |

## 4. Palette files

A palette file is the runtime palette in JSON (SCENE_MODULE_SPEC s8.1):

```json
{
  "name": "neon",
  "background": [0.02, 0.0, 0.05],
  "primary":    [1.0, 0.1, 0.8],
  "secondary":  [0.1, 0.9, 1.0],
  "accent":     [1.0, 1.0, 1.0]
}
```

All four roles are required, each three numbers in `0..1`. Installed palettes
can be added to the runtime palette library; the runtime still chooses which
one is live.

## 5. Archive safety

The verifier rejects a `.dgpack` that:

- is not a valid zip, or has encrypted entries
- has an entry with an absolute path, a drive letter, a backslash, `..`, or a
  symlink
- has more than 2,000 entries, a file over 256 MB, or over 1 GB unpacked
- has a file not listed in `files`, or a listed file missing, or a hash
  mismatch

Installation unpacks only after every check passes, into a temporary
directory first, then moves it into `Packs/` in one step.

## 6. No Python in creator modules

A creator module must declare `capabilities.usesPython` as `false` (or omit
it), and the verifier inspects the `.tox` itself (expanded with TouchDesigner's
`toeexpand`). It fails a module that contains:

- **operators that run code**: any `script` operator, any DAT whose type
  includes `exec` (Execute, Parameter/OP/CHOP/DAT/Panel Execute), Timer CHOP
- **operators that reach outside the module**: network, device and file I/O
  (OSC, TCP/IP, UDP, Web, WebSocket, Serial, MQTT, MIDI, DMX/Art-Net, NDI,
  Spout/Syphon, File Out, Movie File Out, Folder DAT), Window COMP, Engine COMP,
  Replicator COMP
- **a `callbacks` parameter set**, on any operator
- **an `externaltox` parameter set** — no loading other `.tox` files
  (SCENE_MODULE_SPEC s13)
- **a parameter expression that is not a pure read**

A pure-read expression is a single Python expression made only of: numbers,
strings, arithmetic, comparisons, `and`/`or`/`not`, `x if c else y`, indexing,
calls, attribute reads, and the names `op`, `parent`, `me`, `math`,
`absTime`, `abs`, `min`, `max`, `round`, `int`, `float`, `bool`, `len`, `str`,
`pow`, `True`, `False`, `None`. It may not use an attribute starting with
`_`, or any of `run`, `save`, `destroy`, `create`, `copy`, `copyOPs`, `store`,
`unstore`, `storage`, `module`, `text`, `write`, `cook`, `pulse`, `connect`,
`disconnect`, `lock`, `appendRow`, `insertRow`, `replaceRow`, `deleteRow`,
`clear`, `setSize`. No lambdas, comprehensions, f-strings or assignments.

So `1 + op('../motion')['impact_fast'] * parent(2).par.Flash` is fine;
`op('../motion').module.Run()` and `__import__('os')` are not.

GLSL shaders in Text DATs are allowed — they run on the GPU and cannot touch
files or the network.

First-party modules (`touchDesigner/modules/`) are not held to this rule;
`orb_burst` and `clean_lockup` use Python and are trusted as DeckGlow code.

## 7. Verify, install, approve

```text
pack_tool.py build   <pack folder> -o <name>.dgpack   write hashes, verify, zip
pack_tool.py verify  <file.dgpack>                    every check, nothing written
pack_tool.py install <file.dgpack>                    verify, then unpack into Packs/
pack_tool.py remove  <pack id>                        delete Packs/<pack id>/
pack_tool.py list                                     installed packs
```

`verify` and `install` run, in order: archive safety (s5), `pack.json`
(s3), file hashes, then for every module the SCENE_MODULE_SPEC s15.1 static
checks plus the creator rules (namespacing, s6). Any failure stops the
install and nothing is written.

Installing does **not** approve anything. In TouchDesigner the scene library
discovers installed packs alongside first-party modules, each module goes
through quarantine (s15.2–15.4), and the DJ approves each module version
before `LoadApproved` will use it — exactly as for first-party modules.

Upgrading a pack (a higher `version` with the same `id`) replaces the
installed copy; modules whose version changed become `stale` and need
re-validating and re-approving. Installing the same or a lower version is
refused unless forced.

## 8. Versioning

`deckglow.pack/1` follows the same rules as the module contract
(SCENE_MODULE_SPEC s16): adding an optional `pack.json` field is a minor
change; anything that would make an existing valid pack invalid needs
`deckglow.pack/2`. A pack built for module contract `/1` keeps loading as long
as the runtime supports runtime API `2.x`.

## 9. Out of scope

Marketplace, pricing, licence enforcement and download hosting. The signature
field (s3) is the hook for a curated tier when it is wanted.
