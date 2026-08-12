from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from scripts.certify_raw_generation import (
    acquire_references,
    finalize_evidence,
    prepare_evidence,
    publish_local_scan,
    selected_required_partitions,
)
from ddvc.artifact_release import canonical_json_sha256, file_sha256
from ddvc.fetch import dune
from ddvc.fetch.raw import (
    RawFetchInvariantError,
    graph_query_contract_sha256,
    verified_source_day_rows,
)
from ddvc.fetch.schemas import get_schema
from ddvc.fetch.sources import DEX_SOURCES, get_source
from ddvc.provenance import portable_content_sha256
from ddvc.raw_certification import (
    ADJUDICATION_ARTIFACT_POLICY,
    ADJUDICATION_EVIDENCE_POLICY,
    COMPARISON_ENGINE_CONTRACT,
    FIELD_CONTRACTS,
    FETCH_CODE_ARTIFACT_POLICY,
    GENERATION_EVIDENCE_POLICY,
    QUERY_ARTIFACT_POLICY,
    RETRO_CERTIFICATION_POLICY,
    SELECTION_FRAME_POLICY,
    FieldContract,
    RawPartition,
    active_consumer_streams,
    comparison_contract,
    comparison_contract_identity,
    contract_identity,
    generation_identity,
    _validate_generation_against_local,
    required_partitions,
    raw_partition_generation_identity,
    scan_installed_generation,
    load_certified_partition_ledger,
    verify_retro_certificate,
    write_local_scan_certificate,
    write_normalized_legacy_ledger,
    write_retro_certificate,
)


DAY = "20240101"


def graph_contract_sha256(source: str, stream: str) -> str:
    source_record = get_source(source)
    entity = next(
        entity
        for entity in get_schema(source_record.schema).entities
        if entity.stream == stream
    )
    return graph_query_contract_sha256(entity)


