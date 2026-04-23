#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <vector>

#include "Headers/analysis/AnalysisContext.h"
#include "Headers/analysis/FeatureFrame.h"

class TempoEstimator
{
public:
    void process(FeatureFrame& frame, const AnalysisContext& context)
    {
        const float deltaTime = static_cast<float>(std::max(context.blockDurationSeconds, 0.0));
        decayHistogram(deltaTime);

        const bool onsetAccepted = shouldAcceptOnset(frame, context);
        if (onsetAccepted)
        {
            accumulateFromOnset(frame.timestampSeconds, frame.onset);
            m_lastAcceptedOnsetTime = frame.timestampSeconds;
        }

        updateOutput(frame);
    }

private:
    struct OnsetEvent
    {
        double timeSeconds = 0.0;
        float strength = 0.0f;
    };

    static constexpr int kMinBpm = 70;
    static constexpr int kMaxBpm = 180;
    static constexpr int kBinCount = kMaxBpm - kMinBpm + 1;

    bool shouldAcceptOnset(const FeatureFrame& frame, const AnalysisContext& context) const
    {
        if (frame.onset < 0.60f)
            return false;

        if (frame.kick < 0.45f && frame.masterLevel < 0.18f)
            return false;

        const double timeSinceLastAccepted = context.streamTimeSeconds - m_lastAcceptedOnsetTime;
        return timeSinceLastAccepted >= 0.22;
    }

    void accumulateFromOnset(double timeSeconds, float strength)
    {
        pruneEvents(timeSeconds);

        for (const auto& event : m_recentOnsets)
        {
            const double interval = timeSeconds - event.timeSeconds;
            if (interval < 0.25 || interval > 2.00)
                continue;

            const float candidateBpm = foldTempoIntoDanceRange(static_cast<float>(60.0 / interval));
            const int binIndex = static_cast<int>(std::lround(candidateBpm)) - kMinBpm;

            if (binIndex < 0 || binIndex >= kBinCount)
                continue;

            const float recencyWeight = static_cast<float>(1.0 - std::clamp(interval / 2.0, 0.0, 1.0));
            const float weight = std::max(0.05f, strength * event.strength * (0.45f + recencyWeight));
            m_bpmHistogram[binIndex] += weight;
        }

        m_recentOnsets.push_back({ timeSeconds, strength });
    }

    void decayHistogram(float deltaTime)
    {
        if (deltaTime <= 0.0f)
            return;

        const float decayPerSecond = 0.82f;
        const float decayFactor = std::pow(decayPerSecond, deltaTime);

        for (float& bin : m_bpmHistogram)
        {
            bin *= decayFactor;
        }
    }

    void updateOutput(FeatureFrame& frame)
    {
        float bestValue = 0.0f;
        float totalValue = 0.0f;
        int bestIndex = -1;

        for (int i = 0; i < kBinCount; ++i)
        {
            totalValue += m_bpmHistogram[i];

            if (m_bpmHistogram[i] > bestValue)
            {
                bestValue = m_bpmHistogram[i];
                bestIndex = i;
            }
        }

        if (bestIndex >= 0 && bestValue > 0.10f)
        {
            const float candidateBpm = static_cast<float>(kMinBpm + bestIndex);
            const float confidence = std::clamp(bestValue / std::max(totalValue, 0.001f), 0.0f, 1.0f);

            if (m_smoothedBpm <= 0.0f)
            {
                m_smoothedBpm = candidateBpm;
            }
            else
            {
                m_smoothedBpm += (candidateBpm - m_smoothedBpm) * 0.18f;
            }

            m_smoothedConfidence += (confidence - m_smoothedConfidence) * 0.22f;
        }
        else
        {
            m_smoothedConfidence *= 0.98f;
        }

        frame.bpm = m_smoothedBpm;
        frame.bpmConfidence = std::clamp(m_smoothedConfidence, 0.0f, 1.0f);
    }

    void pruneEvents(double currentTimeSeconds)
    {
        constexpr double historyWindowSeconds = 8.0;

        m_recentOnsets.erase(
            std::remove_if(
                m_recentOnsets.begin(),
                m_recentOnsets.end(),
                [&](const OnsetEvent& event)
                {
                    return currentTimeSeconds - event.timeSeconds > historyWindowSeconds;
                }),
            m_recentOnsets.end());
    }

    static float foldTempoIntoDanceRange(float bpm)
    {
        while (bpm < static_cast<float>(kMinBpm))
        {
            bpm *= 2.0f;
        }

        while (bpm > static_cast<float>(kMaxBpm))
        {
            bpm *= 0.5f;
        }

        return bpm;
    }

private:
    std::array<float, kBinCount> m_bpmHistogram{};
    std::vector<OnsetEvent> m_recentOnsets;
    double m_lastAcceptedOnsetTime = -1000.0;
    float m_smoothedBpm = 0.0f;
    float m_smoothedConfidence = 0.0f;
};
