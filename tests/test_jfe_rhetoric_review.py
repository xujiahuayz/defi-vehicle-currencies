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


class OpeningReviewTests(unittest.TestCase):
    def opening(self, heading: str) -> dict:
        return {
            "heading": heading,
            "classification": "direct",
            "incoming_object": "The observed route from the preceding section.",
            "opening_function": "Defines the next economic quantity.",
            "judgment": "The opening begins with the object rather than the document.",
            "raw_exemplar": "source.txt:1-2",
        }

    def test_every_heading_must_be_enumerated_in_source_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "section.tex"
            path.write_text(
                "\\section{Main}\nText.\n\\subsection{Next}\nText.\n",
                encoding="utf-8",
            )
            (ROOT / "source.txt").write_text("raw\npassage\n", encoding="utf-8")
            try:
                row = {"openings": [self.opening("Main")]}
                errors = CHECKER.opening_review_errors("section.tex", row, path)
                self.assertTrue(any("coverage differs" in error for error in errors))

                row["openings"].append(self.opening("Next"))
                self.assertEqual(CHECKER.opening_review_errors("section.tex", row, path), [])
            finally:
                (ROOT / "source.txt").unlink(missing_ok=True)

    def test_opening_review_records_function_not_stock_wording(self) -> None:
        source = CHECKER.opening_review_errors.__doc__.lower()
        self.assertIn("enumeration", source)
        self.assertNotIn("section 2 describes", source)


class ConclusionReviewTests(unittest.TestCase):
    def test_conclusion_must_record_economic_ending(self) -> None:
        row = {
            "conclusion_review": {
                "synthesis": "Moves from the route result to market formation.",
                "economic_consequence": "Fixed-market models explain only one margin.",
                "scope_condition": "Routes alone do not distinguish the mechanisms.",
                "final_sentence_function": "Ends on the economic contribution.",
                "raw_exemplars": [
                    "literature/text/2023-LiYeZheng2023Refusing-refusing-the-best-price.txt:1848-1924"
                ],
            }
        }
        self.assertEqual(CHECKER.conclusion_review_errors("07-conclusion.tex", row), [])
        del row["conclusion_review"]["final_sentence_function"]
        errors = CHECKER.conclusion_review_errors("07-conclusion.tex", row)
        self.assertEqual(errors, ["missing conclusion final sentence function: 07-conclusion.tex"])


class ParagraphFlowReviewTests(unittest.TestCase):
    @staticmethod
    def handoff(line: int) -> dict:
        return {
            "line": line,
            "inherited_object": "The economic object established in the preceding paragraph.",
            "paragraph_function": "Develops the next comparison using that object.",
            "relation_to_previous": "Narrows the preceding claim to the relevant comparison.",
            "economic_subject": "Trading reallocates across endpoint markets.",
            "framing_judgment": "The supported economic result leads and its scope follows.",
            "qualification_leads": False,
            "judgment": "The transition is explicit and economically continuous.",
        }

    def test_review_must_cover_every_substantive_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "section.tex"
            path.write_text(
                "First paragraph carries enough words to count as substantive prose and ends "
                "with a complete sentence for the reader who follows the full economic argument.\n\n"
                "Second paragraph carries the first object into a new economic comparison and "
                "also ends with a complete sentence for the reader who follows the full argument.\n\n"
                "Third paragraph states the implication of that comparison in enough words to "
                "remain part of the reviewed manuscript prose and its complete economic argument.\n",
                encoding="utf-8",
            )
            row = {
                "paragraph_flow_review": {
                    "transition_lines": [3],
                    "handoffs": [self.handoff(3)],
                    "judgment": "Every handoff was read in sequence.",
                    "raw_exemplars": [
                        "literature/text/2023-LiYeZheng2023Refusing-refusing-the-best-price.txt:980-990"
                    ],
                    "jumps": [],
                }
            }
            errors = CHECKER.paragraph_flow_errors("section.tex", row, path)
            self.assertTrue(any("coverage differs" in error for error in errors))
            row["paragraph_flow_review"]["transition_lines"] = [3, 5]
            row["paragraph_flow_review"]["handoffs"] = [self.handoff(3), self.handoff(5)]
            self.assertEqual(CHECKER.paragraph_flow_errors("section.tex", row, path), [])

    def test_jump_inventory_requires_issue_and_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "section.tex"
            path.write_text(
                "First paragraph carries enough words to count as substantive prose and ends "
                "with a complete sentence for the reader who follows the full economic argument.\n"
                "Second paragraph carries the first object into a new economic comparison and "
                "also ends with a complete sentence for the reader who follows the full argument.\n",
                encoding="utf-8",
            )
            row = {
                "paragraph_flow_review": {
                    "transition_lines": [2],
                    "handoffs": [self.handoff(2)],
                    "judgment": "The handoff was reviewed.",
                    "raw_exemplars": [
                        "literature/text/2023-LiYeZheng2023Refusing-refusing-the-best-price.txt:980-990"
                    ],
                    "jumps": [{"line": 2, "issue": "The inherited object was absent."}],
                }
            }
            errors = CHECKER.paragraph_flow_errors("section.tex", row, path)
            self.assertEqual(errors, ["missing resolution: section.tex jumps[1]"])

    def test_each_handoff_requires_its_own_economic_judgment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "section.tex"
            path.write_text(
                "First paragraph establishes the economic object in enough words to count as "
                "substantive prose and ends with a complete sentence for the reader.\n"
                "Second paragraph changes the argument in enough words to count as substantive "
                "prose and ends with a complete sentence for the reader.\n",
                encoding="utf-8",
            )
            handoff = self.handoff(2)
            del handoff["relation_to_previous"]
            row = {
                "paragraph_flow_review": {
                    "transition_lines": [2],
                    "handoffs": [handoff],
                    "judgment": "The section was read.",
                    "raw_exemplars": [
                        "literature/text/2023-LiYeZheng2023Refusing-refusing-the-best-price.txt:980-990"
                    ],
                    "jumps": [],
                }
            }
            errors = CHECKER.paragraph_flow_errors("section.tex", row, path)
            self.assertEqual(
                errors,
                ["missing relation to previous: section.tex handoffs[1]"],
            )

    def test_qualification_may_lead_only_with_editorial_justification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "section.tex"
            path.write_text(
                "First paragraph establishes the economic result in enough words to count as "
                "substantive prose and ends with a complete sentence for the reader.\n"
                "Second paragraph explains the design boundary in enough words to count as "
                "substantive prose and ends with a complete sentence for the reader.\n",
                encoding="utf-8",
            )
            handoff = self.handoff(2)
            handoff["qualification_leads"] = True
            row = {
                "paragraph_flow_review": {
                    "transition_lines": [2],
                    "handoffs": [handoff],
                    "judgment": "The section was read.",
                    "raw_exemplars": [
                        "literature/text/2023-LiYeZheng2023Refusing-refusing-the-best-price.txt:980-990"
                    ],
                    "jumps": [],
                }
            }
            errors = CHECKER.paragraph_flow_errors("section.tex", row, path)
            self.assertEqual(
                errors,
                ["qualification leads without justification: section.tex handoffs[1]"],
            )
            handoff["qualification_leads_justification"] = (
                "The paragraph defines the support on which the following estimate exists."
            )
            self.assertEqual(CHECKER.paragraph_flow_errors("section.tex", row, path), [])


if __name__ == "__main__":
    unittest.main()
