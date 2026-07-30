"""菜名归一策略（2026-07-30 用户裁定，见 work/reports/待裁定.csv 第 1 类）。

三条规则，都只作用于**菜名**（vault 标题 / aliases / 目录锚点），不动正文与 raw_excerpt：

1. **括号全角归一**：菜名里的半角 ``()`` 一律作全角 ``（）``。原书排版本身两种都用
   （目录「焖牛(羊)肉」/ 正文「焖牛（羊）肉」），纯排版差异不该在成品库里分裂成两条。
   笔记文件名与站点 URL 由 ``safe_filename`` 走 NFKC，仍是半角，**不受影响**（URL 不漂）。

2. **「（清素）」批注剥离**：书1 素菜类有 5 道菜的正文标题带「（清素）」——那是编者
   标注这道菜属清素做法，不是菜名的一部分（目录里就不带）。剥出去，同时把带批注的
   原写法记进 aliases：站点搜索索引与「又作：」都收 aliases，检索「清素」仍能命中，
   信息不丢。其余括号批注（酿菜/粉鱼/如意卷/原名金钱油饼/四种/又名香肚/酿皮子）
   **保留在标题里**——用户只裁定删「（清素）」。

3. **目录写法作 alias**：目录与正文菜名打架时以正文为准（用户主规则「默认菜名不同
   以正文，除非特殊说」），目录写法记为 alias 供检索。只在两种**判据明确**的形态下认亲，
   宁可少给一个 alias 也不认错人：

   - *单字之差*：长度相同且恰好一个字不同（海参煨蹄子 / 海参烀蹄子）；
   - *括号批注之差*：剥掉括号批注后完全相同（炒凉粉 / 炒凉粉（粉鱼））。

   **异名**（目录「清汤鱿鱼包袱底」对正文「胡辣鱿鱼丝」+「清汤鱿鱼芙蓉底」两道菜）
   一律不认：那种页面本身就是分段器把两道菜并在一起或目录页码错位，猜是哪一道就是编数据。
   候选多于一个时先按**页码**破平（目录锚点已被 ``_resolve_toc_local_pages`` 换算成本地页，
   插值也是册内单调的，落到哪一页是可靠信号）：只留 ``local_pages`` 含该页的候选；
   仍不唯一就一个都不认（「滑溜里脊片」「焦溜里脊片」这类互相认亲的必须挡掉）。
"""

from __future__ import annotations

import re

from .models import RecipeCandidate

_FULLWIDTH_PARENS = str.maketrans({"(": "（", ")": "）"})

# 括号批注（成对、不嵌套）。与 review_priority.TOC_ANNOTATION_RE 同口径。
ANNOTATION_RE = re.compile(r"[（(][^（()）]*[)）]")

# 只有这些批注词从标题里剥出去（用户 2026-07-30 裁定「括号内删掉」的那 5 条）。
# 剥掉的原写法进 aliases，不会凭空丢失。
STRIPPED_ANNOTATIONS = ("清素",)


def to_fullwidth_parens(text: str) -> str:
    """菜名里的半角圆括号归一为全角。"""
    return text.translate(_FULLWIDTH_PARENS)


def strip_stripped_annotations(title: str) -> str:
    """剥掉 ``STRIPPED_ANNOTATIONS`` 里那几个批注，其余括号批注原样留在标题里。"""

    def drop(match: re.Match[str]) -> str:
        inner = match.group(0)[1:-1].strip()
        return "" if inner in STRIPPED_ANNOTATIONS else match.group(0)

    return ANNOTATION_RE.sub(drop, title).strip()


# 菜名首尾的孤立分隔符是 OCR 残留（书4 p22 的标题被读成「·怪味肚丁」,那个间隔号
# 一路进了 vault 标题、笔记文件名和站点 URL）。只剥首尾,不动名字中间的顿号
# （「大饼、家常饼」「炒饼、烩饼、焖饼」是原书就有的并列菜名）。
_EDGE_SEPARATORS = "、·-—. "


