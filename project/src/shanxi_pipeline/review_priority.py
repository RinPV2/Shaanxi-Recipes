from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .confirmation_reader import parse_confirmation_source
from .manifest import load_books
from .recipe_segmenter import _ingredient_region_mask
from .title_policy import to_fullwidth_parens
from .utils import is_plausible_dish_title, normalize_text, write_json, write_text

PAGE_REF_RE = re.compile(r"[（(]\s*(?P<page>\d+)\s*[.)）]")
# 目录条目 =「菜名 + 可选点线 + （页码）」。点线不能强求:书4 的双栏目录只用空格
# 分隔（「白封肉 (1)」),书2 也有若干条漏了点线（「炒肝油 (50)」「汆三丁(52)」),
# 强求点线会把整页 36 条目录条目一起丢掉。页码闭括号允许「(1.)」这类多余句点。
TOC_ENTRY_RE = re.compile(r"^(?P<title>.+?)\s*[.…·]*\s*[（(]\s*(?P<page>\d+)\s*[.)）]+\s*$")
# 目录条目的编号形态各册不同:书1「41.红烧肘子」、书3「（五九）三原疙瘩面」,
# 而书2/书4 的目录条目根本不编号。菜名本身可以以汉字数字开头（「五香鱼」「三不粘」
# 「四季豆腐」「五柳凤尾笋」),所以汉字数字只有带括号或紧跟顿号/句点时才算编号,
# 否则会把菜名第一个字当序号剥掉。阿拉伯数字开头的菜名不存在,可宽松处理。
TOC_ENUMERATOR_RE = re.compile(
    r"^(?:[（(]\s*[一二三四五六七八九十百千零〇\d]+\s*[)）]"
    r"|[一二三四五六七八九十百千零〇]+\s*[、.]"
    r"|\d+\s*[、.]?)\s*"
)
# 菜名编号必须带闭括号:「（三八）松籽酿方肉」是菜名,「2.炒勺坐火上…」是步骤
DISH_ENUMERATOR_RE = re.compile(r"^[（(]?[一二三四五六七八九十百千零〇\d]+[)）]\s*")
# 人工校对记录的控制标记（定义见 correction_applier）。它们是给回灌器看的指令前缀,
# 不是页面内容:漏剥就会出现「【整页】41.红烧肘子」这种菜名和「【整页】水产类」这种分类。
REVIEW_MARKER_RE = re.compile(r"【(?:整页|补行|补行前|替行|删行)(?::[^】]*)?】\s*")
# 菜名里的括号批注（「箸头面（油泼面）」「炒拨鱼（附，拨鱼方法）」)不参与菜名合法性判断,
# 否则会连正经菜名一起否掉。
TOC_ANNOTATION_RE = re.compile(r"[（(][^（()）]*[)）]")
TITLE_TRIM_CHARS = ".-· "
# 已编译的 text_replacements:(pattern, replacement) 序列
Replacements = tuple[tuple[re.Pattern[str], str], ...]


def _canonical_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", normalize_text(text))
    normalized = normalized.replace("／", "/")
    return normalized.strip()


def _strip_review_markers(text: str) -> str:
    """剥掉校对记录的控制标记前缀（【整页】/【补行】/【补行前:锚】/【替行:锚】/【删行】）。

    在按「/」切分之前整串剥除:个别【替行:…】的锚文本里含「/」,先切分会把标记切断。
    """
    return REVIEW_MARKER_RE.sub("", text)


def compile_text_replacements(
    cleaning_rules: dict[str, Any] | None,
) -> tuple[tuple[re.Pattern[str], str], ...]:
    """把 cleaning_rules.yaml 的 text_replacements 编译成 (pattern, replacement) 序列。"""
    rules = (cleaning_rules or {}).get("text_replacements") or []
    return tuple((re.compile(rule["pattern"]), rule["replacement"]) for rule in rules)


def apply_text_replacements(text: str, replacements: Replacements) -> str:
    for pattern, replacement in replacements:
        text = pattern.sub(replacement, text)
    return text


