from __future__ import annotations

import re
import unittest
from pathlib import Path

from ddvc.fetch.sources import DEX_SOURCES


ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs" / "repository-data-map.md"


def documented_sources(provider: str) -> set[str]:
    text = MAP.read_text(encoding="utf-8")
    match = re.search(rf"^\| {re.escape(provider)} \| ([^|]+) \|", text, re.MULTILINE)
    if match is None:
        raise AssertionError(f"repository data map has no {provider} provider row")
    return set(re.findall(r"`([a-z0-9_]+)`", match.group(1)))


class RepositoryDataMapTests(unittest.TestCase):
    def test_indexed_provider_coverage_matches_executable_registry(self) -> None:
        expected_graph = {
            name for name, source in DEX_SOURCES.items() if source.backend == "thegraph"
        }
        expected_dune = {
            name for name, source in DEX_SOURCES.items() if source.backend == "dune"
        }
        self.assertEqual(documented_sources("The Graph"), expected_graph)
        self.assertEqual(documented_sources("Dune"), expected_dune)


if __name__ == "__main__":
    unittest.main()
