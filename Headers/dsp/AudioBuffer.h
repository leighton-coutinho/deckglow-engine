#pragma once
#include <vector>

class AudioBuffer // This class replaces the resample and mix steps, it can be used to downmix to mono, upmix to stereo, and resample the audio data as needed.
{
public:

    static void downmixToMono(
        const float* interleaved,
        size_t frames,
        int channels,
        std::vector<float>& mono)
    {
        mono.resize(frames);

        for (size_t i = 0; i < frames; i++)
        {
            float sum = 0.0f;

            for (int c = 0; c < channels; c++)
            {
                sum += interleaved[i * channels + c];
            }

            mono[i] = sum / channels;
        }
    }

};