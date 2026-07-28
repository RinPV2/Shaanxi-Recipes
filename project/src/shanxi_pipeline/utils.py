from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import yaml

INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
WHITESPACE = re.compile(r"\s+")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    payload = asdict(data) if is_dataclass(data) else data
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def dump_yaml(data: Any) -> str:
    payload = asdict(data) if is_dataclass(data) else data
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=1000)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ").replace("\t", " ")
    lines = [WHITESPACE.sub(" ", line).strip() for line in text.split("\n")]
    compact = "\n".join(line for line in lines if line)
    compact = re.sub(r"\n{3,}", "\n\n", compact)
    return compact.strip()


def safe_filename(value: str, max_length: int = 80) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = INVALID_FILENAME.sub("-", normalized)
    normalized = re.sub(r"[ ]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip(" .-_")
    if not normalized:
        normalized = "untitled"
    return normalized[:max_length].rstrip(" .-_")


# 原书菜名常为排版对齐在字间插空格（「糖 醋 排 骨」「炝 肚 块」）。这些空格会一路
# 渗进 vault 标题、笔记文件名和站点 URL（如 sxcp-2-p0048-糖-醋-排-骨）。
# 只删与汉字或括号相邻的空格，避免误伤可能存在的西文内容。
_TITLE_PAD = re.compile(r"(?<=[一-鿿（）()、])\s+|\s+(?=[一-鿿（）()、])")


def strip_recipe_enumerator(title: str) -> str:
    cleaned = normalize_text(title)
    cleaned = re.sub(r"^[（(]?[一二三四五六七八九十百零〇0-9]+[）)]\s*", "", cleaned)
    cleaned = _TITLE_PAD.sub("", cleaned)
    return cleaned.strip("：: ")


def setup_logging(log_dir: Path, log_name: str = "pipeline") -> logging.Logger:
    ensure_dir(log_dir)
    logger = logging.getLogger("shanxi_pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    file_handler = logging.FileHandler(log_dir / f"{log_name}.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def split_numbered_steps(text: str) -> list[str]:
    cleaned = normalize_text(text)
    if not cleaned:
        return []
    parts = re.split(r"(?=(?:^|[\n。；; ])(?:\d+|[一二三四五六七八九十]+)[\.、])", cleaned)
    return [part.strip(" \n") for part in parts if part.strip(" \n")] or [cleaned]


def list_to_bullets(values: Iterable[str]) -> str:
    items = [normalize_text(value) for value in values if normalize_text(value)]
    if not items:
        return "- 无\n"
    return "".join(f"- {item}\n" for item in items)
