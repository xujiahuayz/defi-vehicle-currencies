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
    fig, axes = plt.subplots(2, 2, figsize=(11, 8.5))
    fig.suptitle(title, fontsize=16, fontweight="bold")
    for ax, name in zip(axes.ravel(), image_names):
        ax.axis("off")
        path = MODEL / name
        if path.exists():
            ax.imshow(mpimg.imread(path))
            ax.set_title(name.replace("model_", "").replace(".png", ""), fontsize=9)
        else:
            ax.text(0.5, 0.5, f"Missing: {name}", ha="center", va="center")
    for ax in axes.ravel()[len(image_names):]:
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
1. Measurement: BridgeShare is conditional on indirect routing and must be paired with all-route bridge share.
2. P1: WETH vehicle routes provide availability and thin-direct-market protection in quoteable covered venues.
3. P2: vehicle-linked LP concentration and current bridge use predict future BridgeShare; this is not causal LP feedback.
4. P3: WETH downside shocks produce impact stress rotation toward stable vehicles; the supported window is same-day.
5. P4a: V3 evidence is the decline in no-direct/WETH-available cases, not broad V3 launch causality.
6. P4b: V4 partially separates route intermediation from physical intermediary-token transfer; size-bin evidence must be central.
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

P1 is not universal cost superiority. Vehicle route usefulness requires vehicle-route availability and one of: direct route unavailable, direct route thin, or vehicle route cheaper in common support.

P2 is reduced-form persistence:
E[BridgeShare_{k,t+h}] = alpha_k + betaL * LPConcentration_{k,t} + rho * BridgeShare_{k,t}.

P3 is interval-neutral in theory: vehicle risk lowers route advantage on impact. Same-day is the empirical implementation.

P4a increases direct-route liquidity, reducing relative vehicle reliance.
P4b netting intensity lowers physical intermediary-token movement while route intermediation can remain.
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

P2LiquidityPersistence:
- dAdvantage/dLIK > 0 and dAdvantage/dLKJ > 0.
- dExpectedBridgeShareNext/dVehicleLiquidity = betaL >= 0.
- dExpectedBridgeShareNext/dCurrentBridgeShare = rho >= 0.

P3StressRotation:
- dAdvantage/dVehicleRisk = -1.
- dBridgeShare/dVehicleRisk < 0.

P4aConcentratedLiquidity:
- dAdvantage/dDirectLiquidityMultiplier < 0.

P4bFlashAccounting:
- PhysicalVehicleMovement = (1 - n) * GrossVehicleExposure.
- CompressionRatio = n.
- dPhysicalMovement/dNetting < 0; dCompression/dNetting = 1.

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
            ],
        )
        _table_page(pdf, "Table 1. Measurement and Scope", "table_m01_measurement_scope.csv")
        _table_page(pdf, "Table 2. P1 Availability and Thin-Direct Protection", "table_m02_p1_availability_thin_direct.csv")
        _table_page(pdf, "Table 3. P2 Dynamic Predictability", "table_m03_p2_dynamic_predictability.csv")
        _table_page(pdf, "Table 4. P3 Impact Stress Rotation", "table_m04_p3_stress_rotation.csv")
        _table_page(pdf, "Table 5. P4a V3 Route Opportunity", "table_m05_p4a_v3_opportunity.csv")
        _table_page(pdf, "Table 6. P4b V4 Settlement Virtualization", "table_m06_p4b_v4_settlement.csv")
        _table_page(pdf, "Table 7. Specification Registry", "table_m07_specification_registry.csv")
    return PDF


def main() -> int:
    path = build()
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
