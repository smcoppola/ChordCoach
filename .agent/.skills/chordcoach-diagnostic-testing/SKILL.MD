---
name: chordcoach-diagnostic-testing
description: Defines the testing and logging philosophy for ChordCoach Companion's lesson flows and AI interactions. Use when writing test scripts, debugging the learning loop, or evaluating the quality of Gemini's feedback.
---
# ChordCoach Diagnostic Testing Skill
When generating or executing tests for the lesson flow and AI feedback loop, avoid standard binary (pass/fail) testing frameworks. Instead, build diagnostic suites designed to generate comprehensive logs for later review.

## Testing & Logging Directives
1. **No Binary Assertions:** Do not write `assert` statements that determine if a lesson flow "passed" or "failed." The subjective nature of adult learning and AI feedback cannot be reliably evaluated with strict boolean logic.
2. **Verbose Diagnostic Logging:** All test scripts must output highly detailed, structured logs. Ensure the following data points are captured in every test run:
    * **Timestamps & Latency:** Exact timing of the simulated MIDI input, the dispatch to the Gemini API, and the receipt of the response.
    * **Raw Inputs/Outputs:** The exact prompt constructed by the Python layer and the raw, unedited string returned by Gemini.
    * **State Changes:** Any internal state updates to the user's lesson progress or pacing variables.
3. **Agent Review Protocol:** When a test suite finishes, read the generated log files. Analyze the outputs to identify:
    * Logical breaks in the lesson flow.
    * Inappropriate or poorly paced feedback for adult learners.
    * Unexpected delays or blocking operations on the main thread.

## Implementation Notes
- Format the output logs in JSON or structured text so they are easily readable by both human developers and agents.
- Ensure the logging mechanism writes to a designated `/logs/diagnostics/` directory within the workspace, appending a unique timestamp to each run.