def core_title(title: str) -> str:
    """剥掉全部括号批注后的菜名主干（用于目录 / 正文认亲）。"""
    return ANNOTATION_RE.sub("", to_fullwidth_parens(title)).strip(_EDGE_SEPARATORS)


def _add_alias(recipe: RecipeCandidate, alias: str) -> None:
    alias = to_fullwidth_parens(alias).strip()
    if not alias or alias == recipe.title:
        return
    if alias not in recipe.aliases:
        recipe.aliases.append(alias)


def _one_char_apart(left: str, right: str) -> bool:
    if len(left) != len(right) or left == right:
        return False
    return sum(1 for a, b in zip(left, right) if a != b) == 1


# 目录里的「（附…）」不是这道菜的别名,是目录自己的交叉引用:
# 「炒拨鱼（附，拨鱼方法）」= 附带讲拨鱼的手法,「糯米稍梅（附甜翠稍梅）」里的
# 甜翠稍梅还是**另一道菜**。挂成「又作：…」会误导读者。
_APPENDED_NOTE_RE = re.compile(r"[（(]\s*附")


def _is_alias_pair(title: str, toc_title: str) -> bool:
    """目录写法与正文菜名是否「同一道菜的两种写法」。"""
    if not toc_title or title == toc_title:
        return False
    if _one_char_apart(title, toc_title):
        return True
    core = core_title(title)
    if not core or core != core_title(toc_title):
        return False
    return not _APPENDED_NOTE_RE.search(toc_title)


# ---------------------------------------------------------------------------
# 逐条页图核定的「目录写法 → 正文菜名」认亲名单（2026-07-30 第二批）
#
# `_is_alias_pair` 的两条自动判据（单字之差 / 括号批注之差）**故意收得很紧**，
# 认不出「多字之差」与「异名」——那是为了不编数据。下面这几条是**回页图逐字核对后
# 确认成因**的：既不是页码错位、也不是分段漏切，而是**原书目录与正文本身不一致**，
# 两边都不是 OCR 错。总规则「默认以正文为准，目录写法作 alias」照用，只是需要
# 显式点名（键含册号与本地页，页码不对就不认，等于自带一道守卫）。
#
#   · sxcp-2 p46：正文「锅烧拆骨肉」（第三字扌+斤、斤上有点＝拆）／目录「锅烧折骨」
#     （四字、无点＝折）。差两个位置（拆/折 + 少一个「肉」），自动判据认不出。
#   · sxcp-2 p52：正文「红烧肉米金皮」／目录漏印「红」字作「烧肉米金皮」。
#   · sxcp-2 p54：正文「清汤捶鸡片」（主料生鸡脯肉）／目录「清汤捶里脊片」。
#   · sxcp-3 p14：正文「羊（牛）肉小炒煮馍」——**羊在前**，正文通篇同序
#     （「净羊肉或牛肉三十斤」「化羊（牛）油」）；目录作「牛（羊）肉小炒煮馍」，
#     沿用了上一条（p12 牛（羊）肉煮馍）的顺序。同长度但差两个字，自动判据认不出。
#
# 键的括号一律写全角：`attach_toc_aliases` 在查表前已把目录写法过 `to_fullwidth_parens`。
TOC_ALIAS_PAIRS: dict[tuple[str, int, str], str] = {
    ("sxcp-2", 46, "锅烧折骨"): "锅烧拆骨肉",
    ("sxcp-2", 52, "烧肉米金皮"): "红烧肉米金皮",
    ("sxcp-2", 54, "清汤捶里脊片"): "清汤捶鸡片",
    ("sxcp-3", 14, "牛（羊）肉小炒煮馍"): "羊（牛）肉小炒煮馍",
}

# 目录之外的菜名变体（原书正文自己给出的另一种做法名）。
# 书2 p54 清汤捶鸡片 的同页附注写着「清汤捶鸡丝，配料亦改成丝」——那是原书点明的
# 同菜变体，挂成 alias 后检索「清汤捶鸡丝」能落到这道菜上。
# 键 = (册号, 本条的首个本地页, 正文菜名)：页码或菜名对不上就不挂，不会张冠李戴。
MANUAL_ALIASES: dict[tuple[str, int, str], tuple[str, ...]] = {
    ("sxcp-2", 54, "清汤捶鸡片"): ("清汤捶鸡丝",),
}


