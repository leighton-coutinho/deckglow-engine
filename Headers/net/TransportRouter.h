#pragma once

#include <algorithm>
#include <cstdint>
#include <sstream>
#include <string>
#include <vector>

#include "Headers/analysis/FeatureFrame.h"
#include "Headers/app/RuntimeOptions.h"
#include "Headers/net/OscSender.h"
#include "Headers/net/UdpSender.h"

class TransportRouter
{
public:
    bool initialize(const TransportOptions& options)
    {
        m_options = options;

        bool anyEnabled = false;

        if (m_options.osc.enabled)
        {
            if (!m_oscSender.initialize(m_options.osc.host, m_options.osc.port))
            {
                shutdown();
                return false;
            }

            anyEnabled = true;
            m_oscInitialized = true;
        }

        if (m_options.legacyUdp.enabled)
        {
            if (!m_legacySender.initialize(m_options.legacyUdp.host, m_options.legacyUdp.port))
            {
                shutdown();
                return false;
            }

            anyEnabled = true;
            m_legacyInitialized = true;
        }

        return anyEnabled;
    }

    void send(const FeatureFrame& frame)
    {
        if (m_oscInitialized)
        {
            m_oscSender.sendBundle(buildOscMessages(frame));
        }

        if (m_legacyInitialized)
        {
            m_legacySender.send(frame.bass, frame.mid, frame.high);
        }
    }

    void shutdown()
    {
        if (m_oscInitialized)
        {
            m_oscSender.shutdown();
            m_oscInitialized = false;
        }

        if (m_legacyInitialized)
        {
            m_legacySender.shutdown();
            m_legacyInitialized = false;
        }
    }

    std::string describeActiveTransports() const
    {
        std::ostringstream description;
        bool first = true;

        if (m_options.osc.enabled)
        {
            description << "OSC " << m_options.osc.prefix
                << " -> " << m_options.osc.host << ":" << m_options.osc.port;
            first = false;
        }

        if (m_options.legacyUdp.enabled)
        {
            if (!first)
            {
                description << " | ";
            }

            description << "Legacy UDP CSV -> " << m_options.legacyUdp.host
                << ":" << m_options.legacyUdp.port;
        }

        return description.str();
    }

private:
    std::vector<std::vector<std::uint8_t>> buildOscMessages(const FeatureFrame& frame) const
    {
        const auto address = [&](const std::string& suffix)
        {
            return m_options.osc.prefix + suffix;
        };

        std::vector<std::vector<std::uint8_t>> messages;
        messages.reserve(23);

        messages.push_back(OscSender::buildIntMessage(
            address("/meta/frame_id"),
            static_cast<std::int32_t>(std::min<std::uint64_t>(frame.frameId, static_cast<std::uint64_t>(INT32_MAX)))));
        messages.push_back(OscSender::buildFloatMessage(
            address("/meta/timestamp"),
            static_cast<float>(frame.timestampSeconds)));

        messages.push_back(OscSender::buildFloatMessage(address("/audio/master_level"), frame.masterLevel));
        messages.push_back(OscSender::buildFloatMessage(address("/audio/bass"), frame.bass));
        messages.push_back(OscSender::buildFloatMessage(address("/audio/mid"), frame.mid));
        messages.push_back(OscSender::buildFloatMessage(address("/audio/high"), frame.high));
        messages.push_back(OscSender::buildFloatMessage(address("/audio/onset"), frame.onset));
        messages.push_back(OscSender::buildFloatMessage(address("/audio/kick"), frame.kick));
        messages.push_back(OscSender::buildFloatMessage(address("/audio/snare"), frame.snare));
        messages.push_back(OscSender::buildFloatMessage(address("/audio/hihat"), frame.hihat));
        messages.push_back(OscSender::buildFloatMessage(address("/audio/stereo_width"), frame.stereoWidth));
        messages.push_back(OscSender::buildFloatMessage(address("/audio/spectral_centroid"), frame.spectralCentroid));
        messages.push_back(OscSender::buildFloatMessage(address("/audio/spectral_flux"), frame.spectralFlux));

        messages.push_back(OscSender::buildFloatMessage(address("/tempo/bpm"), frame.bpm));
        messages.push_back(OscSender::buildFloatMessage(address("/tempo/confidence"), frame.bpmConfidence));
        messages.push_back(OscSender::buildFloatMessage(address("/tempo/beat_phase"), frame.beatPhase));
        messages.push_back(OscSender::buildFloatMessage(address("/tempo/bar_phase"), frame.barPhase));
        messages.push_back(OscSender::buildFloatMessage(address("/tempo/phrase_phase"), frame.phrasePhase));
        messages.push_back(OscSender::buildFloatMessage(address("/tempo/beat_pulse"), frame.beatPulse));
        messages.push_back(OscSender::buildFloatMessage(address("/tempo/bar_pulse"), frame.barPulse));
        messages.push_back(OscSender::buildFloatMessage(address("/tempo/phrase_pulse"), frame.phrasePulse));

        messages.push_back(OscSender::buildFloatMessage(address("/structure/breakdown_likelihood"), frame.breakdownLikelihood));
        messages.push_back(OscSender::buildFloatMessage(address("/structure/drop_likelihood"), frame.dropLikelihood));
        messages.push_back(OscSender::buildFloatMessage(address("/structure/silence"), frame.silence));

        return messages;
    }

private:
    TransportOptions m_options{};
    OscSender m_oscSender;
    UdpSender m_legacySender;
    bool m_oscInitialized = false;
    bool m_legacyInitialized = false;
};
