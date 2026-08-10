from __future__ import annotations

import hashlib
import json
import tempfile
import tracemalloc
import unittest
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from unittest.mock import patch

import pandas as pd

from ddvc.external_prices import (
    CandleRequest,
    coverage_summary,
    fetch_candle_request,
    fetch_raw_file,
    gap_audit_record,
    missing_candle_requests,
    panel_from_raw_files,
    plan_candle_requests,
    validate_external_weth_usd_release,
    validate_source_identity_body,
    validate_source_identity_file,
    validate_response_body,
    write_gap_audit,
    write_panel_from_raw_files,
)
from ddvc.prices import load_intraday_weth_usd_marks
from ddvc.fetch.coinbase_prices import read_raw_records
from ddvc.provenance import sidecar_path
from ddvc.fetch.raw import write_jsonl, write_jsonl_gz


def raw_record(request: CandleRequest, rows: list[list[object]]) -> dict[str, object]:
    body = json.dumps(rows)
    digest = hashlib.sha256(body.encode()).hexdigest()
    start = pd.Timestamp(request.start_utc, unit="s", tz="UTC").isoformat().replace("+00:00", "Z")
    end = pd.Timestamp(request.end_utc_inclusive, unit="s", tz="UTC").isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "source_id": "coinbase_exchange_eth_usd_spot_1m_close",
        "request_identity": request.identity,
        "request": {
            "method": "GET",
            "url": (
                "https://api.exchange.coinbase.com/products/ETH-USD/candles"
                f"?granularity=60&start={start}&end={end}"
            ),
            "product_id": "ETH-USD",
            "granularity_seconds": 60,
            "start_utc": request.start_utc,
            "end_utc_exclusive": request.end_utc_exclusive,
        },
        "fetched_at_utc": "2026-08-10T00:00:00+00:00",
        "response_headers": {"content-type": "application/json"},
        "response_body": body,
        "response_sha256": digest,
        "attempt_history": [{"attempt": 1, "started_at_utc": "2026-08-10T00:00:00+00:00", "status_code": 200, "response_sha256": digest}],
    }


def write_raw(path: Path, records: list[dict[str, object]]) -> None:
    writer = write_jsonl_gz if path.suffix == ".gz" else write_jsonl
    writer(path, records)


