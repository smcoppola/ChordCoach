pybind11_add_module(chordcoach_hw
    src/midi_handler.cpp
    src/audio_handler.cpp
    src/pybindings.cpp
)

# Include directories
target_include_directories(chordcoach_hw PRIVATE include)

# Link with dependencies
target_link_libraries(chordcoach_hw PRIVATE rtmidi portaudio)
