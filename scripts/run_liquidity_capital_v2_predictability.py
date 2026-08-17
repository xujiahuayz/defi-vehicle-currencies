#!/usr/bin/env python3
"""Estimate V2 deposited-capital and vehicle-use predictability in both directions.

This runner consumes only the independently released V2 candidate-day and
exact-horizon panels. It never opens, fills, or conditions execution on a V3
flow artifact. The estimates are predictive associations, not causal feedback.

Three components live here and share one bound generation. The
quantity-contract component proves the V2-only family did not carry a V3 flow
quantity across from the broader liquidity-allocation design. The predictability
component fits the claim's registered perimeter. The influence component answers
the `liquidity_capital_v2_e0` family's `influence_concentration` attack: it
measures where the support's capital mass sits, then refits the full-calendar
perimeter dropping one candidate or one high-contribution pool at a time and
restates the claim's own decision rule on each remainder. They stay in one
runner because all three are about the same V2 quantity boundary; splitting the
fit owner is how a diagnostic quietly acquires a second inference.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.liquidity_capital_v2_influence import (
    ATTACK_ID as INFLUENCE_ATTACK_ID,
)
from ddvc.analysis.liquidity_capital_v2_influence import (
    candidate_capital_block,
    candidate_contribution_ledger,
    capital_reconciliation,
    leave_out_units,
    open_candidate_capital,
    pool_contribution_ledger,
    rebuild_candidate_day,
    top_pool_keys,
    within_transform_weight,
)
from ddvc.analysis.regression import absorb_fixed_effects, holm_adjusted_pvalues, ols_clustered
from ddvc.capital_release import (
    CAPITAL_RELEASE_POINTER_RELATIVE,
    current_capital_release,
    resolve_capital_release,
)
from ddvc.liquidity_predictability import (
    HORIZONS,
    ROUTE_FAMILY,
    V2_CANDIDATE_DAY_COLUMNS,
    V2_FAMILY,
    V2_QUANTITY_KIND,
    V3_LAUNCH_DATE,
    build_v2_exact_horizon_panel,
    validate_v2_candidate_day_panel,
    validate_v2_exact_horizon_panel,
)
from ddvc.model_artifacts import (
    attach_spec_ids,
    model_artifact_context,
    require_released_model_inputs,
    write_model_exhibit,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.provenance import stamp
from ddvc.runtime import atomic_output


CANDIDATE_DAY_INPUT = REPO_ROOT / "data/processed/liquidity_capital_v2_candidate_day.parquet"
EXACT_HORIZON_INPUT = REPO_ROOT / "data/processed/liquidity_capital_v2_exact_horizons.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/liquidity_capital_v2_predictability.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/liquidity_capital_v2_support.jsonl"
TABLE_OUTPUT = OUTPUT_DIR / "tables/liquidity_capital_v2_predictability.tex"
QUANTITY_CONTRACT_OUTPUT = (
    OUTPUT_DIR / "exhibits/e0_liquidity_capital_v2_quantity_contract.jsonl"
)
QUANTITY_CONTRACT_TABLE_OUTPUT = (
    OUTPUT_DIR / "tables/e0_liquidity_capital_v2_quantity_contract.tex"
)
INFLUENCE_ESTIMATE_OUTPUT = (
    OUTPUT_DIR / "exhibits/e0_liquidity_capital_v2_influence_estimates.jsonl"
)
INFLUENCE_SUPPORT_OUTPUT = (
    OUTPUT_DIR / "exhibits/e0_liquidity_capital_v2_influence_support.jsonl"
)
ATTACK_DISPOSITION_OUTPUT = (
    OUTPUT_DIR / "exhibits/e0_liquidity_capital_v2_attack_disposition.jsonl"
)
PRIMARY_HORIZONS = (1, 7, 30)
DK_LAG = 30
CODE_SOURCES = [
    "scripts/run_liquidity_capital_v2_predictability.py",
    "src/ddvc/liquidity_predictability.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/model_artifacts.py",
]
INFLUENCE_CODE_SOURCES = [
    *CODE_SOURCES,
    "src/ddvc/analysis/liquidity_capital_v2_influence.py",
    "src/ddvc/capital_release.py",
]
INFLUENCE_COMPONENT_FAMILY = "liquidity_capital_v2_influence_component"
# The `liquidity_capital_v2_e0` attacks this runner produces evidence for, and
# where each one lands. It is not the family's full perimeter: the two
# price-covariate attacks are outside it until the token-price panel enters the
# claim-input perimeter. An exploration plan must cite these exhibits and no
# others from this runner.
QUANTITY_CONTRACT_ATTACK_COVERAGE = ("v2_stock_v3_flow_separation",)
PREDICTABILITY_ATTACK_COVERAGE = (
    "bidirectional_exact_horizons",
    "absolute_share_sign_stability",
    "v2_calendar_perimeter_subsamples",
    "multiplicity_support_ledger",
)
INFLUENCE_ATTACK_COVERAGE = (INFLUENCE_ATTACK_ID,)
INFLUENCE_SPEC_ID_COLUMNS = (
    "perimeter",
    "leave_out_kind",
    "leave_out_unit",
    "direction",
    "route_measure",
    "capital_measure",
    "horizon_days",
)
ROUTE_MEASURES = {
    "intermediary_episode_share": "future_intermediary_episode_share_change",
    "vehicle_excess_use_count_ratio": "future_vehicle_excess_use_count_ratio_change",
}
CAPITAL_MEASURES = {
    "log_deposited_capital": "log1p_deposited_capital_usd",
    "five_candidate_capital_share": "five_candidate_capital_share",
}


def _joined(values: object) -> str:
    unique = sorted({str(value) for value in pd.Series(values).dropna()})
    return "|".join(unique) if unique else "none"


def _label(value: object) -> str:
    return str(value).replace("_", " ")


def _panel_quantity_contract_row(
    panel_name: str, panel: pd.DataFrame
) -> dict[str, object]:
    columns = [str(column) for column in panel.columns]
    v3_prefixed = sorted(column for column in columns if column.startswith("v3_"))
    v3_signed_flow = sorted(
        column for column in v3_prefixed if "signed" in column and "flow" in column
    )
    v3_gross_flow = sorted(
        column for column in v3_prefixed if "gross" in column and "flow" in column
    )
    v2_flow = sorted(
        column for column in columns if column.startswith("v2_") and "flow" in column
    )
    if v3_prefixed:
        raise ValueError(
            f"{panel_name} carries V3-prefixed columns inside the V2-only family: "
            f"{v3_prefixed[:10]}"
        )
    if v2_flow:
        raise ValueError(
            f"{panel_name} carries V2-prefixed flow columns inside the stock family: "
            f"{v2_flow[:10]}"
        )
    quantity_kinds = sorted(
        str(value) for value in panel["v2_quantity_kind"].dropna().unique()
    )
    if quantity_kinds != [V2_QUANTITY_KIND]:
        raise ValueError(
            f"{panel_name} changed the V2 quantity contract: {quantity_kinds}"
        )
    v2_families = sorted(
        str(value) for value in panel["v2_measurement_family"].dropna().unique()
    )
    if v2_families != [V2_FAMILY]:
        raise ValueError(
            f"{panel_name} changed the V2 measurement family: {v2_families}"
        )
    route_families = sorted(
        str(value) for value in panel["route_measurement_family"].dropna().unique()
    )
    if route_families != [ROUTE_FAMILY]:
        raise ValueError(
            f"{panel_name} changed the route measurement family: {route_families}"
        )
    origin_dates = pd.to_datetime(panel["origin_date"], errors="coerce")
    if origin_dates.isna().any():
        raise ValueError(f"{panel_name} contains an invalid origin date")
    candidate_days = panel[["origin_date", "candidate_address"]].drop_duplicates()
    supported_dates = (
        panel.loc[panel["v2_capital_day_supported"].astype(bool), "origin_date"]
        .drop_duplicates()
    )
    row: dict[str, object] = {
        "family": "liquidity_capital_v2_quantity_contract_component",
        "attack_id": QUANTITY_CONTRACT_ATTACK_COVERAGE[0],
        "record": "panel_quantity_contract",
        "panel": panel_name,
        "measurement_family": V2_FAMILY,
        "route_measurement_family": ROUTE_FAMILY,
        "quantity_kind": V2_QUANTITY_KIND,
        "contract_validation_status": "passed",
        "v2_capital_validation_statuses": _joined(
            panel["v2_capital_validation_status"]
        ),
        "rows": int(len(panel)),
        "origin_candidate_days": int(len(candidate_days)),
        "origin_dates": int(origin_dates.nunique()),
        "capital_supported_origin_dates": int(supported_dates.nunique()),
        "first_origin_date": origin_dates.min(),
        "last_origin_date": origin_dates.max(),
        "candidate_count": int(panel["candidate_address"].nunique()),
        "v3_prefixed_column_count": int(len(v3_prefixed)),
        "v3_prefixed_columns_present": False,
        "v3_signed_flow_columns_present": bool(v3_signed_flow),
        "v3_gross_flow_columns_present": bool(v3_gross_flow),
        "v3_signed_or_gross_flow_column_count": int(
            len(set(v3_signed_flow) | set(v3_gross_flow))
        ),
        "forbidden_v3_columns": "none",
        "forbidden_v2_flow_columns": "none",
    }
    if "horizon_days" in panel.columns:
        horizon_values = sorted(int(value) for value in panel["horizon_days"].unique())
        row["horizon_days"] = "|".join(str(value) for value in horizon_values)
        row["horizon_count"] = int(len(horizon_values))
        row["horizon_contract"] = _joined(panel["horizon_contract"])
    else:
        row["horizon_days"] = "not_applicable"
        row["horizon_count"] = 0
        row["horizon_contract"] = "not_applicable"
    return row


def _assert_released_origin_identity(
    candidate_day: pd.DataFrame, exact_horizons: pd.DataFrame
) -> None:
    keys = ["origin_date", "candidate_address"]
    expected = (
        candidate_day.sort_values(keys)
        .loc[:, list(V2_CANDIDATE_DAY_COLUMNS)]
        .reset_index(drop=True)
    )
    actual = (
        exact_horizons.sort_values([*keys, "horizon_days"])
        .drop_duplicates(keys)
        .loc[:, list(V2_CANDIDATE_DAY_COLUMNS)]
        .sort_values(keys)
        .reset_index(drop=True)
    )
    expected["origin_date"] = pd.to_datetime(expected["origin_date"])
    actual["origin_date"] = pd.to_datetime(actual["origin_date"])
    try:
        pd.testing.assert_frame_equal(
            actual,
            expected,
            check_dtype=False,
            check_categorical=False,
            check_exact=False,
            rtol=1e-10,
            atol=1e-10,
        )
    except AssertionError as error:
        raise ValueError(
            "released V2 exact-horizon origins do not reproduce the released "
            "V2 candidate-day panel"
        ) from error


def build_v2_quantity_contract(
    candidate_day: pd.DataFrame, exact_horizons: pd.DataFrame
) -> pd.DataFrame:
    """Publish the V2-only quantity boundary before any fitted estimate."""

    validate_v2_candidate_day_panel(candidate_day)
    validate_v2_exact_horizon_panel(exact_horizons)
    _assert_released_origin_identity(candidate_day, exact_horizons)
    rows = [
        _panel_quantity_contract_row("released_v2_candidate_day_panel", candidate_day),
        _panel_quantity_contract_row("released_v2_exact_horizon_panel", exact_horizons),
        {
            "family": "liquidity_capital_v2_quantity_contract_component",
            "attack_id": QUANTITY_CONTRACT_ATTACK_COVERAGE[0],
            "record": "origin_panel_reconciliation",
            "panel": "released_candidate_day_to_exact_horizon_origin_rows",
            "measurement_family": V2_FAMILY,
            "route_measurement_family": ROUTE_FAMILY,
            "quantity_kind": V2_QUANTITY_KIND,
            "contract_validation_status": "passed",
            "v2_capital_validation_statuses": "same_as_released_candidate_day",
            "rows": int(len(candidate_day)),
            "origin_candidate_days": int(
                candidate_day[["origin_date", "candidate_address"]]
                .drop_duplicates()
                .shape[0]
            ),
            "origin_dates": int(pd.to_datetime(candidate_day["origin_date"]).nunique()),
            "capital_supported_origin_dates": int(
                candidate_day.loc[
                    candidate_day["v2_capital_day_supported"].astype(bool),
                    "origin_date",
                ].nunique()
            ),
            "first_origin_date": pd.to_datetime(candidate_day["origin_date"]).min(),
            "last_origin_date": pd.to_datetime(candidate_day["origin_date"]).max(),
            "candidate_count": int(candidate_day["candidate_address"].nunique()),
            "horizon_days": "not_applicable",
            "horizon_count": 0,
            "horizon_contract": "exact_horizon_origin_rows_match_candidate_day",
            "v3_prefixed_column_count": 0,
            "v3_prefixed_columns_present": False,
            "v3_signed_flow_columns_present": False,
            "v3_gross_flow_columns_present": False,
            "v3_signed_or_gross_flow_column_count": 0,
            "forbidden_v3_columns": "none",
            "forbidden_v2_flow_columns": "none",
        },
    ]
    return pd.DataFrame(rows)


def _render_quantity_contract_table(contract: pd.DataFrame) -> str:
    rows = contract[contract["record"].eq("panel_quantity_contract")]
    lines = [
        r"\begin{tabular}{lllllrr}",
        r"\toprule",
        r"Panel & Measurement family & Quantity & Validation & V3 flow cols & Origin days & Rows \\",
        r"\midrule",
    ]
    for row in rows.itertuples(index=False):
        panel = _label(row.panel).replace("released v2 ", "").replace(" panel", "")
        lines.append(
            f"{panel} & {_label(row.measurement_family)} & "
            f"{_label(row.quantity_kind)} & {_label(row.contract_validation_status)} & "
            f"{'none' if not row.v3_prefixed_columns_present else row.forbidden_v3_columns} & "
            f"{int(row.origin_dates):,} & {int(row.rows):,} \\\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines) + "\n"


def run_quantity_contract() -> tuple[Path, Path]:
    context = model_artifact_context()
    inputs = [CANDIDATE_DAY_INPUT, EXACT_HORIZON_INPUT]
    with require_released_model_inputs(
        context, inputs, consumer="V2 liquidity quantity-contract component"
    ) as panel_inputs:
        candidate_day = pd.read_parquet(CANDIDATE_DAY_INPUT)
        exact_horizons = pd.read_parquet(EXACT_HORIZON_INPUT)
        contract = build_v2_quantity_contract(candidate_day, exact_horizons)
        notes = (
            "E0 V2 stock versus V3 flow separation attack: the released V2 "
            "candidate-day and exact-horizon panels validate as deposited-capital "
            "stock panels, carry the V2 measurement family and deposited_capital "
            "quantity kind, expose no V3-prefixed signed or gross flow columns, "
            "and the exact-horizon origins reproduce the released candidate-day "
            "panel before any fitted estimate is consumed"
        )
        write_model_exhibit(
            contract,
            QUANTITY_CONTRACT_OUTPUT,
            role="support",
            context=context,
            code_sources=CODE_SOURCES,
            inputs=panel_inputs,
            notes=notes,
        )
        with atomic_output(QUANTITY_CONTRACT_TABLE_OUTPUT) as temporary:
            temporary.write_text(
                _render_quantity_contract_table(contract), encoding="utf-8"
            )
        stamp(
            QUANTITY_CONTRACT_TABLE_OUTPUT,
            code_sources=CODE_SOURCES,
            inputs=[context.d3_certificate_path, QUANTITY_CONTRACT_OUTPUT],
            rows=int(
                contract["record"].eq("panel_quantity_contract").astype(int).sum()
            ),
            notes=notes,
        )
    return QUANTITY_CONTRACT_OUTPUT, QUANTITY_CONTRACT_TABLE_OUTPUT


def run_attack_disposition() -> Path:
    """Publish the two attacks that the released V2 perimeter cannot fit."""

    context = model_artifact_context()
    frame = pd.DataFrame(
        [
            {
                "family": "liquidity_capital_v2_e0",
                "attack_id": "common_shock_price_risk_placebos",
                "fitted": False,
                "disposition": "blocked_claim_input_perimeter",
                "required_input": "data/processed/token_price_daily.parquet",
                "scientific_reason": (
                    "The current D3 claim-input perimeter excludes the price panel; "
                    "date-global controls are absorbed by the primary origin-date fixed "
                    "effects, so an explicit-control diagnostic must be registered "
                    "without those date effects in a later generation."
                ),
            },
            {
                "family": "liquidity_capital_v2_e0",
                "attack_id": "stress_heterogeneity",
                "fitted": False,
                "disposition": "blocked_claim_input_perimeter",
                "required_input": "data/processed/token_price_daily.parquet",
                "scientific_reason": (
                    "The current D3 claim-input perimeter excludes the price panel needed "
                    "to define a look-ahead-safe stress state; no proxy stress label is "
                    "substituted into the released V2 deposited-capital estimand."
                ),
            },
        ]
    )
    write_model_exhibit(
        frame,
        ATTACK_DISPOSITION_OUTPUT,
        role="support",
        context=context,
        code_sources=CODE_SOURCES,
        inputs=[context.d3_certificate_path],
        notes=(
            "Exact E0 disposition of the common-shock and stress attacks that cannot "
            "be fitted inside the current V2 claim-input perimeter"
        ),
    )
    return ATTACK_DISPOSITION_OUTPUT


def _perimeter(panel: pd.DataFrame, name: str) -> pd.DataFrame:
    data = panel.copy()
    if name == "pre_v3_launch":
        data = data[data["target_date"] < V3_LAUNCH_DATE]
    elif name == "post_v3_launch":
        data = data[data["origin_date"] >= V3_LAUNCH_DATE]
    elif name != "full_v2_calendar":
        raise ValueError(f"unknown V2 calendar perimeter: {name}")
    return data


def _calendar_score_hac_covariance(
    x: np.ndarray,
    residual: np.ndarray,
    dates: pd.Series,
    *,
    lag_days: int,
    scale: float,
) -> np.ndarray:
    """Aggregate scores by date and preserve zero-score dates between observations."""

    design = np.asarray(x, dtype=float)
    errors = np.asarray(residual, dtype=float).reshape(-1)
    if design.ndim == 1:
        design = design[:, None]
    parsed_dates = pd.to_datetime(dates, errors="coerce").dt.normalize()
    if (
        lag_days < 0
        or len(design) != len(errors)
        or len(design) != len(parsed_dates)
        or parsed_dates.isna().any()
    ):
        raise ValueError("calendar score HAC inputs are invalid")
    scores = pd.DataFrame(design * errors[:, None])
    scores.insert(0, "origin_date", parsed_dates.to_numpy())
    daily = scores.groupby("origin_date", sort=True).sum()
    calendar = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(calendar, fill_value=0.0)
    score_array = daily.to_numpy(float)
    meat = score_array.T @ score_array
    for offset in range(1, min(lag_days, len(score_array) - 1) + 1):
        weight = 1.0 - offset / (lag_days + 1.0)
        autocovariance = score_array[offset:].T @ score_array[:-offset]
        meat += weight * (autocovariance + autocovariance.T)
    xtx_inverse = np.linalg.pinv(design.T @ design)
    return scale * xtx_inverse @ meat @ xtx_inverse


def _fit_fe(
    sample: pd.DataFrame,
    outcome: str,
    predictor: str,
    *,
    expected_candidates: int = 5,
    with_two_way: bool = True,
) -> tuple[object, object | None]:
    """Fit one absorbed specification under the claim's own covariance contract.

    `expected_candidates` exists for the leave-one-candidate influence refits and
    for nothing else: the headline perimeter is the fixed five, and a fit that
    silently lost a candidate must still fail. The two-way candidate sensitivity
    is skipped when a candidate is dropped, because four clusters is below the
    five the registered sensitivity already declares as its own limitation.
    """

    required = [outcome, predictor, "candidate_address", "origin_date"]
    data = sample[required].replace([np.inf, -np.inf], np.nan).dropna().copy()
    if (
        len(data) < 100
        or data["origin_date"].nunique() < 20
        or data["candidate_address"].nunique() != expected_candidates
    ):
        raise ValueError("V2 predictability fit has insufficient candidate-date support")
    residual = absorb_fixed_effects(
        data[[outcome, predictor]], data["candidate_address"], data["origin_date"]
    )
    primary_base = ols_clustered(
        residual[outcome], residual[[predictor]], data["origin_date"],
        add_constant=False,
        absorbed_groups=(data["candidate_address"], data["origin_date"]),
        min_observations=100,
        min_clusters=20,
    )
    x = residual[[predictor]].to_numpy(float)
    y = residual[outcome].to_numpy(float)
    fitted_residual = y - x @ primary_base.beta
    n = primary_base.n_observations
    denominator_dof = n - 1 - primary_base.absorbed_degrees_of_freedom
    if denominator_dof <= 0:
        raise ValueError("V2 predictability fit has no residual degrees of freedom")
    observed_dates = data["origin_date"].nunique()
    scale = (observed_dates / (observed_dates - 1)) * ((n - 1) / denominator_dof)
    primary = replace(
        primary_base,
        covariance=_calendar_score_hac_covariance(
            x,
            fitted_residual,
            data["origin_date"],
            lag_days=DK_LAG,
            scale=scale,
        ),
    )
    two_way = (
        ols_clustered(
            residual[outcome], residual[[predictor]], data["candidate_address"],
            add_constant=False,
            absorbed_groups=(data["candidate_address"], data["origin_date"]),
            min_observations=100,
            min_clusters=5,
            additional_clusters=(data["origin_date"],),
        )
        if with_two_way
        else None
    )
    if not np.isfinite(primary.beta[0]) or not np.isfinite(primary.standard_errors[0]):
        raise ValueError("V2 predictability primary covariance is not estimable")
    return primary, two_way


def _month_block_bootstrap(
    sample: pd.DataFrame,
    outcome: str,
    predictor: str,
    *,
    repetitions: int,
    seed: int,
) -> tuple[float, float, int]:
    """Resample whole calendar months and re-absorb both fixed effects."""

    data = sample[[outcome, predictor, "candidate_address", "origin_date"]].dropna().copy()
    data["month"] = data["origin_date"].dt.to_period("M").astype(str)
    months = sorted(data["month"].unique())
    if len(months) < 12:
        return np.nan, np.nan, 0
    rng = np.random.default_rng(seed)
    estimates: list[float] = []
    for repetition in range(repetitions):
        pieces = []
        for draw, month in enumerate(rng.choice(months, size=len(months), replace=True)):
            piece = data[data["month"].eq(month)].copy()
            piece["bootstrap_date"] = str(draw) + ":" + piece["origin_date"].astype(str)
            pieces.append(piece)
        boot = pd.concat(pieces, ignore_index=True)
        residual = absorb_fixed_effects(
            boot[[outcome, predictor]], boot["candidate_address"], boot["bootstrap_date"]
        ).dropna()
        x = residual[predictor].to_numpy(float)
        denominator = float(x @ x)
        if denominator > 0:
            estimates.append(float(x @ residual[outcome].to_numpy(float) / denominator))
    if len(estimates) < max(20, repetitions // 2):
        return np.nan, np.nan, len(estimates)
    values = np.asarray(estimates)
    p_value = min(1.0, 2.0 * min(float((values <= 0).mean()), float((values >= 0).mean())))
    return float(values.std(ddof=1)), p_value, len(values)


def _attach_full_calendar_decision(estimates: pd.DataFrame) -> pd.DataFrame:
    """Adjudicate exact reciprocal pairs on the full calendar and nowhere else."""

    output = estimates.copy()
    output["adjudication_primary"] = (
        output["perimeter"].eq("full_v2_calendar")
        & output["primary_horizon"]
    )
    output["analysis_role"] = np.select(
        [
            output["perimeter"].eq("full_v2_calendar")
            & output["primary_horizon"],
            output["perimeter"].eq("full_v2_calendar"),
        ],
        ["primary_adjudication", "long_horizon_sensitivity"],
        default="calendar_heterogeneity_only",
    )
    output["reciprocal_pair_pass"] = pd.Series(pd.NA, index=output.index, dtype="boolean")
    output["reciprocal_positive_significant_horizons"] = pd.NA
    output["alternative_sign_concordant"] = pd.Series(
        pd.NA, index=output.index, dtype="boolean"
    )
    output["claim_decision_pass"] = pd.Series(pd.NA, index=output.index, dtype="boolean")
    full = output[output["perimeter"].eq("full_v2_calendar")]
    pair_records: dict[str, tuple[bool, str]] = {}
    for pair_id, pair in full.groupby("measure_pair_id", sort=False):
        qualifying: list[int] = []
        for horizon in PRIMARY_HORIZONS:
            rows = pair[pair["horizon_days"].eq(horizon)].set_index("direction")
            if set(rows.index) != {"route_to_capital", "capital_to_route"}:
                raise ValueError(f"reciprocal V2 pair is incomplete: {pair_id}, {horizon}")
            if (
                rows["coefficient"].gt(0).all()
                and rows["p_value_holm"].lt(0.05).all()
            ):
                qualifying.append(horizon)
        long_rows = pair[pair["horizon_days"].eq(120)]
        if set(long_rows["direction"]) != {"route_to_capital", "capital_to_route"}:
            raise ValueError(f"reciprocal V2 long-horizon pair is incomplete: {pair_id}")
        significant_reversal = (
            long_rows["coefficient"].lt(0) & long_rows["p_value"].lt(0.05)
        ).any()
        pair_records[pair_id] = (
            len(qualifying) >= 2 and not bool(significant_reversal),
            "|".join(str(value) for value in qualifying) or "none",
        )

    route_concordance: dict[str, bool] = {}
    for route_measure, rows in full[full["primary_horizon"]].groupby(
        "route_measure", sort=False
    ):
        medians = rows.groupby(["capital_measure", "direction"])["coefficient"].median()
        significant_negative = (
            rows["coefficient"].lt(0) & rows["p_value_holm"].lt(0.05)
        ).any()
        route_concordance[route_measure] = bool(
            len(medians) == len(CAPITAL_MEASURES) * 2
            and medians.gt(0).all()
            and not significant_negative
        )
    claim_pass = any(
        pair_pass
        and route_concordance.get(
            full.loc[full["measure_pair_id"].eq(pair_id), "route_measure"].iloc[0],
            False,
        )
        for pair_id, (pair_pass, _horizons) in pair_records.items()
    )
    for pair_id, (pair_pass, horizons) in pair_records.items():
        pair_mask = output["perimeter"].eq("full_v2_calendar") & output[
            "measure_pair_id"
        ].eq(pair_id)
        route_measure = output.loc[pair_mask, "route_measure"].iloc[0]
        output.loc[pair_mask, "reciprocal_pair_pass"] = pair_pass
        output.loc[
            pair_mask, "reciprocal_positive_significant_horizons"
        ] = horizons
        output.loc[pair_mask, "alternative_sign_concordant"] = route_concordance[
            route_measure
        ]
        output.loc[pair_mask, "claim_decision_pass"] = claim_pass
    output["decision_rule"] = (
        "full_calendar_only; exact route/capital measure pair positive with Holm q<0.05 "
        "in both directions at the same at least two of 1/7/30 days; no significantly "
        "negative 120-day reversal; positive primary-horizon median and no significant "
        "negative coefficient under both capital measurement alternatives"
    )
    return output


def estimate_v2_predictability(
    panel: pd.DataFrame, *, bootstrap_repetitions: int = 199, seed: int = 57291
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit every locked V2 direction, measure, horizon, and calendar perimeter."""

    validate_v2_exact_horizon_panel(panel, HORIZONS)
    panel = panel.copy()
    panel["origin_date"] = pd.to_datetime(panel["origin_date"])
    panel["target_date"] = pd.to_datetime(panel["target_date"])
    rows: list[dict[str, object]] = []
    support: list[dict[str, object]] = []
    perimeters = ("full_v2_calendar", "pre_v3_launch", "post_v3_launch")
    for perimeter in perimeters:
        scoped = _perimeter(panel, perimeter)
        for horizon in HORIZONS:
            horizon_data = scoped[scoped["horizon_days"].eq(horizon)]
            for route_measure, future_route in ROUTE_MEASURES.items():
                for capital_label, capital_suffix in CAPITAL_MEASURES.items():
                    capital_level = f"v2_{capital_suffix}"
                    future_capital = f"future_v2_{capital_suffix}_change"
                    for direction, outcome, predictor in (
                        ("route_to_capital", future_capital, route_measure),
                        ("capital_to_route", future_route, capital_level),
                    ):
                        fit_sample = horizon_data[[outcome, predictor, "candidate_address", "origin_date"]].dropna()
                        support.append({
                            "measurement_family": "v2_family_deposited_capital_stock",
                            "perimeter": perimeter,
                            "horizon_days": horizon,
                            "direction": direction,
                            "route_measure": route_measure,
                            "capital_measure": capital_label,
                            "measure_pair_id": f"{route_measure}__{capital_label}",
                            "observations": int(len(fit_sample)),
                            "origin_dates": int(fit_sample["origin_date"].nunique()),
                            "candidates": int(fit_sample["candidate_address"].nunique()),
                            "origin_start": fit_sample["origin_date"].min(),
                            "origin_end": fit_sample["origin_date"].max(),
                        })
                        primary, two_way = _fit_fe(horizon_data, outcome, predictor)
                        boot_se, boot_p, boot_n = _month_block_bootstrap(
                            horizon_data, outcome, predictor,
                            repetitions=bootstrap_repetitions,
                            seed=seed + horizon + len(rows),
                        )
                        se = float(primary.standard_errors[0])
                        rows.append({
                            "claim_id": "liquidity_capital_v2_predictability",
                            "measurement_family": "v2_family_deposited_capital_stock",
                            "perimeter": perimeter,
                            "horizon_days": horizon,
                            "primary_horizon": horizon in PRIMARY_HORIZONS,
                            "direction": direction,
                            "route_measure": route_measure,
                            "capital_measure": capital_label,
                            "measure_pair_id": f"{route_measure}__{capital_label}",
                            "outcome": outcome,
                            "predictor": predictor,
                            "coefficient": float(primary.beta[0]),
                            "standard_error": se,
                            "t_statistic": float(primary.t_statistics[0]),
                            "p_value": float(primary.p_values[0]),
                            "confidence_interval_lower": float(primary.beta[0] - 1.96 * se),
                            "confidence_interval_upper": float(primary.beta[0] + 1.96 * se),
                            "two_way_candidate_date_standard_error": float(two_way.standard_errors[0]),
                            "two_way_candidate_date_p_value": float(two_way.p_values[0]),
                            "month_block_bootstrap_standard_error": boot_se,
                            "month_block_bootstrap_p_value": boot_p,
                            "month_block_bootstrap_successful_refits": boot_n,
                            "observations": primary.n_observations,
                            "origin_date_clusters": primary.n_clusters,
                            "candidate_clusters": int(fit_sample["candidate_address"].nunique()),
                            "calendar_span_days": (
                                int(
                                    (fit_sample["origin_date"].max() - fit_sample["origin_date"].min()).days
                                )
                                + 1
                            ),
                            "zero_score_calendar_days": (
                                int(
                                    (fit_sample["origin_date"].max() - fit_sample["origin_date"].min()).days
                                )
                                + 1
                                - int(fit_sample["origin_date"].nunique())
                            ),
                            "fixed_effects": "candidate_and_origin_date",
                            "primary_covariance": "candidate_date_score_hac_bartlett_30_calendar_days_zero_score_gaps_preserved",
                            "two_way_cluster_limitation": "five_candidate_clusters",
                            "interpretation": "temporally_ordered_predictability_not_causal_feedback",
                        })
    estimates = pd.DataFrame(rows)
    estimates["p_value_holm"] = np.nan
    primary = estimates["primary_horizon"]
    family = ["perimeter", "direction"]
    for _key, indices in estimates[primary].groupby(family, sort=False).groups.items():
        estimates.loc[indices, "p_value_holm"] = holm_adjusted_pvalues(estimates.loc[indices, "p_value"])
    estimates = _attach_full_calendar_decision(estimates)
    estimates = attach_spec_ids(
        estimates,
        prefix="liquidity-capital-v2",
        columns=("perimeter", "direction", "route_measure", "capital_measure", "horizon_days"),
    )
    return estimates, pd.DataFrame(support).drop_duplicates().reset_index(drop=True)


