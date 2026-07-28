from __future__ import annotations

import re
import shutil
from collections import defaultdict
from pathlib import Path

from .markdown_writer import fallback_filename, recipe_filename, render_fallback_markdown, render_recipe_markdown, write_markdown
from .models import PageFallbackNote, RecipeCandidate
from .utils import ensure_dir, normalize_text

GENERIC_INGREDIENTS = {"主料", "配料", "调料", "原料", "用料", "适量", "少许", "各适量", "净", "各", "适当",
                       "实耗", "实用", "约", "共", "料", "汁"}

# 原书用量：数字串 + 单位（+「半」）。尾部不再吞数字，否则会吃掉下一个食材名的首字
# （「生 姜 三分 八 角 一只」去空格后「三分八」把「八」吃走，剩下孤字「角」）。
_NUM = "〇零一二三四五六七八九十百半两几"
_UNIT = "钱两斤分个只片粒条张朵克根块付副枚棵把碗匙勺撮"
_QTY = rf"[{_NUM}]+[{_UNIT}]半?"
_CJK = "一-鿿"
_PAIR = re.compile(rf"([{_CJK}、]+?)({_QTY})")
_LEAD_QTY = re.compile(rf"^[{_NUM}]+[{_UNIT}]半?(?=.)")
_LABEL = re.compile(r"^(主料|配料|调料|原料|用料)\s*[:：]?")
_PAREN = re.compile(r"[（(][^）)]*[）)]")
# 含句读或步骤号的行是制法正文，不是原料表
_SENTENCE = re.compile(r"[。，；！？]|^\s*\d+\s*[.、]|制法|特点|做法|注[:：]")
_GLUE = re.compile(r"[共各和与及或]")
# 以数字开头的合法食材名（不可剥前导数字）
_NUM_HEAD_OK = {"八角", "五花肉", "五花猪肉", "五花牛肉", "五花羊肉", "五香粉", "五香面",
                "三鲜", "千张", "百合", "十三香", "八宝", "四季豆", "一级羊肉"}
# 剥离量词后可能剩下的无意义单字
_BAD_SINGLE = {"角", "麻", "分", "子", "头", "皮", "水", "色"}


def _clean_ingredient(name: str) -> str | None:
    name = _PAREN.sub("", name).strip("、 ")
    if not name or len(name) > 6:
        return None
    if not all("一" <= char <= "鿿" or char == "、" for char in name):
        return None
    if _GLUE.search(name):
        return None
    if name not in _NUM_HEAD_OK:
        previous = None
        while name and name != previous:
            previous = name
            match = _LEAD_QTY.match(name)
            if match and name not in _NUM_HEAD_OK:
                name = name[match.end():]
                continue
            if name[0] in _NUM + _UNIT and len(name) > 1 and name not in _NUM_HEAD_OK:
                name = name[1:]
    if not name or name in GENERIC_INGREDIENTS or name in _BAD_SINGLE:
        return None
    if all(char in _NUM + _UNIT for char in name):
        return None
    return name


def _extract_terms(lines: list[str]) -> list[str]:
    """从原料/调料行抽取食材名。

    原书为对齐会在名称内部插空格（「味 精 三分」「鸡 蛋 两个」），因此不能按空格
    切词——那会把名字打碎成单字。改为按「名称 + 用量」配对切分。
    """
    terms: list[str] = []
    for line in lines:
        raw = normalize_text(line)
        if _SENTENCE.search(raw):
            continue
        text = _LABEL.sub("", _PAREN.sub("", raw).strip())
        text = re.sub(r"\s+", "", text)
        if not text or len(text) > 30:
            continue
        for match in _PAIR.finditer(text):
            cleaned = _clean_ingredient(match.group(1))
            if not cleaned:
                continue
            for part in cleaned.split("、"):
                part = part.strip()
                if part and part not in GENERIC_INGREDIENTS and part not in _BAD_SINGLE:
                    terms.append(part)
    return list(dict.fromkeys(terms))



def _link_name(note_path: str) -> str:
    return Path(note_path).stem


def assign_related_notes(recipes: list[RecipeCandidate], fallbacks: list[PageFallbackNote]) -> None:
    by_book: dict[str, list[RecipeCandidate]] = defaultdict(list)
    for recipe in recipes:
        by_book[recipe.book_id].append(recipe)
    for rows in by_book.values():
        rows.sort(key=lambda row: (row.local_pages[0], row.title))
        for index, recipe in enumerate(rows):
            related = []
            if index > 0 and rows[index - 1].note_path:
                related.append(_link_name(rows[index - 1].note_path))
            if index + 1 < len(rows) and rows[index + 1].note_path:
                related.append(_link_name(rows[index + 1].note_path))
            recipe.related_notes = related

    for note in fallbacks:
        note.related_notes = []


