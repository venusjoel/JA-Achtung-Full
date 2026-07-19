from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


# tests/ lives inside "Game Simulation/", so the repo root is one level above
# the tests package root.
REPO_ROOT = Path(__file__).resolve().parents[3]
TRACE_SUITE = REPO_ROOT / "comparison" / "test_suite"

BUTTON_BITS = {
    "p1_left": 0b000001,
    "p1_right": 0b000010,
    "p2_left": 0b000100,
    "p2_right": 0b001000,
    "p1_boost": 0b010000,
    "p2_boost": 0b100000,
}

P1_LEFT = BUTTON_BITS["p1_left"]
P1_RIGHT = BUTTON_BITS["p1_right"]
P2_LEFT = BUTTON_BITS["p2_left"]
P2_RIGHT = BUTTON_BITS["p2_right"]
P1_BOOST = BUTTON_BITS["p1_boost"]
P2_BOOST = BUTTON_BITS["p2_boost"]
BUTTON_MASK = 0b111111


@dataclass(frozen=True)
class Trace:
    path: Path
    config: dict
    expected: dict
    frames: int
    frame_buttons: list[int]
    default_buttons: int

    def button_at(self, frame: int) -> int:
        if frame < self.frames:
            return self.frame_buttons[frame]
        return self.default_buttons


def buttons_to_mask(buttons) -> int:
    if buttons is None:
        return 0
    if isinstance(buttons, int):
        return buttons & BUTTON_MASK
    if isinstance(buttons, str):
        text = buttons.strip().lower()
        if text in BUTTON_BITS:
            return BUTTON_BITS[text]
        return int(text, 0) & BUTTON_MASK

    mask = 0
    for item in buttons:
        mask |= buttons_to_mask(item)
    return mask & BUTTON_MASK


def load_trace(path: str | Path) -> Trace:
    trace_path = Path(path).resolve()
    data = json.loads(trace_path.read_text())

    total_frames = int(data.get("frames", 0))
    default_buttons = buttons_to_mask(data.get("default_buttons", 0))
    frame_buttons = [default_buttons] * total_frames

    for event in data.get("events", []):
        start = int(event.get("start", event.get("frame", 0)))
        end = int(event.get("end", start))
        mask = buttons_to_mask(event.get("buttons", 0))
        for frame in range(max(0, start), min(total_frames - 1, end) + 1):
            frame_buttons[frame] = mask

    return Trace(
        path=trace_path,
        config=data.get("config", {}),
        expected=data.get("expected", {}),
        frames=total_frames,
        frame_buttons=frame_buttons,
        default_buttons=default_buttons,
    )


def write_trace(path: str | Path, frame_buttons: list[int], *, frame_w: int = 64,
                frame_h: int = 48, default_buttons: int = 0,
                expected: dict | None = None) -> Path:
    trace_path = Path(path)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    frame_buttons = [int(buttons) & BUTTON_MASK for buttons in frame_buttons]
    default_buttons &= BUTTON_MASK

    events = []
    if frame_buttons:
        run_start = 0
        run_value = frame_buttons[0]
        for frame_index in range(1, len(frame_buttons) + 1):
            next_value = frame_buttons[frame_index] if frame_index < len(frame_buttons) else None
            if next_value != run_value:
                if run_value != default_buttons:
                    event = {"buttons": mask_to_button_names(run_value)}
                    if run_start == frame_index - 1:
                        event["frame"] = run_start
                    else:
                        event["start"] = run_start
                        event["end"] = frame_index - 1
                    events.append(event)
                if frame_index < len(frame_buttons):
                    run_start = frame_index
                    run_value = next_value

    if frame_w == 64:
        start1_x, start2_x, start_y = 10, 53, 24
    else:
        start1_x, start2_x, start_y = 100, 540, 240

    payload = {
        "config": {
            "frame_w": frame_w,
            "frame_h": frame_h,
            "start1_x": start1_x,
            "start2_x": start2_x,
            "start_y": start_y,
            "turn_cooldown": 0,
        },
        **({"expected": expected} if expected else {}),
        "frames": len(frame_buttons),
        "default_buttons": default_buttons,
        "events": events,
    }
    # Keep generated fixtures byte-identical on Windows and Linux so CI can
    # enforce that the committed suite matches this generator.
    trace_path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return trace_path


def mask_to_button_names(mask: int) -> list[str]:
    return [name for name, bit in BUTTON_BITS.items() if mask & bit]


def resolve_trace(name_or_path: str | Path) -> Path:
    candidate = Path(name_or_path)
    if candidate.exists():
        return candidate.resolve()

    text = str(name_or_path)
    if not text.endswith(".json"):
        json_name = f"{text}.json"
    else:
        json_name = text

    direct = TRACE_SUITE / json_name
    if direct.exists():
        return direct.resolve()

    matches = sorted(path for path in TRACE_SUITE.glob("*.json") if path.stem.startswith(text))
    if len(matches) == 1:
        return matches[0].resolve()
    if not matches:
        raise FileNotFoundError(f"Could not find trace {name_or_path!r} in {TRACE_SUITE}")
    raise ValueError(f"Trace {name_or_path!r} is ambiguous: {', '.join(p.name for p in matches)}")


def smoke_traces() -> list[Path]:
    names = [
        "01_straight",
        "04_both_turn",
        "11_hold_button",
        "17_fuzz_sparse_short",
        "20_fuzz_chaos_short",
    ]
    return [resolve_trace(name) for name in names]
