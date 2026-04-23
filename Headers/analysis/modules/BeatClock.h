#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

#include "Headers/analysis/AnalysisContext.h"
#include "Headers/analysis/FeatureFrame.h"

class BeatClock
{
public:
    void process(FeatureFrame& frame, const AnalysisContext& context)
    {
        frame.beatPulse = 0.0f;
        frame.barPulse = 0.0f;
        frame.phrasePulse = 0.0f;

        if (context.blockDurationSeconds <= 0.0 || frame.bpm <= 0.0f || frame.bpmConfidence < 0.05f)
        {
            writePhases(frame);
            return;
        }

        const double beatsAdvanced = context.blockDurationSeconds * static_cast<double>(frame.bpm) / 60.0;
        double phase = m_beatPhase + beatsAdvanced;

        while (phase >= 1.0)
        {
            phase -= 1.0;
            advanceBeat(frame);
        }

        if (frame.onset > 0.72f)
        {
            const bool nearStart = phase < 0.18;
            const bool nearWrap = phase > 0.82;

            if (nearWrap)
            {
                advanceBeat(frame);
                phase = 0.0;
            }
            else if (nearStart)
            {
                phase = 0.0;
            }
        }

        m_beatPhase = phase;
        writePhases(frame);
    }

private:
    void advanceBeat(FeatureFrame& frame)
    {
        ++m_totalBeatCount;
        frame.beatPulse = 1.0f;

        if (m_totalBeatCount % 4 == 0)
        {
            frame.barPulse = 1.0f;
        }

        if (m_totalBeatCount % kPhraseLengthBeats == 0)
        {
            frame.phrasePulse = 1.0f;
        }
    }

    void writePhases(FeatureFrame& frame) const
    {
        frame.beatPhase = static_cast<float>(m_beatPhase);

        const double barPosition = std::fmod(
            static_cast<double>(m_totalBeatCount % 4) + m_beatPhase,
            4.0);
        frame.barPhase = static_cast<float>(barPosition / 4.0);

        const double phrasePosition = std::fmod(
            static_cast<double>(m_totalBeatCount % kPhraseLengthBeats) + m_beatPhase,
            static_cast<double>(kPhraseLengthBeats));
        frame.phrasePhase = static_cast<float>(phrasePosition / static_cast<double>(kPhraseLengthBeats));
    }

private:
    static constexpr std::uint64_t kPhraseLengthBeats = 32;

    std::uint64_t m_totalBeatCount = 0;
    double m_beatPhase = 0.0;
};
