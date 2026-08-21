from __future__ import annotations

import json
from pathlib import Path

import pytest

from ddvc.dominance_tables import (
    parse_newcommands,
    render_dominance_rotation,
    render_pair_composition,
    render_pair_market_accounting,
    render_usdt_transition,
)
ROOT = Path(__file__).resolve().parents[1]
EXHIBITS = ROOT / "output" / "exhibits"
TABLES = ROOT / "output" / "tables"


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_checked_in_fragments_equal_their_named_renderers() -> None:
    rotation = render_dominance_rotation(
        _jsonl(EXHIBITS / "intermediation_complexity_rival.jsonl")
    )
    pair = render_pair_composition(
        {
            **parse_newcommands(
                (
                    EXHIBITS
                    / "vehicle_transition_pair_decomposition_deck_values.tex"
                ).read_text(encoding="utf-8")
            ),
            **parse_newcommands(
                (
                    EXHIBITS / "vehicle_transition_pair_lifecycle_values.tex"
                ).read_text(encoding="utf-8")
            ),
        },
        _jsonl(EXHIBITS / "vehicle_transition_pair_fixed_effects.jsonl"),
    )
    market_accounting = render_pair_market_accounting(
        {
            **parse_newcommands(
                (
                    EXHIBITS
                    / "vehicle_transition_pair_decomposition_deck_values.tex"
                ).read_text(encoding="utf-8")
            ),
            **parse_newcommands(
                (
                    EXHIBITS / "vehicle_transition_pair_lifecycle_values.tex"
                ).read_text(encoding="utf-8")
            ),
        }
    )
    usdt = render_usdt_transition(
        parse_newcommands(
            (EXHIBITS / "presentation_values.tex").read_text(
                encoding="utf-8"
            )
        )
    )

    assert (TABLES / "dominance_rotation.tex").read_text(encoding="utf-8") == rotation
    assert (TABLES / "pair_composition.tex").read_text(encoding="utf-8") == pair
    assert (
        TABLES / "pair_market_accounting.tex"
    ).read_text(encoding="utf-8") == market_accounting
    assert (TABLES / "usdt_transition.tex").read_text(encoding="utf-8") == usdt


def test_rotation_and_usdt_values_are_exact() -> None:
    rotation = (TABLES / "dominance_rotation.tex").read_text(encoding="utf-8")
    assert "Dollar-weighted routes (20\\% agreement)" in rotation
    assert "Change [pp] (s.e.)" in rotation
    assert "16.9\\% & 42.1\\% & $+25.2$ ($1.04$)" in rotation
    assert "32.7\\% & 76.5\\% & $+43.8$ ($2.01$)" in rotation

    usdt = (TABLES / "usdt_transition.tex").read_text(encoding="utf-8")
    assert (
        "Count excess-use ratio (2024 full year; 2026 January--June) & 1.06 & 1.22"
        in usdt
    )
    assert (
        "Value-weighted excess-use ratio (2024 full year; 2026 January--June) & 0.59 & 1.40"
        in usdt
    )
    assert "Paired January--June intermediary minus route-endpoint share [pp]" in usdt
    assert "$-7.13$ & $+7.95$" in usdt


def test_pair_panel_c_contains_all_three_fixed_effect_rows() -> None:
    pair = (TABLES / "pair_composition.tex").read_text(encoding="utf-8")
    assert (
        "All two-leg routes, count share & $+0.23\\ (0.77)$ & 188,344"
        in pair
    )
    assert "Component or estimate & Estimate [pp] & Obs." in pair
    assert (
        "20\\% agreement sample, count share & $+0.32\\ (0.75)$ & 182,734"
        in pair
    )
    assert (
        "20\\% agreement sample, dollar-weighted share & $-1.35\\ (2.19)$ & 182,734"
        in pair
    )
    assert "95\\% CI" not in pair
    assert "0.770" not in pair

    rows = _jsonl(EXHIBITS / "vehicle_transition_pair_fixed_effects.jsonl")
    assert {str(row["metric"]) for row in rows} >= {
        "count_share",
        "matched_strict_count_share",
        "strict_intermediation_value_share",
    }
    for row in rows:
        for field in (
            "confidence_interval_lower",
            "confidence_interval_upper",
            "p_value",
            "p_value_holm",
            "estimator_id",
            "covariance_id",
            "estimand_scope",
            "mechanism_status",
        ):
            assert row[field] is not None


