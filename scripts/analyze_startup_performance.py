#!/usr/bin/env python3
"""Summarize Kira startup-performance.jsonl records from repeated launches.

The report intentionally uses only stdlib and requires complete Windows
phase/memory samples so medians are not silently calculated from partial data.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any


METRICS = {
    "window_shown_ms": ("phases", "window_shown", "elapsed_ms"),
    "first_event_loop_ms": ("phases", "event_loop_first_tick", "elapsed_ms"),
    "window_shown_working_set_mb": (
        "memory_samples", "window_shown", "working_set_mb"
    ),
    "window_shown_private_bytes_mb": (
        "memory_samples", "window_shown", "private_bytes_mb"
    ),
    "window_shown_peak_working_set_mb": (
        "memory_samples", "window_shown", "peak_working_set_mb"
    ),
    "first_tick_working_set_mb": (
        "memory_samples", "event_loop_first_tick", "working_set_mb"
    ),
    "first_tick_private_bytes_mb": (
        "memory_samples", "event_loop_first_tick", "private_bytes_mb"
    ),
    "first_tick_peak_working_set_mb": (
        "memory_samples", "event_loop_first_tick", "peak_working_set_mb"
    ),
}

UNITS = {
    "window_shown_ms": "ms",
    "first_event_loop_ms": "ms",
    "window_shown_working_set_mb": "MB",
    "window_shown_private_bytes_mb": "MB",
    "window_shown_peak_working_set_mb": "MB",
    "first_tick_working_set_mb": "MB",
    "first_tick_private_bytes_mb": "MB",
    "first_tick_peak_working_set_mb": "MB",
}


def _value_at(record: dict[str, Any], path: tuple[str, ...]) -> float | None:
    value: Any = record
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def load_complete_records(path: Path) -> tuple[list[dict[str, Any]], int, int]:
    """Return complete schema-v2 samples, malformed-line count and incomplete count."""
    records: list[dict[str, Any]] = []
    malformed = 0
    incomplete = 0
    try:
        stream = path.open("r", encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError(f"Cannot open startup log '{path}': {exc}") from exc

    with stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(record, dict) or record.get("schema_version") != 2:
                incomplete += 1
                continue
            values = {
                name: _value_at(record, location)
                for name, location in METRICS.items()
            }
            if any(value is None for value in values.values()):
                incomplete += 1
                continue
            records.append({
                "recorded_at": str(record.get("recorded_at") or f"line {line_number}"),
                "values": values,
            })
    return records, malformed, incomplete


def summarize(records: list[dict[str, Any]], runs: int) -> dict[str, dict[str, float | int]]:
    selected = records[-runs:]
    summary: dict[str, dict[str, float | int]] = {}
    for name in METRICS:
        values = [float(record["values"][name]) for record in selected]
        summary[name] = {
            "count": len(values),
            "median": statistics.median(values),
            "minimum": min(values),
            "maximum": max(values),
        }
    return summary


def render_report(
    records: list[dict[str, Any]],
    summary: dict[str, dict[str, float | int]],
    runs: int,
    malformed: int,
    incomplete: int,
) -> str:
    lines = [
        "Kira startup performance report",
        f"Complete launches analyzed: {runs}",
        f"Skipped malformed lines: {malformed}",
        f"Skipped incomplete/unsupported records: {incomplete}",
        "",
        "Metric                                      Median       Min       Max",
        "-----------------------------------------------------------------------",
    ]
    for name, stats in summary.items():
        unit = UNITS[name]
        median = float(stats["median"])
        minimum = float(stats["minimum"])
        maximum = float(stats["maximum"])
        lines.append(
            f"{name:<42} {median:>8.2f} {unit:<3} "
            f"{minimum:>8.2f} {maximum:>8.2f}"
        )
    lines.extend(["", "Launch timestamps (oldest to newest):"])
    for record in records[-runs:]:
        lines.append(f"- {record['recorded_at']}")
    lines.extend([
        "",
        "Notes:",
        "- Medians are calculated from the latest complete schema-v2 records.",
        "- Working Set and Private Bytes are different memory measures; do not combine them.",
        "- Peak Working Set is a process high-water mark, not the current Working Set.",
        "- Compare builds only when machine, data directory, workload and launch conditions match.",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Calculate median startup timings and Windows memory samples from "
            "Kira's startup-performance.jsonl log."
        )
    )
    parser.add_argument("log_file", type=Path, help="Path to logs/startup-performance.jsonl")
    parser.add_argument(
        "--runs", type=int, default=5,
        help="number of latest complete launches to analyze (default: 5)",
    )
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    try:
        records, malformed, incomplete = load_complete_records(args.log_file)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if len(records) < args.runs:
        print(
            f"Need {args.runs} complete Windows launches; found {len(records)}. "
            f"Skipped {malformed} malformed and {incomplete} incomplete/unsupported records. "
            "Launch Kira normally, wait until the chat window is interactive, close it cleanly, "
            "and repeat until enough complete records are present.",
            file=sys.stderr,
        )
        return 1

    selected = records[-args.runs:]
    report = summarize(selected, args.runs)
    print(render_report(selected, report, args.runs, malformed, incomplete))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
