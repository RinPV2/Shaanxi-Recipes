from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import BookEntry, NormalizedPage, PageFallbackNote, RecipeCandidate, ReviewItem
from .utils import normalize_text, split_numbered_steps, strip_recipe_enumerator

SECTION_HEADERS = {
    "ingredients": ("一、原料", "原料", "一、用料", "用料"),
    "steps": ("二、制法", "制法", "二、作法", "作法", "方法", "制作"),
    "tips": ("三、特点", "特点", "提示", "说明", "附注", "注"),
}

INGREDIENT_LABELS = ("主料", "配料", "原料", "用料")
SEASONING_LABELS = ("调料", "佐料", "辅料")


@dataclass
class ActiveRecipe:
    title: str
    book: BookEntry
    source_pdf: str
    source_json: str
    ocr_engine: str
    local_pages: list[int] = field(default_factory=list)
    blocks: list[dict[str, Any]] = field(default_factory=list)
    page_flags: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def is_recipe_title(text: str) -> bool:
    cleaned = normalize_text(text).strip("：: ")
    if not cleaned:
        return False
    if cleaned.endswith("类") or "目录" in cleaned or cleaned == "陕西菜谱":
        return False
    return bool(re.match(r"^[（(]?[一二三四五六七八九十百零〇0-9]+[）)]\s*.+", cleaned))


def find_recipe_title_positions(blocks: list[dict[str, Any]]) -> list[int]:
    positions = []
    for index, block in enumerate(blocks):
        if block.get("block_type") == "title" and is_recipe_title(block.get("text", "")):
            positions.append(index)
    return positions


def _append_to_active(active: ActiveRecipe, page: NormalizedPage, blocks: list[dict[str, Any]]) -> None:
    if page.local_page not in active.local_pages:
        active.local_pages.append(page.local_page)
    active.blocks.extend(blocks)
    active.page_flags.append(
        {
            "local_page": page.local_page,
            "confidence": page.confidence,
            "review_needed": page.review_needed,
            "warnings": list(page.warnings),
        }
    )


def _split_ingredient_line(text: str) -> tuple[list[str], list[str]]:
    normalized = normalize_text(text).strip("：: ")
    ingredients: list[str] = []
    seasonings: list[str] = []
    if not normalized:
        return ingredients, seasonings
    if any(normalized.startswith(label) for label in SEASONING_LABELS):
        seasonings.append(normalized)
    elif any(normalized.startswith(label) for label in INGREDIENT_LABELS):
        ingredients.append(normalized)
    else:
        ingredients.append(normalized)
    return ingredients, seasonings


def _match_section_header(text: str) -> tuple[str | None, str]:
    normalized = normalize_text(text)
    for section, headers in SECTION_HEADERS.items():
        for header in headers:
            if normalized.startswith(header):
                remainder = normalized[len(header) :].lstrip("：:；; ")
                if remainder and remainder != normalized:
                    return section, remainder
                return section, ""
    return None, normalized


def _finalize_recipe(active: ActiveRecipe) -> tuple[RecipeCandidate, list[ReviewItem]]:
    ingredients: list[str] = []
    seasonings: list[str] = []
    steps: list[str] = []
    tips: list[str] = []
    other_text: list[str] = []
    review_items: list[ReviewItem] = []

    current_section = "other"
    for block in active.blocks:
        text = normalize_text(block.get("text", ""))
        if not text:
            continue
        if is_recipe_title(text):
            continue
        matched_section, remainder = _match_section_header(text)
        if matched_section:
            current_section = matched_section
            if not remainder:
                continue
            text = remainder

        if current_section == "ingredients":
            ing, sea = _split_ingredient_line(text)
            ingredients.extend(ing)
            seasonings.extend(sea)
        elif current_section == "seasonings":
            seasonings.append(text)
        elif current_section == "steps":
            steps.extend(split_numbered_steps(text))
        elif current_section == "tips":
            tips.append(text)
        else:
            other_text.append(text)

    if not ingredients and other_text:
        ingredients.extend(other_text[:2])
    if not steps and other_text:
        steps.extend(other_text[:3])

    warning_pool = list(active.warnings)
    flag_conflicts = 0
    for page_flag in active.page_flags:
        warning_pool.extend(page_flag["warnings"])
        if page_flag["review_needed"]:
            flag_conflicts += 1

    raw_excerpt = normalize_text("\n".join(block.get("text", "") for block in active.blocks))[:600]
    title = strip_recipe_enumerator(active.title)
    pages = sorted(set(active.local_pages))
    source_links = [f"{active.book.book_id}#p{page:04d}" for page in pages]

    confidence = "high"
    if not ingredients or not steps:
        confidence = "medium"
    if flag_conflicts or len(pages) > 3 or len(title) <= 1:
        confidence = "low"
    review_needed = confidence == "low" or flag_conflicts > 0

    if review_needed:
        for page in pages:
            review_items.append(
                ReviewItem(
                    book_id=active.book.book_id,
                    local_page=page,
                    reason="recipe boundary or structure needs manual verification",
                    source_pdf_path=active.source_pdf,
                    source_json_path=active.source_json,
                )
            )

    recipe = RecipeCandidate(
        title=title,
        aliases=[],
        series=active.book.series,
        book_id=active.book.book_id,
        book_file=active.book.file_name,
        local_pages=pages,
        source_pdf=active.source_pdf,
        source_json=active.source_json,
        ingredients=list(dict.fromkeys(ingredients)),
        seasonings=list(dict.fromkeys(seasonings)),
        steps=list(dict.fromkeys(steps)),
        tips=list(dict.fromkeys(tips)),
        raw_excerpt=raw_excerpt,
        related_notes=[],
        ocr_engine=active.ocr_engine,
        confidence=confidence,
        status="recipe" if confidence in {"high", "medium"} else "review",
        review_needed=review_needed,
        source_links=source_links,
        warnings=list(dict.fromkeys(warning_pool)),
    )
    return recipe, review_items


