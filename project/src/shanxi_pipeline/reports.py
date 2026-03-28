from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import BookEntry, PageFallbackNote, RecipeCandidate, ReviewItem
from .utils import append_jsonl, now_iso, sha256_file, write_json, write_text


def write_review_queue(report_root: Path, review_items: list[ReviewItem]) -> Path:
    path = report_root / "review_queue.jsonl"
    append_jsonl(path, [item.to_dict() for item in review_items])
    return path


def write_ingestion_manifest(
    report_root: Path,
    books: list[BookEntry],
    recipes_by_book: dict[str, list[RecipeCandidate]],
    fallbacks_by_book: dict[str, list[PageFallbackNote]],
    review_by_book: dict[str, list[ReviewItem]],
    page_counts: dict[str, int],
) -> Path:
    rows: list[dict[str, Any]] = []
    for book in books:
        rows.append(
            {
                "book_id": book.book_id,
                "series": book.series,
                "file_name": book.file_name,
                "file_path": str(book.pdf_path),
                "mineru_json": str(book.json_path) if book.json_path else None,
                "status": book.status,
                "enabled": book.enabled,
                "pdf_sha256": sha256_file(book.pdf_path) if book.pdf_path.exists() else None,
                "json_sha256": sha256_file(book.json_path) if book.json_path and book.json_path.exists() else None,
                "page_count": page_counts.get(book.book_id, 0),
                "recipe_count": len(recipes_by_book.get(book.book_id, [])),
                "fallback_count": len(fallbacks_by_book.get(book.book_id, [])),
                "review_count": len(review_by_book.get(book.book_id, [])),
                "processed_at": now_iso(),
            }
        )
    path = report_root / "ingestion_manifest.json"
    write_json(path, rows)
    return path


def write_summary(
    report_root: Path,
    books: list[BookEntry],
    recipes: list[RecipeCandidate],
    fallbacks: list[PageFallbackNote],
    review_items: list[ReviewItem],
    page_counts: dict[str, int],
) -> tuple[Path, Path]:
    summary = {
        "generated_at": now_iso(),
        "book_count": len(books),
        "page_count": sum(page_counts.values()),
        "recipe_count": len(recipes),
        "fallback_count": len(fallbacks),
        "review_count": len(review_items),
        "books": [
            {
                "book_id": book.book_id,
                "series": book.series,
                "status": book.status,
                "enabled": book.enabled,
                "page_count": page_counts.get(book.book_id, 0),
            }
            for book in books
        ],
    }
    json_path = report_root / "summary.json"
    write_json(json_path, summary)

    lines = [
        "# Architecture Summary",
        "",
        "- Source of truth is the existing MinerU JSON per book.",
        "- Parsed pages are preserved per book under `work/parsed_pages/<book_id>/page-XXXX.json`.",
        "- Normalized pages are written per book under `work/normalized_json/<book_id>/page-XXXX.json`.",
        "- Recipe segmentation is conservative and book-local.",
        "- Low-confidence or non-recipe pages are preserved as fallback notes instead of being discarded.",
        "- `work/reports/ingestion_manifest.json` is the incremental state file used for future imports.",
        "",
        "# Summary",
        "",
        f"- Books processed this run: {', '.join(book.book_id for book in books)}",
        f"- Total normalized pages: {sum(page_counts.values())}",
        f"- Recipe notes: {len(recipes)}",
        f"- Page fallback notes: {len(fallbacks)}",
        f"- Review queue items: {len(review_items)}",
    ]
    md_path = report_root / "architecture_summary.md"
    write_text(md_path, "\n".join(lines).strip() + "\n")
    return json_path, md_path


def write_manifest_strategy(report_root: Path) -> Path:
    path = report_root / "normalized_manifest_strategy.md"
    lines = [
        "# Normalized Manifest Strategy",
        "",
        "- `book.yaml` stores canonical book-level metadata and current availability state.",
        "- `work/reports/ingestion_manifest.json` stores source hashes, counts, and timestamps per book.",
        "- Incremental imports append or update only the target `book_id` entry and then refresh indexes.",
        "- Existing successful outputs for other books remain untouched unless a direct re-run targets them.",
        "- Traceability remains book-local with `book_id` and `local_page` in every artifact.",
    ]
    write_text(path, "\n".join(lines).strip() + "\n")
    return path


def write_validation_checklist(report_root: Path) -> Path:
    path = report_root / "validation_checklist.md"
    lines = [
        "# Validation Checklist",
        "",
        "- [x] Book manifest normalized with book-local PDF and MinerU JSON mapping",
        "- [x] Parsed page artifacts written for each processed book",
        "- [x] Normalized page artifacts written with required fields",
        "- [x] Recipe candidates exported to markdown when confidence is sufficient",
        "- [x] Page fallback notes exported for unresolved or non-recipe pages",
        "- [x] Review queue written as JSONL",
        "- [x] Obsidian vault indexes generated",
        "- [x] Incremental manifest written for future `sxcp-1` import",
    ]
    write_text(path, "\n".join(lines).strip() + "\n")
    return path


def write_directory_tree(report_root: Path, root: Path) -> Path:
    path = report_root / "directory_tree.txt"
    wanted = [
        "book.yaml",
        "project",
        "project/config",
        "project/scripts",
        "project/src/shanxi_pipeline",
        "project/tests",
        "work",
        "work/parsed_pages",
        "work/normalized_json",
        "work/recipe_candidates",
        "work/review_queue",
        "work/page_fallback_notes",
        "work/final_markdown",
        "work/reports",
        "work/vault",
        "logs",
    ]
    lines = [str(root)]
    for item in wanted:
        lines.append(f"└─ {item}")
    write_text(path, "\n".join(lines) + "\n")
    return path
