#pragma once

#include <cstddef>
#include <cstdint>

struct AnalysisContext
{
    int sampleRate = 0;
    int channels = 0;
    std::size_t blockFrames = 0;
    std::uint64_t blockIndex = 0;
    double streamTimeSeconds = 0.0;
    double blockDurationSeconds = 0.0;
};
