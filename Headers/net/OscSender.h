#pragma once

#include <winsock2.h>
#include <ws2tcpip.h>

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#pragma comment(lib, "ws2_32.lib")

class OscSender
{
public:
    bool initialize(const std::string& ip, int port)
    {
        if (m_initialized)
            return true;

        WSADATA wsaData;
        if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0)
            return false;

        m_wsaStarted = true;

        m_socket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (m_socket == INVALID_SOCKET)
        {
            shutdown();
            return false;
        }

        m_addr.sin_family = AF_INET;
        m_addr.sin_port = htons(port);
        if (inet_pton(AF_INET, ip.c_str(), &m_addr.sin_addr) != 1)
        {
            shutdown();
            return false;
        }

        m_initialized = true;
        return true;
    }

    void sendBundle(const std::vector<std::vector<std::uint8_t>>& messages)
    {
        if (!m_initialized || messages.empty())
            return;

        std::vector<std::uint8_t> bundle;
        appendPaddedString(bundle, "#bundle");
        appendUInt64(bundle, 1);

        for (const auto& message : messages)
        {
            appendInt32(bundle, static_cast<std::int32_t>(message.size()));
            bundle.insert(bundle.end(), message.begin(), message.end());
        }

        sendto(
            m_socket,
            reinterpret_cast<const char*>(bundle.data()),
            static_cast<int>(bundle.size()),
            0,
            reinterpret_cast<sockaddr*>(&m_addr),
            sizeof(m_addr));
    }

    void shutdown()
    {
        if (m_socket != INVALID_SOCKET)
        {
            closesocket(m_socket);
            m_socket = INVALID_SOCKET;
        }

        if (m_wsaStarted)
        {
            WSACleanup();
            m_wsaStarted = false;
        }

        m_initialized = false;
    }

    static std::vector<std::uint8_t> buildFloatMessage(const std::string& address, float value)
    {
        std::vector<std::uint8_t> message;
        appendPaddedString(message, address);
        appendPaddedString(message, ",f");
        appendFloat32(message, value);
        return message;
    }

    static std::vector<std::uint8_t> buildIntMessage(const std::string& address, std::int32_t value)
    {
        std::vector<std::uint8_t> message;
        appendPaddedString(message, address);
        appendPaddedString(message, ",i");
        appendInt32(message, value);
        return message;
    }

private:
    static void appendPaddedString(std::vector<std::uint8_t>& buffer, const std::string& value)
    {
        buffer.insert(buffer.end(), value.begin(), value.end());
        buffer.push_back('\0');

        while (buffer.size() % 4 != 0)
        {
            buffer.push_back('\0');
        }
    }

    static void appendInt32(std::vector<std::uint8_t>& buffer, std::int32_t value)
    {
        const std::uint32_t networkValue = htonl(static_cast<std::uint32_t>(value));
        const auto* bytes = reinterpret_cast<const std::uint8_t*>(&networkValue);
        buffer.insert(buffer.end(), bytes, bytes + sizeof(networkValue));
    }

    static void appendUInt64(std::vector<std::uint8_t>& buffer, std::uint64_t value)
    {
        for (int shift = 56; shift >= 0; shift -= 8)
        {
            buffer.push_back(static_cast<std::uint8_t>((value >> shift) & 0xff));
        }
    }

    static void appendFloat32(std::vector<std::uint8_t>& buffer, float value)
    {
        static_assert(sizeof(float) == sizeof(std::uint32_t), "OSC float payloads expect 32-bit floats.");

        std::uint32_t rawValue = 0;
        std::memcpy(&rawValue, &value, sizeof(value));
        rawValue = htonl(rawValue);

        const auto* bytes = reinterpret_cast<const std::uint8_t*>(&rawValue);
        buffer.insert(buffer.end(), bytes, bytes + sizeof(rawValue));
    }

private:
    SOCKET m_socket = INVALID_SOCKET;
    sockaddr_in m_addr{};
    bool m_wsaStarted = false;
    bool m_initialized = false;
};
