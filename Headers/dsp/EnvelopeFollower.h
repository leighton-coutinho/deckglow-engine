#pragma once
#include <cmath>

class EnvelopeFollower
{
public:

    void initialize(float sampleRate, float attackMs, float releaseMs)
    {
        m_sampleRate = sampleRate;

        setAttack(attackMs);
        setRelease(releaseMs);
    }

    void setAttack(float attackMs)
    {
        // Convert ms → coefficient
        float attackTime = attackMs / 1000.0f;
        m_attackCoeff = std::exp(-1.0f / (attackTime * m_sampleRate));
    }

    void setRelease(float releaseMs)
    {
        float releaseTime = releaseMs / 1000.0f;
        m_releaseCoeff = std::exp(-1.0f / (releaseTime * m_sampleRate));
    }

    float process(float input)
    {
        // Full-wave rectification
        float x = std::fabs(input);

        if (x > m_env)
        {
            // Attack (fast rise)
            m_env = m_attackCoeff * (m_env - x) + x;
        }
        else
        {
            // Release (slow decay)
            m_env = m_releaseCoeff * (m_env - x) + x;
        }

        return m_env;
    }

    float getValue() const
    {
        return m_env;
    }

private:

    float m_sampleRate = 48000.0f;

    float m_attackCoeff = 0.0f;
    float m_releaseCoeff = 0.0f;

    float m_env = 0.0f;
};