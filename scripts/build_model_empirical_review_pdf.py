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
TABLES = OUT / "tables"
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


def _table_page(pdf: PdfPages, title: str, csv_name: str, note: str = "") -> None:
    df = pd.read_csv(TABLES / csv_name)
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

Current status: no additional broad experiments are needed before writing if the paper is written around bounded claims. The remaining task is table hierarchy and claim discipline.

Bounded empirical spine:
1. Measurement: vehicle use is conditional on indirect routing and must be paired with all-route vehicle share.
2. P1/setup: direct-market incompleteness is descriptive scope for the central propositions.
3. P2: vehicle intermediation and vehicle-linked LP liquidity are mutually persistent.
4. P3: credibility or risk shocks to a vehicle reduce its route advantage and rotate order flow toward substitutes.
5. P4a: market-architecture changes that deepen direct pairwise markets reduce reliance on vehicle routes.
6. P4b: settlement netting raises LP willingness to supply vehicle-linked liquidity where routed demand is present.

Implementation discipline: WETH, stablecoins, concentrated-liquidity launch, and flash-accounting launch are empirical test beds.
They should appear in table labels and identification text, not as the propositions themselves.
""",
        )
        _page(
            pdf,
            "Model Structure",
            """Trader chooses between direct route i -> j and vehicle route i -> k -> j.

DirectCost(q) = fD + sD + theta*q/LD
VehicleCost(q) = fIK + fKJ + sK + rhoK + theta*q*(1/LIK + 1/LKJ)
RouteAdvantage = DirectCost - VehicleCost
BridgeShare(delta) = 1 / (1 + exp(-lambda*delta))

P1 is treated as setup: direct-market weakness explains why vehicle routes are relevant; direct-unavailable cases are partly mechanical.

P2 is reduced-form liquidity-route feedback:
E[BridgeShare_{k,t+h}] = alpha_k + betaL * LPConcentration_{k,t} + rho * BridgeShare_{k,t}.
E[LPConcentration_{k,t+h}] = alpha_l + betaB * BridgeShare_{k,t} + psi * LPConcentration_{k,t}.

P3 is interval-neutral in theory: vehicle risk or credibility cost lowers route advantage on impact. Same-day stress episodes are the empirical implementation.

P4a: higher direct-route liquidity reduces relative vehicle-route reliance.
P4b: netting lowers the operational inventory cost of supporting routed demand, increasing optimal vehicle-linked LP supply.
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

P2LiquidityRouteFeedback:
- dAdvantage/dLIK > 0 and dAdvantage/dLKJ > 0.
- dExpectedBridgeShareNext/dVehicleLiquidity = betaL >= 0.
- dExpectedBridgeShareNext/dCurrentBridgeShare = rho >= 0.
- dExpectedVehicleLiquidityNext/dCurrentBridgeShare = betaB >= 0.

P3StressRotation:
- dAdvantage/dVehicleRisk = -1.
- dBridgeShare/dVehicleRisk < 0.

P4aDirectMarketDeepening:
- dAdvantage/dDirectLiquidityMultiplier < 0.

P4bSettlementNettingLiquidity:
- PhysicalVehicleMovement = (1 - n) * GrossVehicleExposure.
- LPPayoff = fee value from routed demand - netting-sensitive operating cost - convex liquidity cost.
- dOptimalVehicleLiquidity/dNetting = kappa1 / chi >= 0.
- dOptimalVehicleLiquidity/dRoutedDemand = phi / chi > 0.

Full derivation object:
"""
            + deriv[:2500],
            fontsize=7,
        )
        _image_page(
            pdf,
            "Numerical Simulations",
            [
                "model_bridge_share_liquidity.png",
                "model_bridge_share_risk.png",
                "model_bridge_share_direct_liquidity.png",
                "model_v4_netting_compression.png",
                "model_liquidity_route_feedback.png",
                "model_netting_lp_supply.png",
            ],
        )
        _table_page(pdf, "Table 1. Measurement and Scope", "table_m01_measurement_scope.csv")
        _table_page(pdf, "Table 2. P1 Route Availability and Thin-Direct Protection", "table_m02_p1_availability_thin_direct.csv")
        _table_page(pdf, "Table 3. P2 Liquidity-Route Feedback", "table_m03_p2_dynamic_predictability.csv")
        _table_page(pdf, "Table 4. P3 Vehicle Risk and Stress Rotation", "table_m04_p3_stress_rotation.csv")
        _table_page(pdf, "Table 5. P4a Direct-Market Deepening and Vehicle-Route Opportunity", "table_m05_p4a_v3_opportunity.csv")
        _table_page(pdf, "Table 6. P4b Settlement Netting and LP Response", "table_m06_p4b_v4_settlement.csv")
        _table_page(pdf, "Table 7. Specification Registry", "table_m07_specification_registry.csv")
    return PDF


def main() -> int:
    path = build()
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
