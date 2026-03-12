---
name: chordcoach-safe-testing-policy
description: Enforces a strict read-only execution policy when running tests. Use whenever executing test suites, debugging failures, or analyzing logs for ChordCoach Companion.
---
# ChordCoach Safe Testing Policy
When asked to run tests, evaluate logs, or debug the C++/Python application, you must operate in a strict read-only capacity. Your goal is to identify issues and propose solutions, not to implement them.

## Rules of Engagement
1. **Zero Code Modifications:** Under no circumstances should you edit, delete, or create any source code files (`.cpp`, `.h`, `.py`, etc.) during a testing or debugging session. 
2. **Read-Only Execution:** You may execute test scripts in the terminal and read the output logs, but you must not attempt to automatically fix failing tests.
3. **Analyze and Report:** When an issue is found—whether it's a C++ memory leak, a Python latency spike, or a logical flaw in the Gemini lesson flow—stop and write a detailed bug report. 

## Action Plan Generation
Instead of writing code to fix a discovered issue, you must generate an Action Plan. 
- Create a markdown Artifact detailing the root cause of the bug.
- Outline the exact files and lines of code that need to be changed.
- Provide the proposed code changes as snippets within the Artifact for the user to review.
- Wait for the user to explicitly approve the plan or make the changes themselves.