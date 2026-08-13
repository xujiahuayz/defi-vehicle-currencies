from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ddvc.latex_text import included_section_files, strip_latex_markup


class LatexTextTest(unittest.TestCase):
    def test_included_sections_follow_the_compiled_input_graph(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sections = root / "sections"
            sections.mkdir()
            (sections / "kept.tex").write_text("kept")
            (sections / "retired.tex").write_text("retired")
            main = root / "main.tex"
            main.write_text(r"\input{sections/kept}")
            self.assertEqual(included_section_files(main), (sections / "kept.tex",))

    def test_environment_names_and_source_keys_do_not_become_prose(self) -> None:
        source = r"""
        \begin{frame}
        \frametitle{A visible heading}
        \begin{itemize}
        \item Visible prose with \emph{emphasis} and \citep{Author2024}.
        \end{itemize}
        \label{sec:hidden-source-key}
        \end{frame}
        """
        text = strip_latex_markup(source)
        self.assertIn("Visible prose with emphasis", text)
        for hidden in ("frame", "frametitle", "itemize", "item", "Author2024", "hidden-source-key"):
            self.assertNotIn(hidden, text)

    def test_non_prose_environments_and_math_are_removed(self) -> None:
        source = r"""
        Kept sentence.
        \begin{table}\begin{tabular}{ll}column & route\\\end{tabular}\end{table}
        The value is $m_{it}=1$ and appears in \eqref{eq:state}.
        """
        text = strip_latex_markup(source)
        self.assertIn("Kept sentence", text)
        self.assertIn("The value is x and appears in 1", text)
        self.assertNotIn("column", text)
        self.assertNotIn("route", text)
