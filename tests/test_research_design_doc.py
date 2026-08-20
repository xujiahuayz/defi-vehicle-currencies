from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "docs" / "research" / "design.md"


def test_current_design_names_the_two_paper_claim_families() -> None:
    text = DESIGN.read_text(encoding="utf-8")
    assert "Vehicle-role rotation" in text
    assert "V2 deposited-capital predictability" in text
    assert "Supporting routing analyses" in text


def test_design_uses_endpoint_pair_leg_and_route_vocabulary() -> None:
    text = DESIGN.read_text(encoding="utf-8")
    assert "endpoint pair" in text
    assert "legs" in text
    assert "route" in text
    assert "ultimate pair" not in text
    assert "atomic pair" not in text


def test_design_preserves_identification_boundaries() -> None:
    text = DESIGN.read_text(encoding="utf-8").lower()
    assert "descriptive" in text
    assert "not causal feedback" in text
    assert "calendar time is not a treatment" in text
