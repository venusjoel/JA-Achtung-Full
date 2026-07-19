"""Deterministic trace-suite generator shared by the 1x1 and 2x1 test folders.

Every trace is a JSON button script in the format understood by
tests.common.traces.load_trace. Frame numbers are written against a 64x48 base
schedule, then positions and trace length are scaled 10x for full 640x480.

The 1x1 engine moves one 4-pixel cell every four frames, so its effective
screen speed is still one pixel per frame. Its timeline must not be scaled a
second time; only tap width is held for four frames so the compact sampler
cannot miss it.

Fuzz traces use a seeded RNG so regenerating the suite is reproducible.
"""

from __future__ import annotations

import random
from pathlib import Path

from tests.common.traces import (
    P1_BOOST,
    P1_LEFT,
    P1_RIGHT,
    P2_BOOST,
    P2_LEFT,
    P2_RIGHT,
    write_trace,
)


INPUT_WINDOW = {"1x1": 4, "2x1": 1}
MODE_SCALE = {"coarse": 1, "full": 10}
MODE_SIZE = {"coarse": (64, 48), "full": (640, 480)}
ABSOLUTE_FRAMES = "absolute_frames"

FUZZ_MASKS = (
    P1_LEFT, P1_RIGHT, P2_LEFT, P2_RIGHT,
    P1_LEFT | P2_LEFT, P1_LEFT | P2_RIGHT,
    P1_RIGHT | P2_LEFT, P1_RIGHT | P2_RIGHT,
)

# Only the 2x1 game has boost (gamepad A): mix it into that target's fuzz
# traces so the extra-move HDL path gets fuzzed too.
FUZZ_MASKS_BOOST = FUZZ_MASKS + (
    P1_BOOST, P2_BOOST,
    P1_LEFT | P1_BOOST, P1_RIGHT | P1_BOOST,
    P2_LEFT | P2_BOOST, P2_RIGHT | P2_BOOST,
    P1_BOOST | P2_BOOST,
    P1_RIGHT | P1_BOOST | P2_LEFT | P2_BOOST,
)

BOOST_SPECS = [
    {"name": "22_p1_boost_run", "frames": 60, "events": [(10, 30, P1_BOOST)]},
    {"name": "23_boost_duel", "frames": 80, "events": [
        (10, 40, P1_BOOST | P2_BOOST),
        (12, P1_LEFT | P1_BOOST | P2_BOOST),
        (14, P2_RIGHT | P1_BOOST | P2_BOOST),
    ]},
]


