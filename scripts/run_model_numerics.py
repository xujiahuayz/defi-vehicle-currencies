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


def feedback_paths(
    liquidity0: float = 0.35,
    bridge0: float = 0.15,
    alpha_bridge: float = 0.02,
    beta_liquidity_to_bridge: float = 0.18,
    bridge_persistence: float = 0.62,
    alpha_liquidity: float = 0.04,
    beta_bridge_to_liquidity: float = 0.22,
    liquidity_persistence: float = 0.70,
    periods: int = 24,
) -> tuple[np.ndarray, np.ndarray]:
    liquidity = np.empty(periods + 1)
    bridge = np.empty(periods + 1)
    liquidity[0] = liquidity0
    bridge[0] = bridge0
    for t in range(periods):
        bridge[t + 1] = np.clip(
            alpha_bridge + beta_liquidity_to_bridge * liquidity[t] + bridge_persistence * bridge[t],
            0,
            1,
        )
        liquidity[t + 1] = np.clip(
            alpha_liquidity + beta_bridge_to_liquidity * bridge[t] + liquidity_persistence * liquidity[t],
            0,
            1,
        )
    return liquidity, bridge


def optimal_vehicle_liquidity(
    netting: np.ndarray | float,
    routed_demand: float = 1.0,
    fee_value: float = 0.08,
    base_cost: float = 0.02,
    nettable_cost: float = 0.035,
    convex_cost: float = 0.09,
) -> np.ndarray | float:
    return np.maximum(0.0, (fee_value * routed_demand - base_cost - nettable_cost * (1.0 - netting)) / convex_cost)


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

    liquidity, bridge = feedback_paths()
    t = np.arange(len(liquidity))
    plt.figure(figsize=(7, 4.5))
    plt.plot(t, bridge, label="Bridge share", color="#1f6f8b", linewidth=2.4)
    plt.plot(t, liquidity, label="Vehicle-linked LP liquidity", color="#7b5e2e", linewidth=2.4)
    plt.ylim(0, 1)
    plt.xlabel("Period")
    plt.ylabel("State")
    plt.title("Liquidity-route feedback creates persistent vehicle status")
    plt.legend(frameon=False)
    plt.grid(alpha=0.25)
    save_plot(OUT / "model_liquidity_route_feedback.png")

    lp_supply = optimal_vehicle_liquidity(netting)
    plt.figure(figsize=(7, 4.5))
    plt.plot(netting, lp_supply, color="#2f6f4e", linewidth=2.4)
    plt.xlabel("Settlement netting intensity")
    plt.ylabel("Optimal vehicle-linked LP supply")
    plt.title("Netting raises LP willingness to support vehicle routes")
    plt.grid(alpha=0.25)
    save_plot(OUT / "model_netting_lp_supply.png")

    derivation = """Model derivation highlights

P2 liquidity-route feedback:
ExpectedBridgeShareNext = alphaK + betaL * VehicleLiquidity + rho * CurrentBridgeShare.
dExpectedBridgeShareNext/dVehicleLiquidity = betaL >= 0.
dExpectedBridgeShareNext/dCurrentBridgeShare = rho >= 0.

ExpectedVehicleLiquidityNext = alphaL + betaB * CurrentBridgeShare + psi * VehicleLiquidity.
dExpectedVehicleLiquidityNext/dCurrentBridgeShare = betaB >= 0.
dExpectedVehicleLiquidityNext/dVehicleLiquidity = psi >= 0.

This is the model object for a Matthew-effect interpretation: liquidity predicts future route use, and route use predicts future liquidity.

P4b settlement netting and LP supply:
PhysicalVehicleMovement = (1 - n) * GrossVehicleExposure.
LPPayoff = phi * RoutedDemand * VehicleLiquidity - (kappa0 + kappa1 * (1 - n)) * VehicleLiquidity - chi * VehicleLiquidity^2 / 2.
OptimalVehicleLiquidity = (phi * RoutedDemand - kappa0 - kappa1 * (1 - n)) / chi, truncated at zero.
dOptimalVehicleLiquidity/dNetting = kappa1 / chi >= 0.
dOptimalVehicleLiquidity/dRoutedDemand = phi / chi > 0.

The behavioral prediction goes beyond the accounting identity that netting lowers transfers: netting raises LP willingness to supply vehicle-linked liquidity where routed demand is present.
"""
    (OUT / "model_derivations.txt").write_text(derivation, encoding="utf-8")

    print(f"Wrote model figures to {OUT}")


if __name__ == "__main__":
    main()
