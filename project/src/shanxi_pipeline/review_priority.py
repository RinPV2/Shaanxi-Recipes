from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .confirmation_reader import parse_confirmation_source
from .manifest import load_books
from .utils import normalize_text, write_json, write_text

PAGE_REF_RE = re.compile(r"[（(]\s*(?P<page>\d+)\s*[.)）]")
TOC_ENTRY_RE = re.compile(r"^(?P<title>.+?)\s*(?:[.…·]+|\.+)\s*[（(]\s*(?P<page>\d+)\s*[.)）]\s*$")
RECIPE_ENUMERATOR_RE = re.compile(r"^[（(]?[一二三四五六七八九十百千零〇\d]+[)）]?\s*")


def _canonical_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", normalize_text(text))
    normalized = normalized.replace("／", "/")
    return normalized.strip()


def _canonical_title(text: str) -> str:
    normalized = _canonical_text(text)
    normalized = RECIPE_ENUMERATOR_RE.sub("", normalized)
    normalized = re.sub(r"[·.…]+$", "", normalized)
    normalized = normalized.replace(" ", "")
    return normalized.strip("()（）.- ")


def _split_correct_content(text: str) -> list[str]:
    normalized = _canonical_text(text)
    if not normalized:
        return []
    prepared = normalized.replace(" / ", "\n").replace("/", "\n")
    tokens = [token.strip() for token in prepared.splitlines() if token.strip()]
    return tokens


def _extract_toc_entries(correct_content: str) -> list[dict[str, Any]]:
    tokens = _split_correct_content(correct_content)
    if sum(1 for token in tokens if PAGE_REF_RE.search(token)) < 3:
        return []

    category = ""
    entries: list[dict[str, Any]] = []
    for token in tokens:
        if token == "目录":
            continue
        if token.endswith("类"):
            category = token
            continue
        matched = TOC_ENTRY_RE.match(token)
        if not matched:
            continue
        title = _canonical_title(matched.group("title"))
        if not title:
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
    if not RECIPE_ENUMERATOR_RE.match(first):
        return ""

    for token in tokens[:1]:
        if "原料" in token or "制法" in token or "特点" in token or "目录" == token or token.endswith("类"):
            continue
        if ":" in token or "：" in token:
            continue
        if len(token) > 30:
            continue
        if not RECIPE_ENUMERATOR_RE.match(token):
            continue
        title = _canonical_title(token)
        if title:
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
                        "confidence": row.get("confidence", ""),
                        "status": row.get("status", ""),
                    }
                )
    return recipe_map


def _load_confirmations(context) -> dict[tuple[str, int], dict[str, Any]]:
    rows = parse_confirmation_source(context.work_root / "page_review_md")
    return {(row["book_id"], int(row["local_page"])): row for row in rows if row["book_id"]}


def _build_confirmation_maps(
    confirmations: dict[tuple[str, int], dict[str, Any]],
    page_lookup: dict[tuple[str, int], dict[str, Any]],
) -> tuple[dict[str, dict[int, list[dict[str, Any]]]], dict[str, dict[int, str]], dict[str, Any]]:
    toc_map: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    title_overrides: dict[str, dict[int, str]] = defaultdict(dict)

    stats = {
        "confirmed_pages": 0,
        "confirmed_toc_pages": 0,
        "toc_entries": 0,
        "title_overrides": 0,
    }

    for key, row in confirmations.items():
        if not row.get("confirmed"):
            continue
        stats["confirmed_pages"] += 1
        correct_content = row.get("correct_content", "")
        if not correct_content:
            continue

        toc_entries = _extract_toc_entries(correct_content)
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
) -> dict[str, Any]:
    page_kind = page.get("structure_hints", {}).get("page_kind", "")
    warnings = list(page.get("warnings", []))
    recipe_anchor_count = len(recipe_anchors)
    expected_toc_count = len(expected_toc_entries)
    confirmed = bool(confirmation and confirmation.get("confirmed"))

    reasons: list[str] = []
    notes: list[str] = []
    severe = False

    if confirmed:
        notes.append("confirmed by user review")
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
        "title_candidates": page.get("title_candidates", []),
    }


def build_review_priority_report(context, requested_ids: list[str] | None = None) -> tuple[Path, Path]:
    pages, page_lookup = _load_pages(context, requested_ids)
    recipe_map = _load_recipe_page_map(context, requested_ids)
    confirmation_map = _load_confirmations(context)
    toc_map, title_override_map, confirmation_stats = _build_confirmation_maps(confirmation_map, page_lookup)

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
            "title_overrides": confirmation_stats["title_overrides"],
            "multi_anchor_pages": len(multi_anchor_pages),
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
        f"- 已提取单页标题修正: {report['summary']['title_overrides']}",
        f"- 已识别多菜谱锚点页: {report['summary']['multi_anchor_pages']}",
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
        ]
    )

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