def _influence_cells(
    panel: pd.DataFrame,
    *,
    expected_candidates: int,
    unit: Mapping[str, str],
    variance_shares: list[pd.DataFrame] | None,
) -> pd.DataFrame:
    """Fit the full-calendar perimeter once for one leave-out unit."""

    rows: list[dict[str, object]] = []
    for horizon in HORIZONS:
        horizon_data = panel[panel["horizon_days"].eq(horizon)]
        for route_measure, future_route in ROUTE_MEASURES.items():
            for capital_label, capital_suffix in CAPITAL_MEASURES.items():
                capital_level = f"v2_{capital_suffix}"
                future_capital = f"future_v2_{capital_suffix}_change"
                for direction, outcome, predictor in (
                    ("route_to_capital", future_capital, route_measure),
                    ("capital_to_route", future_route, capital_level),
                ):
                    primary, _two_way = _fit_fe(
                        horizon_data,
                        outcome,
                        predictor,
                        expected_candidates=expected_candidates,
                        with_two_way=False,
                    )
                    fit_sample = horizon_data[
                        [outcome, predictor, "candidate_address", "origin_date"]
                    ].replace([np.inf, -np.inf], np.nan).dropna()
                    if variance_shares is not None:
                        residual = absorb_fixed_effects(
                            fit_sample[[outcome, predictor]],
                            fit_sample["candidate_address"],
                            fit_sample["origin_date"],
                        )
                        weights = within_transform_weight(fit_sample, residual[predictor])
                        weights.insert(0, "record", "within_variance_weight")
                        weights.insert(1, "horizon_days", horizon)
                        weights.insert(2, "direction", direction)
                        weights.insert(3, "route_measure", route_measure)
                        weights.insert(4, "capital_measure", capital_label)
                        variance_shares.append(weights)
                    standard_error = float(primary.standard_errors[0])
                    rows.append({
                        "claim_id": "liquidity_capital_v2_predictability",
                        "measurement_family": "v2_family_deposited_capital_stock",
                        "perimeter": "full_v2_calendar",
                        **unit,
                        "horizon_days": horizon,
                        "primary_horizon": horizon in PRIMARY_HORIZONS,
                        "direction": direction,
                        "route_measure": route_measure,
                        "capital_measure": capital_label,
                        "measure_pair_id": f"{route_measure}__{capital_label}",
                        "outcome": outcome,
                        "predictor": predictor,
                        "coefficient": float(primary.beta[0]),
                        "standard_error": standard_error,
                        "t_statistic": float(primary.t_statistics[0]),
                        "p_value": float(primary.p_values[0]),
                        "confidence_interval_lower": float(primary.beta[0] - 1.96 * standard_error),
                        "confidence_interval_upper": float(primary.beta[0] + 1.96 * standard_error),
                        "observations": primary.n_observations,
                        "origin_date_clusters": primary.n_clusters,
                        "candidate_clusters": int(fit_sample["candidate_address"].nunique()),
                        "fixed_effects": "candidate_and_origin_date",
                        "primary_covariance": (
                            "candidate_date_score_hac_bartlett_30_calendar_days_zero_score_gaps_preserved"
                        ),
                        "share_denominator_candidates": 5,
                        "interpretation": "temporally_ordered_predictability_not_causal_feedback",
                    })
    estimates = pd.DataFrame(rows)
    estimates["p_value_holm"] = np.nan
    primary_mask = estimates["primary_horizon"]
    for _key, indices in estimates[primary_mask].groupby(["perimeter", "direction"], sort=False).groups.items():
        estimates.loc[indices, "p_value_holm"] = holm_adjusted_pvalues(
            estimates.loc[indices, "p_value"]
        )
    return _attach_full_calendar_decision(estimates)


