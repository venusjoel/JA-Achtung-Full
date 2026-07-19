# JA Achtung Full — 1x2

This repository is the standalone two-tile version of our two-player
*Achtung, die Kurve!* hardware game for Tiny Tapeout. It uses 64-direction
movement, boost, passable trail gaps, a color-selection lobby, a 2-bit
external QSPI PSRAM framebuffer, and direct 640×480 VGA.

The Tiny Tapeout project is entirely at the repository root:

- `src/`: exact 1x2 HDL and LibreLane configuration
- `info.yaml`: 1x2 project metadata and pinout
- `docs/info.md`: datasheet source
- `test/`: root RTL and gate-level pin smoke tests
- `Game Simulation/tests/game_2x1/`: 1x2 VGA, game-model, and system tests
- `targets/1x2-working-game/`: byte-for-byte canonical mirror used by CI

The simulation folder retains its historical `game_2x1` name; the official
Tiny Tapeout footprint in `info.yaml` is `1x2`.

## Validation baseline

The exact HDL and configuration in this project were validated with LibreLane
3.0.3 and sky130A PDK revision `8afc8346`:

- standard-cell area: 31,142.4 µm²
- final utilization: 90.9124%
- worst setup slack: +0.57704 ns
- worst hold slack: +0.03362 ns
- setup, hold, routing DRC, Magic DRC, LVS, and antenna violations: 0
- Tiny Tapeout precheck: 15/15 passed
- powered gate-level QSPI/VGA smoke test: passed

The full 1x2 verification covers a real 640×480 VGA frame, 23 full game
traces, 24 coarse traces, collision and gap behavior, gamepad input, QSPI
traffic, and arbitration.

## Local tests

```sh
python "Game Simulation/tests/game_2x1/run.py" --test all --rebuild
python "Game Simulation/tests/ram/run.py" --target 1x2-working-game --rebuild
cd test && make -B
```

The framebuffer is external. Hardware use requires a compatible QSPI PSRAM,
the Tiny Tapeout VGA PMOD, and the Gamepad PMOD. See `docs/info.md` for the
power-up sequence and pinout.
