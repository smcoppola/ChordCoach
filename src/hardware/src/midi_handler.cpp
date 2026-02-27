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
      midiOut = new RtMidiOut();
      std::cout << "MidiHandler initialized with RtMidi" << std::endl;

      // Register our static C++ wrapper callback unconditionally
      midiIn->setCallback(&MidiHandler::midiInputCallback, this);

    } catch (RtMidiError &error) {
      error.printMessage();
    }
  }

  ~MidiHandler() {
    delete midiIn;
    delete midiOut;
  }

  void openPort(int port) {
    if (port < midiIn->getPortCount()) {
      midiIn->openPort(port);
      std::cout << "Opened MIDI Input port: " << midiIn->getPortName(port)
                << std::endl;
    }
    if (port < midiOut->getPortCount()) {
      midiOut->openPort(port);
      std::cout << "Opened MIDI Output port: " << midiOut->getPortName(port)
                << std::endl;
    }
  }

  void sendMessage(const std::vector<unsigned char> &message) {
    if (midiOut && midiOut->isPortOpen()) {
      midiOut->sendMessage(&message);
    }
  }

  std::vector<std::string> getPortNames() {
    std::vector<std::string> names;
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

  RtMidiIn *midiIn;
  RtMidiOut *midiOut;
  std::function<void(double, std::vector<unsigned char>)> pyCallback;
};
