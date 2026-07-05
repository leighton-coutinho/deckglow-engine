#pragma once

#include <algorithm>
#include <cmath>

#include "Headers/analysis/AnalysisContext.h"
#include "Headers/analysis/FeatureFrame.h"

class MacroComposer
{
public:
    void process(FeatureFrame& frame, const AnalysisContext& context)
    {
        const float deltaTime = static_cast<float>(std::max(context.blockDurationSeconds, 0.0));

        frame.macroDrive = composeDrive(frame, deltaTime);
        frame.macroHit = composeHit(frame, deltaTime);
        frame.macroSync = composeSync(frame, deltaTime);
        frame.macroDensity = composeDensity(frame, deltaTime);
        frame.macroTone = composeTone(frame, deltaTime);
    }

private:
    float composeDrive(const FeatureFrame& frame, float deltaTime)
    {
        // Drive is the continuous "body" of the scene, so it should favor
        // stable low-end energy over short-lived transients.
        const float target = std::clamp(
            frame.bass * 0.72f +
            frame.mid * 0.18f +
            frame.masterLevel * 0.10f,
            0.0f,
            1.0f);

        m_drive = smoothTowards(m_drive, target, deltaTime, 5.5f, 2.4f);
        return std::clamp(m_drive, 0.0f, 1.0f);
    }

    float composeHit(const FeatureFrame& frame, float deltaTime)
    {
        // Hit is for flashes and punches, so it should prioritize explicit
        // transients and kick impact, with only a small snare contribution.
        const float silenceAttenuation = 1.0f - frame.silence * 0.35f;
        const float target = std::clamp(
            frame.onset * 0.55f +
            frame.kick * 0.35f +
            frame.snare * 0.10f,
            0.0f,
            1.0f) * silenceAttenuation;

        m_hit = decayEnvelope(m_hit, deltaTime, 0.18f);
        m_hit = std::max(m_hit, target);

        return std::clamp(m_hit, 0.0f, 1.0f);
    }

    float composeSync(const FeatureFrame& frame, float deltaTime)
    {
        // Sync is the rhythmic motion lane. It is mostly a smooth beat-cycle
        // signal, with a light accent envelope so it still "reads" on downbeats.
        const float beatCycle = 0.5f - 0.5f * std::cos(frame.beatPhase * kTwoPi);
        const float accentTrigger = std::clamp(frame.beatPulse * 0.70f + frame.barPulse * 0.30f, 0.0f, 1.0f);

        m_syncAccent = decayEnvelope(m_syncAccent, deltaTime, 0.24f);
        m_syncAccent = std::max(m_syncAccent, accentTrigger);

        const float target = std::clamp(
            beatCycle * 0.85f +
            m_syncAccent * 0.15f,
            0.0f,
            1.0f);

        m_sync = smoothTowards(m_sync, target, deltaTime, 10.0f, 10.0f);
        return std::clamp(m_sync, 0.0f, 1.0f);
    }

    float composeDensity(const FeatureFrame& frame, float deltaTime)
    {
        // Density controls how busy the scene feels, so it should respond to
        // textural change and upper-band activity rather than low-end body.
        const float silenceAttenuation = 1.0f - frame.silence * 0.45f;
        const float target = std::clamp(
            frame.spectralFlux * 0.55f +
            frame.high * 0.25f +
            frame.mid * 0.20f,
            0.0f,
            1.0f) * silenceAttenuation;

        m_density = smoothTowards(m_density, target, deltaTime, 6.5f, 3.0f);
        return std::clamp(m_density, 0.0f, 1.0f);
    }

    float composeTone(const FeatureFrame& frame, float deltaTime)
    {
        // Tone should be a slow timbral mood signal that can steer palette or
        // softness without making the image flicker.
        m_tone = smoothTowards(m_tone, frame.spectralCentroid, deltaTime, 1.8f, 1.8f);
        return std::clamp(m_tone, 0.0f, 1.0f);
    }

    static float smoothTowards(float current, float target, float deltaTime, float riseRate, float fallRate)
    {
        const float rate = target > current ? riseRate : fallRate;
        const float blend = 1.0f - std::exp(-std::max(rate, 0.0f) * std::max(deltaTime, 0.0f));
        return current + (target - current) * blend;
    }

    static float decayEnvelope(float current, float deltaTime, float releaseSeconds)
    {
        if (releaseSeconds <= 0.0f)
        {
            return 0.0f;
        }

        return current * std::exp(-std::max(deltaTime, 0.0f) / releaseSeconds);
    }

private:
    static constexpr float kTwoPi = 6.28318530718f;

    float m_drive = 0.0f;
    float m_hit = 0.0f;
    float m_sync = 0.0f;
    float m_syncAccent = 0.0f;
    float m_density = 0.0f;
    float m_tone = 0.0f;
};
