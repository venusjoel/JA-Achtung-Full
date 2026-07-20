from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from cocotb_tools.runner import get_runner


# tests/ lives inside "Game Simulation/": PKG_ROOT is the import root for the
# tests package, REPO_ROOT holds targets/ and the other hardware sources.
TESTS_DIR = Path(__file__).resolve().parents[1]
PKG_ROOT = TESTS_DIR.parent
REPO_ROOT = TESTS_DIR.parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

TARGETS = ("1x2-working-game",)
SIM_TIMESCALE = ("1ns", "1ps")


def source_for_target(target: str) -> Path:
    path = REPO_ROOT / "src" / "psram_controller.v"
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def display_source_for_target(target: str) -> Path:
    path = REPO_ROOT / "src" / "display_streamer.v"
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def run_target(target: str, rebuild: bool) -> None:
    sim = os.environ.get("SIM", "icarus")
    runner = get_runner(sim)
    build_dir = TESTS_DIR / "out" / "sim_build" / f"ram-{target}"
    runner.build(
        sources=[source_for_target(target)],
        hdl_toplevel="psram_controller",
        build_dir=build_dir,
        timescale=SIM_TIMESCALE,
        always=rebuild,
    )
    results_xml = build_dir / "results.xml"
    runner.test(
        hdl_toplevel="psram_controller",
        test_module="tests.ram.cocotb_psram_controller",
        build_dir=build_dir,
        results_xml=str(results_xml),
        timescale=SIM_TIMESCALE,
        extra_env={
            "PYTHONPATH": str(PKG_ROOT),
            "ACHTUNG_TARGET": target,
        },
    )
    assert_results_passed(results_xml)
    print(f"PASS PSRAM {target}")


def run_display_target(target: str, rebuild: bool) -> None:
    sim = os.environ.get("SIM", "icarus")
    runner = get_runner(sim)
    build_dir = TESTS_DIR / "out" / "sim_build" / f"display-{target}"
    burst_bytes = 4 if target == "1x1-minimal" else 8
    runner.build(
        sources=[display_source_for_target(target)],
        hdl_toplevel="display_streamer",
        build_dir=build_dir,
        parameters={
            "FRAME_W": 64,
            "FRAME_H": 48,
            "BURST_BYTES": burst_bytes,
            "DATA_WIDTH": 8 * burst_bytes,
        },
        timescale=SIM_TIMESCALE,
        always=rebuild,
    )
    results_xml = build_dir / "results.xml"
    runner.test(
        hdl_toplevel="display_streamer",
        test_module="tests.ram.cocotb_display_streamer",
        build_dir=build_dir,
        results_xml=str(results_xml),
        timescale=SIM_TIMESCALE,
        extra_env={
            "PYTHONPATH": str(PKG_ROOT),
            "ACHTUNG_TARGET": target,
        },
    )
    assert_results_passed(results_xml)
    print(f"PASS DISPLAY {target}")


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run current target PSRAM-controller tests.")
    parser.add_argument("--target", choices=("all",) + TARGETS, default="all")
    parser.add_argument("--controller-only", action="store_true", help="Only run psram_controller tests, not display_streamer tests.")
    parser.add_argument("--display-only", action="store_true", help="Only run display_streamer tests.")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    if args.controller_only and args.display_only:
        parser.error("--controller-only and --display-only cannot be combined")

    targets = TARGETS if args.target == "all" else (args.target,)
    for target in targets:
        if not args.display_only:
            run_target(target, args.rebuild)
        if not args.controller_only:
            run_display_target(target, args.rebuild)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
