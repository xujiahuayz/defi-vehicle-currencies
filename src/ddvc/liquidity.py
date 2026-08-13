"""Canonical economic meanings for pool capital and executable depth.

Pool capital, local marginal depth, and executable band depth are different
objects.  A return denominator must be lagged deposited capital; a local-depth
quantity may enter price-impact or invariant-specific LVR calculations but must
never be silently reused as capital.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
import sys
from typing import Callable

import numpy as np
import pandas as pd

from ddvc.capital_contracts import (
    CAPITAL_COLUMN,
    MAX_POOL_CAPITAL_USD,
    capital_contract,
    equal_candidate_capital_weights,
)
from ddvc.execution_contracts import (
    CP_STATE_GENERATION,
    EXECUTION_CONTRACTS,
    TICK_STATE_GENERATIONS,
    execution_contract,
)
from ddvc.paths import REPO_ROOT


LOCAL_DEPTH_COLUMN = "local_depth_usd"
BAND_DEPTH_COLUMN = "band_depth_usd"
LVR_SCALE_COLUMN = "lvr_scale_usd"
LIQUIDITY_QUANTITY_KINDS = frozenset(
    {
        "deposited_capital",
        "local_marginal_depth",
        "executable_band_depth",
        "quote_quality",
        "lvr",
    }
)


@dataclass(frozen=True)
class QuantityCapability:
    """One admitted quantity at one protocol-family state generation."""

    quantity_kind: str
    state_generation: str | None
    materializer: str | None
    validation: str | None
    admissible_uses: tuple[str, ...]
    ready: bool = False


@dataclass(frozen=True)
class LiquidityContract:
    """Pool-family-specific ownership of capital, depth, quotes, and LVR."""

    venue: str
    pool_family: str
    invariant_family: str
    capital_measure: str
    capital_sources: tuple[str, ...]
    capabilities: tuple[QuantityCapability, ...]
    return_model_ready: bool
    scale_label: str

    def capability(self, quantity_kind: str) -> QuantityCapability:
        for capability in self.capabilities:
            if capability.quantity_kind == quantity_kind:
                return capability
        return QuantityCapability(quantity_kind, None, None, None, (), False)

    @property
    def capital_ready(self) -> bool:
        return self.capability("deposited_capital").ready

    @property
    def quote_adapter(self) -> str | None:
        capability = self.capability("quote_quality")
        return capability.materializer if capability.ready else None

    @property
    def local_depth_adapter(self) -> str | None:
        capability = self.capability("local_marginal_depth")
        return capability.materializer if capability.ready else None

    @property
    def band_depth_adapter(self) -> str | None:
        capability = self.capability("executable_band_depth")
        return capability.materializer if capability.ready else None

    @property
    def lvr_adapter(self) -> str | None:
        capability = self.capability("lvr")
        return capability.materializer if capability.ready else None

    @property
    def return_inference_ready(self) -> bool:
        return self.return_model_ready and self.capital_ready and self.lvr_adapter is not None


def _capability(
    quantity_kind: str,
    *,
    state_generation: str | None = None,
    materializer: str | None = None,
    validation: str | None = None,
    admissible_uses: tuple[str, ...] = (),
    ready: bool = False,
) -> QuantityCapability:
    return QuantityCapability(
        quantity_kind=quantity_kind,
        state_generation=state_generation,
        materializer=materializer,
        validation=validation,
        admissible_uses=admissible_uses,
        ready=ready,
    )


def _import_from_repository(module_name: str):
    """Import one in-repository module by file location, without touching sys.path.

    A materializer may name an entrypoint module such as
    ``scripts.build_pool_capital_panel``.  Those modules are importable by name
    only when the repository root is on the import path, which the project runner
    arranges but a bare ``python scripts/x.py`` invocation does not.  A contract
    validator whose verdict depends on how the interpreter was launched is not a
    gate, so resolve the module from its own location instead.
    """

    location = REPO_ROOT.joinpath(*module_name.split(".")).with_suffix(".py")
    if not location.is_file():
        raise ImportError(f"no module named {module_name!r} and no file at {location}")
    spec = spec_from_file_location(module_name, location)
    if spec is None or spec.loader is None:
        raise ImportError(f"{location} is not an importable module")
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[module_name]
        raise
    return module


def resolve_materializer(reference: str) -> Callable[..., object]:
    """Resolve one exact ``module:callable`` implementation reference."""

    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError(f"materializer is not an exact module:callable reference: {reference!r}")
    try:
        module = import_module(module_name)
    except ModuleNotFoundError:
        module = _import_from_repository(module_name)
    implementation = getattr(module, attribute, None)
    if not callable(implementation):
        raise ValueError(f"materializer is not callable: {reference!r}")
    return implementation


def constant_product_lvr_usd(
    realized_variance: pd.Series | np.ndarray | float,
    contemporaneous_pool_value_usd: pd.Series | np.ndarray | float,
) -> pd.Series | np.ndarray | float:
    """Constant-product dollar LVR using the contemporaneous pool-value scale."""

    return realized_variance / 8.0 * contemporaneous_pool_value_usd


def _contract(
    venue: str,
    pool_family: str,
    capital_measure: str,
    *,
    capital_sources: tuple[str, ...] = (),
    capabilities: tuple[QuantityCapability, ...] | None = None,
    return_model_ready: bool = False,
    scale_label: str = "unavailable",
) -> LiquidityContract:
    execution = execution_contract(venue, pool_family)
    declared = {cap.quantity_kind: cap for cap in capabilities or ()}
    complete = tuple(
        declared.get(kind, _capability(kind)) for kind in sorted(LIQUIDITY_QUANTITY_KINDS)
    )
    return LiquidityContract(
        venue=venue,
        pool_family=pool_family,
        invariant_family=execution.invariant_family,
        capital_measure=capital_measure,
        capital_sources=capital_sources,
        capabilities=complete,
        return_model_ready=return_model_ready,
        scale_label=scale_label,
    )


_CP_CAPITAL = capital_contract("uniswap_v2")
CP_CAPABILITIES = (
    _capability(
        "deposited_capital",
        state_generation=_CP_CAPITAL.state_generation,
        materializer=_CP_CAPITAL.materializer,
        validation=_CP_CAPITAL.validation,
        admissible_uses=_CP_CAPITAL.admissible_uses,
        ready=True,
    ),
    _capability(
        "local_marginal_depth",
        state_generation=CP_STATE_GENERATION,
        materializer="ddvc.pricing.v2quote:quote_exact_input_float",
        validation="constant_product_scaling_and_quote_reproduction",
        admissible_uses=("quote_reproduction", "constant_product_lvr"),
        ready=True,
    ),
    _capability(
        "executable_band_depth",
        state_generation=CP_STATE_GENERATION,
        materializer="ddvc.pricing.v2quote:quote_exact_input_float",
        validation="fee_inclusive_price_impact_band",
        admissible_uses=("quote_quality",),
        ready=True,
    ),
    _capability(
        "quote_quality",
        state_generation=CP_STATE_GENERATION,
        materializer="ddvc.pricing.v2quote:quote_exact_input_float",
        validation="exact_input_quote_reproduction",
        admissible_uses=("quote_quality",),
        ready=True,
    ),
    _capability(
        "lvr",
        state_generation="external_reference_price_variance_pending",
        validation=(
            "published_closed_form_scale_test_plus_independent_external_reference_price_path"
        ),
        admissible_uses=("return_after_row_reconciliation",),
    ),
)

V3_CAPABILITIES = (
    _capability(
        "deposited_capital",
        state_generation="uniswap_v3_event_replayed_inventory_v1",
        materializer="pending_event_complete_inventory_replay",
        validation="mint_swap_collect_flash_replay_and_historical_balance_audit",
    ),
    _capability(
        "local_marginal_depth",
        state_generation=TICK_STATE_GENERATIONS["uniswap_v3"],
        materializer="ddvc.pricing.tick_quote:quote_tick_state",
        validation="active_liquidity_state_replay",
        admissible_uses=("descriptive", "quote_reproduction"),
        ready=True,
    ),
    _capability(
        "executable_band_depth",
        state_generation=TICK_STATE_GENERATIONS["uniswap_v3"],
        materializer="ddvc.pricing.tick_quote:quote_tick_state",
        validation="fee_inclusive_tick_traversal",
        admissible_uses=("quote_quality",),
        ready=True,
    ),
    _capability(
        "quote_quality",
        state_generation=TICK_STATE_GENERATIONS["uniswap_v3"],
        materializer="ddvc.pricing.tick_quote:quote_tick_state",
        validation="transaction_ordered_quote_reproduction",
        admissible_uses=("quote_quality",),
        ready=True,
    ),
)

V4_EXECUTION_CAPABILITIES = (
    _capability(
        "local_marginal_depth",
        state_generation=TICK_STATE_GENERATIONS["uniswap_v4"],
        materializer="ddvc.pricing.tick_quote:quote_tick_state",
        validation="active_liquidity_state_replay_for_vanilla_static_fee_pools",
        admissible_uses=("descriptive", "quote_reproduction"),
        ready=True,
    ),
    _capability(
        "executable_band_depth",
        state_generation=TICK_STATE_GENERATIONS["uniswap_v4"],
        materializer="ddvc.pricing.tick_quote:quote_tick_state",
        validation="fee_inclusive_tick_traversal_for_vanilla_static_fee_pools",
        admissible_uses=("quote_quality",),
        ready=True,
    ),
    _capability(
        "quote_quality",
        state_generation=TICK_STATE_GENERATIONS["uniswap_v4"],
        materializer="ddvc.pricing.tick_quote:quote_tick_state",
        validation="transaction_ordered_quote_reproduction_for_vanilla_static_fee_pools",
        admissible_uses=("quote_quality",),
        ready=True,
    ),
)

# The key is intentionally (venue, pool/invariant family). Curve, Balancer and
# V4 are heterogeneous protocols: a venue name alone never authorizes a quantity.
LIQUIDITY_CONTRACTS: dict[tuple[str, str], LiquidityContract] = {
    ("uniswap_v1", "full_range_constant_product"): _contract(
        "uniswap_v1",
        "full_range_constant_product",
        "priced pool reserves not materialized in the current state layer",
        scale_label="unmaterialized priced reserve capital",
    ),
    ("uniswap_v2", "full_range_constant_product"): _contract(
        "uniswap_v2",
        "full_range_constant_product",
        capital_contract("uniswap_v2").capital_measure,
        capital_sources=capital_contract("uniswap_v2").capital_sources,
        capabilities=CP_CAPABILITIES,
        return_model_ready=True,
        scale_label="lagged independently priced exact closing reserves",
    ),
    ("sushiswap_v2", "full_range_constant_product"): _contract(
        "sushiswap_v2",
        "full_range_constant_product",
        capital_contract("sushiswap_v2").capital_measure,
        capital_sources=capital_contract("sushiswap_v2").capital_sources,
        capabilities=CP_CAPABILITIES,
        return_model_ready=True,
        scale_label="lagged independently priced exact closing reserves",
    ),
    ("uniswap_v3", "concentrated_liquidity"): _contract(
        "uniswap_v3",
        "concentrated_liquidity",
        "provider TVL rejected as deposited capital pending event-complete inventory replay",
        capabilities=V3_CAPABILITIES,
        scale_label="unvalidated provider TVL diagnostic",
    ),
    ("sushiswap_v3", "concentrated_liquidity"): _contract(
        "sushiswap_v3",
        "concentrated_liquidity",
        "provider TVL pending balance reconciliation",
        scale_label="unvalidated provider TVL",
    ),
    ("curve", "stableswap"): _contract(
        "curve",
        "stableswap",
        "externally priced normalized token balances",
        scale_label="unmaterialized normalized token-balance capital",
    ),
    ("curve", "cryptoswap"): _contract(
        "curve",
        "cryptoswap",
        "externally priced normalized token balances",
        scale_label="unmaterialized normalized token-balance capital",
    ),
    ("curve", "ng_or_unclassified"): _contract(
        "curve",
        "ng_or_unclassified",
        "unsupported until invariant and rate-provider family is validated",
    ),
    ("balancer", "weighted"): _contract(
        "balancer",
        "weighted",
        "pool-attributed Vault balances net of BPT and wrappers",
        scale_label="unmaterialized net Vault-balance capital",
    ),
    ("balancer", "stable_or_composable_stable"): _contract(
        "balancer",
        "stable_or_composable_stable",
        "pool-attributed Vault balances net of BPT and normalized by rate providers",
        scale_label="unmaterialized normalized Vault-balance capital",
    ),
    ("balancer", "linear_or_boosted"): _contract(
        "balancer",
        "linear_or_boosted",
        "pool-attributed Vault balances net of BPT and wrapper claims",
        scale_label="unmaterialized net Vault-balance capital",
    ),
    ("balancer", "gyro_or_custom"): _contract(
        "balancer",
        "gyro_or_custom",
        "pool-attributed Vault balances pending invariant-specific audit",
    ),
    ("balancer", "dynamic_weight_or_managed"): _contract(
        "balancer",
        "dynamic_weight_or_managed",
        "pool-attributed Vault balances pending weight-schedule and management audit",
    ),
    ("balancer", "unclassified"): _contract(
        "balancer",
        "unclassified",
        "unsupported until the provider pool type maps to an audited invariant family",
    ),
    ("uniswap_v4", "vanilla_concentrated"): _contract(
        "uniswap_v4",
        "vanilla_concentrated",
        "pool-attributed singleton claims pending ownership reconciliation",
        capabilities=V4_EXECUTION_CAPABILITIES,
        scale_label="unvalidated pool-attributed singleton capital",
    ),
    ("uniswap_v4", "hooked_or_dynamic_fee"): _contract(
        "uniswap_v4",
        "hooked_or_dynamic_fee",
        "unsupported until hook-aware claims and execution semantics are audited",
    ),
    ("uniswap_v4", "unclassified"): _contract(
        "uniswap_v4",
        "unclassified",
        "unsupported until immutable pool statics establish the V4 execution family",
    ),
    ("fluid", "trade_only"): _contract(
        "fluid",
        "trade_only",
        "unavailable in the current trade-only source",
    ),
}

if set(LIQUIDITY_CONTRACTS) != set(EXECUTION_CONTRACTS):
    raise RuntimeError("liquidity and execution contract perimeters differ")
for key, contract in LIQUIDITY_CONTRACTS.items():
    execution = EXECUTION_CONTRACTS[key]
    quote = contract.capability("quote_quality")
    if quote.ready != execution.quote_ready:
        raise RuntimeError(f"quote readiness differs across contract layers: {key}")
    if quote.ready and quote.state_generation != execution.state_generation:
        raise RuntimeError(f"quote state generation differs across contract layers: {key}")

DEFAULT_POOL_FAMILIES = {
    "uniswap_v1": "full_range_constant_product",
    "uniswap_v2": "full_range_constant_product",
    "sushiswap_v2": "full_range_constant_product",
    "uniswap_v3": "concentrated_liquidity",
    "sushiswap_v3": "concentrated_liquidity",
    "fluid": "trade_only",
}


def liquidity_contract(venue: str, pool_family: str | None = None) -> LiquidityContract:
    family = pool_family or DEFAULT_POOL_FAMILIES.get(venue)
    if family is None:
        raise ValueError(f"venue {venue!r} requires an explicit pool/invariant family")
    try:
        return LIQUIDITY_CONTRACTS[(venue, family)]
    except KeyError:
        raise ValueError(
            f"venue-family {(venue, family)!r} has no liquidity-semantics contract"
        ) from None


def _resolved_contract(venue: str, pool_family: str | None) -> LiquidityContract | None:
    try:
        return liquidity_contract(venue, pool_family)
    except ValueError:
        return None


def capital_interpretable(venue: str, pool_family: str | None = None) -> bool:
    contract = _resolved_contract(venue, pool_family)
    return bool(contract and contract.capital_ready)


def return_inference_ready(venue: str, pool_family: str | None = None) -> bool:
    contract = _resolved_contract(venue, pool_family)
    return bool(contract and contract.return_inference_ready)


def lvr_inference_ready(venue: str, pool_family: str | None = None) -> bool:
    contract = _resolved_contract(venue, pool_family)
    return bool(contract and contract.lvr_adapter is not None)


def capital_scale_label(venue: str, pool_family: str | None = None) -> str:
    contract = _resolved_contract(venue, pool_family)
    return contract.scale_label if contract else "requires classified pool/invariant family"


def quantity_supported(
    venue: str,
    quantity_kind: str,
    pool_family: str | None = None,
    *,
    use: str | None = None,
) -> bool:
    """Whether a venue has an admitted implementation for one economic quantity."""

    if quantity_kind not in LIQUIDITY_QUANTITY_KINDS:
        raise ValueError(f"unknown liquidity quantity kind: {quantity_kind!r}")
    contract = _resolved_contract(venue, pool_family)
    if not contract:
        return False
    capability = contract.capability(quantity_kind)
    return bool(
        capability.ready
        and (use is None or use in capability.admissible_uses)
    )


def require_quantity_support(
    venue: str,
    quantity_kind: str,
    pool_family: str | None = None,
    *,
    use: str | None = None,
) -> None:
    """Fail closed when an estimator asks a venue for an unsupported object."""

    if not quantity_supported(venue, quantity_kind, pool_family, use=use):
        family = pool_family or DEFAULT_POOL_FAMILIES.get(venue)
        suffix = f" for pool family {family}" if family else " without a classified pool family"
        use_suffix = f" for use {use}" if use else ""
        raise ValueError(f"{venue} does not support {quantity_kind}{suffix}{use_suffix}")


def require_contract_coverage(venues: set[str]) -> None:
    registered = {venue for venue, _family in LIQUIDITY_CONTRACTS}
    missing = venues - registered
    extra = registered - venues
    if missing or extra:
        raise ValueError(
            f"liquidity-contract coverage differs from the venue inventory; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )


def exact_calendar_lag(
    frame: pd.DataFrame,
    *,
    value: str = "reported_capital_usd",
    entity: str = "pool",
    day: str = "day",
) -> pd.Series:
    """Return the exact prior-calendar-day value, never a prior-row substitute."""

    lookup = frame[[entity, day, value]].copy()
    lookup[day] = pd.to_datetime(lookup[day], format="mixed", errors="raise")
    if lookup.duplicated([entity, day]).any():
        raise ValueError(f"duplicate {entity}-day rows cannot define an exact capital lag")
    target = lookup[[entity, day]].copy()
    target["_row_order"] = np.arange(len(target))
    target["prior_day"] = target[day] - pd.Timedelta(days=1)
    source = lookup.rename(columns={day: "prior_day", value: "_lagged_value"})
    matched = target.merge(source, on=[entity, "prior_day"], how="left", validate="one_to_one")
    matched = matched.sort_values("_row_order")
    return pd.Series(matched["_lagged_value"].to_numpy(), index=frame.index, dtype=float)


def capital_reconciliation_mask(
    reported: pd.Series,
    reconstructed: pd.Series,
    *,
    tolerance: float,
) -> pd.Series:
    """Validate provider accounting capital against independently priced holdings."""

    if tolerance <= 1:
        raise ValueError("capital reconciliation tolerance must exceed one")
    reported_value = pd.to_numeric(reported, errors="coerce")
    reconstructed_value = pd.to_numeric(reconstructed, errors="coerce")
    ratio = reconstructed_value / reported_value
    return (
        np.isfinite(reported_value)
        & reported_value.gt(0)
        & np.isfinite(reconstructed_value)
        & reconstructed_value.gt(0)
        & ratio.between(1 / tolerance, tolerance)
    )


def require_capital_denominator(
    frame: pd.DataFrame,
    *,
    venue: str,
    pool_family: str | None = None,
    purpose: str = "return",
) -> None:
    """Fail closed unless a frame carries positive, explicitly sourced lagged capital."""

    if purpose not in {"descriptive", "return"}:
        raise ValueError(f"unknown capital-denominator purpose: {purpose!r}")
    contract = liquidity_contract(venue, pool_family)
    if not contract.capital_ready:
        raise ValueError(f"{venue} has no validated capital measure")
    if purpose == "return" and not contract.return_inference_ready:
        raise ValueError(f"{venue} has no validated return model")
    required = {
        CAPITAL_COLUMN,
        "capital_source",
        "quantity_kind",
        "pool_family",
        "invariant_family",
        "state_generation",
        "capital_validation_status",
        "exact_lag_valid",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"capital frame lacks liquidity-semantics columns: {sorted(missing)}")
    source = frame["capital_source"].fillna("").astype(str)
    if source.str.contains("virtual|local_depth|band_depth", case=False, regex=True).any():
        raise ValueError("local or band depth cannot be a capital source")
    unexpected = set(source.unique()) - set(contract.capital_sources)
    if unexpected:
        raise ValueError(
            f"{venue} capital denominator has unapproved sources: {sorted(unexpected)}"
        )
    capital = pd.to_numeric(frame[CAPITAL_COLUMN], errors="coerce")
    if not (np.isfinite(capital) & capital.gt(0)).all():
        raise ValueError("capital denominator must be finite positive exact-lag capital")
    if not frame["quantity_kind"].eq("deposited_capital").all():
        raise ValueError("capital denominator rows must be typed deposited_capital")
    expected_generation = contract.capability("deposited_capital").state_generation
    identity_mismatch = (
        not frame["pool_family"].eq(contract.pool_family).all()
        or not frame["invariant_family"].eq(contract.invariant_family).all()
        or not frame["state_generation"].eq(expected_generation).all()
    )
    if identity_mismatch:
        raise ValueError(
            "capital denominator family, invariant, or state generation differs from its contract"
        )
    if not frame["exact_lag_valid"].fillna(False).astype(bool).all():
        raise ValueError("capital denominator must retain exact prior-calendar-day validity")
    statuses = set(frame["capital_validation_status"].fillna("").astype(str))
    permitted = (
        {"exact_state_prior_calendar"}
        if purpose == "return"
        else {"exact_state_prior_calendar"}
    )
    unexpected_statuses = statuses - permitted
    if unexpected_statuses:
        raise ValueError(
            f"capital denominator has unapproved validation lineage: {sorted(unexpected_statuses)}"
        )
    if "venue" in frame and not frame["venue"].eq(venue).all():
        raise ValueError(f"capital denominator contains rows outside venue {venue}")
