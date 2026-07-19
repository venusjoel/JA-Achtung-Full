#!/usr/bin/env python3
"""Focused tests for Tiny Tapeout hard-signoff metric classification."""

from __future__ import annotations

import unittest

import check_harden_metrics as checker


def clean_metrics() -> dict[str, float]:
    metrics = {key: 0.0 for key in checker.ZERO_METRICS}
    metrics.update({key: 0.0 for key in checker.NONNEGATIVE_METRICS})
    metrics.update(
        {
            "design__instance__area__stdcell": 15_279.7,
            "design__instance__area": 16_493.3,
            "design__core__area": 16_493.3,
            "design__die__area": 17_954.7,
            "design__instance__utilization": 0.926415,
            "design__max_slew_violation__count": 174,
            "design__max_cap_violation__count": 0,
            "design__max_fanout_violation__count": 0,
        }
    )
    return metrics


class HardenMetricClassificationTests(unittest.TestCase):
    def test_electrical_advisories_do_not_fail_hard_signoff(self) -> None:
        self.assertEqual(checker.validate_metrics_data(clean_metrics(), "1x1"), [])

    def test_hard_signoff_violation_still_fails(self) -> None:
        metrics = clean_metrics()
        metrics["route__drc_errors"] = 1
        self.assertIn(
            "route__drc_errors must be 0, got 1",
            checker.validate_metrics_data(metrics, "1x1"),
        )

    def test_advisory_must_still_be_a_nonnegative_integer(self) -> None:
        metrics = clean_metrics()
        metrics["design__max_slew_violation__count"] = -1
        self.assertIn(
            "design__max_slew_violation__count must be a nonnegative integer, got -1",
            checker.validate_metrics_data(metrics, "1x1"),
        )


if __name__ == "__main__":
    unittest.main()
