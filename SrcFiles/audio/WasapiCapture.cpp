#include "Headers/audio/WasapiCapture.h"

#define NOMINMAX
#include <windows.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <audiopolicy.h>
#include <functiondiscoverykeys_devpkey.h>

#include <vector>
#include <iostream>
#include <algorithm>
#include <cmath>

// Implementation struct to hold COM interface pointers and related data for WASAPI capture
struct WasapiCapture::Impl {
    IMMDeviceEnumerator* enumerator = nullptr;
    IMMDevice* device = nullptr;
    IAudioClient* audioClient = nullptr;
    IAudioCaptureClient* captureClient = nullptr;

    WAVEFORMATEX* mixFormat = nullptr;
    HANDLE eventHandle = nullptr;

    // preferred buffer duration (100ms)
    REFERENCE_TIME bufferDuration = 1000000; // 100ms in 100ns units
};

static void safeRelease(IUnknown*& p) {
    if (p) { p->Release(); p = nullptr; }
}

WasapiCapture::~WasapiCapture() {
    stop();
    if (!m_impl) return;

    if (m_impl->eventHandle) {
        CloseHandle(m_impl->eventHandle);
        m_impl->eventHandle = nullptr;
    }
    if (m_impl->mixFormat) {
        CoTaskMemFree(m_impl->mixFormat);
        m_impl->mixFormat = nullptr;
    }

    safeRelease(reinterpret_cast<IUnknown*&>(m_impl->captureClient));
    safeRelease(reinterpret_cast<IUnknown*&>(m_impl->audioClient));
    safeRelease(reinterpret_cast<IUnknown*&>(m_impl->device));
    safeRelease(reinterpret_cast<IUnknown*&>(m_impl->enumerator));

    delete m_impl;
    m_impl = nullptr;
}

bool WasapiCapture::initializeDefaultLoopback() {
	if (m_impl) return true; // If already initialized, return immediately
    m_impl = new Impl();

    // Initialize COM for multi-threaded use
	HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr) && hr != RPC_E_CHANGED_MODE) {
        std::cerr << "CoInitializeEx failed: 0x" << std::hex << hr << std::dec << "\n";
        return false;
    }

    // Create an instance of the MMDeviceEnumerator COM object
	hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
        __uuidof(IMMDeviceEnumerator),
        reinterpret_cast<void**>(&m_impl->enumerator));
    if (FAILED(hr)) {
        std::cerr << "CoCreateInstance(MMDeviceEnumerator) failed: 0x" << std::hex << hr << std::dec << "\n";
        return false;
    }

    // Use default render (speaker) device TODO Leighton: Verify if default is ok
    hr = m_impl->enumerator->GetDefaultAudioEndpoint(eRender, eConsole, &m_impl->device);
    if (FAILED(hr)) {
        std::cerr << "GetDefaultAudioEndpoint failed: 0x" << std::hex << hr << std::dec << "\n";
        return false;
    }

	// Activate the IAudioClient interface on the device
    hr = m_impl->device->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr,
        reinterpret_cast<void**>(&m_impl->audioClient));
    if (FAILED(hr)) {
        std::cerr << "Activate(IAudioClient) failed: 0x" << std::hex << hr << std::dec << "\n";
        return false;
    }
    
	// Get the mix format of the device
    hr = m_impl->audioClient->GetMixFormat(&m_impl->mixFormat);
    if (FAILED(hr) || !m_impl->mixFormat) {
        std::cerr << "GetMixFormat failed: 0x" << std::hex << hr << std::dec << "\n";
        return false;
    }

    // We’ll capture whatever the system mix format is.
    m_sampleRate = static_cast<int>(m_impl->mixFormat->nSamplesPerSec);
    m_channels = static_cast<int>(m_impl->mixFormat->nChannels);

    // Event-driven loopback capture
    DWORD flags = AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK;

	// Initialize the audio client for loopback capture with the mix format and buffer duration
    hr = m_impl->audioClient->Initialize(
        AUDCLNT_SHAREMODE_SHARED,
        flags,
        m_impl->bufferDuration,
        0,
        m_impl->mixFormat,
        nullptr
    );

    if (FAILED(hr)) {
        std::cerr << "IAudioClient::Initialize failed: 0x" << std::hex << hr << std::dec
            << " (sampleRate=" << m_sampleRate << ", channels=" << m_channels << ")\n";
        return false;
    }

    m_impl->eventHandle = CreateEvent(nullptr, FALSE, FALSE, nullptr);
    if (!m_impl->eventHandle) {
        std::cerr << "CreateEvent failed\n";
        return false;
    }

    hr = m_impl->audioClient->SetEventHandle(m_impl->eventHandle);
    if (FAILED(hr)) {
        std::cerr << "SetEventHandle failed: 0x" << std::hex << hr << std::dec << "\n";
        return false;
    }

    hr = m_impl->audioClient->GetService(__uuidof(IAudioCaptureClient),
        reinterpret_cast<void**>(&m_impl->captureClient));
    if (FAILED(hr)) {
        std::cerr << "GetService(IAudioCaptureClient) failed: 0x" << std::hex << hr << std::dec << "\n";
        return false;
    }

    return true;
}