def _named_specs(target_key: str, mode: str) -> list[dict]:
    # Base schedule (2x1 coarse frames). "events" holds (frame, mask) presses
    # and (start, end, mask) holds. Four-item holds explicitly remain in
    # absolute frame units when scaling would change the intended collision.
    if target_key == "1x1":
        # Compact inputs are sampled every four frames. Keep these edges
        # separate so an intended spam test cannot collapse into L+R holds.
        spam_events = [
            (8 * idx, (P1_LEFT | P2_LEFT) if idx % 3 == 0 else
                      (P1_RIGHT | P2_RIGHT))
            for idx in range(10)
        ]
        # Four separated quarter-turn edges close a two-cell square. The
        # fourth edge is essential: with only three, the other player reaches
        # the open trail first and the fixture is not a self-collision.
        p1_self_events = [
            (4, P1_LEFT), (12, P1_LEFT),
            (20, P1_LEFT), (28, P1_LEFT),
        ]
        p2_self_events = [
            (4, P2_RIGHT), (12, P2_RIGHT),
            (20, P2_RIGHT), (28, P2_RIGHT),
        ]
        scenario_08 = {
            "name": "08_p1_self_crash", "frames": 60,
            "events": p1_self_events,
            "expected": {"death_player": "p1", "death_reason": "self",
                         "p1_alive": False, "p2_alive": True},
        }
        scenario_09 = {
            "name": "09_p2_self_crash", "frames": 60,
            "events": p2_self_events,
            "expected": {"death_player": "p2", "death_reason": "self",
                         "p1_alive": True, "p2_alive": False},
        }
    else:
        spam_events = [
            (8 + 2 * idx, P1_LEFT if idx % 2 == 0 else P1_RIGHT)
            for idx in range(20)
        ]
        if mode == "full":
            # At real resolution the curved game has room for a complete
            # orbit. A continuous turn closes the loop at frame 128 while the
            # other player is still alive.
            scenario_08 = {
                "name": "08_p1_self_crash", "frames": 20,
                # P2's breaker move on the crash frame remains in one integer
                # pixel. This also covers the no-pixel game-over path at the
                # real 640x480 geometry.
                "events": [(0, 20, P1_LEFT),
                           (0, 52, P2_LEFT, ABSOLUTE_FRAMES)],
                "expected": {"death_player": "p1", "death_reason": "self",
                             "p1_alive": False, "p2_alive": True},
            }
            scenario_09 = {
                "name": "09_p2_self_crash", "frames": 20,
                "events": [(0, 20, P2_RIGHT)],
                "expected": {"death_player": "p2", "death_reason": "self",
                             "p1_alive": True, "p2_alive": False},
            }
        else:
            # A 64x48 acceleration arena is narrower than the curved game's
            # minimum orbit. Use it to check opponent-trail collisions instead
            # of carrying a misleading coarse "self crash" label.
            scenario_08 = {
                "name": "08_p2_hits_p1_trail", "frames": 60,
                "events": [(4, P1_LEFT), (12, P1_LEFT), (20, P1_LEFT)],
                "expected": {"death_player": "p2", "death_reason": "opponent",
                             "p1_alive": True, "p2_alive": False},
            }
            scenario_09 = {
                "name": "09_p1_hits_p2_trail", "frames": 60,
                "events": [(4, P2_RIGHT), (12, P2_RIGHT), (20, P2_RIGHT)],
                "expected": {"death_player": "p1", "death_reason": "opponent",
                             "p1_alive": False, "p2_alive": True},
            }
    specs = [
        {"name": "01_straight", "frames": 60, "events": []},
        {"name": "02_p1_turn_ccw", "frames": 60, "events": [(16, P1_LEFT)]},
        {"name": "03_p2_turn_cw", "frames": 60, "events": [(16, P2_RIGHT)]},
        {"name": "04_both_turn", "frames": 60,
         "events": [(16, P1_LEFT | P2_LEFT)]},
        {"name": "05_p1_box", "frames": 80,
         "events": [(4, P1_LEFT), (12, P1_LEFT), (20, P1_LEFT), (28, P1_LEFT)]},
        {"name": "06_p1_wall_crash", "frames": 60,
         "events": [(0, 16, P1_LEFT, ABSOLUTE_FRAMES)],
         "expected": {"death_player": "p1", "death_reason": "wall",
                      "p1_alive": False, "p2_alive": True}},
        {"name": "07_p2_wall_crash", "frames": 60,
         "events": [(0, 16, P2_RIGHT, ABSOLUTE_FRAMES)],
         "expected": {"death_player": "p2", "death_reason": "wall",
                      "p1_alive": True, "p2_alive": False}},
        scenario_08,
        scenario_09,
        {"name": "10_head_to_head", "frames": 60, "events": []},
        {"name": "11_hold_button", "frames": 80,
         "events": [(10, 50, P1_LEFT)]},
        {"name": "12_simultaneous_opposites", "frames": 60,
         "events": [(16, 30, P1_LEFT | P1_RIGHT)]},
        {"name": "13_staircase", "frames": 80, "events": [
            (0, P1_LEFT), (8, P1_RIGHT), (16, P1_LEFT), (24, P1_RIGHT),
            (32, P1_LEFT),
        ]},
        {"name": "14_close_miss", "frames": 80,
         "events": [(16, P1_LEFT | P2_RIGHT)]},
        {"name": "15_frame_0_input", "frames": 60, "events": [(0, P1_LEFT)]},
        {"name": "16_spam_inputs", "frames": 80, "events": spam_events},
    ]
    if target_key == "2x1" and mode == "coarse":
        specs.append({
            "name": "24_p1_breaker_subpixel_game_over",
            "frames": 42,
            "events": [(0, 10, P2_RIGHT, ABSOLUTE_FRAMES)],
            "expected": {
                "death_player": "p1", "death_reason": "opponent",
                "p1_alive": False, "p2_alive": True,
                "game_over": True,
            },
        })
    return specs


