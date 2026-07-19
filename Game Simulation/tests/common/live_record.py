from __future__ import annotations

from pathlib import Path

from tests.common.game_models import model_for_target
from tests.common.maps import write_text_map
from tests.common.traces import (
    P1_BOOST,
    P1_LEFT,
    P1_RIGHT,
    P2_BOOST,
    P2_LEFT,
    P2_RIGHT,
    write_trace,
)


WALL_COLOR = (70, 70, 70)
WHITE = (235, 235, 235)

# Same six colours as the HDL lobby palette (color_rgb in the 2x1 top).
PALETTE = [
    ("red", (255, 60, 60)),
    ("green", (60, 220, 60)),
    ("blue", (70, 140, 255)),
    ("yellow", (235, 235, 60)),
    ("cyan", (60, 220, 220)),
    ("magenta", (235, 60, 235)),
]


def wall_thickness_px(target: str, frame_w: int) -> int:
    if target == "1x1-minimal":
        return 4 if frame_w == 64 else 8
    return 1 if frame_w == 64 else 8


WINDOW_SIZE = (960, 720)


def record_live_trace(target: str, trace_path: str | Path, *, frames: int | None = None,
                      fps: int = 30,
                      preview_map_path: str | Path | None = None,
                      frame_w: int = 640, frame_h: int = 480) -> Path:
    try:
        import pygame
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Live play recording needs pygame in this Python environment.\n"
            "In WSL, install it with:\n"
            "  /root/.venvs/cocotb/bin/python -m pip install pygame"
        ) from exc

    if frames is None:
        frames = 300 if frame_w == 64 else 6000

    pygame.init()
    # Fixed, normal-sized window; the game surface (whatever its resolution)
    # is scaled to fit. Full-res frames use smoothscale for a cleaner look,
    # the coarse 64x48 grid keeps crisp nearest-neighbour pixels.
    screen = pygame.display.set_mode(WINDOW_SIZE)
    pygame.display.set_caption(f"Achtung live trace recorder - {target} {frame_w}x{frame_h}")
    clock = pygame.time.Clock()

    model = model_for_target(target, width=frame_w, height=frame_h)
    recorded: list[int] = []
    pending_buttons = 0
    running = True

    is_2x1 = target == "1x2-working-game"
    p1_color = WHITE
    p2_color = WHITE

    # The arena is drawn once on an unscaled surface; each frame only the
    # freshly painted trail pixels (model.take_dirty) are added, so full
    # 640x480 play stays fast — the map comes straight from the model's
    # framebuffer memory, no display/RAM readback logic involved.
    base = pygame.Surface((frame_w, frame_h)).convert()
    wall = wall_thickness_px(target, frame_w)
    scaler = pygame.transform.scale if frame_w == 64 else pygame.transform.smoothscale

    # Boost display, like the real hardware *looks*: the HDL flashes the
    # boosting player's trail between its colour and the inverted colour every
    # frame at 60Hz, which the eye blends into white. At the recorder's 30fps
    # that flicker is visible instead, so render the perceived effect: the
    # trail shows steady white while boost is held.
    flash = {}
    if is_2x1:
        for value in (1, 2):
            surface = pygame.Surface((frame_w, frame_h)).convert()
            surface.fill((0, 0, 0))
            surface.set_colorkey((0, 0, 0))
            flash[value] = surface

    def draw_border(color) -> None:
        pygame.draw.rect(base, color, (0, 0, frame_w, frame_h), wall)

    def trail_color(value: int):
        if not is_2x1:
            return WHITE
        return p1_color if value == 1 else p2_color

    def present(lines: list[str] | None = None, overlays=()) -> None:
        frame = base
        if overlays:
            frame = base.copy()
            for overlay in overlays:
                frame.blit(overlay, (0, 0))
        screen.blit(scaler(frame, screen.get_size()), (0, 0))
        if lines:
            font = pygame.font.SysFont(None, 30)
            for index, line in enumerate(lines):
                screen.blit(font.render(line, True, (255, 255, 0)), (10, 10 + 26 * index))
        pygame.display.flip()

    def abort(event) -> None:
        detail = pygame.event.event_name(event.type)
        if event.type == pygame.KEYDOWN:
            detail += f" key={pygame.key.name(event.key)}"
        pygame.quit()
        raise SystemExit(f"Live recording aborted before start (got {detail}).")

    base.fill((0, 0, 0))
    draw_border(WHITE if is_2x1 else WALL_COLOR)

    print("Recorder window is open (check the taskbar if you don't see it).", flush=True)

    if is_2x1:
        p1_color, p2_color = run_lobby(pygame, screen, clock, frame_w, frame_h, abort)
        base.fill((0, 0, 0))
        draw_border(WHITE)
    else:
        # Start gate: recording begins only once the window is focused and the
        # player presses a key, so the round can't start behind other windows.
        waiting = True
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (
                    event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q)
                ):
                    abort(event)
                if event.type == pygame.KEYDOWN:
                    waiting = False
            present(["Click window, then press any key to start"])
            clock.tick(30)

    while running and len(recorded) < frames and not getattr(model, "game_over", False):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False

        buttons = current_buttons(pygame.key.get_pressed(), pygame)
        model.step(pending_buttons)
        pending_buttons = buttons
        recorded.append(buttons)

        for x, y, width, height, value in model.take_dirty():
            pygame.draw.rect(base, trail_color(value), (x, y, width, height))
            if is_2x1:
                pygame.draw.rect(flash[value], (255, 255, 255), (x, y, width, height))

        overlays = []
        if is_2x1:
            if buttons & P1_BOOST:
                overlays.append(flash[1])
            if buttons & P2_BOOST:
                overlays.append(flash[2])
        present(overlays=overlays)
        clock.tick(fps)

    if is_2x1 and getattr(model, "game_over", False):
        # Match the real game: the arena border takes the winner's colour
        # (white for a draw).
        if model.p1_alive:
            draw_border(p1_color)
        elif model.p2_alive:
            draw_border(p2_color)
        else:
            draw_border(WHITE)
        present(["Game over"])
        pygame.time.wait(1500)

    pygame.quit()

    out_path = write_trace(trace_path, recorded, frame_w=frame_w, frame_h=frame_h)
    if preview_map_path is not None:
        write_text_map(model.text_map(), preview_map_path,
                       f"Achtung {target} live preview {frame_w}x{frame_h}")
    print(f"Recorded {len(recorded)} frames to {out_path}")
    return out_path


