#pragma once
#include <cmath>
constexpr float PI = 3.14159265358979323846f;

class BiquadFilter      // This class will be used to help split the audio signal into low and high frequency bands for the crossover. 
                        //It implements a biquad filter, which can be configured as either a low-pass or high-pass filter depending on the cutoff frequency and sample rate.
{
public:

    void setLowpass(float cutoff, float sampleRate)
    {
        float w = 2.0f * PI * cutoff / sampleRate;
        float cosw = cos(w);
        float sinw = sin(w);
        float q = 0.707f;

        float alpha = sinw / (2.0f * q);

        float b0 = (1 - cosw) / 2;
        float b1 = 1 - cosw;
        float b2 = (1 - cosw) / 2;
        float a0 = 1 + alpha;
        float a1 = -2 * cosw;
        float a2 = 1 - alpha;

        this->b0 = b0 / a0;
        this->b1 = b1 / a0;
        this->b2 = b2 / a0;
        this->a1 = a1 / a0;
        this->a2 = a2 / a0;
    }

    void setHighpass(float cutoff, float sampleRate)
    {
        float w = 2.0f * PI * cutoff / sampleRate;
        float cosw = cos(w);
        float sinw = sin(w);
        float q = 0.707f;

        float alpha = sinw / (2.0f * q);

        float b0 = (1 + cosw) / 2;
        float b1 = -(1 + cosw);
        float b2 = (1 + cosw) / 2;
        float a0 = 1 + alpha;
        float a1 = -2 * cosw;
        float a2 = 1 - alpha;

        this->b0 = b0 / a0;
        this->b1 = b1 / a0;
        this->b2 = b2 / a0;
        this->a1 = a1 / a0;
        this->a2 = a2 / a0;
    }

    float process(float input)
    {
        float out = b0 * input + z1;
        z1 = b1 * input - a1 * out + z2;
        z2 = b2 * input - a2 * out;
        return out;
    }

private:

    float b0 = 0, b1 = 0, b2 = 0, a1 = 0, a2 = 0;
    float z1 = 0, z2 = 0;
};