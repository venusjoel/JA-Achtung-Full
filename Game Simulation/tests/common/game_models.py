from __future__ import annotations

from dataclasses import dataclass

from .maps import frame_bytes_1x1, frame_bytes_2x1, map_1x1, map_2x1, row_stride_1x1
from .traces import P1_BOOST, P1_LEFT, P1_RIGHT, P2_BOOST, P2_LEFT, P2_RIGHT


BASE_TRIG = [
    (64, 0), (64, 6), (63, 12), (61, 19),
    (59, 24), (56, 30), (53, 36), (49, 41),
    (45, 45), (41, 49), (36, 53), (30, 56),
    (24, 59), (19, 61), (12, 63), (6, 64),
]


@dataclass
class Compact1x1Model:
    width: int = 64
    height: int = 48
    start1_x: int = 10
    start2_x: int = 53
    start_y: int = 24

    def __post_init__(self) -> None:
        self.mem = bytearray(frame_bytes_1x1(self.width, self.height))
        self.cell_w = self.width // 4
        self.cell_h = self.height // 4
        self.wall_t = 1 if self.width == 64 else 2
        self.wall_max_x = self.cell_w - self.wall_t
        self.wall_max_y = self.cell_h - self.wall_t
        self.p1_x = self.start1_x >> 2
        self.p1_y = self.start_y >> 2
        self.p2_x = self.start2_x >> 2
        self.p2_y = self.start_y >> 2
        self.p1_dir = 0
        self.p2_dir = 2
        self.p1_turn_prev = False
        self.p2_turn_prev = False
        self.p1_alive = True
        self.p2_alive = True
        self.death_player: str | None = None
        self.death_reason: str | None = None
        # The compact framebuffer stores only occupancy. Keep ownership in the
        # reference model so semantic fixtures can distinguish a player's own
        # trail from the opponent's trail.
        self._pixel_owner: dict[tuple[int, int, int], int] = {}
        self.idle_paint_row = 0
        self.game_over = False
        # Pixels painted since the last take_dirty(), as (x, y, w, h, value)
        # rects, so a live viewer can redraw incrementally at full resolution.
        self.dirty: list[tuple[int, int, int, int, int]] = []

    def take_dirty(self) -> list[tuple[int, int, int, int, int]]:
        dirty, self.dirty = self.dirty, []
        return dirty

    def step(self, buttons: int) -> None:
        if self.game_over:
            return
        if self.idle_paint_row != 3:
            self.idle_paint_row += 1
            return

        self.idle_paint_row = 0
        self._move_player(0, bool(buttons & P1_LEFT), bool(buttons & P1_RIGHT))
        if not self.game_over:
            self._move_player(1, bool(buttons & P2_LEFT), bool(buttons & P2_RIGHT))

    def text_map(self) -> list[str]:
        return map_1x1(self.mem, self.width, self.height)

    def _move_player(self, player: int, left: bool, right: bool) -> None:
        if player == 0:
            if (left or right) and not self.p1_turn_prev:
                self.p1_dir = (self.p1_dir + (1 if right else -1)) & 0x3
            self.p1_turn_prev = left or right
            x, y, direction = self.p1_x, self.p1_y, self.p1_dir
        else:
            if (left or right) and not self.p2_turn_prev:
                self.p2_dir = (self.p2_dir + (1 if right else -1)) & 0x3
            self.p2_turn_prev = left or right
            x, y, direction = self.p2_x, self.p2_y, self.p2_dir

        next_x = x + (1 if direction == 0 else -1 if direction == 2 else 0)
        next_y = y + (1 if direction == 1 else -1 if direction == 3 else 0)
        if (
            next_x < self.wall_t or next_x >= self.wall_max_x or
            next_y < self.wall_t or next_y >= self.wall_max_y
        ):
            self._record_death(player, "wall")
            return

        for paint_row in range(4):
            if self._get_cell_pixel(next_x, next_y, paint_row):
                owner = self._pixel_owner.get((next_x, next_y, paint_row))
                self._record_death(
                    player, "self" if owner == player else "opponent")
                return

            p2_groove_cell = bool((next_x & 1) ^ (next_y & 1))
            paint_this_row = player == 0 or not p2_groove_cell or paint_row == 0
            if paint_this_row:
                self._set_cell_pixel(next_x, next_y, paint_row, player)

        if player == 0:
            self.p1_x, self.p1_y = next_x, next_y
        else:
            self.p2_x, self.p2_y = next_x, next_y

    def _byte_bit_for_cell(self, cell_x: int, cell_y: int, paint_row: int) -> tuple[int, int]:
        target_y = (cell_y << 2) + paint_row
        byte_index = target_y * row_stride_1x1(self.width) + (cell_x >> 3)
        return byte_index, cell_x & 0x7

    def _get_cell_pixel(self, cell_x: int, cell_y: int, paint_row: int) -> int:
        byte_index, bit = self._byte_bit_for_cell(cell_x, cell_y, paint_row)
        return (self.mem[byte_index] >> bit) & 1

    def _set_cell_pixel(self, cell_x: int, cell_y: int, paint_row: int,
                        player: int) -> None:
        byte_index, bit = self._byte_bit_for_cell(cell_x, cell_y, paint_row)
        self.mem[byte_index] |= 1 << bit
        self._pixel_owner[(cell_x, cell_y, paint_row)] = player
        self.dirty.append((cell_x * 4, (cell_y << 2) + paint_row, 4, 1, 1))

    def _record_death(self, player: int, reason: str) -> None:
        if self.death_player is None:
            self.death_player = "p1" if player == 0 else "p2"
            self.death_reason = reason
        if player == 0:
            self.p1_alive = False
        else:
            self.p2_alive = False
        self.game_over = True


