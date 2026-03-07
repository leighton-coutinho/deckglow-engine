// ReactiveVisualEngine.cpp : This file contains the 'main' function. Program execution begins and ends there.
//

#include <iostream>
#include <vector>

#include "Headers/audio/WasapiCapture.h"
#include "Headers/dsp/AudioBuffer.h"
#include "Headers/dsp/RMS.h"
#include "Headers/dsp/BandSplitter.h"

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
    bool initialized = false;

    cap.setCallback(
        [&](const float* data, size_t frames, int channels, int sampleRate)
        {
            // 1️⃣ Convert stereo → mono
            AudioBuffer::downmixToMono(data, frames, channels, mono);

            // 2️⃣ Initialize filters once
            if (!initialized)
            {
                splitter.initialize(sampleRate);
                initialized = true;
            }

            float bassEnergy = 0;
            float midEnergy = 0;
            float highEnergy = 0;

            // 3️⃣ Process every sample
            for (float s : mono)
            {
                splitter.process(s);

                bassEnergy += splitter.bass * splitter.bass;
                midEnergy += splitter.mid * splitter.mid;
                highEnergy += splitter.high * splitter.high;
            }

            // 4️⃣ Compute RMS for each band
            bassEnergy = std::sqrt(bassEnergy / mono.size());
            midEnergy = std::sqrt(midEnergy / mono.size());
            highEnergy = std::sqrt(highEnergy / mono.size());

            // 5️⃣ Print results
            std::cout
                << "Bass: " << bassEnergy
                << "  Mid: " << midEnergy
                << "  High: " << highEnergy
                << "\r";
        }
    );

    cap.start();

    std::cout << "Listening to system audio...\n";
    std::cout << "Press ENTER to quit\n";

    std::cin.get();

    cap.stop();
}