def attach_manual_aliases(recipes: list[RecipeCandidate]) -> list[dict[str, str]]:
    """挂 ``MANUAL_ALIASES`` 里那几条正文自带的菜名变体。返回清单供审计。"""
    attached: list[dict[str, str]] = []
    for recipe in recipes:
        if not recipe.local_pages:
            continue
        key = (recipe.book_id, recipe.local_pages[0], recipe.title)
        for alias in MANUAL_ALIASES.get(key, ()):
            before = list(recipe.aliases)
            _add_alias(recipe, alias)
            if recipe.aliases != before:
                attached.append(
                    {"book_id": recipe.book_id, "title": recipe.title, "alias": alias}
                )
    return attached


def apply_title_policy(recipes: list[RecipeCandidate]) -> list[dict[str, str]]:
    """规则 1 + 2。返回改动清单供日志/审计。"""
    changes: list[dict[str, str]] = []
    for recipe in recipes:
        old = recipe.title
        annotated = to_fullwidth_parens(old).strip(_EDGE_SEPARATORS)
        title = strip_stripped_annotations(annotated)
        recipe.aliases = [to_fullwidth_parens(alias) for alias in recipe.aliases]
        if title and title != old:
            recipe.title = title
            if title != annotated:
                # 真剥掉了内容（「（清素）」）→ 带批注的写法进 aliases,检索不丢。
                # 只改了括号全半角的不进 aliases:那是排版差异,记下来只是噪音。
                _add_alias(recipe, annotated)
            changes.append({"book_id": recipe.book_id, "old": old, "new": title})
        # 归一后 alias 可能与标题重合（旧的 title_override 遗留),去重
        recipe.aliases = [
            alias for alias in dict.fromkeys(recipe.aliases) if alias and alias != recipe.title
        ]
    return changes


def attach_toc_aliases(
    recipes: list[RecipeCandidate],
    toc_titles: dict[str, list[tuple[str, int]]],
) -> list[dict[str, str]]:
    """规则 3：把目录写法挂到对应菜谱的 aliases 上。返回挂上去的清单供审计。

    ``toc_titles`` = ``{book_id: [(目录菜名, 该锚点的本地页), …]}``。
    """
    attached: list[dict[str, str]] = []
    by_book: dict[str, list[RecipeCandidate]] = {}
    for recipe in recipes:
        by_book.setdefault(recipe.book_id, []).append(recipe)

    for book_id, rows in by_book.items():
        known = {name for row in rows for name in [row.title, *row.aliases]}
        for raw, local_page in toc_titles.get(book_id, []):
            toc_title = to_fullwidth_parens(raw).strip(_EDGE_SEPARATORS)
            if not toc_title or toc_title in known:
                continue  # 目录与正文一字不差,不需要 alias
            # 页图核定的显式认亲优先（自动判据认不出的「多字之差」，见 TOC_ALIAS_PAIRS）
            named = TOC_ALIAS_PAIRS.get((book_id, local_page, toc_title))
            if named:
                matches = [row for row in rows if row.title == named]
                if len(matches) == 1:
                    _add_alias(matches[0], toc_title)
                    attached.append(
                        {"book_id": book_id, "title": named, "alias": toc_title}
                    )
                continue
            matches = [row for row in rows if _is_alias_pair(row.title, toc_title)]
            if len(matches) > 1 and local_page:
                # 「牛肉脆」同时与「牛肉脯」「牛肉松」差一个字:按目录锚点落在哪一页破平。
                on_page = [row for row in matches if local_page in row.local_pages]
                if on_page:
                    matches = on_page
            # 唯一才认亲;认不出的是「异名」类,留给人工裁定
            if len(matches) != 1:
                continue
            recipe = matches[0]
            _add_alias(recipe, toc_title)
            attached.append({"book_id": book_id, "title": recipe.title, "alias": toc_title})
    return attached
