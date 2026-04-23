# Reactive Visual Engine v2 Architecture

## Purpose

This document turns the current prototype into a concrete v2 plan for this exact repo.

The goal is to evolve the project from:

- "3 audio values driving one TouchDesigner patch"

into:

- "a simple, DJ-friendly visual system with a stable feature bus, reusable TouchDesigner scenes, performer controls, and a phased implementation path"

This is written so we can implement block by block and stop after each block for review.

## Current Repo Snapshot

Current relevant files:

- `ReactiveVisualEngine.cpp`
- `Headers/audio/WasapiCapture.h`
- `SrcFiles/audio/WasapiCapture.cpp`
- `Headers/dsp/*.h`
- `Headers/net/UdpSender.h`
- `ReactiveVisualsTouchDesignerProto.toe`

Current runtime:

1. Capture Windows system audio through WASAPI loopback.
2. Downmix to mono.
3. Split into bass, mid, high.
4. Envelope -> gate -> normalize.
5. Send 3 values over UDP to TouchDesigner.

Current strengths:

- Minimal and understandable.
- Real-time loopback capture already works.
- The DSP path is simple enough to refactor safely.
- TouchDesigner is already in the loop, which is the right renderer for fast iteration.

Current limitations:

- Hardcoded audio device behavior.
- Hardcoded network target and packet format.
- No stable schema.
- No beat, bar, phrase, onset, or show control model.
- No config system.
- No scene framework in TouchDesigner.
- No DJ-facing control layer.

Known issue to fix immediately:

- `NoiseGate::initialize()` currently expects `threshold, reduction`, but `main()` passes `sampleRate` as the first argument. That should be corrected before we trust the current outputs.

## Product Direction

v2 should be positioned as:

- a lightweight reactive visuals engine for DJs
- fast to set up
- easy to brand
- musical enough to feel intentional
- simple enough that a non-VJ can still use it

The key design principle is:

- audio analysis should drive a stable feature bus
- TouchDesigner should consume that bus through a reusable scene contract
- scenes should expose a small performer-friendly macro surface

## v2 Goals

### Functional Goals

- Keep Windows/WASAPI as the first-class capture path.
- Standardize feature output as named channels instead of an ad hoc CSV string.
- Add timing intelligence: onset, BPM estimate, beat phase, bar phase, phrase phase.
- Support reusable scene templates in TouchDesigner.
- Support branding and performer control.
- Allow phased growth toward DMX, richer scene logic, and optional DJ software integration.

### Non-Goals For The First v2 Cut

- Full ML-based stems inside the C++ engine.
- Cross-platform audio capture.
- Native integration with every DJ platform.
- A polished GUI application before the signal path and scene contract are stable.

## Architecture Overview

### Runtime Data Flow

1. Audio Input
2. Sample Preprocessing
3. Analysis Modules
4. Feature Bus Assembly
5. Transport Layer
6. TouchDesigner Scene Runtime
7. Performer Control Layer

### High-Level Diagram

```text
WASAPI Loopback
  -> Audio Buffer + Downmix
  -> Analysis Pipeline
     -> band energy
     -> onset / transients
     -> tempo / beat clock
     -> stereo / spectral features
  -> Feature Frame
  -> Transport Router
     -> OSC (primary)
     -> Legacy UDP CSV (temporary compatibility)
  -> TouchDesigner Base Patch
     -> feature ingest
     -> normalization / debug views
     -> scene router
     -> scene template(s)
     -> branding overlay
     -> output
```

## Proposed Repo Structure

Keep the current Visual Studio project and directory style, but add clearer module boundaries.

```text
Headers/
  app/
    AppConfig.h
    RuntimeOptions.h
  audio/
    IAudioInput.h
    WasapiCapture.h
    AudioDeviceInfo.h
  dsp/
    AudioBuffer.h
    BiquadFilter.h
    EnvelopeFollower.h
    NoiseGate.h
    AdaptiveNormalizer.h
    RMS.h
    RingBuffer.h
  analysis/
    AnalysisContext.h
    FeatureFrame.h
    FeatureBus.h
    CalibrationState.h
    modules/
      BandEnergyAnalyzer.h
      OnsetDetector.h
      TempoEstimator.h
      BeatClock.h
      StereoAnalyzer.h
      SpectralAnalyzer.h
      PhraseTracker.h
  net/
    OscSender.h
    LegacyUdpSender.h
    TransportRouter.h
  control/
    ControlState.h
    MidiMap.h
  util/
    TimeUtils.h
    Logger.h

SrcFiles/
  app/
    AppConfig.cpp
    RuntimeOptions.cpp
  audio/
    WasapiCapture.cpp
  analysis/
    AnalysisPipeline.cpp
    modules/
      BandEnergyAnalyzer.cpp
      OnsetDetector.cpp
      TempoEstimator.cpp
      BeatClock.cpp
      StereoAnalyzer.cpp
      SpectralAnalyzer.cpp
      PhraseTracker.cpp
  net/
    OscSender.cpp
    TransportRouter.cpp
  control/
    ControlState.cpp
  util/
    Logger.cpp

docs/
  V2_ARCHITECTURE.md
```

