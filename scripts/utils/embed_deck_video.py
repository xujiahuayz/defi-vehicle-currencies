#!/usr/bin/env python3
"""Embed the deck's MP4 in its PDF as an Acrobat RichMedia annotation.

LaTeX leaves a ``run:`` link over the poster image.  That link is only a build
marker: this script takes its rectangle, removes every external file-launch
action for the film, and embeds the MP4 bytes directly in the PDF.  Adobe
Acrobat can then play the film inside the poster rectangle.  Readers without
RichMedia support retain the static poster.

The PDF structure follows the working GBA lecture-deck implementation and ISO
32000's RichMedia annotation model.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PDF = ROOT / "deck/main.pdf"
DEFAULT_MP4 = ROOT / "output/figures/vehicle_dominance_timelapse.mp4"


@dataclass(frozen=True)
class VideoEmbeddingReport:
    richmedia_annotations: int
    launch_actions: int
    uri_actions: int
    embedded_file_size: int | None
    pages: tuple[int, ...]


def _matches_media(value: object, media_name: str) -> bool:
    text = str(value).replace("\\", "/")
    return text == media_name or text.endswith(f"/{media_name}")


def _launch_target(annotation) -> str | None:
    action = annotation.get(Name.A)
    if action is None or action.get(Name.S) != Name.Launch:
        return None
    target = action.get(Name.F)
    if target is None:
        return None
    if isinstance(target, Dictionary):
        target = target.get(Name.UF) or target.get(Name.F)
    return None if target is None else str(target)


def _uri_target(annotation) -> str | None:
    action = annotation.get(Name.A)
    if action is None or action.get(Name.S) != Name.URI:
        return None
    target = action.get(Name.URI)
    return None if target is None else str(target)


def _richmedia_files(annotation) -> list[tuple[str, object]]:
    if annotation.get(Name.Subtype) != Name.RichMedia:
        return []
    content = annotation.get(Name.RichMediaContent)
    if content is None:
        return []
    assets = content.get(Name.Assets)
    if assets is None:
        return []
    names = assets.get(Name.Names)
    if names is None:
        return []
    return [(str(names[i]), names[i + 1]) for i in range(0, len(names) - 1, 2)]


def _contains_media(annotation, media_name: str) -> bool:
    return any(_matches_media(name, media_name) for name, _filespec in _richmedia_files(annotation))


def _rect(annotation) -> tuple[float, float, float, float]:
    values = annotation.get(Name.Rect)
    if values is None or len(values) != 4:
        raise ValueError("the deck video build marker has no four-coordinate rectangle")
    return tuple(float(value) for value in values)  # type: ignore[return-value]


def _rect_area(rect: tuple[float, float, float, float]) -> float:
    left, bottom, right, top = rect
    return max(0.0, right - left) * max(0.0, top - bottom)


def _build_richmedia_annotation(
    pdf: pikepdf.Pdf,
    mp4_path: Path,
    rect: tuple[float, float, float, float],
):
    """Construct one in-place video annotation with an embedded MP4 asset."""
    embedded_file = pdf.make_stream(mp4_path.read_bytes(), Type=Name.EmbeddedFile)
    embedded_file.stream_dict[Name.Params] = Dictionary(Size=mp4_path.stat().st_size)

    filename = mp4_path.name
    filespec = Dictionary(
        Type=Name.Filespec,
        F=filename,
        UF=filename,
        EF=Dictionary(F=embedded_file),
    )
    instance = Dictionary(
        Type=Name.RichMediaInstance,
        Subtype=Name.Video,
        Asset=filespec,
    )
    configuration = Dictionary(
        Type=Name.RichMediaConfiguration,
        Subtype=Name.Video,
        Instances=Array([instance]),
    )
    content = Dictionary(
        Type=Name.RichMediaContent,
        Assets=Dictionary(Names=Array([filename, filespec])),
        Configurations=Array([configuration]),
    )
    settings = Dictionary(
        Type=Name.RichMediaSettings,
        Activation=Dictionary(
            Condition=Name.PV,
            Presentation=Dictionary(
                Type=Name.RichMediaPresentation,
                Style=Name.Embedded,
            ),
        ),
        Deactivation=Dictionary(Condition=Name.PI),
    )
    annotation = Dictionary(
        Type=Name.Annot,
        Subtype=Name.RichMedia,
        Rect=Array([round(value, 2) for value in rect]),
        Border=Array([0, 0, 0]),
        F=4,
        RichMediaContent=content,
        RichMediaSettings=settings,
    )
    return pdf.make_indirect(annotation)


def inspect_deck_video(
    pdf_path: Path | str = DEFAULT_PDF,
    mp4_path: Path | str = DEFAULT_MP4,
) -> VideoEmbeddingReport:
    """Report whether the PDF carries one self-contained copy of the film."""
    pdf_path = Path(pdf_path).resolve()
    mp4_path = Path(mp4_path).resolve()
    media_name = mp4_path.name
    source_bytes = mp4_path.read_bytes()
    richmedia = 0
    launches = 0
    uris = 0
    embedded_size: int | None = None
    pages: list[int] = []

    with pikepdf.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for annotation in page.obj.get(Name.Annots, []):
                launch = _launch_target(annotation)
                if launch is not None and _matches_media(launch, media_name):
                    launches += 1
                uri = _uri_target(annotation)
                if uri is not None and media_name in uri:
                    uris += 1
                for name, filespec in _richmedia_files(annotation):
                    if not _matches_media(name, media_name):
                        continue
                    richmedia += 1
                    pages.append(page_number)
                    stream = filespec.get(Name.EF).get(Name.F)
                    embedded_bytes = stream.read_bytes()
                    size = len(embedded_bytes)
                    declared = stream.get(Name.Params).get(Name.Size)
                    if declared is None or int(declared) != size:
                        raise ValueError(
                            f"embedded {media_name} declares {declared} bytes but contains {size}"
                        )
                    if embedded_bytes != source_bytes:
                        raise ValueError(
                            f"embedded {media_name} differs from the source MP4"
                        )
                    embedded_size = size

    return VideoEmbeddingReport(
        richmedia_annotations=richmedia,
        launch_actions=launches,
        uri_actions=uris,
        embedded_file_size=embedded_size,
        pages=tuple(pages),
    )


def embed_deck_video(
    pdf_path: Path | str = DEFAULT_PDF,
    mp4_path: Path | str = DEFAULT_MP4,
) -> VideoEmbeddingReport:
    """Replace the LaTeX launch marker with a self-contained video annotation."""
    pdf_path = Path(pdf_path).resolve()
    mp4_path = Path(mp4_path).resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"deck PDF is missing: {pdf_path}")
    if not mp4_path.is_file():
        raise FileNotFoundError(f"deck film is missing: {mp4_path}")

    media_name = mp4_path.name
    markers: list[tuple[int, tuple[float, float, float, float]]] = []

    pdf = pikepdf.open(pdf_path, allow_overwriting_input=True)
    try:
        for page_index, page in enumerate(pdf.pages):
            kept = Array()
            for annotation in page.obj.get(Name.Annots, []):
                launch = _launch_target(annotation)
                if launch is not None and _matches_media(launch, media_name):
                    markers.append((page_index, _rect(annotation)))
                    continue
                if _contains_media(annotation, media_name):
                    continue
                kept.append(annotation)
            page.obj[Name.Annots] = kept

        if not markers:
            current = inspect_deck_video(pdf_path, mp4_path)
            if (
                current.richmedia_annotations == 1
                and current.launch_actions == 0
                and current.uri_actions == 0
                and current.embedded_file_size == mp4_path.stat().st_size
            ):
                return current
            raise ValueError(
                "no LaTeX run-link marker was found for the deck film; rebuild the deck "
                "from main.tex before embedding"
            )

        target_page, target_rect = max(markers, key=lambda item: _rect_area(item[1]))
        annotation = _build_richmedia_annotation(pdf, mp4_path, target_rect)
        page = pdf.pages[target_page]
        page.obj[Name.Annots].append(annotation)
        pdf.save(pdf_path)
    finally:
        pdf.close()

    report = inspect_deck_video(pdf_path, mp4_path)
    expected_size = mp4_path.stat().st_size
    if report != VideoEmbeddingReport(1, 0, 0, expected_size, (target_page + 1,)):
        raise ValueError(f"deck film embedding verification failed: {report}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--mp4", type=Path, default=DEFAULT_MP4)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="inspect the compiled PDF without rewriting it",
    )
    args = parser.parse_args()
    report = (
        inspect_deck_video(args.pdf, args.mp4)
        if args.verify_only
        else embed_deck_video(args.pdf, args.mp4)
    )
    expected = args.mp4.resolve().stat().st_size
    valid = report == VideoEmbeddingReport(1, 0, 0, expected, report.pages)
    print(
        f"RichMedia={report.richmedia_annotations} "
        f"Launch={report.launch_actions} URI={report.uri_actions} "
        f"embedded_bytes={report.embedded_file_size} pages={report.pages}"
    )
    return 0 if valid and len(report.pages) == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
