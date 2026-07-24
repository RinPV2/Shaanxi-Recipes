from __future__ import annotations

import io
from pathlib import Path

import fitz
from PIL import Image

from .models import BookEntry
from .utils import ensure_dir

RENDER_MATRIX = (2, 2)  # 144 dpi
WEBP_QUALITY = 55


def export_book_page_images(
    book: BookEntry,
    output_root: Path,
    overwrite: bool = False,
    quality: int = WEBP_QUALITY,
) -> list[Path]:
    book_root = ensure_dir(output_root / book.book_id)
    written: list[Path] = []
    with fitz.open(book.pdf_path) as doc:
        for page_index in range(doc.page_count):
            target = book_root / f"p{page_index + 1:04d}.webp"
            if target.exists() and not overwrite:
                continue
            pixmap = doc[page_index].get_pixmap(matrix=fitz.Matrix(*RENDER_MATRIX), alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("L")
            image.save(target, "WEBP", quality=quality)
            written.append(target)
    return written
