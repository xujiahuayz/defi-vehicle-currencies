#!/usr/bin/env python3
"""Build a compact PDF review packet for the model and empirical spine.

The repo environment does not assume a LaTeX installation, so this uses
matplotlib's PDF backend. The output is meant for internal review before prose
drafting, not journal typesetting.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
EMP = OUT / "empirical"
MODEL = OUT / "model"
REVIEW = OUT / "review"
PDF = REVIEW / "model_empirical_review.pdf"


def _page(pdf: PdfPages, title: str, body: str, *, fontsize: int = 10) -> None:
    fig = plt.figure(figsize=(11, 8.5))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.text(0.05, 0.95, title, fontsize=16, fontweight="bold", va="top")
    wrapped = []
    for para in body.split("\n"):
        if not para.strip():
            wrapped.append("")
        elif para.startswith("    "):
            wrapped.append(para)
        else:
            wrapped.extend(textwrap.wrap(para, width=125, replace_whitespace=False))
    ax.text(0.05, 0.89, "\n".join(wrapped), fontsize=fontsize, va="top", family="DejaVu Sans Mono")
    pdf.savefig(fig)
    plt.close(fig)


def _table_page(pdf: PdfPages, title: str, data_name: str, note: str = "") -> None:
    df = pd.read_pickle(EMP / f"{data_name}.pkl")
    text = df.to_string(index=False)
    if note:
        text += "\n\n" + note
    _page(pdf, title, text, fontsize=7)


def _image_page(pdf: PdfPages, title: str, image_names: list[str]) -> None:
    ncols = 2
    nrows = max(1, (len(image_names) + ncols - 1) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(11, 8.5))
    fig.suptitle(title, fontsize=16, fontweight="bold")
    flat_axes = axes.ravel() if hasattr(axes, "ravel") else [axes]
    for ax, name in zip(flat_axes, image_names):
        ax.axis("off")
        path = MODEL / name
        if path.exists():
            ax.imshow(mpimg.imread(path))
            ax.set_title(name.replace("model_", "").replace(".png", ""), fontsize=9)
        else:
            ax.text(0.5, 0.5, f"Missing: {name}", ha="center", va="center")
    for ax in flat_axes[len(image_names):]:
        ax.axis("off")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    pdf.savefig(fig)
    plt.close(fig)


def build() -> Path:
    REVIEW.mkdir(parents=True, exist_ok=True)
    with PdfPages(PDF) as pdf:
        _page(
            pdf,
            "Vehicle Currencies in AMMs: Model and Empirical Review Packet",
            """Purpose: internal review before manuscript drafting.

Current status: findings remain unfrozen. This packet is a C/E diagnostic and cannot authorize manuscript drafting.

Bounded empirical spine:
1. Measurement: vehicle use is conditional on indirect routing and must be paired with all-route vehicle share.
2. P1/setup: direct-market incompleteness is descriptive scope for the central propositions.
3. P2: vehicle intermediation and vehicle-linked deposited capital may be mutually persistent; executable route depth is a separate cost primitive.
4. P3: credibility or risk shocks to a vehicle reduce its route advantage and rotate order flow toward substitutes.
5. P4a: market-architecture changes that deepen direct pairwise markets reduce reliance on vehicle routes.
6. P4b: settlement netting raises LP willingness to commit vehicle-linked capital where routed demand is present.

Implementation discipline: WETH, stablecoins, concentrated-liquidity launch, and flash-accounting launch are empirical test beds.
They should appear in table labels and identification text, not as the propositions themselves.
""",
        )
        _page(
            pdf,
            "Model Structure",
            """Trader chooses between direct route i -> j and vehicle route i -> k -> j.

DirectCost(q) = fD + sD + theta*q/DD
VehicleCost(q) = fIK + fKJ + sK + rhoK + theta*q*(1/DIK + 1/DKJ)
RouteAdvantage = DirectCost - VehicleCost
BridgeShare(delta) = 1 / (1 + exp(-lambda*delta))

P1 is treated as setup: direct-market weakness explains why vehicle routes are relevant; direct-unavailable cases are partly mechanical.

P2 is reduced-form capital-route feedback:
E[BridgeShare_{k,t+h}] = alpha_k + betaC * LPCapitalShare_{k,t} + rho * BridgeShare_{k,t}.
E[LPCapitalShare_{k,t+h}] = alpha_l + betaB * BridgeShare_{k,t} + psi * LPCapitalShare_{k,t}.

P3 is interval-neutral in theory: vehicle risk or credibility cost lowers route advantage on impact. Same-day stress episodes are the empirical implementation.

P4a: higher direct-route executable depth reduces relative vehicle-route reliance.
P4b: netting lowers the operational inventory cost of supporting routed demand, increasing optimal vehicle-linked deposited capital.
""",
        )
        deriv = (MODEL / "model_derivations.txt").read_text(encoding="utf-8") if (MODEL / "model_derivations.txt").exists() else ""
        _page(
            pdf,
            "Mathematica Derivation Highlights",
            """Key formal signs from output/model/model_derivations.txt:

P1AvailabilityProtection:
- dBridgeShare/dAdvantage = lambda * Sech[...]^2 / 4 > 0.
- VehicleUsefulCondition includes direct-unavailable, thin-direct, and positive-advantage cases.

P2CapitalRouteFeedback:
- dAdvantage/dDIK > 0 and dAdvantage/dDKJ > 0.
- dExpectedBridgeShareNext/dVehicleCapital = betaC >= 0.
- dExpectedBridgeShareNext/dCurrentBridgeShare = rho >= 0.
- dExpectedVehicleCapitalNext/dCurrentBridgeShare = betaB >= 0.

P3StressRotation:
- dAdvantage/dVehicleRisk = -1.
- dBridgeShare/dVehicleRisk < 0.

P4aDirectMarketDeepening:
- dAdvantage/dDirectCapitalEfficiencyMultiplier < 0 at fixed deposited capital.

P4bSettlementNettingCapital:
- PhysicalVehicleSettlement = (1 - n) * GrossVehicleSettlement.
- LPPayoff = fee value from routed demand - netting-sensitive operating cost - convex capital cost.
- dOptimalVehicleCapital/dNetting = kappa1 / chi >= 0.
- dOptimalVehicleCapital/dRoutedDemand = phi / chi > 0.

Full derivation object:
"""
            + deriv[:2500],
            fontsize=7,
        )
        _image_page(
            pdf,
            "Numerical Simulations",
            [
                "model_bridge_share_depth.png",
                "model_bridge_share_risk.png",
                "model_bridge_share_direct_depth.png",
                "model_v4_netting_compression.png",
                "model_capital_route_feedback.png",
                "model_netting_lp_capital.png",
            ],
        )
        _table_page(pdf, "Measurement and Scope", "measurement_scope")
        _table_page(pdf, "P1 Route Availability and Thin-Direct Protection", "p1_availability_thin_direct")
        _table_page(pdf, "P2 Capital-Route Feedback", "p2_dynamic_predictability")
        _table_page(pdf, "P3 Vehicle Risk and Stress Rotation", "p3_stress_rotation")
        _table_page(pdf, "P4a Direct-Market Deepening and Vehicle-Route Opportunity", "p4a_v3_opportunity")
        _table_page(pdf, "P4b Settlement Netting and LP Response", "p4b_v4_settlement")
        _table_page(pdf, "Specification Registry", "specification_registry")
    return PDF


def main() -> int:
    path = build()
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
