from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BookEntry:
    book_id: str
    series: int
    file_name: str
    file_path: str
    mineru_json: str | None
    status: str
    enabled: bool

    @property
    def pdf_path(self) -> Path:
        return Path(self.file_path)

    @property
    def json_path(self) -> Path | None:
        return Path(self.mineru_json) if self.mineru_json else None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineContext:
    project_root: Path
    work_root: Path
    vault_root: Path
    logs_root: Path
    book_manifest: Path
    pipeline_config: dict[str, Any]
    cleaning_rules: dict[str, Any]
    obsidian_schema: dict[str, Any]


@dataclass
class NormalizedPage:
    book_id: str
    book_file: str
    series: int
    local_page: int
    source_pdf_path: str
    source_json_path: str
    raw_text: str
    cleaned_text: str
    text_blocks: list[dict[str, Any]] = field(default_factory=list)
    title_candidates: list[str] = field(default_factory=list)
    structure_hints: dict[str, Any] = field(default_factory=dict)
    ocr_engine: str = ""
    confidence: str = "failed"
    warnings: list[str] = field(default_factory=list)
    review_needed: bool = False
    rendered_page_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RecipeCandidate:
    title: str
    aliases: list[str]
    series: int
    book_id: str
    book_file: str
    local_pages: list[int]
    source_pdf: str
    source_json: str
    ingredients: list[str]
    seasonings: list[str]
    steps: list[str]
    tips: list[str]
    raw_excerpt: str
    related_notes: list[str]
    ocr_engine: str
    confidence: str
    status: str
    review_needed: bool
    source_links: list[str]
    warnings: list[str] = field(default_factory=list)
    note_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageFallbackNote:
    title: str
    series: int
    book_id: str
    book_file: str
    local_pages: list[int]
    source_pdf: str
    source_json: str
    raw_excerpt: str
    cleaned_text: str
    related_notes: list[str]
    ocr_engine: str
    confidence: str
    status: str
    review_needed: bool
    source_links: list[str]
    warnings: list[str] = field(default_factory=list)
    rendered_page_path: str | None = None
    note_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewItem:
    book_id: str
    local_page: int
    reason: str
    source_pdf_path: str
    source_json_path: str
    rendered_page_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