def _canonical_title(text: str, replacements: Replacements = ()) -> str:
    normalized = _canonical_text(text)
    normalized = TOC_ENUMERATOR_RE.sub("", normalized)
    normalized = re.sub(r"[·.…]+$", "", normalized)
    normalized = normalized.replace(" ", "")
    # 锚点图是可再生的派生产物,职责是与 vault 标题交叉核对,两侧必须落在同一归一化
    # 空间:否则每个已被 text_replacements 规范化的字（氽→汆、山查糕→山楂糕)都会变成
    # 一条假缺口。忠实原书的留痕由 work/page_review_md 的校对记录承担,不在这里。
    normalized = apply_text_replacements(normalized, replacements)
    # 括号全角归一（用户 2026-07-30「括号全部统一」)。_canonical_text 的 NFKC 会把原书
    # 目录里的全角括号压成半角,而 vault 菜名一侧走 title_policy 归一到全角:两侧必须
    # 落在同一形态,否则「牛（羊）肉煮馍」与「牛(羊)肉煮馍」永远精确对不上。
    normalized = to_fullwidth_parens(normalized)
    normalized = normalized.strip(TITLE_TRIM_CHARS)
    # 括号成对时不能剥。原先无条件 strip("()（）") 把「箸头面(油泼面)」削成
    # 「箸头面(油泼面」,只有落单的括号才是解析残留。
    if normalized.count("(") + normalized.count("（") != normalized.count(")") + normalized.count("）"):
        normalized = normalized.strip("()（）")
    return normalized.strip(TITLE_TRIM_CHARS)


def _is_toc_dish_title(title: str) -> bool:
    """目录条目解析结果的合法性校验:剥掉括号批注后必须像菜名。"""
    core = TOC_ANNOTATION_RE.sub("", title).strip(TITLE_TRIM_CHARS) or title
    return is_plausible_dish_title(core)


def _split_correct_content(text: str) -> list[str]:
    normalized = _strip_review_markers(_canonical_text(text))
    if not normalized:
        return []
    prepared = normalized.replace(" / ", "\n").replace("/", "\n")
    tokens = [token.strip() for token in prepared.splitlines() if token.strip()]
    return tokens


