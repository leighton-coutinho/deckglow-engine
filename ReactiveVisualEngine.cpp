// ReactiveVisualEngine.cpp : This file contains the 'main' function. Program execution begins and ends there.
//

#include <iomanip>
#include <iostream>

#include "Headers/analysis/AnalysisPipeline.h"
#include "Headers/analysis/FeatureFrame.h"
#include "Headers/app/RuntimeOptions.h"
#include "Headers/audio/WasapiCapture.h"
#include "Headers/net/TransportRouter.h"

int main()
{
    RuntimeOptions options;
    WasapiCapture cap;

    if (!cap.initializeDefaultLoopback())
    {
        std::cout << "Failed to initialize audio capture\n";
        return 1;
    }

    TransportRouter transportRouter;
    if (!transportRouter.initialize(options.transport))
    {
        std::cout << "Failed to initialize transport router\n";
        return 1;
    }

    AnalysisPipeline analysisPipeline;

    std::cout << std::fixed << std::setprecision(3);

    cap.setCallback(
        [&](const float* data, size_t frames, int channels, int sampleRate)
        {
            const FeatureFrame frame = analysisPipeline.processAudioBlock(data, frames, channels, sampleRate);

            transportRouter.send(frame);

            std::cout
                << "Level: " << frame.masterLevel
                << "  Bass: " << frame.bass
                << "  Mid: " << frame.mid
                << "  High: " << frame.high
                << "  Onset: " << frame.onset
                << "  BPM: " << frame.bpm
                << "  Conf: " << frame.bpmConfidence
                << "  Beat: " << frame.beatPhase
                << "  SR: " << sampleRate
                << "\r";
        }
    );

    cap.start();

    std::cout << "Listening to system audio and sending reactive values via "
        << transportRouter.describeActiveTransports() << "\n";
    std::cout << "Press ENTER to quit\n";

    std::cin.get();

    cap.stop();
    transportRouter.shutdown();

    return 0;
}
