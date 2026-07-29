from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import BookEntry, NormalizedPage, PageFallbackNote, RecipeCandidate, ReviewItem
from .utils import (
    is_plausible_dish_title,
    normalize_text,
    split_numbered_steps,
    strip_recipe_enumerator,
)

SECTION_HEADERS = {
    # 「原材料」是书3的常用写法（「一、原材料：」），必须排在「原料」之前，
    # 否则 startswith("原料") 永远匹配不到它，整区原料会落进 other_text。
    "ingredients": ("一、原材料", "原材料", "一、原料", "原料", "一、用料", "用料"),
    # 「制作方法」必须排在「制作」之前，否则「二、制作方法：」只会命中「制作」，
    # 残留的「方法：」被当成正文留下。
    "steps": ("二、制作方法", "制作方法", "二、制法", "制法", "二、作法", "作法", "方法", "制作"),
    "tips": ("三、特点", "特点", "提示", "说明", "附注", "注"),
}

INGREDIENT_LABELS = ("主料", "配料", "原料", "用料")
SEASONING_LABELS = ("调料", "佐料", "辅料")


@dataclass
class ActiveRecipe:
    title: str
    book: BookEntry
    source_pdf: str
    source_json: str
    ocr_engine: str
    local_pages: list[int] = field(default_factory=list)
    blocks: list[dict[str, Any]] = field(default_factory=list)
    page_flags: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# 书4 部分菜用「（一）用料：」「（二）作法：」而非「一、用料：」编排章节，
# 与菜名的「（数字）菜名」同形。旧实现把这些章节头也判成菜名，
# 于是一道菜被撕成「桂花桶鸭(空)」+「用料」+「作法」多条记录。
_SECTION_WORDS = (
    "用料", "原料", "材料", "配料", "主料", "调料",
    "作法", "制法", "做法", "方法", "制作",
    "特点", "说明", "附注", "注意", "备注",
)


# 菜名不会以冒号收尾。「（1）干馍：」「（2）云云：」是原料区里的子项标签
# （（三二）兴平干馍和云云馍 一菜两式），旧实现把它们当成新菜名，
# 于是父菜谱被截成「食材0 步骤0」的空壳，内容全被划给了子项。
_TRAILING_COLON = re.compile(r"[：:]\s*$")


def is_recipe_title(text: str) -> bool:
    normalized = normalize_text(text)
    cleaned = normalized.strip("：: ")
    if not cleaned:
        return False
    if cleaned.endswith("类") or "目录" in cleaned or cleaned == "陕西菜谱":
        return False
    match = re.match(r"^[（(]?[一二三四五六七八九十百零〇0-9]+[）)]\s*(.+)", cleaned)
    if not match:
        return False
    # 序号后接章节名 → 是章节头，不是菜名
    remainder = match.group(1).strip("：: ")
    if remainder.startswith(_SECTION_WORDS):
        return False
    if _TRAILING_COLON.search(normalized):
        return False
    # 「(1)葱花酥油饼: 将猪板油切成小丁,…」这种「编号+子项名+整段做法」被 OCR 并成一块时，
    # 旧实现整块当菜名：一段正文成了站点标题与 URL，正主则退化成空壳。
    # 序号后面必须真的像个菜名（长度/句读/用量串/括号成对）才算菜名。
    if not is_plausible_dish_title(remainder):
        return False
    return True


def find_recipe_title_positions(blocks: list[dict[str, Any]]) -> list[int]:
    positions = []
    for index, block in enumerate(blocks):
        if block.get("block_type") == "title" and is_recipe_title(block.get("text", "")):
            positions.append(index)
    return positions


# 书末附录（书4 的「附：酱卤菜的特点及制作方法。」「附：几种特殊刀法」）以「附：」起标题。
# 它之后整段散文没有任何菜名标题，于是一直被当成续页塞给最后一道菜——
# （129）酿青椒 因此把 106～116 页整个刀工/拼盘附录吞了进去。
# 注意书3 p52 的「附：糖 棋 子」是真的附菜，所以只在「附：」后面不像菜名时才当附录边界。
_APPENDIX_HEAD = re.compile(r"^附\s*[：:]\s*(.*)$")


def _is_appendix_page(blocks: list[dict[str, Any]]) -> bool:
    for block in blocks:
        if block.get("block_type") != "title":
            continue
        matched = _APPENDIX_HEAD.match(normalize_text(block.get("text", "")))
        if matched and not is_plausible_dish_title(matched.group(1)):
            return True
    return False


def _append_to_active(active: ActiveRecipe, page: NormalizedPage, blocks: list[dict[str, Any]]) -> None:
    if page.local_page not in active.local_pages:
        active.local_pages.append(page.local_page)
    active.blocks.extend(blocks)
    active.page_flags.append(
        {
            "local_page": page.local_page,
            "confidence": page.confidence,
            "review_needed": page.review_needed,
            "warnings": list(page.warnings),
        }
    )


