from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .confirmation_reader import parse_confirmation_source
from .models import NormalizedPage
from .recipe_segmenter import is_recipe_title
from .utils import normalize_text

LINE_SEPARATOR = " / "
FULL_PAGE_PREFIX = "【整页】"
MATCH_THRESHOLD = 0.6


def split_correct_content(content: str) -> list[str]:
    return [part.strip() for part in content.split(LINE_SEPARATOR) if part.strip()]


def load_page_corrections(work_root: Path) -> dict[tuple[str, int], str]:
    review_root = work_root / "page_review_md"
    if not review_root.exists():
        return {}
    corrections: dict[tuple[str, int], str] = {}
    for row in parse_confirmation_source(review_root):
        if not row["book_id"]:
            continue
        content = row["correct_content"].strip()
        if row["confirmed"] and content:
            corrections[(row["book_id"], int(row["local_page"]))] = content
    return corrections


def _classify_block_type(text: str) -> str:
    cleaned = normalize_text(text).strip("：: ")
    if cleaned.endswith("类") or cleaned == "目录":
        return "title"
    if is_recipe_title(cleaned):
        return "title"
    return "text"


def _rebuild_page_text(page: NormalizedPage) -> None:
    page.raw_text = "\n".join(block["text"] for block in page.text_blocks if block["text"])
    page.title_candidates = [
        block["text"] for block in page.text_blocks if block["block_type"] == "title" and block["text"]
    ]


def apply_correction(page: NormalizedPage, correct_content: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "book_id": page.book_id,
        "local_page": page.local_page,
        "mode": "line_patch",
        "patched": 0,
        "unmatched": [],
    }

    if correct_content.startswith(FULL_PAGE_PREFIX):
        lines = split_correct_content(correct_content[len(FULL_PAGE_PREFIX):])
        page.text_blocks = [
            {
                "block_type": _classify_block_type(line),
                "text": normalize_text(line),
                "bbox": None,
                "index": None,
            }
            for line in lines
        ]
        _rebuild_page_text(page)
        page.structure_hints["correction_applied"] = True
        result["mode"] = "full_page"
        result["patched"] = len(lines)
        return result

    used_indices: set[int] = set()
    for line in split_correct_content(correct_content):
        target = normalize_text(line)
        best_index = -1
        best_ratio = 0.0
        for index, block in enumerate(page.text_blocks):
            if index in used_indices:
                continue
            ratio = SequenceMatcher(None, block.get("text", ""), target).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_index = index
        if best_index >= 0 and best_ratio >= MATCH_THRESHOLD:
            used_indices.add(best_index)
            block = page.text_blocks[best_index]
            block["text"] = target
            if is_recipe_title(target):
                block["block_type"] = "title"
            result["patched"] += 1
        else:
            result["unmatched"].append(line)

    if result["patched"]:
        _rebuild_page_text(page)
        page.structure_hints["correction_applied"] = True
    return result