def _influence_displacement(estimates: pd.DataFrame) -> pd.DataFrame:
    """Compare every leave-out cell with the same cell on the recomputed base."""

    keys = ["horizon_days", "direction", "route_measure", "capital_measure"]
    base = estimates[estimates["leave_out_kind"].eq("none")]
    if len(base) != len(HORIZONS) * 2 * len(ROUTE_MEASURES) * len(CAPITAL_MEASURES):
        raise ValueError("influence base perimeter is incomplete")
    reference = base.set_index(keys)[["coefficient", "standard_error", "p_value_holm", "p_value"]]
    merged = estimates.merge(
        reference.rename(
            columns={
                "coefficient": "base_coefficient",
                "standard_error": "base_standard_error",
                "p_value_holm": "base_p_value_holm",
                "p_value": "base_p_value",
            }
        ),
        left_on=keys, right_index=True, how="left", validate="many_to_one",
    )
    merged["coefficient_displacement"] = merged["coefficient"] - merged["base_coefficient"]
    merged["displacement_in_base_standard_errors"] = (
        merged["coefficient_displacement"] / merged["base_standard_error"]
    )
    merged["sign_flip"] = (
        np.sign(merged["coefficient"]).ne(np.sign(merged["base_coefficient"]))
        & merged["coefficient"].ne(0)
        & merged["base_coefficient"].ne(0)
    )
    merged["primary_significance_flip"] = merged["primary_horizon"] & (
        merged["p_value_holm"].lt(0.05).ne(merged["base_p_value_holm"].lt(0.05))
    )
    return merged


