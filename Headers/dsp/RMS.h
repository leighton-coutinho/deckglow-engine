#pragma once
#include <cmath>

class RMS   // This class computes the Root Mean Square (RMS) value of an audio buffer, which is a common measure of the signal's power or loudness. (RMS Chop)
{
public:

    static float compute(const float* buffer, size_t n)
    {
        double sum = 0.0;

        for (size_t i = 0; i < n; i++)
        {
            sum += buffer[i] * buffer[i];
        }

        return std::sqrt(sum / n);
    }

};
