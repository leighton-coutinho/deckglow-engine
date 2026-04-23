#pragma once

#include <string>

struct OscTransportOptions
{
    bool enabled = true;
    std::string host = "127.0.0.1";
    int port = 9001;
    std::string prefix = "/rve/v2";
};

struct LegacyUdpTransportOptions
{
    bool enabled = true;
    std::string host = "127.0.0.1";
    int port = 9000;
};

struct TransportOptions
{
    OscTransportOptions osc{};
    LegacyUdpTransportOptions legacyUdp{};
};

struct RuntimeOptions
{
    TransportOptions transport{};
};