@dataclass
class Curved2x1Model:
    width: int = 64
    height: int = 48
    start1_x: int = 10
    start2_x: int = 53
    start_y: int = 24

    def __post_init__(self) -> None:
        self.mem = bytearray(frame_bytes_2x1(self.width, self.height))
        self.wall_t = 1 if self.width == 64 else 8
        self.wall_max_x = self.width - self.wall_t
        self.wall_max_y = self.height - self.wall_t
        self.p1_x_fp = self.start1_x << 6
        self.p1_y_fp = self.start_y << 6
        self.p2_x_fp = self.start2_x << 6
        self.p2_y_fp = self.start_y << 6
        self.p1_angle = 0
        self.p2_angle = 32
        self.p1_alive = True
        self.p2_alive = True
        self.death_player: str | None = None
        self.death_reason: str | None = None
        self.turn_phase = False
        self.game_over = False
        # Per-player trail-distance counters mirror the HDL. P2 starts half a
        # period ahead so the players' first gaps are phase shifted.
        self.p1_gap_counter = 0
        self.p2_gap_counter = 128
        # Pixels painted since the last take_dirty(), as (x, y, w, h, value)
        # rects, so a live viewer can redraw incrementally at full resolution.
        self.dirty: list[tuple[int, int, int, int, int]] = []

    def take_dirty(self) -> list[tuple[int, int, int, int, int]]:
        dirty, self.dirty = self.dirty, []
        return dirty

    def step(self, buttons: int) -> None:
        if self.game_over:
            return

        self.turn_phase = not self.turn_phase
        if self.p1_alive:
            self._run_player_until_done(0, buttons)
        if not self.game_over and self.p2_alive:
            self._run_player_until_done(1, buttons)
        if not self.p1_alive or not self.p2_alive:
            self.game_over = True

    def text_map(self) -> list[str]:
        return map_2x1(self.mem, self.width, self.height)

    def _gap_active(self, player: int) -> bool:
        counter = self.p1_gap_counter if player == 0 else self.p2_gap_counter
        return counter >= 224

    def _advance_gap_counter(self, player: int) -> None:
        if player == 0:
            self.p1_gap_counter = (self.p1_gap_counter + 1) & 0xFF
        else:
            self.p2_gap_counter = (self.p2_gap_counter + 1) & 0xFF

    def _run_player_until_done(self, player: int, buttons: int) -> None:
        boost_used = False
        while True:
            again = self._move_player(player, buttons, boost_used)
            if not again:
                return
            boost_used = True

    def _move_player(self, player: int, buttons: int, boost_used: bool) -> bool:
        left = bool(buttons & (P1_LEFT if player == 0 else P2_LEFT))
        right = bool(buttons & (P1_RIGHT if player == 0 else P2_RIGHT))
        # Boost (A on the gamepad) grants one extra move per frame while the
        # other player is still alive, exactly like the HDL boost path.
        boost = bool(buttons & (P1_BOOST if player == 0 else P2_BOOST))

        if self.turn_phase and left and not right:
            if player == 0:
                self.p1_angle = (self.p1_angle - 1) & 0x3F
            else:
                self.p2_angle = (self.p2_angle - 1) & 0x3F
        elif self.turn_phase and right and not left:
            if player == 0:
                self.p1_angle = (self.p1_angle + 1) & 0x3F
            else:
                self.p2_angle = (self.p2_angle + 1) & 0x3F

        x_fp, y_fp, angle = self._player_state(player)
        dx, dy = angle_vector(angle)
        next_x_fp = x_fp + dx
        next_y_fp = y_fp + dy
        next_x = next_x_fp >> 6
        next_y = next_y_fp >> 6
        draw_x = x_fp >> 6
        draw_y = y_fp >> 6

        if self._hits_wall(next_x, next_y):
            self._kill(player, "wall")
            if player == 0 and self.p2_alive:
                return False
            self.game_over = True
            return False

        if next_x == draw_x and next_y == draw_y:
            self._commit_player(player, next_x_fp, next_y_fp)
            return boost and not boost_used and self._other_alive(player)

        targets = []
        if next_x != draw_x and next_y != draw_y:
            targets.append((next_x, draw_y))
        targets.append((next_x, next_y))

        for target_x, target_y in targets:
            pixel = self._get_pixel(target_x, target_y)
            if pixel != 0:
                self._kill(
                    player, "self" if pixel == player + 1 else "opponent")
                if player == 0 and self.p2_alive:
                    return False
                if (
                    player == 1 and self.p1_alive and pixel == 1 and
                    target_x == (self.p1_x_fp >> 6) and target_y == (self.p1_y_fp >> 6)
                ):
                    self._kill(0, "opponent")
                self.game_over = True
                return False
            if not self._gap_active(player):
                self._set_pixel(target_x, target_y, 1 if player == 0 else 2)
            self._advance_gap_counter(player)

        self._commit_player(player, next_x_fp, next_y_fp)
        if player == 1 and not self.p1_alive:
            self.game_over = True
        return boost and not boost_used and self._other_alive(player)

    def _player_state(self, player: int) -> tuple[int, int, int]:
        if player == 0:
            return self.p1_x_fp, self.p1_y_fp, self.p1_angle
        return self.p2_x_fp, self.p2_y_fp, self.p2_angle

    def _commit_player(self, player: int, x_fp: int, y_fp: int) -> None:
        if player == 0:
            self.p1_x_fp = x_fp & 0xFFFF
            self.p1_y_fp = y_fp & 0x7FFF
        else:
            self.p2_x_fp = x_fp & 0xFFFF
            self.p2_y_fp = y_fp & 0x7FFF

    def _kill(self, player: int, reason: str) -> None:
        if self.death_player is None:
            self.death_player = "p1" if player == 0 else "p2"
            self.death_reason = reason
        if player == 0:
            self.p1_alive = False
        else:
            self.p2_alive = False

    def _other_alive(self, player: int) -> bool:
        return self.p2_alive if player == 0 else self.p1_alive

    def _hits_wall(self, x: int, y: int) -> bool:
        return x < self.wall_t or x >= self.wall_max_x or y < self.wall_t or y >= self.wall_max_y

    def _get_pixel(self, x: int, y: int) -> int:
        byte_index = (y * self.width + x) >> 2
        shift = (x & 0x3) << 1
        return (self.mem[byte_index] >> shift) & 0x3

    def _set_pixel(self, x: int, y: int, value: int) -> None:
        byte_index = (y * self.width + x) >> 2
        shift = (x & 0x3) << 1
        self.mem[byte_index] &= ~(0x3 << shift)
        self.mem[byte_index] |= (value & 0x3) << shift
        self.dirty.append((x, y, 1, 1, value))


def angle_vector(angle: int) -> tuple[int, int]:
    base_c, base_s = BASE_TRIG[angle & 0xF]
    quadrant = (angle >> 4) & 0x3
    if quadrant == 0:
        return base_c, base_s
    if quadrant == 1:
        return -base_s, base_c
    if quadrant == 2:
        return -base_c, -base_s
    return base_s, -base_c


def model_for_target(target: str, width: int = 64, height: int = 48):
    if width == 64:
        start1_x, start2_x, start_y = 10, 53, 24
    else:
        start1_x, start2_x, start_y = 100, 540, 240

    if target == "1x1-minimal":
        return Compact1x1Model(width=width, height=height, start1_x=start1_x, start2_x=start2_x, start_y=start_y)
    if target == "1x2-working-game":
        return Curved2x1Model(width=width, height=height, start1_x=start1_x, start2_x=start2_x, start_y=start_y)
    raise ValueError(f"Unknown target {target!r}")