def run_influence_concentration(
    *,
    top_pool_count: int = 5,
) -> tuple[Path, Path]:
    """Publish the `influence_concentration` attack for the V2 capital family.

    The attack asks whether the family's pooled result is a market statement or a
    statement about a few units. Its two halves are published together: the
    contribution ledgers that measure where the support's mass sits, and refits
    that drop one candidate or one high-contribution pool at a time and restate
    the claim's own decision rule on what is left. The leave-one-pool half runs
    on a capital block recomputed from the released allocation rows, and refuses
    to publish unless that recomputation reproduces the released panel first.
    """

    context = model_artifact_context()
    inputs = [CANDIDATE_DAY_INPUT, EXACT_HORIZON_INPUT]
    capital_release = resolve_capital_release()
    bound = context.d3_input_records.get(CAPITAL_RELEASE_POINTER_RELATIVE)
    if not isinstance(bound, Mapping) or bound.get("release_generation") != capital_release.generation_id:
        raise ValueError("capital release differs from the D3-bound generation")
    with require_released_model_inputs(
        context, inputs, consumer="V2 liquidity influence-concentration component"
    ) as panel_inputs, current_capital_release(capital_release) as release:
        released_candidate_day = pd.read_parquet(CANDIDATE_DAY_INPUT)
        connection = open_candidate_capital(release.artifacts["candidate"])
        try:
            pool_ledger = pool_contribution_ledger(connection, top_n=10)
            pool_keys = top_pool_keys(pool_ledger, count=top_pool_count)
            base_block = candidate_capital_block(connection, released_candidate_day)
            base_candidate_day = rebuild_candidate_day(released_candidate_day, base_block)
            reconciliation = capital_reconciliation(released_candidate_day, base_candidate_day)
            base_panel = build_v2_exact_horizon_panel(base_candidate_day, HORIZONS)
            variance_shares: list[pd.DataFrame] = []
            frames: list[pd.DataFrame] = []
            for unit in leave_out_units(base_candidate_day, pool_keys):
                if unit["leave_out_kind"] == "none":
                    panel, expected = base_panel, 5
                elif unit["leave_out_kind"] == "candidate":
                    panel = base_panel[
                        base_panel["candidate_address"].ne(unit["leave_out_unit"])
                    ]
                    expected = 4
                else:
                    block = candidate_capital_block(
                        connection,
                        released_candidate_day,
                        excluded_pool_keys=[unit["leave_out_unit"]],
                    )
                    panel = build_v2_exact_horizon_panel(
                        rebuild_candidate_day(released_candidate_day, block), HORIZONS
                    )
                    expected = 5
                frames.append(
                    _influence_cells(
                        panel,
                        expected_candidates=expected,
                        unit=unit,
                        variance_shares=variance_shares if unit["leave_out_kind"] == "none" else None,
                    )
                )
        finally:
            connection.close()
        estimates = _influence_displacement(pd.concat(frames, ignore_index=True))
        estimates.insert(0, "family", INFLUENCE_COMPONENT_FAMILY)
        estimates.insert(1, "attack_id", INFLUENCE_ATTACK_ID)
        estimates = attach_spec_ids(
            estimates, prefix="liquidity_capital_v2_e0_influence",
            columns=INFLUENCE_SPEC_ID_COLUMNS,
        )
        if len(set(estimates["spec_id"])) != len(estimates):
            raise ValueError("influence fitted spec_ids are not unique")
        support = pd.concat(
            [
                reconciliation,
                pool_ledger,
                candidate_contribution_ledger(base_candidate_day),
                pd.concat(variance_shares, ignore_index=True, sort=False),
                estimates.loc[
                    :, ["leave_out_kind", "leave_out_unit", "horizon_days", "direction",
                        "route_measure", "capital_measure", "observations",
                        "origin_date_clusters", "candidate_clusters"]
                ].assign(record="leave_out_fit_support"),
            ],
            ignore_index=True, sort=False,
        )
        support.insert(0, "family", INFLUENCE_COMPONENT_FAMILY)
        support.insert(1, "attack_id", INFLUENCE_ATTACK_ID)
        release_inputs = list(release.bundle.lineage_paths)
        notes = (
            "E0 influence and concentration attack on the V2 deposited-capital family: "
            "pool and candidate contribution ledgers, the within-transformed predictor "
            "variance each candidate carries, and full-calendar refits dropping one "
            "candidate or one high-contribution pool at a time with the claim's own "
            "decision rule restated on each remainder. The five-candidate share "
            "denominator is held fixed when a candidate is dropped, so the diagnostic "
            "perturbs the sample and not the estimand. Leave-one-pool panels are "
            "recomputed from the released allocation rows and reconciled against the "
            "released capital column before any exclusion is taken"
        )
        write_model_exhibit(
            support, INFLUENCE_SUPPORT_OUTPUT, role="support", context=context,
            code_sources=INFLUENCE_CODE_SOURCES,
            inputs=[*panel_inputs, *release_inputs], notes=notes,
        )
        write_model_exhibit(
            estimates, INFLUENCE_ESTIMATE_OUTPUT, role="result", context=context,
            code_sources=INFLUENCE_CODE_SOURCES,
            inputs=[*panel_inputs, *release_inputs], notes=notes,
        )
        release.bundle.assert_current()
    flips = int(estimates["sign_flip"].astype(bool).sum())
    passes = int(
        estimates.loc[estimates["primary_horizon"], "claim_decision_pass"]
        .astype("boolean").fillna(False).sum()
    )
    print(
        f"fitted {len(estimates)} influence specifications across "
        f"{estimates['leave_out_unit'].nunique()} leave-out units; {flips} sign flips; "
        f"{passes} primary cells passing the decision rule"
    )
    return INFLUENCE_ESTIMATE_OUTPUT, INFLUENCE_SUPPORT_OUTPUT


