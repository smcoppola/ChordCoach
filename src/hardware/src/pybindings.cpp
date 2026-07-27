/**
 * NOTE FOR DEVELOPERS:
 * If your IDE reports 'portaudio.h' or 'RtMidi.h' not found, ensure your
 * include paths include the following (relative to build directory):
 * - _deps/portaudio-src/include
 * - _deps/rtmidi-src
 */
#include "midi_handler.cpp"
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

PYBIND11_MODULE(chordcoach_hw, m) {
  m.doc() = "ChordCoach Hardware Layer C++ Extensions";

  // gil_scoped_release on every call that can touch WinMM/CoreMIDI: a
  // blocked driver call (zombie device-list handle) must never freeze the
  // Python interpreter — with the GIL held it would hang the entire app,
  // including the UI thread. setCallback keeps the GIL (stores a callable).
  py::class_<MidiHandler>(m, "MidiHandler")
      .def(py::init<>(), py::call_guard<py::gil_scoped_release>())
      .def("openPort", &MidiHandler::openPort,
           py::call_guard<py::gil_scoped_release>())
      .def("closePort", &MidiHandler::closePort,
           py::call_guard<py::gil_scoped_release>())
      .def("getPortNames", &MidiHandler::getPortNames,
           py::call_guard<py::gil_scoped_release>())
      .def("setCallback", &MidiHandler::setCallback)
      .def("setIgnoreTypes", &MidiHandler::setIgnoreTypes,
           py::call_guard<py::gil_scoped_release>());
}