def write_source_identity(path: Path) -> None:
    body = json.dumps(
        {"id": "ETH-USD", "base_currency": "ETH", "quote_currency": "USD"}
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_id": "coinbase_exchange_eth_usd_spot_1m_close",
                "request": {
                    "method": "GET",
                    "url": "https://api.exchange.coinbase.com/products/ETH-USD",
                },
                "fetched_at_utc": "2026-08-10T00:00:00+00:00",
                "response_body": body,
                "response_sha256": hashlib.sha256(body.encode()).hexdigest(),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


class ExternalPriceTests(unittest.TestCase):
    def test_rate_limit_retry_preserves_attempt_history(self) -> None:
        request = CandleRequest(60, 120)
        body = json.dumps([[60, 1.0, 2.1, 1.1, 2.0, 3.0]])

        class Response:
            def __init__(self, status_code: int, text: str) -> None:
                self.status_code = status_code
                self.text = text
                self.content = text.encode("utf-8")
                self.headers = {"Retry-After": "0"}
                self.request = type(
                    "Prepared",
                    (),
                    {
                        "url": (
                            "https://api.exchange.coinbase.com/products/ETH-USD/candles"
                            "?granularity=60&start=1970-01-01T00%3A01%3A00Z"
                            "&end=1970-01-01T00%3A01%3A59Z"
                        )
                    },
                )()

        class Session:
            def __init__(self) -> None:
                self.responses = [Response(429, '{"message":"rate limit"}'), Response(200, body)]

            def get(self, *args, **kwargs):
                return self.responses.pop(0)

        with patch("ddvc.fetch.coinbase_prices.time.sleep"):
            record = fetch_candle_request(Session(), request, minimum_interval_seconds=0)
        self.assertEqual([item["status_code"] for item in record["attempt_history"]], [429, 200])
        self.assertEqual(record["response_sha256"], record["attempt_history"][-1]["response_sha256"])

    def test_source_identity_requires_eth_quoted_in_fiat_usd(self) -> None:
        valid = json.dumps({"id": "ETH-USD", "base_currency": "ETH", "quote_currency": "USD"})
        self.assertEqual(validate_source_identity_body(valid)["quote_currency"], "USD")
        tether = json.dumps({"id": "ETH-USDT", "base_currency": "ETH", "quote_currency": "USDT"})
        with self.assertRaisesRegex(ValueError, "ETH quoted in USD"):
            validate_source_identity_body(tether)

    def test_malformed_source_identity_file_fails_closed_with_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source_identity.json"
            path.write_text("[]\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source-identity digest mismatch"):
                validate_source_identity_file(path)

    def test_source_identity_rejects_non_string_response_body(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source_identity.json"
            write_source_identity(path)
            record = json.loads(path.read_text(encoding="utf-8"))
            record["response_body"] = {"id": "ETH-USD"}
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source-identity digest mismatch"):
                validate_source_identity_file(path)

    def test_planner_is_aligned_bounded_and_nonoverlapping(self) -> None:
        requests = plan_candle_requests(0, 601 * 60)
        self.assertEqual([r.end_utc_exclusive - r.start_utc for r in requests], [18_000, 18_000, 60])
        self.assertEqual(requests[0].start_utc, 0)
        self.assertEqual(requests[-1].end_utc_exclusive, 601 * 60)
        with self.assertRaisesRegex(ValueError, "minute boundaries"):
            plan_candle_requests(1, 61)
        with self.assertRaisesRegex(ValueError, "exact integer"):
            plan_candle_requests(0.5, 60)
        with self.assertRaisesRegex(ValueError, "exact integer"):
            plan_candle_requests(0, 60.5)

    def test_response_filters_provider_boundary_rows(self) -> None:
        request = CandleRequest(60, 180)
        rows = [[0, 1, 2, 1, 2, 1], [60, 1, 2, 1, 2, 1], [120, 2, 3, 2, 3, 1], [180, 3, 4, 3, 4, 1]]
        self.assertEqual([row[0] for row in validate_response_body(json.dumps(rows), request)], [60, 120])

    def test_response_rejects_fractional_timestamp_before_perimeter_filter(self) -> None:
        request = CandleRequest(60, 180)
        rows = [[0.5, 1, 2, 1, 2, 1], [60, 1, 2, 1, 2, 1]]
        with self.assertRaisesRegex(ValueError, "exact integer"):
            validate_response_body(json.dumps(rows), request)

    def test_raw_digest_tampering_fails_closed(self) -> None:
        request = CandleRequest(60, 120)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.jsonl"
            record = raw_record(request, [[60, 1, 2, 1, 2, 1]])
            record["response_sha256"] = "0" * 64
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid external-price raw evidence"):
                read_raw_records(path)

    def test_malformed_raw_record_fails_closed_with_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.jsonl"
            path.write_text("[]\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid external-price raw evidence"):
                read_raw_records(path)

    def test_raw_record_requires_string_body_and_exact_attempt_envelopes(self) -> None:
        request = CandleRequest(60, 120)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.jsonl"
            for mutation in ("body", "unknown_attempt_key", "missing_attempt_time", "nonsequential_attempt"):
                record = raw_record(request, [[60, 1, 2, 1, 2, 1]])
                if mutation == "body":
                    record["response_body"] = [[60, 1, 2, 1, 2, 1]]
                elif mutation == "unknown_attempt_key":
                    record["attempt_history"][0]["elapsed"] = 1
                elif mutation == "missing_attempt_time":
                    del record["attempt_history"][0]["started_at_utc"]
                else:
                    record["attempt_history"][0]["attempt"] = 2
                path.write_text(json.dumps(record) + "\n", encoding="utf-8")
                with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "invalid external-price raw evidence"):
                    read_raw_records(path)

    def test_raw_request_rejects_fractional_bounds_and_nonexact_query_schema(self) -> None:
        request = CandleRequest(60, 120)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.jsonl"
            fractional = raw_record(request, [[60, 1, 2, 1, 2, 1]])
            fractional["request"]["start_utc"] = 60.5
            path.write_text(json.dumps(fractional) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid external-price raw evidence"):
                read_raw_records(path)

            for mutation in ("unknown", "duplicate", "missing"):
                record = raw_record(request, [[60, 1, 2, 1, 2, 1]])
                parsed = urlparse(record["request"]["url"])
                pairs = parse_qsl(parsed.query, keep_blank_values=True)
                if mutation == "unknown":
                    pairs.append(("limit", "300"))
                elif mutation == "duplicate":
                    pairs.append(("start", pairs[1][1]))
                else:
                    pairs = [pair for pair in pairs if pair[0] != "end"]
                record["request"]["url"] = urlunparse(parsed._replace(query=urlencode(pairs)))
                path.write_text(json.dumps(record) + "\n", encoding="utf-8")
                with self.subTest(mutation=mutation), self.assertRaisesRegex(
                    ValueError,
                    "invalid external-price raw evidence",
                ):
                    read_raw_records(path)

    def test_torn_final_journal_resumes_but_corrupt_interior_fails(self) -> None:
        first = CandleRequest(0, 60)
        second = CandleRequest(60, 120)
        first_record = raw_record(first, [[0, 1, 2, 1, 2, 1]])
        second_record = raw_record(second, [[60, 2, 3, 2, 3, 1]])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resumed = root / "resumed.jsonl.gz"
            partial = resumed.with_suffix(resumed.suffix + ".partial")
            partial.write_bytes(
                (json.dumps(first_record, sort_keys=True, separators=(",", ":")) + "\n").encode()
                + b'{"request_identity":"torn'
            )
            with patch(
                "ddvc.fetch.coinbase_prices.fetch_candle_request",
                return_value=second_record,
            ) as fetch:
                fetch_raw_file(resumed, [first, second], session=object(), workers=1)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(
                [record["request_identity"] for record in read_raw_records(resumed)],
                [first.identity, second.identity],
            )

            corrupt = root / "corrupt.jsonl.gz"
            corrupt_partial = corrupt.with_suffix(corrupt.suffix + ".partial")
            corrupt_partial.write_text(
                json.dumps(first_record, sort_keys=True, separators=(",", ":"))
                + "\n{bad}\n"
                + json.dumps(second_record, sort_keys=True, separators=(",", ":"))
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid external-price raw evidence"):
                fetch_raw_file(corrupt, [first, second], session=object(), workers=1)

    def test_clean_and_resumed_fetches_are_byte_identical(self) -> None:
        first = CandleRequest(0, 60)
        second = CandleRequest(60, 120)
        records = {
            first.identity: raw_record(first, [[0, 1, 2, 1, 2, 1]]),
            second.identity: raw_record(second, [[60, 2, 3, 2, 3, 1]]),
        }

        def fixed_fetch(_session, request, **_kwargs):
            return records[request.identity]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clean = root / "clean.jsonl.gz"
            resumed = root / "resumed.jsonl.gz"
            partial = resumed.with_suffix(resumed.suffix + ".partial")
            partial.write_text(
                json.dumps(records[first.identity], sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            with patch(
                "ddvc.fetch.coinbase_prices.fetch_candle_request",
                side_effect=fixed_fetch,
            ):
                fetch_raw_file(clean, [first, second], session=object(), workers=1)
                fetch_raw_file(resumed, [first, second], session=object(), workers=1)
            self.assertEqual(clean.read_bytes(), resumed.read_bytes())

    def test_final_consolidation_never_uses_the_materializing_reader(self) -> None:
        requests = [CandleRequest(index * 60, (index + 1) * 60) for index in range(32)]

        def fixed_fetch(_session, request, **_kwargs):
            return raw_record(request, [[request.start_utc, 1, 2, 1, 2, 1]])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bounded.jsonl.gz"
            with patch("ddvc.fetch.coinbase_prices.fetch_candle_request", side_effect=fixed_fetch), patch("ddvc.fetch.coinbase_prices.read_raw_records", side_effect=AssertionError("materialized")):
                fetch_raw_file(path, requests, session=object(), workers=1)
            self.assertEqual(sum(1 for _record in read_raw_records(path)), len(requests))

    def test_final_raw_file_is_sorted_deterministically_and_workers_are_bounded(self) -> None:
        first = CandleRequest(0, 60)
        second = CandleRequest(60, 120)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.jsonl.gz"
            partial = path.with_suffix(path.suffix + ".partial")
            write_raw(
                partial,
                [
                    raw_record(second, [[60, 1, 2, 1, 2, 1]]),
                    raw_record(first, [[0, 1, 2, 1, 2, 1]]),
                ],
            )
            fetch_raw_file(path, [first, second], session=object(), workers=1)
            self.assertEqual(
                [row["request_identity"] for row in read_raw_records(path)],
                [first.identity, second.identity],
            )
            with self.assertRaisesRegex(ValueError, "between one and 3"):
                fetch_raw_file(Path(directory) / "too-many.jsonl.gz", [], workers=4)

    def test_gap_requery_is_retained_and_recovers_only_observed_minutes(self) -> None:
        base_request = CandleRequest(0, 180)
        gap_request = CandleRequest(60, 120)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "1970.jsonl.gz"
            gaps = root / "1970.gaps.jsonl.gz"
            audit = root / "1970.gap_audit.json"
            write_raw(
                base,
                [raw_record(base_request, [[0, 1, 2, 1, 2, 1], [120, 3, 4, 3, 4, 1]])],
            )
            self.assertEqual(
                list(missing_candle_requests([base], start_utc=0, end_utc_exclusive=180)),
                [gap_request],
            )
            write_raw(gaps, [raw_record(gap_request, [[60, 2, 3, 2, 3, 1]])])
            write_gap_audit(
                audit,
                base,
                gaps,
                start_utc=0,
                end_utc_exclusive=180,
            )
            panel = panel_from_raw_files(
                [base, gaps], start_utc=0, end_utc_exclusive=180
            )
            record = gap_audit_record(
                base,
                gaps,
                start_utc=0,
                end_utc_exclusive=180,
            )
        self.assertEqual(panel["bucket_start_utc"].tolist(), [0, 60, 120])
        self.assertEqual(record["first_pass_missing_minutes"], 1)
        self.assertEqual(record["recovered_minutes"], 1)
        self.assertEqual(record["unresolved_minutes"], 0)

    def test_gap_planning_memory_does_not_scale_with_observed_minutes(self) -> None:
        observations = 250_000

        def ordered_streams(*_args, **_kwargs):
            for bucket_start in range(0, observations * 60, 60):
                yield bucket_start, "raw", "0" * 64, [bucket_start, 1, 2, 1, 2, 1]

        with patch("ddvc.external_prices._ordered_candle_streams", side_effect=ordered_streams):
            tracemalloc.start()
            self.assertEqual(sum(1 for _request in missing_candle_requests([], start_utc=0, end_utc_exclusive=observations * 60)), 0)
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        self.assertLess(peak, 2_000_000)

    def test_gap_identity_audit_is_streaming(self) -> None:
        requests = 200_000
        base = Path("base")
        reconciliation = Path("reconciliation")

        def missing(paths, **_kwargs):
            if paths == [base]:
                return (CandleRequest(index * 60, (index + 1) * 60) for index in range(requests))
            return iter(())

        def raw_records(_path, **_kwargs):
            return ({"request_identity": CandleRequest(index * 60, (index + 1) * 60).identity} for index in range(requests))

        with patch("ddvc.external_prices.missing_candle_requests", side_effect=missing), patch("ddvc.external_prices.iter_raw_records", side_effect=raw_records):
            tracemalloc.start()
            record = gap_audit_record(base, reconciliation, start_utc=0, end_utc_exclusive=requests * 60)
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        self.assertEqual(record["gap_request_count"], requests)
        self.assertEqual(record["first_pass_missing_minutes"], requests)
        self.assertLess(peak, 2_000_000)

    def test_panel_carries_availability_and_source_evidence(self) -> None:
        request = CandleRequest(60, 180)
        rows = [[60, 1.0, 2.1, 1.1, 2.0, 3.0], [120, 2.0, 3.1, 2.1, 3.0, 4.0]]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.jsonl"
            path.write_text(json.dumps(raw_record(request, rows)) + "\n", encoding="utf-8")
            panel = panel_from_raw_files([path], start_utc=60, end_utc_exclusive=180)
        self.assertEqual(panel["available_at_utc"].tolist(), [120, 180])
        self.assertEqual(panel["weth_usd"].tolist(), [2.0, 3.0])
        self.assertTrue(panel["price_source"].eq("coinbase_exchange_eth_usd_spot_1m_close").all())
        self.assertTrue(panel["raw_response_sha256"].str.fullmatch("[0-9a-f]{64}").all())

    def test_streaming_writer_and_filtered_loader_preserve_causal_perimeter(self) -> None:
        request = CandleRequest(60, 240)
        rows = [
            [60, 1.0, 2.1, 1.1, 2.0, 3.0],
            [120, 2.0, 3.1, 2.1, 3.0, 4.0],
            [180, 3.0, 4.1, 3.1, 4.0, 5.0],
        ]
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.jsonl"
            output = Path(directory) / "panel.parquet"
            raw.write_text(json.dumps(raw_record(request, rows)) + "\n", encoding="utf-8")
            coverage = write_panel_from_raw_files(
                [raw], output, start_utc=60, end_utc_exclusive=240
            )
            loaded = load_intraday_weth_usd_marks(
                output, pd.DataFrame({"timestamp_utc": [181]})
            )
        self.assertEqual(coverage["observed_minutes"], 3)
        self.assertEqual(coverage["missing_minutes"], 0)
        self.assertEqual(loaded["available_at_utc"].tolist(), [180])

    def test_streaming_writer_serializes_gap_boundaries_as_native_integers(self) -> None:
        request = CandleRequest(0, 180)
        rows = [
            [0, 1.0, 2.1, 1.1, 2.0, 3.0],
            [120, 3.0, 4.1, 3.1, 4.0, 5.0],
        ]
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.jsonl"
            output = Path(directory) / "panel.parquet"
            raw.write_text(json.dumps(raw_record(request, rows)) + "\n", encoding="utf-8")
            coverage = write_panel_from_raw_files(
                [raw],
                output,
                start_utc=0,
                end_utc_exclusive=180,
                code_sources=["tests/test_external_prices.py"],
            )
            provenance = json.loads(sidecar_path(output).read_text(encoding="utf-8"))

        self.assertEqual(coverage["first_missing_utc"], 60)
        self.assertEqual(coverage["last_missing_utc"], 60)
        self.assertIn('"first_missing_utc": 60', provenance["notes"])

    def test_external_builder_preserves_prior_pair_on_stamp_or_lineage_failure(self) -> None:
        request = CandleRequest(60, 180)
        rows = [[60, 1.0, 2.1, 1.1, 2.0, 3.0], [120, 2.0, 3.1, 2.1, 3.0, 4.0]]
        for failure_target, message in (("ddvc.tables.prepare_stamp", "stamp failed"), ("ddvc.external_prices.validate_panel_raw_lineage", "lineage failed")):
            with self.subTest(failure_target=failure_target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                raw = root / "raw.jsonl"
                output = root / "panel.parquet"
                raw.write_text(json.dumps(raw_record(request, rows)) + "\n", encoding="utf-8")
                pd.DataFrame({"prior": [1]}).to_parquet(output, index=False)
                prior = output.read_bytes()
                sidecar = sidecar_path(output)
                sidecar.write_bytes(b"prior-sidecar\n")
                with patch(failure_target, side_effect=RuntimeError(message)), self.assertRaisesRegex(RuntimeError, message):
                    write_panel_from_raw_files([raw], output, start_utc=60, end_utc_exclusive=180, code_sources=["tests/test_external_prices.py"])
                self.assertEqual(output.read_bytes(), prior)
                self.assertEqual(sidecar.read_bytes(), b"prior-sidecar\n")
                self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_external_builder_validates_full_gap_audit_before_install(self) -> None:
        request = CandleRequest(0, 180)
        rows = [[0, 1.0, 2.1, 1.1, 2.0, 3.0], [60, 2.0, 3.1, 2.1, 3.0, 4.0], [120, 3.0, 4.1, 3.1, 4.0, 5.0]]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "1970.jsonl.gz"
            gaps = root / "1970.gaps.jsonl.gz"
            audit = root / "1970.gap_audit.json"
            output = root / "panel.parquet"
            write_source_identity(root / "source_identity.json")
            write_raw(base, [raw_record(request, rows)])
            write_raw(gaps, [])
            write_gap_audit(audit, base, gaps, start_utc=0, end_utc_exclusive=180)
            audit.write_text('{"stale":true}\n', encoding="utf-8")
            pd.DataFrame({"prior": [1]}).to_parquet(output, index=False)
            prior = output.read_bytes()
            sidecar = sidecar_path(output)
            sidecar.write_bytes(b"prior-sidecar\n")
            with self.assertRaisesRegex(ValueError, "gap audit is stale"):
                write_panel_from_raw_files([base, gaps], output, start_utc=0, end_utc_exclusive=180, code_sources=["tests/test_external_prices.py"], raw_root=root)
            self.assertEqual(output.read_bytes(), prior)
            self.assertEqual(sidecar.read_bytes(), b"prior-sidecar\n")

    def test_coverage_reports_gaps_without_filling_them(self) -> None:
        panel = pd.DataFrame({"bucket_start_utc": [0, 120]})
        result = coverage_summary(panel, start_utc=0, end_utc_exclusive=180)
        self.assertEqual(result["expected_minutes"], 3)
        self.assertEqual(result["missing_minutes"], 1)
        self.assertEqual(result["first_missing_utc"], 60)
        self.assertFalse(result["full_minute_lattice"])

    def test_release_validator_reopens_raw_lineage_and_rejects_panel_tampering(self) -> None:
        request = CandleRequest(0, 180)
        rows = [
            [0, 1.0, 2.1, 1.1, 2.0, 3.0],
            [60, 2.0, 3.1, 2.1, 3.0, 4.0],
            [120, 3.0, 4.1, 3.1, 4.0, 5.0],
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "1970.jsonl.gz"
            gaps = root / "1970.gaps.jsonl.gz"
            audit = root / "1970.gap_audit.json"
            panel_path = root / "panel.parquet"
            write_source_identity(root / "source_identity.json")
            write_raw(base, [raw_record(request, rows)])
            write_raw(gaps, [])
            write_gap_audit(
                audit,
                base,
                gaps,
                start_utc=0,
                end_utc_exclusive=180,
            )
            write_panel_from_raw_files(
                [base, gaps], panel_path, start_utc=0, end_utc_exclusive=180
            )
            with patch("ddvc.provenance.require_current_artifacts"):
                release = validate_external_weth_usd_release(
                    panel_path,
                    root,
                    start_utc=0,
                    end_utc_exclusive=180,
                )
            self.assertEqual(release["rows"], 3)
            panel = pd.read_parquet(panel_path)
            panel.loc[1, "weth_usd"] = 99.0
            panel.to_parquet(panel_path, index=False)
            with (
                patch("ddvc.provenance.require_current_artifacts"),
                self.assertRaisesRegex(ValueError, "lineage differs"),
            ):
                validate_external_weth_usd_release(
                    panel_path,
                    root,
                    start_utc=0,
                    end_utc_exclusive=180,
                )


if __name__ == "__main__":
    unittest.main()
