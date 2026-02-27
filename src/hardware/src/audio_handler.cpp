#include <functional>
#include <iostream>
#include <portaudio.h>
#include <pybind11/functional.h> // Required for std::function conversions
#include <pybind11/pybind11.h>
#include <vector>


namespace py = pybind11;

class AudioHandler {
public:
  AudioHandler() {
    PaError err = Pa_Initialize();
    if (err != paNoError) {
      std::cerr << "PortAudio initialization error: " << Pa_GetErrorText(err)
                << std::endl;
    } else {
      std::cout << "AudioHandler initialized with PortAudio" << std::endl;
    }
  }

  ~AudioHandler() {
    stopCapture();
    Pa_Terminate();
  }

  void setCallback(std::function<void(std::vector<float>)> callback) {
    pyCallback = callback;
  }

  void startCapture() {
    if (stream) {
      std::cout << "Audio capture already running." << std::endl;
      return;
    }

    PaStreamParameters inputParameters;
    inputParameters.device = Pa_GetDefaultInputDevice();
    if (inputParameters.device == paNoDevice) {
      std::cerr << "Error: No default input device." << std::endl;
      return;
    }
    inputParameters.channelCount = 1; // mono
    inputParameters.sampleFormat = paFloat32;
    inputParameters.suggestedLatency =
        Pa_GetDeviceInfo(inputParameters.device)->defaultLowInputLatency;
    inputParameters.hostApiSpecificStreamInfo = nullptr;

    PaError err = Pa_OpenStream(&stream, &inputParameters,
                                nullptr, // no output
                                16000,   // sample rate
                                512,     // frames per buffer
                                paClipOff, &AudioHandler::paCallback, this);

    if (err != paNoError) {
      std::cerr << "PortAudio open stream error: " << Pa_GetErrorText(err)
                << std::endl;
      return;
    }

    err = Pa_StartStream(stream);
    if (err != paNoError) {
      std::cerr << "PortAudio start stream error: " << Pa_GetErrorText(err)
                << std::endl;
      return;
    }

    std::cout << "Started audio capture" << std::endl;
  }

  void stopCapture() {
    if (stream) {
      Pa_StopStream(stream);
      Pa_CloseStream(stream);
      stream = nullptr;
      std::cout << "Stopped audio capture" << std::endl;
    }
  }

private:
  static int paCallback(const void *inputBuffer, void *outputBuffer,
                        unsigned long framesPerBuffer,
                        const PaStreamCallbackTimeInfo *timeInfo,
                        PaStreamCallbackFlags statusFlags, void *userData) {

    AudioHandler *handler = static_cast<AudioHandler *>(userData);

    if (handler && handler->pyCallback && inputBuffer) {
      const float *in = static_cast<const float *>(inputBuffer);
      std::vector<float> pcmData(in, in + framesPerBuffer);

      // Acquire GIL to safely execute Python callback
      py::gil_scoped_acquire acquire;
      try {
        handler->pyCallback(pcmData);
      } catch (py::error_already_set &e) {
        std::cerr << "Python callback exception in Audio thread: " << e.what()
                  << std::endl;
      }
    }

    return paContinue;
  }

  PaStream *stream = nullptr;
  std::function<void(std::vector<float>)> pyCallback;
};