## Core v2 Modules

### 1. Audio Input Layer

Responsibility:

- Own capture device selection and raw block delivery.

First implementation:

- Keep `WasapiCapture` as the only concrete input.
- Add an interface so the rest of the pipeline is not tightly coupled to WASAPI.

Suggested interface:

```cpp
class IAudioInput {
public:
    using Callback = std::function<void(const float* interleaved,
                                        size_t frames,
                                        int channels,
                                        int sampleRate)>;
    virtual ~IAudioInput() = default;
    virtual bool initializeDefault() = 0;
    virtual void setCallback(Callback cb) = 0;
    virtual void start() = 0;
    virtual void stop() = 0;
};
```

Why this matters:

- It keeps the door open for ASIO, microphone input, virtual cable input, or deck feed input later.

### 2. Preprocessing Layer

Responsibility:

- Convert raw capture data into analysis-friendly buffers.

Includes:

- downmix to mono
- preserve stereo channels for width analysis
- optional gain trim
- optional resample later if needed

Output:

- `MonoBlock`
- `StereoBlock`
- timestamps

### 3. Analysis Pipeline

Responsibility:

- Convert audio blocks into musically useful features.

This should be a composed pipeline, not logic packed into `main()`.

Suggested module split:

- `BandEnergyAnalyzer`
- `OnsetDetector`
- `TempoEstimator`
- `BeatClock`
- `StereoAnalyzer`
- `SpectralAnalyzer`
- `PhraseTracker`

### 4. Feature Bus

Responsibility:

- Hold the full state for one analysis tick in a single struct.

This is the key contract between engine and renderer.

Suggested shape:

```cpp
struct FeatureFrame {
    uint64_t frameId;
    double timestampSeconds;

    float masterLevel;
    float bass;
    float mid;
    float high;

    float onset;
    float kick;
    float snare;
    float hihat;

    float bpm;
    float bpmConfidence;
    float beatPhase;
    float barPhase;
    float phrasePhase;

    float beatPulse;
    float barPulse;
    float phrasePulse;

    float spectralCentroid;
    float spectralFlux;
    float stereoWidth;

    float breakdownLikelihood;
    float dropLikelihood;
    float silence;
};
```

### 5. Transport Layer

Responsibility:

- Publish the feature bus in stable formats.

Transport priority:

1. OSC over UDP
2. Temporary legacy CSV UDP output for backwards compatibility

Why OSC should become the primary transport:

- Native fit for TouchDesigner.
- Human-readable addresses.
- Easier to version.
- Easier to debug and extend than a custom CSV string.

### 6. TouchDesigner Runtime Contract

Responsibility:

- Consume the engine feature bus in a standard way.
- Normalize scene inputs.
- Expose consistent macros across all scenes.

The `.toe` file should stop being a one-off patch and become a reusable runtime shell.

### 7. Performer Control Layer

Responsibility:

- Give DJs just enough control without turning them into full VJs.

Controls should be macro-level:

- scene next / previous
- intensity
- motion amount
- strobe accent
- blackout
- logo on/off
- palette shift
- FX amount

This can initially live in TouchDesigner via MIDI/OSC mapping and later move into the engine or a companion control app.

## Analysis Module Details

### BandEnergyAnalyzer

Purpose:

- Preserve the current low/mid/high reactivity.

v2 output:

- `masterLevel`
- `bass`
- `mid`
- `high`

Implementation note:

- Keep the existing biquad split and envelope approach first.
- Make crossover points configurable in config later.

### OnsetDetector

Purpose:

- Detect momentary energy changes that feel like hits, accents, and cuts.

v2 output:

- `onset`
- `kick`
- `snare`
- `hihat`

Implementation note:

- Do not overpromise drum separation at first.
- Start with heuristic proxies:
  - kick from low-band transient
  - snare from mid-band transient
  - hihat from high-band transient

