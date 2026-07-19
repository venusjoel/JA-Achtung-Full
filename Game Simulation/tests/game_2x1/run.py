"""Test runner for the 2x1 (two-tile 1x2-working-game) target.

Examples (from the repo root, inside the WSL cocotb venv):

  python "Game Simulation/tests/game_2x1/run.py" --gen        regenerate traces
  python "Game Simulation/tests/game_2x1/run.py" --test vga   lined picture over real PSRAM+VGA
  python "Game Simulation/tests/game_2x1/run.py" --test vga --full-vga
  python "Game Simulation/tests/game_2x1/run.py" --test game --trace 05_p1_box
  python "Game Simulation/tests/game_2x1/run.py" --test game --mode full --trace 20_fuzz
  python "Game Simulation/tests/game_2x1/run.py" --test suite
  python "Game Simulation/tests/game_2x1/run.py" --test live  play pygame, then HDL compare
  python "Game Simulation/tests/game_2x1/run.py"              vga + coarse suite + full subset
"""

from __future__ import annotations

import sys
from pathlib import Path

# "Game Simulation" is the tests package root (tests.* imports resolve there).
PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from tests.common.target_runner import TargetSpec, main

SPEC = TargetSpec(
    key="2x1",
    target="1x2-working-game",
    folder="game_2x1",
    test_module="tests.game_2x1.cocotb_game_direct",
)

if __name__ == "__main__":
    raise SystemExit(main(SPEC))
