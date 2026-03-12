---
name: chordcoach-cpp-python-bridge
description: Manages the interoperability between the C++ audio/MIDI engine and the Python AI learning logic for ChordCoach Companion. Use when writing cross-language bindings, debugging memory sharing, or managing build pipelines.
---
# ChordCoach C++/Python Bridge Skill
When assisting with the core architecture of the app, enforce strict separation of concerns between the high-performance audio engine and the educational AI logic.

## Architecture Guidelines
1. **C++ for Performance:** All low-latency MIDI parsing, buffer management, and realtime I/O must remain exclusively in C++.
2. **Python for AI:** The AI-driven pacing and feedback models designed for adult learners must reside in Python.
3. **Data Passing:** When handling cross-language bindings, ensure that live MIDI structs are passed by reference to avoid copying overhead that could introduce audio stuttering.

## How to Handle Changes
- If modifying the Python AI logic, ensure it runs asynchronously so it never blocks the C++ audio thread.
- Always check cross-platform compatibility for Windows and MacOS build targets when updating CMake configurations or build pipelines.