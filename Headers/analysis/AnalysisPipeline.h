#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "Headers/analysis/AnalysisContext.h"
#include "Headers/analysis/FeatureFrame.h"
#include "Headers/analysis/modules/BandEnergyAnalyzer.h"
#include "Headers/dsp/AudioBuffer.h"

class AnalysisPipeline
{
public:

    FeatureFrame processAudioBlock(
        const float* interleaved,
        std::size_t frames,
        int channels,
        int sampleRate)
    {
        AnalysisContext context;
        context.sampleRate = sampleRate;
        context.channels = channels;
        context.blockFrames = frames;
        context.blockIndex = ++m_blockCounter;
        context.streamTimeSeconds = sampleRate > 0
            ? static_cast<double>(m_totalFrames) / static_cast<double>(sampleRate)
            : 0.0;

        if (!interleaved || frames == 0 || channels <= 0 || sampleRate <= 0)
        {
            return FeatureFrame{
                context.blockIndex,
                context.streamTimeSeconds,
                0.0f,
                0.0f,
                0.0f,
                0.0f
            };
        }

        AudioBuffer::downmixToMono(interleaved, frames, channels, m_mono);

        FeatureFrame frame = m_bandEnergyAnalyzer.processBlock(m_mono, context);
        m_totalFrames += frames;

        return frame;
    }

private:

    std::vector<float> m_mono;
    std::uint64_t m_blockCounter = 0;
    std::uint64_t m_totalFrames = 0;
    BandEnergyAnalyzer m_bandEnergyAnalyzer;
};
