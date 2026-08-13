from __future__ import annotations

from contextlib import contextmanager

import numpy as np
import pandas as pd
import pytest

from scripts import run_vehicle_rotation_e0 as rotation


def _panel(symbols: list[tuple[str, str]], start: str, periods: int) -> pd.DataFrame:
    rows = []
    for date_index, date in enumerate(pd.date_range(start, periods=periods)):
        for symbol_index, (symbol, asset_type) in enumerate(symbols):
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "asset_type": asset_type,
                    "intermediate_usd": 100.0 + symbol_index,
                    "endpoint_usd": 100.0,
                    "vehicle_excess_use_ratio": 1.0 + 0.001 * date_index,
                }
            )
    return pd.DataFrame(rows)


def test_fiat_reserve_treatment_comes_from_the_canonical_backing_taxonomy() -> None:
    expected = {
        symbol
        for symbol, regime in rotation.STABLE_BACKING.items()
        if regime == "fiat_reserve"
    }
    assert rotation.FIAT_STABLE == expected
    assert "USDT" in rotation.FIAT_STABLE
    assert "USDe" not in rotation.FIAT_STABLE
    assert "DAI" not in rotation.FIAT_STABLE


def test_break_series_excludes_synthetic_stables_from_the_fiat_reserve_class() -> None:
    base = _panel(
        [("USDC", "stable"), ("USDe", "stable"), ("WETH", "native")],
        "2025-01-01",
        3,
    )
    first = rotation._fiat_native_differential(base)
    base.loc[base.symbol.eq("USDe"), "intermediate_usd"] *= 1_000_000
    second = rotation._fiat_native_differential(base)
    pd.testing.assert_series_equal(first, second)


def test_break_search_recovers_a_known_mean_shift_but_labels_it_descriptive() -> None:
    dates = pd.date_range("2023-01-01", "2026-06-30")
    shift = pd.Timestamp("2025-02-14")
    values = np.where(dates < shift, -0.4, 0.8)
    record = rotation._break_search(pd.Series(values, index=dates))
    assert record is not None
    assert record["break_date"] == "2025-02-14"
    assert record["lens"] == "break_search_descriptive"
    assert "does not identify" in record["interpretation"]


def test_overlapping_named_events_are_not_claimed_as_separately_identified() -> None:
    assert rotation._overlapping_events("2024-12-30") == ["uniswap_v4"]
    assert rotation._overlapping_events("2025-01-31") == ["mica_stablecoin_deadline"]
    assert "ftx_failure" in rotation._overlapping_events("2022-09-15")


def test_joint_pretrend_builds_an_explicit_restriction_matrix() -> None:
    class Model:
        observed = None

        def wald_test(self, *, R, distribution):
            self.observed = (R, distribution)
            return pd.Series({"pvalue": 0.42})

    model = Model()
    names = ["rel_week::-3:treated", "rel_week::-2:treated", "rel_week::0:treated"]
    result = rotation._joint_pretrend_p(model, names, names[:2])
    restriction, distribution = model.observed
    assert result == 0.42
    assert distribution == "chi2"
    np.testing.assert_array_equal(
        restriction,
        np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
    )


def test_event_study_refuses_cluster_robust_inference_with_too_few_tokens() -> None:
    frame = _panel(
        [("USDT", "stable"), ("USDC", "stable"), ("WETH", "native"), ("WBTC", "imported")],
        "2021-03-01",
        900,
    )
    frame["intermediate_usd"] = 2 * rotation.MATERIAL_USD
    output: list[dict] = []
    rotation.lens3_event_studies(output, frame)
    v3 = next(row for row in output if row.get("event") == "uniswap_v3_concentrated_liquidity")
    assert v3["status"] == "underidentified_few_clusters"
    assert v3["clusters"] == 4


