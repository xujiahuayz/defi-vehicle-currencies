#!/usr/bin/env python3
"""Select Fluid route components for exact receipt checks."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import pandas as pd

from ddvc.analysis.fluid_route_label_validation import deterministic_component_sample
from ddvc.paths import DATA_DIR
from ddvc.runtime import atomic_output


DEFAULT_OUTPUT = DATA_DIR / "interim" / "fluid_route_label_validation_sample.parquet"


def component_population(unified: Path) -> pd.DataFrame:
    columns = [
        "tx_hash",
        "component_id",
        "source",
        "amount_usd",
        "route_class",
        "ambiguous",
    ]
    parts: list[pd.DataFrame] = []
    paths = [
        path
        for path in sorted(unified.glob("[0-9]" * 8 + ".parquet"))
        if "20241029" <= path.stem <= "20260630"
    ]
    for index, path in enumerate(paths, 1):
        frame = pd.read_parquet(path, columns=columns)
        eligible = frame[
            frame["route_class"].astype(str).eq("coherent")
            & ~frame["ambiguous"].fillna(True).astype(bool)
        ].copy()
        eligible["tx_hash"] = eligible["tx_hash"].astype(str).str.lower()
        fluid = eligible[eligible["source"].astype(str).eq("fluid")]
        if fluid.empty:
            continue
        keys = pd.MultiIndex.from_frame(fluid[["tx_hash", "component_id"]])
        component_index = pd.MultiIndex.from_frame(
            eligible[["tx_hash", "component_id"]]
        )
        components = eligible[component_index.isin(keys)].copy()
        components["positive_usd"] = components["amount_usd"].where(
            components["amount_usd"] > 0
        )
        grouped = components.groupby(["tx_hash", "component_id"], sort=True)
        summary = grouped.agg(
            component_value_usd=("positive_usd", "min"),
            component_leg_count=("source", "size"),
            venue_count=("source", "nunique"),
            venues=("source", lambda values: "|".join(sorted(set(map(str, values))))),
        ).reset_index()
        fluid_counts = (
            fluid.groupby(["tx_hash", "component_id"], sort=True)
            .size()
            .rename("fluid_leg_count")
            .reset_index()
        )
        summary = summary.merge(
            fluid_counts,
            on=["tx_hash", "component_id"],
            how="inner",
            validate="one_to_one",
        )
        summary["component_value_usd"] = summary[
            "component_value_usd"
        ].fillna(0.0)
        summary.insert(0, "day", path.stem)
        parts.append(summary)
        if index % 100 == 0 or index == len(paths):
            print(f"  Fluid component days {index:,}/{len(paths):,}", flush=True)
    if not parts:
        raise RuntimeError("unified routes contain no eligible Fluid components")
    return pd.concat(parts, ignore_index=True)


def _raw_fluid_rows(path: Path) -> dict[tuple[str, int], dict]:
    rows: dict[tuple[str, int], dict] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            key = (str(row.get("tx_hash") or "").lower(), int(row["evt_index"]))
            if key in rows:
                raise ValueError(f"Fluid raw day contains a duplicate event: {path.name}/{key}")
            rows[key] = row
    return rows


def attach_fluid_legs(
    selected: pd.DataFrame,
    *,
    unified: Path,
    fluid_raw: Path,
) -> pd.DataFrame:
    """Attach each sampled component's labelled Fluid legs and raw pool identity."""

    records: list[dict[str, object]] = []
    for day, components in selected.groupby("day", sort=True):
        route_path = unified / f"{day}.parquet"
        raw_path = fluid_raw / f"fluid_swaps_{day}.jsonl.gz"
        if not route_path.is_file() or not raw_path.is_file():
            raise FileNotFoundError(f"Fluid sample source is absent for {day}")
        frame = pd.read_parquet(route_path)
        frame["tx_hash"] = frame["tx_hash"].astype(str).str.lower()
        keys = {
            (str(row.tx_hash), int(row.component_id))
            for row in components.itertuples(index=False)
        }
        fluid = frame[
            frame["source"].astype(str).eq("fluid")
            & frame.apply(
                lambda row: (str(row["tx_hash"]), int(row["component_id"])) in keys,
                axis=1,
            )
        ].copy()
        raw_rows = _raw_fluid_rows(raw_path)
        component_rows = {
            (str(row.tx_hash), int(row.component_id)): row._asdict()
            for row in components.itertuples(index=False)
        }
        for leg in fluid.sort_values(
            ["tx_hash", "component_id", "log_index"], kind="mergesort"
        ).itertuples(index=False):
            tx_hash = str(leg.tx_hash)
            component_id = int(leg.component_id)
            log_index = int(leg.log_index)
            raw = raw_rows.get((tx_hash, log_index))
            if raw is None:
                raise ValueError(
                    f"sampled Fluid leg is absent from its raw day: {day}/{tx_hash}/{log_index}"
                )
            token_in = str(raw.get("token_sold_address") or "").lower()
            token_out = str(raw.get("token_bought_address") or "").lower()
            if (
                token_in != str(leg.token_in).lower()
                or token_out != str(leg.token_out).lower()
            ):
                raise ValueError(
                    f"sampled Fluid leg differs from its raw token labels: "
                    f"{day}/{tx_hash}/{log_index}"
                )
            selection = component_rows[(tx_hash, component_id)]
            records.append(
                {
                    **selection,
                    "log_index": log_index,
                    "block_number": int(raw["block_number"]),
                    "pool": str(raw.get("pool") or "").lower(),
                    "token_in": token_in,
                    "token_out": token_out,
                    "token_in_symbol": str(raw.get("token_sold_symbol") or ""),
                    "token_out_symbol": str(raw.get("token_bought_symbol") or ""),
                    "amount_in": float(raw["token_sold_amount"]),
                    "amount_out": float(raw["token_bought_amount"]),
                    "amount_usd": float(raw.get("amount_usd") or 0),
                }
            )
    output = pd.DataFrame(records)
    observed = (
        output.groupby(["tx_hash", "component_id"], sort=False).size().to_dict()
    )
    for row in selected.itertuples(index=False):
        key = (str(row.tx_hash), int(row.component_id))
        if observed.get(key) != int(row.fluid_leg_count):
            raise ValueError(f"sampled Fluid component lost labelled legs: {key}")
    if output.empty or output[["tx_hash", "log_index"]].duplicated().any():
        raise ValueError("Fluid validation sample is empty or duplicates an event")
    return output.sort_values(
        ["half_year", "venue_scope", "selection_basis", "selection_rank", "log_index"],
        kind="mergesort",
    ).reset_index(drop=True)


def run(
    *,
    unified: Path,
    fluid_raw: Path,
    output: Path,
) -> pd.DataFrame:
    population = component_population(unified)
    selected = deterministic_component_sample(population)
    sample = attach_fluid_legs(selected, unified=unified, fluid_raw=fluid_raw)
    output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(output) as temporary:
        sample.to_parquet(temporary, index=False)
    print(
        f"wrote {sample[['tx_hash', 'component_id']].drop_duplicates().shape[0]:,} "
        f"components and {len(sample):,} Fluid legs to {output}"
    )
    return sample


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unified", type=Path, default=DATA_DIR / "unified")
    parser.add_argument(
        "--fluid-raw",
        type=Path,
        default=DATA_DIR / "raw" / "dune" / "fluid",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(unified=args.unified, fluid_raw=args.fluid_raw, output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