def _fuzz_specs() -> list[dict]:
    return [
        {"name": "17_fuzz_sparse_short", "frames": 200, "probability": 0.05},
        {"name": "18_fuzz_sparse_long", "frames": 500, "probability": 0.02},
        {"name": "19_fuzz_active", "frames": 300, "probability": 0.15},
        {"name": "20_fuzz_chaos_short", "frames": 150, "probability": 0.50},
        {"name": "21_fuzz_chaos_long", "frames": 800, "probability": 0.40},
    ]


def _named_frame_buttons(spec: dict, timeline_scale: int, tap_hold: int) -> list[int]:
    total = spec["frames"] * timeline_scale
    frame_buttons = [0] * total
    for event in spec["events"]:
        if len(event) == 2:
            frame, mask = event
            start = frame * timeline_scale
            # A "press" must stay down for one full input window of the scaled
            # game, otherwise the slower 1x1 move cadence would never see it.
            end = start + tap_hold - 1
        elif len(event) == 3:
            start_frame, end_frame, mask = event
            start = start_frame * timeline_scale
            end = end_frame * timeline_scale
        else:
            start, end, mask, units = event
            if units != ABSOLUTE_FRAMES:
                raise ValueError(f"Unknown event units {units!r}")
        for frame in range(start, min(end, total - 1) + 1):
            frame_buttons[frame] |= mask
    return frame_buttons


def _fuzz_frame_buttons(spec: dict, timeline_scale: int, input_window: int, seed: str,
                        masks: tuple = FUZZ_MASKS) -> list[int]:
    rng = random.Random(seed)
    total = spec["frames"] * timeline_scale
    probability = spec["probability"]
    frame_buttons = []
    hold = 0
    mask = 0
    for _ in range(total):
        if hold > 0:
            hold -= 1
        elif rng.random() < probability:
            mask = rng.choice(masks)
            # Hold each random press across one full input window so the
            # scaled 1x1 game samples it; add jitter so edges vary.
            hold = input_window - 1 + rng.randrange(input_window)
        else:
            mask = 0
        frame_buttons.append(mask)
    # Seeded sparse traces can otherwise contain no press before the straight
    # game ends. Add one independently seeded early pulse only in that case.
    early_end = min(total, 17 * timeline_scale)
    if not any(frame_buttons[:early_end]):
        early_start = 8 * timeline_scale
        early_mask = random.Random(seed + "-early").choice(masks)
        for frame in range(early_start, min(early_start + input_window, total)):
            frame_buttons[frame] |= early_mask
    return frame_buttons


def generate_target_suite(target_key: str, mode: str, out_dir: Path) -> list[Path]:
    if target_key not in INPUT_WINDOW:
        raise ValueError(f"Unknown target key {target_key!r}")
    if mode not in MODE_SCALE:
        raise ValueError(f"Unknown mode {mode!r}")

    timeline_scale = MODE_SCALE[mode]
    input_window = INPUT_WINDOW[target_key]
    # Preserve the curved game's existing full-resolution steering duration;
    # compact cardinal turns need only one four-frame sampling window.
    tap_hold = input_window if target_key == "1x1" else timeline_scale
    fuzz_hold = input_window if target_key == "1x1" else timeline_scale
    frame_w, frame_h = MODE_SIZE[mode]
    has_boost = target_key == "2x1"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Make the generated directory an exact manifest of this generator: stale
    # committed scenarios must disappear when a spec is renamed or removed.
    for stale_path in out_dir.glob("*.json"):
        stale_path.unlink()

    named = _named_specs(target_key, mode) + (BOOST_SPECS if has_boost else [])
    fuzz_masks = FUZZ_MASKS_BOOST if has_boost else FUZZ_MASKS

    written = []
    for spec in named:
        frame_buttons = _named_frame_buttons(spec, timeline_scale, tap_hold)
        written.append(write_trace(out_dir / f"{spec['name']}.json",
                                   frame_buttons, frame_w=frame_w, frame_h=frame_h,
                                   expected=spec.get("expected")))
    for spec in _fuzz_specs():
        seed = f"{target_key}-{mode}-{spec['name']}"
        frame_buttons = _fuzz_frame_buttons(
            spec, timeline_scale, fuzz_hold, seed, fuzz_masks)
        written.append(write_trace(out_dir / f"{spec['name']}.json",
                                   frame_buttons, frame_w=frame_w, frame_h=frame_h))
    return written
