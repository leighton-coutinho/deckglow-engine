#pragma once

#include <algorithm>
#include <cmath>
#include <vector>

#include "Headers/analysis/AnalysisContext.h"
#include "Headers/analysis/FeatureFrame.h"
#include "Headers/dsp/BandSplitter.h"
#include "Headers/dsp/EnvelopeFollower.h"
#include "Headers/dsp/RMS.h"

class SpectralDynamicsAnalyzer
{
public:
    void process(const std::vector<float>& mono, FeatureFrame& frame, const AnalysisContext& context)
    {
        if (mono.empty() || context.sampleRate <= 0)
        {
            return;
        }

        if (!m_initialized || m_sampleRate != static_cast<float>(context.sampleRate))
        {
            initialize(static_cast<float>(context.sampleRate));
        }

        double bassAccum = 0.0;
        double midAccum = 0.0;
        double highAccum = 0.0;
        double fluxAccum = 0.0;

        for (float sample : mono)
        {
            m_splitter.process(sample);

            const float bassEnvelope = m_bassEnvelope.process(m_splitter.bass);
            const float midEnvelope = m_midEnvelope.process(m_splitter.mid);
            const float highEnvelope = m_highEnvelope.process(m_splitter.high);

            bassAccum += bassEnvelope;
            midAccum += midEnvelope;
            highAccum += highEnvelope;

            const float bassRise = std::max(0.0f, bassEnvelope - m_previousBassEnvelope);
            const float midRise = std::max(0.0f, midEnvelope - m_previousMidEnvelope);
            const float highRise = std::max(0.0f, highEnvelope - m_previousHighEnvelope);

            fluxAccum += bassRise * 0.40 + midRise * 0.35 + highRise * 0.25;

            m_previousBassEnvelope = bassEnvelope;
            m_previousMidEnvelope = midEnvelope;
            m_previousHighEnvelope = highEnvelope;
        }

        const float inverseSampleCount = 1.0f / static_cast<float>(mono.size());
        const float bassAverage = static_cast<float>(bassAccum) * inverseSampleCount;
        const float midAverage = static_cast<float>(midAccum) * inverseSampleCount;
        const float highAverage = static_cast<float>(highAccum) * inverseSampleCount;

        const float rawFlux = static_cast<float>(fluxAccum) * inverseSampleCount;
        const float deltaTime = static_cast<float>(std::max(context.blockDurationSeconds, 0.0));
        const float fluxTarget = normalizeTransient(rawFlux, m_fluxPeak, deltaTime, 0.28f, 0.0005f);
        m_smoothedFlux = smoothTowards(m_smoothedFlux, fluxTarget, deltaTime, 10.0f, 8.0f);

        frame.spectralCentroid = computeCentroid(bassAverage, midAverage, highAverage, deltaTime);
        frame.spectralFlux = std::clamp(m_smoothedFlux, 0.0f, 1.0f);
        frame.silence = computeSilence(mono, frame.masterLevel, deltaTime);
    }

private:
    void initialize(float sampleRate)
    {
        m_splitter.initialize(sampleRate);

        m_bassEnvelope.initialize(sampleRate, 4.0f, 90.0f);
        m_midEnvelope.initialize(sampleRate, 3.0f, 80.0f);
        m_highEnvelope.initialize(sampleRate, 2.0f, 60.0f);

        m_sampleRate = sampleRate;
        m_initialized = true;

        m_previousBassEnvelope = 0.0f;
        m_previousMidEnvelope = 0.0f;
        m_previousHighEnvelope = 0.0f;
        m_fluxPeak = 0.01f;
        m_rmsPeak = 0.01f;
        m_smoothedFlux = 0.0f;
        m_smoothedCentroid = 0.0f;
        m_smoothedSilence = 1.0f;
    }

