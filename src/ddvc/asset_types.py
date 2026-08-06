"""Asset-type taxonomy for the vehicle-currency question.

The paper's claim is about currency TYPES, not tickers. DeFi is the laboratory,
so every ticker below is a proxy for a type that has a traditional-finance
counterpart, and the paper's language should stay at the type level:

  native            the platform's own settlement asset. Thickest incumbent
                    pairing network, high volatility. TradFi counterpart: the
                    incumbent international currency whose role rests on
                    thick-market externalities.
  staked_native     a liquid-staking derivative of the native asset. Same
                    underlying exposure, different instrument. Held apart from
                    `native` because whether it counts as the same currency is a
                    specification choice, not a fact (see ALTERNATIVES).
  stable            low-volatility numeraire and unit of account. TradFi
                    counterpart: the managed or pegged stable unit.
  imported          non-native store of value brought onto the platform in
                    wrapped form, including tokenised gold. TradFi counterpart:
                    gold or a foreign reserve asset.
  other             everything else that intermediates a route.

Coverage. Selected by measuring actual intermediation over 57 days stratified
across 2020-02 to 2026-06 (2,149,718 intermediation episodes, 9,283 distinct
intermediary tokens). The five original candidates plus unwrapped native ETH
account for 81.7% of all episodes; the classified set below extends that. The
long tail is genuinely long, so `other` is a real category rather than a
residual to be explained away.

Why unwrapped ETH matters. An earlier version of this taxonomy carried only
WETH and therefore misfiled native ETH (the zero address) as `other`. In
2026 samples that single omission was 19.8% of the `other` bucket, which
understated the native share materially. Native ETH appears as a route token
mainly in the later sample, consistent with native-ETH support in newer
protocol versions.
"""

from __future__ import annotations

# Native platform asset. The zero address is native ETH, which several routers
# and newer protocol versions handle without wrapping.
NATIVE = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
    "0x0000000000000000000000000000000000000000": "ETH",
    "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee": "ETH",  # alt native sentinel
}

# Liquid-staking derivatives of the native asset.
STAKED_NATIVE = {
    "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0": "wstETH",
    "0xae7ab96520de3a18e5e111b5eaab095312d7fe84": "stETH",
    "0xae78736cd615f374d3085123a210448e74fc6393": "rETH",
    "0xbe9895146f7af43049ca1c1ae358b0541ea49704": "cbETH",
    "0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee": "weETH",
    "0xa2e3356610840701bdf5611a53974510ae27e2e1": "wBETH",
    "0xac3e018457b222d93114458476f3e3416abbe38f": "sfrxETH",
    "0x5e8422345238f34275888049021821e8e08caa1f": "frxETH",
}

# Low-volatility numeraire assets. USD-pegged unless flagged in NON_USD_STABLE.
STABLE = {
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
    "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
    "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e": "crvUSD",
    "0x4c9edd5852cd905f086c759e8383e09bff1e68b3": "USDe",
    "0x9d39a5de30e57443bff2a8307a4256c8797a3497": "sUSDe",
    "0x853d955acef822db058eb8505911ed77f175b99e": "FRAX",
    "0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d": "USD1",
    "0x57ab1ec28d129707052df4df418d58a2d46d5f51": "sUSD",
    "0x6c3ea9036406852006290770bedfcaba0e23a0e8": "PYUSD",
    "0x5f98805a4e8be255a32880fdec7f6728c6568ba0": "LUSD",
    "0x0000000000085d4780b73119b644ae5ecd22b376": "TUSD",
    "0x8e870d67f660d95d5be530380d0ec0bd388289e1": "USDP",
    "0x056fd409e1d7a124bd7017459dfea2f387b6d5cd": "GUSD",
    "0xdc035d45d973e3ec169d2276ddab16f1e407384f": "USDS",
    "0x99d8a9c45b2eca8864373a26d1459e3dff1e17f3": "MIM",
    "0x865377367054516e17014ccded1e7d814edc9ce4": "DOLA",
    "0xbc6da0fe9ad5f3b0d58160288917aa56653660e9": "alUSD",
    "0x4fabb145d64652a948d72533023f6e7a623c7c53": "BUSD",
    "0x1a7e4e63778b4f12a199c062f3efdd288afcbce8": "agEUR",
    "0xdb25f211ab05b1c97d595516f45794528a807ad8": "EURS",
}