def _page_to_fallback(page: NormalizedPage) -> tuple[PageFallbackNote, list[ReviewItem]]:
    review_items = []
    if page.review_needed or page.confidence in {"low", "failed"}:
        review_items.append(
            ReviewItem(
                book_id=page.book_id,
                local_page=page.local_page,
                reason="page-level fallback requires review",
                source_pdf_path=page.source_pdf_path,
                source_json_path=page.source_json_path,
            )
        )
    note = PageFallbackNote(
        title=f"{page.book_id} 第{page.local_page}页 页面回退",
        series=page.series,
        book_id=page.book_id,
        book_file=page.book_file,
        local_pages=[page.local_page],
        source_pdf=page.source_pdf_path,
        source_json=page.source_json_path,
        raw_excerpt=page.raw_text[:800],
        cleaned_text=page.cleaned_text,
        related_notes=[],
        ocr_engine=page.ocr_engine,
        confidence=page.confidence,
        status=page.structure_hints.get("page_kind", "fallback"),
        review_needed=page.review_needed,
        source_links=[f"{page.book_id}#p{page.local_page:04d}"],
        warnings=list(page.warnings),
        rendered_page_path=page.rendered_page_path,
    )
    return note, review_items


def segment_book(
    book: BookEntry,
    pages: list[NormalizedPage],
) -> tuple[list[RecipeCandidate], list[PageFallbackNote], list[ReviewItem]]:
    recipes: list[RecipeCandidate] = []
    fallbacks: list[PageFallbackNote] = []
    review_items: list[ReviewItem] = []
    active: ActiveRecipe | None = None

    for page in sorted(pages, key=lambda item: item.local_page):
        blocks = [block for block in page.text_blocks if normalize_text(block.get("text", ""))]
        title_positions = find_recipe_title_positions(blocks)
        page_kind = page.structure_hints.get("page_kind")

        if page_kind in {"toc", "front_matter", "category"} and not title_positions:
            if active is not None:
                recipe, recipe_reviews = _finalize_recipe(active)
                recipes.append(recipe)
                review_items.extend(recipe_reviews)
                active = None
            fallback, fallback_reviews = _page_to_fallback(page)
            fallbacks.append(fallback)
            review_items.extend(fallback_reviews)
            continue

        if title_positions:
            if active is not None:
                leading = blocks[:title_positions[0]]
                if leading:
                    _append_to_active(active, page, leading)
                recipe, recipe_reviews = _finalize_recipe(active)
                recipes.append(recipe)
                review_items.extend(recipe_reviews)
                active = None

            for idx, start in enumerate(title_positions):
                end = title_positions[idx + 1] if idx + 1 < len(title_positions) else len(blocks)
                segment_blocks = blocks[start:end]
                candidate = ActiveRecipe(
                    title=normalize_text(segment_blocks[0].get("text", "")),
                    book=book,
                    source_pdf=page.source_pdf_path,
                    source_json=page.source_json_path,
                    ocr_engine=page.ocr_engine,
                )
                _append_to_active(candidate, page, segment_blocks)
                candidate.warnings.extend(page.warnings)
                if idx + 1 < len(title_positions):
                    recipe, recipe_reviews = _finalize_recipe(candidate)
                    recipes.append(recipe)
                    review_items.extend(recipe_reviews)
                else:
                    active = candidate
            continue

        continuation_like = page_kind == "continuation" or bool(page.cleaned_text)
        if active is not None and continuation_like:
            _append_to_active(active, page, blocks)
            active.warnings.extend(page.warnings)
        else:
            fallback, fallback_reviews = _page_to_fallback(page)
            fallbacks.append(fallback)
            review_items.extend(fallback_reviews)

    if active is not None:
        recipe, recipe_reviews = _finalize_recipe(active)
        recipes.append(recipe)
        review_items.extend(recipe_reviews)

    return recipes, fallbacks, review_items