# 原书用量：数字串 + 单位（+「半」）。字符表与 obsidian_exporter 中的口径保持一致。
_ING_NUM = "〇零一二三四五六七八九十百半两几"
_ING_UNIT = "钱两斤分个只片粒条张朵克根块付副枚棵把碗匙勺撮"
# 成对括号注。原书括号里既有工艺说明（（去皮）（切细丝）（实耗）），也有用量说明
# （（一条）（约二斤）（2-3斤）（约100条）），全角半角还常混排（「绿叶菜(洗净）」）。
# 允许嵌一层：「红薯一斤半（山药、扁（豌）豆粉亦可）」只认内层会把外层整段漏掉。
_ING_PAREN = re.compile(r"[（(](?:[^（()）]|[（(][^（()）]*[）)])*[）)]")
# 括号注在配对时整体缩成一个占位字符（见 _mask_parens）：括号里的用量因此不可能
# 被当成本条的用量。旧实现把「（」「）」当普通名称字符，于是括号内的用量会截断配对——
# 「活鲤鱼（一条）约二斤」切成「活鲤鱼（ 一条」+「）约 二斤」，全书 72 处；
# 「甲鱼 重（2-3斤）一个」更惨：2-3 不是汉字，扫描从括号后重启，名称只剩「斤）」。
_ING_MASK = "\x00"
# 用量可以是复合的：原书写「面粉 二斤五两」「食盐 一两一钱」「猪肉 三斤半」。
# 旧正则一次只吃一个「数字串+单位」，于是「面粉 二斤五两 猪板油 一斤」被切成
# 「面粉 二斤」+「五两猪板油 一斤」——被丢下的「五两」黏成了下一味原料的名字
# （（七四）渭南时辰包子）。因此量词组要允许连续出现。
# 用量后面还可以跟一个括号注（「猪前肘一斤（一个）」「面粉 十斤（其中酵面二斤）」），
# 不在这里收住，尾括号就会变成下一条的开头（「（ 一个」）。
# 中间容一个 OCR 杂点（「小 曲 一两. (暑季用曲量为七钱)」的句点），但标点只在
# 确实跟着括号注时才吃——否则「A 二钱、B（切碎）三钱」会把顿号并进 A 的用量。
# 这里与 obsidian_exporter._PAIR 有意不同：那边只取名字喂食材索引，
# 多余的前导用量由 _clean_ingredient 事后剥掉，本函数则要原样保留用量串。
# 末尾允许一串光秃秃的数字：原书把「一钱二分」省写成「一钱二」（书1 p94「盐 一钱二」、
# 书2 p57「菜籽油 一两二」，页图已核）。不收这个尾巴，用量就被截成「一钱」——
# 那是写错分量，比不写更糟。必须锚在片段末尾（\Z）：不锚的话
# 「酱油 二钱 三鲜汤 半斤」会把下一味料名字的首字吃成用量（「二钱三」）。
_ING_QTY = (
    rf"(?:[{_ING_NUM}]+[{_ING_UNIT}]半?)+"
    rf"(?:[{_ING_NUM}]+\Z)?"
    rf"(?:[.．。、，,]?{_ING_MASK})?"
)
# 名称里仍收裸括号：OCR 截断的「配料：白菜心（或」没有成对括号可掩，
# 不收就整行匹配不上、退化成一条。
_ING_PAIR = re.compile(rf"([一-鿿、（）(){_ING_MASK}]+?)({_ING_QTY})")
# 标签后面必须是分隔符、空白或行尾。原书的分隔符是「：」，OCR 常读成「；」「，」「·」「。」，
# 所以不能只认冒号；但也不能像原先那样让分隔符整个可省——那样「调料面 二分」
# （五香调料面，是一味原料）会被当成「调料：面 二分」，把它后面继承分组的续行
# 整段错记成调料（（三二）兴平干馍和云云馍 的「云云」用料就是这样丢的）。
_ING_LABEL = re.compile(r"^(主料|配料|调料|佐料|辅料|原料|用料)(?:\s*[:：；;，,、·．.。]\s*|\s+|$)")
# 行中分组标签必须带冒号才切：行首标签允许省略冒号（原书排版如此），
# 但行中若不要求冒号，「各种调料。」这类正文里的「调料」也会被误切。
_ING_LABEL_SPLIT = re.compile(r"(主料|配料|调料|佐料|辅料|原料|用料)\s*[:：]")


def _clean_ing_name(name: str) -> str:
    """去掉原书为对齐插入的空格：「蛋 清」→「蛋清」、「葱 花」→「葱花」。"""
    return re.sub(r"\s+", "", name).strip("、 ")


def _join_aligned_chars(segment: str) -> str:
    """合并原书为对齐插入的字间空格：「味 精 少许」→「味精 少许」。

    只用于拆不出用量、整段保留的片段——配对成功的条目其名称已由
    _clean_ing_name 收过空格。这里不能像那样一律删空格：整段保留的片段常常
    还带着字段分隔（「蒜苗 食盐」是两味料、「米醋 适量 蒜水 适量」是两组名称+用量），
    删光就粘成一坨。只合并「恰好两个连续单字」：
      · 单字与多字之间的空格是字段分隔，动了「盐 适量」会并成「盐适量」；
      · 三个以上连续单字在本书实测都是多栏名称被拆碎（「椒 草 果」是花椒+草果、
        「味 精 绍 酒」是味精+绍酒），合并只会把不同名称粘在一起。
    原书名称以两字为主，对齐时插一个空格，正好落在这条规则里。
    """
    merged: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if len(run) == 2:
            merged.append("".join(run))
        else:
            merged.extend(run)
        run.clear()

    for token in segment.split():
        if len(token) == 1:
            run.append(token)
            continue
        flush()
        merged.append(token)
    flush()
    return " ".join(merged)


