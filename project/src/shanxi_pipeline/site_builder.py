"""从 vault 生成 GitHub Pages 静态站(纯 HTML/CSS/JS,无外部依赖)。

站点直接以仓库根为发布目录:页图 `assets/pages/` 原地复用,不复制 53MB。
"""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

LOGGER = logging.getLogger(__name__)

REPO_URL = "https://github.com/RinPV2/Shaanxi-Recipes"
SITE_BASE = "https://rinpv2.github.io/Shaanxi-Recipes"
SITE_TITLE = "陕西菜谱"
SITE_SUBTITLE = "1970 年代《陕西菜谱》全四册数字化"
FULL_PAGE_PREFIX = "【整页】"
BOOK_LABELS = {"sxcp-1": "第一册", "sxcp-2": "第二册", "sxcp-3": "第三册", "sxcp-4": "第四册"}
UNCATEGORIZED = "未分类"

# 回退页(page_fallbacks/)里值得单独成页的那些：书前书后的正文型页面。
# 目录页 / 分类扉页 / 书名页不在此表内——它们只有一行标签或一串页码，
# 内容已由站内索引与分类筛选覆盖，单独成页只是噪音（页图仍可从附录索引直达）。
#
# 每篇「专文」跨若干连续页；页码为**本地页码**（与 assets/pages/<book>/p####.webp 一致，
# 与原书印刷页码差约 10，故与目录里的页码不同）。改动本表 = 改动发布范围。
APPENDIX_DIRNAME = "appendix"
APPENDIX_TITLE = "书前书后·专文与附录"
INGREDIENT_DIRNAME = "ingredients"
INGREDIENT_TITLE = "食材索引"
APPENDIX_ARTICLES: tuple[dict[str, Any], ...] = (
    {"book_id": "sxcp-1", "title": "前言", "kind": "书前", "pages": (2, 3)},
    {
        "book_id": "sxcp-4",
        "title": "附：酱卤菜的特点及制作方法",
        "kind": "附录",
        "pages": (107, 108, 109, 110, 111, 112),
    },
    {
        "book_id": "sxcp-4",
        "title": "冷盘的装拼方法",
        "kind": "附录",
        "pages": (113, 114, 115, 116),
    },
    {"book_id": "sxcp-4", "title": "几种特殊刀法", "kind": "附录", "pages": (117, 118, 119)},
    {"book_id": "sxcp-4", "title": "版权页", "kind": "书末", "pages": (120,)},
)
# 未发布回退页的归类标签（frontmatter 的 status → 人话），只用于附录索引页的说明清单。
FALLBACK_STATUS_LABELS = {
    "toc": "目录页",
    "category": "分类扉页",
    "title_page": "分类扉页（续）",
    "front_matter": "书名页",
    "continuation": "接续页",
    "unresolved": "未解析页（多为目录续页）",
}


def _book_label(book_id: str) -> str:
    return BOOK_LABELS.get(book_id, book_id)


def _esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def _split_note(text: str) -> tuple[dict[str, Any] | None, str]:
    """拆出 (frontmatter dict, 正文)；frontmatter 解析不了时返回 (None, "")。"""
    if not text.startswith("---"):
        return None, ""
    _, _, rest = text.partition("---\n")
    front, _, body = rest.partition("\n---")
    try:
        data = yaml.safe_load(front) or {}
    except yaml.YAMLError:
        return None, ""
    if not isinstance(data, dict):
        return None, ""
    return data, body


def load_recipes(vault_root: Path) -> list[dict[str, Any]]:
    """读取 vault/recipes 下的笔记,解析 YAML frontmatter。"""
    recipes: list[dict[str, Any]] = []
    for path in sorted((vault_root / "recipes").glob("*.md")):
        data, _body = _split_note(path.read_text(encoding="utf-8"))
        if data is None:
            LOGGER.warning("跳过无法解析的笔记: %s", path.name)
            continue
        data["slug"] = path.stem
        recipes.append(data)
    return recipes


def _page_text_paragraphs(body: str) -> list[str]:
    """取回退笔记 `## 页面文本` 小节的段落（原样照录，仅去空行）。"""
    if "## 页面文本" not in body:
        return []
    section = body.split("## 页面文本", 1)[1]
    section = section.split("\n## ", 1)[0]
    return [line.strip() for line in section.splitlines() if line.strip() and line.strip() != "无"]


def load_page_fallbacks(vault_root: Path) -> list[dict[str, Any]]:
    """读取 vault/page_fallbacks 下的回退笔记（目录不存在 = 没有回退页）。

    与 load_recipes 不同,回退笔记没有结构化字段,正文在 `## 页面文本` 小节里,
    这里解析成 `body` 段落列表——下游注释挂载与渲染都只认这一个段。
    """
    notes: list[dict[str, Any]] = []
    directory = vault_root / "page_fallbacks"
    if not directory.is_dir():
        return notes
    for path in sorted(directory.glob("*.md")):
        data, body = _split_note(path.read_text(encoding="utf-8"))
        if data is None:
            LOGGER.warning("跳过无法解析的回退笔记: %s", path.name)
            continue
        pages = [p for p in (data.get("local_pages") or []) if isinstance(p, int)]
        notes.append(
            {
                "note_slug": path.stem,
                "book_id": data.get("book_id", ""),
                "local_pages": pages,
                "status": data.get("status") or "",
                "review_needed": bool(data.get("review_needed")),
                "body": _page_text_paragraphs(body),
            }
        )
    return notes


