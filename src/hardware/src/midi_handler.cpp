#include <RtMidi.h>
#include <functional>
#include <iostream>
#include <pybind11/functional.h> // Required for std::function conversions
#include <pybind11/pybind11.h>
#include <vector>

namespace py = pybind11;

class MidiHandler {
public:
  MidiHandler() {
    try {
      midiIn = new RtMidiIn();
      std::cout << "MidiHandler initialized with RtMidi" << std::endl;

      // NOTE: We deliberately do NOT register the callback here.
      // RtMidi starts an internal input thread when setCallback() is called,
      // and on macOS (CoreMIDI) this can deadlock if no run-loop is active
      // or if the port hasn't been opened yet.  The callback is registered
      // in openPort() after the port is successfully opened.

    } catch (RtMidiError &error) {
      // midiIn stays nullptr — all methods below must null-guard
      error.printMessage();
    }
  }

  ~MidiHandler() {
    if (midiIn) {
      if (callbackActive)
        midiIn->cancelCallback();
      delete midiIn;
      midiIn = nullptr;
    }
  }

  void openPort(int port) {
    if (!midiIn)
      return;
    if (port >= 0 && static_cast<unsigned int>(port) < midiIn->getPortCount()) {
      midiIn->openPort(port);
      std::cout << "Opened MIDI Input port: " << midiIn->getPortName(port)
                << std::endl;

      // Register the C++ wrapper callback now that the port is open.
      // This starts RtMidi's internal input thread.
      midiIn->setCallback(&MidiHandler::midiInputCallback, this);
      callbackActive = true;
      std::cout << "MIDI input callback registered." << std::endl;
    }
  }

  // Deterministic teardown callable from Python BEFORE the reference is
  // dropped. Runs with the GIL released (see pybindings), so the WinMM /
  // CoreMIDI close cannot deadlock against the input thread acquiring the
  // GIL for a Python callback.
  void closePort() {
    if (!midiIn)
      return;
    if (callbackActive) {
      midiIn->cancelCallback();
      callbackActive = false;
    }
    midiIn->closePort();
    delete midiIn;
    midiIn = nullptr;
  }

  void setIgnoreTypes(bool sysex, bool timing, bool activeSensing) {
    if (midiIn) {
      midiIn->ignoreTypes(sysex, timing, activeSensing);
    }
  }

  std::vector<std::string> getPortNames() {
    std::vector<std::string> names;
    if (!midiIn)
      return names;
    unsigned int nPorts = midiIn->getPortCount();
    for (unsigned int i = 0; i < nPorts; i++) {
      names.push_back(midiIn->getPortName(i));
    }
    return names;
  }

  void setCallback(
      std::function<void(double, std::vector<unsigned char>)> callback) {
    pyCallback = callback;
  }

private:
  static void midiInputCallback(double deltatime,
                                std::vector<unsigned char> *message,
                                void *userData) {
    MidiHandler *handler = static_cast<MidiHandler *>(userData);

    if (handler && handler->pyCallback && message && !message->empty()) {
      // Acquire the Global Interpreter Lock (GIL) before executing the Python
      // callback
      py::gil_scoped_acquire acquire;

      try {
        handler->pyCallback(deltatime, *message);
      } catch (py::error_already_set &e) {
        std::cerr << "Python callback exception in MIDI thread: " << e.what()
                  << std::endl;
      }
    }
  }

  RtMidiIn *midiIn = nullptr;
  bool callbackActive = false;
  std::function<void(double, std::vector<unsigned char>)> pyCallback;
};