def _mask_parens(text: str) -> tuple[str, list[tuple[int, int]]]:
    """把每个成对括号注压成一个占位字符，便于按「名称 用量」配对。

    同时返回占位串每个字符对应的原文区间，配对完按区间取回原文——
    不用「先替换再还原」，是因为未被任何条目吃掉的括号注会让还原序错位。
    """
    masked: list[str] = []
    spans: list[tuple[int, int]] = []
    position = 0
    for matched in _ING_PAREN.finditer(text):
        for index in range(position, matched.start()):
            masked.append(text[index])
            spans.append((index, index + 1))
        masked.append(_ING_MASK)
        spans.append(matched.span())
        position = matched.end()
    for index in range(position, len(text)):
        masked.append(text[index])
        spans.append((index, index + 1))
    return "".join(masked), spans


def _unmask(text: str, spans: list[tuple[int, int]], start: int, end: int) -> str:
    """取回占位串 [start, end) 对应的原文（含被压掉的括号注）。"""
    return text[spans[start][0]:spans[end - 1][1]]


_WHITESPACE = re.compile(r"\s")


def _strip_spaces_with_map(text: str) -> tuple[str, list[int]]:
    """去掉空白，同时返回「去空白串的每个下标 → 原文下标」的映射。

    配对判断必须在去空白的串上做（原书为对齐在名称/用量中间插空格），
    但残余片段要按原文切片才能保住字段之间的空格（「食盐 味精 适量」是三个词，
    按去空白串取回就粘成「食盐味精适量」）。
    """
    kept = [index for index, char in enumerate(text) if not _WHITESPACE.match(char)]
    return "".join(text[index] for index in kept), kept


# 未被任何「名称+用量」对覆盖的残余文本要保留，但先得判断它是不是一条真原料。
# 两端先剥掉标点（「。香菜（切段）」→「香菜（切段）」，「八角，」→「八角」），
# 但**不剥括号**：原书的「（切段）」「（实耗）」是条目自身的注。
_ING_RESIDUE_EDGE = "、，,。．.：:；;·…！!？?-－—‐~～"
# 剥完必须还剩汉字/数字/字母才算内容。这一条挡掉全书 27 处行末孤立句号、
# 「1.」这种步骤序号残片，以及 OCR 用来占位漏字的「▢」。
_ING_RESIDUE_REAL = re.compile(r"[一-鿿0-9A-Za-z]")
# 「制法」标题整行没被 OCR 出来时，整段做法散文会留在原料区。这类行本来就已经
# 产出一堆假条目——分区本身由 _implied_steps_start 补救，但补救不了的（页面残缺到
# 连步骤序号都没有）仍会漏到这里。残余片段在这里会是半句话，
# 灌进原料表只会更脏，所以这类片段只跳过收集，其它行为一概不变。
# 判据：以步骤序号开头，或长段落里出现句中句号/分号——原书的原料行只在末尾带句号。
_STEP_ENUM_HEAD = re.compile(r"^\s*\d+\s*[.、．]")
_PROSE_BREAK = re.compile(r"[。；](?!\s*$)")
_PROSE_MIN_LEN = 40


def _residue_items(
    segment: str,
    body_map: list[int],
    masked: str,
    spans: list[tuple[int, int]],
    covered: bytearray,
) -> list[tuple[int, str]]:
    """收集「一个 pair 都没覆盖到」的残余片段，作为不带用量的条目保留。

    原书里这些残余绝大多数是**用量不是数词**的条目：「酱油 少许」「菜油 适量」
    「香精 微量」「葱段、姜块少许」，以及 OCR 把「半两」读成「平两」这类错字
    （sxcp-1 p79 条子肉 的「菜籽油 平两」）。旧实现只在整段一个都配不上时兜底，
    于是「湿淀粉 一钱半 菜籽油 平两」前半配上、后半被静默丢掉。
    这里**不猜用量**：配不上就照原文留着，OCR 错字交给校对/清洗规则。
    """
    if _STEP_ENUM_HEAD.match(segment):
        return []
    if len(segment) >= _PROSE_MIN_LEN and _PROSE_BREAK.search(segment):
        return []
    found: list[tuple[int, str]] = []
    index = 0
    while index < len(masked):
        if covered[index]:
            index += 1
            continue
        end = index
        while end < len(masked) and not covered[end]:
            end += 1
        start_char = body_map[spans[index][0]]
        end_char = body_map[spans[end - 1][1] - 1] + 1
        text = segment[start_char:end_char].strip().strip(_ING_RESIDUE_EDGE).strip()
        # 先合并对齐空格再判标签：原书的「配 料：」被 OCR 读散后残余是「配 料」，
        # 不先合并就认不出它只是个组标签
        text = _join_aligned_chars(text)
        if text and _ING_RESIDUE_REAL.search(text):
            label_only = _ING_LABEL.match(text)
            # 光一个「配料」不是条目（OCR 把「配 料：」读散时会剩下它）
            if not (label_only and label_only.end() == len(text)):
                found.append((index, text))
        index = end
    return found