### TempoEstimator

Purpose:

- Estimate BPM and confidence from onset history.

v2 output:

- `bpm`
- `bpmConfidence`

Implementation note:

- Start with a bounded range tuned for DJ music, for example 70-180 BPM with octave correction.
- Good enough and stable beats matter more than academic BPM precision.

### BeatClock

Purpose:

- Turn detected tempo into phase and pulse signals scenes can use directly.

v2 output:

- `beatPhase`
- `barPhase`
- `phrasePhase`
- `beatPulse`
- `barPulse`
- `phrasePulse`

Implementation note:

- Phrase should default to 32 beats for dance music unless a profile says otherwise.

### StereoAnalyzer

Purpose:

- Capture width and movement information.

v2 output:

- `stereoWidth`

Use cases:

- widen camera movement on wide chorus sections
- compress visuals during breakdowns

### SpectralAnalyzer

Purpose:

- Capture timbral brightness and change rate.

v2 output:

- `spectralCentroid`
- `spectralFlux`

Use cases:

- color temperature
- particle density
- texture sharpness

### PhraseTracker

Purpose:

- Give the system simple structural awareness, even if it is only heuristic at first.

v2 output:

- `breakdownLikelihood`
- `dropLikelihood`
- `silence`

Implementation note:

- Start heuristic.
- Use combinations of energy drop, onset density, bass return, and phrase boundaries.

## Feature Schema

## Required v2 Core Features

These should exist before we call the engine "v2 ready":

| Feature | Type | Range | Notes |
| --- | --- | --- | --- |
| `masterLevel` | float | 0..1 | normalized global energy |
| `bass` | float | 0..1 | normalized low-band energy |
| `mid` | float | 0..1 | normalized mid-band energy |
| `high` | float | 0..1 | normalized high-band energy |
| `onset` | float | 0..1 | general transient strength |
| `bpm` | float | positive | estimated tempo |
| `bpmConfidence` | float | 0..1 | trust level of tempo |
| `beatPhase` | float | 0..1 | normalized beat cycle |
| `barPhase` | float | 0..1 | normalized 4-beat cycle |
| `phrasePhase` | float | 0..1 | normalized phrase cycle |
| `beatPulse` | float | 0 or 1 / short pulse | one-shot style trigger |
| `barPulse` | float | 0 or 1 / short pulse | one-shot style trigger |
| `spectralCentroid` | float | 0..1 | normalized brightness |
| `stereoWidth` | float | 0..1 | width estimate |

## Extended v2 Features

These can land after the core feature contract is stable:

| Feature | Type | Range | Notes |
| --- | --- | --- | --- |
| `kick` | float | 0..1 | low transient proxy |
| `snare` | float | 0..1 | mid transient proxy |
| `hihat` | float | 0..1 | high transient proxy |
| `phrasePulse` | float | 0 or 1 / short pulse | phrase boundary pulse |
| `spectralFlux` | float | 0..1 | change rate |
| `breakdownLikelihood` | float | 0..1 | heuristic |
| `dropLikelihood` | float | 0..1 | heuristic |
| `silence` | float | 0..1 | silence / low-activity amount |

## TouchDesigner Contract

OSC should be the canonical engine-to-TouchDesigner contract.

### OSC Namespace

Use a stable versioned prefix:

- `/rve/v2/...`

Suggested addresses:

```text
/rve/v2/meta/frame_id
/rve/v2/meta/timestamp

/rve/v2/audio/master_level
/rve/v2/audio/bass
/rve/v2/audio/mid
/rve/v2/audio/high
/rve/v2/audio/onset
/rve/v2/audio/kick
/rve/v2/audio/snare
/rve/v2/audio/hihat
/rve/v2/audio/stereo_width
/rve/v2/audio/spectral_centroid
/rve/v2/audio/spectral_flux

/rve/v2/tempo/bpm
/rve/v2/tempo/confidence
/rve/v2/tempo/beat_phase
/rve/v2/tempo/bar_phase
/rve/v2/tempo/phrase_phase
/rve/v2/tempo/beat_pulse
/rve/v2/tempo/bar_pulse
/rve/v2/tempo/phrase_pulse

/rve/v2/structure/breakdown_likelihood
/rve/v2/structure/drop_likelihood
/rve/v2/structure/silence
```

### Transport Rules

- Send one OSC bundle per analysis tick.
- Default analysis/output rate should be stable and practical, for example 60 Hz or 100 Hz.
- All normalized visual-driving values should be `0..1`.
- BPM should be absolute.
- Pulse values should be edge-friendly for TouchDesigner logic operators.

