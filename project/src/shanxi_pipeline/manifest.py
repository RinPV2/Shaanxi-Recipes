from __future__ import annotations

from pathlib import Path

import yaml

from .models import BookEntry
from .utils import dump_yaml, ensure_dir, normalize_text

DEFAULT_BOOKS = [
    {
        "book_id": "sxcp-1",
        "series": 1,
        "file_name": "陕西菜谱1.pdf",
        "file_path": "C:/hobby/Shanxi/陕西菜谱1.pdf",
        "mineru_json": None,
        "status": "pending",
        "enabled": False,
    },
    {
        "book_id": "sxcp-2",
        "series": 2,
        "file_name": "陕西菜谱2.pdf",
        "file_path": "C:/hobby/Shanxi/陕西菜谱2.pdf",
        "mineru_json": "C:/hobby/Shanxi/MinerU_陕西菜谱2__20260328040931.json",
        "status": "ready",
        "enabled": True,
    },
    {
        "book_id": "sxcp-3",
        "series": 3,
        "file_name": "陕西菜谱3.pdf",
        "file_path": "C:/hobby/Shanxi/陕西菜谱3.pdf",
        "mineru_json": "C:/hobby/Shanxi/MinerU_陕西菜谱3__20260328040247.json",
        "status": "ready",
        "enabled": True,
    },
    {
        "book_id": "sxcp-4",
        "series": 4,
        "file_name": "陕西菜谱4.pdf",
        "file_path": "C:/hobby/Shanxi/陕西菜谱4.pdf",
        "mineru_json": "C:/hobby/Shanxi/MinerU_陕西菜谱4__20260328035609.json",
        "status": "ready",
        "enabled": True,
    },
]


def normalize_book_manifest(path: Path) -> list[BookEntry]:
    existing = {}
    if path.exists():
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for row in payload.get("books", []):
            book_id = row.get("book_id")
            if book_id:
                existing[book_id] = row

    normalized = []
    for default in DEFAULT_BOOKS:
        merged = dict(default)
        merged.update(existing.get(default["book_id"], {}))
        merged["file_name"] = normalize_text(merged["file_name"])
        normalized.append(merged)

    ensure_dir(path.parent)
    path.write_text(dump_yaml({"books": normalized}), encoding="utf-8")
    return [BookEntry(**row) for row in normalized]


def load_books(path: Path) -> list[BookEntry]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [BookEntry(**row) for row in payload.get("books", [])]


def upsert_book(path: Path, updated_book: BookEntry) -> list[BookEntry]:
    books = normalize_book_manifest(path)
    merged = [updated_book if book.book_id == updated_book.book_id else book for book in books]
    path.write_text(dump_yaml({"books": [book.to_dict() for book in merged]}), encoding="utf-8")
    return merged
