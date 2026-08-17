from __future__ import annotations

import tempfile
import unittest
from contextlib import nullcontext
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from ddvc.data_release import (
    _exact_key_gate,
    _validated_release_ledger,
    ReleasedPartition,
    ReleasedPartitionSet,
    audit_cross_venue_order_conflicts,
    released_route_partitions,
    released_state_partitions,
    release_preinstall_validator,
    require_market_state_release,
    require_v2_event_source_release,
    require_v3_event_source_release,
)
from ddvc.artifact_release import file_sha256
from ddvc.provenance import sidecar_path, verify
from ddvc.state_data import QUALITY_COLUMNS, SCHEMA_VERSION, STATE_ENGINE
from ddvc.tables import write_panel
from ddvc.v4_quarantine import audit_v4_pool_static_conflicts


class DataReleaseTests(unittest.TestCase):
    @staticmethod
    def _test_release(root: Path) -> ReleasedPartitionSet:
        ledger = root / "ledger.parquet"
        ledger.write_bytes(b"ledger")
        panel = root / "source.parquet"
        panel.write_bytes(b"source-a")
        marker = root / "source.quality.json"
        marker.write_bytes(b'{"passed":true}\n')
        partition = ReleasedPartition(
            day="20250101",
            path=panel,
            marker_path=marker,
            expected_rows=1,
            expected_bytes=panel.stat().st_size,
            expected_sha256=file_sha256(panel),
            marker_sha256=file_sha256(marker),
            input_fingerprint="a" * 64,
        )
        return ReleasedPartitionSet(
            kind="state",
            columns=("value",),
            ledger_path=ledger,
            ledger_sha256=file_sha256(ledger),
            partitions=(partition,),
            content_identity_sha256="b" * 64,
            provenance_inputs=(ledger, panel, marker),
        )

    def test_release_validator_rejects_mutation_before_install_and_preserves_prior_pair(self) -> None:
        class MutatedRelease:
            @staticmethod
            def assert_current() -> None:
                raise RuntimeError("released state marker changed")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "panel.parquet"
            pd.DataFrame({"value": [1]}).to_parquet(output, index=False)
            prior = output.read_bytes()
            sidecar = sidecar_path(output)
            sidecar.write_bytes(b"prior-sidecar\n")
            with self.assertRaisesRegex(RuntimeError, "marker changed"):
                write_panel(
                    pd.DataFrame({"value": [2]}),
                    output,
                    code_sources=["tests/test_data_release.py"],
                    preinstall_validator=release_preinstall_validator(MutatedRelease()),
                )
            self.assertEqual(output.read_bytes(), prior)
            self.assertEqual(sidecar.read_bytes(), b"prior-sidecar\n")

    def test_release_mutation_during_provenance_preparation_cannot_install_or_misstamp(self) -> None:
        from unittest.mock import patch
        import ddvc.tables as tables

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = self._test_release(root)
            output = root / "result.parquet"
            pd.DataFrame({"value": [1]}).to_parquet(output, index=False)
            prior = output.read_bytes()
            sidecar = sidecar_path(output)
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_bytes(b"prior-sidecar\n")
            original_prepare = tables.prepare_stamp

            def mutate_then_prepare(*args, **kwargs):
                release.partitions[0].marker_path.write_bytes(b'{"passed":false}\n')
                return original_prepare(*args, **kwargs)

            with (
                patch("ddvc.tables.prepare_stamp", side_effect=mutate_then_prepare),
                self.assertRaisesRegex(RuntimeError, "marker changed"),
            ):
                write_panel(
                    pd.DataFrame({"value": [2]}),
                    output,
                    code_sources=["tests/test_data_release.py"],
                    inputs=list(release.provenance_inputs),
                    preinstall_validator=release_preinstall_validator(release),
                )
            self.assertEqual(output.read_bytes(), prior)
            self.assertEqual(sidecar.read_bytes(), b"prior-sidecar\n")

    def test_exact_release_binding_detects_large_input_mutation_with_restored_mtime(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = self._test_release(root)
            source = release.partitions[0].path
            source_stat = source.stat()
            output = root / "result.parquet"
            with patch("ddvc.provenance.CONTENT_HASH_MAX_BYTES", 0):
                write_panel(
                    pd.DataFrame({"value": [2]}),
                    output,
                    code_sources=["tests/test_data_release.py"],
                    inputs=list(release.provenance_inputs),
                    preinstall_validator=release_preinstall_validator(release),
                )
                stamped = json.loads(sidecar_path(output).read_text())
                self.assertEqual(len(stamped["released_input_bindings"]), 3)
                source.write_bytes(b"source-b")
                os.utime(
                    source,
                    ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
                )
                verdict = verify(output)
            self.assertEqual(verdict["status"], "stale")
            self.assertIn(str(source.resolve()), verdict["changed_inputs"])

    def test_release_bound_provenance_ignores_mtime_only_drift_but_tracks_science(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "scientific.py"
            dependency.write_text("VALUE = 1\n", encoding="utf-8")
            release = self._test_release(root)
            output = root / "result.parquet"
            with (
                patch("ddvc.provenance.ROOT", root),
                patch("ddvc.provenance.MANIFESTS", root / "manifests"),
                patch("ddvc.data_release.REPO_ROOT", root),
            ):
                write_panel(
                    pd.DataFrame({"value": [2]}),
                    output,
                    code_sources=["scientific.py"],
                    inputs=list(release.provenance_anchors),
                    preinstall_validator=release_preinstall_validator(release),
                )
                stamped = json.loads(sidecar_path(output).read_text())
                self.assertEqual(len(stamped["inputs"]), 1)
                self.assertTrue(stamped["inputs"][0]["path"].endswith("ledger.parquet"))
                self.assertEqual(stamped["inputs"][0]["sha256"], release.ledger_sha256)
                self.assertEqual(len(stamped["released_input_bindings"]), 3)

                for path in release.provenance_inputs:
                    stat = path.stat()
                    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
                self.assertEqual(verify(output)["status"], "ok")

                dependency.write_text("VALUE = 2\n", encoding="utf-8")
                self.assertEqual(verify(output)["status"], "stale")
                dependency.write_text("VALUE = 1\n", encoding="utf-8")
                self.assertEqual(verify(output)["status"], "ok")

                source = release.partitions[0].path
                source.write_bytes(b"source-b")
                verdict = verify(output)
                self.assertEqual(verdict["status"], "stale")
                self.assertIn(str(source.resolve()), verdict["changed_inputs"])

    def test_independent_multi_output_contract_cannot_leave_a_stale_member_current(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = self._test_release(root)
            validator = release_preinstall_validator(release)
            first = root / "first.parquet"
            second = root / "second.parquet"
            write_panel(
                pd.DataFrame({"value": [1]}),
                first,
                code_sources=["tests/test_data_release.py"],
                inputs=list(release.provenance_inputs),
                preinstall_validator=validator,
            )
            pd.DataFrame({"value": [0]}).to_parquet(second, index=False)
            prior_second = second.read_bytes()
            second_sidecar = sidecar_path(second)
            second_sidecar.parent.mkdir(parents=True, exist_ok=True)
            second_sidecar.write_bytes(b"prior-sidecar\n")
            release.partitions[0].marker_path.write_bytes(b'{"passed":false}\n')
            with self.assertRaisesRegex(RuntimeError, "marker changed"):
                write_panel(
                    pd.DataFrame({"value": [2]}),
                    second,
                    code_sources=["tests/test_data_release.py"],
                    inputs=list(release.provenance_inputs),
                    preinstall_validator=validator,
                )
            self.assertEqual(verify(first)["status"], "stale")
            self.assertEqual(second.read_bytes(), prior_second)
            self.assertEqual(second_sidecar.read_bytes(), b"prior-sidecar\n")

    def test_market_state_producer_publishes_engine_contract_consumed_by_release_gate(self) -> None:
        from unittest.mock import patch
        from scripts.build_market_state import market_state_quality_frame

        row = {column: 0 for column in QUALITY_COLUMNS}
        row.update(
            {
                "schema_version": SCHEMA_VERSION,
                "family": "tick",
                "venue": "uniswap_v3",
                "day": "20250101",
                "input_fingerprint": "c" * 64,
                "output_sha256": "d" * 64,
                "passed": True,
            }
        )
        produced = market_state_quality_frame([row])
        self.assertEqual(produced["engine"].tolist(), [STATE_ENGINE])
        produced["cross_venue_order_conflicts"] = 0
        produced["v4_static_conflict_pools"] = 0
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "market-state-quality.parquet"
            produced.to_parquet(ledger, index=False)
            with (
                patch("ddvc.data_release.MARKET_STATE_QUALITY_PANEL", ledger),
                patch("ddvc.data_release.current_artifacts", return_value=nullcontext()),
                patch("ddvc.data_release.expected_state_keys", return_value=[("tick", "uniswap_v3", "20250101")]),
                patch("ddvc.data_release.read_tick_quality", return_value=SimpleNamespace()),
                patch("ddvc.data_release.load_v4_static_quarantine", return_value=set()),
            ):
                consumed = _validated_release_ledger("state")
        self.assertEqual(list(consumed.columns), list(produced.columns))

    def test_released_route_partitions_bind_exact_order_rows_and_mutation_safe_reads(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "route-ledger.parquet"
            ledger.write_bytes(b"ledger")
            panel = root / "20250101.parquet"
            pd.DataFrame(
                [
                    {"source": "uniswap_v2", "tx_hash": "0xa"},
                    {"source": "uniswap_v3", "tx_hash": "0xb"},
                ]
            ).to_parquet(panel, index=False)
            marker = root / "20250101.json"
            quality = {
                "day": "20250101",
                "input_fingerprint": "a" * 64,
                "output_rows": 2,
                "output_bytes": panel.stat().st_size,
                "output_sha256": file_sha256(panel),
                "passed": True,
            }
            marker.write_text(json.dumps(quality), encoding="utf-8")
            empty_panel = root / "20250102.parquet"
            pd.DataFrame(columns=["source", "tx_hash"]).to_parquet(empty_panel, index=False)
            empty_marker = root / "20250102.json"
            empty_quality = {
                **quality,
                "day": "20250102",
                "output_rows": 0,
                "output_bytes": empty_panel.stat().st_size,
                "output_sha256": file_sha256(empty_panel),
            }
            empty_marker.write_text(json.dumps(empty_quality), encoding="utf-8")
            ledger_frame = pd.DataFrame([quality, empty_quality])
            ledger_frame.attrs["ledger_sha256"] = file_sha256(ledger)
            empty_ledger_frame = pd.DataFrame([empty_quality])
            empty_ledger_frame.attrs["ledger_sha256"] = file_sha256(ledger)
            panels = {"20250101": panel, "20250102": empty_panel}
            markers = {"20250101": marker, "20250102": empty_marker}
            with (
                patch("ddvc.data_release.UNIFIED_QUALITY_PANEL", ledger),
                patch("ddvc.data_release.ROUTE_RELEASE_ROOT", root),
                patch("ddvc.data_release.current_artifacts", return_value=nullcontext()),
                patch("ddvc.data_release._validated_release_ledger_unlocked", return_value=ledger_frame),
                patch("ddvc.data_release.unified_path", side_effect=lambda day: panels[day]),
                patch("ddvc.data_release.unified_quality_path", side_effect=lambda day: markers[day]),
            ):
                release = released_route_partitions(("source", "tx_hash"), nonempty=True)
                self.assertEqual(release.days, ("20250101",))
                self.assertEqual(release.expected_rows, (2,))
                self.assertEqual(
                    released_route_partitions(("source",), nonempty=False).days,
                    ("20250101", "20250102"),
                )
                with (
                    patch("ddvc.data_release._validated_release_ledger_unlocked", return_value=empty_ledger_frame),
                    self.assertRaisesRegex(RuntimeError, "no nonempty partitions"),
                ):
                    released_route_partitions(("source",), nonempty=True)
                self.assertEqual(release.read_day("2025-01-01")["tx_hash"].tolist(), ["0xa", "0xb"])
                self.assertEqual(len(release.content_identity_sha256), 64)
                subset = release.select_days(("2025-01-01",))
                self.assertEqual(subset.days, ("20250101",))
                self.assertNotEqual(subset.content_identity_sha256, release.content_identity_sha256)
                self.assertEqual(subset.read_day("20250101")["tx_hash"].tolist(), ["0xa", "0xb"])
                with self.assertRaisesRegex(ValueError, "nonempty and unique"):
                    release.select_days(())
                read_parquet = pd.read_parquet

                def mutate_during_read(*args, **kwargs):
                    frame = read_parquet(*args, **kwargs)
                    panel.write_bytes(b"x" * quality["output_bytes"])
                    return frame

                with self.assertRaisesRegex(RuntimeError, "content changed"):
                    with patch("ddvc.data_release.pd.read_parquet", side_effect=mutate_during_read):
                        release.read_day("20250101")

    def test_released_v4_state_partitions_exclude_static_conflict_pool_identities(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "state-ledger.parquet"
            ledger.write_bytes(b"ledger")
            panel = root / "20250101.parquet"
            pd.DataFrame(
                [
                    {"day": "20250101", "pool": "usable", "usable": True},
                    {"day": "20250101", "pool": "conflict", "usable": True},
                    {"day": "20250101", "pool": "unusable", "usable": False},
                ]
            ).to_parquet(panel, index=False)
            marker = root / "20250101.quality.json"
            quality = {
                "family": "tick",
                "venue": "uniswap_v4",
                "day": "20250101",
                "input_fingerprint": "b" * 64,
                "canonical_rows": 3,
                "output_bytes": panel.stat().st_size,
                "output_sha256": file_sha256(panel),
                "passed": True,
                "scientific_support": True,
            }
            marker.write_text(json.dumps(quality), encoding="utf-8")
            quarantine = root / "v4-quarantine.parquet"
            pd.DataFrame(
                [
                    {
                        "pool": "conflict",
                        "swap_rows": 2,
                        "static_variants": 2,
                        "first_day": "20250101",
                        "last_day": "20250102",
                    }
                ]
            ).to_parquet(quarantine, index=False)
            ledger_frame = pd.DataFrame([quality, {**quality, "day": "20250102", "scientific_support": False}])
            ledger_frame.attrs["ledger_sha256"] = file_sha256(ledger)
            with (
                patch("ddvc.data_release.MARKET_STATE_QUALITY_PANEL", ledger),
                patch("ddvc.data_release.V4_STATIC_QUARANTINE_PANEL", quarantine),
                patch("ddvc.v4_quarantine.current_artifacts", return_value=nullcontext((quarantine,))),
                patch("ddvc.data_release.current_artifacts", return_value=nullcontext()),
                patch("ddvc.data_release._validated_release_ledger_unlocked", return_value=ledger_frame),
                patch("ddvc.data_release.state_partition_path", return_value=panel),
                patch("ddvc.data_release.state_quality_path", return_value=marker),
            ):
                release = released_state_partitions("tick", "uniswap_v4", ("day", "pool"))
                self.assertEqual(release.days, ("20250101",))
                frame = release.read_day("20250101")
                self.assertEqual(frame["pool"].tolist(), ["usable"])
                inclusive = released_state_partitions(
                    "tick",
                    "uniswap_v4",
                    ("pool",),
                    include_quarantined=True,
                ).read_day("20250101")
                self.assertEqual(inclusive["pool"].tolist(), ["usable", "conflict", "unusable"])
                marker.write_text(json.dumps({**quality, "passed": False}), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "marker changed"):
                    release.assert_current()

    def test_full_market_state_release_adds_event_certificate_after_prerelease(self) -> None:
        from unittest.mock import patch

        with (
            patch("ddvc.data_release.require_market_state_prerelease") as prerelease,
            patch("ddvc.data_release.require_v2_event_source_release") as event_source,
            patch("ddvc.data_release.require_v3_event_source_release") as v3_event_source,
        ):
            require_market_state_release()
        prerelease.assert_called_once_with()
        event_source.assert_called_once_with()
        v3_event_source.assert_called_once_with()

    def test_v2_event_release_gate_requires_current_artifacts_and_exact_calendar(self) -> None:
        from unittest.mock import patch

        summary = pd.DataFrame()
        exceptions = pd.DataFrame()
        certificate = {"status": "pass"}
        release = SimpleNamespace(
            artifact_paths=(Path("summary.parquet"), Path("exceptions.parquet"), Path("certificate.json")),
        )
        with (
            patch("ddvc.data_release.resolve_v2_event_source_release", return_value=release) as resolve,
            patch("ddvc.data_release.current_artifacts") as current,
            patch(
                "ddvc.data_release.read_v2_event_source_release",
                return_value=(summary, exceptions, certificate),
            ) as read,
            patch(
                "ddvc.data_release.transaction_frontier_audit_days",
                return_value=["20250115"],
            ),
            patch("ddvc.data_release.validate_v2_event_source_certificate") as validate,
            patch("ddvc.data_release.validate_v2_event_source_evidence_bundle") as validate_evidence,
        ):
            require_v2_event_source_release()
        resolve.assert_called_once_with()
        current.assert_called_once()
        read.assert_called_once_with(release)
        validate.assert_called_once_with(
            summary,
            exceptions,
            certificate,
            ["20250115"],
        )
        validate_evidence.assert_called_once_with(certificate, summary=summary)

    def test_v2_event_release_gate_wraps_legacy_flat_failure(self) -> None:
        from unittest.mock import patch

        with (
            patch(
                "ddvc.data_release.resolve_v2_event_source_release",
                side_effect=RuntimeError("legacy flat V2 event-source artifacts require regeneration"),
            ),
            self.assertRaisesRegex(RuntimeError, "node D V2-family event-source certificate failed.*legacy flat"),
        ):
            require_v2_event_source_release()

    def test_v3_event_release_gate_requires_current_artifacts_and_reopening(self) -> None:
        from unittest.mock import patch

        summary = pd.DataFrame()
        exceptions = pd.DataFrame()
        quarantine = pd.DataFrame()
        certificate = {"status": "pass"}
        release = SimpleNamespace(
            artifact_paths=(
                Path("summary.parquet"),
                Path("exceptions.parquet"),
                Path("quarantine.parquet"),
                Path("certificate.json"),
            ),
        )
        with (
            patch(
                "ddvc.data_release.resolve_v3_event_source_release",
                return_value=release,
            ) as resolve,
            patch("ddvc.data_release.current_artifacts") as current,
            patch(
                "ddvc.data_release.read_v3_event_source_release",
                return_value=(summary, exceptions, quarantine, certificate),
            ) as read,
            patch("ddvc.data_release.v3_audit_days", return_value=["20250115"]),
            patch("ddvc.data_release.validate_v3_event_source_certificate") as validate,
            patch(
                "ddvc.data_release.validate_v3_event_source_evidence_bundle"
            ) as validate_evidence,
        ):
            require_v3_event_source_release()
        resolve.assert_called_once_with()
        current.assert_called_once()
        read.assert_called_once_with(release)
        validate.assert_called_once_with(
            summary,
            exceptions,
            quarantine,
            certificate,
            ["20250115"],
        )
        validate_evidence.assert_called_once_with(
            certificate, summary=summary, quarantine=quarantine
        )

    def test_v3_event_release_gate_wraps_missing_release(self) -> None:
        from unittest.mock import patch

        with (
            patch(
                "ddvc.data_release.resolve_v3_event_source_release",
                side_effect=FileNotFoundError("missing current pointer"),
            ),
            self.assertRaisesRegex(
                RuntimeError,
                "node D V3 event-source certificate failed.*missing current pointer",
            ),
        ):
            require_v3_event_source_release()

    def test_v4_static_audit_returns_complete_pool_level_quarantine(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v4.parquet"
            pd.DataFrame(
                [
                    {
                        "pool": "stable",
                        "record_type": "swap",
                        "usable": True,
                        "quote_supported": True,
                        "token0_raw": "0xa",
                        "token1_raw": "0xb",
                        "decimals0": 18,
                        "decimals1": 6,
                        "fee_pips": 500,
                        "tick_spacing": 10,
                        "hooks": "0x0",
                        "day": "20250101",
                    },
                    {
                        "pool": "drift",
                        "record_type": "swap",
                        "usable": True,
                        "quote_supported": False,
                        "token0_raw": "0xa",
                        "token1_raw": "0xc",
                        "decimals0": 18,
                        "decimals1": 18,
                        "fee_pips": 3000,
                        "tick_spacing": 60,
                        "hooks": "0x0",
                        "day": "20250101",
                    },
                    {
                        "pool": "drift",
                        "record_type": "swap",
                        "usable": True,
                        "quote_supported": True,
                        "token0_raw": "0xa",
                        "token1_raw": "0xc",
                        "decimals0": 18,
                        "decimals1": 0,
                        "fee_pips": 3000,
                        "tick_spacing": 60,
                        "hooks": "0x0",
                        "day": "20250102",
                    },
                ]
            ).to_parquet(path, index=False)
            quarantine = audit_v4_pool_static_conflicts([path])
        self.assertEqual(quarantine["pool"].tolist(), ["drift"])
        self.assertEqual(int(quarantine.iloc[0]["static_variants"]), 2)
        self.assertEqual(int(quarantine.iloc[0]["swap_rows"]), 2)

    def test_cross_venue_order_audit_rejects_one_block_log_claimed_twice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for venue, tx_hash in (("uniswap_v3", "0xv3"), ("uniswap_v4", "0xv4")):
                path = root / f"{venue}.parquet"
                pd.DataFrame(
                    [{
                        "venue": venue,
                        "tx_hash": tx_hash,
                        "block_number": 100,
                        "log_index": 7,
                        "usable": True,
                    }]
                ).to_parquet(path, index=False)
                paths[venue] = [path]
            count, samples = audit_cross_venue_order_conflicts(paths)
        self.assertEqual(count, 1)
        self.assertEqual(samples[0]["venues"], ["uniswap_v3", "uniswap_v4"])

    def test_cross_venue_order_audit_ignores_quarantined_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for venue, usable in (("uniswap_v3", True), ("uniswap_v4", False)):
                path = root / f"{venue}.parquet"
                pd.DataFrame(
                    [{
                        "venue": venue,
                        "tx_hash": venue,
                        "block_number": 100,
                        "log_index": 7,
                        "usable": usable,
                    }]
                ).to_parquet(path, index=False)
                paths[venue] = [path]
            count, samples = audit_cross_venue_order_conflicts(paths)
        self.assertEqual((count, samples), (0, []))

    def test_exact_key_gate_accepts_only_the_complete_perimeter(self) -> None:
        expected = [("family", "venue", "20250101"), ("family", "venue", "20250102")]
        _exact_key_gate(label="test", actual=reversed(expected), expected=expected)
        with self.assertRaisesRegex(RuntimeError, "missing=.*20250102"):
            _exact_key_gate(label="test", actual=expected[:1], expected=expected)

    def test_analysis_panel_builders_call_the_shared_release_gate(self) -> None:
        expected = {
            "scripts/build_intermediation_by_type.py": "released_route_partitions(",
            "scripts/build_cross_venue_routing_series.py": "released_route_partitions(",
            "scripts/build_vehicle_excess_use.py": "released_route_partitions(",
            "scripts/build_vehicle_swap_style.py": "released_route_partitions(",
            "scripts/build_vehicle_centrality.py": "released_route_partitions(",
            "scripts/build_ethereum_day_calendar.py": "require_node_d_release(routes=True)",
            "scripts/process/build_route_gas_units.py": "released_route_partitions(",
            "scripts/process/build_route_transaction_gas.py": "require_node_d_release(routes=True, market_state=True)",
            "scripts/run_route_cost_panel.py": "require_node_d_release(routes=True, market_state=True)",
            "scripts/build_transaction_state_frontier.py": "require_node_d_release(routes=True)",
            "scripts/build_routing_maturation_panel.py": "require_node_d_release(routes=True, market_state=True)",
            "scripts/build_counterfactual_dominance.py": "require_node_d_release(routes=True, market_state=True)",
            "scripts/build_rent_incidence_panel.py": "cp_event_stream(",
            "scripts/build_v2_token_panel.py": "released_state_partitions(",
            "scripts/build_pool_capital_panel.py": "cp_state_stream(",
        }
        for filename, call in expected.items():
            with self.subTest(filename=filename):
                self.assertIn(call, Path(filename).read_text(encoding="utf-8"))

    def test_intermediation_panel_binds_the_exact_route_release(self) -> None:
        source = Path("scripts/build_intermediation_by_type.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("days = list(route_release.paths)", source)
        self.assertIn("inputs=list(route_release.provenance_anchors)", source)
        self.assertIn(
            "preinstall_validator=release_preinstall_validator(route_release)",
            source,
        )
        self.assertNotIn("inputs=[UNIFIED]", source)

    def test_route_only_d3_builders_use_portable_exact_release_bindings(self) -> None:
        filenames = [
            "scripts/build_intermediation_by_type.py",
            "scripts/build_cross_venue_routing_series.py",
            "scripts/build_vehicle_excess_use.py",
            "scripts/build_vehicle_swap_style.py",
            "scripts/build_vehicle_centrality.py",
            "scripts/process/build_route_gas_units.py",
        ]
        for filename in filenames:
            with self.subTest(filename=filename):
                source = Path(filename).read_text(encoding="utf-8")
                self.assertIn("released_route_partitions(", source)
                self.assertIn("provenance_anchors", source)
                self.assertIn("release_preinstall_validator(route_release)", source)
                self.assertNotIn("inputs=[UNIFIED]", source)

    def test_market_state_consumers_take_days_from_the_release_ledger(self) -> None:
        filenames = [
            "scripts/build_counterfactual_dominance.py",
            "scripts/validate_curve_quoter.py",
            "scripts/validate_weighted_quoter.py",
            "scripts/build_lp_liquidity_flow_panel.py",
            "scripts/build_v2_token_panel.py",
            "scripts/test_block_vs_hour_verdict.py",
            "scripts/audit_findings_freeze.py",
        ]
        for filename in filenames:
            with self.subTest(filename=filename):
                source = Path(filename).read_text(encoding="utf-8")
                self.assertIn("released_state_partitions", source)
                self.assertIn(".read_day(", source)
                self.assertNotIn("available_state_days", source)
                self.assertNotIn("released_state_days", source)
                self.assertNotIn("read_cp_partition", source)
                self.assertNotIn("read_tick_partition", source)
                self.assertNotIn("read_multi_asset_partition", source)
                self.assertNotRegex(source, r"MARKET_STATE.*\.glob\(")
        rent_source = Path("scripts/build_rent_incidence_panel.py").read_text(encoding="utf-8")
        self.assertIn('selected_capital.manifest["certified_reserve_stream"]', rent_source)
        self.assertIn("cp_event_stream(", rent_source)
        self.assertIn("release.read_day(day)", rent_source)
        self.assertNotIn("released_state_partitions", rent_source)

    def test_release_bound_publishers_validate_again_immediately_before_install(self) -> None:
        filenames = [
            "scripts/test_block_vs_hour_verdict.py",
            "scripts/validate_curve_quoter.py",
            "scripts/validate_weighted_quoter.py",
            "scripts/build_counterfactual_dominance.py",
        ]
        for filename in filenames:
            with self.subTest(filename=filename):
                source = Path(filename).read_text(encoding="utf-8")
                self.assertIn("release_preinstall_validator(", source)
                self.assertIn("preinstall_validator=", source)
        rent_source = Path("scripts/build_rent_incidence_panel.py").read_text(encoding="utf-8")
        self.assertIn("state_release.assert_current()", rent_source)
        self.assertIn("preinstall_validator=validate_sources", rent_source)

    def test_v3_materiality_reads_only_released_route_partitions(self) -> None:
        source = Path("src/ddvc/v3_graph_materiality.py").read_text(encoding="utf-8")
        self.assertIn("route_release.read_day(day)", source)
        self.assertNotRegex(source, r"unified.*\.parquet")
        self.assertNotIn(".glob(", source)

    def test_retired_daily_gas_pipeline_is_absent(self) -> None:
        self.assertFalse(Path("scripts/process/fetch_daily_gas_price_graph.py").exists())
        self.assertFalse(Path("tests/test_gas_price_fetch.py").exists())
        self.assertNotIn(
            "load_daily_gas_prices",
            Path("src/ddvc/gas.py").read_text(encoding="utf-8"),
        )
        for contract in (
            Path("docs/specification-lock.json"),
            Path("scripts/refresh_panel_dependents.py"),
        ):
            self.assertNotIn(
                "daily_gas_price_graph.parquet",
                contract.read_text(encoding="utf-8"),
            )

    def test_withdrawn_daily_gas_arbitrage_bound_fails_closed(self) -> None:
        from scripts import test_gap_arbitrage_bound

        with self.assertRaisesRegex(RuntimeError, "exact transaction/block gas"):
            test_gap_arbitrage_bound.main()

    def test_withdrawn_fixed_clock_dominance_windows_fail_closed(self) -> None:
        from scripts import measure_dominance_windows

        with self.assertRaisesRegex(RuntimeError, "exact-clock all-in replacement"):
            measure_dominance_windows.main()

    def test_withdrawn_fixed_gas_rent_incidence_fails_closed(self) -> None:
        from scripts import run_rent_incidence

        with self.assertRaisesRegex(RuntimeError, "receipt-measured LP-operation gas"):
            run_rent_incidence.main()

    def test_release_orchestration_does_not_invalidate_analysis_results(self) -> None:
        filenames = [
            "scripts/build_intermediation_by_type.py",
            "scripts/build_cross_venue_routing_series.py",
            "scripts/build_vehicle_excess_use.py",
            "scripts/build_vehicle_swap_style.py",
            "scripts/build_vehicle_centrality.py",
            "scripts/build_ethereum_day_calendar.py",
            "scripts/build_counterfactual_dominance.py",
            "scripts/build_transaction_state_frontier.py",
            "scripts/build_routing_maturation_panel.py",
            "scripts/build_v2_token_panel.py",
            "scripts/build_rent_incidence_panel.py",
            "scripts/run_rent_incidence.py",
            "scripts/process/build_route_gas_units.py",
            "scripts/process/build_route_transaction_gas.py",
        ]
        for filename in filenames:
            with self.subTest(filename=filename):
                source = Path(filename).read_text(encoding="utf-8")
                self.assertNotIn('"src/ddvc/data_release.py"', source)

    def test_mixed_construction_and_analysis_runners_have_panel_only_mode(self) -> None:
        filenames = [
            "scripts/build_intermediation_by_type.py",
            "scripts/build_cross_venue_routing_series.py",
            "scripts/build_vehicle_excess_use.py",
            "scripts/build_vehicle_swap_style.py",
            "scripts/build_vehicle_centrality.py",
            "scripts/build_counterfactual_dominance.py",
            "scripts/process/build_route_gas_units.py",
        ]
        for filename in filenames:
            with self.subTest(filename=filename):
                source = Path(filename).read_text(encoding="utf-8")
                self.assertIn('"--panel-only"', source)
                self.assertIn("if args.panel_only:", source)

    def test_bounded_diagnostics_cannot_replace_canonical_panels(self) -> None:
        filenames = [
            "scripts/build_intermediation_by_type.py",
            "scripts/build_cross_venue_routing_series.py",
            "scripts/build_vehicle_excess_use.py",
            "scripts/build_v2_token_panel.py",
            "scripts/build_counterfactual_dominance.py",
        ]
        for filename in filenames:
            with self.subTest(filename=filename):
                source = Path(filename).read_text(encoding="utf-8")
                self.assertIn("canonical outputs unchanged", source)

    def test_dependent_consumers_require_current_analysis_inputs(self) -> None:
        filenames = [
            "scripts/build_transaction_state_frontier.py",
            "scripts/build_routing_maturation_panel.py",
            "scripts/build_counterfactual_dominance.py",
        ]
        for filename in filenames:
            with self.subTest(filename=filename):
                source = Path(filename).read_text(encoding="utf-8")
                self.assertTrue(
                    "current_artifacts(" in source
                    or "require_current_artifacts(" in source
                )


if __name__ == "__main__":
    unittest.main()