def _extract_ing_items(segment: str, label: str) -> list[str]:
    """把一个（可能带组标签的）原料片段拆成若干「名称 用量」条目。"""
    segment = segment.strip("：: ")
    if not segment:
        return []
    body, body_map = _strip_spaces_with_map(segment)
    masked, spans = _mask_parens(body)
    found: list[tuple[int, str]] = []
    covered = bytearray(len(masked))
    for matched in _ING_PAIR.finditer(masked):
        name = _clean_ing_name(_unmask(body, spans, *matched.span(1)))
        if not name:
            continue
        found.append((matched.start(), f"{name} {_unmask(body, spans, *matched.span(2))}"))
        for position in range(matched.start(), matched.end()):
            covered[position] = 1
    if found:
        # 配上的条目与残余片段按原文先后混排，顺序与原书一致
        found.extend(_residue_items(segment, body_map, masked, spans, covered))
        found.sort(key=lambda pair: pair[0])
        items = [text for _position, text in found]
    else:
        # 拆不出用量时整段保留，不丢信息（只收掉对齐用的字间空格）
        items = [_join_aligned_chars(segment)]
    if label:
        items[0] = f"{label}：{items[0]}"     # 组标签只出现在该组首条，与原书排版一致
    return items


def _split_ingredient_line(text: str, current_group: str) -> tuple[list[tuple[str, str]], str]:
    """把一行原料拆成若干 (分组, 「名称 用量」) 条目，并返回行尾所处的分组。

    两个关键点：
    1. **没有标签的续行继承上一行的分组**。原书里「调料：」下面往往还有两三行继续
       列调料（葱花/姜米/味精…），旧实现逐行独立判断，把这些续行一律归到
       ingredients，导致调料被错分到食材。
    2. **组标签可能出现在行中而不只在行首**。OCR 把原书竖排对齐的两三行并成一行时，
       「调料：」会落到行中央（如 sxcp-2 p144 绣球鱼肚、sxcp-1 p59 炝肚块），
       旧实现的标签正则锚定 `^`，整行只能按行首标签（或继承的分组）归类，
       「调料：」之后的食盐/味精/葱姜就被错记成食材。因此先按标签切段再逐段抽取。
    """
    normalized = normalize_text(text).strip("：: ")
    if not normalized:
        return [], current_group

    entries: list[tuple[str, str]] = []
    group = current_group
    head_label = ""
    # 行首标签单独处理：原书行首的标签常省略冒号（「调料 葱花 一钱」），行中的不能这样放宽
    label_match = _ING_LABEL.match(normalized)
    if label_match:
        head_label = label_match.group(1)
        group = "seasoning" if head_label in SEASONING_LABELS else "ingredient"
        normalized = normalized[label_match.end():]

    # re.split 带一个捕获组 → [首段, 标签1, 段1, 标签2, 段2, ...]
    pieces = _ING_LABEL_SPLIT.split(normalized)
    for item in _extract_ing_items(pieces[0], head_label):
        entries.append((group, item))         # 首段沿用行首标签或继承来的分组
    for index in range(1, len(pieces) - 1, 2):
        label = pieces[index]
        group = "seasoning" if label in SEASONING_LABELS else "ingredient"
        for item in _extract_ing_items(pieces[index + 1], label):
            entries.append((group, item))
    return entries, group


# ---------------------------------------------------------------------------
# 分栏原料表：名称块与用量块被 MinerU 拆开后的复原
#
# 原书原料表是「名称 用量 名称 用量」的两栏网格（书1 p92/p94、书2 p57/p137、
# 书4 p90 等，页图已核）。MinerU 大多把一整印刷行读成一块，但遇到栏间空白过宽时
# 会按栏切块，于是右栏的名称与用量各自成块：名称块抽不出用量，用量块没有名字，
# 成品库里就出现一串裸食材名 + 一串孤立分量（（八三）烧牛蹄筋 是典型）。
#
# 复原只依据 bbox：同一印刷行（y 区间重叠）内按 x 从左到右，
# 若某块以「光秃秃的用量」开头、而它左边一块以「没有用量的名称」结尾，
# 就把这段用量搬到左边那块的末尾——等于把 MinerU 切开的印刷行缝回去。
# 关键约束：**只在数据本身能定归属时才配**。
#   · 左边那块已经以用量收尾（说明本行左栏是完整的）→ 不搬，孤立用量原样留着。
#     书1 p94「调料：绍酒 三钱」右边的「六钱」就是这种：它的名字「酱油」整块被
#     OCR 漏掉了，谁也不知道该配给谁，宁可留一个没名字的分量。
#   · 用量必须是完整的「数字+单位」。书1 p203「调料：白糖」右边只剩一个「两」
#     （「二」被漏掉），不成用量 → 不搬，白糖就没有分量，不猜。
_ING_QTY_RE = re.compile(_ING_QTY)
_ING_QTY_HEAD = re.compile(rf"^(?:{_ING_QTY})")
# 判断「尾巴还是名字吗」时要忽略的字符：数字、单位、占位符与标点。
# 剩下还有字符才算真有名字——「一两二」的尾巴「二」全是数字，不算名字。
_ING_TAIL_FILLER = set(_ING_NUM + _ING_UNIT + _ING_MASK + "、，,。．.：:；;·…！!？?（）()「」 ")


