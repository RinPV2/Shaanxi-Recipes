from __future__ import annotations

from pathlib import Path

import fitz

from .models import BookEntry
from .models import ReviewItem
from .utils import ensure_dir


def render_review_pages(review_items: list[ReviewItem], output_root: Path, limit: int | None = None) -> list[ReviewItem]:
    rendered: list[ReviewItem] = []
    grouped: dict[tuple[str, str], list[ReviewItem]] = {}
    for item in review_items:
        key = (item.book_id, item.source_pdf_path)
        grouped.setdefault(key, []).append(item)

    count = 0
    for (book_id, pdf_path), items in grouped.items():
        doc = fitz.open(pdf_path)
        try:
            for item in sorted(items, key=lambda row: row.local_page):
                if limit is not None and count >= limit:
                    break
                page = doc.load_page(item.local_page - 1)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                target = ensure_dir(output_root / book_id) / f"p{item.local_page:04d}.png"
                pixmap.save(target)
                item.rendered_page_path = str(target)
                rendered.append(item)
                count += 1
        finally:
            doc.close()
        if limit is not None and count >= limit:
            break
    return rendered


def render_book_pages(
    book: BookEntry,
    output_root: Path,
    start_page: int | None = None,
    end_page: int | None = None,
    overwrite: bool = False,
) -> list[str]:
    rendered_paths: list[str] = []
    doc = fitz.open(book.pdf_path)
    try:
        total_pages = doc.page_count
        first_page = max(1, start_page or 1)
        last_page = min(total_pages, end_page or total_pages)
        book_root = ensure_dir(output_root / book.book_id)
        for local_page in range(first_page, last_page + 1):
            target = book_root / f"p{local_page:04d}.png"
            if target.exists() and not overwrite:
                rendered_paths.append(str(target))
                continue
            page = doc.load_page(local_page - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            pixmap.save(target)
            rendered_paths.append(str(target))
    finally:
        doc.close()
    return rendered_paths