def run_lobby(pygame, screen, clock, frame_w, frame_h, abort):
    """Colour-pick lobby mirroring the HDL flow: move over the 3x2 palette,
    lock with the boost key (A button on the pad), unlock with S/Down, and a
    single Start (Enter) begins once both players locked a colour."""
    pick = [0, 1]
    locked = [False, False]

    swatch_w = screen.get_width() // 5
    swatch_h = screen.get_height() // 5
    grid_x = screen.get_width() // 2 - int(1.5 * swatch_w)
    grid_y = screen.get_height() // 2 - swatch_h

    def cell_rect(color_id):
        return (grid_x + (color_id % 3) * swatch_w,
                grid_y + (color_id // 3) * swatch_h,
                swatch_w - 6, swatch_h - 6)

    def move(player, step):
        if not locked[player]:
            pick[player] = (pick[player] + step) % 6

    def lock(player):
        other = 1 - player
        if locked[other] and pick[player] == pick[other]:
            return  # colour already taken, same rule as the HDL lobby
        locked[player] = True

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (
                event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q)
            ):
                abort(event)
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_a:
                    move(0, -1)
                elif event.key == pygame.K_d:
                    move(0, 1)
                elif event.key == pygame.K_w:
                    lock(0)
                elif event.key == pygame.K_s:
                    locked[0] = False
                elif event.key == pygame.K_LEFT:
                    move(1, -1)
                elif event.key == pygame.K_RIGHT:
                    move(1, 1)
                elif event.key == pygame.K_UP:
                    lock(1)
                elif event.key == pygame.K_DOWN:
                    locked[1] = False
                elif event.key == pygame.K_RETURN and locked[0] and locked[1]:
                    return PALETTE[pick[0]][1], PALETTE[pick[1]][1]

        screen.fill((0, 0, 0))
        # Side bars appear once a player locks, like the HDL lobby.
        if locked[0]:
            pygame.draw.rect(screen, PALETTE[pick[0]][1],
                             (0, 0, screen.get_width() // 40, screen.get_height()))
        if locked[1]:
            pygame.draw.rect(screen, PALETTE[pick[1]][1],
                             (screen.get_width() - screen.get_width() // 40, 0,
                              screen.get_width() // 40, screen.get_height()))
        for color_id, (_, rgb) in enumerate(PALETTE):
            pygame.draw.rect(screen, rgb, cell_rect(color_id))
        # White box = hover cursor; black box = locked colour (HDL style).
        for player in (0, 1):
            if locked[player]:
                pygame.draw.rect(screen, (0, 0, 0), cell_rect(pick[player]), 4)
            else:
                pygame.draw.rect(screen, (255, 255, 255), cell_rect(pick[player]), 4)

        font = pygame.font.SysFont(None, 30)
        for index, line in enumerate((
            "LOBBY  -  P1: A/D move, W lock, S unlock",
            "          P2: arrows move, Up lock, Down unlock",
            "Both lock, then Enter to start   (in game: W / Up = boost)",
        )):
            screen.blit(font.render(line, True, (255, 255, 0)), (10, 10 + 26 * index))
        pygame.display.flip()
        clock.tick(30)


def current_buttons(keys, pygame) -> int:
    mask = 0
    if keys[pygame.K_a]:
        mask |= P1_LEFT
    if keys[pygame.K_d]:
        mask |= P1_RIGHT
    if keys[pygame.K_LEFT]:
        mask |= P2_LEFT
    if keys[pygame.K_RIGHT]:
        mask |= P2_RIGHT
    if keys[pygame.K_w]:
        mask |= P1_BOOST
    if keys[pygame.K_UP]:
        mask |= P2_BOOST
    return mask