def write_gzip(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as handle:
            for row in rows:
                handle.write(
                    (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
                )


def v3_swap(identity: str, timestamp: int = 1_704_067_300) -> dict[str, object]:
    return {
        "id": identity,
        "transaction": {
            "id": f"tx-{identity}",
            "blockNumber": "18900000",
            "timestamp": str(timestamp),
        },
        "timestamp": str(timestamp),
        "pool": {
            "id": "pool",
            "feeTier": "3000",
            "token0": {"id": "token0", "symbol": "T0", "decimals": "18"},
            "token1": {"id": "token1", "symbol": "T1", "decimals": "6"},
        },
        "amount0": "1",
        "amount1": "-2",
        "amountUSD": "2",
        "sqrtPriceX96": "3",
        "tick": "4",
        "logIndex": "5",
    }


def fluid_swap(timestamp: str = "2024-01-01 00:00:01.000 UTC") -> dict[str, object]:
    return {
        "tx_hash": "0xabc",
        "evt_index": 1,
        "block_number": 18_900_000,
        "block_time": timestamp,
        "token_sold_address": "token0",
        "token_sold_symbol": "T0",
        "token_sold_amount": 1,
        "token_bought_address": "token1",
        "token_bought_symbol": "T1",
        "token_bought_amount": 2,
        "amount_usd": 2,
        "pool": "pool",
    }


class RawCertificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.work = self.root / "work"
        self.perimeter = RawPartition("uniswap_v3", "swaps", DAY)
        self.perimeter_patch = patch(
            "ddvc.raw_certification.required_partitions",
            return_value=(self.perimeter,),
        )
        self.perimeter_patch.start()

    def tearDown(self) -> None:
        self.perimeter_patch.stop()
        self.temporary.cleanup()

    def path(self, partition: RawPartition) -> Path:
        backend = "dune" if partition.source == "fluid" else "thegraph"
        return (
            self.data
            / "raw"
            / backend
            / partition.source
            / f"{partition.source}_{partition.stream}_{partition.day}.jsonl.gz"
        )

    def test_local_scan_subset_is_exact_and_rejects_inactive_pairs(self) -> None:
        selected = selected_required_partitions(
            ["uniswap_v3"], ["swaps", "mints", "burns"]
        )
        self.assertEqual(
            {(partition.source, partition.stream) for partition in selected},
            {
                ("uniswap_v3", "swaps"),
                ("uniswap_v3", "mints"),
                ("uniswap_v3", "burns"),
            },
        )
        self.assertEqual(len(selected), 1884 * 3)
        with self.assertRaisesRegex(ValueError, "does not expose"):
            selected_required_partitions(["uniswap_v3"], ["joins_exits"])
        with self.assertRaisesRegex(ValueError, "requires"):
            selected_required_partitions(None, ["swaps"])

    def meta_path(self, partition: RawPartition) -> Path:
        return self.path(partition).with_name(
            f"{partition.source}_meta_{partition.day}.json"
        )

    def scan(self, partition: RawPartition) -> dict[str, object]:
        return scan_installed_generation(
            self.data, self.work, workers=1, partitions=[partition]
        )[0]

    def fresh_local_partitions(self) -> tuple[list[RawPartition], list[dict[str, object]]]:
        partitions: list[RawPartition] = []
        local: list[dict[str, object]] = []
        activity = [1, 3, 2, 5, 1, 4]
        for offset, rows in enumerate(activity):
            date = dt.date(2024, 1, 1) + dt.timedelta(days=offset)
            day = date.strftime("%Y%m%d")
            timestamp = int(
                dt.datetime.combine(
                    date,
                    dt.time(hour=12),
                    tzinfo=dt.timezone.utc,
                ).timestamp()
            )
            partition = RawPartition("uniswap_v3", "swaps", day)
            write_gzip(
                self.path(partition),
                [v3_swap(f"{day}-{index}", timestamp) for index in range(rows)],
            )
            partitions.append(partition)
            local.append(self.scan(partition))
        return partitions, local

    def evidence_bundle(
        self,
        source: str,
        stream: str,
        *,
        kind: str = "legacy_unfrozen_graph",
        query_hash: str = "2" * 64,
        adjudication_kind: str = "independent_event_certificate",
        local_partitions: list[dict[str, object]] | None = None,
    ) -> tuple[Path, Path]:
        generation = {
            "source": source,
            "stream": stream,
            "generation_kind": kind,
        }
        if kind == "legacy_unfrozen_graph":
            generation.update(
                {
                    "provenance_status": "legacy_graph_code_or_query_unavailable",
                    "fetch_code_identity_sha256": None,
                    "query_generation_identity_sha256": None,
                }
            )
        else:
            repository = Path(__file__).resolve().parents[1]
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            code_paths = [
                "scripts/fetch_raw_market_data.py",
                "src/ddvc/fetch/graph.py",
                "src/ddvc/fetch/raw.py",
            ]
            fetch_artifact_payload = {
                "policy": FETCH_CODE_ARTIFACT_POLICY,
                "source": source,
                "stream": stream,
                "repository_commit_sha": commit,
                "tracked_blobs": [
                    {
                        "path": code_path,
                        "blob_sha256": hashlib.sha256(
                            subprocess.run(
                                ["git", "show", f"{commit}:{code_path}"],
                                cwd=repository,
                                check=True,
                                capture_output=True,
                            ).stdout
                        ).hexdigest(),
                    }
                    for code_path in sorted(code_paths)
                ],
            }
            fetch_artifact = self.root / "fetch-code.json"
            fetch_artifact.write_text(json.dumps(fetch_artifact_payload, sort_keys=True))
            query_contract = {
                "backend": "thegraph",
                "source": source,
                "stream": stream,
                "recorded_query_contracts": [graph_contract_sha256(source, stream)],
                "sample_days": [DAY],
            }
            query_artifact_payload = {
                "policy": QUERY_ARTIFACT_POLICY,
                "source": source,
                "stream": stream,
                "endpoint_family": "thegraph",
                "entity": stream,
                "selected_fields": sorted(
                    FIELD_CONTRACTS[(source, stream)].required_paths
                ),
                "bounds": {
                    "field": "timestamp",
                    "lower": "inclusive_utc_day",
                    "upper": "exclusive_utc_day",
                },
                "pagination": {
                    "chunk_policy": "hour_range_v1",
                    "direction": "ascending",
                    "order_field": "id",
                    "page_size": 1000,
                },
                "query_contract": query_contract,
            }
            query_artifact = self.root / "query.json"
            query_artifact.write_text(json.dumps(query_artifact_payload, sort_keys=True))
            generation.update(
                {
                    "provenance_status": "available",
                    "fetch_code_artifact": fetch_artifact.name,
                    "fetch_code_artifact_sha256": file_sha256(fetch_artifact),
                    "fetch_code_identity_sha256": canonical_json_sha256(
                        fetch_artifact_payload
                    ),
                    "query_artifact": query_artifact.name,
                    "query_artifact_sha256": file_sha256(query_artifact),
                    "query_generation_identity_sha256": canonical_json_sha256(
                        query_contract
                    ),
                }
            )
        generation["generation_identity_sha256"] = generation_identity(generation)
        generation_path = self.root / "generation.json"
        generation_path.write_text(
            json.dumps(
                {
                    "policy": GENERATION_EVIDENCE_POLICY,
                    "generations": [generation],
                },
                sort_keys=True,
            )
        )
        comparison = {
            "policy": ADJUDICATION_ARTIFACT_POLICY,
            "kind": adjudication_kind,
            "source": source,
            "stream": stream,
            "generation_identity_sha256": generation["generation_identity_sha256"],
            "status": "passed",
            "zero_exceptions": True,
            "sample_days": [DAY],
            "compared_rows": 10,
            "missing_rows": 0,
            "extra_rows": 0,
            "duplicate_rows": 0,
            "quantity_mismatch_rows": 0,
        }
        if adjudication_kind == "independent_event_certificate":
            comparison["identity_fields"] = [
                "block_number",
                "log_index",
                "transaction_hash",
            ]
        else:
            assert local_partitions is not None
            population = [
                {
                    "day": item["day"],
                    "activity_rows": item["rows"],
                    "logical_content_sha256": item["logical_content_sha256"],
                }
                for item in sorted(local_partitions, key=lambda item: item["day"])
            ]
            days = [str(candidate["day"]) for candidate in population]
            first = len(days) // 3
            second = 2 * len(days) // 3
            windows = {
                "early": days[:first],
                "middle": days[first:second],
                "late": days[second:],
            }
            activity = {
                str(candidate["day"]): int(candidate["activity_rows"])
                for candidate in population
            }
            strata = {}
            for name, candidates in windows.items():
                strata[f"{name}_quiet"] = min(
                    candidates, key=lambda day: (activity[day], day)
                )
                strata[f"{name}_busy"] = max(
                    candidates, key=lambda day: (activity[day], day)
                )
            selection_frame = {
                "policy": SELECTION_FRAME_POLICY,
                "activity_metric": "legacy_rows",
                "tie_rule": "quiet=min(activity_rows,day);busy=max(activity_rows,day)",
                "candidate_start": days[0],
                "candidate_end": days[-1],
                "window_boundaries": {
                    name: {"start": candidates[0], "end": candidates[-1]}
                    for name, candidates in windows.items()
                },
                "candidate_population": population,
                "candidate_population_sha256": canonical_json_sha256(population),
            }
            comparison.update(
                {
                    "sample_days": sorted(strata.values()),
                    "strata": strata,
                    "selection_frame": selection_frame,
                }
            )
        field_contract = comparison_contract(source, stream)
        identity_fields = list(field_contract.identity_fields)
        quantity_fields = list(field_contract.quantity_fields)
        ledger_rows = [
            {
                "day": day,
                "identity": {field: f"identity-{index}-{field}" for field in identity_fields},
                "quantities": {field: f"quantity-{index}-{field}" for field in quantity_fields},
            }
            for index, day in enumerate(comparison["sample_days"])
        ]
        legacy_ledger = self.root / "legacy-comparison.jsonl"
        reference_ledger = self.root / "reference-comparison.jsonl"
        ledger_text = "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in ledger_rows
        )
        legacy_ledger.write_text(ledger_text)
        reference_ledger.write_text(ledger_text)
        provider_response = self.root / "provider-response.bin"
        provider_response.write_bytes(b"fresh-independent-test-source")
        provider_metadata = []
        for day in comparison["sample_days"]:
            metadata = self.root / f"provider-meta-{day}.json"
            metadata.write_text(
                json.dumps(
                    {
                        "source": source,
                        "day": f"{day[:4]}-{day[4:6]}-{day[6:]}",
                        "streams": {
                            stream: {
                                "query_contract_sha256": graph_contract_sha256(
                                    source, stream
                                )
                            }
                        },
                    },
                    sort_keys=True,
                )
            )
            provider_metadata.append(metadata)
        repository = Path(__file__).resolve().parents[1]
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        owner_paths = [
            "scripts/fetch_raw_market_data.py",
            "src/ddvc/fetch/graph.py",
            "src/ddvc/fetch/raw.py",
        ]
        code_payload = {
            "policy": FETCH_CODE_ARTIFACT_POLICY,
            "source": source,
            "stream": stream,
            "repository_commit_sha": commit,
            "tracked_blobs": [
                {
                    "path": path,
                    "blob_sha256": hashlib.sha256(
                        subprocess.run(
                            ["git", "show", f"{commit}:{path}"],
                            cwd=repository,
                            check=True,
                            capture_output=True,
                        ).stdout
                    ).hexdigest(),
                }
                for path in sorted(owner_paths)
            ],
        }
        reference_code = self.root / "reference-code.json"
        reference_code.write_text(json.dumps(code_payload, sort_keys=True))
        raw_contract = FIELD_CONTRACTS[(source, stream)]
        query_contract = {
            "backend": "thegraph",
            "source": source,
            "stream": stream,
            "recorded_query_contracts": [graph_contract_sha256(source, stream)],
            "sample_days": comparison["sample_days"],
        }
        query_payload = {
            "policy": QUERY_ARTIFACT_POLICY,
            "source": source,
            "stream": stream,
            "endpoint_family": "thegraph",
            "entity": stream,
            "selected_fields": sorted(
                set(raw_contract.required_paths).union(
                    *(set(group) for group in raw_contract.required_any_paths)
                )
            ),
            "bounds": {
                "field": raw_contract.timestamp_path,
                "lower": "inclusive_utc_day",
                "upper": "exclusive_utc_day",
            },
            "pagination": {
                "chunk_policy": "hour_range_v1",
                "direction": "ascending",
                "order_field": raw_contract.identity_path,
                "page_size": 1000,
            },
            "query_contract": query_contract,
        }
        reference_query = self.root / "reference-query.json"
        reference_query.write_text(json.dumps(query_payload, sort_keys=True))
        reference_evidence = self.root / "reference-evidence.json"
        reference_evidence.write_text(
            json.dumps(
                {
                    "policy": "fresh-reference-provider-evidence-v1",
                    "source": source,
                    "stream": stream,
                    "backend": "thegraph",
                    "sample_days": comparison["sample_days"],
                    "comparison_contract_sha256": comparison_contract_identity(
                        source, stream
                    ),
                    "raw_artifacts": [
                        {
                            "path": provider_response.name,
                            "sha256": file_sha256(provider_response),
                        },
                        *[
                            {
                                "path": metadata.name,
                                "sha256": file_sha256(metadata),
                            }
                            for metadata in provider_metadata
                        ],
                    ],
                    "reference_ledger": reference_ledger.name,
                    "reference_ledger_sha256": file_sha256(reference_ledger),
                    "fetch_code_artifact": reference_code.name,
                    "fetch_code_artifact_sha256": file_sha256(reference_code),
                    "query_artifact": reference_query.name,
                    "query_artifact_sha256": file_sha256(reference_query),
                    "query_generation_identity_sha256": canonical_json_sha256(
                        query_contract
                    ),
                },
                sort_keys=True,
            )
        )
        comparison.update(
            {
                "comparison_engine_identity_sha256": canonical_json_sha256(
                    COMPARISON_ENGINE_CONTRACT
                ),
                "identity_fields": identity_fields,
                "quantity_fields": quantity_fields,
                "comparison_contract_sha256": comparison_contract_identity(
                    source, stream
                ),
                "legacy_ledger": legacy_ledger.name,
                "legacy_ledger_sha256": file_sha256(legacy_ledger),
                "reference_ledger": reference_ledger.name,
                "reference_ledger_sha256": file_sha256(reference_ledger),
                "reference_evidence": reference_evidence.name,
                "reference_evidence_sha256": file_sha256(reference_evidence),
                "compared_rows": len(ledger_rows),
            }
        )
        artifact = self.root / "comparison.json"
        artifact.write_text(json.dumps(comparison, sort_keys=True) + "\n")
        adjudication_path = self.root / "adjudication.json"
        adjudication_path.write_text(
            json.dumps(
                {
                    "policy": ADJUDICATION_EVIDENCE_POLICY,
                    "evidence": [
                        {
                            "source": source,
                            "stream": stream,
                            "kind": adjudication_kind,
                            "generation_identity_sha256": generation[
                                "generation_identity_sha256"
                            ],
                            "artifact": artifact.name,
                            "artifact_sha256": hashlib.sha256(
                                artifact.read_bytes()
                            ).hexdigest(),
                            "status": "passed",
                            "zero_exceptions": True,
                            "sample_days": comparison["sample_days"],
                            "compared_rows": comparison["compared_rows"],
                            "missing_rows": 0,
                            "extra_rows": 0,
                            "duplicate_rows": 0,
                            "quantity_mismatch_rows": 0,
                            "comparison_engine_identity_sha256": comparison[
                                "comparison_engine_identity_sha256"
                            ],
                            "legacy_ledger": comparison["legacy_ledger"],
                            "legacy_ledger_sha256": comparison[
                                "legacy_ledger_sha256"
                            ],
                            "reference_ledger": comparison["reference_ledger"],
                            "reference_ledger_sha256": comparison[
                                "reference_ledger_sha256"
                            ],
                            "identity_fields": comparison["identity_fields"],
                            "quantity_fields": comparison["quantity_fields"],
                            "comparison_contract_sha256": comparison[
                                "comparison_contract_sha256"
                            ],
                            "reference_evidence": comparison["reference_evidence"],
                            "reference_evidence_sha256": comparison[
                                "reference_evidence_sha256"
                            ],
                            **(
                                {}
                                if adjudication_kind == "independent_event_certificate"
                                else {
                                    "strata": comparison["strata"],
                                    "selection_frame": comparison["selection_frame"],
                                }
                            ),
                        }
                    ],
                },
                sort_keys=True,
            )
        )
        return generation_path, adjudication_path

    def test_active_consumer_perimeter_is_exactly_43120_stream_days(self) -> None:
        required = {
            source: sorted(streams)
            for source, streams in active_consumer_streams().items()
        }
        self.assertNotIn("uniswap_v1", required)
        self.assertEqual(required["fluid"], ["swaps"])
        self.assertEqual(
            required["sushiswap_v2"],
            ["burns", "daily", "hourly_reserves", "mints", "swaps"],
        )
        self.assertEqual(len(required_partitions()), 43_120)

    def test_dune_reference_pagination_and_retry_bounds_fail_closed(self) -> None:
        completed = (200, {"state": "QUERY_STATE_COMPLETED"})
        throttled = (429, {})
        with (
            patch.object(dune, "_call", side_effect=[completed, throttled, throttled]),
            patch.object(dune.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "retry bound"):
                dune._await_rows("execution", max_polls=1, max_page_retries=1)
        full_page = (200, {"result": {"rows": [{}] * 1000}})
        with patch.object(dune, "_call", side_effect=[completed, full_page]):
            with self.assertRaisesRegex(RuntimeError, "exceeded 1 pages"):
                dune._await_rows("execution", max_polls=1, max_result_pages=1)

    def test_dune_output_root_is_explicit_and_isolated(self) -> None:
        isolated = self.root / "reference"
        path = dune.dune_path(
            "fluid", "swaps", dt.date(2024, 1, 1), data_root=isolated
        )
        self.assertTrue(path.is_relative_to(isolated))
        self.assertFalse(path.is_relative_to(self.data))

    def test_retro_certificate_rejects_a_partial_partition_perimeter(self) -> None:
        first = self.perimeter
        second = RawPartition("uniswap_v3", "swaps", "20240102")
        with patch(
            "ddvc.raw_certification.required_partitions",
            return_value=(first, second),
        ):
            with self.assertRaisesRegex(ValueError, "partition perimeter mismatch"):
                write_retro_certificate(
                    self.root / "certificate.json",
                    [
                        {
                            "source": first.source,
                            "stream": first.stream,
                            "day": first.day,
                        }
                    ],
                    generation_evidence=self.root / "generation.json",
                    adjudication_evidence=self.root / "adjudication.json",
                )

    def test_certificate_requires_evidence_for_every_active_source_stream(self) -> None:
        daily = RawPartition("uniswap_v3", "daily", DAY)
        swap = self.perimeter
        generation, adjudication = self.evidence_bundle(swap.source, swap.stream)
        local = [
            {
                "source": partition.source,
                "stream": partition.stream,
                "day": partition.day,
                "contract_sha256": contract_identity(
                    partition.source, partition.stream
                ),
                "local_pass": True,
                "errors": [],
            }
            for partition in (daily, swap)
        ]
        with patch(
            "ddvc.raw_certification.required_partitions",
            return_value=(daily, swap),
        ):
            certificate = write_retro_certificate(
                self.root / "certificate.json",
                local,
                generation_evidence=generation,
                adjudication_evidence=adjudication,
            )
        self.assertEqual(certificate["status"], "incomplete")
        self.assertEqual(
            certificate["missing_generation_evidence"], ["uniswap_v3/daily"]
        )
        self.assertEqual(
            certificate["missing_adjudication_evidence"], ["uniswap_v3/daily"]
        )

    def test_graph_scan_binds_content_count_contract_order_and_day(self) -> None:
        partition = RawPartition("uniswap_v3", "swaps", DAY)
        rows = [v3_swap("a"), v3_swap("b", 1_704_153_500)]
        write_gzip(self.path(partition), rows)
        meta = {
            "source": partition.source,
            "day": "2024-01-01",
            "head_block_at_fetch": 25_000_000,
            "streams": {
                partition.stream: {
                    "rows": 2,
                    "query_contract_sha256": "9" * 64,
                }
            },
        }
        self.meta_path(partition).write_text(json.dumps(meta))
        observed = self.scan(partition)
        expected = hashlib.sha256(gzip.open(self.path(partition), "rb").read()).hexdigest()
        self.assertTrue(observed["local_pass"])
        self.assertEqual(observed["logical_content_sha256"], expected)
        self.assertEqual(observed["rows"], 2)
        self.assertEqual(observed["recorded_rows"], 2)
        self.assertEqual(observed["first_pagination_identity"], "a")
        self.assertEqual(observed["last_pagination_identity"], "b")
        self.assertEqual(observed["observed_query_contract_sha256"], "9" * 64)

    def test_local_scan_certificate_binds_content_contract_perimeter_and_file_generation(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        observed = self.scan(partition)
        output = (
            self.data
            / "processed"
            / "raw_generation"
            / "uniswap_v3_local_certificate.json"
        )
        certificate = write_local_scan_certificate(
            output,
            [observed],
            expected_partitions=[partition],
        )
        rows, binding = load_certified_partition_ledger(
            output,
            data_root=self.data,
            partitions=[partition],
        )
        self.assertEqual(rows, [observed])
        self.assertEqual(binding["certificate_sha256"], certificate["certificate_sha256"])
        self.assertEqual(binding["selected_partition_count"], 1)
        rows[0]["logical_content_sha256"] = "mutated"
        rows[0]["errors"].append("caller mutation")
        fresh_rows, _fresh_binding = load_certified_partition_ledger(
            output,
            data_root=self.data,
            partitions=[partition],
        )
        self.assertEqual(fresh_rows, [observed])
        identity = raw_partition_generation_identity(
            "uniswap_v3", "swaps", DAY, data_root=self.data
        )
        self.assertEqual(len(identity), 64)
        self.meta_path(partition).write_text(
            json.dumps(
                {
                    "source": "uniswap_v3",
                    "day": "2024-01-01",
                    "streams": {
                        "swaps": {
                            "logical_content_sha256": observed[
                                "logical_content_sha256"
                            ]
                        }
                    },
                    "promotion": {
                        "policy": "raw-source-day-promotion-v1",
                        "promotion_id": "corrupt",
                    },
                }
            )
        )
        with self.assertRaisesRegex(
            RawFetchInvariantError, "promotion identity"
        ):
            raw_partition_generation_identity(
                "uniswap_v3", "swaps", DAY, data_root=self.data
            )
        self.meta_path(partition).unlink()
        original = self.path(partition).stat()
        write_gzip(self.path(partition), [v3_swap("b")])
        os.utime(
            self.path(partition),
            ns=(original.st_atime_ns, original.st_mtime_ns),
        )
        with self.assertRaisesRegex(ValueError, "changed after scan"):
            load_certified_partition_ledger(output, data_root=self.data)

    def test_verified_local_partition_reader_streams_once_and_binds_exact_authority(self) -> None:
        partition = self.perimeter
        expected_rows = [v3_swap("a"), v3_swap("b")]
        write_gzip(self.path(partition), expected_rows)
        observed = self.scan(partition)
        certificate = self.data / "processed" / "raw_generation" / "uniswap_v3_local_certificate.json"
        write_local_scan_certificate(
            certificate,
            [observed],
            expected_partitions=[partition],
        )
        identity = raw_partition_generation_identity(
            partition.source,
            partition.stream,
            partition.day,
            data_root=self.data,
        )
        with patch("ddvc.fetch.raw.gzip.open", wraps=gzip.open) as gzip_open:
            with verified_source_day_rows(
                partition.source,
                partition.stream,
                dt.datetime.strptime(partition.day, "%Y%m%d").date(),
                data_root=self.data,
                expected_generation_identity=identity,
            ) as rows:
                self.assertEqual(list(rows), expected_rows)
        self.assertEqual(gzip_open.call_count, 1)
        with self.assertRaisesRegex(
            RawFetchInvariantError, "authority changed before read"
        ):
            with verified_source_day_rows(
                partition.source,
                partition.stream,
                dt.datetime.strptime(partition.day, "%Y%m%d").date(),
                data_root=self.data,
                expected_generation_identity="0" * 64,
            ):
                pass

    def test_verified_local_partition_reader_rejects_early_exit_and_mutation(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a"), v3_swap("b")])
        observed = self.scan(partition)
        certificate = self.data / "processed" / "raw_generation" / "uniswap_v3_local_certificate.json"
        write_local_scan_certificate(
            certificate,
            [observed],
            expected_partitions=[partition],
        )
        with self.assertRaisesRegex(RawFetchInvariantError, "was not exhausted"):
            with verified_source_day_rows(
                partition.source,
                partition.stream,
                dt.datetime.strptime(partition.day, "%Y%m%d").date(),
                data_root=self.data,
            ) as rows:
                next(rows)
        original = self.path(partition).stat()
        write_gzip(self.path(partition), [v3_swap("c"), v3_swap("d")])
        os.utime(
            self.path(partition),
            ns=(original.st_atime_ns, original.st_mtime_ns),
        )
        with self.assertRaisesRegex(ValueError, "changed after scan"):
            with verified_source_day_rows(
                partition.source,
                partition.stream,
                dt.datetime.strptime(partition.day, "%Y%m%d").date(),
                data_root=self.data,
            ):
                pass

    def test_verified_local_partition_reader_rejects_ledger_certificate_and_mid_read_mutation(self) -> None:
        partition = self.perimeter
        expected_rows = [v3_swap("a"), v3_swap("b")]
        write_gzip(self.path(partition), expected_rows)
        observed = self.scan(partition)
        certificate = self.data / "processed" / "raw_generation" / "uniswap_v3_local_certificate.json"
        write_local_scan_certificate(
            certificate,
            [observed],
            expected_partitions=[partition],
        )
        ledger = certificate.with_suffix(".partitions.jsonl")
        ledger.write_text(ledger.read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ledger mismatch"):
            with verified_source_day_rows(
                partition.source,
                partition.stream,
                dt.datetime.strptime(partition.day, "%Y%m%d").date(),
                data_root=self.data,
            ):
                pass
        write_local_scan_certificate(
            certificate,
            [observed],
            expected_partitions=[partition],
        )
        body = json.loads(certificate.read_text(encoding="utf-8"))
        body["status"] = "tampered"
        certificate.write_text(json.dumps(body), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "envelope mismatch"):
            with verified_source_day_rows(
                partition.source,
                partition.stream,
                dt.datetime.strptime(partition.day, "%Y%m%d").date(),
                data_root=self.data,
            ):
                pass
        write_local_scan_certificate(
            certificate,
            [observed],
            expected_partitions=[partition],
        )
        with self.assertRaisesRegex(
            RawFetchInvariantError, "authority changed during read"
        ):
            with verified_source_day_rows(
                partition.source,
                partition.stream,
                dt.datetime.strptime(partition.day, "%Y%m%d").date(),
                data_root=self.data,
            ) as rows:
                self.assertEqual(next(rows), expected_rows[0])
                certificate.write_text(
                    certificate.read_text(encoding="utf-8") + "\n",
                    encoding="utf-8",
                )
                self.assertEqual(list(rows), expected_rows[1:])

    def test_verified_partition_reader_has_no_uncertified_fallback(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        with self.assertRaisesRegex(ValueError, "certificate is unreadable"):
            with verified_source_day_rows(
                partition.source,
                partition.stream,
                dt.datetime.strptime(partition.day, "%Y%m%d").date(),
                data_root=self.data,
            ):
                pass

    def test_verified_local_reader_binds_metadata_presence_content_and_registry(self) -> None:
        partition = self.perimeter
        rows = [v3_swap("a"), v3_swap("b")]
        write_gzip(self.path(partition), rows)
        certificate = self.data / "processed" / "raw_generation" / "uniswap_v3_local_certificate.json"
        observed = self.scan(partition)
        write_local_scan_certificate(
            certificate,
            [observed],
            expected_partitions=[partition],
        )
        metadata = self.meta_path(partition)
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "metadata presence changed"):
            with verified_source_day_rows(
                partition.source,
                partition.stream,
                dt.datetime.strptime(partition.day, "%Y%m%d").date(),
                data_root=self.data,
            ):
                pass
        metadata_payload = {
            "source": partition.source,
            "day": "2024-01-01",
            "streams": {partition.stream: {"rows": len(rows)}},
        }
        metadata.write_text(json.dumps(metadata_payload), encoding="utf-8")
        observed = self.scan(partition)
        write_local_scan_certificate(
            certificate,
            [observed],
            expected_partitions=[partition],
        )
        metadata_payload["streams"][partition.stream]["rows"] = 999
        metadata.write_text(json.dumps(metadata_payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "metadata changed after scan"):
            with verified_source_day_rows(
                partition.source,
                partition.stream,
                dt.datetime.strptime(partition.day, "%Y%m%d").date(),
                data_root=self.data,
            ):
                pass
        metadata_payload["streams"][partition.stream]["rows"] = len(rows)
        metadata.write_text(json.dumps(metadata_payload), encoding="utf-8")
        observed = self.scan(partition)
        write_local_scan_certificate(
            certificate,
            [observed],
            expected_partitions=[partition],
        )
        metadata.unlink()
        with self.assertRaisesRegex(ValueError, "metadata presence changed"):
            with verified_source_day_rows(
                partition.source,
                partition.stream,
                dt.datetime.strptime(partition.day, "%Y%m%d").date(),
                data_root=self.data,
            ):
                pass
        metadata.write_text(json.dumps(metadata_payload), encoding="utf-8")
        observed = self.scan(partition)
        write_local_scan_certificate(
            certificate,
            [observed],
            expected_partitions=[partition],
        )
        with self.assertRaisesRegex(ValueError, "metadata changed after scan"):
            with verified_source_day_rows(
                partition.source,
                partition.stream,
                dt.datetime.strptime(partition.day, "%Y%m%d").date(),
                data_root=self.data,
            ) as streamed:
                self.assertEqual(next(streamed), rows[0])
                metadata.write_text(
                    metadata.read_text(encoding="utf-8") + "\n",
                    encoding="utf-8",
                )
                self.assertEqual(list(streamed), rows[1:])
        metadata.write_text(json.dumps(metadata_payload), encoding="utf-8")
        observed = self.scan(partition)
        write_local_scan_certificate(
            certificate,
            [observed],
            expected_partitions=[partition],
        )
        expected_identity = raw_partition_generation_identity(
            partition.source,
            partition.stream,
            partition.day,
            data_root=self.data,
        )
        with patch.dict(
            DEX_SOURCES,
            {
                partition.source: replace(
                    DEX_SOURCES[partition.source],
                    route_normalizer_family="mutated-before-read",
                )
            },
        ):
            with self.assertRaisesRegex(
                RawFetchInvariantError, "authority changed before read"
            ):
                with verified_source_day_rows(
                    partition.source,
                    partition.stream,
                    dt.datetime.strptime(partition.day, "%Y%m%d").date(),
                    data_root=self.data,
                    expected_generation_identity=expected_identity,
                ):
                    pass
        registry_patch = patch.dict(
            DEX_SOURCES,
            {
                partition.source: replace(
                    DEX_SOURCES[partition.source], notes="mutated during read"
                )
            },
        )
        try:
            with self.assertRaisesRegex(
                RawFetchInvariantError, "authority changed during read"
            ):
                with verified_source_day_rows(
                    partition.source,
                    partition.stream,
                    dt.datetime.strptime(partition.day, "%Y%m%d").date(),
                    data_root=self.data,
                ) as streamed:
                    self.assertEqual(next(streamed), rows[0])
                    registry_patch.start()
                    self.assertEqual(list(streamed), rows[1:])
        finally:
            registry_patch.stop()

    def test_local_scan_certificate_owns_one_explicit_ledger_publication(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        observed = self.scan(partition)
        output = self.root / "certificate.json"
        ledger = self.root / "local-scan.jsonl"
        certificate = write_local_scan_certificate(
            output,
            [observed],
            expected_partitions=[partition],
            ledger_path=ledger,
        )
        self.assertTrue(ledger.is_file())
        self.assertFalse(output.with_suffix(".partitions.jsonl").exists())
        self.assertEqual(certificate["partition_ledger"], ledger.name)
        rows, _binding = load_certified_partition_ledger(
            output, data_root=self.data
        )
        self.assertEqual(rows, [observed])
        with self.assertRaisesRegex(ValueError, "must be siblings"):
            write_local_scan_certificate(
                output,
                [observed],
                expected_partitions=[partition],
                ledger_path=self.root / "nested" / "local-scan.jsonl",
            )

    def test_failed_local_scan_publishes_one_diagnostic_ledger_and_no_certificate(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        observed = self.scan(partition)
        ledger = self.root / "local-scan.jsonl"
        certificate = self.root / "certificate.json"
        publish_local_scan(ledger, certificate, [observed], (partition,))
        self.assertTrue(certificate.is_file())
        failed = {**observed, "local_pass": False, "errors": ["diagnostic"]}
        summary = publish_local_scan(ledger, certificate, [failed], (partition,))
        self.assertEqual(summary["failed"], 1)
        self.assertFalse(certificate.exists())
        self.assertFalse(certificate.with_suffix(".partitions.jsonl").exists())
        self.assertEqual(json.loads(ledger.read_text()), failed)

    def test_local_scan_certificate_rejects_tampered_ledger_and_partial_perimeter(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        observed = self.scan(partition)
        output = self.root / "local-certificate.json"
        write_local_scan_certificate(
            output,
            [observed],
            expected_partitions=[partition],
        )
        ledger = output.with_suffix(".partitions.jsonl")
        ledger.write_text(ledger.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "ledger mismatch"):
            load_certified_partition_ledger(output, data_root=self.data)
        with self.assertRaisesRegex(ValueError, "perimeter mismatch"):
            write_local_scan_certificate(
                output,
                [observed],
                expected_partitions=[partition, RawPartition("uniswap_v3", "mints", DAY)],
            )

    def test_graph_scan_rejects_duplicate_out_of_order_and_out_of_day_rows(self) -> None:
        partition = RawPartition("uniswap_v3", "swaps", DAY)
        rows = [
            v3_swap("b"),
            v3_swap("a"),
            v3_swap("a", 1_704_153_600),
            v3_swap("c", 1_704_067_199),
        ]
        write_gzip(self.path(partition), rows)
        observed = self.scan(partition)
        self.assertFalse(observed["local_pass"])
        self.assertIn("unstable_pagination_order", observed["errors"])
        self.assertIn("duplicate_pagination_identity", observed["errors"])
        self.assertIn("outside_utc_day", observed["errors"])

    def test_scan_rejects_consumer_field_and_sidecar_count_failures(self) -> None:
        partition = RawPartition("uniswap_v4", "swaps", DAY)
        row = v3_swap("a")
        pool = row["pool"]
        assert isinstance(pool, dict)
        pool.pop("feeTier")
        pool["token0"] = {"id": "token0", "symbol": "T0"}
        pool["token1"] = {"id": "token1", "symbol": "T1"}
        row.pop("amountUSD")
        row.pop("sqrtPriceX96")
        row.pop("tick")
        write_gzip(self.path(partition), [row])
        self.meta_path(partition).write_text(
            json.dumps(
                {
                    "source": partition.source,
                    "day": "2024-01-01",
                    "streams": {partition.stream: {"rows": 2}},
                }
            )
        )
        observed = self.scan(partition)
        self.assertNotIn("missing_field:pool.token0.decimals", observed["errors"])
        self.assertNotIn("missing_field:pool.feeTier", observed["errors"])
        self.assertNotIn("missing_field:amountUSD", observed["errors"])
        self.assertIn("sidecar_row_count_mismatch", observed["errors"])

    def test_sidecar_content_hash_mismatch_fails_local_scan(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        self.meta_path(partition).write_text(
            json.dumps(
                {
                    "source": partition.source,
                    "day": "2024-01-01",
                    "streams": {
                        partition.stream: {
                            "rows": 1,
                            "logical_content_sha256": "0" * 64,
                        }
                    },
                }
            )
        )
        observed = self.scan(partition)
        self.assertFalse(observed["local_pass"])
        self.assertIn("sidecar_content_hash_mismatch", observed["errors"])

    def test_optional_swap_enrichment_can_be_null_or_empty(self) -> None:
        partition = RawPartition("uniswap_v3", "swaps", DAY)
        row = v3_swap("a")
        pool = row["pool"]
        assert isinstance(pool, dict)
        token0 = pool["token0"]
        assert isinstance(token0, dict)
        token0["symbol"] = None
        pool["feeTier"] = None
        write_gzip(self.path(partition), [row])
        observed = self.scan(partition)
        self.assertTrue(observed["local_pass"], observed["errors"])
        self.assertNotIn("missing_field:pool.token0.symbol", observed["errors"])
        self.assertNotIn("missing_field:pool.feeTier", observed["errors"])

    def test_v3_swap_replay_state_is_a_required_consumer_field(self) -> None:
        partition = RawPartition("uniswap_v3", "swaps", DAY)
        for field in ("sqrtPriceX96", "tick"):
            with self.subTest(field=field):
                row = v3_swap("a")
                row[field] = ""
                write_gzip(self.path(partition), [row])
                self.assertIn(f"missing_field:{field}", self.scan(partition)["errors"])

    def test_missing_metadata_is_allowed_for_legacy_local_content_only(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        observed = self.scan(partition)
        self.assertTrue(observed["local_pass"])
        self.assertFalse(observed["metadata_present"])
        self.assertNotIn("observed_query_contract_sha256", observed)

    def test_dune_scan_uses_transaction_event_identity_and_utc_time(self) -> None:
        partition = RawPartition("fluid", "swaps", DAY)
        first = fluid_swap()
        second = fluid_swap("2024-01-01 00:00:02.000 UTC")
        second["tx_hash"] = "0xdef"
        write_gzip(self.path(partition), [first, second])
        observed = self.scan(partition)
        self.assertTrue(observed["local_pass"])
        self.assertEqual(observed["rows"], 2)
        self.assertEqual(observed["first_pagination_identity"], "0xabc")

    def test_dune_generation_accepts_exact_recorded_month_window(self) -> None:
        partition = RawPartition("fluid", "swaps", DAY)
        source = get_source("fluid")
        start = dt.date(2024, 1, 1)
        end = dt.date(2024, 2, 1)
        write_gzip(self.path(partition), [fluid_swap()])
        digest = portable_content_sha256(self.path(partition))
        self.meta_path(partition).write_text(
            json.dumps(
                {
                    "source": "fluid",
                    "day": start.isoformat(),
                    "streams": {
                        "swaps": {
                            "rows": 1,
                            "logical_content_sha256": digest,
                            "query_contract_sha256": dune.dune_query_contract_sha256(
                                source, start, end
                            ),
                            dune.DUNE_QUERY_START_FIELD: start.isoformat(),
                            dune.DUNE_QUERY_END_EXCLUSIVE_FIELD: end.isoformat(),
                        }
                    },
                }
            )
        )
        observed = self.scan(partition)
        self.assertEqual(
            _validate_generation_against_local(
                {"generation_kind": "dune_sql_export", "source": "fluid"},
                [observed],
            ),
            [],
        )
        tampered = {**observed, "observed_query_start_date": "2024-02-01"}
        self.assertEqual(
            _validate_generation_against_local(
                {"generation_kind": "dune_sql_export", "source": "fluid"},
                [tampered],
            ),
            [DAY],
        )

    def test_dune_scan_rejects_noncausal_block_event_order(self) -> None:
        partition = RawPartition("fluid", "swaps", DAY)
        first = fluid_swap("2024-01-01 00:00:01.000 UTC")
        first["block_number"] = 18_900_001
        second = fluid_swap("2024-01-01 00:00:02.000 UTC")
        second["tx_hash"] = "0xdef"
        second["block_number"] = 18_900_000
        write_gzip(self.path(partition), [first, second])
        observed = self.scan(partition)
        self.assertIn("unstable_pagination_order", observed["errors"])

    def test_normalized_legacy_ledger_retains_exact_comparison_fields(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        output = self.root / "legacy.jsonl"
        self.assertEqual(
            write_normalized_legacy_ledger(
                self.data,
                partition.source,
                partition.stream,
                [partition.day],
                output,
            ),
            1,
        )
        row = json.loads(output.read_text().strip())
        contract = comparison_contract(partition.source, partition.stream)
        self.assertEqual(set(row["identity"]), set(contract.identity_fields))
        self.assertEqual(set(row["quantities"]), set(contract.quantity_fields))

    def test_prepare_and_finalize_evidence_commands_build_reopenable_bundle(self) -> None:
        partitions, local = self.fresh_local_partitions()
        local_ledger = self.root / "local.jsonl"
        local_ledger.write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in local
            )
        )
        bundle = self.root / "bundle"
        with patch(
            "ddvc.raw_certification.required_partitions",
            return_value=tuple(partitions),
        ):
            prepared = prepare_evidence(self.data, local_ledger, bundle)
        self.assertEqual(prepared["pairs"], 1)
        canonical_before = {
            path.relative_to(self.data): file_sha256(path)
            for path in self.data.rglob("*")
            if path.is_file()
        }

        def fake_fetch(source, day, *, streams, data_root, **_kwargs):
            stream = next(iter(streams))
            day_text = day.strftime("%Y%m%d")
            partition = RawPartition(source.name, stream, day_text)
            path = (
                data_root
                / "raw"
                / "thegraph"
                / source.name
                / f"{source.name}_{stream}_{day_text}.jsonl.gz"
            )
            with gzip.open(self.path(partition), "rt", encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
            write_gzip(path, rows)
            meta = path.with_name(f"{source.name}_meta_{day_text}.json")
            meta.write_text(
                json.dumps(
                    {
                        "source": source.name,
                        "day": day.isoformat(),
                        "streams": {
                            stream: {
                                "rows": len(rows),
                                "query_contract_sha256": graph_contract_sha256(
                                    source.name, stream
                                ),
                            }
                        },
                    }
                )
            )
            return {"partition": partition.day}

        repository = Path(__file__).resolve().parents[1]
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        acquisition_code = {
            "policy": FETCH_CODE_ARTIFACT_POLICY,
            "source": "uniswap_v3",
            "stream": "swaps",
            "repository_commit_sha": commit,
            "tracked_blobs": [
                {
                    "path": path,
                    "blob_sha256": hashlib.sha256(
                        subprocess.run(
                            ["git", "show", f"{commit}:{path}"],
                            cwd=repository,
                            check=True,
                            capture_output=True,
                        ).stdout
                    ).hexdigest(),
                }
                for path in sorted(
                    [
                        "scripts/fetch_raw_market_data.py",
                        "src/ddvc/fetch/graph.py",
                        "src/ddvc/fetch/raw.py",
                    ]
                )
            ],
        }

        with (
            patch(
                "ddvc.raw_certification.required_partitions",
                return_value=tuple(partitions),
            ),
            patch(
                "scripts.certify_raw_generation.frozen_graph_head",
                return_value=25_000_000,
            ),
            patch(
                "scripts.certify_raw_generation.fetch_source_day",
                side_effect=fake_fetch,
            ),
            patch(
                "scripts.certify_raw_generation.fetch_code_artifact",
                return_value=acquisition_code,
            ),
        ):
            acquired = acquire_references(
                bundle,
                scratch_root=bundle / "reference_raw",
                workers=2,
            )
        self.assertEqual(acquired, {"pairs": 1, "status": "acquired"})
        self.assertEqual(
            canonical_before,
            {
                path.relative_to(self.data): file_sha256(path)
                for path in self.data.rglob("*")
                if path.is_file()
            },
        )
        finalized = finalize_evidence(bundle)
        self.assertEqual(finalized, {
            "pairs": 1,
            "passed": 1,
            "failed": 0,
            "adjudication_evidence": "adjudication.json",
        })
        certificate_path = bundle / "certificate.json"
        with patch(
            "ddvc.raw_certification.required_partitions",
            return_value=tuple(partitions),
        ):
            certificate = write_retro_certificate(
                certificate_path,
                local,
                generation_evidence=bundle / "generation.json",
                adjudication_evidence=bundle / "adjudication.json",
            )
            self.assertEqual(certificate["status"], "passed")
            verify_retro_certificate(certificate_path, data_root=self.data)
        acquisition = json.loads((bundle / "reference-acquisition.json").read_text())
        evidence = json.loads(
            (bundle / acquisition["entries"][0]["evidence"]).read_text()
        )
        retained = bundle / evidence["raw_artifacts"][0]["path"]
        retained.write_bytes(retained.read_bytes() + b"tampered")
        with self.assertRaisesRegex(ValueError, "fresh provider response changed"):
            finalize_evidence(bundle)

    def test_finalize_rejects_partial_reference_acquisition(self) -> None:
        partitions, local = self.fresh_local_partitions()
        local_ledger = self.root / "local.jsonl"
        local_ledger.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in local)
        )
        bundle = self.root / "bundle"
        with patch(
            "ddvc.raw_certification.required_partitions",
            return_value=tuple(partitions),
        ):
            prepare_evidence(self.data, local_ledger, bundle)
        (bundle / "reference-acquisition.json").write_text(
            json.dumps(
                {
                    "policy": "fresh-reference-acquisition-v1",
                    "plan_sha256": file_sha256(
                        bundle / "fresh-reference-plan.json"
                    ),
                    "entries": [],
                }
            )
        )
        with self.assertRaisesRegex(ValueError, "acquisition is partial"):
            finalize_evidence(bundle)

    def test_completed_month_shard_is_reused_until_an_input_changes(self) -> None:
        partition = RawPartition("uniswap_v3", "swaps", DAY)
        write_gzip(self.path(partition), [v3_swap("a")])
        first = self.scan(partition)
        cache = next(self.work.glob("*.json"))
        first_cache = cache.read_bytes()
        second = self.scan(partition)
        self.assertEqual(first, second)
        self.assertEqual(cache.read_bytes(), first_cache)
        write_gzip(self.path(partition), [v3_swap("a"), v3_swap("b")])
        third = self.scan(partition)
        self.assertEqual(third["rows"], 2)
        self.assertNotEqual(third["logical_content_sha256"], first["logical_content_sha256"])

    def test_v3_cache_without_file_generation_identity_is_forced_through_v4_rescan(self) -> None:
        partition = RawPartition("uniswap_v3", "swaps", DAY)
        write_gzip(self.path(partition), [v3_swap("a")])
        self.scan(partition)
        cache = next(self.work.glob("*.json"))
        stale = json.loads(cache.read_text())
        stale["scan_policy"] = "installed-required-raw-local-scan-v3"
        stale["partitions"][0].pop("container_mtime_ns")
        stale["partitions"][0].pop("container_ctime_ns")
        cache.write_text(json.dumps(stale))
        from ddvc.raw_certification import _scan_partition

        with patch(
            "ddvc.raw_certification._scan_partition", wraps=_scan_partition
        ) as scan_partition:
            observed = self.scan(partition)
        scan_partition.assert_called_once()
        self.assertIn("container_mtime_ns", observed)
        self.assertIn("container_ctime_ns", observed)

    def test_cached_missing_partition_is_rescanned_when_file_appears(self) -> None:
        partition = RawPartition("uniswap_v3", "swaps", DAY)
        missing = self.scan(partition)
        self.assertEqual(missing["errors"], ["missing_file"])
        write_gzip(self.path(partition), [v3_swap("a")])
        observed = self.scan(partition)
        self.assertTrue(observed["local_pass"])
        self.assertEqual(observed["rows"], 1)

    def test_same_size_rewrite_with_restored_mtime_invalidates_cache(self) -> None:
        partition = self.perimeter
        path = self.path(partition)
        write_gzip(path, [v3_swap("a")])
        first = self.scan(partition)
        original = path.stat()
        write_gzip(path, [v3_swap("b")])
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        rewritten = path.stat()
        self.assertEqual(rewritten.st_size, original.st_size)
        self.assertEqual(rewritten.st_mtime_ns, original.st_mtime_ns)
        self.assertNotEqual(rewritten.st_ctime_ns, original.st_ctime_ns)
        second = self.scan(partition)
        self.assertNotEqual(
            second["logical_content_sha256"], first["logical_content_sha256"]
        )

    def test_cached_partition_is_rescanned_when_metadata_changes(self) -> None:
        partition = RawPartition("uniswap_v3", "swaps", DAY)
        write_gzip(self.path(partition), [v3_swap("a")])
        self.meta_path(partition).write_text(
            json.dumps(
                {
                    "source": partition.source,
                    "day": "2024-01-01",
                    "streams": {
                        partition.stream: {
                            "rows": 1,
                            "query_contract_sha256": "9" * 64,
                        }
                    },
                }
            )
        )
        first = self.scan(partition)
        self.assertTrue(first["local_pass"])
        self.meta_path(partition).write_text(
            json.dumps(
                {
                    "source": partition.source,
                    "day": "2024-01-01",
                    "streams": {
                        partition.stream: {
                            "rows": 2,
                            "query_contract_sha256": "changed",
                        }
                    },
                }
            )
        )
        observed = self.scan(partition)
        self.assertIn("sidecar_row_count_mismatch", observed["errors"])
        self.assertEqual(observed["observed_query_contract_sha256"], "changed")

    def test_present_metadata_requires_source_day_and_nonbool_row_count(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        self.meta_path(partition).write_text(
            json.dumps({"streams": {partition.stream: {"rows": True}}})
        )
        observed = self.scan(partition)
        self.assertFalse(observed["local_pass"])
        self.assertIn(observed["metadata_error"], {
            "metadata_source_identity",
            "metadata_day_identity",
            "metadata_row_count",
        })
        self.meta_path(partition).write_text(
            json.dumps(
                {
                    "source": partition.source,
                    "day": "2024-01-01",
                    "streams": {partition.stream: {"rows": True}},
                }
            )
        )
        observed = self.scan(partition)
        self.assertIn("metadata_row_count", observed["errors"])

    def test_v3_provider_usd_is_not_a_route_or_exact_state_prerequisite(self) -> None:
        partition = self.perimeter
        row = v3_swap("a")
        row.pop("amountUSD")
        write_gzip(self.path(partition), [row])
        self.assertNotIn("missing_field:amountUSD", self.scan(partition)["errors"])

    def test_provider_symbols_are_optional_route_enrichment(self) -> None:
        optional = {
            ("uniswap_v2", "swaps"): ("pair.token0.symbol", "pair.token1.symbol"),
            ("sushiswap_v2", "swaps"): ("pair.token0.symbol", "pair.token1.symbol"),
            ("uniswap_v3", "swaps"): ("pool.token0.symbol", "pool.token1.symbol"),
            ("uniswap_v4", "swaps"): ("pool.token0.symbol", "pool.token1.symbol"),
            ("curve", "swaps"): ("tokenIn.symbol", "tokenOut.symbol"),
            ("sushiswap_v3", "swaps"): ("tokenIn.symbol", "tokenOut.symbol"),
            ("balancer", "swaps"): ("tokenInSym", "tokenOutSym"),
            ("fluid", "swaps"): ("token_sold_symbol", "token_bought_symbol"),
        }
        for key, fields in optional.items():
            with self.subTest(source=key[0], stream=key[1]):
                required = FIELD_CONTRACTS[key].required_paths
                self.assertTrue(all(field not in required for field in fields))

        partition = self.perimeter
        row = v3_swap("a")
        pool = row["pool"]
        assert isinstance(pool, dict)
        for side in ("token0", "token1"):
            token = pool[side]
            assert isinstance(token, dict)
            token.pop("symbol")
        write_gzip(self.path(partition), [row])
        observed = self.scan(partition)
        self.assertTrue(observed["local_pass"], observed["errors"])

    def test_curve_provider_amp_is_not_a_materializer_prerequisite(self) -> None:
        partition = RawPartition("curve", "daily", DAY)
        write_gzip(
            self.path(partition),
            [
                {
                    "id": "snapshot",
                    "timestamp": "1704067300",
                    "inputTokenBalances": ["1", "2"],
                    "pool": {
                        "id": "pool",
                        "symbol": "3pool",
                        "inputTokens": [
                            {"id": "token0", "decimals": "18"},
                            {"id": "token1", "decimals": "6"},
                        ],
                    },
                }
            ],
        )
        observed = self.scan(partition)
        self.assertTrue(observed["local_pass"], observed["errors"])
        self.assertNotIn("pool.amp", FIELD_CONTRACTS[("curve", "daily")].required_paths)

    def test_balancer_fitted_parameters_are_optional_but_state_is_required(self) -> None:
        partition = RawPartition("balancer", "daily", DAY)
        row = {
            "id": "snapshot",
            "timestamp": "1704067300",
            "amounts": ["1", "2"],
            "pool": {
                "id": "pool",
                "poolType": "Weighted",
                "swapFee": "0.003",
                "tokensList": ["token0", "token1"],
                "tokens": [
                    {"address": "token0", "decimals": "18"},
                    {"address": "token1", "decimals": "6"},
                ],
            },
        }
        write_gzip(self.path(partition), [row])
        observed = self.scan(partition)
        self.assertTrue(observed["local_pass"], observed["errors"])
        row_without_balances = dict(row)
        row_without_balances.pop("amounts")
        write_gzip(self.path(partition), [row_without_balances])
        self.assertIn(
            "missing_field:amounts", self.scan(partition)["errors"]
        )
        pool = row["pool"]
        assert isinstance(pool, dict)
        tokens = pool["tokens"]
        assert isinstance(tokens, list)
        token0 = tokens[0]
        assert isinstance(token0, dict)
        token0.pop("decimals")
        write_gzip(self.path(partition), [row])
        self.assertIn(
            "missing_field:pool.tokens[].decimals",
            self.scan(partition)["errors"],
        )

    def test_cached_partition_is_rescanned_when_consumer_contract_changes(self) -> None:
        partition = RawPartition("uniswap_v3", "swaps", DAY)
        write_gzip(self.path(partition), [v3_swap("a")])
        self.assertTrue(self.scan(partition)["local_pass"])
        key = (partition.source, partition.stream)
        original = FIELD_CONTRACTS[key]
        changed = FieldContract(
            (*original.required_paths, "new.consumer.field"),
            original.timestamp_path,
            original.identity_path,
            original.order_path,
        )
        with patch.dict(FIELD_CONTRACTS, {key: changed}):
            observed = self.scan(partition)
        self.assertIn("missing_field:new.consumer.field", observed["errors"])

    def test_shard_is_not_cached_if_an_input_changes_during_scan(self) -> None:
        partition = RawPartition("uniswap_v3", "swaps", DAY)
        write_gzip(self.path(partition), [v3_swap("a")])
        from ddvc.raw_certification import _scan_partition

        def mutate_after_scan(data_root: str, selected: RawPartition):
            observed = _scan_partition(data_root, selected)
            write_gzip(self.path(partition), [v3_swap("a"), v3_swap("b")])
            return observed

        with patch(
            "ddvc.raw_certification._scan_partition", side_effect=mutate_after_scan
        ):
            with self.assertRaisesRegex(RuntimeError, "changed while scanning"):
                self.scan(partition)
        self.assertFalse(any(self.work.glob("*.json")))

    def test_retro_certificate_is_distinct_deterministic_and_reopenable(self) -> None:
        partition = RawPartition("uniswap_v3", "swaps", DAY)
        write_gzip(self.path(partition), [v3_swap("a")])
        local = [self.scan(partition)]
        generation, adjudication = self.evidence_bundle(
            partition.source, partition.stream
        )
        output = self.root / "certificate.json"
        certificate = write_retro_certificate(
            output,
            local,
            generation_evidence=generation,
            adjudication_evidence=adjudication,
        )
        self.assertEqual(certificate["policy"], RETRO_CERTIFICATION_POLICY)
        self.assertEqual(certificate["status"], "passed")
        self.assertFalse(certificate["asserts_current_frozen_head_query_contract"])
        self.assertEqual(
            verify_retro_certificate(output, data_root=self.data), certificate
        )
        original = output.read_bytes()
        write_retro_certificate(
            output,
            local,
            generation_evidence=generation,
            adjudication_evidence=adjudication,
        )
        self.assertEqual(output.read_bytes(), original)

    def test_current_generation_requires_observed_contract_and_frozen_head(self) -> None:
        partition = RawPartition("uniswap_v3", "swaps", DAY)
        write_gzip(self.path(partition), [v3_swap("a")])
        local = [self.scan(partition)]
        generation, adjudication = self.evidence_bundle(
            partition.source,
            partition.stream,
            kind="current_frozen_graph",
            query_hash="7" * 64,
        )
        certificate = write_retro_certificate(
            self.root / "certificate.json",
            local,
            generation_evidence=generation,
            adjudication_evidence=adjudication,
        )
        self.assertEqual(certificate["status"], "incomplete")
        self.assertEqual(
            certificate["generation_mismatch_days"],
            {"uniswap_v3/swaps": [DAY]},
        )

    def test_generation_rejects_invented_hashes_without_artifacts(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        generation, adjudication = self.evidence_bundle(
            partition.source, partition.stream
        )
        payload = json.loads(generation.read_text())
        entry = payload["generations"][0]
        entry.update(
            {
                "provenance_status": "available",
                "fetch_code_identity_sha256": "1" * 64,
                "query_generation_identity_sha256": "2" * 64,
            }
        )
        entry["generation_identity_sha256"] = generation_identity(entry)
        generation.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "fetch-code artifact missing"):
            write_retro_certificate(
                self.root / "certificate.json",
                [self.scan(partition)],
                generation_evidence=generation,
                adjudication_evidence=adjudication,
            )

    def test_generation_rejects_nonexistent_fetch_commit(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        generation, adjudication = self.evidence_bundle(
            partition.source,
            partition.stream,
            kind="current_frozen_graph",
        )
        fetch = self.root / "fetch-code.json"
        fetch_payload = json.loads(fetch.read_text())
        fetch_payload["repository_commit_sha"] = "0" * 40
        fetch.write_text(json.dumps(fetch_payload, sort_keys=True))
        payload = json.loads(generation.read_text())
        entry = payload["generations"][0]
        entry["fetch_code_artifact_sha256"] = file_sha256(fetch)
        entry["fetch_code_identity_sha256"] = canonical_json_sha256(fetch_payload)
        entry["generation_identity_sha256"] = generation_identity(entry)
        generation.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "commit or path is unavailable"):
            write_retro_certificate(
                self.root / "certificate.json",
                [self.scan(partition)],
                generation_evidence=generation,
                adjudication_evidence=adjudication,
            )

    def test_generation_rejects_wrong_fetch_blob_hash(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        generation, adjudication = self.evidence_bundle(
            partition.source,
            partition.stream,
            kind="current_frozen_graph",
        )
        fetch = self.root / "fetch-code.json"
        fetch_payload = json.loads(fetch.read_text())
        fetch_payload["tracked_blobs"][0]["blob_sha256"] = "f" * 64
        fetch.write_text(json.dumps(fetch_payload, sort_keys=True))
        payload = json.loads(generation.read_text())
        entry = payload["generations"][0]
        entry["fetch_code_artifact_sha256"] = file_sha256(fetch)
        entry["fetch_code_identity_sha256"] = canonical_json_sha256(fetch_payload)
        entry["generation_identity_sha256"] = generation_identity(entry)
        generation.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "blob hash mismatch"):
            write_retro_certificate(
                self.root / "certificate.json",
                [self.scan(partition)],
                generation_evidence=generation,
                adjudication_evidence=adjudication,
            )

    def test_query_artifact_change_invalidates_adjudication_generation(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        generation, adjudication = self.evidence_bundle(
            partition.source,
            partition.stream,
            kind="current_frozen_graph",
        )
        query = self.root / "query.json"
        query_payload = json.loads(query.read_text())
        query_payload["query_contract"]["semantic_revision"] = "changed"
        query.write_text(json.dumps(query_payload, sort_keys=True))
        payload = json.loads(generation.read_text())
        entry = payload["generations"][0]
        entry["query_artifact_sha256"] = file_sha256(query)
        entry["query_generation_identity_sha256"] = canonical_json_sha256(
            query_payload["query_contract"]
        )
        entry["generation_identity_sha256"] = generation_identity(entry)
        generation.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "adjudication generation mismatch"):
            write_retro_certificate(
                self.root / "certificate.json",
                [self.scan(partition)],
                generation_evidence=generation,
                adjudication_evidence=adjudication,
            )

    def test_missing_adjudication_is_incomplete_not_a_local_refetch_claim(self) -> None:
        partition = RawPartition("uniswap_v3", "swaps", DAY)
        write_gzip(self.path(partition), [v3_swap("a")])
        local = [self.scan(partition)]
        generation, adjudication = self.evidence_bundle(
            partition.source, partition.stream
        )
        adjudication.write_text(
            json.dumps(
                {"policy": ADJUDICATION_EVIDENCE_POLICY, "evidence": []}
            )
        )
        certificate = write_retro_certificate(
            self.root / "certificate.json",
            local,
            generation_evidence=generation,
            adjudication_evidence=adjudication,
        )
        self.assertEqual(certificate["status"], "incomplete")
        self.assertEqual(certificate["local_repair_required"], [])
        self.assertEqual(
            certificate["missing_adjudication_evidence"], ["uniswap_v3/swaps"]
        )

    def test_fresh_adjudication_rejects_relabelled_strata(self) -> None:
        partitions, local = self.fresh_local_partitions()
        generation, adjudication = self.evidence_bundle(
            "uniswap_v3",
            "swaps",
            adjudication_kind="fresh_stratified_comparison",
            local_partitions=local,
        )
        payload = json.loads(adjudication.read_text())
        artifact = self.root / "comparison.json"
        artifact_payload = json.loads(artifact.read_text())
        relabelled = dict(payload["evidence"][0]["strata"])
        relabelled["early_quiet"], relabelled["middle_quiet"] = (
            relabelled["middle_quiet"],
            relabelled["early_quiet"],
        )
        payload["evidence"][0]["strata"] = relabelled
        artifact_payload["strata"] = relabelled
        artifact.write_text(json.dumps(artifact_payload, sort_keys=True))
        payload["evidence"][0]["artifact_sha256"] = file_sha256(artifact)
        adjudication.write_text(json.dumps(payload))
        with patch(
            "ddvc.raw_certification.required_partitions",
            return_value=tuple(partitions),
        ):
            with self.assertRaisesRegex(ValueError, "do not follow the selection frame"):
                write_retro_certificate(
                    self.root / "certificate.json",
                    local,
                    generation_evidence=generation,
                    adjudication_evidence=adjudication,
                )

    def test_fresh_adjudication_rejects_forged_selection_population(self) -> None:
        partitions, local = self.fresh_local_partitions()
        generation, adjudication = self.evidence_bundle(
            "uniswap_v3",
            "swaps",
            adjudication_kind="fresh_stratified_comparison",
            local_partitions=local,
        )
        artifact = self.root / "comparison.json"
        artifact_payload = json.loads(artifact.read_text())
        frame = artifact_payload["selection_frame"]
        frame["candidate_population"][0]["activity_rows"] += 100
        frame["candidate_population_sha256"] = canonical_json_sha256(
            frame["candidate_population"]
        )
        artifact.write_text(json.dumps(artifact_payload, sort_keys=True))
        manifest = json.loads(adjudication.read_text())
        manifest["evidence"][0]["selection_frame"] = frame
        manifest["evidence"][0]["artifact_sha256"] = file_sha256(artifact)
        adjudication.write_text(json.dumps(manifest))
        with patch(
            "ddvc.raw_certification.required_partitions",
            return_value=tuple(partitions),
        ):
            with self.assertRaisesRegex(ValueError, "does not match local evidence"):
                write_retro_certificate(
                    self.root / "certificate.json",
                    local,
                    generation_evidence=generation,
                    adjudication_evidence=adjudication,
                )

    def test_adjudication_rejects_a_hollow_hashed_artifact(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        generation, adjudication = self.evidence_bundle(
            partition.source, partition.stream
        )
        artifact = self.root / "comparison.json"
        artifact.write_text('{"status":"passed"}\n')
        payload = json.loads(adjudication.read_text())
        payload["evidence"][0]["artifact_sha256"] = hashlib.sha256(
            artifact.read_bytes()
        ).hexdigest()
        adjudication.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "does not bind its artifact"):
            write_retro_certificate(
                self.root / "certificate.json",
                [self.scan(partition)],
                generation_evidence=generation,
                adjudication_evidence=adjudication,
            )

    def test_adjudication_recomputes_counts_from_retained_ledgers(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        generation, adjudication = self.evidence_bundle(
            partition.source, partition.stream
        )
        reference = self.root / "reference-comparison.jsonl"
        row = json.loads(reference.read_text().strip())
        first_quantity = next(iter(row["quantities"]))
        row["quantities"][first_quantity] = "changed"
        reference.write_text(json.dumps(row, sort_keys=True) + "\n")
        artifact = self.root / "comparison.json"
        artifact_payload = json.loads(artifact.read_text())
        artifact_payload["reference_ledger_sha256"] = file_sha256(reference)
        reference_evidence = self.root / "reference-evidence.json"
        evidence_payload = json.loads(reference_evidence.read_text())
        evidence_payload["reference_ledger_sha256"] = file_sha256(reference)
        reference_evidence.write_text(json.dumps(evidence_payload, sort_keys=True))
        artifact_payload["reference_evidence_sha256"] = file_sha256(
            reference_evidence
        )
        artifact.write_text(json.dumps(artifact_payload, sort_keys=True))
        manifest = json.loads(adjudication.read_text())
        manifest["evidence"][0]["reference_ledger_sha256"] = file_sha256(reference)
        manifest["evidence"][0]["reference_evidence_sha256"] = file_sha256(
            reference_evidence
        )
        manifest["evidence"][0]["artifact_sha256"] = file_sha256(artifact)
        adjudication.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "counts do not match retained ledgers"):
            write_retro_certificate(
                self.root / "certificate.json",
                [self.scan(partition)],
                generation_evidence=generation,
                adjudication_evidence=adjudication,
            )

    def test_verify_reopens_adjudication_artifact(self) -> None:
        partition = RawPartition("uniswap_v3", "swaps", DAY)
        write_gzip(self.path(partition), [v3_swap("a")])
        generation, adjudication = self.evidence_bundle(
            partition.source, partition.stream
        )
        output = self.root / "certificate.json"
        write_retro_certificate(
            output,
            [self.scan(partition)],
            generation_evidence=generation,
            adjudication_evidence=adjudication,
        )
        (self.root / "comparison.json").write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "artifact hash mismatch"):
            verify_retro_certificate(output, data_root=self.data)

    def test_verify_reopens_installed_raw_partition_hashes(self) -> None:
        partition = self.perimeter
        write_gzip(self.path(partition), [v3_swap("a")])
        generation, adjudication = self.evidence_bundle(
            partition.source, partition.stream
        )
        output = self.root / "certificate.json"
        write_retro_certificate(
            output,
            [self.scan(partition)],
            generation_evidence=generation,
            adjudication_evidence=adjudication,
        )
        write_gzip(self.path(partition), [v3_swap("b")])
        with self.assertRaisesRegex(ValueError, "installed raw partitions changed"):
            verify_retro_certificate(output, data_root=self.data)


if __name__ == "__main__":
    unittest.main()