def _nonspace_cut(text: str, count: int) -> int:
    """返回原文中「前 count 个非空白字符」之后的切点。

    配对判断都在去空白的串上做（原书为对齐在名称/用量中间插空格，
    「二 个」「一 两」都是一个用量），切原文时得把这些空格换算回来。
    """
    seen = 0
    for index, char in enumerate(text):
        if not char.isspace():
            seen += 1
            if seen == count:
                return index + 1
    return len(text)


def _peel_head_qty(text: str) -> tuple[str, str]:
    """剥掉行首那段没有名字的用量，返回 (用量, 余下文本)。"""
    body = re.sub(r"\s+", "", text)
    if not body:
        return "", text
    masked, spans = _mask_parens(body)
    matched = _ING_QTY_HEAD.match(masked)
    if not matched or matched.end() == 0:
        return "", text
    cut = _nonspace_cut(text, spans[matched.end() - 1][1])
    return text[:cut].strip(), text[cut:].strip()


def _ends_with_bare_name(text: str) -> bool:
    """这块是不是以「没有用量的名称」收尾？只有这样才敢把右边的用量接过来。"""
    body = re.sub(r"\s+", "", text)
    if not body:
        return False
    label_only = _ING_LABEL.match(body)
    if label_only and label_only.end() == len(body):
        return False          # 光一个「调料：」不是名称，别让它把右边的用量吞了
    masked, _spans = _mask_parens(body)
    last_end = 0
    for matched in _ING_QTY_RE.finditer(masked):
        last_end = matched.end()
    return any(char not in _ING_TAIL_FILLER for char in masked[last_end:])


def _ingredient_region_mask(blocks: list[dict[str, Any]], carry: bool) -> tuple[list[bool], bool]:
    """标出哪些块落在原料区内，并返回本页末尾是否仍在原料区。

    原料区会跨页（书1 p202 的「一、原料：」下面，调料行续到了 p203 页首），
    所以状态要在页间传递。章节头与菜名本身不参与配对，一律标 False。
    """
    mask: list[bool] = []
    in_ingredients = carry
    for block in blocks:
        text = normalize_text(block.get("text", ""))
        if is_recipe_title(text):
            in_ingredients = False
            mask.append(False)
            continue
        section, _remainder = _match_section_header(text)
        if section is not None:
            in_ingredients = section == "ingredients"
            mask.append(False)
            continue
        mask.append(in_ingredients)
    return mask, in_ingredients


def _printed_rows(items: list[tuple[int, dict[str, Any]]]) -> list[list[tuple[int, dict[str, Any]]]]:
    """按 bbox 的 y 区间重叠把块归成印刷行，行内按 x 从左到右排序。

    用「重叠过半」而不是「中心点相差几像素」：原料表相邻行只差 3～5 像素间距，
    中心点容差稍大就会把上下两行并成一行，用量会接到上一行的名称上。
    """
    rows: list[list[tuple[int, dict[str, Any]]]] = []
    for entry in sorted(items, key=lambda pair: (pair[1]["bbox"][1] + pair[1]["bbox"][3]) / 2):
        bbox = entry[1]["bbox"]
        placed = False
        if rows:
            head = rows[-1][0][1]["bbox"]
            overlap = min(head[3], bbox[3]) - max(head[1], bbox[1])
            shorter = min(head[3] - head[1], bbox[3] - bbox[1])
            if shorter > 0 and overlap * 2 >= shorter:
                rows[-1].append(entry)
                placed = True
        if not placed:
            rows.append([entry])
    for row in rows:
        row.sort(key=lambda pair: pair[1]["bbox"][0])
    return rows


def _repair_split_columns(
    blocks: list[dict[str, Any]],
    carry: bool,
) -> tuple[list[dict[str, Any]], bool]:
    """把被 MinerU 按栏切开的原料行缝回去（详见本节顶部说明）。"""
    mask, next_carry = _ingredient_region_mask(blocks, carry)
    candidates = [
        (index, block)
        for index, (block, flag) in enumerate(zip(blocks, mask))
        if flag and isinstance(block.get("bbox"), list) and len(block["bbox"]) == 4
    ]
    if len(candidates) < 2:
        return blocks, next_carry

    patched: dict[int, str] = {}
    dropped: set[int] = set()
    for row in _printed_rows(candidates):
        if len(row) < 2:
            continue
        previous_index = -1
        for index, block in row:
            text = patched.get(index, normalize_text(block.get("text", "")))
            if previous_index >= 0:
                head_qty, remainder = _peel_head_qty(text)
                if head_qty and _ends_with_bare_name(patched[previous_index]):
                    patched[previous_index] = f"{patched[previous_index]} {head_qty}"
                    text = remainder
                    if not text:
                        dropped.add(index)
                        continue
            patched[index] = text
            previous_index = index

    repaired: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        if index in dropped:
            continue
        if index in patched and patched[index] != normalize_text(block.get("text", "")):
            block = {**block, "text": patched[index]}
        repaired.append(block)
    return repaired, next_carry


