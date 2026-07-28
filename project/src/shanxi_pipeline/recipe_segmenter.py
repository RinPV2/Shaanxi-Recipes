from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import BookEntry, NormalizedPage, PageFallbackNote, RecipeCandidate, ReviewItem
from .utils import (
    is_plausible_dish_title,
    normalize_text,
    split_numbered_steps,
    strip_recipe_enumerator,
)

SECTION_HEADERS = {
    # 「原材料」是书3的常用写法（「一、原材料：」），必须排在「原料」之前，
    # 否则 startswith("原料") 永远匹配不到它，整区原料会落进 other_text。
    "ingredients": ("一、原材料", "原材料", "一、原料", "原料", "一、用料", "用料"),
    # 「制作方法」必须排在「制作」之前，否则「二、制作方法：」只会命中「制作」，
    # 残留的「方法：」被当成正文留下。
    "steps": ("二、制作方法", "制作方法", "二、制法", "制法", "二、作法", "作法", "方法", "制作"),
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


# 书4 部分菜用「（一）用料：」「（二）作法：」而非「一、用料：」编排章节，
# 与菜名的「（数字）菜名」同形。旧实现把这些章节头也判成菜名，
# 于是一道菜被撕成「桂花桶鸭(空)」+「用料」+「作法」多条记录。
_SECTION_WORDS = (
    "用料", "原料", "材料", "配料", "主料", "调料",
    "作法", "制法", "做法", "方法", "制作",
    "特点", "说明", "附注", "注意", "备注",
)


# 菜名不会以冒号收尾。「（1）干馍：」「（2）云云：」是原料区里的子项标签
# （（三二）兴平干馍和云云馍 一菜两式），旧实现把它们当成新菜名，
# 于是父菜谱被截成「食材0 步骤0」的空壳，内容全被划给了子项。
_TRAILING_COLON = re.compile(r"[：:]\s*$")


def is_recipe_title(text: str) -> bool:
    normalized = normalize_text(text)
    cleaned = normalized.strip("：: ")
    if not cleaned:
        return False
    if cleaned.endswith("类") or "目录" in cleaned or cleaned == "陕西菜谱":
        return False
    match = re.match(r"^[（(]?[一二三四五六七八九十百零〇0-9]+[）)]\s*(.+)", cleaned)
    if not match:
        return False
    # 序号后接章节名 → 是章节头，不是菜名
    remainder = match.group(1).strip("：: ")
    if remainder.startswith(_SECTION_WORDS):
        return False
    if _TRAILING_COLON.search(normalized):
        return False
    # 「(1)葱花酥油饼: 将猪板油切成小丁,…」这种「编号+子项名+整段做法」被 OCR 并成一块时，
    # 旧实现整块当菜名：一段正文成了站点标题与 URL，正主则退化成空壳。
    # 序号后面必须真的像个菜名（长度/句读/用量串/括号成对）才算菜名。
    if not is_plausible_dish_title(remainder):
        return False
    return True


def find_recipe_title_positions(blocks: list[dict[str, Any]]) -> list[int]:
    positions = []
    for index, block in enumerate(blocks):
        if block.get("block_type") == "title" and is_recipe_title(block.get("text", "")):
            positions.append(index)
    return positions


# 书末附录（书4 的「附：酱卤菜的特点及制作方法。」「附：几种特殊刀法」）以「附：」起标题。
# 它之后整段散文没有任何菜名标题，于是一直被当成续页塞给最后一道菜——
# （129）酿青椒 因此把 106～116 页整个刀工/拼盘附录吞了进去。
# 注意书3 p52 的「附：糖 棋 子」是真的附菜，所以只在「附：」后面不像菜名时才当附录边界。
_APPENDIX_HEAD = re.compile(r"^附\s*[：:]\s*(.*)$")


def _is_appendix_page(blocks: list[dict[str, Any]]) -> bool:
    for block in blocks:
        if block.get("block_type") != "title":
            continue
        matched = _APPENDIX_HEAD.match(normalize_text(block.get("text", "")))
        if matched and not is_plausible_dish_title(matched.group(1)):
            return True
    return False


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


# 原书用量：数字串 + 单位（+「半」）。与 obsidian_exporter 中的口径保持一致。
_ING_NUM = "〇零一二三四五六七八九十百半两几"
_ING_UNIT = "钱两斤分个只片粒条张朵克根块付副枚棵把碗匙勺撮"
_ING_PAIR = re.compile(rf"([一-鿿、（）()]+?)([{_ING_NUM}]+[{_ING_UNIT}]半?)")
# 标签后面必须是分隔符、空白或行尾。原书的分隔符是「：」，OCR 常读成「；」「，」「·」「。」，
# 所以不能只认冒号；但也不能像原先那样让分隔符整个可省——那样「调料面 二分」
# （五香调料面，是一味原料）会被当成「调料：面 二分」，把它后面继承分组的续行
# 整段错记成调料（（三二）兴平干馍和云云馍 的「云云」用料就是这样丢的）。
_ING_LABEL = re.compile(r"^(主料|配料|调料|佐料|辅料|原料|用料)(?:\s*[:：；;，,、·．.。]\s*|\s+|$)")
# 行中分组标签必须带冒号才切：行首标签允许省略冒号（原书排版如此），
# 但行中若不要求冒号，「各种调料。」这类正文里的「调料」也会被误切。
_ING_LABEL_SPLIT = re.compile(r"(主料|配料|调料|佐料|辅料|原料|用料)\s*[:：]")


def _clean_ing_name(name: str) -> str:
    """去掉原书为对齐插入的空格：「蛋 清」→「蛋清」、「葱 花」→「葱花」。"""
    return re.sub(r"\s+", "", name).strip("、 ")


def _extract_ing_items(segment: str, label: str) -> list[str]:
    """把一个（可能带组标签的）原料片段拆成若干「名称 用量」条目。"""
    segment = segment.strip("：: ")
    if not segment:
        return []
    body = re.sub(r"\s+", "", segment)
    items = [
        f"{_clean_ing_name(m.group(1))} {m.group(2)}"
        for m in _ING_PAIR.finditer(body)
        if _clean_ing_name(m.group(1))
    ]
    if not items:
        items = [segment]                     # 拆不出用量时整段保留，不丢信息
    if label:
        items[0] = f"{label}：{items[0]}"     # 组标签只出现在该组首条，与原书排版一致
    return items


def _split_ingredient_line(text: str, current_group: str) -> tuple[list[tuple[str, str]], str]:
    """把一行原料拆成若干 (分组, 「名称 用量」) 条目，并返回行尾所处的分组。

    两个关键点：
    1. **没有标签的续行继承上一行的分组**。原书里「调料：」下面往往还有两三行继续
       列调料（葱花/姜米/味精…），旧实现逐行独立判断，把这些续行一律归到
       ingredients，导致调料被错分到食材。
    2. **组标签可能出现在行中而不只在行首**。OCR 把原书竖排对齐的两三行并成一行时，
       「调料：」会落到行中央（如 sxcp-2 p144 绣球鱼肚、sxcp-1 p59 炝肚块），
       旧实现的标签正则锚定 `^`，整行只能按行首标签（或继承的分组）归类，
       「调料：」之后的食盐/味精/葱姜就被错记成食材。因此先按标签切段再逐段抽取。
    """
    normalized = normalize_text(text).strip("：: ")
    if not normalized:
        return [], current_group

    entries: list[tuple[str, str]] = []
    group = current_group
    head_label = ""
    # 行首标签单独处理：原书行首的标签常省略冒号（「调料 葱花 一钱」），行中的不能这样放宽
    label_match = _ING_LABEL.match(normalized)
    if label_match:
        head_label = label_match.group(1)
        group = "seasoning" if head_label in SEASONING_LABELS else "ingredient"
        normalized = normalized[label_match.end():]

    # re.split 带一个捕获组 → [首段, 标签1, 段1, 标签2, 段2, ...]
    pieces = _ING_LABEL_SPLIT.split(normalized)
    for item in _extract_ing_items(pieces[0], head_label):
        entries.append((group, item))         # 首段沿用行首标签或继承来的分组
    for index in range(1, len(pieces) - 1, 2):
        label = pieces[index]
        group = "seasoning" if label in SEASONING_LABELS else "ingredient"
        for item in _extract_ing_items(pieces[index + 1], label):
            entries.append((group, item))
    return entries, group


# 章节序号前缀：原书排版不一，「一、原料」「一 原料」「一，原料」「一.原料」都出现过。
# 旧实现只按字面 startswith 匹配，凡分隔符不是「、」的都漏识，整行被当成食材条目留下。
# 书4 另有「（一）用料：」「（二）作法:」的带括号编排（如 (81) 桂花桶鸭），
# 旧正则不认括号形式 → 该菜整条原料/做法都归不进任何区，只靠 other_text 兜底救回两行。
_SECTION_ENUM = re.compile(
    r"^(?:[（(]\s*[一二三四五六七八九十\d]+\s*[）)]|[一二三四五六七八九十]\s*[、，,．.。:：]?)\s*"
)


# 章节头后面只可能跟标点（原书是「：」，OCR 常读成「。」「，」「.」「、」）或行尾。
# 若紧跟汉字，那就是一句以该词开头的正文，不是章节头——书4 书末附录的
# 「原材料经洗刷整理干净…」「原料切成片、条、丝、块后…」正是这样把整段散文
# 翻成了原料区，「制法简单，薄脆酥香。」（特点行）也被误判成制法标题。
_HEADER_TAIL = re.compile(r"^[：:；;。，,．.、·…！!？?\s]")


def _match_section_header(text: str) -> tuple[str | None, str]:
    normalized = normalize_text(text)
    candidates = [normalized]
    stripped = _SECTION_ENUM.sub("", normalized, count=1)
    if stripped and stripped != normalized:
        candidates.append(stripped)
    for candidate in candidates:
        for section, headers in SECTION_HEADERS.items():
            for header in headers:
                if not candidate.startswith(header):
                    continue
                remainder = candidate[len(header) :]
                if remainder and not _HEADER_TAIL.match(remainder):
                    continue
                # 原先只剥「：:；; 」，于是「二、制法。」剥完还剩「。」，
                # 这个孤立句号会作为一条步骤留在正文里。
                return section, remainder.lstrip("：:；;。，,．.、·…！!？? ")
    return None, normalized


# OCR 把「一、用料：」读成「一、用补：」「一、用情。」「一、用朴：」这类残行。
# 它是章节头而不是数据，落进原料区只会变成一条无用量的垃圾条目。
_GARBLED_SECTION_LINE = re.compile(
    r"^(?:[（(]\s*[一二三四五六七八九十\d]+\s*[）)]|[一二三四五六七八九十]\s*[、，,．.。:：])"
    r"\s*[^\s]{0,4}[：:。.]?$"
)


def _implied_ingredients_end(blocks: list[dict[str, Any]]) -> int:
    """原料区扫描褪色、「一、原料」整行没被 OCR 出来时，按版式位置推断原料区。

    返回原料区的结束下标（>0 表示「菜名之后、制法之前」这一段应按原料解析）。
    只在两个条件同时成立时才推断，避免把书末的刀工附录、豆腐脑散文当成原料：
      ① 本条以自己的菜名开头（不是续页片段）；
      ② 后面确实出现「制法/作法」标题，原料区有明确右边界。
    先遇到「原料」标题说明不需要推断；先遇到「特点」等说明版式不明，一律不猜。
    """
    if not blocks:
        return 0
    if not is_recipe_title(normalize_text(blocks[0].get("text", ""))):
        return 0
    for index, block in enumerate(blocks[1:], start=1):
        text = normalize_text(block.get("text", ""))
        if not text:
            continue
        section, _remainder = _match_section_header(text)
        if section == "steps":
            return index
        if section is not None:
            return 0
    return 0


def _finalize_recipe(active: ActiveRecipe) -> tuple[RecipeCandidate, list[ReviewItem]]:
    ingredients: list[str] = []
    seasonings: list[str] = []
    steps: list[str] = []
    tips: list[str] = []
    other_text: list[str] = []
    review_items: list[ReviewItem] = []

    implied_end = _implied_ingredients_end(active.blocks)
    current_section = "ingredients" if implied_end else "other"
    ingredient_group = "ingredient"   # 原料区内的当前分组，供无标签续行继承
    for index, block in enumerate(active.blocks):
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
        elif index < implied_end and _GARBLED_SECTION_LINE.match(text):
            continue   # 推断出的原料区里的残缺章节头，丢弃而不是当成原料条目

        if current_section == "ingredients":
            entries, ingredient_group = _split_ingredient_line(text, ingredient_group)
            for group, item in entries:
                (seasonings if group == "seasoning" else ingredients).append(item)
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

        is_appendix = _is_appendix_page(blocks)
        if (page_kind in {"toc", "front_matter", "category"} or is_appendix) and not title_positions:
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
