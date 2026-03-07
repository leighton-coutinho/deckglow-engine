#pragma once

#include <functional>
#include <thread>
#include <atomic>
#include <cstddef>

class WasapiCapture {
public:
    using Callback = std::function<void(const float* interleaved, size_t frames, int channels, int sampleRate)>;

    WasapiCapture() = default;
    ~WasapiCapture();

    bool initializeDefaultLoopback();
    void start();
    void stop();

    void setCallback(Callback cb) { m_callback = std::move(cb); }

    int sampleRate() const { return m_sampleRate; }
    int channels() const { return m_channels; }

private:
    void captureThread();

    std::thread m_thread; 
    std::atomic<bool> m_running{ false };
    Callback m_callback;

    // runtime format
    int m_sampleRate = 0;
    int m_channels = 0;

    // opaque impl pointers (COM interfaces)
    struct Impl; // Forward declaration of Implementation struct for PIMPL pattern
    Impl* m_impl = nullptr;
};