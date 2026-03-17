# Gemini Interface Holistic Overhaul Plan

This plan proposes an overhaul of the WebSocket timing state machine, instruction isolation inside `systemInstruction`, and strict synchronization between Gemini audio concludes vs Server turn-completion messages to fully resolve race conditions during live speech pauses.

## User Review Required
No breaking features anticipated. Redesigns focus under-the-hood framing of asynchronous handshake binds to solve random skips or failsafe locks.

---

## Proposed Changes

### 1. Prompt and System Directives Isolation
Currently, `ChordTrainerService.start_lesson_plan()` blends System templates with user workspace variables and outputs them to AI inside initial user turns.

*   **[MODIFY] `src/logic/services/gemini_service.py`**:
    -   Update `connect_service()` or `setup_msg` to accept a `dynamic_instruction` or dictionary format instead of forcing everything in `base_instruction` inside `_connect_ws()`.
*   **[MODIFY] `src/logic/services/chord_trainer.py`**:
    -   Move dynamic rule templates (e.g. Variety Rule, Safety Rules, Pronunciation setups) into independent static formats passed through to the underlying `GeminiService.setup` packet rather than prepended inside context loads on user turns.

---

### 2. State Machine Coordination & Timing Overhaul
We will replace dispersed boolean flags (`_waiting_for_ai`, `_is_paused_for_speech`, `_is_requesting_exercise`) with a rigid, structured state tracking mechanism to fully lock out race windows (e.g. tool arrival frames passing before audio buffers fill).

*   **[MODIFY] `src/logic/services/chord_trainer.py`**:
    -   Introduce explicit `LessonState` (e.g., `IDLE`, `AWAITING_EXERCISE`, `AI_SPEAKING`, `USER_PLAYING`).
    -   Strictly evaluate note presses **only** when `state == LessonState.USER_PLAYING`.
    -   Unpause/Transitions trigger purely on holistic discrete state switches to decouple raw buffer loop timers from core workout steps.

#### UI Backward Compatibility
To prevent any impact or breakage in QML views (such as `ChordTrainerView.qml` which binds directly to boolean state triggers like `isPausedForSpeech`), `ChordTrainerService` will retain those existing variables as read-only `@Property(bool)` fields that fetch dynamically from the underlying `LessonState` enum. **Zero QML rewrites will be required.**

*   **[MODIFY] `src/logic/services/gemini_service.py`**:
    -   Refactor `_pump_audio` to strictly coordinate `_turn_complete` vs Buffer state framing upfront, providing a clean `isResponseActive` state for the coordinator to feed downstream instead of raw delays.

---

## Verification Plan

### Automated Benchmark Tests
Run the pre-existing diagnostic timing runner heavily before and after applying the core branch.
We will ensure that the overhaul **completely eliminates** or drops to zero the following target issues listed in logs:
1.  **`failsafe_fires`** (Timeout nudge locks)
2.  **`dropped_tool_calls`** (AI speech with missing tool)
3.  **`stuck_locks`** (`_is_requesting_exercise` stuck True)

**Command to run benchmark:**
```bash
# From workspace root
python tests/test_full_lesson_timing.py
```
Compare the generated log files inside `tests/logs/` (e.g. itemizing percentages of dropped callbacks or chaos handling) to ensure absolute stability metrics improve.