def _extract_toc_entries(
    correct_content: str,
    rejected: list[str] | None = None,
    replacements: Replacements = (),
    category_state: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """解析一页目录。

    `category_state` 是**按册**的分类上下文（形如 `{"category": "水产类"}`）:分类标题
    在原书里只印一次,后面的目录续页直接接着排菜名。不跨页续传的话,每张续页开头到
    下一个「…类」之间的条目就全部丢分类。调用方按册传同一个 dict 即可。
    """
    tokens = _split_correct_content(correct_content)
    if sum(1 for token in tokens if PAGE_REF_RE.search(token)) < 3:
        # 不是目录页:提前退出,不能污染分类上下文
        return []

    category = (category_state or {}).get("category", "")
    entries: list[dict[str, Any]] = []
    for token in tokens:
        if token == "目录":
            continue
        if token.endswith("类"):
            category = token
            if category_state is not None:
                category_state["category"] = category
            continue
        matched = TOC_ENTRY_RE.match(token)
        if not matched:
            continue
        title = _canonical_title(matched.group("title"), replacements)
        if not title:
            continue
        # 目录里也排着附录条目（「附:酱卤菜的特点及制作方法」「二、汤汁的配制及保养方法」),
        # 它们不是菜名锚点,放进映射只会在与正文菜名交叉核对时冒充缺口。
        if not _is_toc_dish_title(title):
            if rejected is not None:
                rejected.append(title)
            continue
        entries.append(
            {
                "title": title,
                "local_page": int(matched.group("page")),
                "category": category,
            }
        )
    return entries


def _extract_page_title_override(correct_content: str) -> str:
    tokens = _split_correct_content(correct_content)
    if not tokens:
        return ""
    first = tokens[0]
    if PAGE_REF_RE.search(first):
        # 带页码引用的行是目录条目,不是菜谱标题
        return ""
    if "原料" in first or "制法" in first or "特点" in first or first == "目录" or first.endswith("类"):
        return ""
    if ":" in first or "：" in first:
        return ""
    if len(first) > 30:
        return ""
    # 必须是「（数字）菜名」这种带闭括号的菜名编号。原先闭括号可选,
    # 于是续页首行的编号步骤（「2.取蒸碗两个,…」）和原料续行（「八角 一钱半 …」）
    # 都能匹配,首字被当成序号剥掉,剩下的正文冒充菜名。
    if not DISH_ENUMERATOR_RE.match(first):
        return ""

    title = _canonical_title(first)
    # 剥掉序号后还要像菜名（长度/句读/用量串/括号成对),否则宁可不给 override
    if title and is_plausible_dish_title(title):
        return title
    return ""


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _select_books(context, requested_ids: list[str] | None) -> list:
    books = load_books(context.book_manifest)
    if requested_ids:
        wanted = set(requested_ids)
        return [book for book in books if book.book_id in wanted]
    return [book for book in books if book.enabled and book.status != "pending"]


def _load_pages(context, requested_ids: list[str] | None) -> tuple[list[dict[str, Any]], dict[tuple[str, int], dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    lookup: dict[tuple[str, int], dict[str, Any]] = {}
    for book in _select_books(context, requested_ids):
        root = context.work_root / "normalized_json" / book.book_id
        for path in sorted(root.glob("page-*.json")):
            page = _load_json(path)
            rows.append(page)
            lookup[(book.book_id, int(page["local_page"]))] = page
    return rows, lookup


# OCR / 校对记录里给「印不清、认不出的字」留的占位符。它不是脏字,**不能清洗掉**:
# 「▢淀粉 二钱」（书2 p102）实为湿淀粉,「菜籽油 ▢钱」（书1 p75）「葱段 ▢钱」（书2 p103）
# 缺的是数词。替换成任何具体字都是编数据,所以只能当成校对信号往上报。
# 落在**原料区**的占位符最要紧:那里缺的往往正是用量,成品库会出现没有分量的原料。
PLACEHOLDER_CHARS = "▢□"


def _placeholder_ingredient_lines(pages: list[dict[str, Any]]) -> dict[tuple[str, int], list[str]]:
    """找出「原料区含占位符」的页,返回 {(册, 页): [涉及的原文行]}。

    原料区的判定直接借用分段器的 `_ingredient_region_mask`,与成品库口径一致;
    原料区会跨页,所以状态要按册在页序上传递（与 segment_book 同）。
    """
    by_book: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page in pages:
        by_book[page["book_id"]].append(page)

    found: dict[tuple[str, int], list[str]] = {}
    for book_id, book_pages in by_book.items():
        carry = False
        for page in sorted(book_pages, key=lambda item: int(item["local_page"])):
            blocks = [
                block for block in page.get("text_blocks", []) if normalize_text(block.get("text", ""))
            ]
            mask, carry = _ingredient_region_mask(blocks, carry)
            hits = [
                normalize_text(block["text"])
                for block, in_ingredients in zip(blocks, mask)
                if in_ingredients and any(char in block["text"] for char in PLACEHOLDER_CHARS)
            ]
            if hits:
                found[(book_id, int(page["local_page"]))] = hits
    return found


def _load_recipe_page_map(context, requested_ids: list[str] | None) -> dict[tuple[str, int], list[dict[str, Any]]]:
    recipe_map: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    wanted = set(requested_ids or [])
    for path in sorted((context.work_root / "recipe_candidates").glob("*.json")):
        book_id = path.stem
        if wanted and book_id not in wanted:
            continue
        for row in _load_json(path):
            for local_page in row.get("local_pages", []):
                recipe_map[(row["book_id"], int(local_page))].append(
                    {
                        "title": row.get("title", ""),
                        "aliases": list(row.get("aliases") or []),
                        "confidence": row.get("confidence", ""),
                        "status": row.get("status", ""),
                    }
                )
    return recipe_map


def _fold_title(title: str) -> str:
    """比对用的宽松键:去掉括号批注、分隔符与全半角差异。"""
    folded = TOC_ANNOTATION_RE.sub("", unicodedata.normalize("NFKC", title))
    return re.sub(r"[、—\-·,，/\s]", "", folded)


def _build_recipe_title_index(
    recipe_map: dict[tuple[str, int], list[dict[str, Any]]],
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    """每册「菜名 → 正文起始本地页」。同名取最小页（= local_pages[0]）。"""
    exact: dict[str, dict[str, int]] = defaultdict(dict)
    folded: dict[str, dict[str, int]] = defaultdict(dict)
    for (book_id, local_page), rows in recipe_map.items():
        for row in rows:
            for name in [row.get("title", ""), *(row.get("aliases") or [])]:
                name = (name or "").strip()
                if not name:
                    continue
                for index, key in ((exact, name), (folded, _fold_title(name))):
                    if not key:
                        continue
                    known = index[book_id].get(key)
                    if known is None or local_page < known:
                        index[book_id][key] = local_page
    return exact, folded


def _resolve_toc_local_pages(
    toc_map: dict[str, dict[int, list[dict[str, Any]]]],
    recipe_map: dict[tuple[str, int], list[dict[str, Any]]],
) -> tuple[dict[str, dict[int, list[dict[str, Any]]]], dict[str, int]]:
    """把锚点的**印刷**页码换成正文**本地**页。

    目录里印的是原书页码,与 PDF 本地页相差 7–13 页且册内不固定（插图页导致),照印刷
    页码去查分类会把分类边界整体放早,实测 327 道可判定菜里错 82 道（25.1%）。这里不建
    偏移映射表（偏移不固定,表本身就是新的错误来源),而是用已有的精确匹配定位:菜名能与
    正文对上的直接取该菜的起始本地页;对不上的按册内目录顺序在已定位锚点之间单调插值。
    原印刷页码保留在 `printed_page` 里备查。
    """
    exact_index, folded_index = _build_recipe_title_index(recipe_map)
    stats: Counter = Counter()
    resolved: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))

    for book_id, page_map in toc_map.items():
        # 目录顺序 = 印刷页码顺序
        flat = [(printed, entry) for printed, entries in sorted(page_map.items()) for entry in entries]
        located: list[int | None] = []
        for _printed, entry in flat:
            local = exact_index[book_id].get(entry["title"])
            source = "matched"
            if local is None:
                local = folded_index[book_id].get(_fold_title(entry["title"]))
                source = "matched_folded" if local is not None else "interpolated"
            located.append(local)
            entry["page_source"] = source

        for position, (printed, _entry) in enumerate(flat):
            if located[position] is not None:
                continue
            previous = next(
                ((located[i], flat[i][0]) for i in range(position - 1, -1, -1) if located[i] is not None),
                None,
            )
            following = next(
                ((located[i], flat[i][0]) for i in range(position + 1, len(flat)) if located[i] is not None),
                None,
            )
            if previous is not None:
                guess = previous[0] + (printed - previous[1])
                if following is not None:
                    guess = max(previous[0], min(guess, following[0]))
            elif following is not None:
                guess = max(1, following[0] - (following[1] - printed))
            else:
                guess = printed
            located[position] = guess

        for (printed, entry), local in zip(flat, located):
            entry["printed_page"] = printed
            entry["local_page"] = int(local)
            resolved[book_id][int(local)].append(entry)
            stats[entry["page_source"]] += 1

    return resolved, dict(stats)


def _load_confirmations(context) -> dict[tuple[str, int], dict[str, Any]]:
    rows = parse_confirmation_source(context.work_root / "page_review_md")
    return {(row["book_id"], int(row["local_page"])): row for row in rows if row["book_id"]}


def _build_confirmation_maps(
    confirmations: dict[tuple[str, int], dict[str, Any]],
    page_lookup: dict[tuple[str, int], dict[str, Any]],
    replacements: Replacements = (),
) -> tuple[dict[str, dict[int, list[dict[str, Any]]]], dict[str, dict[int, str]], dict[str, Any]]:
    toc_map: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    title_overrides: dict[str, dict[int, str]] = defaultdict(dict)

    stats = {
        "confirmed_pages": 0,
        "confirmed_toc_pages": 0,
        "toc_entries": 0,
        "toc_entries_rejected": 0,
        "toc_rejected_samples": [],
        "title_overrides": 0,
    }

    # 分类上下文按册续传,因此必须按 (册, 页) 顺序遍历
    category_states: dict[str, dict[str, str]] = defaultdict(dict)

    for key, row in sorted(confirmations.items()):
        if not row.get("confirmed"):
            continue
        stats["confirmed_pages"] += 1
        correct_content = row.get("correct_content", "")
        if not correct_content:
            continue

        rejected: list[str] = []
        toc_entries = _extract_toc_entries(
            correct_content, rejected, replacements, category_states[row["book_id"]]
        )
        if rejected:
            stats["toc_entries_rejected"] += len(rejected)
            stats["toc_rejected_samples"].extend(
                f"{row['book_id']} p{int(row['local_page']):04d}: {title}" for title in rejected
            )
        if toc_entries:
            stats["confirmed_toc_pages"] += 1
            stats["toc_entries"] += len(toc_entries)
            for entry in toc_entries:
                toc_map[row["book_id"]][entry["local_page"]].append(entry)
            continue

        page = page_lookup.get(key, {})
        page_kind = page.get("structure_hints", {}).get("page_kind", "")
        if page_kind in {"toc", "category"}:
            continue

        title = _extract_page_title_override(correct_content)
        if title:
            title_overrides[row["book_id"]][int(row["local_page"])] = title
            stats["title_overrides"] += 1

    return toc_map, title_overrides, stats


def _classify_page(
    page: dict[str, Any],
    recipe_anchors: list[dict[str, Any]],
    expected_toc_entries: list[dict[str, Any]],
    confirmation: dict[str, Any] | None,
    title_override: str | None,
    placeholder_lines: list[str] | None = None,
) -> dict[str, Any]:
    page_kind = page.get("structure_hints", {}).get("page_kind", "")
    warnings = list(page.get("warnings", []))
    recipe_anchor_count = len(recipe_anchors)
    expected_toc_count = len(expected_toc_entries)
    confirmed = bool(confirmation and confirmation.get("confirmed"))

    placeholder_lines = list(placeholder_lines or [])

    reasons: list[str] = []
    notes: list[str] = []
    severe = False

    if confirmed:
        notes.append("confirmed by user review")
    if placeholder_lines:
        notes.append(
            "unreadable-glyph placeholder in ingredient region: " + " / ".join(placeholder_lines)
        )
    if title_override:
        notes.append(f"title override available: {title_override}")
    if expected_toc_count:
        notes.append(f"confirmed toc starts on this page: {expected_toc_count}")
    if recipe_anchor_count >= 2:
        notes.append(f"recipe anchors detected on this page: {recipe_anchor_count}")

    multiple_title_warning = "multiple recipe title candidates on one page" in warnings
    other_warnings = [warning for warning in warnings if warning != "multiple recipe title candidates on one page"]

    if multiple_title_warning:
        if confirmed or expected_toc_count >= 2 or recipe_anchor_count >= 2:
            notes.append("multiple title candidates treated as a valid multi-anchor page")
        else:
            reasons.append("multiple title candidates without stable anchor evidence")
            severe = True

    for warning in other_warnings:
        if warning.startswith("suspicious text pattern matched"):
            reasons.append(warning)
            severe = True
        elif warning == "very sparse text":
            reasons.append(warning)
            severe = True
        elif warning == "empty cleaned text":
            reasons.append(warning)
            severe = True
        else:
            notes.append(warning)

    if page.get("confidence") == "failed":
        reasons.append("failed confidence")
        severe = True

    if not confirmed:
        if page_kind == "unresolved":
            reasons.append("unresolved page kind")
            severe = True
        elif page_kind == "continuation":
            if recipe_anchor_count:
                notes.append("continuation page already linked to recipe candidate")
            else:
                reasons.append("continuation page not linked to a recipe candidate")
                severe = True

    if confirmed:
        bucket = "safe_to_skip"
    elif severe:
        bucket = "must_review"
    elif page.get("confidence") == "medium":
        bucket = "optional_sample"
        notes.append("medium confidence page")
    elif page_kind == "continuation" and recipe_anchor_count:
        bucket = "optional_sample"
    elif page.get("confidence") == "high" and (recipe_anchor_count >= 2 or expected_toc_count >= 1 or title_override):
        bucket = "safe_to_skip"
    elif recipe_anchor_count >= 2 or expected_toc_count >= 1 or title_override:
        bucket = "optional_sample"
    else:
        bucket = "safe_to_skip"

    # 占位符是校对员**主动**标下的「这个字认不出」,所以这些页往往已经确认过、
    # 本来会被判成可跳过。这里把它们至少提到「建议复核」档,免得缺用量的原料悄悄进库。
    if placeholder_lines and bucket == "safe_to_skip":
        bucket = "optional_sample"

    return {
        "book_id": page["book_id"],
        "local_page": int(page["local_page"]),
        "page_kind": page_kind,
        "confidence": page.get("confidence", ""),
        "bucket": bucket,
        "confirmed": confirmed,
        "recipe_anchor_count": recipe_anchor_count,
        "expected_toc_count": expected_toc_count,
        "title_override": title_override,
        "reasons": reasons,
        "notes": notes,
        "warnings": warnings,
        "placeholder_ingredient_lines": placeholder_lines,
        "title_candidates": page.get("title_candidates", []),
    }


def build_review_priority_report(context, requested_ids: list[str] | None = None) -> tuple[Path, Path]:
    pages, page_lookup = _load_pages(context, requested_ids)
    recipe_map = _load_recipe_page_map(context, requested_ids)
    confirmation_map = _load_confirmations(context)
    replacements = compile_text_replacements(getattr(context, "cleaning_rules", None))
    toc_map, title_override_map, confirmation_stats = _build_confirmation_maps(
        confirmation_map, page_lookup, replacements
    )
    toc_map, page_resolution_stats = _resolve_toc_local_pages(toc_map, recipe_map)
    confirmation_stats["toc_page_resolution"] = page_resolution_stats
    confirmation_stats["toc_entries_without_category"] = sum(
        1 for page_map in toc_map.values() for entries in page_map.values() for entry in entries
        if not entry.get("category")
    )

    placeholder_map = _placeholder_ingredient_lines(pages)

    bucketed: dict[str, list[dict[str, Any]]] = {
        "must_review": [],
        "optional_sample": [],
        "safe_to_skip": [],
    }
    per_book_counts: dict[str, Counter] = defaultdict(Counter)
    summary_confidence = Counter()
    summary_page_kind = Counter()

    for page in sorted(pages, key=lambda item: (item["book_id"], int(item["local_page"]))):
        key = (page["book_id"], int(page["local_page"]))
        row = _classify_page(
            page=page,
            recipe_anchors=recipe_map.get(key, []),
            expected_toc_entries=toc_map[page["book_id"]].get(int(page["local_page"]), []),
            confirmation=confirmation_map.get(key),
            title_override=title_override_map[page["book_id"]].get(int(page["local_page"])),
            placeholder_lines=placeholder_map.get(key),
        )
        bucketed[row["bucket"]].append(row)
        per_book_counts[row["book_id"]][row["bucket"]] += 1
        summary_confidence[row["confidence"]] += 1
        summary_page_kind[row["page_kind"]] += 1

    multi_anchor_pages = [
        row
        for rows in bucketed.values()
        for row in rows
        if any("multi-anchor page" in note for note in row["notes"])
    ]

    report = {
        "summary": {
            "total_pages": len(pages),
            "confidence": dict(summary_confidence),
            "page_kind": dict(summary_page_kind),
            "must_review_count": len(bucketed["must_review"]),
            "optional_sample_count": len(bucketed["optional_sample"]),
            "safe_to_skip_count": len(bucketed["safe_to_skip"]),
            "confirmed_pages_used": confirmation_stats["confirmed_pages"],
            "confirmed_toc_pages": confirmation_stats["confirmed_toc_pages"],
            "toc_entries_extracted": confirmation_stats["toc_entries"],
            "toc_entries_rejected": confirmation_stats["toc_entries_rejected"],
            "toc_rejected_samples": confirmation_stats["toc_rejected_samples"],
            "toc_page_resolution": confirmation_stats["toc_page_resolution"],
            "toc_entries_without_category": confirmation_stats["toc_entries_without_category"],
            "title_overrides": confirmation_stats["title_overrides"],
            "multi_anchor_pages": len(multi_anchor_pages),
            "placeholder_ingredient_pages": len(placeholder_map),
            "placeholder_ingredient_lines": sum(len(lines) for lines in placeholder_map.values()),
        },
        "per_book": {
            book_id: {
                "must_review": counts["must_review"],
                "optional_sample": counts["optional_sample"],
                "safe_to_skip": counts["safe_to_skip"],
            }
            for book_id, counts in sorted(per_book_counts.items())
        },
        "must_review": bucketed["must_review"],
        "optional_sample": bucketed["optional_sample"],
        "safe_to_skip": bucketed["safe_to_skip"],
        "toc_anchor_map": {
            book_id: {
                f"{page:04d}": entries for page, entries in sorted(page_map.items())
            }
            for book_id, page_map in sorted(toc_map.items())
        },
        "title_override_map": {
            book_id: {
                f"{page:04d}": title for page, title in sorted(page_map.items())
            }
            for book_id, page_map in sorted(title_override_map.items())
        },
        "placeholder_ingredient_pages": [
            {"book_id": book_id, "local_page": local_page, "lines": lines}
            for (book_id, local_page), lines in sorted(placeholder_map.items())
        ],
    }

    json_path = context.work_root / "reports" / "review_priority.json"
    write_json(json_path, report)

    lines = [
        "# Review Priority",
        "",
        f"- 总页数: {report['summary']['total_pages']}",
        f"- 高置信页: {report['summary']['confidence'].get('high', 0)}",
        f"- 中置信页: {report['summary']['confidence'].get('medium', 0)}",
        f"- 低置信页: {report['summary']['confidence'].get('low', 0)}",
        f"- 必看页: {report['summary']['must_review_count']}",
        f"- 可抽查页: {report['summary']['optional_sample_count']}",
        f"- 可暂时跳过页: {report['summary']['safe_to_skip_count']}",
        "",
        "## 本次纳入的人工校对信号",
        f"- 已读取确认页: {report['summary']['confirmed_pages_used']}",
        f"- 已确认目录页: {report['summary']['confirmed_toc_pages']}",
        f"- 已提取目录锚点: {report['summary']['toc_entries_extracted']}",
        f"- 目录条目判为非菜名而剔除: {report['summary']['toc_entries_rejected']}",
        f"- 锚点页码定位: {report['summary']['toc_page_resolution']}（印刷页→本地页）",
        f"- 锚点缺分类: {report['summary']['toc_entries_without_category']}",
        f"- 已提取单页标题修正: {report['summary']['title_overrides']}",
        f"- 已识别多菜谱锚点页: {report['summary']['multi_anchor_pages']}",
        f"- 原料区含不可识字占位符（{PLACEHOLDER_CHARS}）的页: "
        f"{report['summary']['placeholder_ingredient_pages']}"
        f"（共 {report['summary']['placeholder_ingredient_lines']} 行）",
        "",
        "## 分书统计",
    ]

    for book_id, counts in sorted(report["per_book"].items()):
        lines.append(
            f"- {book_id}: 必看 {counts['must_review']} / 可抽查 {counts['optional_sample']} / 可暂时跳过 {counts['safe_to_skip']}"
        )

    lines.extend(
        [
            "",
            "## 复核规则更新",
            "- 已确认的页面不再进入必看清单。",
            "- `multiple recipe title candidates on one page` 不再自动视为错误。",
            "- 如果同页存在多个菜谱起始锚点，或目录明确说明该页有多个菜名起始，则记为多菜谱锚点页，降为可抽查。",
            "- continuation 页如果已经被现有 recipe candidate 覆盖，不再自动列为必看。",
            "- 已确认目录页提取出的菜名和页码会写入锚点映射，用于后续菜谱到图片的页级链接依据。",
            f"- 原料区里出现 `{PLACEHOLDER_CHARS}`（不可识字占位符）的页一律至少降为可抽查："
            "占位符常常正好占着用量的位置，成品库会出现没有分量的原料。占位符本身不清洗、不猜字。",
        ]
    )

    if report["placeholder_ingredient_pages"]:
        lines.extend(["", f"## 原料区含不可识字占位符（{PLACEHOLDER_CHARS}）"])
        for row in report["placeholder_ingredient_pages"]:
            for line in row["lines"]:
                lines.append(f"- {row['book_id']} p.{row['local_page']:04d}: {line}")

    if report["title_override_map"]:
        lines.extend(["", "## 已知标题修正"])
        for book_id, page_map in sorted(report["title_override_map"].items()):
            for page, title in sorted(page_map.items()):
                lines.append(f"- {book_id} p.{page}: {title}")

    if report["must_review"]:
        lines.extend(["", "## 必看页 Top 80"])
        for row in report["must_review"][:80]:
            detail = " | ".join(row["reasons"] or ["no explicit reason"])
            lines.append(
                f"- {row['book_id']} p.{row['local_page']:04d} | {row['page_kind']} | {row['confidence']} | {detail}"
            )

    if report["optional_sample"]:
        lines.extend(["", "## 可抽查页 Top 80"])
        for row in report["optional_sample"][:80]:
            detail = " | ".join(row["notes"] or row["reasons"] or ["sample page"])
            lines.append(
                f"- {row['book_id']} p.{row['local_page']:04d} | {row['page_kind']} | {row['confidence']} | {detail}"
            )

    md_path = context.work_root / "reports" / "review_priority.md"
    write_text(md_path, "\n".join(lines).strip() + "\n")

    write_json(context.work_root / "reports" / "toc_anchor_map.json", report["toc_anchor_map"])
    write_json(context.work_root / "reports" / "title_override_map.json", report["title_override_map"])
    return json_path, md_path