def test_temporal_persistence_survives_every_one_and_two_quarter_omission(monkeypatch) -> None:
    supports = ("", "_within_2x", "_within_20pct")

    def row(period_key: str, period: int | str, asset_type: str, intermediate: float) -> dict:
        record = {
            "level": "asset_type",
            "scope": "candidate_currencies",
            "asset_type": asset_type,
            period_key: period,
            "days": 90,
        }
        for suffix in supports:
            record[f"intermediate_usd{suffix}"] = intermediate
            record[f"endpoint_usd{suffix}"] = 50.0
        return record

    annual = [row("year", 2024, "stable", 20.0), row("year", 2024, "native", 80.0)]
    quarterly = []
    for quarter in ("2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"):
        quarterly.extend([
            row("quarter", quarter, "stable", 60.0),
            row("quarter", quarter, "native", 40.0),
        ])
    monkeypatch.setattr(
        rotation,
        "_rows",
        lambda name: annual if name == "vehicle_excess_use.jsonl" else quarterly,
    )

    output: list[dict] = []
    rotation.lens2_temporal_persistence(output)

    assert {record["support"] for record in output} == {
        "all_routes", "within_2x", "within_20pct"
    }
    assert all(record["leave_one_all_positive"] for record in output)
    assert all(record["leave_two_all_positive"] for record in output)
    assert all(record["post_quarters"] == 6 for record in output)


def test_stable_concentration_and_duopoly_share_one_existing_owner(monkeypatch) -> None:
    rows = []
    observations = {
        2024: {"USDT": (30.0, 0.10, 0.08), "USDC": (60.0, 0.15, 0.12), "DAI": (10.0, 0.05, 0.05)},
        2025: {"USDT": (50.0, 0.20, 0.10), "USDC": (40.0, 0.20, 0.15), "DAI": (10.0, 0.05, 0.05)},
        2026: {"USDT": (55.0, 0.30, 0.15), "USDC": (40.0, 0.23, 0.16), "DAI": (5.0, 0.07, 0.06)},
    }
    for year, tokens in observations.items():
        for symbol, (usd, intermediate_share, endpoint_share) in tokens.items():
            rows.append({
                "level": "token",
                "scope": "candidate_currencies",
                "asset_type": "stable",
                "year": year,
                "symbol": symbol,
                "intermediate_usd": usd,
                "intermediate_share": intermediate_share,
                "endpoint_share": endpoint_share,
            })
    monkeypatch.setattr(rotation, "_rows", lambda _name: rows)

    output: list[dict] = []
    rotation.lens3_stable_concentration(output)

    concentration = {
        row["year"]: row for row in output if row["lens"] == "stable_concentration"
    }
    assert concentration[2024]["usdt_usdc_cr2"] == pytest.approx(0.9)
    assert concentration[2026]["usdt_usdc_cr2"] == pytest.approx(0.95)
    decomposition = [
        row for row in output
        if row["lens"] == "stable_duopoly_decomposition"
        and row["comparison_year"] == 2026
    ]
    assert {row["bucket"] for row in decomposition} == {"USDT", "USDC", "other"}
    assert sum(row["share_of_stable_intermediate_change"] for row in decomposition) == pytest.approx(1.0)
    assert sum(row["share_of_stable_gap_change"] for row in decomposition) == pytest.approx(1.0)


def test_main_binds_the_annual_and_quarterly_owner_inputs(monkeypatch) -> None:
    observed = []

    @contextmanager
    def current(inputs, *, consumer):
        observed.append((tuple(inputs), consumer))
        yield

    written = []
    monkeypatch.setattr(rotation, "current_artifacts", current)
    monkeypatch.setattr(rotation, "lens1_cross_section", lambda out: out.append({"lens": "test"}))
    monkeypatch.setattr(rotation, "lens2_temporal_persistence", lambda _out: None)
    monkeypatch.setattr(rotation, "lens3_stable_concentration", lambda _out: None)
    monkeypatch.setattr(rotation, "lens_did_annual", lambda _out: None)
    monkeypatch.setattr(rotation, "_daily_panel", lambda: (None, "deferred"))
    monkeypatch.setattr(
        rotation,
        "write_exhibit",
        lambda _frame, _out, **kwargs: written.append(kwargs),
    )

    assert rotation.main() == 0
    assert observed == [
        ((rotation.ANNUAL_INPUT, rotation.QUARTERLY_INPUT), "vehicle-rotation E0")
    ]
    assert written[0]["inputs"] == [rotation.ANNUAL_INPUT, rotation.QUARTERLY_INPUT]


def test_main_refuses_stale_base_exhibits_without_rewriting_output(monkeypatch) -> None:
    @contextmanager
    def stale_inputs(*_args, **_kwargs):
        raise RuntimeError("stale source")
        yield

    wrote = []
    monkeypatch.setattr(rotation, "current_artifacts", stale_inputs)
    monkeypatch.setattr(rotation, "write_exhibit", lambda *_args, **_kwargs: wrote.append(True))
    assert rotation.main() == 2
    assert wrote == []
