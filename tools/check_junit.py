#!/usr/bin/env python3
"""Strictly validate a JUnit XML result instead of grepping its text."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


class JUnitValidationError(RuntimeError):
    """Raised when a JUnit file is missing, malformed, or not wholly passing."""


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def descendants(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element.iter() if local_name(child) == name]


def validate_junit(
    path: Path,
    *,
    expected_tests: int | None = None,
    expected_names: frozenset[str] | None = None,
) -> list[str]:
    if not path.is_file() or path.stat().st_size == 0:
        raise JUnitValidationError(f"JUnit result is missing or empty: {path}")
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise JUnitValidationError(f"cannot parse JUnit result {path}: {error}") from error

    cases = descendants(root, "testcase")
    if not cases:
        raise JUnitValidationError(f"JUnit result contains no test cases: {path}")
    if expected_tests is not None and len(cases) != expected_tests:
        raise JUnitValidationError(
            f"JUnit result has {len(cases)} tests, expected {expected_tests}: {path}"
        )

    names = [case.get("name") for case in cases]
    if any(name is None or not name.strip() for name in names):
        raise JUnitValidationError(f"JUnit result contains an unnamed test: {path}")
    if len(names) != len(set(names)):
        raise JUnitValidationError(f"JUnit result contains duplicate test names: {path}")
    if expected_names is not None and frozenset(names) != expected_names:
        raise JUnitValidationError(
            f"JUnit test names are {sorted(names)}, expected {sorted(expected_names)}: {path}"
        )

    for outcome in ("failure", "error", "skipped"):
        count = len(descendants(root, outcome))
        if count:
            raise JUnitValidationError(
                f"JUnit result contains {count} {outcome} element(s): {path}"
            )

    suites = [element for element in root.iter() if local_name(element) in {"testsuite", "testsuites"}]
    if not suites:
        raise JUnitValidationError(f"JUnit result contains no test suite: {path}")
    for suite in suites:
        suite_name = suite.get("name", local_name(suite))
        for attribute in ("failures", "errors", "skipped"):
            raw_value = suite.get(attribute)
            if raw_value is None:
                continue
            try:
                value = int(raw_value)
            except ValueError as error:
                raise JUnitValidationError(
                    f"JUnit suite {suite_name!r} has nonnumeric {attribute}={raw_value!r}: {path}"
                ) from error
            if value != 0:
                raise JUnitValidationError(
                    f"JUnit suite {suite_name!r} reports {attribute}={value}: {path}"
                )
        raw_tests = suite.get("tests")
        if raw_tests is not None:
            try:
                declared_tests = int(raw_tests)
            except ValueError as error:
                raise JUnitValidationError(
                    f"JUnit suite {suite_name!r} has nonnumeric tests={raw_tests!r}: {path}"
                ) from error
            actual_tests = len(descendants(suite, "testcase"))
            if declared_tests != actual_tests:
                raise JUnitValidationError(
                    f"JUnit suite {suite_name!r} declares {declared_tests} tests but contains "
                    f"{actual_tests}: {path}"
                )
    return names  # useful to callers that want to print an exact summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--expected-tests", type=int)
    parser.add_argument("--test-name", action="append", default=[])
    args = parser.parse_args()
    if args.expected_tests is not None and args.expected_tests < 1:
        parser.error("--expected-tests must be positive")
    expected_names = frozenset(args.test_name) if args.test_name else None
    try:
        names = validate_junit(
            args.result,
            expected_tests=args.expected_tests,
            expected_names=expected_names,
        )
    except JUnitValidationError as error:
        print(f"JUNIT FAIL: {error}")
        return 1
    print(f"JUNIT PASS: {len(names)} test(s): {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
