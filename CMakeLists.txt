cmake_minimum_required(VERSION 3.10)
project(ChordCoachHW)

set(CMAKE_CXX_STANDARD 17)

# pybind11 is required for the Python interface
# Try to find pybind11 via Python if find_package fails
if(NOT pybind11_DIR)
    execute_process(
        COMMAND python -c "import pybind11; print(pybind11.get_cmake_dir())"
        OUTPUT_VARIABLE pybind11_DIR
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
endif()
find_package(pybind11 REQUIRED PATHS ${pybind11_DIR} NO_DEFAULT_PATH)

include(FetchContent)

# RtMidi
FetchContent_Declare(
    rtmidi
    GIT_REPOSITORY https://github.com/thestk/rtmidi.git
    GIT_TAG master
)
FetchContent_MakeAvailable(rtmidi)

# PortAudio
FetchContent_Declare(
    portaudio
    GIT_REPOSITORY https://github.com/PortAudio/portaudio.git
    GIT_TAG master
)
FetchContent_MakeAvailable(portaudio)

add_subdirectory(src/hardware)