# 章节序号前缀：原书排版不一，「一、原料」「一 原料」「一，原料」「一.原料」都出现过。
# 旧实现只按字面 startswith 匹配，凡分隔符不是「、」的都漏识，整行被当成食材条目留下。
# 书4 另有「（一）用料：」「（二）作法:」的带括号编排（如 (81) 桂花桶鸭），
# 旧正则不认括号形式 → 该菜整条原料/做法都归不进任何区，只靠 other_text 兜底救回两行。
_SECTION_ENUM = re.compile(
    r"^(?:[（(]\s*[一二三四五六七八九十\d]+\s*[）)]|[一二三四五六七八九十]\s*[、，,．.。:：]?)\s*"
)


# 章节头后面只可能跟标点（原书是「：」，OCR 常读成「。」「，」「.」「、」）或行尾。
# 若紧跟汉字，那就是一句以该词开头的正文，不是章节头——书4 书末附录的
# 「原材料经洗刷整理干净…」「原料切成片、条、丝、块后…」正是这样把整段散文
# 翻成了原料区，「制法简单，薄脆酥香。」（特点行）也被误判成制法标题。
_HEADER_TAIL = re.compile(r"^[：:；;。，,．.、·…！!？?\s]")


def _match_section_header(text: str) -> tuple[str | None, str]:
    normalized = normalize_text(text)
    candidates = [normalized]
    stripped = _SECTION_ENUM.sub("", normalized, count=1)
    if stripped and stripped != normalized:
        candidates.append(stripped)
    for candidate in candidates:
        for section, headers in SECTION_HEADERS.items():
            for header in headers:
                if not candidate.startswith(header):
                    continue
                remainder = candidate[len(header) :]
                if remainder and not _HEADER_TAIL.match(remainder):
                    continue
                # 原先只剥「：:；; 」，于是「二、制法。」剥完还剩「。」，
                # 这个孤立句号会作为一条步骤留在正文里。
                return section, remainder.lstrip("：:；;。，,．.、·…！!？? ")
    return None, normalized


# OCR 把「一、用料：」读成「一、用补：」「一、用情。」「一、用朴：」这类残行。
# 它是章节头而不是数据，落进原料区只会变成一条无用量的垃圾条目。
_GARBLED_SECTION_LINE = re.compile(
    r"^(?:[（(]\s*[一二三四五六七八九十\d]+\s*[）)]|[一二三四五六七八九十]\s*[、，,．.。:：])"
    r"\s*[^\s]{0,4}[：:。.]?$"
)


def _implied_ingredients_end(blocks: list[dict[str, Any]]) -> int:
    """原料区扫描褪色、「一、原料」整行没被 OCR 出来时，按版式位置推断原料区。

    返回原料区的结束下标（>0 表示「菜名之后、制法之前」这一段应按原料解析）。
    只在两个条件同时成立时才推断，避免把书末的刀工附录、豆腐脑散文当成原料：
      ① 本条以自己的菜名开头（不是续页片段）；
      ② 后面确实出现「制法/作法」标题，原料区有明确右边界。
    先遇到「原料」标题说明不需要推断；先遇到「特点」等说明版式不明，一律不猜。
    """
    if not blocks:
        return 0
    if not is_recipe_title(normalize_text(blocks[0].get("text", ""))):
        return 0
    for index, block in enumerate(blocks[1:], start=1):
        text = normalize_text(block.get("text", ""))
        if not text:
            continue
        section, _remainder = _match_section_header(text)
        if section == "steps":
            return index
        if section is not None:
            return 0
    return 0


# 原料区里出现的步骤序号（「1. 制皮面：…」）。必须是**裸**序号:
# 「（1）干馍：」「（2）云云：」是「一菜两式」的子项标签（书3 p40/p41 兴平干馍和云云馍），
# 它们也在原料区里,但后面跟的是各自的原料表而不是做法,误判会把整张原料表划给 steps。
_IMPLIED_STEP_ENUM = re.compile(r"^\s*(\d+)\s*[.、．]")
# 原料区里残缺的「二、×××：」章节头。本书的章节序号是固定的:一=原料、二=制法、三=特点,
# 所以原料区里冒出来的「二、…」只可能是没被认出来的制法标题——
# 书3 p23 黄桂油糕印的「二、制法：」几乎褪没,OCR 读成「二、制馅：」（与下一行的
# 「1. 制馅：」串了行);书4 p83 四季豆腐印的「二、作法：」被读成「二、你法：」。
_IMPLIED_STEPS_HEAD = re.compile(r"^[二2]\s*[、，,．.。:：]\s*(?P<name>[^\s]{1,4}?)[：:。.]?$")
_HAN = re.compile(r"[一-鿿]")


def _is_implied_steps_head(text: str) -> bool:
    matched = _IMPLIED_STEPS_HEAD.match(text)
    if not matched:
        return False
    name = matched.group("name")
    # 章节名是纯汉字词（制法/作法/你法/制馅…）。要求全汉字挡掉「二、三钱」这种
    # 用量残片,要求至少一个字不是数词/量词挡掉「二、三四」这种编号串。
    return all(_HAN.match(char) for char in name) and any(
        char not in _ING_NUM + _ING_UNIT for char in name
    )


