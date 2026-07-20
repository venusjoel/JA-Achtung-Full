# Canonical 1x2 target mirror

This directory is a byte-for-byte mirror of the standalone root `src/` and
`info.yaml`. CI checks the mirror before RTL tests and hardening so the game
tests, root Tiny Tapeout project, and validated physical configuration cannot
silently diverge.

Validated LibreLane 3.0.3 result: 31,468.9 µm² standard-cell area, 91.8657%
utilization, +1.55711 ns setup slack, +0.03365 ns hold slack, and zero hard
signoff violations.
