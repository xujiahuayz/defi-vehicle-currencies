from __future__ import annotations

from pathlib import Path
import shutil
import tempfile

import pandas as pd
import pytest

from ddvc.artifact_release import file_sha256
from ddvc.model_artifacts import ModelArtifactContext, require_released_model_inputs
from ddvc.paths import REPO_ROOT
from ddvc.provenance import portable_content_sha256, sidecar_path, stamp


def _record(path: Path) -> dict[str, object]:
    provenance = sidecar_path(path)
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "content_sha256": portable_content_sha256(path),
        "provenance_path": provenance.relative_to(REPO_ROOT).as_posix(),
        "provenance_sha256": file_sha256(provenance),
    }


def _context(path: Path, record: dict[str, object] | None) -> ModelArtifactContext:
    relative = path.relative_to(REPO_ROOT).as_posix()
    return ModelArtifactContext(
        d3_generation="a" * 64,
        d3_certificate_relative="certificate.json",
        d3_certificate_path=REPO_ROOT / "certificate.json",
        d3_certificate_bytes=0,
        d3_certificate_sha256="b" * 64,
        d3_certificate_provenance_path=REPO_ROOT / "certificate.json.prov.json",
        d3_certificate_provenance_sha256="c" * 64,
        d3_input_relatives=frozenset({relative}),
        d3_input_records={} if record is None else {relative: record},
    )


def test_ordinary_d3_input_requires_and_matches_exact_record() -> None:
    with tempfile.TemporaryDirectory(prefix="model-input-", dir=REPO_ROOT) as raw:
        directory = Path(raw)
        source = directory / "source.parquet"
        pd.DataFrame({"value": [1]}).to_parquet(source, index=False)
        stamp(source, code_sources=["tests/test_model_artifacts.py"], inputs=[])
        try:
            with require_released_model_inputs(
                _context(source, _record(source)),
                [source],
                root=REPO_ROOT,
                consumer="ordinary identity test",
            ) as leased:
                assert leased == [source.resolve()]
            with pytest.raises(ValueError, match="lacks an exact D3 identity record"):
                with require_released_model_inputs(
                    _context(source, None),
                    [source],
                    root=REPO_ROOT,
                    consumer="ordinary identity test",
                ):
                    pass
        finally:
            manifest = REPO_ROOT / "data/manifests" / directory.relative_to(REPO_ROOT)
            shutil.rmtree(manifest, ignore_errors=True)


def test_ordinary_d3_rebuild_between_context_and_lease_fails() -> None:
    with tempfile.TemporaryDirectory(prefix="model-rebuild-", dir=REPO_ROOT) as raw:
        directory = Path(raw)
        source = directory / "source.parquet"
        pd.DataFrame({"value": [1]}).to_parquet(source, index=False)
        stamp(source, code_sources=["tests/test_model_artifacts.py"], inputs=[])
        context = _context(source, _record(source))
        pd.DataFrame({"value": [2]}).to_parquet(source, index=False)
        stamp(source, code_sources=["tests/test_model_artifacts.py"], inputs=[])
        try:
            with pytest.raises(ValueError, match="differs from its bound D3 identity"):
                with require_released_model_inputs(
                    context,
                    [source],
                    root=REPO_ROOT,
                    consumer="ordinary rebuild test",
                ):
                    pass
        finally:
            manifest = REPO_ROOT / "data/manifests" / directory.relative_to(REPO_ROOT)
            shutil.rmtree(manifest, ignore_errors=True)
