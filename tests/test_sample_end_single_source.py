"""The sample end date must have exactly one definition.

This project has repeatedly been bitten by the same failure: the calendar end is
edited in one place and the other spellings of it are forgotten, so parts of the
pipeline silently keep the old boundary. These tests fail if a new hardcoded
spelling of the sample end appears outside `ddvc.calendar`, and they pin the
derived forms so a single edit provably moves every consumer.
"""

from __future__ import annotations

import datetime as dt
import importlib
import re
import subprocess
import unittest
from pathlib import Path

from ddvc.calendar import (
    RESEARCH_SAMPLE_END,
    day_date,
    sample_end_date,
    sample_end_exclusive_iso,
    sample_end_iso,
    sample_end_utc_exclusive,
)


REPO = Path(__file__).resolve().parents[1]

# The one file allowed to spell the boundary out.
CANONICAL_SOURCE = "src/ddvc/calendar.py"

# Directories that legitimately restate the boundary: fixtures pin expected
# values on purpose, and prose is a human record rather than an input.
EXEMPT_PREFIXES = ("tests/", "docs/", "data/", "output/", "scratch/", ".venv/")


def _tracked_python_files() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "*.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [
        rel
        for rel in out
        if rel != CANONICAL_SOURCE and not rel.startswith(EXEMPT_PREFIXES)
    ]


class SampleEndSingleSource(unittest.TestCase):
    def test_derived_forms_agree(self) -> None:
        end = sample_end_date()
        self.assertEqual(end, day_date(RESEARCH_SAMPLE_END))
        self.assertEqual(sample_end_iso(), end.isoformat())
        exclusive = end + dt.timedelta(days=1)
        self.assertEqual(sample_end_exclusive_iso(), exclusive.isoformat())
        self.assertEqual(
            sample_end_utc_exclusive(),
            int(
                dt.datetime(
                    exclusive.year,
                    exclusive.month,
                    exclusive.day,
                    tzinfo=dt.timezone.utc,
                ).timestamp()
            ),
        )

    def test_exclusive_bound_is_the_day_after(self) -> None:
        """Guards the off-by-one that an inclusive/exclusive mix-up creates."""
        self.assertEqual(
            day_date(sample_end_exclusive_iso()) - sample_end_date(),
            dt.timedelta(days=1),
        )

    def test_no_hardcoded_sample_end_outside_calendar(self) -> None:
        end = sample_end_date()
        exclusive = end + dt.timedelta(days=1)
        # Every spelling that would drift if the constant moved.
        forbidden = {
            end.strftime("%Y%m%d"),
            end.isoformat(),
            exclusive.strftime("%Y%m%d"),
            exclusive.isoformat(),
            f"{end.year}, {end.month}, {end.day}",
            f"{exclusive.year}, {exclusive.month}, {exclusive.day}",
        }
        pattern = re.compile("|".join(re.escape(s) for s in sorted(forbidden)))

        offenders: list[str] = []
        for rel in _tracked_python_files():
            path = REPO / rel
            try:
                body = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(body.splitlines(), start=1):
                if pattern.search(line):
                    offenders.append(f"{rel}:{number}: {line.strip()}")

        self.assertEqual(
            offenders,
            [],
            "Hardcoded sample-end date found. Import from ddvc.calendar instead "
            "(RESEARCH_SAMPLE_END, sample_end_iso(), sample_end_exclusive_iso(), "
            "sample_end_utc_exclusive()):\n" + "\n".join(offenders),
        )

    def test_consumers_follow_a_changed_constant(self) -> None:
        """One edit must move every consumer, including derived filenames."""
        calendar = importlib.import_module("ddvc.calendar")
        original = calendar.RESEARCH_SAMPLE_END
        moved = "20261231"
        self.assertNotEqual(original, moved, "pick a different probe date")

        consumers = {
            "scripts.build_v3_pool_registry": ("GRAPH_STATIC_PATH", "END_META_PATH"),
            "scripts.build_v3_inventory_panel": ("GRAPH_STATIC_PATH",),
            "scripts.fetch_v3_inventory_events": ("END_META_PATH",),
            "scripts.fetch_pool_identity_registry": ("SAMPLE_DAY",),
            "ddvc.fetch.coinbase_prices": ("SAMPLE_END_UTC_EXCLUSIVE",),
        }
        try:
            calendar.RESEARCH_SAMPLE_END = moved
            for name, attrs in consumers.items():
                module = importlib.reload(importlib.import_module(name))
                for attr in attrs:
                    rendered = str(getattr(module, attr))
                    if attr == "SAMPLE_END_UTC_EXCLUSIVE":
                        self.assertEqual(
                            int(rendered),
                            int(
                                dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc).timestamp()
                            ),
                            f"{name}.{attr} ignored the moved constant",
                        )
                    else:
                        self.assertIn(
                            moved,
                            rendered,
                            f"{name}.{attr} ignored the moved constant: {rendered}",
                        )
                    self.assertNotIn(
                        original,
                        rendered,
                        f"{name}.{attr} kept the old boundary: {rendered}",
                    )
        finally:
            calendar.RESEARCH_SAMPLE_END = original
            for name in consumers:
                importlib.reload(importlib.import_module(name))


if __name__ == "__main__":
    unittest.main()
