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

# MinerU 把原书的「〇」(U+3007 IDEOGRAPHIC NUMBER ZERO) 时而读成几何符号「○」(U+25CB)：
# 字形几乎一样，码位不同。菜名编号里只要出现一次，is_recipe_title / strip_recipe_enumerator /
# page_normalizer.RECIPE_ENUMERATOR 的数字字符类就匹配不到，那道菜不再算标题，
# 整篇被上一道菜吞掉（（一○八）奶汤锅子鱼、（一一○）清汤鱼丸、（七○）锅烧羊肉、
# （一○八）花生辣鸡丁；书3 的（四○）大肉饼、（一○八）宝鸡油茶已被校对员逐页手工绕过）。
#
# 必须放在 normalize_text 而不是 cleaning_rules.text_replacements 里：correction_applier
# 早于 normalize_page（= 应用 text_replacements 的地方）就要用 is_recipe_title 判定
# block_type，那时替换规则还没跑，校对写回的正确菜名依旧被定成 text 块；
# 而 find_recipe_title_positions 只看 title 块，之后再替换也救不回来。
# 这属于同形异码归一（与本函数已有的 U+3000→空格 同类），不是原书用字取舍。
_ZERO_LOOKALIKES = str.maketrans({"○": "〇", "◯": "〇"})


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
    text = text.translate(_ZERO_LOOKALIKES)
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

# 菜名编号：原书作「（一一〇）」，OCR 偶尔读成阿拉伯数字，前括号有时整个丢掉。
_RECIPE_ENUM_DIGITS = "一二三四五六七八九十百零〇0-9"
# **编号被铅印污损到不可辨**时的形态。书2 p109（印刷页 99）「明月红松鸡」的编号
# 在扫描件上是一团墨迹（20× 页图：三个字位全部糊成连片的黑块，笔画无一可辨），
# MinerU 把那团墨迹读成了一串拉丁字母：`（Triflox Wreumn Bionnn）明月红松鸡`。
# 任何数字字符类都救不了它，这道菜因此不算标题，整篇（本地页 109–110）被上一道
# 「酱爆鸡丁」吞了进去（曾作为已知缺陷记在 CLAUDE.md 里）。
#
# 判据只认「**成对**括号 + 纯拉丁（可含空格/点/间隔号） + 后面跟着一个像菜名的串」
# ——`is_recipe_title` 随后还要过 `is_plausible_dish_title`。全库（parsed_pages，
# 四册 641 页、未经任何替换）符合此形的块**只有那一处**，无误伤。
# **不猜编号是几**：目录作「明月红松鸡…(99)」但污损的三个字看不清，
# 编造「（一一一）」就是编数据，所以只把这团乱码当作「有编号」的凭据剥掉，
# 标题即「明月红松鸡」。
_RECIPE_ENUM_GARBLED = r"[A-Za-z][A-Za-z .·]*"
RECIPE_ENUM_HEAD = re.compile(
    rf"^(?:[（(]?[{_RECIPE_ENUM_DIGITS}]+[）)]|[（(]{_RECIPE_ENUM_GARBLED}[）)])\s*"
)
# 「编号 + 后面确实还有内容」。recipe_segmenter.is_recipe_title 与
# page_normalizer.RECIPE_ENUMERATOR 共用，两处对编号的口径不会漂。
# 组 1 = 编号之后的那一行（`.` 不跨行，与旧实现一致）。
RECIPE_ENUM_WITH_NAME = re.compile(RECIPE_ENUM_HEAD.pattern + r"(.+)")


def strip_recipe_enumerator(title: str) -> str:
    cleaned = normalize_text(title)
    cleaned = RECIPE_ENUM_HEAD.sub("", cleaned, count=1)
    cleaned = _TITLE_PAD.sub("", cleaned)
    return cleaned.strip("：: ")


# 菜名合法性校验。菜名会直接成为 vault 笔记名、站点标题和 URL，一旦把一段正文
# 当成菜名，缺陷就直接暴露给读者。全书 630 道菜实测：最长菜名 12 字
# （「螺旋油饼（原名金钱油饼）」），最短 2 字，无一含句读，无一含「数字+钱/两/斤/克」
# 的用量串，括号一律成对。据此设阈值，宁可放弃一个可疑候选也不让正文冒充菜名。
MAX_DISH_TITLE_LEN = 14
_TITLE_PUNCT = re.compile(r"[。．，,；;：:！!？?…“”\"']")
_TITLE_QTY = re.compile(r"[〇零一二三四五六七八九十百半]+[钱两斤克]")
# 「一、原料」「二、制法」这类章节头，以及分类页的「…类」，都不是菜名
_TITLE_SECTION_WORD = ("原料", "用料", "材料", "主料", "配料", "调料", "佐料", "辅料",
                       "制法", "作法", "做法", "方法", "制作", "特点", "说明", "附注", "目录")


def is_plausible_dish_title(title: str) -> bool:
    """判断一个候选串是否像菜名（而不是正文/原料行/编号步骤）。"""
    cleaned = strip_recipe_enumerator(title)
    if not cleaned or "\n" in cleaned:
        return False
    if not 2 <= len(cleaned) <= MAX_DISH_TITLE_LEN:
        return False
    if _TITLE_PUNCT.search(cleaned):
        return False
    if _TITLE_QTY.search(cleaned):
        return False
    if cleaned.count("(") + cleaned.count("（") != cleaned.count(")") + cleaned.count("）"):
        return False
    if cleaned.endswith("类") or any(word in cleaned for word in _TITLE_SECTION_WORD):
        return False
    return True


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