### Temporary Compatibility Layer

Until the `.toe` file is migrated:

- keep a legacy sender that can still emit `bassMidHigh,...`
- make this optional and clearly mark it deprecated

## TouchDesigner Base Patch Contract

The TouchDesigner project should be reorganized into a base runtime with scene modules.

### Recommended Top-Level Components

```text
/engine_in
/engine_debug
/feature_filter
/feature_history
/beat_master
/scene_router
/scenes
/brand_overlay
/performer_controls
/output_main
```

### Responsibilities

`/engine_in`

- receives OSC from the engine
- maps addresses to stable channels

`/engine_debug`

- shows raw values, BPM confidence, pulses, device status

`/feature_filter`

- smooths, clamps, remaps, and calibrates incoming features for visual use

`/feature_history`

- holds trails / recent values for procedural effects

`/beat_master`

- converts engine beat information into a local TouchDesigner timing reference if needed

`/scene_router`

- routes a shared feature bus and performer macros to the active scene

`/scenes`

- contains reusable scene COMPs

`/brand_overlay`

- logo
- artist name
- event title
- social handle
- optional media slot

`/performer_controls`

- MIDI/OSC control ingest
- scene switching
- intensity controls

`/output_main`

- final compositing and output path

## Scene Contract

Every scene should consume the same feature bus and expose the same macro surface.

### Required Scene Inputs

- `masterLevel`
- `bass`
- `mid`
- `high`
- `onset`
- `bpm`
- `beatPhase`
- `barPhase`
- `phrasePhase`
- `stereoWidth`

### Required Scene Macros

- `intensity`
- `motion`
- `colorShift`
- `fxMix`
- `strobeAmount`
- `logoOpacity`

### Scene Behavior Rules

- Scenes should work with no manual DJ interaction.
- Scenes should look reasonable with only `bass/mid/high/onset/beatPhase`.
- Scenes should react differently to beat pulse, bar pulse, and phrase phase.
- Scene transitions should happen on beat or phrase boundaries whenever possible.

## Configuration

v2 should introduce a config file so the engine is not compiled around one setup.

Suggested path:

- `config/rve.json`

Suggested config sections:

```json
{
  "audio": {
    "mode": "default_loopback",
    "deviceId": "",
    "bufferMs": 50
  },
  "analysis": {
    "outputRateHz": 60,
    "bands": {
      "bassHz": 200,
      "midHz": 2500
    },
    "phraseLengthBeats": 32
  },
  "transport": {
    "oscEnabled": true,
    "oscHost": "127.0.0.1",
    "oscPort": 9000,
    "legacyUdpEnabled": false,
    "legacyUdpPort": 9001
  },
  "show": {
    "profile": "club_default",
    "brandName": "",
    "logoPath": "",
    "primaryColor": "#ffffff"
  }
}
```

## Recommended Show Profiles

Profiles let the same engine feel better for different DJ contexts.

Initial profiles:

- `club_default`
- `house_melodic`
- `techno_peak`
- `open_format`
- `downtempo`

Profiles can control:

- band sensitivity
- BPM limits
- phrase length assumptions
- scene transition aggressiveness
- pulse hold times

## Phased Implementation Plan

Each block should end in a checkpoint so you can correct direction before we continue.

### Block 0 - Stabilize The Current Prototype

Goal:

- make the existing prototype trustworthy before refactoring

Tasks:

- fix the `NoiseGate` initialization bug
- move hardcoded IP/port into constants or config stubs
- clean up console logging
- keep current `bass/mid/high` behavior working

Deliverable:

- current app still runs
- values are more believable
- no behavior hidden in `main()` that we cannot explain

Checkpoint question:

- do the current low/mid/high values feel musically useful enough to preserve as the base layer?

### Block 1 - Introduce The Feature Bus

Goal:

- remove ad hoc processing from `main()` and create a stable internal contract

Tasks:

- add `FeatureFrame`
- add `AnalysisContext`
- add `AnalysisPipeline`
- move band energy logic into a dedicated analyzer
- keep output equivalent to current behavior plus metadata

Deliverable:

- `main()` becomes orchestration only
- the app can generate a complete `FeatureFrame` each tick

Checkpoint question:

- is the field list correct, or do we want to rename any features before the TouchDesigner contract is frozen?

### Block 2 - Replace Custom UDP With OSC

Goal:

