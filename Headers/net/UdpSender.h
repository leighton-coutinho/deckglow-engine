#pragma once

#include <winsock2.h>
#include <ws2tcpip.h>
#include <string>

#pragma comment(lib, "ws2_32.lib")

class UdpSender
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

    void send(float bass, float mid, float high)
    {
        if (!m_initialized)
            return;

        char buffer[128];
        int len = sprintf_s(buffer, "bassMidHigh,%f,%f,%f\n", bass, mid, high);

        sendto(m_socket, buffer, len, 0,
            reinterpret_cast<sockaddr*>(&m_addr), sizeof(m_addr));
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

private:
    SOCKET m_socket = INVALID_SOCKET;
    sockaddr_in m_addr{};
    bool m_wsaStarted = false;
    bool m_initialized = false;
};
