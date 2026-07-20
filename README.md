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

- standard-cell area: 31,468.9 µm²
- final utilization: 91.8657%
- worst setup slack: +1.55711 ns
- worst hold slack: +0.03365 ns
- worst-corner max-slew advisories: 259
- worst-corner max-capacitance advisories: 2
- worst-corner max-fanout advisories: 0
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

## Play it live

You can play the game yourself and have the hardware checked against your run.
Use an Ubuntu/WSL terminal in the repo root. The first time on each computer,
run the setup file (it installs/checks Icarus Verilog and creates an isolated,
pinned Python environment):

```sh
./setup-live
```

After that, no environment activation is needed:

```sh
./1x2 --live
```

A window opens on the colour-selection lobby, records your play, then replays
the exact inputs through the Verilog and diffs the hardware output against the
Python model. In the lobby, player 1 moves with `A`/`D`, locks with `W`, and
unlocks with `S`; player 2 uses the arrows, `Up`, and `Down`; press `Enter`
once both players have locked. In game, `A`/`D` steer player 1 and the
left/right arrows steer player 2, with `W` and `Up` for boost; `Esc` or `Q`
ends the recording. Add `--mode coarse` for a quick low-resolution session.

`./1x2` without `--live` runs the full automatic test set. It also forwards every
other runner flag (`--test vga`, `--test suite`, `--gen`, …). These files are
developer conveniences only — no CI workflow uses them and they do not affect
the hardware, the Tiny Tapeout test harness, or GDS signoff.

## DE10-Lite FPGA

The [`fpga/`](fpga/) folder contains a reproducible Intel Quartus project that
builds and programs this exact `src/` RTL on a Terasic DE10-Lite. It also lists
the required VGA, QSPI PSRAM, and Gamepad PMOD wiring.
