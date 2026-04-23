#pragma once

#include <string>

struct TransportOptions
{
    std::string host = "127.0.0.1";
    int port = 9000;
};

struct RuntimeOptions
{
    TransportOptions transport{};
};
