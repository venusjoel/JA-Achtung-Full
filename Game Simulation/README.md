# 1x2 game verification

The maintained 1x2 simulation suite is in `tests/game_2x1`. The folder keeps
its historical name, while the physical Tiny Tapeout footprint is `1x2`. The
suite compares the validated target HDL against an independent Python
game/framebuffer model and exercises VGA, QSPI PSRAM, gamepad, and arbitration.

Run from the repository root:

```sh
python "Game Simulation/tests/game_2x1/run.py" --test all --rebuild
python "Game Simulation/tests/ram/run.py" --target 1x2-working-game --rebuild
```

Generated output is written below `Game Simulation/tests/out/` and is ignored
by Git. The committed coarse and full traces are deterministic test inputs.
