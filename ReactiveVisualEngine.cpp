// ReactiveVisualEngine.cpp : This file contains the 'main' function. Program execution begins and ends there.
//

#include <iomanip>
#include <iostream>

#include "Headers/analysis/AnalysisPipeline.h"
#include "Headers/analysis/FeatureFrame.h"
#include "Headers/app/RuntimeOptions.h"
#include "Headers/audio/WasapiCapture.h"
#include "Headers/net/UdpSender.h"

int main()
{
    RuntimeOptions options;
    WasapiCapture cap;

    if (!cap.initializeDefaultLoopback())
    {
        std::cout << "Failed to initialize audio capture\n";
        return 1;
    }

    UdpSender udp;
    if (!udp.initialize(options.transport.host, options.transport.port))
    {
        std::cout << "Failed to initialize UDP sender for "
            << options.transport.host << ":" << options.transport.port << "\n";
        return 1;
    }

    AnalysisPipeline analysisPipeline;

    std::cout << std::fixed << std::setprecision(3);

    cap.setCallback(
        [&](const float* data, size_t frames, int channels, int sampleRate)
        {
            const FeatureFrame frame = analysisPipeline.processAudioBlock(data, frames, channels, sampleRate);

            udp.send(frame.bass, frame.mid, frame.high);

            std::cout
                << "Level: " << frame.masterLevel
                << "  Bass: " << frame.bass
                << "  Mid: " << frame.mid
                << "  High: " << frame.high
                << "  SR: " << sampleRate
                << "\r";
        }
    );

    cap.start();

    std::cout << "Listening to system audio and sending reactive values to "
        << options.transport.host << ":" << options.transport.port << "\n";
    std::cout << "Press ENTER to quit\n";

    std::cin.get();

    cap.stop();
    udp.shutdown();

    return 0;
}
