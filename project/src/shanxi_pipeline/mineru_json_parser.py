from __future__ import annotations

import re
from html import unescape
from typing import Any

from .models import BookEntry, NormalizedPage
from .utils import normalize_text, read_json

# MinerU 把部分原料表识别为 table 块：内容不在 span["content"] 而在 span["html"]。
# 旧实现只读 content，于是整块原料表（全书 56 张）被静默丢弃。
_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def _table_rows(html_text: str) -> list[str]:
    """把表格 HTML 还原成逐行文本，一个 <tr> 一行。

    必须逐行返回而不是拼成一块：原料表里「主料/配料/调料」各占一行，
    合并后去空格会让中间的分组标签匹配不到（分段器的标签正则锚定行首）。
    """
    rows: list[str] = []
    for row_html in _TR.findall(html_text):
        cells = [
            normalize_text(unescape(_TAG.sub("", cell))).strip()
            for cell in _TD.findall(row_html)
        ]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(" ".join(cells))
    return rows


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
    table_rows: list[str] = []
    for line in lines:
        for span in line.get("spans", []):
            content = (span.get("content") or "").strip()
            if content:
                parts.append(content)
                continue
            # table 类型的 span 内容在 html 里，content 为空
            html_text = span.get("html") or ""
            if html_text:
                table_rows.extend(_table_rows(html_text))
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
    # 表格逐行入块，保持与原块相同的 bbox/index，顺序不变，
    # 归属仍由分段器按位置判定（与普通文本块一致）
    for row in table_rows:
        collector.append(
            {
                "block_type": "table",
                "text": row,
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
