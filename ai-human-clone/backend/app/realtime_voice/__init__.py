"""Real-time voice conversations with a clone (Phase 17).

Browser <-> authenticated WebSocket <-> a RealtimeProvider. The implemented provider,
"pipeline", runs each turn through this platform's own speech-to-text, the clone's
normal chat pipeline (prompt, knowledge, approved memories, history) and its voice,
spoken sentence by sentence while the answer streams. Contract: docs/phase17/contract.md.
"""
