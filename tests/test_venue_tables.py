from __future__ import annotations

import json
from pathlib import Path

import pytest

from ddvc.provenance import sidecar_path, verify
from ddvc.venue_tables import VENUE_HEADERS, VENUE_ORDER, render_venue_coverage, venue_coverage_values


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output" / "exhibits" / "venue_volume_by_year.jsonl"
TABLE = ROOT / "output" / "tables" / "venue_coverage.tex"


def _rows() -> list[dict[str, object]]:
    return [json.loads(line) for line in INPUT.read_text(encoding="utf-8").splitlines()]


def test_venue_coverage_fragment_equals_named_renderer() -> None:
    assert TABLE.read_text(encoding="utf-8") == render_venue_coverage(_rows())


def test_venue_coverage_order_and_sums() -> None:
    text = TABLE.read_text(encoding="utf-8")
    assert "Year & " + " & ".join(VENUE_HEADERS) in text
    assert VENUE_ORDER == (
        "uniswap_v1", "uniswap_v2", "uniswap_v3", "uniswap_v4",
        "sushiswap_v2", "sushiswap_v3", "curve", "balancer",
    )
    values = venue_coverage_values(_rows())
    for _, shares in values:
        assert sum(shares) == pytest.approx(100.0)
    assert "2020 & 2.09 & 75.89" in text
    assert "Pooled & 0.05 & 14.97 & 56.00 & 5.45 & 5.88 & 0.02 & 13.73 & 3.92" in text


def test_venue_coverage_has_one_paper_consumer_and_current_lineage() -> None:
    appendix = (ROOT / "paper" / "sections" / "08-appendix.tex").read_text(encoding="utf-8")
    assert appendix.count(r"\input{../output/tables/venue_coverage.tex}") == 1
    assert "Percentage shares within the seven-venue panel" not in appendix
    assert "Uni v3 & Uni v2" not in appendix
    expected = {
        "output/exhibits/venue_volume_by_year.jsonl",
        "data/manifests/output/exhibits/venue_volume_by_year.jsonl.prov.json",
    }
    for suffix in ("tex", "pdf"):
        artifact = ROOT / "output" / "tables" / f"venue_coverage.{suffix}"
        assert verify(artifact)["status"] == "ok"
        record = json.loads(sidecar_path(artifact).read_text(encoding="utf-8"))
        assert {str(item["path"]) for item in record["inputs"]} == expected


def test_venue_coverage_rejects_missing_and_duplicate_rows() -> None:
    rows = _rows()
    first_displayed = next(
        index for index, row in enumerate(rows)
        if row["year"] == "2020" and row["venue"] == "uniswap_v1"
    )
    with pytest.raises(ValueError, match="missing"):
        venue_coverage_values(rows[:first_displayed] + rows[first_displayed + 1:])
    with pytest.raises(ValueError, match="duplicate"):
        venue_coverage_values(rows + [next(row for row in rows if row["year"] == "2020")])
