from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name

from scripts.utils.embed_deck_video import (
    VideoEmbeddingReport,
    embed_deck_video,
    inspect_deck_video,
)


def _write_pdf_with_video_markers(pdf_path: Path, media_name: str) -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(400, 300))
    markers = []
    for rect in ([20, 40, 360, 250], [150, 12, 250, 32]):
        marker = Dictionary(
            Type=Name.Annot,
            Subtype=Name.Link,
            Rect=Array(rect),
            A=Dictionary(S=Name.Launch, F=f"../output/figures/{media_name}"),
        )
        markers.append(pdf.make_indirect(marker))
    page.obj[Name.Annots] = Array(markers)
    pdf.save(pdf_path)


def test_embed_deck_video_replaces_launch_markers_and_is_idempotent(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "deck.pdf"
    mp4_path = tmp_path / "film.mp4"
    mp4_path.write_bytes(b"synthetic MP4 payload")
    _write_pdf_with_video_markers(pdf_path, mp4_path.name)

    expected = VideoEmbeddingReport(
        richmedia_annotations=1,
        launch_actions=0,
        uri_actions=0,
        embedded_file_size=mp4_path.stat().st_size,
        pages=(1,),
    )
    assert embed_deck_video(pdf_path, mp4_path) == expected
    assert inspect_deck_video(pdf_path, mp4_path) == expected
    assert embed_deck_video(pdf_path, mp4_path) == expected

    with pikepdf.open(pdf_path) as pdf:
        annotations = pdf.pages[0].obj[Name.Annots]
        assert len(annotations) == 1
        assert annotations[0].get(Name.Subtype) == Name.RichMedia
        assert tuple(float(value) for value in annotations[0].get(Name.Rect)) == (
            20.0,
            40.0,
            360.0,
            250.0,
        )