def appendix_plan(
    fallbacks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按 APPENDIX_ARTICLES 把回退笔记分成 (要发布的页, 不发布的页)。

    发布的页会补上专文归属与同篇前后页 slug；slug 形如 `sxcp-4-p0113`，
    与菜谱 slug（含菜名）不同名空间，注释可用 slug 精确指定。
    """
    by_key = {
        (note["book_id"], page): note for note in fallbacks for page in note["local_pages"]
    }
    published: list[dict[str, Any]] = []
    claimed_notes: set[str] = set()
    for article in APPENDIX_ARTICLES:
        book_id = article["book_id"]
        found = [(page, by_key[(book_id, page)]) for page in article["pages"] if (book_id, page) in by_key]
        missing = [page for page in article["pages"] if (book_id, page) not in by_key]
        if missing:
            # 整篇都找不到 = 大概率不是完整 vault（测试夹具 / 局部构建），记 INFO 就好；
            # 只缺其中几页才是真异常（笔记被删或页码分段写错），必须 WARNING。
            log = LOGGER.warning if found else LOGGER.info
            log(
                "附录《%s》缺少回退笔记，这些页不会上站: %s %s",
                article["title"],
                book_id,
                ", ".join(f"p{p:04d}" for p in missing),
            )
        slugs = [f"{book_id}-p{page:04d}" for page, _ in found]
        for index, (page, note) in enumerate(found):
            claimed_notes.add(note["note_slug"])
            published.append(
                {
                    **note,
                    "slug": slugs[index],
                    "local_pages": [page],
                    "page": page,
                    "article": article["title"],
                    "kind": article["kind"],
                    "index": index + 1,
                    "total": len(found),
                    "prev": slugs[index - 1] if index else "",
                    "next": slugs[index + 1] if index + 1 < len(found) else "",
                    "title": article["title"]
                    if len(found) == 1
                    else f"{article['title']}（{index + 1}/{len(found)}）",
                }
            )
    skipped = [note for note in fallbacks if note["note_slug"] not in claimed_notes]
    return published, skipped


def build_category_lookup(anchor_map: dict[str, Any]) -> dict[str, list[tuple[int, str]]]:
    """每册按页码排序的 (起始页, 分类) 列表——分类沿用最近的前置锚点。"""
    lookup: dict[str, list[tuple[int, str]]] = {}
    for book_id, pages in anchor_map.items():
        points: dict[int, str] = {}
        for entries in pages.values():
            for entry in entries:
                # 曾在此 replace 掉 FULL_PAGE_PREFIX 作为创可贴；控制标记已在
                # review_priority 源头剥除（_strip_review_markers），此处不再兜底，
                # 以免掩盖同类回归。
                category = (entry.get("category") or "").strip()
                page = entry.get("local_page")
                if category and isinstance(page, int):
                    # 同页多条目时保留首次出现的分类
                    points.setdefault(page, category)
        lookup[book_id] = sorted(points.items())
    return lookup


def category_for(lookup: dict[str, list[tuple[int, str]]], book_id: str, page: int | None) -> str:
    points = lookup.get(book_id) or []
    if not points or page is None:
        return UNCATEGORIZED
    current = UNCATEGORIZED
    for start, category in points:
        if start <= page:
            current = category
        else:
            break
    return current


ANNOTATED_SECTIONS = ("ingredients", "seasonings", "steps", "tips")
# 回退页（附录专文）没有结构化小节，正文全在 body 一段里。
APPENDIX_SECTIONS = ("body",)


def load_annotations(path: Path) -> list[dict[str, Any]]:
    """读取 config/annotations.yaml 的 annotations 列表（缺文件=没有注释）。

    `pending` 段落里的条目故意不返回：那是目标页尚未上站、暂存待用的注释，
    算进匹配统计只会让 annotations_unmatched 常年不为 0，掩盖真正的锚文本失配。
    """
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        LOGGER.warning("annotations.yaml 无法解析，本次不渲染注释: %s", path)
        return []
    items = data.get("annotations") or []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            LOGGER.warning("annotations[%s] 不是映射，跳过", index)
            continue
        missing = [k for k in ("book_id", "local_page", "anchor", "note") if not item.get(k)]
        if missing:
            LOGGER.warning("annotations[%s] 缺字段 %s，跳过", index, "/".join(missing))
            continue
        result.append(item)
    return result


def annotations_for_recipe(
    annotations: list[dict[str, Any]], recipe: dict[str, Any], used: set[int]
) -> list[dict[str, Any]]:
    """挑出该页（菜谱或回退页）的候选注释（按 book_id + local_page，可用 slug 显式指定）。

    `used` 记下已被别的页认领的注释 id，避免同一页两道菜都挂同一条。
    """
    book_id = recipe.get("book_id", "")
    pages = set(recipe.get("local_pages") or [])
    slug = recipe.get("slug", "")
    picked: list[dict[str, Any]] = []
    for item in annotations:
        if id(item) in used:
            continue
        target_slug = item.get("slug")
        if target_slug:
            if target_slug != slug:
                continue
        elif item.get("book_id") != book_id or item.get("local_page") not in pages:
            continue
        picked.append(item)
    return picked


def attach_annotations(
    recipe: dict[str, Any],
    candidates: list[dict[str, Any]],
    sections: tuple[str, ...] = ANNOTATED_SECTIONS,
) -> tuple[dict[str, list[str]], list[dict[str, Any]], list[dict[str, Any]]]:
    """把上角标插进正文（已转义的 HTML 片段），返回 (各段 HTML 行, 命中的注释, 落空的注释)。

    段内按 `sections` 给的顺序扫描（菜谱=食材→调料→做法→特点；回退页=body 一段），
    锚文本只在首次出现处挂角标。返回的行是 HTML，调用方不得再次转义。
    """
    rows: dict[str, list[str]] = {}
    for key in sections:
        rows[key] = [_esc(row) for row in (recipe.get(key) or []) if str(row).strip()]

    matched: list[dict[str, Any]] = []
    pending = list(candidates)
    number = 0
    # 按正文顺序走；一行里有多条注释时取最靠前的锚文本先挂，编号才跟阅读顺序一致。
    for key in sections:
        for row_index in range(len(rows[key])):
            while pending:
                hits = [
                    (position, item)
                    for item in pending
                    if (position := rows[key][row_index].find(_esc(item["anchor"]))) >= 0
                ]
                if not hits:
                    break
                position, item = min(hits, key=lambda pair: pair[0])
                number += 1
                cut = position + len(_esc(item["anchor"]))
                sup = (
                    f'<sup class="fn"><a id="fnref-{number}" href="#fn-{number}">'
                    f"{number}</a></sup>"
                )
                row = rows[key][row_index]
                rows[key][row_index] = row[:cut] + sup + row[cut:]
                matched.append(item)
                pending.remove(item)

    # 这里不记 WARNING：同一页有多道菜时，一条注释在别的菜谱里落空是正常的。
    # 真正的失配由 build_site 在扫完全库后统一判定（谁都没认领 = 未命中）。
    return rows, matched, pending


def render_footnotes(matched: list[dict[str, Any]]) -> str:
    if not matched:
        return ""
    lis = "\n".join(
        f'<li id="fn-{i}">{_esc(item["note"])} '
        f'<a class="fn-back" href="#fnref-{i}" aria-label="返回正文">↩</a></li>'
        for i, item in enumerate(matched, start=1)
    )
    return (
        '<details class="notes" open><summary>注释（{n}）</summary>'
        '<ol class="fnlist">{lis}</ol></details>'
    ).format(n=len(matched), lis=lis)


# ------------------------------------------------------- 食材索引与正文链接化
#
# 全书 824 个食材写法里有大量「表状态 / 处理方式」的前后缀变体
# （水木耳 / 木耳 / 净木耳，净冬笋 / 冬笋片 / 冬笋）。每个写法单独成页太零碎，
# 强行归一又丢原书用词，所以：**一个基名一页，页内按原书写法分组**。
#
# 基名 = 反复剥掉下列前后缀后、仍然「站得住」的最长残词。「站得住」有两条口径，
# 都由全库统计说话，不靠人拍脑袋：
#   1) 残词本身就是原书的食材写法（在词表里出现过）——如 木耳、冬笋、猪肉、姜；
#   2) 残词长度 ≥2，且有 **两个以上**不同写法「只剥前缀」就能汇到它——
#      如 水海参 / 水发海参 → 海参，水鱼肚 / 水发鱼肚 / 干鱼肚 → 鱼肚。
#      原书从不单写「海参」，但两种写法一致指向它，这个基名是可信的。
# 单字残词只在口径 1 下接受（姜、葱、蒜 原书确有单写），否则「肉米→肉」「水粉丝→粉」
# 这类过度剥离全被挡住。后缀剥离**不参与**口径 2，否则「玉兰片→玉兰」会成立。
BASE_PREFIXES = ("水发", "净", "水", "熟", "生", "鲜", "干")
BASE_SUFFIXES = ("片", "丝", "米", "丁", "块", "条", "末")
# 前后缀是名字的一部分，剥了就是另一样东西——一律按原样自成基名。
# 多数已被上面的规则挡住，这里显式再兜一层，同时充当「刻意不剥」的清单。
INGREDIENT_ATOMIC = frozenset(
    {
        "生菜", "干菜", "水晶", "干贝", "玉兰片", "花生米", "海米", "虾米", "大米",
        "江米", "糯米", "籼米", "薏米", "香米", "葛仙米", "肉米", "肉丝", "粉条",
        "粉丝", "粉皮", "青红丝", "红丝", "鲜桃", "鲜梨", "干姜", "生姜",
        # 熟面＝熟面粉（做馅用），与「面」（面粉／面条）不是一味东西。
        # 规则本会因「面」在书里单独出现过而把它并进去，故显式挡住。
        "熟面",
    }
)
# 剥出来会改词义的残词，永不作基名（长度 ≥2 才需要列，单字已被规则挡住）。
INGREDIENT_NOT_A_BASE = frozenset({"玉兰", "花生", "青红", "大海", "熟笋", "竹笋切"})

# ------------------------------------------------------------ 非食材：显式剔除
#
# 「原料」表里混进来的、**压根不是一种可食用原料**的写法。全部逐条回原书页图核实过，
# 每条注明出处（书序-页码 · 菜名）与原书那一行长什么样。
#
# 判据只有一条：它在原书语境里指的不是食材。分三类——
#   ① 季节/条件词：原书给同一味料按季节列了三个用量，季节词被当成了名字；
#   ② 概数词残尾：「约一两」的「约」黏在名字后，而名字只有一个字，尾巴剥不掉；
#   ③ 名称粘连：原书为省版面把「甲少许／适量 乙 用量」排在一行（常跨行折断），
#      「名称+用量」配对切分把「甲+量词+乙」整段当成了一个名字。
#
# **只列压根不是食材的。** 部位名（下五花猪肉／前膀肥瘦肉／猪臀尖肉）、状态名
# （净猪腰花／熟猪油／鲜熟笋）、等级名（一级羊肉／上银耳）、地方物产
# （临潼火景柿子）都是原书真实写法，一律保留。OCR 讹字（大白莱／波菜／莱籽汕／
# 白矶）指向的仍是食材，也保留——它们是校对问题，不是「不是食材」。
# 拿不准就留着：误删一味真食材，读者从此搜不到；多留一条残渣，只是多一页。
#
# 增删办法：直接改这个集合，然后重新 build-site。陈旧页清理会自动删掉
# ingredients/ 下多出来的 HTML；被剔除的写法在菜谱正文里仍原样显示，只是不再是链接。
INGREDIENT_NOT_FOOD = frozenset(
    {
        # ① 季节词。sxcp-3 p0041 乾州锅盔 原书：「酵面　夏季七两、春秋季一斤、冬季斤半。」
        #    ——酵面才是料，三个季节是它的分季用量。「酵面夏季」是名字与季节粘连。
        "冬季",
        "春秋季",
        "酵面夏季",
        # ② 概数词残尾。sxcp-3 p0032 炸麻花 原书：「碱　约一两」——料是「碱」（已单列）。
        "碱约",
        # ③ 名称粘连（原书同行排两味料，折行后被当成一个名字）。
        # sxcp-4 p0036 熏黄花鱼 / p0089 五柳凤尾笋：「葱一段　姜一块」
        "葱一段姜",
        # sxcp-2 p0122 什锦铁锅蛋：「味精五厘　绍酒一钱」
        "味精五厘绍酒",
        # sxcp-4 p0081 油焖腐竹：「味精适量　酱油五钱」
        "味精适量酱油",
        # sxcp-4 p0081 油焖腐竹：「酱（卤）汤适量　菜油二两」
        "酱汤适量菜油",
        # sxcp-4 p0084 糖醋面筋泡：「清油适量　糖六两」
        "清油适量糖",
        # sxcp-4 p0016 琉璃肉：「菜籽油五钱（实耗）盐少／许粉面四两」（原书在此折行）
        "盐少许粉面",
        # sxcp-4 p0067 五香鸭块：「糖五钱（讹作「饯」）　绍酒一两」
        "糖五饯绍酒",
        # sxcp-4 p0079 虾籽素火腿：「糖色少许　盐一两半」
        "糖色少许盐",
        # sxcp-4 p0104 金银肝：「绍酒少许　鸡蛋二个」
        "绍酒少许鸡蛋",
        # sxcp-4 p0104 金银肝：「酱油少许　味精一分」
        "酱油少许味精",
        # sxcp-4 p0092 酸辣甘兰：「菜油少许　盐三两」
        "菜油少许盐",
        # sxcp-4 p0082 五香豆腐：「菜油适量　盐一两」
        "菜油适量盐",
        # sxcp-4 p0036 酱汁鱼：「菜油适量　绍酒一两」
        "菜油适量绍酒",
        # sxcp-4 p0057 烧扒鸡：「蜂蜜少许　菜油一两」
        "蜂蜜少许菜油",
        # sxcp-4 p0105 炸菊红卷：「面粉少许　酱油一两」
        "面粉少许酱油",
    }
)


def _affix_residuals(name: str) -> dict[str, bool]:
    """名字可达的全部残词 → 该残词是否「只靠剥前缀」到达（供口径 2 判定）。"""
    seen: dict[str, bool] = {name: True}
    frontier = [(name, True)]
    while frontier:
        current, prefix_only = frontier.pop()
        for affix in BASE_PREFIXES:
            if current.startswith(affix) and len(current) > len(affix):
                shorter = current[len(affix):]
                if shorter not in seen or (prefix_only and not seen[shorter]):
                    seen[shorter] = prefix_only
                    frontier.append((shorter, prefix_only))
        for affix in BASE_SUFFIXES:
            if current.endswith(affix) and len(current) > len(affix):
                shorter = current[: -len(affix)]
                if shorter not in seen:
                    seen[shorter] = False
                    frontier.append((shorter, False))
    del seen[name]
    return seen


def ingredient_bases(terms: list[str]) -> dict[str, str]:
    """全库食材写法 → 基名。规则见上方注释；结果对同一批 terms 是确定的。"""
    unique = list(dict.fromkeys(terms))
    attested = set(unique)
    residuals = {name: _affix_residuals(name) for name in unique}
    prefix_support: dict[str, int] = {}
    for table in residuals.values():
        for word, prefix_only in table.items():
            if prefix_only:
                prefix_support[word] = prefix_support.get(word, 0) + 1

    def usable(word: str) -> bool:
        if word in INGREDIENT_NOT_A_BASE:
            return False
        if word in attested:
            return True
        return len(word) >= 2 and prefix_support.get(word, 0) >= 2

    # 一步：挑最长的「站得住」残词。
    step: dict[str, str] = {}
    for name in unique:
        if name in INGREDIENT_ATOMIC:
            step[name] = name
            continue
        options = [word for word in residuals[name] if usable(word)]
        step[name] = max(options, key=lambda word: (len(word), word)) if options else name

    # 传递闭包：水玉兰片丝 → 玉兰片丝 → 玉兰片，熟火腿丝 → 熟火腿 → 火腿。
    # 每步严格变短，不可能成环。
    bases: dict[str, str] = {}
    for name in unique:
        current = name
        # step 只为「书里出现过的写法」建了键，但它的值可能是一个剥出来的残词
        # （如 响皮），那种词不在 unique 里、没有自己的条目 → 用 get 兜底，
        # 取不到就说明已经到底了。直接 step[current] 会 KeyError（实测崩在 响皮）。
        while True:
            nxt = step.get(current, current)
            if nxt == current:
                break
            current = nxt
        bases[name] = current
    return bases


def _recipe_terms(recipe: dict[str, Any]) -> list[str]:
    """一道菜的食材写法。复用 vault 食材索引的同一个抽取器，两边口径不会漂。"""
    from .obsidian_exporter import _extract_terms

    return _extract_terms(
        [str(row) for row in (recipe.get("ingredients") or [])]
        + [str(row) for row in (recipe.get("seasonings") or [])]
    )


def build_ingredient_index(recipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """归出基名分组：[{base, count, variants:[{name, recipes:[...]}]}]，按菜数降序。"""
    by_term: dict[str, list[dict[str, Any]]] = {}
    for recipe in recipes:
        for term in _recipe_terms(recipe):
            # 非食材残渣在这里就落地：索引不收它，IngredientLinker 由索引构造，
            # 于是正文里也不会再把它链接出去（但文字照旧原样显示）。
            if term in INGREDIENT_NOT_FOOD:
                continue
            by_term.setdefault(term, []).append(recipe)
    bases = ingredient_bases(list(by_term))

    grouped: dict[str, list[str]] = {}
    for term, base in bases.items():
        grouped.setdefault(base, []).append(term)

    index: list[dict[str, Any]] = []
    for base, terms in grouped.items():
        variants = [
            {
                "name": term,
                "recipes": sorted(
                    by_term[term], key=lambda r: (r.get("book_id", ""), r["slug"])
                ),
            }
            for term in sorted(terms, key=lambda t: (-len(by_term[t]), t))
        ]
        dishes = {r["slug"] for term in terms for r in by_term[term]}
        index.append({"base": base, "count": len(dishes), "variants": variants})
    index.sort(key=lambda item: (-item["count"], item["base"]))
    return index


_TAG_RE = re.compile(r"<[^>]*>")
_OPEN_A_RE = re.compile(r"<a[\s>]", re.IGNORECASE)
_CLOSE_A_RE = re.compile(r"</a\s*>", re.IGNORECASE)


class IngredientLinker:
    """把正文行里的食材写法换成指向索引页的链接。

    输入是 **已转义、可能已插好 `<sup>` 上角标** 的 HTML 行（attach_annotations 的产物），
    所以必须：① 只在标签之外的文本段上替换；② 不进 `<a>…</a>` 内部（否则嵌套锚点）；
    ③ 用已转义形式去匹配，别再动转义。匹配最长优先——「水木耳」不会被「木耳」切开。
    """

    def __init__(self, index: list[dict[str, Any]]) -> None:
        self.targets: dict[str, tuple[str, int]] = {}
        for item in index:
            for variant in item["variants"]:
                self.targets[variant["name"]] = (item["base"], len(variant["recipes"]))
        # 长的排在前面：Python 的 `|` 取最左侧能匹配的分支，长度降序即最长优先。
        names = sorted(self.targets, key=lambda n: (-len(n), n))
        escaped = [re.escape(_esc(name)) for name in names]
        self._by_escaped = {_esc(name): name for name in names}
        self._pattern = re.compile("|".join(escaped)) if escaped else None

    def _link(self, match: re.Match[str], depth: int) -> str:
        name = self._by_escaped[match.group(0)]
        base, count = self.targets[name]
        href = (
            f"{'../' * depth}{INGREDIENT_DIRNAME}/{_esc(base)}.html"
            f"#{_variant_anchor(name)}"
        )
        return (
            f'<a class="ing" href="{href}" title="{_esc(name)}·{count} 道菜">'
            f"{match.group(0)}</a>"
        )

    def _text(self, segment: str, depth: int) -> str:
        if not segment or self._pattern is None:
            return segment
        return self._pattern.sub(lambda m: self._link(m, depth), segment)

    def linkify(self, row: str, *, depth: int = 1) -> str:
        out: list[str] = []
        position = 0
        inside_anchor = 0
        for tag in _TAG_RE.finditer(row):
            chunk = row[position : tag.start()]
            out.append(chunk if inside_anchor else self._text(chunk, depth))
            out.append(tag.group(0))
            if _OPEN_A_RE.match(tag.group(0)):
                inside_anchor += 1
            elif _CLOSE_A_RE.match(tag.group(0)):
                inside_anchor = max(0, inside_anchor - 1)
            position = tag.end()
        tail = row[position:]
        out.append(tail if inside_anchor else self._text(tail, depth))
        return "".join(out)

    def linkify_rows(
        self, rows: dict[str, list[str]], *, depth: int = 1
    ) -> dict[str, list[str]]:
        return {
            key: [self.linkify(row, depth=depth) for row in value]
            for key, value in rows.items()
        }


def _variant_anchor(name: str) -> str:
    return f"v-{_esc(name)}"


def render_ingredient_page(item: dict[str, Any]) -> str:
    """一个基名一页：页内按原书写法分组，各组列出用到它的菜。"""
    blocks = []
    for variant in item["variants"]:
        links = "".join(
            f'<li><a href="../recipes/{_esc(r["slug"])}.html">{_esc(r.get("title") or r["slug"])}</a>'
            f'<span class="sub">{_book_label(r.get("book_id", ""))} · '
            f'{_esc(_page_range(r.get("local_pages") or []))}</span></li>'
            for r in variant["recipes"]
        )
        same = " variant-base" if variant["name"] == item["base"] else ""
        blocks.append(
            f'<section class="block variant{same}" id="{_variant_anchor(variant["name"])}">'
            f'<h2>{_esc(variant["name"])}</h2>'
            f'<p class="meta">原书写法「{_esc(variant["name"])}」· {len(variant["recipes"])} 道菜</p>'
            f'<ul class="dishlist">{links}</ul></section>'
        )
    note = ""
    if len(item["variants"]) > 1:
        note = (
            f'<p>原书对它有 <strong>{len(item["variants"])}</strong> 种写法'
            f"（前缀「净/水/水发/熟/生/鲜/干」、后缀「片/丝/米/丁/块/条/末」表处理状态），"
            "下面按原书写法分组照录，不作合并改写。</p>"
        )
    body = f"""
<main class="home ingredient">
  <p class="crumbs"><a href="../index.html">全部菜谱</a> › <a href="index.html">{INGREDIENT_TITLE}</a> › {_esc(item["base"])}</p>
  <div class="hero">
    <h1>{_esc(item["base"])}</h1>
    <p>共 <strong>{item["count"]}</strong> 道菜用到它。</p>
    {note}
  </div>
  {"".join(blocks)}
</main>
"""
    return _layout(f"{item['base']} · {INGREDIENT_TITLE} · {SITE_TITLE}", body, depth=1)


def render_ingredient_index(index: list[dict[str, Any]]) -> str:
    """总览：全部基名按菜数降序（同数按字排），标注菜数与写法数。"""
    common = [item for item in index if item["count"] >= 5]
    rest = [item for item in index if item["count"] < 5]

    def cards(rows: list[dict[str, Any]]) -> str:
        return "".join(
            f'<li class="card"><a href="{_esc(item["base"])}.html">{_esc(item["base"])}</a>'
            f'<div class="sub">{item["count"]} 道菜'
            + (f' · {len(item["variants"])} 种写法' if len(item["variants"]) > 1 else "")
            + "</div></li>"
            for item in rows
        )

    variants_total = sum(len(item["variants"]) for item in index)
    body = f"""
<main class="home ingredient-index">
  <p class="crumbs"><a href="../index.html">全部菜谱</a> › {INGREDIENT_TITLE}</p>
  <div class="hero">
    <h1>{INGREDIENT_TITLE}</h1>
    <p>原书共出现 <strong>{variants_total}</strong> 种食材写法，归为 <strong>{len(index)}</strong> 个条目
    （「水木耳 / 水发木耳 / 木耳」这类只差处理状态的写法收进同一条，页内仍按原书写法分组照录）。
    菜谱正文里的食材名都是链接，点一下即到这里。</p>
  </div>
  <section class="block"><h2>常见食材（5 道菜以上，{len(common)} 条）</h2>
    <ul class="grid">{cards(common)}</ul></section>
  <section class="block"><h2>其余 {len(rest)} 条</h2>
    <ul class="grid">{cards(rest)}</ul></section>
</main>
"""
    return _layout(f"{INGREDIENT_TITLE} · {SITE_TITLE}", body, depth=1)


def _first_page(recipe: dict[str, Any]) -> int | None:
    pages = recipe.get("local_pages") or []
    return pages[0] if pages else None


def _page_range(pages: list[int]) -> str:
    if not pages:
        return ""
    if len(pages) == 1:
        return f"第 {pages[0]} 页"
    return f"第 {pages[0]}–{pages[-1]} 页"


def _issue_url(recipe: dict[str, Any], page_url: str, label: str = "菜谱") -> str:
    from urllib.parse import quote

    title = f"纠错：{recipe.get('title', '')}（{_book_label(recipe.get('book_id', ''))} {_page_range(recipe.get('local_pages') or [])}）"
    body = (
        f"**{label}**：{recipe.get('title', '')}\n"
        f"**出处**：{_book_label(recipe.get('book_id', ''))} {_page_range(recipe.get('local_pages') or [])}\n"
        f"**页面**：{page_url}\n\n"
        "**问题描述**（哪一句、应该是什么、依据原书页图的哪个位置）：\n\n"
    )
    return f"{REPO_URL}/issues/new?title={quote(title)}&body={quote(body)}"


# ---------------------------------------------------------------- 渲染

def _layout(title: str, body: str, *, depth: int, extra_head: str = "") -> str:
    prefix = "../" * depth
    return f"""<!DOCTYPE html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<link rel="stylesheet" href="{prefix}site/style.css">
{extra_head}
</head>
<body>
<header class="topbar">
  <a class="brand" href="{prefix}index.html">{SITE_TITLE}<span class="brand-sub">{SITE_SUBTITLE}</span></a>
  <nav><a href="{prefix}{INGREDIENT_DIRNAME}/index.html">{INGREDIENT_TITLE}</a><a href="{prefix}{APPENDIX_DIRNAME}/index.html">专文与附录</a><a href="{REPO_URL}" rel="noopener">GitHub</a></nav>
</header>
{body}
<footer class="footer">
  <p>《陕西菜谱》(全四册)，陕西省副食服务公司、西安市饮食公司编写，1970 年代内部发行。本站为非营利数字化整理。</p>
  <p>整理内容 CC BY 4.0 · 站点代码 MIT · <a href="{REPO_URL}" rel="noopener">项目仓库</a></p>
</footer>
</body>
</html>
"""


def _page_image_href(book_id: str, page: int, *, depth: int = 1) -> str:
    """页图路径（站点根下的 assets/pages/，不复制、原地复用）。"""
    return f"{'../' * depth}assets/pages/{_esc(book_id)}/p{page:04d}.webp"


def _scans_html(book_id: str, pages: list[int], alt_prefix: str, *, depth: int = 1) -> str:
    """右栏「原书页图」对照：菜谱页与附录页共用同一版式。"""
    return "\n".join(
        f'<figure><a href="{_page_image_href(book_id, page, depth=depth)}" target="_blank" rel="noopener">'
        f'<img loading="lazy" src="{_page_image_href(book_id, page, depth=depth)}" '
        f'alt="{_esc(alt_prefix)} 原书第 {page} 页"></a>'
        f"<figcaption>原书 {_book_label(book_id)} 第 {page} 页</figcaption></figure>"
        for page in pages
    )


def render_recipe_page(
    recipe: dict[str, Any],
    category: str,
    site_base: str,
    annotations: list[dict[str, Any]] | None = None,
    linker: IngredientLinker | None = None,
) -> str:
    title = recipe.get("title") or recipe.get("slug", "")
    book_id = recipe.get("book_id", "")
    pages: list[int] = recipe.get("local_pages") or []
    slug = recipe["slug"]
    page_url = f"{site_base}/recipes/{slug}.html" if site_base else f"recipes/{slug}.html"

    # 正文行在这里已经转义完并插好上角标；section() 不得再转义。
    # 顺序固定为「先挂角标、后链接化」：角标靠 find(_esc(anchor)) 定位，
    # 若先插了 <a> 标签，锚文本会被标签切断而失配。链接化则天然能跳过既有标签。
    rows_by_key, matched, _unmatched = attach_annotations(recipe, list(annotations or []))
    if linker is not None:
        rows_by_key = linker.linkify_rows(rows_by_key, depth=1)

    def section(heading: str, key: str, cls: str = "") -> str:
        rows = rows_by_key.get(key) or []
        if not rows:
            return ""
        lis = "\n".join(f"<li>{row}</li>" for row in rows)
        return f'<section class="block {cls}"><h2>{heading}</h2><ul>{lis}</ul></section>'

    images = _scans_html(book_id, pages, title)

    aliases = recipe.get("aliases") or []
    alias_html = (
        f'<p class="aliases">又作：{_esc("、".join(str(a) for a in aliases))}</p>' if aliases else ""
    )
    flag = ""
    if recipe.get("review_needed"):
        flag = '<p class="warn">此条 OCR 置信度较低，欢迎对照原书页图纠错。</p>'

    body = f"""
<main class="recipe">
  <p class="crumbs"><a href="../index.html">全部菜谱</a> › <a href="../index.html?book={_esc(book_id)}">{_book_label(book_id)}</a> › {_esc(category)}</p>
  <h1>{_esc(title)}</h1>
  {alias_html}
  <p class="meta">{_book_label(book_id)} · {_esc(_page_range(pages))} · {_esc(category)}</p>
  {flag}
  <div class="cols">
    <div class="text">
      {section("食材", "ingredients")}
      {section("调料", "seasonings")}
      {section("做法", "steps", "steps")}
      {section("特点", "tips")}
      {render_footnotes(matched)}
      <p class="report"><a class="btn" href="{_esc(_issue_url(recipe, page_url))}" target="_blank" rel="noopener">发现错误？提交纠错</a></p>
    </div>
    <aside class="scans">
      <h2>原书页图</h2>
      {images}
    </aside>
  </div>
</main>
"""
    return _layout(f"{title} · {SITE_TITLE}", body, depth=1)


def render_appendix_page(
    page: dict[str, Any],
    site_base: str,
    annotations: list[dict[str, Any]] | None = None,
    linker: IngredientLinker | None = None,
) -> str:
    """一个回退页 = 一个 HTML，版式与菜谱页一致（左正文右页图），正文按段落照录。"""
    book_id = page.get("book_id", "")
    number = page.get("page")
    pages = [p for p in (page.get("local_pages") or []) if isinstance(p, int)]
    slug = page["slug"]
    page_url = (
        f"{site_base}/{APPENDIX_DIRNAME}/{slug}.html"
        if site_base
        else f"{APPENDIX_DIRNAME}/{slug}.html"
    )
    title = page.get("title") or slug

    rows_by_key, matched, _unmatched = attach_annotations(
        page, list(annotations or []), APPENDIX_SECTIONS
    )
    if linker is not None:
        rows_by_key = linker.linkify_rows(rows_by_key, depth=1)
    paragraphs = "\n".join(f"<p>{row}</p>" for row in rows_by_key.get("body") or [])
    if not paragraphs:
        paragraphs = '<p class="muted">此页无可显示的文本，请直接看右侧页图。</p>'

    pager_links = []
    if page.get("prev"):
        pager_links.append(f'<a href="{_esc(page["prev"])}.html">← 上一页</a>')
    pager_links.append(f'<a href="index.html">{APPENDIX_TITLE}</a>')
    if page.get("next"):
        pager_links.append(f'<a href="{_esc(page["next"])}.html">下一页 →</a>')
    pager = f'<nav class="pager">{" · ".join(pager_links)}</nav>'

    flag = ""
    if page.get("review_needed"):
        flag = '<p class="warn">此页 OCR 置信度较低，欢迎对照原书页图纠错。</p>'
    span = f"《{page.get('article')}》共 {page.get('total')} 页" if (page.get("total") or 1) > 1 else f"《{page.get('article')}》"

    body = f"""
<main class="recipe appendix">
  <p class="crumbs"><a href="../index.html">全部菜谱</a> › <a href="index.html">{APPENDIX_TITLE}</a> › {_esc(page.get("kind", ""))}</p>
  <h1>{_esc(title)}</h1>
  <p class="meta">{_book_label(book_id)} · 第 {number} 页 · {_esc(span)}</p>
  {flag}
  <div class="cols">
    <div class="text">
      <section class="block prose"><h2>页面文本（照录原书）</h2>{paragraphs}</section>
      {render_footnotes(matched)}
      {pager}
      <p class="report"><a class="btn" href="{_esc(_issue_url(page, page_url, "附录页"))}" target="_blank" rel="noopener">发现错误？提交纠错</a></p>
    </div>
    <aside class="scans">
      <h2>原书页图</h2>
      {_scans_html(book_id, pages, title)}
    </aside>
  </div>
</main>
"""
    return _layout(f"{title} · {SITE_TITLE}", body, depth=1)


def render_appendix_index(pages: list[dict[str, Any]], skipped: list[dict[str, Any]]) -> str:
    """附录索引：按专文列出已发布页；未单独成页的回退页只给页图直链。"""
    blocks = []
    seen: list[tuple[str, str]] = []
    for page in pages:
        key = (page.get("book_id", ""), page.get("article", ""))
        if key not in seen:
            seen.append(key)
    for book_id, article in seen:
        group = [p for p in pages if p.get("book_id") == book_id and p.get("article") == article]
        items = "".join(
            f'<li><a href="{_esc(p["slug"])}.html">第 {p["page"]} 页</a></li>' for p in group
        )
        blocks.append(
            f'<section class="block"><h2>{_esc(article)}</h2>'
            f'<p class="meta">{_book_label(book_id)} · {_esc(group[0].get("kind", ""))} · 共 {len(group)} 页</p>'
            f'<ul class="pagelist">{items}</ul></section>'
        )

    skipped_rows = []
    for book_id in sorted(BOOK_LABELS):
        book_notes = [n for n in skipped if n.get("book_id") == book_id]
        if not book_notes:
            continue
        links = "、".join(
            f'<a href="{_page_image_href(book_id, page)}" target="_blank" rel="noopener">'
            f"p{page:04d}</a>"
            for note in book_notes
            for page in note["local_pages"]
        )
        kinds = sorted(
            {FALLBACK_STATUS_LABELS.get(n["status"], n["status"] or "其他") for n in book_notes}
        )
        skipped_rows.append(
            f'<li>{_book_label(book_id)}（{_esc("、".join(kinds))}）：{links}</li>'
        )
    skipped_html = (
        '<details class="notes"><summary>未单独成页的 {n} 页（目录页 / 分类扉页 / 书名页）</summary>'
        "<p>这些页只有一行标签或一串目录页码，内容已由站内的分类筛选和菜谱索引覆盖，"
        "因此不单独成页；需要核对原书排布时可直接看页图。</p>"
        "<ul>{rows}</ul></details>"
    ).format(n=sum(len(n["local_pages"]) for n in skipped), rows="".join(skipped_rows))

    body = f"""
<main class="home appendix-index">
  <p class="crumbs"><a href="../index.html">全部菜谱</a> › {APPENDIX_TITLE}</p>
  <div class="hero">
    <h1>{APPENDIX_TITLE}</h1>
    <p>原书里不是菜谱、却值得读的部分——前言、书末工艺附录、版权页，共 <strong>{len(pages)}</strong> 页，逐页与原书页图对照。</p>
  </div>
  {"".join(blocks)}
  {skipped_html if skipped_rows else ""}
</main>
"""
    return _layout(f"{APPENDIX_TITLE} · {SITE_TITLE}", body, depth=1)


def render_index_page(
    recipes: list[dict[str, Any]],
    categories: list[str],
    appendix: list[dict[str, Any]] | None = None,
    ingredients: list[dict[str, Any]] | None = None,
) -> str:
    book_chips = "".join(
        f'<button class="chip" data-filter="book" data-value="{bid}">{_book_label(bid)}</button>'
        for bid in sorted(BOOK_LABELS)
    )
    cat_chips = "".join(
        f'<button class="chip" data-filter="category" data-value="{_esc(c)}">{_esc(c)}</button>'
        for c in categories
    )
    appendix = appendix or []
    # 首页入口：菜谱之外的内容（附录专文）此前读者完全看不到，这里给一条明路。
    # 每篇专文一张卡，直接落到该篇第一页（不是索引页，少一次点击）。
    first_page: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for page in appendix:
        name = page.get("article")
        if not name:
            continue
        first_page.setdefault(name, page)
        counts[name] = counts.get(name, 0) + 1
    appendix_html = ""
    if appendix:
        links = "".join(
            f'<li class="card">'
            f'<a href="{APPENDIX_DIRNAME}/{_esc(first_page[name]["slug"])}.html">{_esc(name)}</a>'
            f'<div class="sub">{_book_label(first_page[name].get("book_id", ""))} · {counts[name]} 页</div></li>'
            for name in first_page
        )
        appendix_html = f"""
  <section class="promo">
    <h2><a href="{APPENDIX_DIRNAME}/index.html">{APPENDIX_TITLE}</a></h2>
    <p>原书里不是菜谱、却值得读的 <strong>{len(appendix)}</strong> 页：书末的酱卤与冷盘工艺、刀法图解，以及前言与版权页。</p>
    <ul class="grid">{links}</ul>
  </section>"""

    # 食材入口：与专文入口同一版式，卡片给最常用的几味，落到具体食材页。
    ingredients = ingredients or []
    ingredient_html = ""
    if ingredients:
        top = ingredients[:12]
        links = "".join(
            f'<li class="card">'
            f'<a href="{INGREDIENT_DIRNAME}/{_esc(item["base"])}.html">{_esc(item["base"])}</a>'
            f'<div class="sub">{item["count"]} 道菜</div></li>'
            for item in top
        )
        variants_total = sum(len(item["variants"]) for item in ingredients)
        ingredient_html = f"""
  <section class="promo">
    <h2><a href="{INGREDIENT_DIRNAME}/index.html">{INGREDIENT_TITLE}</a></h2>
    <p>原书 <strong>{variants_total}</strong> 种食材写法归为 <strong>{len(ingredients)}</strong> 个条目：
    每页列出用到它的全部菜谱，并按原书写法（净 / 水发 / 熟 / 片 / 丝…）分组照录。
    菜谱正文里的食材名都是链接，点一下即到。</p>
    <ul class="grid">{links}</ul>
  </section>"""

    body = f"""
<main class="home">
  <div class="hero">
    <h1>{SITE_TITLE}</h1>
    <p>{SITE_SUBTITLE}——共 <strong>{len(recipes)}</strong> 道菜，641 页原书扫描图逐页校对。</p>
  </div>
  {ingredient_html}
  {appendix_html}
  <div class="controls">
    <input id="q" type="search" placeholder="搜索菜名、食材、做法…" autocomplete="off">
    <div class="chips">
      <button class="chip active" data-filter="book" data-value="">全部册</button>{book_chips}
    </div>
    <div class="chips">
      <button class="chip active" data-filter="category" data-value="">全部分类</button>{cat_chips}
    </div>
    <p class="count"><span id="count">{len(recipes)}</span> 道菜</p>
  </div>
  <ul id="list" class="grid"></ul>
  <p id="empty" class="empty" hidden>没有匹配的菜谱。</p>
</main>
"""
    return _layout(SITE_TITLE, body, depth=0, extra_head='<script defer src="site/data.js"></script>\n<script defer src="site/app.js"></script>')


STYLE_CSS = """
:root{
  --bg:#f6f1e7; --panel:#fffdf8; --ink:#2f2a24; --muted:#7b7168; --line:#e0d6c6;
  --accent:#9c3024; --accent-soft:#f2e2df;
}
@media (prefers-color-scheme:dark){
  :root{ --bg:#1b1815; --panel:#232019; --ink:#ece5da; --muted:#a1978a; --line:#3a342c;
    --accent:#e2705f; --accent-soft:#3a251f; }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"PingFang SC","Microsoft YaHei","Hiragino Sans GB",system-ui,sans-serif;
  line-height:1.75;}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.topbar{display:flex;justify-content:space-between;align-items:center;gap:1rem;
  padding:.9rem 1.4rem;border-bottom:1px solid var(--line);background:var(--panel);
  position:sticky;top:0;z-index:10}
.brand{font-size:1.15rem;font-weight:700;color:var(--ink);display:flex;flex-direction:column}
.brand-sub{font-size:.72rem;font-weight:400;color:var(--muted)}
main{max-width:1100px;margin:0 auto;padding:1.5rem 1.4rem 3rem}
.hero h1{font-size:2rem;margin:.2rem 0 .4rem;letter-spacing:.06em}
.hero p{color:var(--muted);margin:0 0 1.4rem}
.controls{position:sticky;top:57px;background:var(--bg);padding:.6rem 0 .8rem;z-index:5}
#q{width:100%;padding:.7rem .9rem;font-size:1rem;border:1px solid var(--line);
  border-radius:8px;background:var(--panel);color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.6rem}
.chip{border:1px solid var(--line);background:var(--panel);color:var(--muted);
  padding:.28rem .7rem;border-radius:999px;font-size:.82rem;cursor:pointer}
.chip:hover{border-color:var(--accent)}
.chip.active{background:var(--accent);border-color:var(--accent);color:#fff}
.count{color:var(--muted);font-size:.85rem;margin:.7rem 0 0}
.grid{list-style:none;padding:0;margin:1rem 0 0;display:grid;gap:.7rem;
  grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:.8rem .9rem}
.card:hover{border-color:var(--accent)}
.card a{display:block;color:var(--ink);font-weight:600}
.card .sub{color:var(--muted);font-size:.78rem;margin-top:.25rem}
.empty{color:var(--muted);text-align:center;padding:2rem}
.crumbs{color:var(--muted);font-size:.85rem;margin:0 0 .6rem}
.recipe h1{font-size:1.9rem;margin:.2rem 0 .3rem}
.aliases,.meta{color:var(--muted);font-size:.88rem;margin:.1rem 0}
.warn{background:var(--accent-soft);border-left:3px solid var(--accent);
  padding:.5rem .8rem;font-size:.86rem;margin:.9rem 0}
.cols{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:2rem;margin-top:1.4rem;align-items:start}
.block{margin:0 0 1.4rem}
.block h2{font-size:1rem;letter-spacing:.14em;color:var(--accent);
  border-bottom:1px solid var(--line);padding-bottom:.3rem;margin:0 0 .6rem}
.block ul{margin:0;padding-left:1.1rem}
.block li{margin:.3rem 0}
.steps li{margin:.7rem 0;list-style:none;margin-left:-1.1rem}
.scans{position:sticky;top:75px}
.scans h2{font-size:1rem;letter-spacing:.14em;color:var(--accent);
  border-bottom:1px solid var(--line);padding-bottom:.3rem;margin:0 0 .6rem}
.scans figure{margin:0 0 1rem}
.scans img{width:100%;border:1px solid var(--line);border-radius:6px;background:#fff}
.scans figcaption{color:var(--muted);font-size:.78rem;text-align:center;margin-top:.3rem}
sup.fn{font-size:.62em;line-height:0;vertical-align:super;margin:0 .12em}
sup.fn a{padding:0 .12em;font-weight:700;text-decoration:none}
sup.fn a:hover{text-decoration:none;background:var(--accent-soft);border-radius:3px}
.notes{margin:0 0 1.4rem;border-top:1px solid var(--line);padding-top:.6rem}
.notes summary{font-size:1rem;letter-spacing:.14em;color:var(--accent);cursor:pointer}
.fnlist{margin:.5rem 0 0;padding-left:1.4rem;font-size:.86rem;color:var(--muted)}
.fnlist li{margin:.45rem 0}
.fnlist li:target{background:var(--accent-soft);border-radius:4px}
.fn-back{font-size:.9em}
.btn{display:inline-block;border:1px solid var(--accent);color:var(--accent);
  padding:.45rem 1rem;border-radius:8px;font-size:.88rem}
.btn:hover{background:var(--accent);color:#fff;text-decoration:none}
.topbar nav a{margin-left:.9rem;font-size:.9rem}
.promo{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:1rem 1.1rem;margin:0 0 1.2rem}
.promo h2{font-size:1.05rem;margin:0 0 .3rem;letter-spacing:.08em}
.promo h2 a{color:var(--accent)}
.promo p{color:var(--muted);font-size:.88rem;margin:0}
.promo .grid{margin-top:.8rem;grid-template-columns:repeat(auto-fill,minmax(180px,1fr))}
.appendix .prose p{margin:.65rem 0;text-indent:1em;text-align:justify}
.appendix .prose{font-size:.98rem}
.muted{color:var(--muted)}
.pager{margin:.2rem 0 1.2rem;font-size:.88rem;color:var(--muted)}
.pagelist{list-style:none;padding:0;margin:.4rem 0 0;display:flex;flex-wrap:wrap;gap:.4rem}
.pagelist a{border:1px solid var(--line);background:var(--panel);border-radius:6px;
  padding:.2rem .6rem;font-size:.82rem;display:inline-block}
.appendix-index .block{margin-bottom:1.6rem}
/* 食材链接：正文里出现频繁，故只用底线 + 极淡底色，不抢正文的黑度；
   accent 系变量在明暗两套配色里都已调过对比度，跟着它走即可。 */
a.ing{color:inherit;text-decoration:none;
  border-bottom:1px solid color-mix(in srgb,var(--accent) 45%,transparent);
  background:color-mix(in srgb,var(--accent-soft) 55%,transparent);
  border-radius:2px;padding:0 .06em}
a.ing:hover,a.ing:focus{color:var(--accent);background:var(--accent-soft);
  border-bottom-color:var(--accent);text-decoration:none}
@supports not (color:color-mix(in srgb,red,blue)){
  a.ing{border-bottom:1px solid var(--accent);background:var(--accent-soft)}
}
.ingredient .variant{margin-bottom:1.6rem;scroll-margin-top:70px}
.ingredient .variant:target h2{color:var(--ink);background:var(--accent-soft);
  border-radius:4px;padding-left:.3rem}
.ingredient .hero p{margin:0 0 .4rem}
.dishlist{list-style:none;padding:0;margin:.4rem 0 0}
.dishlist li{margin:.35rem 0;display:flex;flex-wrap:wrap;gap:.5rem;align-items:baseline}
.dishlist .sub{color:var(--muted);font-size:.78rem}
.ingredient-index .grid{grid-template-columns:repeat(auto-fill,minmax(140px,1fr))}
.ingredient-index .card a{font-weight:600}
.footer{border-top:1px solid var(--line);margin-top:2rem;padding:1.2rem 1.4rem;
  color:var(--muted);font-size:.78rem;text-align:center}
.footer p{margin:.25rem 0}
@media (max-width:820px){
  .cols{grid-template-columns:1fr;gap:1.2rem}
  .scans{position:static}
}
"""

APP_JS = """
(function () {
  var data = (window.SHANXI_DATA || {}).recipes || [];
  var list = document.getElementById('list');
  var countEl = document.getElementById('count');
  var emptyEl = document.getElementById('empty');
  var q = document.getElementById('q');
  var filters = { book: '', category: '' };

  var params = new URLSearchParams(location.search);
  if (params.get('book')) filters.book = params.get('book');
  if (params.get('category')) filters.category = params.get('category');

  function matches(r) {
    if (filters.book && r.b !== filters.book) return false;
    if (filters.category && r.c !== filters.category) return false;
    var term = q.value.trim();
    if (!term) return true;
    return r.s.indexOf(term) !== -1;
  }

  function render() {
    var frag = document.createDocumentFragment();
    var n = 0;
    for (var i = 0; i < data.length; i++) {
      var r = data[i];
      if (!matches(r)) continue;
      n++;
      var li = document.createElement('li');
      li.className = 'card';
      var a = document.createElement('a');
      a.href = 'recipes/' + encodeURIComponent(r.u) + '.html';
      a.textContent = r.t;
      var sub = document.createElement('div');
      sub.className = 'sub';
      sub.textContent = r.bl + ' · ' + r.p + ' · ' + r.c;
      li.appendChild(a);
      li.appendChild(sub);
      frag.appendChild(li);
    }
    list.textContent = '';
    list.appendChild(frag);
    countEl.textContent = n;
    emptyEl.hidden = n > 0;
  }

  q.addEventListener('input', render);
  document.querySelectorAll('.chip').forEach(function (chip) {
    chip.addEventListener('click', function () {
      var kind = chip.dataset.filter;
      filters[kind] = chip.dataset.value;
      document.querySelectorAll('.chip[data-filter="' + kind + '"]').forEach(function (c) {
        c.classList.toggle('active', c === chip);
      });
      render();
    });
  });

  document.querySelectorAll('.chip').forEach(function (chip) {
    if (chip.dataset.value && chip.dataset.value === filters[chip.dataset.filter]) {
      document.querySelectorAll('.chip[data-filter="' + chip.dataset.filter + '"]').forEach(function (c) {
        c.classList.toggle('active', c === chip);
      });
    }
  });

  render();
})();
"""


def build_site(root: Path) -> dict[str, Any]:
    """生成静态站到仓库根目录,返回统计信息。"""
    vault_root = root / "work" / "vault"
    anchor_path = root / "work" / "reports" / "toc_anchor_map.json"
    recipes = load_recipes(vault_root)
    anchor_map = json.loads(anchor_path.read_text(encoding="utf-8")) if anchor_path.exists() else {}
    lookup = build_category_lookup(anchor_map)
    annotations = load_annotations(root / "project" / "config" / "annotations.yaml")
    claimed: set[int] = set()
    annotations_rendered = 0

    appendix_pages, appendix_skipped = appendix_plan(load_page_fallbacks(vault_root))

    ingredient_index = build_ingredient_index(recipes)
    linker = IngredientLinker(ingredient_index)

    site_dir = root / "site"
    recipes_dir = root / "recipes"
    appendix_dir = root / APPENDIX_DIRNAME
    ingredient_dir = root / INGREDIENT_DIRNAME
    site_dir.mkdir(exist_ok=True)
    recipes_dir.mkdir(exist_ok=True)
    appendix_dir.mkdir(exist_ok=True)
    ingredient_dir.mkdir(exist_ok=True)

    # 菜名变化会改变文件名，旧 HTML 若不清理会留在 recipes/ 里继续被发布。
    # 先记下本次应当产出的文件名，收尾时删除多余者。
    expected_pages = {f"{recipe['slug']}.html" for recipe in recipes}

    entries: list[dict[str, Any]] = []
    categories: set[str] = set()
    for recipe in recipes:
        book_id = recipe.get("book_id", "")
        category = category_for(lookup, book_id, _first_page(recipe))
        categories.add(category)
        pages = recipe.get("local_pages") or []
        blob = " ".join(
            [str(recipe.get("title", ""))]
            + [str(a) for a in (recipe.get("aliases") or [])]
            + [str(i) for i in (recipe.get("ingredients") or [])]
            + [str(i) for i in (recipe.get("seasonings") or [])]
            + [str(i) for i in (recipe.get("steps") or [])]
            + [str(i) for i in (recipe.get("tips") or [])]
        )
        entries.append(
            {
                "u": recipe["slug"],
                "t": recipe.get("title") or recipe["slug"],
                "b": book_id,
                "bl": _book_label(book_id),
                "p": _page_range(pages),
                "c": category,
                "s": blob,
            }
        )
        # 先算命中情况（这一步负责 WARNING 与统计），再把命中的那几条交给渲染。
        # 只传命中的，渲染时就不会重复报一遍未命中。
        candidates = annotations_for_recipe(annotations, recipe, claimed)
        _rows, matched, _missed = attach_annotations(recipe, candidates)
        claimed.update(id(item) for item in matched)
        annotations_rendered += len(matched)
        (recipes_dir / f"{recipe['slug']}.html").write_text(
            render_recipe_page(recipe, category, SITE_BASE, matched, linker),
            encoding="utf-8",
        )

    entries.sort(key=lambda e: (e["b"], e["u"]))
    ordered_categories = sorted(c for c in categories if c != UNCATEGORIZED)
    if UNCATEGORIZED in categories:
        ordered_categories.append(UNCATEGORIZED)

    # 附录页：与菜谱页共用注释机制（同一个 claimed 集合，annotations_unmatched 才准）。
    for page in appendix_pages:
        candidates = annotations_for_recipe(annotations, page, claimed)
        _rows, matched, _missed = attach_annotations(page, candidates, APPENDIX_SECTIONS)
        claimed.update(id(item) for item in matched)
        annotations_rendered += len(matched)
        (appendix_dir / f"{page['slug']}.html").write_text(
            render_appendix_page(page, SITE_BASE, matched, linker), encoding="utf-8"
        )
    (appendix_dir / "index.html").write_text(
        render_appendix_index(appendix_pages, appendix_skipped), encoding="utf-8"
    )

    for item in ingredient_index:
        (ingredient_dir / f"{item['base']}.html").write_text(
            render_ingredient_page(item), encoding="utf-8"
        )
    (ingredient_dir / "index.html").write_text(
        render_ingredient_index(ingredient_index), encoding="utf-8"
    )

    (root / "index.html").write_text(
        render_index_page(recipes, ordered_categories, appendix_pages, ingredient_index),
        encoding="utf-8",
    )
    (site_dir / "style.css").write_text(STYLE_CSS.strip() + "\n", encoding="utf-8")
    (site_dir / "app.js").write_text(APP_JS.strip() + "\n", encoding="utf-8")
    (site_dir / "data.js").write_text(
        "window.SHANXI_DATA=" + json.dumps({"recipes": entries}, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    (root / ".nojekyll").write_text("", encoding="utf-8")

    # 清理陈旧页面：菜名修正后旧文件名的 HTML 不再对应任何 vault 笔记
    pruned = 0
    for stale in recipes_dir.glob("*.html"):
        if stale.name not in expected_pages:
            LOGGER.info("删除陈旧页面: %s", stale.name)
            stale.unlink()
            pruned += 1

    # 同理清 appendix/：改动 APPENDIX_ARTICLES（缩小范围、改页码分段）后旧页不能留。
    expected_appendix = {"index.html"} | {f"{page['slug']}.html" for page in appendix_pages}
    appendix_pruned = 0
    for stale in appendix_dir.glob("*.html"):
        if stale.name not in expected_appendix:
            LOGGER.info("删除陈旧附录页: %s", stale.name)
            stale.unlink()
            appendix_pruned += 1

    # 同理清 ingredients/：改基名规则、或原书写法被校对改动后，旧基名页不能留。
    expected_ingredients = {"index.html"} | {
        f"{item['base']}.html" for item in ingredient_index
    }
    ingredients_pruned = 0
    for stale in ingredient_dir.glob("*.html"):
        if stale.name not in expected_ingredients:
            LOGGER.info("删除陈旧食材页: %s", stale.name)
            stale.unlink()
            ingredients_pruned += 1

    # 一条注释若全库无人认领，就是锚文本没对上（菜名改了、文本被归一化动过、页码写错）。
    # 静默跳过会让注释悄悄消失，所以在这里显形。
    unmatched = [item for item in annotations if id(item) not in claimed]
    for item in unmatched:
        LOGGER.warning(
            "注释锚文本未命中，该注释不会出现在站上: %s p%s 「%s」%s",
            item.get("book_id"),
            item.get("local_page"),
            item.get("anchor"),
            f"（slug={item['slug']}）" if item.get("slug") else "",
        )

    stats = {
        "recipes": len(recipes),
        "pruned": pruned,
        "appendix_pages": len(appendix_pages),
        "appendix_pruned": appendix_pruned,
        "fallbacks_skipped": len(appendix_skipped),
        "ingredient_pages": len(ingredient_index),
        "ingredient_variants": sum(len(i["variants"]) for i in ingredient_index),
        "ingredients_pruned": ingredients_pruned,
        "categories": len(ordered_categories),
        "uncategorized": sum(1 for e in entries if e["c"] == UNCATEGORIZED),
        "annotations": len(annotations),
        "annotations_rendered": annotations_rendered,
        "annotations_unmatched": len(unmatched),
    }
    LOGGER.info(
        "Site built: %s recipes, %s appendix pages (%s fallbacks skipped), "
        "%s ingredient pages (%s written forms), "
        "%s categories (%s uncategorized), annotations %s rendered / %s unmatched",
        stats["recipes"],
        stats["appendix_pages"],
        stats["fallbacks_skipped"],
        stats["ingredient_pages"],
        stats["ingredient_variants"],
        stats["categories"],
        stats["uncategorized"],
        stats["annotations_rendered"],
        stats["annotations_unmatched"],
    )
    return stats
