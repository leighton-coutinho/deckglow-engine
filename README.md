# DeckGlow

Reactive visuals for DJs. DeckGlow listens to whatever your computer is
playing, finds the energy, hits and beat, and drives projector visuals in
TouchDesigner - with your name on screen, looks you can fade between on the
beat, a MIDI controller, and creator packs you can add.

```
 your music ──> audio engine ──OSC──> TouchDesigner runtime ──> projector
 (any player)   (WASAPI, C++)          (scene modules, looks,
                                        safety stage)
                                            ▲
                          desktop app ──────┘  deckglow.control/1
                          (switches, looks, MIDI, packs, setup)
```

## Install (Windows)

1. **Install TouchDesigner** from [derivative.ca](https://derivative.ca/download).
   DeckGlow draws its visuals in TouchDesigner, which has its own licence:
   the free Non-Commercial licence is for non-commercial use and limits the
   output to 1280×720; paid shows need a Commercial licence.
2. **Download `DeckGlow-Setup-<version>.exe`** from this repository's
   [Releases](../../releases) and run it. It installs for your user only (no
   administrator rights). The installer is not code-signed yet, so Windows
   SmartScreen may warn: choose *More info → Run anyway*.
3. **Open DeckGlow.** Setup opens by itself and walks you through it:
   - it finds TouchDesigner,
   - installs the DeckGlow runtime to `Documents\DeckGlow` (your packs,
     approvals and settings live there),
   - opens DeckGlow's project in TouchDesigner,
   - starts the audio engine - play some music and the meters move,
   - sets your name, and puts the output on your projector (optional).

Setup is always one click away (the header's **Setup** button). Updating
DeckGlow later keeps your packs, approvals and show; Setup offers the
runtime update and puts your show back afterwards.

## Using it

- **Layers** - Scene (the moving background), Hits (effects on every hit),
  Name, Finish. Switch each on or off, pick its module, set its intensity.
- **Looks** - 16 pads: click to fade to a saved look on the next beat or bar,
  shift-click to cut. A look is the Scene and Hits layers with their
  settings, plus the colours.
- **Controller** - MIDI learn: click Learn, touch a pad or knob.
- **Library** - install creator packs (`.dgpack`); each new module is
  validated and must be approved by you before it can be used.
- **Output safety** - a flash limiter for photosensitive viewers (on by
  default), a brightness ceiling, Blackout (`B`).

## Develop

| Part | Where | Docs |
| --- | --- | --- |
| Audio engine (C++20, WASAPI → OSC) | `Headers/`, `SrcFiles/`, `ReactiveVisualEngine.vcxproj` | [docs/V2_ARCHITECTURE.md](docs/V2_ARCHITECTURE.md) |
| TouchDesigner runtime | `touchDesigner/` (project, modules, builders, tools) | [docs/HYBRID_RUNTIME_ARCHITECTURE.md](docs/HYBRID_RUNTIME_ARCHITECTURE.md), [docs/SCENE_MODULE_SPEC.md](docs/SCENE_MODULE_SPEC.md) |
| Desktop app (Electron + TypeScript) | `app/` | [app/README.md](app/README.md), [docs/FRONTEND_MESSAGE_CONTRACT.md](docs/FRONTEND_MESSAGE_CONTRACT.md) |
| Creator packs | `touchDesigner/tools/pack_tool.py` | [docs/PACK_FORMAT_SPEC.md](docs/PACK_FORMAT_SPEC.md) |

[CLAUDE.md](CLAUDE.md) holds the working notes: what is built, what was
verified, and the TouchDesigner pitfalls that cost time.

Build the engine (Visual Studio 2022 or newer):

```powershell
& "C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe" ReactiveVisualEngine.vcxproj -p:Configuration=Release -p:Platform=x64
```

Run the app from the checkout (it uses the repository's `touchDesigner/`
folder directly; open `touchDesigner/engine_input_block1.toe` in
TouchDesigner, or let Setup open it):

```powershell
cd app
npm install
npm start
```

Checks: `npm test` (in `app/`), `npm run smoke` with TouchDesigner running,
and `python touchDesigner/tools/check_contract.py`.

## Release

`app/` builds the installer: `npm run dist` stages the runtime and the
Release engine into `app/build/` and writes `app/release/DeckGlow-Setup-<version>.exe`.
GitHub Actions does the same: [CI](.github/workflows/ci.yml) builds the
engine and runs the tests on every push; pushing a tag `v<version>` matching
`app/package.json` runs [Release](.github/workflows/release.yml), which
attaches the installer to a **draft** release for review.

Before staging a release, open the project in TouchDesigner and save it, so
the shipped `engine_input_block1.toe` has the current runtime built in.
