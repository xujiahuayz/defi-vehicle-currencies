from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.run_provisional_vehicle_transition import (
    compare_runs,
    run_provisional_vehicle_transition,
)


ROOT = Path(__file__).resolve().parents[1]


def sample_panel() -> pd.DataFrame:
    rows = []
    for year, shift in ((2024, 0), (2026, 12)):
        for day in range(1, 41):
            row: dict[str, object] = {"date": pd.Timestamp(year=year, month=1, day=1) + pd.Timedelta(days=day - 1)}
            for scope_index, scope in enumerate(("two_leg", "single_venue_two_leg", "cross_venue_two_leg")):
                stable = 30 + shift + scope_index + (day % 7)
                native = 70 - shift + scope_index + ((day * 3) % 11)
                row[f"cnt_{scope}_stable"] = stable
                row[f"cnt_{scope}_native"] = native
                row[f"usd_within_20pct_{scope}_stable"] = float(stable * (10 + day % 5))
                row[f"usd_within_20pct_{scope}_native"] = float(native * (9 + day % 6))
            rows.append(row)
    return pd.DataFrame(rows)


def test_provisional_run_is_quarantined_and_comparable(tmp_path: Path) -> None:
    first_input = tmp_path / "first.parquet"
    sample_panel().to_parquet(first_input, index=False)
    first = run_provisional_vehicle_transition(
        input_path=first_input,
        output_root=tmp_path / "runs",
        root=ROOT,
        minimum_endpoint_days=2,
    )
    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "provisional_diagnostic_only"
    assert manifest["paper_claim_eligible"] is False
    assert manifest["promotion_prohibited"] is True
    assert manifest["requires_certified_input_rerun"] is True
    estimates = pd.read_json(first / "estimates.provisional.jsonl", lines=True)
    assert len(estimates) == 12
    assert estimates["spec_id"].nunique() == 12

    changed = sample_panel()
    changed.loc[changed["date"].eq(pd.Timestamp("2026-01-10")), "cnt_two_leg_stable"] += 100
    second_input = tmp_path / "second.parquet"
    changed.to_parquet(second_input, index=False)
    second = run_provisional_vehicle_transition(
        input_path=second_input,
        output_root=tmp_path / "runs",
        root=ROOT,
        compare_to=first,
        minimum_endpoint_days=2,
    )
    comparison = compare_runs(first, second)
    assert comparison["source_file_changed"] is True
    assert comparison["analytical_input_changed"] is True
    assert comparison["affected_observations"] == 1
    assert comparison["changed_cells_by_variable"] == {"cnt_two_leg_stable": 1}
    assert any(row["estimate_delta"] != 0 for row in comparison["coefficient_changes"])


def test_source_byte_change_outside_analytical_perimeter_is_distinguished(tmp_path: Path) -> None:
    first_panel = sample_panel()
    first_panel["unused"] = 0
    first_input = tmp_path / "first.parquet"
    first_panel.to_parquet(first_input, index=False)
    first = run_provisional_vehicle_transition(
        input_path=first_input,
        output_root=tmp_path / "runs",
        root=ROOT,
        minimum_endpoint_days=2,
    )
    second_panel = first_panel.copy()
    second_panel["unused"] = np.arange(len(second_panel))
    second_input = tmp_path / "second.parquet"
    second_panel.to_parquet(second_input, index=False)
    second = run_provisional_vehicle_transition(
        input_path=second_input,
        output_root=tmp_path / "runs",
        root=ROOT,
        minimum_endpoint_days=2,
    )
    comparison = compare_runs(first, second)
    assert comparison["source_file_changed"] is True
    assert comparison["analytical_input_changed"] is False
    assert comparison["affected_observations"] == 0
    assert comparison["invariance_review_required"] is False