def _implied_steps_start(blocks: list[dict[str, Any]]) -> tuple[int, bool]:
    """「制法」标题整行没被 OCR 出来时,推断 steps 区的起点。

    返回 `(下标, 该块本身是不是标题)`;下标 0 表示不推断。整段做法散文留在原料区的后果是
    steps 为空、原料表里塞着半截句子（书3 p89 糯米稍梅、书3 p23 黄桂油糕、书4 p83 四季豆腐）。

    只在**本条完全没有可识别的制法标题**时才推断,并且只认两种硬信号:
      ① 原料区里有残缺的「二、×××：」章节头 → 它就是制法标题（见 _IMPLIED_STEPS_HEAD）;
      ② 原料区里出现裸步骤序号,且从 1 开始逐个递增 → 第一条就是 steps 的起点。
    另要求边界之前还剩至少一块原料区内容,免得把整条原料表划给 steps。
    """
    section = "ingredients" if _implied_ingredients_end(blocks) else "other"
    ingredient_blocks = 0
    header_index = -1
    numbered: list[tuple[int, int]] = []
    for index, block in enumerate(blocks):
        text = normalize_text(block.get("text", ""))
        if not text or is_recipe_title(text):
            continue
        matched_section, _remainder = _match_section_header(text)
        if matched_section is not None:
            if matched_section == "steps":
                return 0, False       # 制法标题在,不需要推断
            section = matched_section
            continue
        if section != "ingredients":
            continue
        if header_index < 0 and not numbered and _is_implied_steps_head(text):
            header_index = index
            continue
        if header_index < 0:
            if _IMPLIED_STEP_ENUM.match(text):
                numbered.append((index, int(_IMPLIED_STEP_ENUM.match(text).group(1))))
            else:
                ingredient_blocks += 1

    if not ingredient_blocks:
        return 0, False
    if header_index >= 0:
        return header_index, True
    if numbered and all(number == order + 1 for order, (_index, number) in enumerate(numbered)):
        return numbered[0][0], False
    return 0, False


def _finalize_recipe(active: ActiveRecipe) -> tuple[RecipeCandidate, list[ReviewItem]]:
    ingredients: list[str] = []
    seasonings: list[str] = []
    steps: list[str] = []
    tips: list[str] = []
    other_text: list[str] = []
    review_items: list[ReviewItem] = []

    implied_end = _implied_ingredients_end(active.blocks)
    implied_steps, implied_steps_is_head = _implied_steps_start(active.blocks)
    current_section = "ingredients" if implied_end else "other"
    ingredient_group = "ingredient"   # 原料区内的当前分组，供无标签续行继承
    for index, block in enumerate(active.blocks):
        text = normalize_text(block.get("text", ""))
        if not text:
            continue
        if is_recipe_title(text):
            continue
        if implied_steps and index == implied_steps:
            current_section = "steps"
            if implied_steps_is_head:
                continue      # 这一块就是残缺的制法标题，本身不是步骤内容
        matched_section, remainder = _match_section_header(text)
        if matched_section:
            current_section = matched_section
            if not remainder:
                continue
            text = remainder
        elif index < implied_end and _GARBLED_SECTION_LINE.match(text):
            continue   # 推断出的原料区里的残缺章节头，丢弃而不是当成原料条目

        if current_section == "ingredients":
            entries, ingredient_group = _split_ingredient_line(text, ingredient_group)
            for group, item in entries:
                (seasonings if group == "seasoning" else ingredients).append(item)
        elif current_section == "seasonings":
            seasonings.append(text)
        elif current_section == "steps":
            steps.extend(split_numbered_steps(text))
        elif current_section == "tips":
            tips.append(text)
        else:
            other_text.append(text)

    if not ingredients and other_text:
        ingredients.extend(other_text[:2])
    if not steps and other_text:
        steps.extend(other_text[:3])

    warning_pool = list(active.warnings)
    flag_conflicts = 0
    for page_flag in active.page_flags:
        warning_pool.extend(page_flag["warnings"])
        if page_flag["review_needed"]:
            flag_conflicts += 1

    raw_excerpt = normalize_text("\n".join(block.get("text", "") for block in active.blocks))[:600]
    title = strip_recipe_enumerator(active.title)
    pages = sorted(set(active.local_pages))
    source_links = [f"{active.book.book_id}#p{page:04d}" for page in pages]

    confidence = "high"
    if not ingredients or not steps:
        confidence = "medium"
    if flag_conflicts or len(pages) > 3 or len(title) <= 1:
        confidence = "low"
    review_needed = confidence == "low" or flag_conflicts > 0

    if review_needed:
        for page in pages:
            review_items.append(
                ReviewItem(
                    book_id=active.book.book_id,
                    local_page=page,
                    reason="recipe boundary or structure needs manual verification",
                    source_pdf_path=active.source_pdf,
                    source_json_path=active.source_json,
                )
            )

    recipe = RecipeCandidate(
        title=title,
        aliases=[],
        series=active.book.series,
        book_id=active.book.book_id,
        book_file=active.book.file_name,
        local_pages=pages,
        source_pdf=active.source_pdf,
        source_json=active.source_json,
        # 原料/调料不去重：原书的原料表本来就会把同一味料列两次——渭南时辰包子的
        # 「葱 二斤」分皮面与肉馅两栏，兴平干馍和云云馍 一菜两式各列一份「面粉 一斤」。
        # 更要紧的是 MinerU 会把两栏表拆成「每格一块」（鱼香猪肝：主料：净猪肝／四两／
        # 配料：泡辣椒／二钱／调料：葱花／二钱…），用量格自成一条；按字符串去重会把
        # 重复的「二钱」合并，名称与用量的先后配对随之报废。
        # 制法/特点仍去重：那是连续文字，逐字重复只可能是同一块被并进来两次。
        ingredients=ingredients,
        seasonings=seasonings,
        steps=list(dict.fromkeys(steps)),
        tips=list(dict.fromkeys(tips)),
        raw_excerpt=raw_excerpt,
        related_notes=[],
        ocr_engine=active.ocr_engine,
        confidence=confidence,
        status="recipe" if confidence in {"high", "medium"} else "review",
        review_needed=review_needed,
        source_links=source_links,
        warnings=list(dict.fromkeys(warning_pool)),
    )
    return recipe, review_items


