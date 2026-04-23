#pragma once

#include <algorithm>
#include <vector>

#include "Headers/analysis/AnalysisContext.h"
#include "Headers/analysis/FeatureFrame.h"
#include "Headers/dsp/AdaptiveNormalizer.h"
#include "Headers/dsp/BandSplitter.h"
#include "Headers/dsp/EnvelopeFollower.h"
#include "Headers/dsp/NoiseGate.h"

class BandEnergyAnalyzer
{
public:

    void initialize(float sampleRate)
    {
        m_splitter.initialize(sampleRate);

        m_bassEnv.initialize(sampleRate, 10.0f, 200.0f);
        m_midEnv.initialize(sampleRate, 20.0f, 150.0f);
        m_highEnv.initialize(sampleRate, 5.0f, 80.0f);

        m_bassGate.initialize(0.005f);
        m_midGate.initialize(0.003f);
        m_highGate.initialize(0.002f);

        m_bassNorm.initialize(sampleRate);
        m_midNorm.initialize(sampleRate);
        m_highNorm.initialize(sampleRate);

        m_sampleRate = sampleRate;
        m_initialized = true;
    }

    FeatureFrame processBlock(const std::vector<float>& mono, const AnalysisContext& context)
    {
        if (context.sampleRate <= 0)
        {
            FeatureFrame frame;
            frame.frameId = context.blockIndex;
            frame.timestampSeconds = context.streamTimeSeconds;
            return frame;
        }

        if (!m_initialized || m_sampleRate != static_cast<float>(context.sampleRate))
        {
            initialize(static_cast<float>(context.sampleRate));
        }

        FeatureFrame frame;
        frame.frameId = context.blockIndex;
        frame.timestampSeconds = context.streamTimeSeconds;

        if (mono.empty())
        {
            return frame;
        }

        float bassValue = 0.0f;
        float midValue = 0.0f;
        float highValue = 0.0f;

        for (float sample : mono)
        {
            m_splitter.process(sample);

            float bassEnvelope = m_bassEnv.process(m_splitter.bass);
            float midEnvelope = m_midEnv.process(m_splitter.mid);
            float highEnvelope = m_highEnv.process(m_splitter.high);

            bassEnvelope = m_bassGate.process(bassEnvelope);
            midEnvelope = m_midGate.process(midEnvelope);
            highEnvelope = m_highGate.process(highEnvelope);

            bassValue = m_bassNorm.process(bassEnvelope);
            midValue = m_midNorm.process(midEnvelope);
            highValue = m_highNorm.process(highEnvelope);
        }

        frame.bass = bassValue;
        frame.mid = midValue;
        frame.high = highValue;
        frame.masterLevel = std::clamp((bassValue + midValue + highValue) / 3.0f, 0.0f, 1.0f);

        return frame;
    }

private:

    float m_sampleRate = 0.0f;
    bool m_initialized = false;

    BandSplitter m_splitter;

    EnvelopeFollower m_bassEnv;
    EnvelopeFollower m_midEnv;
    EnvelopeFollower m_highEnv;

    NoiseGate m_bassGate;
    NoiseGate m_midGate;
    NoiseGate m_highGate;

    AdaptiveNormalizer m_bassNorm;
    AdaptiveNormalizer m_midNorm;
    AdaptiveNormalizer m_highNorm;
};
