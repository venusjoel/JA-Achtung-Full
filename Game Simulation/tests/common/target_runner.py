"""CLI/runner behind the standalone tests/game_2x1/run.py suite.

Each target folder provides a TargetSpec; this module implements the tests:

- vga:   full VGA + real QSPI PSRAM read path streaming a lined picture.
- game:  direct-RAM game-logic compare, Python model vs HDL, text-map diff.
- suite: every generated trace in the target's traces/<mode>/ folder.
- live:  play the Python model in pygame, record a trace, replay it in the
         HDL, and compare both text maps.
- all:   true-640x480 VGA + the selected-mode suite (full by default) + system smoke.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from cocotb_tools.runner import get_runner

# This file lives in "<repo>/Game Simulation/tests/common/". The `tests`
# package root is "Game Simulation" (which goes on PYTHONPATH), while the
# hardware sources live at the repo root.
TESTS_DIR = Path(__file__).resolve().parents[1]
PKG_ROOT = TESTS_DIR.parent
REPO_ROOT = TESTS_DIR.parents[1]

from tests.common.game_models import model_for_target
from tests.common.maps import first_difference, write_text_map
from tests.common.trace_gen import generate_target_suite
from tests.common.traces import load_trace

MODES = ("coarse", "full")


@dataclass(frozen=True)
class TargetSpec:
    key: str            # "1x1" or "2x1"
    target: str         # targets/<target> source snapshot
    folder: str         # tests/<folder>
    test_module: str    # cocotb module for the direct game test


def mode_size(mode: str) -> tuple[int, int]:
    return (640, 480) if mode == "full" else (64, 48)


def start_coords(mode: str) -> tuple[int, int, int]:
    return (100, 540, 240) if mode == "full" else (10, 53, 24)


def assert_results_passed(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    testcases = list(root.iter("testcase"))
    problems = []
    if not testcases:
        problems.append("result contains no test cases")

    for suite in root.iter("testsuite"):
        for attribute in ("failures", "errors", "skipped"):
            raw_value = suite.get(attribute)
            if raw_value is None:
                continue
            try:
                value = int(raw_value)
            except ValueError:
                problems.append(
                    f"suite has nonnumeric {attribute}={raw_value!r}"
                )
                continue
            if value != 0:
                problems.append(f"suite reports {attribute}={value}")

    for testcase in testcases:
        identity = f"{testcase.get('classname')}.{testcase.get('name')}"
        for tag in ("failure", "error", "skipped"):
            detail = testcase.find(tag)
            if detail is not None:
                message = detail.get("message") or detail.get("error_msg") or ""
                problems.append(f"{identity}: {tag}: {message}")

    if problems:
        raise SystemExit(
            "Invalid cocotb JUnit result in " + str(path) + ":\n"
            + "\n".join(problems)
        )


def target_src_dir(_spec: TargetSpec) -> Path:
    # Always simulate the exact HDL that will be submitted to Tiny Tapeout.
    # Target snapshots may be useful as references, but they can become stale.
    src_dir = REPO_ROOT / "src"
    if not src_dir.exists():
        raise FileNotFoundError(f"Missing submission source directory: {src_dir}")
    return src_dir


def traces_dir(spec: TargetSpec, mode: str) -> Path:
    return TESTS_DIR / spec.folder / "traces" / mode


def out_dir(spec: TargetSpec) -> Path:
    return TESTS_DIR / "out" / spec.folder


def resolve_trace(spec: TargetSpec, mode: str, name_or_path: str) -> Path:
    candidate = Path(name_or_path)
    if candidate.exists():
        return candidate.resolve()
    text = str(name_or_path)
    json_name = text if text.endswith(".json") else f"{text}.json"
    direct = traces_dir(spec, mode) / json_name
    if direct.exists():
        return direct.resolve()
    matches = sorted(path for path in traces_dir(spec, mode).glob("*.json")
                     if path.stem.startswith(text))
    if len(matches) == 1:
        return matches[0].resolve()
    if not matches:
        raise FileNotFoundError(
            f"Could not find trace {name_or_path!r} in {traces_dir(spec, mode)} "
            "(run with --gen to generate the suite)")
    raise ValueError(f"Trace {name_or_path!r} is ambiguous: "
                     + ", ".join(p.name for p in matches))


def write_python_map(spec: TargetSpec, trace_path: Path, frames: int,
                     path: Path, mode: str) -> None:
    trace = load_trace(trace_path)
    frame_w, frame_h = mode_size(mode)
    model = model_for_target(spec.target, width=frame_w, height=frame_h)
    for frame in range(frames):
        model.step(trace.button_at(frame))
    if frames >= trace.frames and trace.expected:
        mismatches = []
        for attribute, expected in trace.expected.items():
            if not hasattr(model, attribute):
                mismatches.append(f"unknown model attribute {attribute!r}")
                continue
            actual = getattr(model, attribute)
            if actual != expected:
                mismatches.append(
                    f"{attribute}: expected {expected!r}, got {actual!r}")
        if mismatches:
            raise AssertionError(
                f"Semantic expectation failed for {trace.path.name}: "
                + "; ".join(mismatches))
        print(f"PASS semantic {trace.path.name}: {trace.expected}")
    write_text_map(model.text_map(), path, f"Achtung {spec.target} {frame_w}x{frame_h}")


def run_hdl_direct(spec: TargetSpec, trace_path: Path, frames: int,
                   hdl_map: Path, mode: str, rebuild: bool) -> None:
    sim = os.environ.get("SIM", "icarus")
    runner = get_runner(sim)
    frame_w, frame_h = mode_size(mode)
    start1_x, start2_x, start_y = start_coords(mode)

    build_dir = out_dir(spec) / "sim_build" / f"direct-{mode}"
    runner.build(
        sources=[target_src_dir(spec) / "game_fsm.v",
                 TESTS_DIR / spec.folder / "tb_game_direct.v"],
        hdl_toplevel="tb_game_direct",
        parameters={
            "FRAME_W": frame_w,
            "FRAME_H": frame_h,
            "START1_X": start1_x,
            "START2_X": start2_x,
            "START_Y": start_y,
        },
        build_dir=build_dir,
        always=rebuild,
    )
    results_xml = build_dir / "results.xml"
    runner.test(
        hdl_toplevel="tb_game_direct",
        test_module=spec.test_module,
        build_dir=build_dir,
        results_xml=str(results_xml),
        extra_env={
            "PYTHONPATH": str(PKG_ROOT),
            "ACHTUNG_TRACE": str(trace_path),
            "ACHTUNG_FRAMES": str(frames),
            "ACHTUNG_FRAME_W": str(frame_w),
            "ACHTUNG_FRAME_H": str(frame_h),
            "ACHTUNG_HDL_MAP": str(hdl_map),
        },
    )
    assert_results_passed(results_xml)


def run_game(spec: TargetSpec, trace_path: Path, frames: int | None,
             mode: str, rebuild: bool) -> bool:
    trace = load_trace(trace_path)
    frame_count = trace.frames if frames is None else min(frames, trace.frames)
    result_dir = out_dir(spec) / "game" / mode / trace_path.stem
    python_map = result_dir / "python_map.txt"
    hdl_map = result_dir / "hdl_map.txt"

    write_python_map(spec, trace_path, frame_count, python_map, mode)
    run_hdl_direct(spec, trace_path, frame_count, hdl_map, mode, rebuild)
    if not hdl_map.exists():
        raise RuntimeError(f"HDL simulation did not produce {hdl_map}")

    diff = first_difference(python_map, hdl_map)
    if diff is None:
        print(f"PASS {spec.folder} game {mode} {trace_path.name} ({frame_count} frames)")
        return True
    print(f"FAIL {spec.folder} game {mode} {trace_path.name} ({frame_count} frames)")
    print(f"  expected: {python_map}")
    print(f"  hdl:      {hdl_map}")
    print(f"  {diff}")
    return False


def run_vga(spec: TargetSpec, full_vga: bool, rows: int | None, rebuild: bool) -> bool:
    sim = os.environ.get("SIM", "icarus")
    runner = get_runner(sim)
    mode = "full" if full_vga else "coarse"
    frame_w, frame_h = (640, 480) if full_vga else (64, 48)
    rows_to_check = frame_h if rows is None else min(rows, frame_h)

    defines = {"COCOTB_SIM": 1}
    if full_vga:
        defines["FULL_VGA_SIM"] = 1

    build_dir = out_dir(spec) / "sim_build" / f"vga-{mode}"
    runner.build(
        sources=sorted(target_src_dir(spec).glob("*.v"))
                + [TESTS_DIR / "common" / "tb_tt_um.v"],
        hdl_toplevel="tb_tt_um",
        defines=defines,
        build_dir=build_dir,
        always=rebuild,
    )
    result_dir = out_dir(spec) / "vga" / mode
    results_xml = build_dir / "results.xml"
    runner.test(
        hdl_toplevel="tb_tt_um",
        test_module="tests.common.cocotb_vga_picture",
        build_dir=build_dir,
        results_xml=str(results_xml),
        extra_env={
            "PYTHONPATH": str(PKG_ROOT),
            "ACHTUNG_TARGET": spec.target,
            "ACHTUNG_FRAME_W": str(frame_w),
            "ACHTUNG_FRAME_H": str(frame_h),
            "ACHTUNG_VGA_ROWS": str(rows_to_check),
            "ACHTUNG_VGA_MAP": str(result_dir / "captured_map.txt"),
            "ACHTUNG_VGA_EXPECTED_MAP": str(result_dir / "expected_map.txt"),
        },
    )
    assert_results_passed(results_xml)
    print(f"PASS {spec.folder} vga {mode} ({frame_w}x{rows_to_check} pixels)")
    print(f"  map: {result_dir / 'captured_map.txt'}")
    return True


# The compact game can collide before trace 04's delayed turn is sampled.
# Frame-zero input makes the short full-system smoke exercise real decoding.
SYSTEM_DEFAULT_TRACE = {"1x1": "15_frame_0_input", "2x1": "23_boost_duel"}
SYSTEM_DEFAULT_FRAMES = 60


def run_system(spec: TargetSpec, trace_path: Path, frames: int | None, rebuild: bool) -> bool:
    """Full-top smoke compare: gamepad PMOD protocol + real QSPI + arbitration."""
    sim = os.environ.get("SIM", "icarus")
    runner = get_runner(sim)
    frame_w, frame_h = mode_size("coarse")

    trace = load_trace(trace_path)
    frame_count = min(frames if frames is not None else SYSTEM_DEFAULT_FRAMES, trace.frames)
    result_dir = out_dir(spec) / "system" / trace_path.stem
    python_map = result_dir / "python_map.txt"
    hdl_map = result_dir / "hdl_map.txt"
    write_python_map(spec, trace_path, frame_count, python_map, "coarse")

    build_dir = out_dir(spec) / "sim_build" / "system-coarse"
    runner.build(
        sources=sorted(target_src_dir(spec).glob("*.v"))
                + [TESTS_DIR / "common" / "tb_tt_um.v"],
        hdl_toplevel="tb_tt_um",
        defines={"COCOTB_SIM": 1},
        build_dir=build_dir,
        always=rebuild,
    )
    results_xml = build_dir / "results.xml"
    runner.test(
        hdl_toplevel="tb_tt_um",
        test_module="tests.common.cocotb_system_compare",
        build_dir=build_dir,
        results_xml=str(results_xml),
        extra_env={
            "PYTHONPATH": str(PKG_ROOT),
            "ACHTUNG_TARGET": spec.target,
            "ACHTUNG_TRACE": str(trace_path),
            "ACHTUNG_FRAMES": str(frame_count),
            "ACHTUNG_FRAME_W": str(frame_w),
            "ACHTUNG_FRAME_H": str(frame_h),
            "ACHTUNG_HDL_MAP": str(hdl_map),
        },
    )
    assert_results_passed(results_xml)

    diff = first_difference(python_map, hdl_map)
    if diff is None:
        print(f"PASS {spec.folder} system {trace_path.name} ({frame_count} frames, "
              "gamepad+QSPI+arbitration)")
        return True
    print(f"FAIL {spec.folder} system {trace_path.name} ({frame_count} frames)")
    print(f"  expected: {python_map}")
    print(f"  hdl:      {hdl_map}")
    print(f"  {diff}")
    return False


def run_suite(spec: TargetSpec, mode: str, frames: int | None, rebuild: bool) -> bool:
    trace_paths = sorted(traces_dir(spec, mode).glob("*.json"))
    if not trace_paths:
        raise SystemExit(f"No traces in {traces_dir(spec, mode)}; run with --gen first.")
    ok = True
    for index, trace_path in enumerate(trace_paths):
        ok = run_game(spec, trace_path, frames, mode,
                      rebuild=rebuild and index == 0) and ok
    return ok


def run_live(spec: TargetSpec, args, rebuild: bool) -> bool:
    from tests.common.live_record import record_live_trace

    frame_w, frame_h = mode_size(args.mode)
    live_dir = out_dir(spec) / "live"
    trace_path = (Path(args.live_trace).resolve() if args.live_trace
                  else live_dir / f"live_trace_{uuid.uuid4().hex}.json")
    preview_map = trace_path.with_name(trace_path.stem + "_python_preview.txt")
    record_live_trace(
        spec.target,
        trace_path,
        frames=args.live_frames,
        fps=args.live_fps,
        preview_map_path=preview_map,
        frame_w=frame_w,
        frame_h=frame_h,
    )
    print(f"Live Python preview map: {preview_map}")
    return run_game(spec, trace_path, None, args.mode, rebuild)


def generate_traces(spec: TargetSpec) -> None:
    for mode in MODES:
        written = generate_target_suite(spec.key, mode, traces_dir(spec, mode))
        print(f"Generated {len(written)} {mode} traces in {traces_dir(spec, mode)}")


def main(spec: TargetSpec) -> int:
    parser = argparse.ArgumentParser(
        description=f"Achtung {spec.target} test runner.")
    parser.add_argument("--test", choices=("all", "vga", "game", "suite", "system", "live"),
                        default="all")
    parser.add_argument("--mode", choices=MODES, default="full",
                        help="game/suite resolution: full=real 640x480 game (default), coarse=quick 64x48")
    parser.add_argument("--trace", default=None,
                        help="trace name (defaults to 01_straight for game or the target system smoke) or path")
    parser.add_argument("--frames", type=int, default=None)
    parser.add_argument("--full-vga", action="store_true",
                        help="vga test at real 640x480 timing (slow)")
    parser.add_argument("--rows", type=int, default=None,
                        help="limit VGA rows captured/checked")
    parser.add_argument("--gen", action="store_true",
                        help="(re)generate this target's trace suites, then exit")
    parser.add_argument("--live-frames", type=int, default=None,
                        help="max frames to record (default: 300 coarse / 6000 full)")
    parser.add_argument("--live-fps", type=int, default=30)
    parser.add_argument("--live-trace", default=None)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    for option, value in (
        ("--frames", args.frames),
        ("--rows", args.rows),
        ("--live-frames", args.live_frames),
    ):
        if value is not None and value < 1:
            parser.error(f"{option} must be at least 1")
    if args.live_fps < 1:
        parser.error("--live-fps must be at least 1")

    if args.gen:
        generate_traces(spec)
        return 0

    if args.test == "vga":
        ok = run_vga(spec, args.full_vga, args.rows, args.rebuild)
    elif args.test == "game":
        trace_path = resolve_trace(spec, args.mode, args.trace or "01_straight")
        ok = run_game(spec, trace_path, args.frames, args.mode, args.rebuild)
    elif args.test == "suite":
        ok = run_suite(spec, args.mode, args.frames, args.rebuild)
    elif args.test == "system":
        name = args.trace or SYSTEM_DEFAULT_TRACE[spec.key]
        ok = run_system(spec, resolve_trace(spec, "coarse", name), args.frames, args.rebuild)
    elif args.test == "live":
        ok = run_live(spec, args, args.rebuild)
    else:  # all
        # RAM read path: one true-640x480 frame streamed over real QSPI+VGA.
        ok = run_vga(spec, full_vga=True, rows=args.rows, rebuild=args.rebuild)
        # Game logic: every trace on the full-size game, direct RAM.
        ok = run_suite(spec, args.mode, args.frames, args.rebuild) and ok
        # Full-top smoke: gamepad decode + QSPI writes + bus arbitration.
        system_trace = resolve_trace(spec, "coarse", SYSTEM_DEFAULT_TRACE[spec.key])
        ok = run_system(spec, system_trace, None, args.rebuild) and ok
    return 0 if ok else 1
