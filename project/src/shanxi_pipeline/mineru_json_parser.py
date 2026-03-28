from __future__ import annotations

from typing import Any

from .models import BookEntry, NormalizedPage
from .utils import normalize_text, read_json


def discover_page_container(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for value in payload.values():
            if (
                isinstance(value, list)
                and value
                and isinstance(value[0], dict)
                and "page_idx" in value[0]
                and "para_blocks" in value[0]
            ):
                return value
    raise ValueError("Unable to discover MinerU page container.")


def _flatten_lines(block: dict[str, Any], container_type: str, collector: list[dict[str, Any]]) -> None:
    lines = block.get("lines") or []
    parts = []
    for line in lines:
        for span in line.get("spans", []):
            content = (span.get("content") or "").strip()
            if content:
                parts.append(content)
    text = normalize_text("".join(parts))
    if text:
        collector.append(
            {
                "block_type": block.get("type", container_type or "text"),
                "text": text,
                "bbox": block.get("bbox"),
                "index": block.get("index"),
            }
        )


def extract_text_blocks(para_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for block in para_blocks:
        _flatten_lines(block, block.get("type", "text"), collected)
        for nested in block.get("blocks", []):
            if isinstance(nested, dict):
                _flatten_lines(nested, block.get("type", "text"), collected)
    return collected


def parse_mineru_book(book: BookEntry) -> tuple[list[NormalizedPage], dict[str, Any]]:
    if not book.json_path:
        raise FileNotFoundError(f"No MinerU JSON configured for {book.book_id}.")
    payload = read_json(book.json_path)
    page_container = discover_page_container(payload)
    backend = payload.get("_backend", "")
    version = payload.get("_version_name", "")
    ocr_engine = "::".join(part for part in [backend, version] if part)

    pages: list[NormalizedPage] = []
    for page in page_container:
        blocks = extract_text_blocks(page.get("para_blocks", []))
        raw_text = "\n".join(block["text"] for block in blocks if block["text"])
        titles = [block["text"] for block in blocks if block["block_type"] == "title" and block["text"]]
        warnings = []
        if not raw_text.strip():
            warnings.append("page has no extracted text")
        pages.append(
            NormalizedPage(
                book_id=book.book_id,
                book_file=book.file_name,
                series=book.series,
                local_page=int(page.get("page_idx", 0)) + 1,
                source_pdf_path=str(book.pdf_path),
                source_json_path=str(book.json_path),
                raw_text=raw_text,
                cleaned_text="",
                text_blocks=blocks,
                title_candidates=titles,
                structure_hints={
                    "page_idx_zero_based": int(page.get("page_idx", 0)),
                    "page_size": page.get("page_size"),
                    "block_types": sorted({block["block_type"] for block in blocks}),
                },
                ocr_engine=ocr_engine,
                warnings=warnings,
            )
        )
    return pages, {"ocr_engine": ocr_engine, "page_count": len(pages)}
