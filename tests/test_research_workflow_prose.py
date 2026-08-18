from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_readme_maps_the_direct_scientific_workflow() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for stage in ("scripts/fetch/", "scripts/process/", "scripts/analyze/", "scripts/plot/", "scripts/tabulate/"):
        assert stage in text
    assert "data/raw/" in text
    assert "data/processed/" in text
    assert "output/exhibits/" in text
    assert "paper/ and deck/" in text


def test_script_readme_requires_one_owner_and_current_consumer() -> None:
    text = (ROOT / "scripts" / "README.md").read_text(encoding="utf-8")
    assert "Every retained derived file needs both a producer" in text
    assert "current paper, deck, test, verification, or findings consumer" in text