def test_pair_tables_keep_the_two_count_factorisations_apart() -> None:
    """The main and appendix tables decompose one total two ways.

    Both are registered against ``raw_pooled_count_share_change``, but the
    appendix accounting conditions on observed market activity and the main
    decomposition on native-plus-stable choice mass. No component of one is
    the same object as a component of the other.
    """

    pair = (TABLES / "pair_composition.tex").read_text(encoding="utf-8")
    market = (TABLES / "pair_market_accounting.tex").read_text(encoding="utf-8")
    macros = {
        **parse_newcommands(
            (
                EXHIBITS / "vehicle_transition_pair_decomposition_deck_values.tex"
            ).read_text(encoding="utf-8")
        ),
        **parse_newcommands(
            (EXHIBITS / "vehicle_transition_pair_lifecycle_values.tex").read_text(
                encoding="utf-8"
            )
        ),
    }

    assert macros["MarketBridgeTotal"] == macros["PairPooledTotal"]
    total = macros["MarketBridgeTotal"].removesuffix(" pp")
    assert pair.count(f"Total route-count change & {total}") == 1
    assert market.count(f"Total route-count change & {total}") == 1

    # The alternative accounting's labels stay out of the central table.
    for label in (
        "Market activity shifting across continuing pairs",
        "Change in how often continuing pairs use a vehicle",
        "Stablecoin share within continuing vehicle-using pairs",
        "Pairs entering or leaving the sample",
    ):
        assert label not in pair
        assert market.count(label) == 1

    # The identity's labels appear once in its count panel and once in its
    # value panel, and nowhere else.
    for label in (
        "Net stablecoin-share change within continuing pairs",
        "Vehicle activity shifting across continuing pairs",
        "Weight of continuing versus year-specific pairs",
        "Net contribution of period-specific vehicle activity",
    ):
        assert pair.count(label) == 2

    for label in (
        "Pairs first observed after 2024 H1",
        "Pairs reactivated after absence in 2024 H1",
        "Vehicle-role turnover in continuing pairs",
        "Pairs exiting before 2026 H1",
    ):
        assert pair.count(label) == 2

    # The count identity itself must be tabulated, not left to the prose.
    for macro in (
        "PairPooledWithin",
        "PairPooledReweight",
        "PairPooledSupportMass",
        "PairLifecycleCountNetTable",
    ):
        assert macros[macro].removesuffix(" pp") in pair

    assert "Pairs moving toward stablecoins (1,569) & $+1.3$" in pair
    assert "Pairs moving toward native assets (1,487) & $-1.4$" in pair
    assert "Pairs moving toward stablecoins (1,505) & $+2.3$" in pair
    assert "Pairs moving toward native assets (1,445) & $-2.4$" in pair
    assert "Pairs first observed after 2024 H1 & $+20.09$" in pair
    assert "Pairs first observed after 2024 H1 & $+21.94$" in pair
    assert "Pairs reactivated after absence in 2024 H1 & $+0.20$" in pair
    assert "Pairs reactivated after absence in 2024 H1 & $+0.04$" in pair
    assert "Vehicle-role turnover in continuing pairs & $-0.77$" in pair
    assert "Vehicle-role turnover in continuing pairs & $-1.72$" in pair
    assert "Pairs exiting before 2026 H1 & $-1.73$" in pair
    assert "Pairs exiting before 2026 H1 & $-1.10$" in pair


def test_paper_has_one_consumer_and_no_duplicate_inline_body() -> None:
    section = (ROOT / "paper" / "sections" / "03-dominance.tex").read_text(
        encoding="utf-8"
    )
    appendix = (ROOT / "paper" / "sections" / "08-appendix.tex").read_text(
        encoding="utf-8"
    )
    paper = section + "\n" + appendix
    for stem in ("dominance_rotation", "pair_composition"):
        assert paper.count(rf"\input{{../output/tables/{stem}.tex}}") == 1
    # Issuer-level transition estimates remain available as generated output,
    # but the manuscript uses the endpoint-direction evidence instead of
    # carrying a second, disconnected transition table.
    assert r"\input{../output/tables/usdt_transition.tex}" not in paper
    assert r"\begin{tabular}" not in section
    assert r"\begin{tabularx}" not in section
    assert r"S^{(m)}_{pds,y}=\alpha^{(m)}_{pds}+\beta^{(m)}\mathbf{1}_{\{y=2026\}}" in section
    assert r"y\in\{2024,2026\}" in section
    assert "same pair, date within the year, and realised single- or cross-exchange route class" in section
    assert "weighted by native-plus-stable route count or supported routed value" in section
    assert "standard errors cluster by pair and date" in section
    assert "The comparison is descriptive" in section


@pytest.mark.parametrize(
    "stem",
    (
        "dominance_rotation",
        "pair_composition",
        "pair_market_accounting",
        "usdt_transition",
    ),
)
def test_generated_table_artifacts_exist_for_named_renderers(stem: str) -> None:
    # Git does not preserve filesystem mtimes across clones. Exact TeX equality
    # with each named renderer is checked above; here we retain the independent
    # requirement that both publication artifacts are present.
    for suffix in ("tex", "pdf"):
        artifact = TABLES / f"{stem}.{suffix}"
        assert artifact.is_file()


def test_renderers_reject_missing_or_ambiguous_cells() -> None:
    with pytest.raises(ValueError, match="missing"):
        render_usdt_transition({})
    rows = _jsonl(EXHIBITS / "intermediation_complexity_rival.jsonl")
    with pytest.raises(ValueError, match="exactly one row"):
        render_dominance_rotation(rows + rows)
