from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .confirmation_reader import parse_confirmation_markdown, parse_confirmation_source
from .manifest import load_books
from .utils import dump_yaml, ensure_dir, normalize_text, write_json, write_text


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_confirmation_map(source: Path) -> dict[tuple[str, int], dict]:
    if not source.exists():
        return {}
    rows = parse_confirmation_markdown(source)
    return {(row["book_id"], int(row["local_page"])): row for row in rows}


def _load_recipe_map(root: Path) -> dict[tuple[str, int], list[dict]]:
    recipe_map: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for path in sorted(root.glob("*.json")):
        for row in _load_json(path):
            for local_page in row.get("local_pages", []):
                recipe_map[(row["book_id"], int(local_page))].append(
                    {
                        "title": row["title"],
                        "confidence": row["confidence"],
                        "status": row["status"],
                        "note_path": row.get("note_path"),
                    }
                )
    return recipe_map


def _load_fallback_map(root: Path) -> dict[tuple[str, int], list[dict]]:
    fallback_map: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for path in sorted(root.glob("*/*.json")):
        row = _load_json(path)
        for local_page in row.get("local_pages", []):
            fallback_map[(row["book_id"], int(local_page))].append(
                {
                    "title": row["title"],
                    "confidence": row["confidence"],
                    "status": row["status"],
                    "note_path": row.get("note_path"),
                }
            )
    return fallback_map


def render_page_review_markdown(
    page: dict,
    book_file: str,
    image_path: str,
    image_relative_path: str | None = None,
    recipe_candidates: list[dict] | None = None,
    fallback_candidates: list[dict] | None = None,
    confirmation: dict | None = None,
) -> str:
    if image_relative_path is None:
        image_relative_path = image_path
    recipe_candidates = recipe_candidates or []
    fallback_candidates = fallback_candidates or []
    notes = confirmation["notes"] if confirmation else ""
    correct_content = confirmation["correct_content"] if confirmation else ""
    confirm_mark = confirmation["confirm_mark"] if confirmation else "[ ]"

    frontmatter = {
        "book_id": page["book_id"],
        "book_file": book_file,
        "series": page["series"],
        "local_page": page["local_page"],
        "confidence": page["confidence"],
        "review_needed": page["review_needed"],
        "image_path": image_path,
        "source_pdf_path": page["source_pdf_path"],
        "source_json_path": page["source_json_path"],
        "title_candidates": page.get("title_candidates", []),
        "current_recipe_candidates": [row["title"] for row in recipe_candidates],
        "current_fallback_candidates": [row["title"] for row in fallback_candidates],
        "warnings": page.get("warnings", []),
    }

    lines = [
        "---",
        dump_yaml(frontmatter).strip(),
        "---",
        "",
        f"# {page['book_id']} p.{page['local_page']}",
        "",
        "## 页面信息",
        f"- 书名: {book_file}",
        f"- 本地页码: {page['local_page']}",
        f"- 置信度: {page['confidence']}",
        f"- 需要复核: {page['review_needed']}",
        f"- 图片路径: {image_path}",
        "",
        "## 页面图片",
        f"![{page['book_id']} p.{page['local_page']}]({image_relative_path})",
        "",
        "## 当前候选",
        f"- 标题候选: {json.dumps(page.get('title_candidates', []), ensure_ascii=False)}",
        f"- 菜谱候选: {json.dumps([row['title'] for row in recipe_candidates], ensure_ascii=False)}",
        f"- 回退候选: {json.dumps([row['title'] for row in fallback_candidates], ensure_ascii=False)}",
        "",
        "## 警告",
        f"- {json.dumps(page.get('warnings', []), ensure_ascii=False)}",
        "",
        "## 当前采集文本",
        page.get("cleaned_text", "") or "无",
        "",
        "## 原始 OCR 文本",
        page.get("raw_text", "") or "无",
        "",
        "## 校对记录",
        f"- notes: {notes}",
        f"- 正确内容: {correct_content}",
        f"- 确认勾: {confirm_mark}",
        "",
    ]
    return "\n".join(lines)


def build_page_review_dataset(context, requested_ids: list[str] | None = None) -> tuple[Path, int]:
    review_md_root = ensure_dir(context.work_root / "page_review_md")
    books = load_books(context.book_manifest)
    wanted = set(requested_ids or [])
    if wanted:
        books = [book for book in books if book.book_id in wanted]
    else:
        books = [book for book in books if book.enabled and book.status != "pending"]

    confirmation_map = _load_confirmation_map(context.work_root / "reports" / "user_confirmation_queue.md")
    # 已写入 page_review_md 的校对记录优先于 legacy 队列,防止 rebuild 抹掉既有确认
    if review_md_root.exists():
        for row in parse_confirmation_source(review_md_root):
            if not row["book_id"]:
                continue
            if row["confirmed"] or row["notes"] or row["correct_content"]:
                confirmation_map[(row["book_id"], int(row["local_page"]))] = row
    recipe_map = _load_recipe_map(context.work_root / "recipe_candidates")
    fallback_map = _load_fallback_map(context.work_root / "page_fallback_notes")

    manifest_rows = []
    total_pages = 0
    for book in books:
        normalized_root = context.work_root / "normalized_json" / book.book_id
        image_root = context.work_root / "review_queue" / "rendered" / book.book_id
        book_review_root = ensure_dir(review_md_root / book.book_id)

        for page_path in sorted(normalized_root.glob("page-*.json")):
            page = _load_json(page_path)
            key = (book.book_id, int(page["local_page"]))
            image_path = image_root / f"p{int(page['local_page']):04d}.png"
            review_md_path = book_review_root / f"p{int(page['local_page']):04d}.md"
            image_relative_path = Path("..") / ".." / "review_queue" / "rendered" / book.book_id / image_path.name
            markdown = render_page_review_markdown(
                page=page,
                book_file=book.file_name,
                image_path=str(image_path),
                image_relative_path=image_relative_path.as_posix(),
                recipe_candidates=recipe_map.get(key, []),
                fallback_candidates=fallback_map.get(key, []),
                confirmation=confirmation_map.get(key),
            )
            write_text(review_md_path, markdown)
            manifest_rows.append(
                {
                    "book_id": book.book_id,
                    "book_file": book.file_name,
                    "series": book.series,
                    "local_page": int(page["local_page"]),
                    "confidence": page["confidence"],
                    "review_needed": page["review_needed"],
                    "image_path": str(image_path),
                    "markdown_path": str(review_md_path),
                    "title_candidates": page.get("title_candidates", []),
                    "warnings": page.get("warnings", []),
                }
            )
            total_pages += 1

        page_links = []
        for page_path in sorted(book_review_root.glob("p*.md")):
            local_page = int(page_path.stem[1:])
            label = f"p.{local_page:04d}"
            page_links.append(f"- [{label}](./{page_path.name})")
        index_lines = [
            f"# {book.book_id} Page Review",
            "",
            f"- 书名: {book.file_name}",
            f"- 页数: {len(page_links)}",
            "",
            "## 页面列表",
            *page_links,
            "",
        ]
        write_text(book_review_root / "index.md", "\n".join(index_lines))

    root_index_lines = [
        "# Page Review Index",
        "",
        "## Books",
    ]
    for book in books:
        root_index_lines.append(f"- [{book.book_id}](./{book.book_id}/index.md)")
    root_index_lines.append("")
    write_text(review_md_root / "index.md", "\n".join(root_index_lines))

    manifest_path = context.work_root / "reports" / "page_review_manifest.json"
    write_json(manifest_path, manifest_rows)
    return manifest_path, total_pages
