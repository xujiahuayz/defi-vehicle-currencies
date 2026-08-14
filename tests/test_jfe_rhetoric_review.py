from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_jfe_rhetoric_review.py"

SPEC = importlib.util.spec_from_file_location("check_jfe_rhetoric_review", SCRIPT)
assert SPEC and SPEC.loader
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def passage_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AnecdoteAnalogyReviewTests(unittest.TestCase):
    def review(self, source_hash: str) -> dict:
        common = {
            "source": "source.txt",
            "line_start": 2,
            "line_end": 3,
            "sha256": source_hash,
            "kind": "named case",
            "rhetorical_job": "Makes the economic object concrete.",
            "handoff": "Moves from the case to the population test.",
        }
        return {
            "anecdote_analogy_review": {
                "precedents": [{
                    **common,
                    "paper_page_section": "page 1, introduction",
                    "placement": "introduction",
                    "draft_relevance": "The case reveals the measured object.",
                }],
                "draft_uses": [{**common, "judgment": "The case earns its place."}],
            }
        }

    def test_review_is_invalidated_when_reviewed_passage_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "source.txt"
            path.write_text("outside\nreviewed one\nreviewed two\noutside\n", encoding="utf-8")
            expected = passage_hash("reviewed one\nreviewed two\n")
            review = self.review(expected)
            self.assertEqual(CHECKER.anecdote_analogy_errors(review, root), [])

            path.write_text("outside\nreviewed one\nchanged\noutside\n", encoding="utf-8")
            errors = CHECKER.anecdote_analogy_errors(review, root)
            self.assertTrue(any("stale anecdote/analogy review" in error for error in errors))

    def test_review_requires_rhetorical_job_and_handoff_not_a_length_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.txt").write_text(
                "outside\nreviewed one\nreviewed two\noutside\n", encoding="utf-8"
            )
            expected = passage_hash("reviewed one\nreviewed two\n")
            review = self.review(expected)
            del review["anecdote_analogy_review"]["draft_uses"][0]["handoff"]
            errors = CHECKER.anecdote_analogy_errors(review, root)
            self.assertTrue(any("missing handoff" in error for error in errors))
            serialized = str(review).lower()
            self.assertNotIn("word_count", serialized)
            self.assertNotIn("target_length", serialized)


class TransitionReviewTests(unittest.TestCase):
    def test_review_requires_all_three_scientific_handoffs(self) -> None:
        row = {
            "entry_handoff": "The observed route motivates the measure.",
            "internal_progression": "The section moves from counts to values.",
            "exit_handoff": "The allocation result motivates mechanism tests.",
        }
        self.assertEqual(CHECKER.transition_review_errors("section.tex", row), [])
        del row["internal_progression"]
        errors = CHECKER.transition_review_errors("section.tex", row)
        self.assertEqual(errors, ["missing internal progression: section.tex"])

    def test_transition_review_does_not_encode_stock_connectives(self) -> None:
        source = CHECKER.transition_review_errors.__doc__.lower()
        self.assertNotIn("however", source)
        self.assertNotIn("therefore", source)


if __name__ == "__main__":
    unittest.main()