# Non-USD numeraires, tracked separately because a EUR-pegged unit is a
# different currency and not merely a different issuer of the same one.
NON_USD_STABLE = {"agEUR", "EURS"}

# ---------------------------------------------------------------------------
# Backing regime, crossing the `stable` type. Added by node C round 2
# (docs/node-c-definitions-round2.md section 3) because the corpus cuts
# stablecoins here and we were pooling across the cut.
#
# Catalini, de Gortari and Shah (2022) split stablecoins into fiat-backed,
# crypto-asset-backed, and those "backed partially or fully by their own
# investment token [which] only rely on their own algorithms and smart
# contracts", and state the consequence: "unlike stablecoins backed by fiat
# assets or cryptocurrencies, the true solvency of an algorithmic coin is
# linked to the public's confidence in the coin". Lyons and Viswanath-Natraj
# (2023) build their result on the same line: "in contrast to dollar-backed
# stablecoins, there is no clear arbitrage mechanism to restore prices when
# TerraUSD is priced at a discount." Four papers in this project's corpus exist
# principally because backing regimes behave differently.
#
# Weight, measured on incident-edge strength in data/processed/
# vehicle_centrality.parquet: 89.4% of `stable` intermediation value is
# fiat-backed pooled across the sample, so this moves no aggregate. It matters
# on the time axis the paper reads its transition against, where crypto
# collateral is 30.3% of stable intermediation in 2020 and 3.3% in 2026, and
# the synthetic regime appears from 2024 at roughly 4.5%.
# ---------------------------------------------------------------------------

STABLE_BACKING = {
    "USDC": "fiat", "USDT": "fiat", "PYUSD": "fiat", "TUSD": "fiat",
    "USDP": "fiat", "GUSD": "fiat", "BUSD": "fiat", "USD1": "fiat",
    "DAI": "crypto_collateral", "LUSD": "crypto_collateral",
    "crvUSD": "crypto_collateral", "alUSD": "crypto_collateral",
    "DOLA": "crypto_collateral", "sUSD": "crypto_collateral",
    "USDS": "crypto_collateral", "MIM": "crypto_collateral",
    "USDe": "synthetic", "sUSDe": "synthetic",
    "FRAX": "fractional_algorithmic",
    "agEUR": "non_usd", "EURS": "non_usd",
}

BACKINGS = ("fiat", "crypto_collateral", "synthetic", "fractional_algorithmic",
            "non_usd", "not_applicable")

# Non-native stores of value, wrapped onto the platform. Includes tokenised
# gold, which is the cleanest available analogue of a metallic reserve asset.
IMPORTED = {
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",
    "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf": "cbBTC",
    "0x18084fba666a33d37592fa2633fd49a74dd93a88": "tBTC",
    "0x8daebade922df735c38c80c7ebd708af50815faa": "tBTCv1",
    "0x45804880de22913dafe09f4980848ece6ecbaf78": "PAXG",
    "0x68749665ff8d2d112fa859aa293f07a622782f38": "XAUt",
}

TYPES = ("native", "staked_native", "stable", "imported", "other")

_LOOKUP: dict[str, tuple[str, str]] = {}
for _m, _t in ((NATIVE, "native"), (STAKED_NATIVE, "staked_native"),
               (STABLE, "stable"), (IMPORTED, "imported")):
    for _addr, _sym in _m.items():
        _LOOKUP[_addr.lower()] = (_sym, _t)


def classify(address: object) -> tuple[str | None, str]:
    """Return (symbol, type) for a token address; type is 'other' if unknown.

    Defensive about input because callers pass pandas columns, where a missing
    token arrives as float('nan'). NaN is truthy, so a bare `if not address`
    guard lets it through and then fails on .lower().
    """
    if not isinstance(address, str) or not address:
        return None, "other"
    return _LOOKUP.get(address.lower(), (None, "other"))


def asset_type(address: str | None) -> str:
    return classify(address)[1]


def backing(address: object) -> str:
    """Backing regime for a token, 'not_applicable' outside the `stable` type.

    The primary axis stays the five-value asset type. This crosses it, so a
    result reported at `stable` level carries a required robustness row at
    backing level and the prose can stop saying "the stable numeraire" as if
    USDC and USDe were the same instrument.
    """
    sym, typ = classify(address)
    if typ != "stable" or sym is None:
        return "not_applicable"
    return STABLE_BACKING.get(sym, "not_applicable")


