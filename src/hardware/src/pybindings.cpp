/**
 * NOTE FOR DEVELOPERS:
 * If your IDE reports 'portaudio.h' or 'RtMidi.h' not found, ensure your
 * include paths include the following (relative to build directory):
 * - _deps/portaudio-src/include
 * - _deps/rtmidi-src
 */
#include "audio_handler.cpp"
#include "midi_handler.cpp"
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

PYBIND11_MODULE(chordcoach_hw, m) {
  m.doc() = "ChordCoach Hardware Layer C++ Extensions";

  py::class_<MidiHandler>(m, "MidiHandler")
      .def(py::init<>())
      .def("openPort", &MidiHandler::openPort)
      .def("sendMessage", &MidiHandler::sendMessage)
      .def("getPortNames", &MidiHandler::getPortNames)
      .def("setCallback", &MidiHandler::setCallback);

  py::class_<AudioHandler>(m, "AudioHandler")
      .def(py::init<>())
      .def("startCapture", &AudioHandler::startCapture)
      .def("stopCapture", &AudioHandler::stopCapture)
      .def("setCallback", &AudioHandler::setCallback);
}
