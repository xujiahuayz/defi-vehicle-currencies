from __future__ import annotations

import json
import gzip
from pathlib import Path

import pytest

from ddvc.venue_tables import VENUE_HEADERS, VENUE_ORDER, render_venue_coverage, venue_coverage_values
import scripts.analyze.run_venue_coverage_bounds as venue_bounds


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
        "sushiswap_v2", "sushiswap_v3", "curve", "balancer", "fluid",
    )
    values = venue_coverage_values(_rows())
    for _, shares in values:
        assert sum(shares) == pytest.approx(100.0)
    assert "2020 & 2.09 & 75.89" in text
    assert "2024 & 0.00 & 11.63 & 69.06 & 0.00 & 0.49 & 0.01 & 12.57 & 5.86 & 0.38" in text
    assert "2025 & 0.01 & 4.21 & 53.10 & 19.53 & 0.28 & 0.01 & 9.68 & 1.49 & 11.70" in text
    assert "2026 & 0.01 & 2.27 & 46.02 & 31.94 & 0.11 & 0.16 & 12.61 & 0.15 & 6.73" in text
    assert "Pooled & 0.05 & 14.58 & 54.54 & 5.30 & 5.73 & 0.02 & 13.37 & 3.82 & 2.61" in text


def test_fluid_reader_uses_volume_without_inventing_tvl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(venue_bounds, "RAW_FLUID", tmp_path)
    path = tmp_path / "fluid_daily_20260102.jsonl.gz"
    records = [
        {"id": "a", "volumeUSD": 125.5, "tvlUSD": None},
        {"pool": "b", "amount_usd": 74.5},
        {"id": "c", "volumeUSD": venue_bounds.MAX_POOL_DAY_USD + 1, "tvlUSD": None},
        {"id": "d", "volumeUSD": None, "tvlUSD": None},
    ]
    with gzip.open(path, "wt") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    assert venue_bounds.day_volume("fluid", "20260102") == (200.0, 2, 2)
    assert venue_bounds.day_volume("fluid", "20260103") is None


def test_fluid_rows_disclose_partial_date_support() -> None:
    by_year = {
        str(row["year"]): row for row in _rows() if row["venue"] == "fluid"
    }
    assert int(by_year["2024"]["sampled_days"]) == 6
    assert int(by_year["2025"]["sampled_days"]) == 25
    assert int(by_year["2026"]["sampled_days"]) == 9
    assert all(int(row["pool_days_screened_out"]) == 0 for row in by_year.values())


def test_venue_coverage_has_one_paper_consumer_and_publication_artifacts() -> None:
    appendix = (ROOT / "paper" / "sections" / "08-appendix.tex").read_text(encoding="utf-8")
    assert appendix.count(r"\input{../output/tables/venue_coverage.tex}") == 1
    assert "Percentage shares within the seven-venue panel" not in appendix
    assert "Uni v3 & Uni v2" not in appendix
    producer = Path(venue_bounds.__file__).read_text(encoding="utf-8")
    assert "partial calendar support" in producer
    assert "no TVL" in producer
    for suffix in ("tex", "pdf"):
        artifact = ROOT / "output" / "tables" / f"venue_coverage.{suffix}"
        assert artifact.is_file()


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
