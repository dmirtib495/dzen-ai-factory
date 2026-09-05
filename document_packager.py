from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path
from typing import Iterable

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt


MIN_APPROVED_IMAGES = 5


def _safe_name(value: str, fallback: str = "article") -> str:
    value = re.sub(r"[^\w\-а-яА-ЯёЁ ]+", "", (value or "").strip(), flags=re.UNICODE)
    value = re.sub(r"\s+", "_", value).strip("_")
    return value[:80] or fallback


def _add_markdown(document: Document, markdown: str) -> None:
    for raw in (markdown or "").splitlines():
        line = raw.strip()
        if not line:
            document.add_paragraph()
            continue
        if line.startswith("## "):
            document.add_heading(line[3:].strip(), level=2)
            continue
        if line.startswith("### "):
            document.add_heading(line[4:].strip(), level=3)
            continue
        if re.match(r"^\d+\.\s+", line):
            p = document.add_paragraph(style="List Number")
            p.add_run(re.sub(r"^\d+\.\s+", "", line))
            continue
        if line.startswith("- "):
            p = document.add_paragraph(style="List Bullet")
            p.add_run(line[2:].strip())
            continue
        document.add_paragraph(line)


def build_article_docx(
    *,
    headline: str,
    article_markdown: str,
    approved_images: Iterable[str | Path],
    output_path: str | Path,
    captions: Iterable[str] | None = None,
) -> Path:
    images = [Path(p) for p in approved_images]
    if len(images) < MIN_APPROVED_IMAGES:
        raise ValueError(
            f"DOCX requires at least {MIN_APPROVED_IMAGES} approved images; got {len(images)}"
        )
    missing = [str(p) for p in images if not p.is_file()]
    if missing:
        raise FileNotFoundError("Approved image files missing: " + ", ".join(missing))

    caption_list = list(captions or [])
    while len(caption_list) < len(images):
        caption_list.append("")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)

    styles = doc.styles
    styles["Normal"].font.name = "Arial"
    styles["Normal"].font.size = Pt(11)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run((headline or "").strip())
    run.bold = True
    run.font.size = Pt(18)

    doc.add_paragraph()
    _add_markdown(doc, article_markdown)

    doc.add_page_break()
    doc.add_heading("Иллюстрации", level=2)

    for idx, image in enumerate(images, 1):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run().add_picture(str(image), width=Inches(6.3))
        caption = (caption_list[idx - 1] or "").strip()
        if caption:
            cp = doc.add_paragraph(f"Рис. {idx}. {caption}")
            cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in cp.runs:
                r.italic = True
                r.font.size = Pt(9)

    doc.save(output)
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError("DOCX was not created correctly")
    return output


def build_article_package(
    *,
    article_id: int | str,
    headline: str,
    article_markdown: str,
    approved_images: Iterable[str | Path],
    output_root: str | Path = "data/packages",
    captions: Iterable[str] | None = None,
) -> tuple[Path, Path, Path]:
    images = [Path(p) for p in approved_images]
    if len(images) < MIN_APPROVED_IMAGES:
        raise ValueError(
            f"Package requires at least {MIN_APPROVED_IMAGES} approved images; got {len(images)}"
        )

    root = Path(output_root)
    folder = root / f"article_{article_id}_{_safe_name(headline)}"
    if folder.exists():
        shutil.rmtree(folder)
    image_dir = folder / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    for idx, src in enumerate(images, 1):
        if not src.is_file():
            raise FileNotFoundError(str(src))
        suffix = src.suffix.lower() if src.suffix else ".jpg"
        dst = image_dir / f"image_{idx:02d}{suffix}"
        shutil.copy2(src, dst)
        copied.append(dst)

    docx_path = folder / "article.docx"
    build_article_docx(
        headline=headline,
        article_markdown=article_markdown,
        approved_images=copied,
        output_path=docx_path,
        captions=captions,
    )

    (folder / "article.md").write_text(article_markdown or "", encoding="utf-8")
    (folder / "headline.txt").write_text((headline or "").strip(), encoding="utf-8")

    zip_path = root / f"{folder.name}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(folder)))

    if not zip_path.is_file() or zip_path.stat().st_size <= 0:
        raise RuntimeError("ZIP was not created correctly")
    return folder, docx_path, zip_path