    float computeCentroid(float bassAverage, float midAverage, float highAverage, float deltaTime)
    {
        const float totalEnergy = bassAverage + midAverage + highAverage;
        if (totalEnergy <= 0.00001f)
        {
            m_smoothedCentroid = smoothTowards(m_smoothedCentroid, 0.0f, deltaTime, 2.0f, 6.0f);
            return m_smoothedCentroid;
        }

        const float weightedHz =
            (bassAverage * kBassCenterHz +
                midAverage * kMidCenterHz +
                highAverage * kHighCenterHz) / totalEnergy;

        const float target = normalizeLogRange(weightedHz, 80.0f, 8000.0f);
        m_smoothedCentroid = smoothTowards(m_smoothedCentroid, target, deltaTime, 7.0f, 7.0f);
        return std::clamp(m_smoothedCentroid, 0.0f, 1.0f);
    }

    float computeSilence(const std::vector<float>& mono, float masterLevel, float deltaTime)
    {
        const float rms = RMS::compute(mono.data(), mono.size());
        m_rmsPeak = std::max(rms, decayPeak(m_rmsPeak, deltaTime, 0.60f));

        const float relativeLevel = std::clamp(rms / std::max(m_rmsPeak, 0.002f), 0.0f, 1.0f);
        const float effectiveLevel = std::max(relativeLevel, masterLevel * 0.55f);

        const float absoluteQuiet = 1.0f - smoothstep(0.0035f, 0.018f, rms);
        const float relativeQuiet = 1.0f - smoothstep(0.08f, 0.22f, effectiveLevel);
        const float target = std::clamp(absoluteQuiet * 0.70f + relativeQuiet * 0.30f, 0.0f, 1.0f);

        m_smoothedSilence = smoothTowards(m_smoothedSilence, target, deltaTime, 2.0f, 9.0f);
        return std::clamp(m_smoothedSilence, 0.0f, 1.0f);
    }

    static float normalizeTransient(
        float value,
        float& peak,
        float deltaTime,
        float releasePerSecond,
        float minimumPeak)
    {
        peak = std::max(value, decayPeak(peak, deltaTime, releasePerSecond));
        return std::clamp(value / std::max(peak, minimumPeak), 0.0f, 1.0f);
    }

    static float normalizeLogRange(float value, float minValue, float maxValue)
    {
        const float clampedValue = std::clamp(value, minValue, maxValue);
        const float minLog = std::log(minValue);
        const float maxLog = std::log(maxValue);
        const float valueLog = std::log(clampedValue);
        return std::clamp((valueLog - minLog) / std::max(maxLog - minLog, 0.0001f), 0.0f, 1.0f);
    }

    static float decayPeak(float peak, float deltaTime, float releasePerSecond)
    {
        return peak * std::pow(std::clamp(releasePerSecond, 0.001f, 0.999f), deltaTime);
    }

    static float smoothTowards(float current, float target, float deltaTime, float riseRate, float fallRate)
    {
        const float rate = target > current ? riseRate : fallRate;
        const float blend = 1.0f - std::exp(-std::max(rate, 0.0f) * std::max(deltaTime, 0.0f));
        return current + (target - current) * blend;
    }

    static float smoothstep(float edge0, float edge1, float value)
    {
        const float t = std::clamp((value - edge0) / std::max(edge1 - edge0, 0.0001f), 0.0f, 1.0f);
        return t * t * (3.0f - 2.0f * t);
    }

private:
    static constexpr float kBassCenterHz = 110.0f;
    static constexpr float kMidCenterHz = 1200.0f;
    static constexpr float kHighCenterHz = 6500.0f;

    float m_sampleRate = 0.0f;
    bool m_initialized = false;

    BandSplitter m_splitter;
    EnvelopeFollower m_bassEnvelope;
    EnvelopeFollower m_midEnvelope;
    EnvelopeFollower m_highEnvelope;

    float m_previousBassEnvelope = 0.0f;
    float m_previousMidEnvelope = 0.0f;
    float m_previousHighEnvelope = 0.0f;

    float m_fluxPeak = 0.01f;
    float m_rmsPeak = 0.01f;

    float m_smoothedFlux = 0.0f;
    float m_smoothedCentroid = 0.0f;
    float m_smoothedSilence = 1.0f;
};
