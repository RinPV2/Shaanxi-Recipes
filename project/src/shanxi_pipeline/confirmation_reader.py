from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .utils import ensure_dir, normalize_text, write_json, write_text

SECTION_HEADER = re.compile(r"^##\s+(?P<book_id>sxcp-\d+)\s+p\.(?P<local_page>\d+)\s*$")
PAGE_HEADER = re.compile(r"^#\s+(?P<book_id>sxcp-\d+)\s+p\.(?P<local_page>\d+)\s*$")


def _split_sections(text: str) -> list[dict]:
    rows: list[dict] = []
    current: dict | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        matched = SECTION_HEADER.match(line)
        if matched:
            if current:
                rows.append(current)
            current = {
                "book_id": matched.group("book_id"),
                "local_page": int(matched.group("local_page")),
                "lines": [],
            }
            continue
        if current is not None:
            current["lines"].append(line)
    if current:
        rows.append(current)
    return rows


def _parse_bullet_map(lines: list[str]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for line in lines:
        if not line.startswith("- "):
            continue
        body = line[2:]
        if ":" not in body:
            continue
        key, value = body.split(":", 1)
        payload[normalize_text(key)] = value.strip()
    return payload


def _extract_value(payload: dict[str, str], *keys: str) -> str:
    for key in keys:
        if key in payload:
            return payload[key]
    return ""


def parse_confirmation_markdown(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    rows = []
    for section in _split_sections(text):
        bullets = _parse_bullet_map(section["lines"])
        notes = _extract_value(bullets, "notes")
        correct_content = _extract_value(bullets, "正确内容", "????")
        confirm_mark = _extract_value(bullets, "确认勾", "???")
        rendered_page_path = _extract_value(bullets, "rendered_page_path")
        title_candidates = _extract_value(bullets, "title_candidates")
        rows.append(
            {
                "book_id": section["book_id"],
                "local_page": section["local_page"],
                "confidence": _extract_value(bullets, "confidence"),
                "reasons": _extract_value(bullets, "reasons"),
                "title_candidates_raw": title_candidates,
                "rendered_page_path": rendered_page_path,
                "current_recipe_candidates_raw": _extract_value(bullets, "current_recipe_candidates"),
                "current_fallback_candidates_raw": _extract_value(bullets, "current_fallback_candidates"),
                "content_preview": _extract_value(bullets, "content_preview"),
                "notes": notes,
                "correct_content": correct_content,
                "confirm_mark": confirm_mark,
                "confirmed": "[x]" in confirm_mark.lower(),
            }
        )
    return rows


def parse_page_review_markdown(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    book_id = ""
    local_page = 0
    for line in text.splitlines():
        matched = PAGE_HEADER.match(line.strip())
        if matched:
            book_id = matched.group("book_id")
            local_page = int(matched.group("local_page"))
            break

    bullets = _parse_bullet_map(text.splitlines())
    notes = _extract_value(bullets, "notes")
    correct_content = _extract_value(bullets, "正确内容")
    confirm_mark = _extract_value(bullets, "确认勾")
    return {
        "book_id": book_id,
        "local_page": local_page,
        "confidence": _extract_value(bullets, "置信度", "confidence"),
        "reasons": _extract_value(bullets, "reasons"),
        "title_candidates_raw": _extract_value(bullets, "标题候选", "title_candidates"),
        "rendered_page_path": _extract_value(bullets, "image_path", "rendered_page_path"),
        "current_recipe_candidates_raw": _extract_value(bullets, "菜谱候选", "current_recipe_candidates"),
        "current_fallback_candidates_raw": _extract_value(bullets, "回退候选", "current_fallback_candidates"),
        "content_preview": "",
        "notes": notes,
        "correct_content": correct_content,
        "confirm_mark": confirm_mark,
        "confirmed": "[x]" in confirm_mark.lower(),
        "source_path": str(path),
    }


def parse_confirmation_source(path: Path) -> list[dict]:
    if path.is_dir():
        rows = []
        for md_path in sorted(path.glob("*/p*.md")):
            rows.append(parse_page_review_markdown(md_path))
        return rows
    return parse_confirmation_markdown(path)


def summarize_confirmations(rows: list[dict]) -> dict:
    confirmed = [row for row in rows if row["confirmed"]]
    notes_counter = Counter()
    rule_buckets: dict[str, list[dict]] = defaultdict(list)

    for row in confirmed:
        note = normalize_text(row["notes"])
        if note:
            notes_counter[note] += 1
            if "括号" in note and "英文" in note:
                rule_buckets["normalize_brackets_to_ascii"].append(row)
            if "空格" in note and ("去除" in note or "去掉" in note):
                rule_buckets["remove_spurious_inner_spaces"].append(row)
            if "内容正确" in note:
                rule_buckets["accept_current_content"].append(row)
            if "属于" in note or "开始" in note:
                rule_buckets["respect_category_boundaries"].append(row)
            if "两个菜谱标题" in note or "三个菜谱" in note:
                rule_buckets["multi_recipe_anchor_page_is_valid"].append(row)
            if "通假字" in note or "其实是" in note:
                rule_buckets["apply_title_override"].append(row)

    learned_rules = []
    for rule_name, examples in rule_buckets.items():
        learned_rules.append(
            {
                "rule_name": rule_name,
                "evidence_count": len(examples),
                "pages": [f"{item['book_id']}#p{item['local_page']:04d}" for item in examples],
                "sample_notes": list(dict.fromkeys(item["notes"] for item in examples if item["notes"]))[:5],
            }
        )

    return {
        "confirmed_count": len(confirmed),
        "all_entries_count": len(rows),
        "notes_frequency": [{"note": note, "count": count} for note, count in notes_counter.most_common()],
        "learned_rules": learned_rules,
        "confirmed_entries": confirmed,
    }


def write_confirmation_learning(report_root: Path, rows: list[dict]) -> tuple[Path, Path, Path]:
    ensure_dir(report_root)
    summary = summarize_confirmations(rows)

    records_path = report_root / "confirmation_records.json"
    write_json(records_path, summary["confirmed_entries"])

    rules_path = report_root / "learned_confirmation_rules.json"
    write_json(
        rules_path,
        {
            "confirmed_count": summary["confirmed_count"],
            "all_entries_count": summary["all_entries_count"],
            "notes_frequency": summary["notes_frequency"],
            "learned_rules": summary["learned_rules"],
        },
    )

    lines = [
        "# Learned Confirmation Rules",
        "",
        f"- Confirmed entries read: {summary['confirmed_count']}",
        f"- Total queue entries parsed: {summary['all_entries_count']}",
        "",
        "## Learned Rules",
    ]
    if summary["learned_rules"]:
        for rule in summary["learned_rules"]:
            lines.append(f"- {rule['rule_name']}: {rule['evidence_count']} pages")
            lines.append(f"  pages: {', '.join(rule['pages'])}")
            if rule["sample_notes"]:
                lines.append(f"  notes: {' | '.join(rule['sample_notes'])}")
    else:
        lines.append("- No stable repeated rules extracted yet.")

    lines.extend(["", "## Confirmed Pages"])
    for item in summary["confirmed_entries"]:
        lines.append(
            f"- {item['book_id']} p.{item['local_page']}: notes={item['notes'] or '无'} | correct_content={'有' if item['correct_content'] else '无'}"
        )

    md_path = report_root / "learned_confirmation_rules.md"
    write_text(md_path, "\n".join(lines).strip() + "\n")
    return records_path, rules_path, md_path
