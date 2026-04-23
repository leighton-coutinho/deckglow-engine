#pragma once

#include <cstdint>

struct FeatureFrame
{
    std::uint64_t frameId = 0;
    double timestampSeconds = 0.0;

    float masterLevel = 0.0f;
    float bass = 0.0f;
    float mid = 0.0f;
    float high = 0.0f;

    float onset = 0.0f;
    float kick = 0.0f;
    float snare = 0.0f;
    float hihat = 0.0f;

    float bpm = 0.0f;
    float bpmConfidence = 0.0f;
    float beatPhase = 0.0f;
    float barPhase = 0.0f;
    float phrasePhase = 0.0f;

    float beatPulse = 0.0f;
    float barPulse = 0.0f;
    float phrasePulse = 0.0f;

    float spectralCentroid = 0.0f;
    float spectralFlux = 0.0f;
    float stereoWidth = 0.0f;

    float breakdownLikelihood = 0.0f;
    float dropLikelihood = 0.0f;
    float silence = 0.0f;
};
