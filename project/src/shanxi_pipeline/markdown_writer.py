from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import PageFallbackNote, RecipeCandidate
from .utils import dump_yaml, ensure_dir, list_to_bullets, safe_filename, write_text


def recipe_filename(recipe: RecipeCandidate) -> str:
    return f"{recipe.book_id}-p{recipe.local_pages[0]:04d}-{safe_filename(recipe.title)}.md"


def fallback_filename(note: PageFallbackNote) -> str:
    return f"{note.book_id}-page-{note.local_pages[0]:04d}-fallback.md"


def render_recipe_markdown(recipe: RecipeCandidate, dish_category: str = "") -> str:
    frontmatter: dict[str, Any] = {
        "title": recipe.title,
        "aliases": recipe.aliases,
        "series": recipe.series,
        "book_id": recipe.book_id,
        "book_file": recipe.book_file,
        "local_pages": recipe.local_pages,
        "source_pdf": recipe.source_pdf,
        "source_json": recipe.source_json,
        "ingredients": recipe.ingredients,
        "seasonings": recipe.seasonings,
        "steps": recipe.steps,
        "tips": recipe.tips,
        "raw_excerpt": recipe.raw_excerpt,
        "related_notes": recipe.related_notes,
        "ocr_engine": recipe.ocr_engine,
        "confidence": recipe.confidence,
        "status": recipe.status,
        "review_needed": recipe.review_needed,
        "source_links": recipe.source_links,
        "dish_category": dish_category,
        "tags": ["shanxi-cookbook", "recipe", recipe.book_id, f"series-{recipe.series}"],
    }
    sections = [
        "---",
        dump_yaml(frontmatter).strip(),
        "---",
        "",
        f"# {recipe.title}",
        "",
        "## 来源",
        f"- 书目: {recipe.book_file}",
        f"- 本地页码: {', '.join(str(page) for page in recipe.local_pages)}",
        f"- PDF: `{recipe.source_pdf}`",
        f"- MinerU JSON: `{recipe.source_json}`",
        "",
        "## 食材",
        list_to_bullets(recipe.ingredients).rstrip(),
        "",
        "## 调料",
        list_to_bullets(recipe.seasonings).rstrip(),
        "",
        "## 做法",
        list_to_bullets(recipe.steps).rstrip(),
        "",
        "## 提示",
        list_to_bullets(recipe.tips).rstrip(),
        "",
        "## OCR 不确定内容",
        list_to_bullets(recipe.warnings or ["无"]).rstrip(),
    ]
    return "\n".join(sections).strip() + "\n"


def render_fallback_markdown(note: PageFallbackNote) -> str:
    frontmatter: dict[str, Any] = {
        "title": note.title,
        "series": note.series,
        "book_id": note.book_id,
        "book_file": note.book_file,
        "local_pages": note.local_pages,
        "source_pdf": note.source_pdf,
        "source_json": note.source_json,
        "raw_excerpt": note.raw_excerpt,
        "related_notes": note.related_notes,
        "ocr_engine": note.ocr_engine,
        "confidence": note.confidence,
        "status": note.status,
        "review_needed": note.review_needed,
        "source_links": note.source_links,
        "rendered_page_path": note.rendered_page_path,
        "tags": ["shanxi-cookbook", "page-fallback", note.book_id, f"series-{note.series}"],
    }
    sections = [
        "---",
        dump_yaml(frontmatter).strip(),
        "---",
        "",
        f"# {note.title}",
        "",
        "## 来源",
        f"- 书目: {note.book_file}",
        f"- 本地页码: {', '.join(str(page) for page in note.local_pages)}",
        f"- PDF: `{note.source_pdf}`",
        f"- MinerU JSON: `{note.source_json}`",
        "",
        "## 页面文本",
        note.cleaned_text or "无",
        "",
        "## OCR 不确定内容",
        list_to_bullets(note.warnings or ["无"]).rstrip(),
    ]
    return "\n".join(sections).strip() + "\n"


def write_markdown(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    write_text(path, content)