def _page_to_fallback(page: NormalizedPage) -> tuple[PageFallbackNote, list[ReviewItem]]:
    review_items = []
    if page.review_needed or page.confidence in {"low", "failed"}:
        review_items.append(
            ReviewItem(
                book_id=page.book_id,
                local_page=page.local_page,
                reason="page-level fallback requires review",
                source_pdf_path=page.source_pdf_path,
                source_json_path=page.source_json_path,
            )
        )
    note = PageFallbackNote(
        title=f"{page.book_id} 第{page.local_page}页 页面回退",
        series=page.series,
        book_id=page.book_id,
        book_file=page.book_file,
        local_pages=[page.local_page],
        source_pdf=page.source_pdf_path,
        source_json=page.source_json_path,
        raw_excerpt=page.raw_text[:800],
        cleaned_text=page.cleaned_text,
        related_notes=[],
        ocr_engine=page.ocr_engine,
        confidence=page.confidence,
        status=page.structure_hints.get("page_kind", "fallback"),
        review_needed=page.review_needed,
        source_links=[f"{page.book_id}#p{page.local_page:04d}"],
        warnings=list(page.warnings),
        rendered_page_path=page.rendered_page_path,
    )
    return note, review_items


def segment_book(
    book: BookEntry,
    pages: list[NormalizedPage],
) -> tuple[list[RecipeCandidate], list[PageFallbackNote], list[ReviewItem]]:
    recipes: list[RecipeCandidate] = []
    fallbacks: list[PageFallbackNote] = []
    review_items: list[ReviewItem] = []
    active: ActiveRecipe | None = None
    # 原料区跨页续行：本页开头是否还在上一页的原料区里（分栏复原要按页做，
    # 因为 bbox 的 y 只在页内可比）
    ingredients_carry = False

    for page in sorted(pages, key=lambda item: item.local_page):
        blocks = [block for block in page.text_blocks if normalize_text(block.get("text", ""))]
        blocks, ingredients_carry = _repair_split_columns(blocks, ingredients_carry)
        title_positions = find_recipe_title_positions(blocks)
        page_kind = page.structure_hints.get("page_kind")

        is_appendix = _is_appendix_page(blocks)
        if (page_kind in {"toc", "front_matter", "category"} or is_appendix) and not title_positions:
            ingredients_carry = False
            if active is not None:
                recipe, recipe_reviews = _finalize_recipe(active)
                recipes.append(recipe)
                review_items.extend(recipe_reviews)
                active = None
            fallback, fallback_reviews = _page_to_fallback(page)
            fallbacks.append(fallback)
            review_items.extend(fallback_reviews)
            continue

        if title_positions:
            if active is not None:
                leading = blocks[:title_positions[0]]
                if leading:
                    _append_to_active(active, page, leading)
                recipe, recipe_reviews = _finalize_recipe(active)
                recipes.append(recipe)
                review_items.extend(recipe_reviews)
                active = None

            for idx, start in enumerate(title_positions):
                end = title_positions[idx + 1] if idx + 1 < len(title_positions) else len(blocks)
                segment_blocks = blocks[start:end]
                candidate = ActiveRecipe(
                    title=normalize_text(segment_blocks[0].get("text", "")),
                    book=book,
                    source_pdf=page.source_pdf_path,
                    source_json=page.source_json_path,
                    ocr_engine=page.ocr_engine,
                )
                _append_to_active(candidate, page, segment_blocks)
                candidate.warnings.extend(page.warnings)
                if idx + 1 < len(title_positions):
                    recipe, recipe_reviews = _finalize_recipe(candidate)
                    recipes.append(recipe)
                    review_items.extend(recipe_reviews)
                else:
                    active = candidate
            continue

        continuation_like = page_kind == "continuation" or bool(page.cleaned_text)
        if active is not None and continuation_like:
            _append_to_active(active, page, blocks)
            active.warnings.extend(page.warnings)
        else:
            fallback, fallback_reviews = _page_to_fallback(page)
            fallbacks.append(fallback)
            review_items.extend(fallback_reviews)

    if active is not None:
        recipe, recipe_reviews = _finalize_recipe(active)
        recipes.append(recipe)
        review_items.extend(recipe_reviews)

    return recipes, fallbacks, review_items
