from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

import ddvc.presentation_values as renderer_module
from ddvc.presentation_values import (
    INPUTS,
    OUTPUT,
    render_presentation_values,
)


ROOT = Path(__file__).resolve().parents[1]


def test_import_is_side_effect_free() -> None:
    artefact_before = OUTPUT.read_bytes()
    importlib.reload(renderer_module)
    assert OUTPUT.read_bytes() == artefact_before


def test_checked_in_route_binding_equals_its_renderer() -> None:
    frames = [pd.read_json(path, lines=True) for path in INPUTS]
    assert OUTPUT.read_text(encoding="utf-8") == render_presentation_values(
        *frames
    )


def test_route_binding_matches_current_display_values_and_excludes_other_lanes() -> None:
    text = OUTPUT.read_text(encoding="utf-8")
    for expected in (
        r"\newcommand{\StableCountBase}{16.9\%}",
        r"\newcommand{\RoutePanelRawSwaps}{475 million}",
        r"\newcommand{\RoutePanelRawSwapsExact}{475,071,108}",
        r"\newcommand{\RoutePanelUsableLegsExact}{474,388,425}",
        r"\newcommand{\RoutePanelMissingSourceDays}{0}",
        r"\newcommand{\RoutePanelCalendarDates}{2,798}",
        r"\newcommand{\RoutePanelDeploymentCount}{9}",
        r"\newcommand{\RoutePanelSpan}{November 2018--June 2026}",
        r"\newcommand{\NativeStableEpisodeShareMin}{83.8\%}",
        r"\newcommand{\NativeStableValueShareMin}{76.7\%}",
        r"\newcommand{\EthereumMarketCoverageBase}{98.5\%}",
        r"\newcommand{\EthereumMarketCoverageEnd}{77.5\%}",
        r"\newcommand{\EthereumMarketCoveragePooled}{87.5\%}",
        r"\newcommand{\StableCountEnd}{42.1\%}",
        r"\newcommand{\StableValueBase}{32.7\%}",
        r"\newcommand{\StableValueEnd}{76.5\%}",
        r"\newcommand{\JointStableContribution}{92.1\%}",
        r"\newcommand{\USDTEndpointGapChange}{$+15.08$ pp}",
        r"\newcommand{\CrossVenueCountEnd}{57.2\%}",
        r"\newcommand{\CrossVenueValueEnd}{79.1\%}",
        # The venue pricing-family rival: the constant-product restriction must
        # keep the value rotation and must not silently become the smaller move.
        r"\newcommand{\VenueCPStableValueBase}{0.78}",
        r"\newcommand{\VenueCPStableValueEnd}{1.33}",
        r"\newcommand{\VenueAllStableValueChange}{$+0.40$}",
        r"\newcommand{\VenueCPStableValueChange}{$+0.55$}",
        r"\newcommand{\VenueCPEpisodeShare}{84.8\%}",
        # The router-release windows: no release is followed by a materially
        # higher incidence of intermediation, and path length barely moves.
        r"\newcommand{\RouterIntermediationOne}{$-5.7$ pp}",
        r"\newcommand{\RouterIntermediationTwo}{$+0.8$ pp}",
        r"\newcommand{\RouterIntermediationThree}{$-0.7$ pp}",
        r"\newcommand{\RouterLargestIntermediationRise}{$+0.8$ pp}",
        r"\newcommand{\RouterLargestLegMovement}{0.049}",
        r"\newcommand{\RouterCrossOne}{$+2.5$ pp}",
    ):
        assert expected in text
    assert r"\DiagnosticN" not in text
    assert r"\VOneForcedRoutes" not in text


def _router_frames() -> list:
    """Load the validated inputs with the router windows last, as the renderer takes them."""
    return [pd.read_json(path, lines=True) for path in INPUTS]


def test_a_router_release_that_raises_intermediation_withholds_every_macro() -> None:
    frames = _router_frames()
    windows = frames[-1]
    post = windows["period"].eq("post") & windows["event"].eq("universal_router")
    windows.loc[post, "intermediated_share"] = (
        windows.loc[windows["period"].eq("pre") & windows["event"].eq("universal_router"),
                    "intermediated_share"].iloc[0] + 0.02
    )
    with pytest.raises(ValueError, match="intermediation now steps up"):
        render_presentation_values(*frames)


def test_a_material_path_length_movement_withholds_every_macro() -> None:
    frames = _router_frames()
    windows = frames[-1]
    windows.loc[windows["period"].eq("post"), "mean_legs"] += 0.2
    with pytest.raises(ValueError, match="mean path length now moves materially"):
        render_presentation_values(*frames)


def test_a_level_shift_in_the_balanced_perimeter_is_allowed() -> None:
    frames = _router_frames()
    windows = frames[-1]
    windows.loc[windows["scope"].eq("balanced"), "cross_venue_share"] += 0.01
    rendered = render_presentation_values(*frames)
    assert r"\newcommand{\RouterCrossOne}{$+2.5$ pp}" in rendered
