from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
import pandas as pd

import scripts.run_stress_reallocation_e0 as runner
from ddvc.analysis.stress_reallocation_e0 import (
    StressDesign,
    compare_daily_reference_sources,
    conditional_role_composition,
    decompose_event,
    direction_comparability_diagnostic,
    fit_direction_fixed_effects,
    one_sample_small_cluster_inference,
    prepare_etherscan_daily_reference,
    select_reference_events,
)


def _raw_prices(dates: pd.DatetimeIndex, prices: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date(UTC)": [f"{day.month}/{day.day}/{day.year}" for day in dates],
            "UnixTimeStamp": [int(day.timestamp()) for day in dates],
            "Value": prices,
        }
    )


class StressPriceSourceTests(unittest.TestCase):
    def test_price_validity_and_conservative_availability(self) -> None:
        dates = pd.date_range("2024-01-01", periods=5)
        frame = prepare_etherscan_daily_reference(
            _raw_prices(dates, np.array([100.0, 90.0, 99.0, 101.0, 102.0]))
        )
        self.assertEqual(frame.iloc[0]["available_date"], pd.Timestamp("2024-01-02"))
        self.assertEqual(
            frame.iloc[0]["event_hour"],
            int(pd.Timestamp("2024-01-02", tz="UTC").timestamp() // 3600),
        )
        self.assertAlmostEqual(frame.iloc[1]["daily_log_return"], np.log(0.9))

    def test_daily_returns_require_consecutive_dates(self) -> None:
        dates = pd.DatetimeIndex(["2024-01-01", "2024-01-03"])
        with self.assertRaisesRegex(ValueError, "not consecutive"):
            prepare_etherscan_daily_reference(
                _raw_prices(dates, np.array([100.0, 101.0]))
            )

    def test_independent_source_alignment_and_agreement(self) -> None:
        dates = pd.date_range("2024-01-01", periods=90)
        returns = 0.002 + 0.01 * np.sin(np.arange(len(dates)) / 5)
        prices = 100 * np.exp(returns.cumsum())
        primary = prepare_etherscan_daily_reference(_raw_prices(dates, prices))
        comparator = pd.DataFrame(
            {
                "date": primary["available_date"],
                "eth_price_usd": primary["eth_usd"] * 1.0005,
            }
        )
        audit = compare_daily_reference_sources(primary, comparator)
        self.assertEqual(audit["overlap_days"], 90)
        self.assertGreater(audit["log_return_correlation"], 0.999)
        self.assertLess(audit["median_absolute_relative_difference"], 0.001)

    def test_symmetric_selection_uses_direct_calendar_collisions(self) -> None:
        dates = pd.date_range("2024-01-01", periods=70)
        returns = np.zeros(len(dates))
        returns[2] = -0.10
        returns[3] = 0.20  # wins the joint collision cluster
        returns[22] = -0.12
        returns[45] = 0.11
        prices = 100 * np.exp(returns.cumsum())
        reference = prepare_etherscan_daily_reference(_raw_prices(dates, prices))
        selected, excluded = select_reference_events(
            reference,
            StressDesign(
                cluster_gap_days=14,
                event_count_per_direction=5,
                randomization_repetitions=99,
            ),
            sample_start="2024-01-01",
            sample_end="2024-03-31",
        )
        self.assertEqual(set(selected["event_type"]), {"drawdown", "rally"})
        self.assertNotIn(pd.Timestamp("2024-01-03"), set(selected["observation_date"]))
        self.assertIn(
            "direct_calendar_collision_with_higher_priority_move",
            set(excluded["reason"]),
        )
        rejected = excluded.loc[
            excluded["observation_date"].eq(pd.Timestamp("2024-01-03"))
        ].iloc[0]
        self.assertEqual(rejected["calendar_distance_days"], 1)
        self.assertEqual(
            rejected["collision_reference_date"], pd.Timestamp("2024-01-04")
        )
        gaps = selected["observation_date"].sort_values().diff().dt.days.dropna()
        self.assertTrue(gaps.gt(14).all())

    def test_long_chain_does_not_create_transitive_calendar_collision(self) -> None:
        dates = pd.date_range("2024-01-01", periods=80)
        returns = np.zeros(len(dates))
        returns[1] = 0.30
        returns[11] = -0.20
        returns[21] = -0.18
        returns[55] = 0.16
        prices = 100 * np.exp(returns.cumsum())
        reference = prepare_etherscan_daily_reference(_raw_prices(dates, prices))
        selected, excluded = select_reference_events(
            reference,
            StressDesign(
                cluster_gap_days=14,
                event_count_per_direction=5,
                randomization_repetitions=99,
            ),
            sample_start="2024-01-01",
            sample_end="2024-03-31",
        )
        selected_dates = set(selected["observation_date"])
        self.assertIn(pd.Timestamp("2024-01-02"), selected_dates)
        self.assertIn(pd.Timestamp("2024-01-22"), selected_dates)
        chained = excluded.loc[
            excluded["observation_date"].eq(pd.Timestamp("2024-01-12"))
        ].iloc[0]
        self.assertEqual(chained["calendar_distance_days"], 10)
        self.assertEqual(
            chained["collision_reference_date"], pd.Timestamp("2024-01-02")
        )


class StressEstimatorTests(unittest.TestCase):
    def test_exit_reweighting_and_substitution_are_exact_and_separate(self) -> None:
        rows = []
        values = {
            ("a>b", -1): (80.0, 20.0),
            ("c>d", -1): (20.0, 80.0),
            # a>b exits; c>d continues and changes its intermediary composition
            ("c>d", 1): (50.0, 50.0),
        }
        for (pair, relative_hour), (native, stable) in values.items():
            src, tgt = pair.split(">")
            for candidate, amount in (("native", native), ("stable", stable)):
                rows.append(
                    {
                        "pair": pair,
                        "src": src,
                        "tgt": tgt,
                        "hour": relative_hour,
                        "relative_hour": relative_hour,
                        "candidate_type": candidate,
                        "route_count": amount,
                    }
                )
        result = decompose_event(
            pd.DataFrame(rows), "route_count", minimum_pre_hours=1
        )
        self.assertEqual(result["exited_pairs"], 1)
        self.assertAlmostEqual(result["exited_pair_pre_activity_share"], 0.5)
        self.assertNotEqual(result["pair_exit_composition"], 0.0)
        self.assertAlmostEqual(
            result["native_share_change"],
            result["pair_exit_composition"]
            + result["continuing_pair_activity_reallocation"]
            + result["continuing_pair_intermediary_substitution"],
        )
        self.assertAlmostEqual(result["decomposition_residual"], 0.0)

    def test_pre_route_support_sensitivity_changes_only_support(self) -> None:
        rows = []
        for pair, pre_hours in (("a>b", [-2, -1]), ("c>d", [-1])):
            src, tgt = pair.split(">")
            for hour in [*pre_hours, 1]:
                for candidate in ("native", "stable"):
                    rows.append(
                        {
                            "pair": pair,
                            "src": src,
                            "tgt": tgt,
                            "hour": hour,
                            "relative_hour": hour,
                            "candidate_type": candidate,
                            "route_count": 1.0,
                        }
                    )
        frame = pd.DataFrame(rows)
        loose = decompose_event(frame, "route_count", minimum_pre_hours=1)
        strict = decompose_event(frame, "route_count", minimum_pre_hours=2)
        self.assertEqual(loose["pairs"], 2)
        self.assertEqual(strict["pairs"], 1)

    def test_small_cluster_inference_is_deterministic(self) -> None:
        values = np.array([0.08, 0.05, -0.01, 0.06, 0.03, 0.02, 0.04, 0.01])
        first = one_sample_small_cluster_inference(
            values, label="test", repetitions=999
        )
        second = one_sample_small_cluster_inference(
            values, label="test", repetitions=999
        )
        self.assertEqual(
            first["wild_sign_flip_p_value"], second["wild_sign_flip_p_value"]
        )
        self.assertGreaterEqual(first["sign_test_p_value"], 0.0)
        self.assertLessEqual(first["sign_test_p_value"], 1.0)
        zero = one_sample_small_cluster_inference(
            np.zeros(8), label="zero", repetitions=999
        )
        self.assertEqual(zero["wild_sign_flip_p_value"], 1.0)
        self.assertEqual(zero["p_value"], 1.0)

    def test_two_way_fixed_effects_recovers_known_direction_difference(self) -> None:
        rows = []
        beta = 0.08
        for event_number in range(10):
            event = f"event-{event_number}"
            event_type = "drawdown" if event_number < 5 else "rally"
            for pair_number in range(3):
                pair = f"s{pair_number}>t{pair_number}"
                pair_effect = 0.01 * pair_number
                for relative_hour in range(-4, 4):
                    time_effect = 0.002 * relative_hour
                    share = (
                        0.40
                        + pair_effect
                        + time_effect
                        + beta
                        * (event_type == "drawdown")
                        * (relative_hour >= 0)
                    )
                    for candidate, amount in (
                        ("native", 100.0 * share),
                        ("stable", 100.0 * (1 - share)),
                    ):
                        rows.append(
                            {
                                "event": event,
                                "event_type": event_type,
                                "pair": pair,
                                "src": f"s{pair_number}",
                                "tgt": f"t{pair_number}",
                                "hour": event_number * 100 + relative_hour,
                                "relative_hour": relative_hour,
                                "candidate_type": candidate,
                                "route_count": amount,
                            }
                        )
        result = fit_direction_fixed_effects(
            pd.DataFrame(rows),
            "route_count",
            minimum_pre_hours=2,
            randomization_repetitions=999,
        )
        self.assertAlmostEqual(result["estimate"], beta, places=10)
        sensitivity = fit_direction_fixed_effects(
            pd.DataFrame(rows),
            "route_count",
            minimum_pre_hours=3,
            randomization_repetitions=999,
        )
        self.assertEqual(sensitivity["specification"], "pre_support_3_hours")

    def test_direction_comparability_exposes_imbalance_without_forcing_match(self) -> None:
        events = pd.DataFrame(
            [
                {
                    "event": f"2020-01-{day:02d}",
                    "event_type": "drawdown" if day <= 4 else "rally",
                    "daily_log_return": -0.10 if day <= 4 else 0.30,
                }
                for day in range(1, 9)
            ]
        )
        diagnostic, matched = direction_comparability_diagnostic(events)
        self.assertFalse(diagnostic["matching_eligible"])
        self.assertEqual(matched, ())
        self.assertIn("no matched model", diagnostic["matching_decision"])

    def test_broader_endpoint_comparison_is_labeled_conditional(self) -> None:
        weth = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
        usdc = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
        other = "0x1111111111111111111111111111111111111111"
        choices = pd.DataFrame(
            [
                {"hour": 99, "src": weth, "tgt": other, "candidate_type": "stable", "route_count": 10},
                {"hour": 99, "src": usdc, "tgt": other, "candidate_type": "native", "route_count": 10},
                {"hour": 100, "src": weth, "tgt": other, "candidate_type": "stable", "route_count": 20},
                {"hour": 100, "src": usdc, "tgt": other, "candidate_type": "native", "route_count": 5},
            ]
        )
        result = conditional_role_composition(
            choices,
            event_hour=100,
            measure="route_count",
            design=StressDesign(hours_before=1, hours_after=1),
        )
        self.assertAlmostEqual(result["endpoint_native_share_pre"], 0.5)
        self.assertAlmostEqual(result["endpoint_native_share_post"], 0.8)


class StressProvenanceTests(unittest.TestCase):
    @staticmethod
    def _record(path: Path, role: str) -> dict[str, object]:
        payload = path.read_bytes()
        return {
            "role": role,
            "path": str(path),
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def test_source_and_code_tampering_fail_hash_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            code = root / "owner.py"
            source.write_text("date,price\n2024-01-01,100\n")
            code.write_text("VALUE = 1\n")
            records = [self._record(source, "source"), self._record(code, "code")]
            runner.verify_hash_records(records)
            code.write_text("VALUE = 2\n")
            with self.assertRaisesRegex(RuntimeError, "bound code changed"):
                runner.verify_hash_records(records)

    def test_continuous_file_lease_rejects_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "price.csv"
            source.write_text("date,price\n2024-01-01,100\n")
            with self.assertRaisesRegex(RuntimeError, "leased source file changed"):
                with runner.current_stress_files([source]):
                    source.write_text("date,price\n2024-01-01,101\n")

    def test_run_holds_price_quality_and_release_leases_through_owner(self) -> None:
        active: set[str] = set()
        code_paths = {runner.REPO_ROOT / path for path in runner.CODE_SOURCES}

        @contextmanager
        def files(paths):
            label = "code" if set(paths) == code_paths else "files"
            active.add(label)
            try:
                yield ()
            finally:
                active.remove(label)

        @contextmanager
        def quality(_paths, *, consumer: str):
            self.assertIn("route-quality", consumer)
            active.add("quality")
            try:
                yield ()
            finally:
                active.remove("quality")

        @contextmanager
        def release():
            active.add("release")
            try:
                yield SimpleNamespace(generation_id="a" * 64)
            finally:
                active.remove("release")

        def owner(*_args, **_kwargs):
            self.assertEqual(active, {"code", "files", "quality", "release"})
            return 7

        with (
            mock.patch.object(runner, "current_stress_files", files),
            mock.patch.object(runner, "current_artifacts", quality),
            mock.patch.object(runner, "current_stress_composition_release", release),
            mock.patch.object(runner, "_run_under_leases", owner),
        ):
            result = runner.run(
                StressDesign(),
                price_source=Path("price"),
                comparator=Path("comparator"),
                comparator_raw=Path("raw"),
            )
        self.assertEqual(result, 7)
        self.assertEqual(active, set())

    def test_run_rejects_scientific_code_mutation_during_owner(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="stress-code-race-", dir=runner.REPO_ROOT
        ) as directory:
            root = Path(directory)
            code = root / "scientific_owner.py"
            code.write_text("VALUE = 1\n")
            prices = [root / name for name in ("price", "comparator", "raw")]
            for path in prices:
                path.write_text(path.name)
            relative = code.relative_to(runner.REPO_ROOT).as_posix()

            @contextmanager
            def quality(_paths, *, consumer: str):
                yield ()

            @contextmanager
            def release():
                yield SimpleNamespace(generation_id="a" * 64)

            def mutate(*_args, **_kwargs):
                code.write_text("VALUE = 2\n")
                return 0

            try:
                with (
                    mock.patch.object(runner, "CODE_SOURCES", [relative]),
                    mock.patch.object(runner, "current_artifacts", quality),
                    mock.patch.object(
                        runner, "current_stress_composition_release", release
                    ),
                    mock.patch.object(runner, "_run_under_leases", mutate),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "leased source file changed"
                    ):
                        runner.run(
                            StressDesign(),
                            price_source=prices[0],
                            comparator=prices[1],
                            comparator_raw=prices[2],
                        )
            finally:
                manifest_root = (
                    runner.REPO_ROOT
                    / "data/manifests"
                    / root.relative_to(runner.REPO_ROOT)
                )
                shutil.rmtree(manifest_root, ignore_errors=True)

    def test_canonical_composition_lease_propagates_stale_and_partial_failures(self) -> None:
        @contextmanager
        def stale(_pointer: Path):
            raise ValueError("semantic-validation receipt is stale")
            yield  # pragma: no cover

        @contextmanager
        def partial(_pointer: Path):
            raise FileNotFoundError("partial endpoint-candidate generation")
            yield  # pragma: no cover

        pointer = Path("synthetic-current.json")
        for factory, message in (
            (stale, "receipt is stale"),
            (partial, "partial endpoint-candidate"),
        ):
            with self.subTest(message=message):
                with mock.patch.object(
                    runner,
                    "current_endpoint_candidate_composition_release",
                    factory,
                ):
                    with self.assertRaisesRegex((ValueError, FileNotFoundError), message):
                        with runner.current_stress_composition_release(pointer):
                            self.fail("invalid release was admitted")

    def test_scientific_code_source_perimeter_is_complete(self) -> None:
        required = {
            "src/ddvc/realised.py",
            "src/ddvc/route_roles.py",
            "src/ddvc/fetch/sources.py",
            "src/ddvc/endpoint_candidate_composition.py",
            "src/ddvc/endpoint_candidate_composition_release.py",
            "src/ddvc/artifact_release.py",
            "src/ddvc/reconstruct.py",
        }
        self.assertTrue(required.issubset(set(runner.CODE_SOURCES)))

    def test_support_exclusion_provenance_includes_route_and_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            price = root / "price.csv"
            route = root / "route.parquet"
            marker = root / "route.json"
            for path in (price, route, marker):
                path.write_text(path.name)
            with mock.patch.object(runner, "write_exhibit") as writer:
                runner.write_selection_exclusions(
                    pd.DataFrame([{"reason": "no_pre_supported_ordered_pairs"}]),
                    provenance_inputs=[price, route, marker],
                    notes="red",
                )
            inputs = writer.call_args.kwargs["inputs"]
            self.assertEqual(inputs, [price, route, marker])

    def test_price_inputs_have_no_machine_specific_defaults(self) -> None:
        with self.assertRaisesRegex(ValueError, "no machine-specific price defaults"):
            runner.resolve_price_inputs(None, None, None)
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ("a", "b", "c")]
            for path in paths:
                path.write_text(path.name)
            resolved = runner.resolve_price_inputs(*paths)
            self.assertEqual(resolved, tuple(path.resolve() for path in paths))

    def test_summarize_only_declares_package_replay_boundary(self) -> None:
        record = runner.summarize_only_boundary_record()
        self.assertEqual(record["mode"], "package_replay_not_raw_input_rebuild")
        self.assertFalse(record["raw_input_rebuild"])
        self.assertIn("does not reconstruct", record["boundary"])

    def test_manifest_json_is_recursive_strict_json(self) -> None:
        payload = {
            "top": np.nan,
            "nested": {
                "values": [np.inf, -np.inf, pd.NA, np.float64(2.5)],
            },
        }
        text = runner._strict_json_bytes(payload).decode("utf-8")

        def reject(value: str) -> object:
            raise ValueError(f"non-finite constant: {value}")

        decoded = json.loads(text, parse_constant=reject)
        self.assertIsNone(decoded["top"])
        self.assertEqual(decoded["nested"]["values"], [None, None, None, 2.5])
        with self.assertRaisesRegex(ValueError, "non-finite constant"):
            json.loads('{"value": NaN}', parse_constant=reject)

    def test_manifest_replay_requires_detached_provenance_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            source = root / "source"
            pointer = root / "current.json"
            outputs = [root / f"output-{index}" for index in range(5)]
            for path in [source, pointer, *outputs]:
                path.write_text(path.name)
            code_sources = ["scripts/run_stress_reallocation_e0.py"]
            manifest = {
                "source_inputs": [self._record(source, "source")],
                "composition_release": self._record(
                    pointer, "composition_release_pointer"
                ),
                "route_inputs": [],
                "code_inputs": [
                    self._record(runner.REPO_ROOT / code_sources[0], "code")
                ],
                "outputs": [self._record(path, "derived_output") for path in outputs],
            }
            manifest_path.write_bytes(runner._strict_json_bytes(manifest))
            with mock.patch.object(runner, "CODE_SOURCES", code_sources):
                runner.stamp(
                    manifest_path,
                    code_sources=code_sources,
                    inputs=[source, pointer, *outputs],
                    notes="test",
                    script="scripts/run_stress_reallocation_e0.py",
                )
                with runner.current_stress_manifest(manifest_path) as authenticated:
                    self.assertEqual(authenticated, manifest)

                replaced = dict(manifest)
                replaced["status"] = "replaced"
                manifest_path.write_bytes(runner._strict_json_bytes(replaced))
                with self.assertRaisesRegex(RuntimeError, "requires current analysis"):
                    with runner.current_stress_manifest(manifest_path):
                        self.fail("replacement manifest was trusted")

                manifest_path.write_bytes(runner._strict_json_bytes(manifest))
                runner.stamp(
                    manifest_path,
                    code_sources=code_sources,
                    inputs=[source, pointer, *outputs],
                    notes="test",
                    script="scripts/run_stress_reallocation_e0.py",
                )
                false_identity = json.loads(json.dumps(manifest))
                false_identity["source_inputs"][0]["sha256"] = "0" * 64
                manifest_path.write_bytes(runner._strict_json_bytes(false_identity))
                runner.stamp(
                    manifest_path,
                    code_sources=code_sources,
                    inputs=[source, pointer, *outputs],
                    notes="test",
                    script="scripts/run_stress_reallocation_e0.py",
                )
                with self.assertRaisesRegex(
                    RuntimeError, "disagree with detached provenance"
                ):
                    with runner.current_stress_manifest(manifest_path):
                        self.fail("manifest-owned hash displaced the trust anchor")

    def test_manifest_rejects_changed_hourly_bytes_and_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            pointer = root / "current.json"
            outputs = [root / name for name in ("summary", "events", "hourly", "exclusions", "audit")]
            summary, events, hourly, exclusions, audit = outputs
            source.write_text("source")
            for output in outputs:
                output.write_text(f"{output.name}-v1")
            generation = "a" * 64
            pointer.write_text(json.dumps({"generation_id": generation}))
            manifest = {
                "source_inputs": [self._record(source, "source")],
                "composition_release": {
                    **self._record(pointer, "composition_release_pointer"),
                    "generation_id": generation,
                },
                "route_inputs": [],
                "code_inputs": [],
                "outputs": [
                    self._record(output, "derived_output") for output in outputs
                ],
            }
            with (
                mock.patch.object(runner, "COMPOSITION_POINTER", pointer),
                mock.patch.object(runner, "SUMMARY", summary),
                mock.patch.object(runner, "EVENT_OUTPUT", events),
                mock.patch.object(runner, "HOURLY_OUTPUT", hourly),
                mock.patch.object(runner, "SELECTION_EXCLUSIONS", exclusions),
                mock.patch.object(runner, "SOURCE_AUDIT", audit),
                mock.patch.object(
                    runner,
                    "_composition_release_record",
                    lambda _release: manifest["composition_release"],
                ),
            ):
                release = SimpleNamespace(generation_id=generation)
                runner.verify_manifest_state(
                    manifest, composition_release=release
                )
                hourly.write_text("hourly-v2")
                with self.assertRaisesRegex(RuntimeError, "derived_output changed"):
                    runner.verify_manifest_state(
                        manifest, composition_release=release
                    )

    def test_raw_coingecko_payload_binds_derived_comparator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "ethereum.json"
            comparator = root / "eth_price.parquet"
            day = pd.Timestamp("2025-06-03", tz="UTC")
            timestamp = int(day.timestamp() * 1000)
            raw.write_text(
                json.dumps(
                    {
                        "prices": [[timestamp, 2500.0]],
                        "market_caps": [[timestamp, 300_000_000_000.0]],
                        "total_volumes": [[timestamp, 1.0]],
                    }
                )
            )
            pd.DataFrame(
                {
                    "date": [day.tz_localize(None)],
                    "eth_price_usd": [2500.0],
                    "eth_market_cap_usd": [300_000_000_000.0],
                }
            ).to_parquet(comparator, index=False)
            result = runner.verify_coingecko_raw_comparator(raw, comparator)
            self.assertEqual(result["derived_rows_verified_against_raw"], 1)


if __name__ == "__main__":
    unittest.main()
