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
};
