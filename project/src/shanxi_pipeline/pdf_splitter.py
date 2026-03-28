from __future__ import annotations

import json
from pathlib import Path

import fitz

from .manifest import load_books
from .utils import ensure_dir, write_json


def _save_pdf_range(source_doc, start_page: int, end_page: int, target: Path) -> int:
    out_doc = fitz.open()
    try:
        out_doc.insert_pdf(source_doc, from_page=start_page - 1, to_page=end_page - 1)
        out_doc.save(target, garbage=4, deflate=True)
    finally:
        out_doc.close()
    return target.stat().st_size


def _find_chunk_end(source_doc, start_page: int, total_pages: int, max_pages: int, max_bytes: int, temp_root: Path) -> tuple[int, int]:
    end_page = min(total_pages, start_page + max_pages - 1)
    temp_target = temp_root / "chunk-check.pdf"

    while True:
        size_bytes = _save_pdf_range(source_doc, start_page, end_page, temp_target)
        if size_bytes <= max_bytes or end_page == start_page:
            return end_page, size_bytes
        page_count = end_page - start_page + 1
        shrink_ratio = max_bytes / size_bytes
        new_page_count = max(1, int(page_count * shrink_ratio * 0.97))
        if new_page_count >= page_count:
            new_page_count = page_count - 1
        end_page = start_page + new_page_count - 1


def split_pdf_file(source_path: Path, output_root: Path, max_pages: int, max_bytes: int, stem_prefix: str) -> list[dict]:
    ensure_dir(output_root)
    temp_root = ensure_dir(output_root / "_tmp")
    segments = []
    source_doc = fitz.open(source_path)
    try:
        total_pages = source_doc.page_count
        start_page = 1
        part_index = 1
        while start_page <= total_pages:
            end_page, _ = _find_chunk_end(source_doc, start_page, total_pages, max_pages, max_bytes, temp_root)
            target = output_root / f"{stem_prefix}_part{part_index:02d}_p{start_page:04d}-p{end_page:04d}.pdf"
            size_bytes = _save_pdf_range(source_doc, start_page, end_page, target)
            segments.append(
                {
                    "part_index": part_index,
                    "start_page": start_page,
                    "end_page": end_page,
                    "page_count": end_page - start_page + 1,
                    "size_bytes": size_bytes,
                    "size_mb": round(size_bytes / 1024 / 1024, 2),
                    "path": str(target),
                }
            )
            start_page = end_page + 1
            part_index += 1
    finally:
        source_doc.close()

    temp_file = temp_root / "chunk-check.pdf"
    if temp_file.exists():
        temp_file.unlink()
    if temp_root.exists() and not any(temp_root.iterdir()):
        temp_root.rmdir()
    return segments


def split_books(context, requested_ids: list[str] | None = None, max_pages: int = 200, max_megabytes: int = 100) -> Path:
    books = load_books(context.book_manifest)
    wanted = set(requested_ids or [])
    if wanted:
        books = [book for book in books if book.book_id in wanted]

    output_root = ensure_dir(context.work_root / "split_pdfs")
    max_bytes = max_megabytes * 1024 * 1024
    manifest = []
    for book in books:
        if not book.pdf_path.exists():
            continue
        book_root = ensure_dir(output_root / book.book_id)
        for existing in book_root.glob("*.pdf"):
            existing.unlink()
        segments = split_pdf_file(
            source_path=book.pdf_path,
            output_root=book_root,
            max_pages=max_pages,
            max_bytes=max_bytes,
            stem_prefix=book.book_id,
        )
        manifest.append(
            {
                "book_id": book.book_id,
                "source_pdf": str(book.pdf_path),
                "max_pages": max_pages,
                "max_megabytes": max_megabytes,
                "segments": segments,
            }
        )

    manifest_path = context.work_root / "reports" / "split_pdf_manifest.json"
    write_json(manifest_path, manifest)
    return manifest_path
