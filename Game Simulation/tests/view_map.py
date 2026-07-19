"""Show a captured text framebuffer map in a pygame window (Windows side).

Usage:
  python tests/view_map.py game_2x1
  python tests/view_map.py path/to/map.txt     any map file
  ... [--seconds N]                            auto-close after N seconds

TAB toggles captured <-> expected (when next to each other), Q/Esc closes.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

COLORS = {
    ".": (0, 0, 0),
    "#": (235, 235, 235),
    "1": (255, 60, 60),
    "2": (70, 140, 255),
    "?": (150, 150, 150),
}
WINDOW_SIZE = (960, 720)


def find_map(arg: str) -> Path:
    path = Path(arg)
    if path.exists():
        return path
    candidates = sorted((HERE / "out" / arg / "vga").glob("*/captured_map.txt"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise SystemExit(f"No captured VGA map for {arg!r}; run --test vga first.")
    return candidates[0]


def load_surface(pygame, path: Path):
    lines = path.read_text().splitlines()
    title, rows = lines[0], [line for line in lines[1:] if line]
    height = len(rows)
    width = max(len(row) for row in rows)
    surface = pygame.Surface((width, height))
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            surface.set_at((x, y), COLORS.get(char, (150, 150, 150)))
    return title, surface.convert(), width


def main() -> int:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    seconds = None
    if "--seconds" in sys.argv:
        seconds = float(sys.argv[sys.argv.index("--seconds") + 1])

    captured_path = find_map(args[0] if args else "game_2x1")
    expected_path = captured_path.with_name("expected_map.txt")

    import pygame
    pygame.init()
    screen = pygame.display.set_mode(WINDOW_SIZE)
    clock = pygame.time.Clock()

    views = [load_surface(pygame, captured_path)]
    if expected_path.exists():
        views.append(load_surface(pygame, expected_path))
    current = 0

    start = time.time()
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (
                event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q)
            ):
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
                current = (current + 1) % len(views)
        if seconds is not None and time.time() - start > seconds:
            running = False

        title, surface, width = views[current]
        scaler = pygame.transform.scale if width <= 64 else pygame.transform.smoothscale
        pygame.display.set_caption(f"{title}  (TAB: captured/expected, Q: close)")
        screen.blit(scaler(surface, screen.get_size()), (0, 0))
        font = pygame.font.SysFont(None, 26)
        screen.blit(font.render(title, True, (255, 255, 0)), (8, 8))
        pygame.display.flip()
        clock.tick(30)

    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
