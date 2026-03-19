// ReactiveVisualEngine.cpp : This file contains the 'main' function. Program execution begins and ends there.
//

#include <iostream>
#include <vector>

#include "Headers/audio/WasapiCapture.h"
#include "Headers/dsp/AudioBuffer.h"
#include "Headers/dsp/RMS.h"
#include "Headers/dsp/BandSplitter.h"
#include "Headers/dsp/EnvelopeFollower.h"

int main()
{
    WasapiCapture cap;

    if (!cap.initializeDefaultLoopback())
    {
        std::cout << "Failed to initialize audio capture\n";
        return 1;
    }

    std::vector<float> mono;

    BandSplitter splitter;

    EnvelopeFollower bassEnv;
    EnvelopeFollower midEnv;
    EnvelopeFollower highEnv;

    bool initialized = false;

    cap.setCallback(
        [&](const float* data, size_t frames, int channels, int sampleRate)
        {
            // 1️⃣ Downmix stereo → mono
            AudioBuffer::downmixToMono(data, frames, channels, mono);

            // 2️⃣ Initialize DSP once (we need sample rate)
            if (!initialized)
            {
                splitter.initialize(static_cast<float>(sampleRate));

                bassEnv.initialize(static_cast<float>(sampleRate), 10.0f, 200.0f);
                midEnv.initialize(static_cast<float>(sampleRate), 20.0f, 150.0f);
                highEnv.initialize(static_cast<float>(sampleRate), 5.0f, 80.0f);

                initialized = true;
            }

            float bassValue = 0.0f;
            float midValue = 0.0f;
            float highValue = 0.0f;

            // 3️⃣ Process audio block
            for (float s : mono)
            {
                splitter.process(s);

                bassValue = bassEnv.process(splitter.bass);
                midValue = midEnv.process(splitter.mid);
                highValue = highEnv.process(splitter.high);
            }

            // 4️⃣ Print smoothed output
            std::cout
                << "Bass: " << bassValue
                << "  Mid: " << midValue
                << "  High: " << highValue
                << "\r";
        }
    );

    cap.start();

    std::cout << "Listening to system audio...\n";
    std::cout << "Press ENTER to quit\n";

    std::cin.get();

    cap.stop();

    return 0;
}