#!/usr/bin/env python3
"""Fallback numerical illustrations for the vehicle-currency model.

This mirrors scripts/model/vehicle_currency_numerics.wl so the figures can be generated
before local Wolfram activation is available.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "model"


def bridge_share(delta: np.ndarray | float, lam: float = 4.0) -> np.ndarray | float:
    return 1.0 / (1.0 + np.exp(-lam * delta))


def direct_cost(q: float, liquidity: np.ndarray | float, fee: float, settlement: float, theta: float) -> np.ndarray | float:
    return fee + settlement + theta * q / liquidity


def vehicle_cost(
    q: float,
    lik: np.ndarray | float,
    lkj: np.ndarray | float,
    fee_ik: float,
    fee_kj: float,
    settlement: float,
    risk: np.ndarray | float,
    theta: float,
) -> np.ndarray | float:
    return fee_ik + fee_kj + settlement + risk + theta * q * (1.0 / lik + 1.0 / lkj)


def route_advantage(
    q: float = 1.0,
    direct_liquidity: np.ndarray | float = 1.4,
    vehicle_liquidity_ik: np.ndarray | float = 1.0,
    vehicle_liquidity_kj: np.ndarray | float = 1.0,
    direct_fee: float = 0.003,
    vehicle_fee_ik: float = 0.003,
    vehicle_fee_kj: float = 0.003,
    direct_settlement: float = 0.0005,
    vehicle_settlement: float = 0.0005,
    vehicle_risk: np.ndarray | float = 0.01,
    theta: float = 0.08,
) -> np.ndarray | float:
    return direct_cost(q, direct_liquidity, direct_fee, direct_settlement, theta) - vehicle_cost(
        q,
        vehicle_liquidity_ik,
        vehicle_liquidity_kj,
        vehicle_fee_ik,
        vehicle_fee_kj,
        vehicle_settlement,
        vehicle_risk,
        theta,
    )


def save_plot(path: Path) -> None:
    plt.tight_layout()
    plt.savefig(path, dpi=200)
    plt.close()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    vehicle_liquidity = np.linspace(0.25, 5.0, 300)
    share_liquidity = bridge_share(
        route_advantage(vehicle_liquidity_ik=vehicle_liquidity, vehicle_liquidity_kj=vehicle_liquidity)
    )
    plt.figure(figsize=(7, 4.5))
    plt.plot(vehicle_liquidity, share_liquidity, color="#1f6f8b", linewidth=2.4)
    plt.ylim(0, 1)
    plt.xlabel("Vehicle-linked executable liquidity")
    plt.ylabel("Bridge share")
    plt.title("Vehicle liquidity raises bridge use")
    plt.grid(alpha=0.25)
    save_plot(OUT / "model_bridge_share_liquidity.png")

    risk = np.linspace(0.0, 0.12, 300)
    share_risk = bridge_share(route_advantage(vehicle_risk=risk))
    plt.figure(figsize=(7, 4.5))
    plt.plot(risk, share_risk, color="#b33f62", linewidth=2.4)
    plt.ylim(0, 1)
    plt.xlabel("Vehicle risk / credibility cost")
    plt.ylabel("Bridge share")
    plt.title("Risk shocks rotate routes away from the vehicle")
    plt.grid(alpha=0.25)
    save_plot(OUT / "model_bridge_share_risk.png")

    direct_multiplier = np.linspace(0.5, 5.0, 300)
    direct_liquidity = 1.4 * direct_multiplier
    share_direct = bridge_share(route_advantage(direct_liquidity=direct_liquidity))
    plt.figure(figsize=(7, 4.5))
    plt.plot(direct_multiplier, share_direct, color="#4d7c2f", linewidth=2.4)
    plt.ylim(0, 1)
    plt.xlabel("Direct-route liquidity multiplier")
    plt.ylabel("Bridge share")
    plt.title("Direct liquidity lowers vehicle-route reliance")
    plt.grid(alpha=0.25)
    save_plot(OUT / "model_bridge_share_direct_liquidity.png")

    netting = np.linspace(0.0, 1.0, 300)
    compression = netting
    physical_over_gross = 1.0 - netting
    plt.figure(figsize=(7, 4.5))
    plt.plot(netting, compression, label="Compression ratio", color="#5f4b8b", linewidth=2.4)
    plt.plot(netting, physical_over_gross, label="Physical movement / gross exposure", color="#c17c2f", linewidth=2.4)
    plt.ylim(0, 1)
    plt.xlabel("Netting intensity")
    plt.ylabel("Share")
    plt.title("V4 netting virtualizes vehicle settlement")
    plt.legend(frameon=False)
    plt.grid(alpha=0.25)
    save_plot(OUT / "model_v4_netting_compression.png")

    print(f"Wrote model figures to {OUT}")


if __name__ == "__main__":
    main()
