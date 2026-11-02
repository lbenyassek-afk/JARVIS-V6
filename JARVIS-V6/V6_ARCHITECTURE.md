# JARVIS V6 architecture

V6 uses five boundaries. The interface never performs network, microphone,
encryption or desktop work synchronously. The intelligence layer selects Gemini
or the bounded local core. The memory layer owns encrypted categorized data and
retrieval budgets. The operation layer validates every plan against registered
actions and backend permissions. The integration layer exposes only declared
plugin adapters and an authenticated companion inbox.

## Stable-release gates

1. UI event-loop stalls remain below 100 ms during normal interaction.
2. Every desktop action has allowlist, permission, cancellation and audit tests.
3. Gemini setup distinguishes network, credential, access, quota and model errors.
4. Voice capture, transcription, interruption, synthesis and fallback pass on Windows.
5. Memory edits, deletion, backup, recovery and V5 import preserve user control.
6. Companion and plugin inputs cannot bypass the central permission engine.
7. No secret appears in configuration, logs, prompts, memory or repository history.