def export_notes(
    final_markdown_root: Path,
    vault_root: Path,
    recipes: list[RecipeCandidate],
    fallbacks: list[PageFallbackNote],
    schema: dict,
) -> None:
    folders = schema["folders"]
    recipe_root = ensure_dir(final_markdown_root / folders["recipes"])
    fallback_root = ensure_dir(final_markdown_root / folders["page_fallbacks"])
    ensure_dir(vault_root / folders["recipes"])
    ensure_dir(vault_root / folders["page_fallbacks"])

    for recipe in recipes:
        recipe.note_path = str(recipe_root / recipe_filename(recipe))
    for note in fallbacks:
        note.note_path = str(fallback_root / fallback_filename(note))

    # 标题修正会改变文件名;清掉不再对应任何笔记的旧导出文件,避免 vault 积累孤儿
    expected_recipes = {Path(recipe.note_path).name for recipe in recipes}
    expected_fallbacks = {Path(note.note_path).name for note in fallbacks}
    for folder, expected in (
        (recipe_root, expected_recipes),
        (vault_root / folders["recipes"], expected_recipes),
        (fallback_root, expected_fallbacks),
        (vault_root / folders["page_fallbacks"], expected_fallbacks),
    ):
        for stale in folder.glob("*.md"):
            if stale.name not in expected:
                stale.unlink()

    assign_related_notes(recipes, fallbacks)

    for recipe in recipes:
        target = Path(recipe.note_path)
        write_markdown(target, render_recipe_markdown(recipe, schema["note_defaults"].get("dish_category", "")))
        shutil.copy2(target, vault_root / folders["recipes"] / target.name)

    for note in fallbacks:
        target = Path(note.note_path)
        write_markdown(target, render_fallback_markdown(note))
        shutil.copy2(target, vault_root / folders["page_fallbacks"] / target.name)


def build_indexes(
    vault_root: Path,
    recipes: list[RecipeCandidate],
    fallbacks: list[PageFallbackNote],
    schema: dict,
) -> list[Path]:
    folders = schema["folders"]
    index_root = ensure_dir(vault_root / folders["indexes"])
    index_files = schema["index_files"]

    by_series: dict[int, list[RecipeCandidate]] = defaultdict(list)
    by_book: dict[str, list[RecipeCandidate]] = defaultdict(list)
    by_ingredient: dict[str, list[RecipeCandidate]] = defaultdict(list)

    for recipe in recipes:
        by_series[recipe.series].append(recipe)
        by_book[recipe.book_id].append(recipe)
        for ingredient in _extract_terms(recipe.ingredients + recipe.seasonings):
            by_ingredient[ingredient].append(recipe)

    review_targets = [item for item in recipes if item.review_needed] + [item for item in fallbacks if item.review_needed]

    total_lines = [
        "# 00 总索引",
        "",
        f"- 菜谱笔记: {len(recipes)}",
        f"- 页面回退笔记: {len(fallbacks)}",
        f"- 待复核项目: {len(review_targets)}",
        "",
        "- [[系列索引]]",
        "- [[书目索引]]",
        "- [[菜名索引]]",
        "- [[食材索引]]",
        "- [[低置信度待复核]]",
    ]

    series_lines = ["# 系列索引", ""]
    for series in sorted(by_series):
        series_lines.append(f"## 系列 {series}")
        for recipe in sorted(by_series[series], key=lambda row: (row.local_pages[0], row.title)):
            series_lines.append(f"- [[{Path(recipe.note_path).stem}]]")
        series_lines.append("")

    book_lines = ["# 书目索引", ""]
    for book_id in sorted(by_book):
        book_lines.append(f"## {book_id}")
        for recipe in sorted(by_book[book_id], key=lambda row: (row.local_pages[0], row.title)):
            book_lines.append(f"- [[{Path(recipe.note_path).stem}]]")
        book_lines.append("")

    dish_lines = ["# 菜名索引", ""]
    for recipe in sorted(recipes, key=lambda row: row.title):
        dish_lines.append(f"- {recipe.title} -> [[{Path(recipe.note_path).stem}]]")

    ingredient_lines = ["# 食材索引", ""]
    for ingredient in sorted(by_ingredient):
        ingredient_lines.append(f"## {ingredient}")
        for recipe in sorted(by_ingredient[ingredient], key=lambda row: row.title):
            ingredient_lines.append(f"- [[{Path(recipe.note_path).stem}]]")
        ingredient_lines.append("")

    review_lines = ["# 低置信度待复核", ""]
    for item in review_targets:
        review_lines.append(
            f"- [[{Path(item.note_path).stem}]] | {item.book_id} | 页码 {','.join(str(page) for page in item.local_pages)} | 置信度 {item.confidence}"
        )

    mapping = {
        index_files["total"]: "\n".join(total_lines).strip() + "\n",
        index_files["series"]: "\n".join(series_lines).strip() + "\n",
        index_files["books"]: "\n".join(book_lines).strip() + "\n",
        index_files["dishes"]: "\n".join(dish_lines).strip() + "\n",
        index_files["ingredients"]: "\n".join(ingredient_lines).strip() + "\n",
        index_files["review"]: "\n".join(review_lines).strip() + "\n",
    }

    written = []
    for filename, content in mapping.items():
        target = index_root / filename
        target.write_text(content, encoding="utf-8")
        written.append(target)
    return written
