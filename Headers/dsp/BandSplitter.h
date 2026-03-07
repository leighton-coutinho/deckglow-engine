#pragma once
#include "BiquadFilter.h"

/*
This class splits the audio signal into three frequency bands: bass, mid, and high. 
It uses biquad filters to separate the frequencies based on the specified crossover points. 
Here are the current band definitions:
Bass  : 20–200 Hz
Mid   : 200–2500 Hz         
High  : 2500–12000 Hz
The process method takes an input sample and updates the bass, mid, and high member variables with the corresponding filtered values
*/

class BandSplitter
{
public:

    void initialize(float sampleRate)
    {
        bassLP.setLowpass(200.0f, sampleRate);

        midHP.setHighpass(200.0f, sampleRate);
        midLP.setLowpass(2500.0f, sampleRate);

        highHP.setHighpass(2500.0f, sampleRate);
    }

    void process(float sample)
    {
        bass = bassLP.process(sample);

        float mid = midHP.process(sample);
        mid = midLP.process(mid);

        float high = highHP.process(sample);

        this->mid = mid;
        this->high = high;
    }

    float bass = 0;
    float mid = 0;
    float high = 0;

private:

    BiquadFilter bassLP;

    BiquadFilter midHP;
    BiquadFilter midLP;

    BiquadFilter highHP;
};