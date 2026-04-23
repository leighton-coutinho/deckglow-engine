#pragma once

#include <algorithm>
#include <cmath>

#include "Headers/analysis/AnalysisContext.h"
#include "Headers/analysis/FeatureFrame.h"

class OnsetDetector
{
public:
    void process(FeatureFrame& frame, const AnalysisContext& context)
    {
        const float deltaTime = static_cast<float>(std::max(context.blockDurationSeconds, 0.0));

        const float bassRise = std::max(0.0f, frame.bass - m_previousBass);
        const float midRise = std::max(0.0f, frame.mid - m_previousMid);
        const float highRise = std::max(0.0f, frame.high - m_previousHigh);
        const float masterRise = std::max(0.0f, frame.masterLevel - m_previousMasterLevel);

        frame.kick = normalizeTransient(bassRise, m_kickPeak, deltaTime);
        frame.snare = normalizeTransient(midRise, m_snarePeak, deltaTime);
        frame.hihat = normalizeTransient(highRise, m_hihatPeak, deltaTime);

        const float compositeRise = std::max(
            masterRise,
            bassRise * 0.65f + midRise * 0.25f + highRise * 0.10f);

        const float onsetBase = normalizeTransient(compositeRise, m_onsetPeak, deltaTime);
        frame.onset = std::clamp(
            onsetBase * 0.55f + frame.kick * 0.25f + frame.snare * 0.15f + frame.hihat * 0.05f,
            0.0f,
            1.0f);

        m_previousMasterLevel = frame.masterLevel;
        m_previousBass = frame.bass;
        m_previousMid = frame.mid;
        m_previousHigh = frame.high;
    }

private:
    static float decayPeak(float peak, float deltaTime)
    {
        const float releasePerSecond = 0.35f;
        return peak * std::pow(releasePerSecond, deltaTime);
    }

    static float normalizeTransient(float value, float& peak, float deltaTime)
    {
        peak = std::max(value, decayPeak(peak, deltaTime));
        const float safePeak = std::max(peak, 0.01f);
        return std::clamp(value / safePeak, 0.0f, 1.0f);
    }

private:
    float m_previousMasterLevel = 0.0f;
    float m_previousBass = 0.0f;
    float m_previousMid = 0.0f;
    float m_previousHigh = 0.0f;

    float m_onsetPeak = 0.05f;
    float m_kickPeak = 0.05f;
    float m_snarePeak = 0.05f;
    float m_hihatPeak = 0.05f;
};