# ---------------------------------------------------------------------------
# Specification alternatives, for the decision registry.
#
# Each of these is a defensible choice rather than a fact, so results that move
# under them must be reported as moving. Mitton (RFS 2022) is the reason: with
# discretion over a handful of routine choices a researcher can make most
# randomly generated variables look significant.
# ---------------------------------------------------------------------------

ALTERNATIVES = {
    "wrapped_native_identity": (
        "Native ETH (zero address, Uniswap v4) and WETH treated as ONE currency "
        "(default) or as two distinct assets. Wrapping is one-for-one and routers "
        "wrap silently, so the currency-level view is primary; the split is kept "
        "because wrapping costs gas and is a distinct venue."
    ),
    "staked_native_in_native": (
        "Fold staked_native into native. Defensible because wstETH and stETH "
        "carry the same underlying exposure as ETH; contestable because they "
        "are distinct instruments with their own liquidity and depeg risk. "
        "Primary specification keeps them separate. Measured weight is small "
        "(wstETH 0.38% and rETH 0.11% of episodes over the stratified sample), "
        "so this should not move a headline; verify rather than assume."
    ),
    "non_usd_stable_separate": (
        "Break agEUR and EURS out of `stable` into their own numeraire type. "
        "A EUR-pegged unit is a different currency, which matters for a paper "
        "about currency competition. Immaterial by weight (under 0.1%) but "
        "conceptually right, so report it once and then pool."
    ),
    "gold_separate_from_imported": (
        "Split tokenised gold (PAXG, XAUt) out of `imported` from wrapped "
        "bitcoin. Gold is a metallic reserve asset while wrapped BTC is a "
        "foreign crypto reserve asset, and the TradFi analogue differs. "
        "Combined weight roughly 0.38% of episodes."
    ),
    "stable_backing_pooled": (
        "Pool all backing regimes inside `stable` (the state before node C "
        "round 2) or report the stable-type results once at backing level "
        "(now required). The corpus cuts stablecoins by backing and four of "
        "its papers exist because the regimes behave differently, so pooling "
        "is the choice that has to be defended. Pooled weight is 89.4% "
        "fiat-backed, so the aggregate does not move; the 2020 to 2022 window "
        "does, where crypto collateral runs 30.3% down to 7.8%."
    ),
    "candidate_set_only": (
        "Restrict to the five original candidates (WETH, USDC, USDT, DAI, "
        "WBTC) so results are comparable with the project's earlier work. This "
        "is the specification that misfiled native ETH as `other`, so it should "
        "be reported only as a backward-compatibility check and never as "
        "primary."
    ),
}

# ---------------------------------------------------------------------------
# Wrapped and native ETH: one currency or two?
#
# Uniswap v4 restored native ETH as a pool asset, so from 2025 the same currency
# appears under two identifiers: the zero address for native ETH and the WETH
# contract for the wrapped claim. Whether those are ONE vehicle or two is a
# modelling choice, not a fact, and the paper reports both.
#
# The case for treating them as one currency is the stronger of the two, and it is
# behavioural rather than aesthetic: WETH is redeemable one-for-one on demand, and
# routers routinely accept native ETH and wrap it inside the same transaction, so a
# trader who spent ETH never chose WETH at all. Counting that route as a
# "WETH-intermediated" trade would attribute to the trader a decision the router
# made silently. Under this reading the wrapper is plumbing and the vehicle is ETH.
#
# The case for treating them as two is that wrapping is not free. It costs gas and
# introduces a distinct contract, so a pool holding native ETH is a genuinely
# different execution venue even when the currency is the same. That distinction
# matters for cost comparisons, and it is why the split is kept available rather
# than argued away.
#
# Both are therefore expressible, the currency-level view is primary, and the
# venue-level split is a robustness specification.
# ---------------------------------------------------------------------------

NATIVE_ETH = "0x0000000000000000000000000000000000000000"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"


def canonical_token(address: object, *, unify_wrapped: bool = True) -> str | None:
    """Token identity for routing, optionally collapsing native ETH onto WETH.

    With `unify_wrapped`, native ETH resolves to the WETH address so that a v4
    native-ETH pool and a v3 WETH pool are the same vehicle. Without it, the two
    stay distinct and a route through one is not a route through the other.
    """
    if not isinstance(address, str) or not address:
        return None
    a = address.lower()
    if unify_wrapped and a == NATIVE_ETH:
        return WETH
    return a