def _render_table(estimates: pd.DataFrame) -> str:
    selected = estimates[
        estimates["perimeter"].eq("full_v2_calendar") & estimates["primary_horizon"]
    ]
    lines = [
        r"\begin{tabular}{lllrrrr}", r"\toprule",
        r"Direction & Vehicle-use measure & Capital measure & Horizon & Coefficient & SE & Holm $p$ \\",
        r"\midrule",
    ]
    for row in selected.itertuples(index=False):
        lines.append(
            f"{row.direction.replace('_', ' ')} & {row.route_measure.replace('_', ' ')} & "
            f"{row.capital_measure.replace('_', ' ')} & {row.horizon_days} & "
            f"{row.coefficient:.4f} & {row.standard_error:.4f} & {row.p_value_holm:.3f} \\\\" 
        )
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines) + "\n"


def run(*, bootstrap_repetitions: int = 199) -> tuple[Path, Path, Path]:
    context = model_artifact_context()
    inputs = [CANDIDATE_DAY_INPUT, EXACT_HORIZON_INPUT]
    with require_released_model_inputs(
        context, inputs, consumer="V2 liquidity predictability estimator"
    ):
        panel = pd.read_parquet(EXACT_HORIZON_INPUT)
        estimates, support = estimate_v2_predictability(
            panel, bootstrap_repetitions=bootstrap_repetitions
        )
        notes = (
            "V2-only bidirectional exact-calendar predictability; candidate and origin-date fixed effects; "
            "cross-section-aggregated score HAC with zero-score dates on the complete calendar and 30-day Bartlett bandwidth, "
            "month-block bootstrap and limited five-candidate two-way sensitivity; full-calendar adjudication only; "
            "pre/post estimates are heterogeneity; descriptive predictive interpretation only"
        )
        write_model_exhibit(
            estimates, RESULT_OUTPUT, role="result", context=context,
            code_sources=CODE_SOURCES, inputs=inputs, notes=notes,
        )
        write_model_exhibit(
            support, SUPPORT_OUTPUT, role="support", context=context,
            code_sources=CODE_SOURCES, inputs=inputs, notes=notes,
        )
        with atomic_output(TABLE_OUTPUT) as temporary:
            temporary.write_text(_render_table(estimates), encoding="utf-8")
        stamp(
            TABLE_OUTPUT, code_sources=CODE_SOURCES,
            inputs=[context.d3_certificate_path, RESULT_OUTPUT, SUPPORT_OUTPUT],
            rows=int(len(estimates)), notes=notes,
        )
    return RESULT_OUTPUT, SUPPORT_OUTPUT, TABLE_OUTPUT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-repetitions", type=int, default=199)
    parser.add_argument("--top-pool-count", type=int, default=5)
    parser.add_argument(
        "--component",
        choices=("all", "quantity-contract", "predictability", "influence"),
        default="all",
        help="all components share one bound generation; split them only to diagnose",
    )
    args = parser.parse_args()
    if args.bootstrap_repetitions < 20:
        raise ValueError("month-block bootstrap requires at least 20 repetitions")
    if args.top_pool_count < 1:
        raise ValueError("the leave-one-pool perimeter needs at least one pool")
    paths: tuple[Path, ...] = ()
    try:
        if args.component in ("all", "quantity-contract"):
            paths += run_quantity_contract()
        if args.component in ("all", "predictability"):
            paths += run(bootstrap_repetitions=args.bootstrap_repetitions)
        if args.component in ("all", "influence"):
            paths += run_influence_concentration(top_pool_count=args.top_pool_count)
        if args.component == "all":
            paths += (run_attack_disposition(),)
    except (RuntimeError, ValueError, FileNotFoundError) as error:
        print(f"INPUT BLOCKED: {error}")
        return 2
    print("wrote " + ", ".join(str(path) for path in paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
