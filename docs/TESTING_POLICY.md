# Project Policy: No Gemini Mocking

## 🚨 CRITICAL DIRECTIVE

**Under no circumstances should the `GeminiService` or AI interaction loop be mocked in integration or diagnostic tests.**

### Rationale
The core value and complexity of ChordCoach Companion lie in the real-time, bidirectional interaction between the local MIDI/Logic layer and the Gemini Multimodal AI.
Mocking these interactions (e.g., using `unittest.mock.patch` or static `MagicMock` responses) provides a false sense of security and fails to test the most critical failure points:
1. **Latency:** AI response times are variable and must be handled gracefully by the UI/Audio threads.
2. **Context Awareness:** The AI's ability to "see" the user's progress relies on accurate state synchronization which mocks cannot replicate.
3. **Pedagogical Quality:** Gemini's feedback is subjective; tests must facilitate human (agent) review of real responses.
4. **Tool-Call Integrity:** The `set_exercise` protocol between Gemini and the Python layer is sensitive to prompt engineering and version changes in the model.

### Guidelines for Test Authors
1. **Headless Execution is OK:** It is acceptable to mock `QAudioSink` or MIDI hardware to allow tests to run on build servers without speakers or physical pianos.
2. **Live API Requirements:** All flow-based tests require a valid `GOOGLE_API_KEY` in the environment.
3. **Wait for Signals:** Use `QEventLoop` or `app.processEvents()` loops to wait for real `aiStartedSpeaking` and `exerciseReceived` signals rather than manually emitting them.
4. **Diagnostic Logger:** Use the `DiagnosticLogger` class to capture raw prompts and latency data for later review as per the `chordcoach-diagnostic-testing` skill.

### Implementation Status
The following tests have been switched to Live AI only:
- `tests/test_onboarding_flow.py`
- `tests/test_lesson_timing.py`
- `tests/test_full_lesson_timing.py`
- `tests/review_onboarding_flow.py`
