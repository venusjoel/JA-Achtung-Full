#!/usr/bin/env python3
"""Fail CI when a LibreLane harden finishes with signoff violations."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


ZERO_METRICS = (
    "flow__errors__count",
    "design__lint_error__count",
    "design__lint_timing_construct__count",
    "design__inferred_latch__count",
    "synthesis__check_error__count",
    "design__instance_unmapped__count",
    "design__critical_disconnected_pin__count",
    "design__violations",
    "timing__setup_vio__count",
    "timing__hold_vio__count",
    "timing__setup__tns",
    "timing__hold__tns",
    "route__drc_errors",
    "magic__drc_error__count",
    "magic__illegal_overlap__count",
    "design__lvs_error__count",
    "design__lvs_device_difference__count",
    "design__lvs_net_difference__count",
    "design__lvs_property_fail__count",
    "design__lvs_unmatched_device__count",
    "design__lvs_unmatched_net__count",
    "design__lvs_unmatched_pin__count",
    "antenna__violating__nets",
    "antenna__violating__pins",
    "route__antenna_violation__count",
    "design__power_grid_violation__count",
)

NONNEGATIVE_METRICS = (
    "timing__setup__ws",
    "timing__hold__ws",
)

ADVISORY_METRICS = (
    "design__max_slew_violation__count",
    "design__max_cap_violation__count",
    "design__max_fanout_violation__count",
)

AREA_METRICS = (
    "design__instance__area__stdcell",
    "design__instance__area",
    "design__core__area",
    "design__die__area",
)

TARGETS = ("1x1", "1x2")


def number(metrics: dict[str, Any], key: str, failures: list[str]) -> float | None:
    if key not in metrics:
        failures.append(f"missing required metric: {key}")
        return None
    value = metrics[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        failures.append(f"metric {key} is not numeric: {value!r}")
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        failures.append(f"metric {key} is not finite: {value!r}")
        return None
    return numeric


def validate_metrics_data(metrics: dict[str, Any], target: str) -> list[str]:
    failures: list[str] = []
    for key in ZERO_METRICS:
        value = number(metrics, key, failures)
        if value is not None and value != 0:
            failures.append(f"{key} must be 0, got {value:g}")
    for key in NONNEGATIVE_METRICS:
        value = number(metrics, key, failures)
        if value is not None and value < 0:
            failures.append(f"{key} must be nonnegative, got {value:g}")

    areas: dict[str, float] = {}
    for key in AREA_METRICS:
        value = number(metrics, key, failures)
        if value is not None:
            if value <= 0:
                failures.append(f"{key} must be positive, got {value:g}")
            areas[key] = value
    if len(areas) == len(AREA_METRICS):
        ordered = [areas[key] for key in AREA_METRICS]
        if ordered != sorted(ordered):
            failures.append(
                "area hierarchy must be stdcell <= instance <= core <= die, got "
                + " <= ".join(f"{value:g}" for value in ordered)
            )

    utilization = number(metrics, "design__instance__utilization", failures)
    if utilization is not None and not 0 < utilization <= 1:
        failures.append(
            f"design__instance__utilization must be in (0, 1], got {utilization:g}"
        )

    for key in ADVISORY_METRICS:
        value = number(metrics, key, failures)
        if value is None:
            continue
        if value < 0 or not value.is_integer():
            failures.append(f"{key} must be a nonnegative integer, got {value:g}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check the hard signoff gates in a LibreLane metrics.json file."
    )
    parser.add_argument("metrics", type=Path)
    parser.add_argument("--target", choices=TARGETS, required=True)
    args = parser.parse_args()

    try:
        metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"HARDEN FAIL: cannot read {args.metrics}: {error}")
        return 2
    if not isinstance(metrics, dict):
        print(f"HARDEN FAIL: {args.metrics} does not contain a JSON object")
        return 2

    failures = validate_metrics_data(metrics, args.target)

    setup = metrics.get("timing__setup__ws", "missing")
    hold = metrics.get("timing__hold__ws", "missing")
    area = metrics.get("design__instance__area__stdcell", "missing")
    utilization = metrics.get("design__instance__utilization", "missing")
    print(
        "HARDEN SUMMARY: "
        f"setup_ws={setup}, hold_ws={hold}, "
        f"stdcell_area={area}, utilization={utilization}"
    )

    advisories = []
    for key in ADVISORY_METRICS:
        value = metrics.get(key, "missing")
        advisories.append(f"{key}={value}")
    print("HARDEN ELECTRICAL ADVISORIES: " + ", ".join(advisories))

    if failures:
        print("HARDEN FAIL:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("HARDEN PASS: required hard-signoff metrics are clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
