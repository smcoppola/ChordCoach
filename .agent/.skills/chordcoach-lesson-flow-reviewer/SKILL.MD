---
name: chordcoach-lesson-flow-reviewer
description: Executes diagnostic test suites and analyzes the generated logs to evaluate the pedagogical quality, pacing, and logic of the AI's lesson flow. Use when evaluating the learning experience, reviewing Gemini's feedback, or debugging lesson state changes.
---
# ChordCoach Lesson Flow Reviewer
When asked to run tests or review the lesson flow, your role is to act as an observability tool and a pedagogical evaluator for adult piano learners. You are not looking for binary pass/fail conditions; you are looking for qualitative issues in the learning loop.



## Step 1: Execution
1. Trigger the diagnostic test runner. Ensure the environment is configured to hit the live Gemini API. 
2. Verify that no mocking frameworks are active for the Gemini integration.
3. Wait for the test suite to complete and locate the most recent timestamped log file in the `/logs/diagnostics/` directory.

## Step 2: Log Ingestion & Analysis
Read the structured log file and analyze the data across three primary dimensions:

### A. Pedagogical Quality
- **Tone & Clarity:** Review the raw Gemini responses. Is the feedback appropriate, encouraging, and mature enough for an adult learner? 
- **Context Awareness:** Does the AI correctly identify the specific chords or notes that were missed based on the MIDI input logs?
- **Progression Logic:** Did the lesson state advance correctly, or did the flow get stuck in a repetitive loop?

### B. Pacing & Timing
- **Adult Learner Simulation:** Look at the timestamps of the simulated MIDI inputs. If the test simulated a slow, hesitant beginner with frequent pauses, did the AI interrupt too quickly or wait an appropriate amount of time before offering guidance?
- **Response Latency:** Check the time delta between the Python layer sending the prompt and receiving the live Gemini response. Flag any latency spikes that would disrupt a real-time playing experience.

### C. Technical Anomalies
- Look for dropped MIDI events or asynchronous blocking where the Python AI thread may have stalled the C++ audio engine.

## Step 3: Reporting
After analyzing the logs, output a detailed markdown summary of your findings. 
- Highlight specific turns in the conversation where the lesson flow felt disjointed or poorly timed.
- Quote the exact Gemini response and the preceding user input state when pointing out logical flaws.
- Suggest prompt adjustments or state-machine tweaks to improve the identified issues.