void WasapiCapture::start() {
    if (!m_impl || m_running) return;

    HRESULT hr = m_impl->audioClient->Start();
    if (FAILED(hr)) {
        std::cerr << "IAudioClient::Start failed: 0x" << std::hex << hr << std::dec << "\n";
        return;
    }

    m_running = true;
    m_thread = std::thread(&WasapiCapture::captureThread, this);
}

void WasapiCapture::stop() {
    if (!m_running) return;
    m_running = false;

    if (m_impl && m_impl->eventHandle)
        SetEvent(m_impl->eventHandle); // wake thread

    if (m_thread.joinable())
        m_thread.join();

    if (m_impl && m_impl->audioClient) {
        m_impl->audioClient->Stop();
    }
}

static bool isFloatFormat(const WAVEFORMATEX* wf) {
    if (!wf) return false;
    if (wf->wFormatTag == WAVE_FORMAT_IEEE_FLOAT) return true;
    if (wf->wFormatTag == WAVE_FORMAT_EXTENSIBLE) {
        auto* wfe = reinterpret_cast<const WAVEFORMATEXTENSIBLE*>(wf);
        return IsEqualGUID(wfe->SubFormat, KSDATAFORMAT_SUBTYPE_IEEE_FLOAT);
    }
    return false;
}

void WasapiCapture::captureThread() {
    std::vector<float> floatInterleaved;

    const bool floatFmt = isFloatFormat(m_impl->mixFormat);
    const int ch = m_channels;
    const int sr = m_sampleRate;

    // If not float, we’ll do minimal conversion for PCM16 only
    const bool pcm16 = (m_impl->mixFormat->wFormatTag == WAVE_FORMAT_PCM &&
        m_impl->mixFormat->wBitsPerSample == 16);

    while (m_running) {
		// Wait for the capture event to be signaled, with a timeout to allow checking m_running
        DWORD waitRes = WaitForSingleObject(m_impl->eventHandle, 200);
        if (!m_running) break;
        if (waitRes != WAIT_OBJECT_0) continue;

		// Check how many frames are available in the capture buffer
        UINT32 packetFrames = 0;
        HRESULT hr = m_impl->captureClient->GetNextPacketSize(&packetFrames);
        if (FAILED(hr)) continue;

        while (packetFrames > 0) {
            BYTE* data = nullptr;
            UINT32 frames = 0;
            DWORD flags = 0;

			// Get the captured audio data from the capture buffer
            hr = m_impl->captureClient->GetBuffer(&data, &frames, &flags, nullptr, nullptr);
            if (FAILED(hr)) break;

            const bool silent = (flags & AUDCLNT_BUFFERFLAGS_SILENT) != 0;

            // Prepare float buffer
            floatInterleaved.resize(static_cast<size_t>(frames) * ch);

            if (silent || !data) {
                std::fill(floatInterleaved.begin(), floatInterleaved.end(), 0.0f);
            }
            else if (floatFmt) {
                // Interleaved float32
                const float* f = reinterpret_cast<const float*>(data);
                std::copy(f, f + floatInterleaved.size(), floatInterleaved.begin());
            }
            else if (pcm16) {
                const int16_t* s = reinterpret_cast<const int16_t*>(data);
                for (size_t i = 0; i < floatInterleaved.size(); ++i)
                    floatInterleaved[i] = static_cast<float>(s[i]) / 32768.0f;
            }
            else {
                // Unknown format; zero it to avoid garbage
                std::fill(floatInterleaved.begin(), floatInterleaved.end(), 0.0f);
            }

			// Call the user callback with the captured audio data
            if (m_callback) {
                m_callback(floatInterleaved.data(), frames, ch, sr);
            }

			// Release the buffer back to the audio engine
            hr = m_impl->captureClient->ReleaseBuffer(frames);
            if (FAILED(hr)) break;

			// Check if more data is available in the capture buffer  TODO Leighton: Verify if this loop is necessary or if we can rely on the event to trigger for new data
            hr = m_impl->captureClient->GetNextPacketSize(&packetFrames);
            if (FAILED(hr)) break;
        }
    }
}