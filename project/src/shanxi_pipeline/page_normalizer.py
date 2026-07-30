from __future__ import annotations

import re
from typing import Any

from .models import NormalizedPage
from .utils import RECIPE_ENUM_WITH_NAME, normalize_text

# 编号口径与 recipe_segmenter.is_recipe_title / strip_recipe_enumerator 共用一处定义
# （含「编号被铅印污损、被 OCR 读成拉丁乱码」的那一种，见 utils.RECIPE_ENUM_HEAD）。
RECIPE_ENUMERATOR = RECIPE_ENUM_WITH_NAME


def _is_recipe_title(text: str, ignored_titles: set[str], generic_keywords: list[str]) -> bool:
    cleaned = normalize_text(text).strip("：: ")
    if not cleaned or cleaned in ignored_titles:
        return False
    if cleaned.endswith("类") or cleaned.endswith("目录"):
        return False
    if RECIPE_ENUMERATOR.match(cleaned):
        return True
    if any(keyword in cleaned for keyword in generic_keywords):
        return False
    return False


def _detect_structure(page: NormalizedPage, cleaning_rules: dict[str, Any]) -> dict[str, Any]:
    aliases = cleaning_rules["section_aliases"]
    titles = [normalize_text(title).strip("：: ") for title in page.title_candidates]
    text = page.raw_text

    has_ingredients = any(header in text for header in aliases["ingredients"])
    has_seasonings = any(header in text for header in aliases["seasonings"])
    has_steps = any(header in text for header in aliases["steps"])
    has_tips = any(header in text for header in aliases["tips"])
    is_toc = any(title.replace(" ", "") == "目录" for title in titles) or ("目录" in text and "…" in text)
    is_front_matter = page.local_page <= 2 and len(page.cleaned_text) <= 20
    is_category_page = (
        not is_toc
        and len(titles) >= 1
        and all(title.endswith("类") or title.endswith("目录") for title in titles)
        and len(page.cleaned_text) <= 40
    )
    ignored_titles = set(cleaning_rules["ignored_title_exact"])
    generic_keywords = cleaning_rules["generic_title_keywords"]
    recipe_title_candidates = [title for title in titles if _is_recipe_title(title, ignored_titles, generic_keywords)]

    return {
        "has_ingredients_header": has_ingredients,
        "has_seasonings_header": has_seasonings,
        "has_steps_header": has_steps,
        "has_tips_header": has_tips,
        "is_toc": is_toc,
        "is_front_matter": is_front_matter,
        "is_category_page": is_category_page,
        "recipe_title_candidates": recipe_title_candidates,
    }


def normalize_page(page: NormalizedPage, cleaning_rules: dict[str, Any], thresholds: dict[str, Any]) -> NormalizedPage:
    replacements = cleaning_rules.get("text_replacements", [])
    cleaned = normalize_text(page.raw_text)
    for replacement in replacements:
        cleaned = re.sub(replacement["pattern"], replacement["replacement"], cleaned)
    page.cleaned_text = normalize_text(cleaned)

    # 清洗规则同样作用于 text_blocks——分割器与菜谱正文取自块文本,而非 cleaned_text
    for block in page.text_blocks:
        text = block.get("text", "")
        for replacement in replacements:
            text = re.sub(replacement["pattern"], replacement["replacement"], text)
        block["text"] = normalize_text(text)
    page.title_candidates = [
        block["text"] for block in page.text_blocks if block.get("block_type") == "title" and block.get("text")
    ]

    structure = _detect_structure(page, cleaning_rules)
    page.structure_hints.update(structure)
    warnings = list(page.warnings)

    if len(page.cleaned_text) < int(thresholds["sparse_text_chars"]):
        warnings.append("very sparse text")
    if len(structure["recipe_title_candidates"]) > 1:
        warnings.append("multiple recipe title candidates on one page")
    if not page.cleaned_text:
        warnings.append("empty cleaned text")
    for pattern in cleaning_rules.get("suspicious_patterns", []):
        if re.search(pattern, page.cleaned_text):
            warnings.append(f"suspicious text pattern matched: {pattern}")

    page_kind = "recipe"
    if structure["is_toc"]:
        page_kind = "toc"
    elif structure["is_front_matter"]:
        page_kind = "front_matter"
    elif structure["is_category_page"]:
        page_kind = "category"
    elif not structure["recipe_title_candidates"] and (structure["has_steps_header"] or structure["has_ingredients_header"]):
        page_kind = "continuation"
    elif not structure["recipe_title_candidates"]:
        page_kind = "unresolved"
    page.structure_hints["page_kind"] = page_kind

    if not page.cleaned_text:
        page.confidence = "failed"
    elif (
        structure["recipe_title_candidates"]
        and structure["has_steps_header"]
        and structure["has_ingredients_header"]
        and len(page.cleaned_text) >= int(thresholds["high_text_chars"])
    ):
        page.confidence = "high"
    elif structure["recipe_title_candidates"] and len(page.cleaned_text) >= int(thresholds["medium_text_chars"]):
        page.confidence = "medium"
    else:
        page.confidence = "low"

    page.review_needed = any(
        [
            "very sparse text" in warnings,
            len(structure["recipe_title_candidates"]) > 1,
            page_kind == "unresolved",
            page_kind == "continuation" and not structure["has_steps_header"],
        ]
    )
    page.warnings = list(dict.fromkeys(warnings))
    return page
