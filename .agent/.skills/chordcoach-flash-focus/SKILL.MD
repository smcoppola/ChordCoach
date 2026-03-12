---
name chordcoach-flash-focus
description Keeps the agent focused, concise, and strictly on-task when generating or modifying code. Use this to prevent over-engineering, scope creep, or hallucinated features during active development.
---
# Gemini Flash Focus Protocol

When assisting with active code generation or refactoring for ChordCoach Companion, you must operate with strict tunnel vision on the user's immediate request. Efficiency and adherence to the established architecture are your top priorities.

## Scope & Constraint Rules
1. Strict Task Adherence Only generate or modify code that directly answers the current prompt. Do not proactively refactor neighboring functions, reorganize files, or suggest sweeping architectural changes unless explicitly commanded.
2. Respect the Boundaries Maintain the strict division of labor C++ handles the low-latency audioMIDI engine, and Python handles the AI logic. Do not suggest importing Python-esque conveniences into the C++ engine or vice versa.
3. Audience Context Remember the target demographic is adult learners. Do not suggest or implement code for overly gamified UI elements, child-focused pedagogical logic, or distracting visual features. Keep the logic focused on mature, structured learning.
4. No Premature Optimization Unless the prompt is specifically about fixing a performance bottleneck (e.g., a C++ buffer underrun or a Python thread stalling), prioritize clean, functional, and readable code over micro-optimizations. 

## Interaction Guidelines
- Be Concise Provide brief, direct explanations for the code you write. Omit lengthy tutorials or background information unless specifically asked.
- Cross-Platform Awareness If a generated snippet inherently breaks compatibility between the Windows and Linux build targets, flag it briefly, but do not derail the current task to rewrite CMake files unless instructed.
- Honor Existing Directives Ensure all generated code remains compatible with the established read-only testing policies and the live-API testing mandates. Do not generate code that relies on mocking the Gemini connection.