- standardize engine output

Tasks:

- implement `OscSender`
- implement `TransportRouter`
- send `/rve/v2/...` addresses
- optionally keep legacy CSV sender behind a compatibility flag

Deliverable:

- TouchDesigner can ingest named channels without custom parsing logic

Checkpoint question:

- do we want OSC to be the only renderer contract, or do you want a second contract for other consumers as well?

### Block 3 - Add Timing Intelligence

Goal:

- move from generic audio reactivity to DJ-relevant musical timing

Tasks:

- implement onset detection
- implement BPM estimation
- implement beat and bar phase
- emit `beatPulse`, `barPulse`, and `phrasePhase`

Deliverable:

- TouchDesigner scenes can sync visual events to beat and phrase, not just raw energy

Checkpoint question:

- do we want phrase logic tuned for 16-beat or 32-beat structures by default?

### Block 4 - Build The TouchDesigner Base Patch

Goal:

- replace the one-off prototype patch with a reusable runtime shell

Tasks:

- create `/engine_in`, `/feature_filter`, `/scene_router`, `/brand_overlay`, `/output_main`
- wire the new OSC contract
- add debug panels for engine values

Deliverable:

- one `.toe` file that can host multiple scenes against one stable feature bus

Checkpoint question:

- do you want the base patch optimized for livestream visuals, projector visuals, or LED-wall style visuals first?

### Block 5 - Add Starter Scene System

Goal:

- give DJs more than one reactive look without editing internals

Tasks:

- create 3-5 scene templates
- define required macros
- add simple scene switching
- add phrase-safe transitions

Suggested first scene pack:

- logo pulse
- abstract particles
- geometric tunnel
- waveform bloom
- high-energy strobe scene

Deliverable:

- DJs can switch among distinct looks without rewiring the patch

Checkpoint question:

- which visual direction should become the primary brand: clean/minimal, club/techno, glossy/open-format, or something else?

### Block 6 - Add Performer Controls

Goal:

- make the system playable during a set

Tasks:

- add MIDI learn or fixed MIDI mapping
- add scene next/previous
- add intensity/motion/fx macros
- add blackout and logo toggles

Deliverable:

- a DJ can operate the visuals from a controller or simple control surface

Checkpoint question:

- do you want performer control to live mainly in TouchDesigner, or do you want the C++ side to eventually own mapping/state too?

### Block 7 - Add Show Profiles And Branding

Goal:

- make setup fast for different DJs and event types

Tasks:

- add config-driven profiles
- add logo/media/brand settings
- add profile presets

Deliverable:

- a DJ can pick a profile and get a coherent starting point without editing code

Checkpoint question:

- should branding be lightweight and tasteful, or intentionally prominent for promoter/event use?

### Block 8 - Add Structural Autopilot

Goal:

- make visuals stay musical during unscripted sets

Tasks:

- add breakdown/drop heuristics
- trigger scene changes on phrase boundaries
- build fallback "autoloop" behavior

Deliverable:

- the system still feels intentional even when nobody is manually cueing visuals

Checkpoint question:

- should autopilot be subtle and safe, or more aggressive and showy?

### Block 9 - Package For Real DJ Use

Goal:

- reduce friction for deployment

Tasks:

- simplify startup
- define installation steps
- document TouchDesigner or TouchPlayer packaging path
- add logging and diagnostics

Deliverable:

- another machine can run the system with minimal setup

Checkpoint question:

- is the intended user installing this on their own performance laptop, or are you aiming for event/venue deployment too?

## Acceptance Criteria For v2

We should consider v2 successful when:

- the engine publishes a stable named feature schema
- TouchDesigner consumes the schema without custom one-off parsing
- at least 3 distinct scenes share one common contract
- the system reacts to beat and phrase, not only loudness
- a DJ can control scene flow and intensity without editing the patch
- branding can be changed without recompiling C++

## Recommended First Build Sequence

If we start implementation immediately, the safest order is:

1. Block 0
2. Block 1
3. Block 2
4. Block 3

That gets us from prototype to a credible feature engine before we spend time redesigning the TouchDesigner side.

## Assumptions To Confirm

These are the assumptions this plan currently makes:

- Windows-first is acceptable.
- TouchDesigner remains the renderer for v2.
- OSC becomes the primary engine-to-renderer transport.
- We want DJ usability more than deep VJ flexibility in the first product pass.
- We should optimize first for live club visuals rather than broadcast motion graphics.

If any of those are wrong, we should adjust before Block 1 begins.
