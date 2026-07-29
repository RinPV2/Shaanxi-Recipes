from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline.models import BookEntry, NormalizedPage
from shanxi_pipeline.recipe_segmenter import (
    _repair_split_columns,
    _split_ingredient_line,
    is_recipe_title,
    segment_book,
)
from shanxi_pipeline.utils import normalize_text, strip_recipe_enumerator


class SegmenterTests(unittest.TestCase):
    def test_segments_two_recipes_on_one_page(self) -> None:
        book = BookEntry(
            book_id="sxcp-2",
            series=2,
            file_name="陕西菜谱2.pdf",
            file_path="C:/hobby/Shanxi/陕西菜谱2.pdf",
            mineru_json="C:/hobby/Shanxi/example.json",
            status="ready",
            enabled=True,
        )
        page = NormalizedPage(
            book_id="sxcp-2",
            book_file="陕西菜谱2.pdf",
            series=2,
            local_page=9,
            source_pdf_path=book.file_path,
            source_json_path=book.mineru_json,
            raw_text="",
            cleaned_text="（一）猪肉小炒\n一、原料：\n主料：猪肉\n二、制法：\n1. 炒熟。\n（二）水煮肉片\n一、原料：\n主料：猪肉\n二、制法：\n1. 煮熟。",
            text_blocks=[
                {"block_type": "title", "text": "（一）猪肉小炒"},
                {"block_type": "title", "text": "一、原料："},
                {"block_type": "text", "text": "主料：猪肉"},
                {"block_type": "title", "text": "二、制法："},
                {"block_type": "text", "text": "1. 炒熟。"},
                {"block_type": "title", "text": "（二）水煮肉片"},
                {"block_type": "title", "text": "一、原料："},
                {"block_type": "text", "text": "主料：猪肉"},
                {"block_type": "title", "text": "二、制法："},
                {"block_type": "text", "text": "1. 煮熟。"},
            ],
            title_candidates=["（一）猪肉小炒", "（二）水煮肉片"],
            structure_hints={"page_kind": "recipe"},
            ocr_engine="mineru",
            confidence="high",
            warnings=[],
            review_needed=False,
        )
        recipes, fallbacks, review_items = segment_book(book, [page])
        self.assertEqual(len(recipes), 2)
        self.assertEqual(len(fallbacks), 0)
        self.assertEqual(recipes[0].title, "猪肉小炒")
        self.assertEqual(recipes[1].title, "水煮肉片")
        self.assertEqual(len(review_items), 0)


class ZeroLookalikeTitleTests(unittest.TestCase):
    """MinerU 把菜名编号里的「〇」(U+3007) 时而读成几何符号「○」(U+25CB)。

    两者字形几乎一样，码位不同：漏归一时该菜不算标题，整篇被上一道菜吞掉
    （（一○八）奶汤锅子鱼、（一一○）清汤鱼丸、（七○）锅烧羊肉、（一○八）花生辣鸡丁）。
    """

    def test_white_circle_is_canonicalized_to_ideographic_zero(self) -> None:
        self.assertEqual(normalize_text("（一○八）奶汤锅子鱼"), "（一〇八）奶汤锅子鱼")
        self.assertEqual(normalize_text("（七◯）锅烧羊肉"), "（七〇）锅烧羊肉")

    def test_recipe_title_accepts_both_zero_code_points(self) -> None:
        for title in ("（一〇七）清蒸甲鱼", "（一○八）奶汤锅子鱼", "（七○）锅烧羊肉", "（一一○）清汤鱼丸"):
            with self.subTest(title=title):
                self.assertTrue(is_recipe_title(title))

    def test_enumerator_with_white_circle_is_stripped_from_title(self) -> None:
        # U+25CB 落进文件名/站点 URL 的兜底防线
        self.assertIn("\u25cb", "（一○八）奶汤锅子鱼")
        self.assertEqual(strip_recipe_enumerator("（一○八）奶汤锅子鱼"), "奶汤锅子鱼")

    def test_second_recipe_with_white_circle_number_is_not_swallowed(self) -> None:
        book = BookEntry(
            book_id="sxcp-1",
            series=1,
            file_name="陕西菜谱1.pdf",
            file_path="C:/hobby/Shanxi/陕西菜谱1.pdf",
            mineru_json="C:/hobby/Shanxi/example.json",
            status="ready",
            enabled=True,
        )
        blocks = [
            {"block_type": "title", "text": "（一〇七）清蒸甲鱼"},      # U+3007
            {"block_type": "title", "text": "一、原料："},
            {"block_type": "text", "text": "主料：活甲鱼 一只"},
            {"block_type": "title", "text": "二、制法："},
            {"block_type": "text", "text": "1. 蒸熟。"},
            {"block_type": "title", "text": "（一○八）奶汤锅子鱼"},     # U+25CB
            {"block_type": "title", "text": "一、原料："},
            {"block_type": "text", "text": "主料：活鲤鱼 一条"},
            {"block_type": "title", "text": "二、制法："},
            {"block_type": "text", "text": "1. 汆熟。"},
        ]
        page = NormalizedPage(
            book_id="sxcp-1",
            book_file="陕西菜谱1.pdf",
            series=1,
            local_page=117,
            source_pdf_path=book.file_path,
            source_json_path=book.mineru_json,
            raw_text="",
            cleaned_text="\n".join(block["text"] for block in blocks),
            text_blocks=blocks,
            title_candidates=["（一〇七）清蒸甲鱼", "（一○八）奶汤锅子鱼"],
            structure_hints={"page_kind": "recipe"},
            ocr_engine="mineru",
            confidence="high",
            warnings=[],
            review_needed=False,
        )
        recipes, _fallbacks, _reviews = segment_book(book, [page])
        self.assertEqual([recipe.title for recipe in recipes], ["清蒸甲鱼", "奶汤锅子鱼"])
        # 吞并的症状是一篇笔记里出现两组主料
        self.assertEqual(recipes[0].ingredients, ["主料：活甲鱼 一只"])
        self.assertEqual(recipes[1].ingredients, ["主料：活鲤鱼 一条"])


class CompoundQuantityTests(unittest.TestCase):
    """原书用量可以是复合的（二斤五两 / 一钱三分 / 三斤半）。

    一次只吃一个「数字串+单位」时，余下的量词会黏成下一味原料的名字。
    """

    def test_compound_weight_stays_with_its_ingredient(self) -> None:
        entries, group = _split_ingredient_line("面粉 二斤五两 猪板油 一斤", "ingredient")
        self.assertEqual(entries, [("ingredient", "面粉 二斤五两"), ("ingredient", "猪板油 一斤")])
        self.assertEqual(group, "ingredient")

    def test_compound_quantity_after_group_label(self) -> None:
        entries, group = _split_ingredient_line("调料：食盐 一钱三分 醋 半钱", "ingredient")
        self.assertEqual(entries, [("seasoning", "调料：食盐 一钱三分"), ("seasoning", "醋 半钱")])
        self.assertEqual(group, "seasoning")

    def test_numeral_prefixed_ingredient_name_is_not_eaten(self) -> None:
        # 「八角」「五香粉」以数字起头但不是用量，不能被前一味的用量吸走
        entries, _group = _split_ingredient_line("小茴香 一斤八两 八角 四两 五香粉 一钱", "ingredient")
        self.assertEqual(
            [item for _group_name, item in entries],
            ["小茴香 一斤八两", "八角 四两", "五香粉 一钱"],
        )


class ParentheticalNoteTests(unittest.TestCase):
    """括号注里的用量不得被当成本条用量（全书 72 处）。

    括号注在配对时整体缩成一个占位字符，因此「（一条）」「（2-3斤）」既不会截断
    名称，也不会冒充用量；跟在用量后面的括号注则收进用量串。
    """

    def _items(self, line: str) -> list[str]:
        entries, _group = _split_ingredient_line(line, "ingredient")
        return [item for _group_name, item in entries]

    def test_quantity_inside_parens_does_not_split_the_item(self) -> None:
        self.assertEqual(self._items("主料：活鲤鱼（一条）约二斤"), ["主料：活鲤鱼（一条）约 二斤"])
        self.assertEqual(self._items("主料：老母鸡（一只） 二斤"), ["主料：老母鸡（一只） 二斤"])

    def test_ascii_digits_inside_parens_keep_the_name(self) -> None:
        # 2-3 不是汉字：旧实现从括号后重启扫描，名称只剩「斤）」
        self.assertEqual(self._items("主料：甲鱼 重（2-3斤）一个"), ["主料：甲鱼重（2-3斤） 一个"])
        self.assertEqual(self._items("主料：鲜 桃(10个) 二斤"), ["主料：鲜桃(10个) 二斤"])

    def test_trailing_note_stays_with_its_quantity(self) -> None:
        # 不收住尾括号，它就会变成下一条的开头（「（ 一个」）
        self.assertEqual(self._items("主料：猪前肘一斤（一个）"), ["主料：猪前肘 一斤（一个）"])
        self.assertEqual(
            self._items("盐 面 一斤九两(皮面用六两、馅用一斤三两)"),
            ["盐面 一斤九两(皮面用六两、馅用一斤三两)"],
        )

    def test_mixed_width_and_nested_parens(self) -> None:
        # 原书全角半角混排；嵌套只认内层会把外层整段漏掉
        self.assertEqual(self._items("绿叶菜(洗净） 一钱"), ["绿叶菜(洗净） 一钱"])
        self.assertEqual(
            self._items("主料：红薯一斤半（山药、扁（豌）豆粉亦可）"),
            ["主料：红薯 一斤半（山药、扁（豌）豆粉亦可）"],
        )

    def test_ocr_truncated_paren_still_keeps_the_name(self) -> None:
        # 没有成对括号可掩时，裸括号仍要能进名称，否则整行退化成一条
        self.assertEqual(self._items("配料：白菜心（或 三钱"), ["配料：白菜心（或 三钱"])

    def test_separator_before_note_is_not_swallowed_as_quantity(self) -> None:
        # 标点只在确实跟着括号注时才并进用量
        self.assertEqual(self._items("小 曲 一两. (暑季用曲量为七钱)"), ["小曲 一两.(暑季用曲量为七钱)"])
        self.assertEqual(
            self._items("食盐 二钱、味精（去腥）三分"),
            ["食盐 二钱", "味精（去腥） 三分"],
        )


class AlignmentSpaceTests(unittest.TestCase):
    """拆不出用量、整段保留的片段里，只有连续单字之间的空格是原书对齐填充。"""

    def _items(self, line: str) -> list[str]:
        entries, _group = _split_ingredient_line(line, "ingredient")
        return [item for _group_name, item in entries]

    def test_padding_between_single_chars_is_joined(self) -> None:
        # MinerU 把两栏表拆成每格一块时，名称格自成一条（鱼香猪肝 的「蒜 米」）
        self.assertEqual(self._items("蒜 米"), ["蒜米"])
        self.assertEqual(self._items("味 精 少许"), ["味精 少许"])

    def test_field_separators_are_left_alone(self) -> None:
        # 这些空格是字段分隔，删掉就粘成一坨
        self.assertEqual(self._items("蒜苗 食盐"), ["蒜苗 食盐"])
        self.assertEqual(self._items("米醋 适量 蒜水 适量"), ["米醋 适量 蒜水 适量"])
        self.assertEqual(self._items("盐 适量 调料面 适量"), ["盐 适量 调料面 适量"])

    def test_longer_single_char_runs_are_left_alone(self) -> None:
        # 三个以上连续单字是多栏名称被拆碎：「椒 草 果」是花椒+草果，
        # 「味 精 绍 酒」是味精+绍酒，合并只会把不同名称粘在一起
        self.assertEqual(self._items("八角 小茴香花 椒 草 果"), ["八角 小茴香花 椒 草 果"])
        self.assertEqual(self._items("味 精 绍 酒 （适量）"), ["味 精 绍 酒 （适量）"])


class DuplicateIngredientTests(unittest.TestCase):
    """原书的原料表会重复列同一味料，不能按字符串去重。"""

    def test_repeated_ingredient_line_is_kept_twice(self) -> None:
        # 渭南时辰包子：葱分皮面与肉馅两栏，各二斤
        book = BookEntry(
            book_id="sxcp-3",
            series=3,
            file_name="陕西菜谱3.pdf",
            file_path="C:/hobby/Shanxi/陕西菜谱3.pdf",
            mineru_json="C:/hobby/Shanxi/example.json",
            status="ready",
            enabled=True,
        )
        blocks = [
            {"block_type": "title", "text": "（七四）渭南时辰包子"},
            {"block_type": "title", "text": "一 原料"},
            {"block_type": "text", "text": "面粉 二斤五两 猪板油 一斤"},
            {"block_type": "text", "text": "青油 三两 葱 二斤"},
            {"block_type": "text", "text": "葱 二斤 调和面 七钱"},
            {"block_type": "title", "text": "二、制法："},
            {"block_type": "text", "text": "1. 包制即成。"},
        ]
        page = NormalizedPage(
            book_id="sxcp-3",
            book_file="陕西菜谱3.pdf",
            series=3,
            local_page=82,
            source_pdf_path=book.file_path,
            source_json_path=book.mineru_json,
            raw_text="",
            cleaned_text="\n".join(block["text"] for block in blocks),
            text_blocks=blocks,
            title_candidates=["（七四）渭南时辰包子"],
            structure_hints={"page_kind": "recipe"},
            ocr_engine="mineru",
            confidence="high",
            warnings=[],
            review_needed=False,
        )
        recipes, _fallbacks, _reviews = segment_book(book, [page])
        self.assertEqual(len(recipes), 1)
        self.assertEqual(recipes[0].ingredients.count("葱 二斤"), 2)
        self.assertEqual(recipes[0].ingredients[0], "面粉 二斤五两")


class AbbreviatedQuantityTests(unittest.TestCase):
    """原书把「一钱二分」省写成「一钱二」（书1 p94「盐 一钱二」、书2 p57「菜籽油 一两二」、
    书2 p66「米醋 一两六」、书3 p34「食盐 二钱五」，页图 8 倍放大已核）。

    旧实现一次只吃「数字串+单位」，末尾光秃秃的数字被丢掉，用量被截成「一钱」——
    那是把分量写小了，比不写更糟。
    """

    def _items(self, line: str) -> list[str]:
        entries, _group = _split_ingredient_line(line, "ingredient")
        return [item for _group_name, item in entries]

    def test_trailing_bare_numeral_stays_in_the_quantity(self) -> None:
        self.assertEqual(self._items("味精 二分 熟猪油 一两二"), ["味精 二分", "熟猪油 一两二"])
        self.assertEqual(self._items("绍酒 三钱 食盐 二钱五"), ["绍酒 三钱", "食盐 二钱五"])
        self.assertEqual(self._items("葱花 一钱 盐 一钱二"), ["葱花 一钱", "盐 一钱二"])

    def test_bare_numeral_is_only_absorbed_at_the_end_of_the_line(self) -> None:
        # 不锚在行尾，「二钱」后面的「三鲜汤」会被啃掉首字，用量变成「二钱三」
        self.assertEqual(
            self._items("酱油 二钱 三鲜汤 半斤"),
            ["酱油 二钱", "三鲜汤 半斤"],
        )
        self.assertEqual(
            self._items("小茴香 一斤八两 八角 四两"),
            ["小茴香 一斤八两", "八角 四两"],
        )


class SplitColumnRepairTests(unittest.TestCase):
    """原书原料表是「名称 用量 名称 用量」两栏网格，MinerU 遇到宽栏间距会按栏切块，
    右栏的名称与用量各自成块 → 成品库里一串裸食材名 + 一串孤立分量
    （书1 p92 烧牛蹄筋、书2 p137 烧猴头、书4 p90 辣汁茄皮，页图 6 倍放大已核）。

    复原只认 bbox：同一印刷行内按 x 从左到右，把「光秃秃的用量」接到左边
    「没有用量的名称」后面。定不了归属的一律不配。
    """

    def _blocks(self, rows: list[list[tuple[str, int, int]]]) -> list[dict]:
        """rows = [[(文本, x0, x1), ...], ...]，每个 row 是一印刷行（y 自动排）。"""
        blocks = [{"block_type": "title", "text": "一、原料：", "bbox": [80, 60, 160, 78]}]
        for row_index, row in enumerate(rows):
            top = 100 + row_index * 30
            for text, x0, x1 in row:
                blocks.append({"block_type": "text", "text": text, "bbox": [x0, top, x1, top + 20]})
        return blocks

    def _items(self, rows: list[list[tuple[str, int, int]]]) -> list[str]:
        blocks, _carry = _repair_split_columns(self._blocks(rows), False)
        entries: list[str] = []
        group = "ingredient"
        for block in blocks[1:]:
            row_entries, group = _split_ingredient_line(block["text"], group)
            entries.extend(item for _group_name, item in row_entries)
        return entries

    def test_right_column_name_gets_its_own_quantity(self) -> None:
        # 书1 p92：左栏整行成块，右栏名称与用量各自成块
        items = self._items(
            [
                [("配料：水玉兰片（切片）半两", 115, 315), ("水木耳", 348, 414), ("三钱", 477, 510)],
                [("调料：酱 油 半两", 116, 315), ("味 精", 348, 414), ("二分", 477, 510)],
            ]
        )
        self.assertEqual(
            items,
            ["配料：水玉兰片（切片） 半两", "水木耳 三钱", "调料：酱油 半两", "味精 二分"],
        )

    def test_four_cells_all_split_apart(self) -> None:
        # 书2 p57：一行四格全被切开
        items = self._items([[("调料：葱花", 80, 196), ("二钱", 274, 335), ("姜米", 374, 433), ("一钱", 508, 549)]])
        self.assertEqual(items, ["调料：葱花 二钱", "姜米 一钱"])

    def test_quantity_embedded_in_the_middle_block(self) -> None:
        # 书1 p17：中间那块是「上一味的用量 + 下一味的名称」
        items = self._items([[("调料：酱油", 110, 214), ("三钱 甜面酱", 284, 405), ("三钱", 490, 524)]])
        self.assertEqual(items, ["调料：酱油 三钱", "甜面酱 三钱"])

    def test_orphan_quantity_without_a_name_is_left_alone(self) -> None:
        # 书1 p94：右栏名称「酱油」整块被 OCR 漏了，「六钱」无主 → 不许猜，原样留着
        items = self._items([[("调料：绍酒 三钱", 105, 312), ("六钱", 486, 523)]])
        self.assertEqual(items, ["调料：绍酒 三钱", "六钱"])

    def test_incomplete_quantity_is_not_attached(self) -> None:
        # 书1 p203 蜜汁葫芦：「二两」的「二」被漏掉，剩下的「两」不成用量 → 白糖就没分量
        items = self._items([[("调料：白糖", 97, 208), ("两", 278, 315), ("蜂蜜", 348, 403), ("二两", 490, 524)]])
        self.assertEqual(items, ["调料：白糖", "两", "蜂蜜 二两"])

    def test_quantity_does_not_jump_across_printed_rows(self) -> None:
        # 相邻行只差几个像素，行归组松一点就会把用量接到上一行的名称上
        items = self._items([[("配料：水木耳", 115, 315)], [("味精", 115, 315), ("二分", 477, 510)]])
        self.assertEqual(items, ["配料：水木耳", "味精 二分"])

    def test_dangling_name_in_the_middle_of_a_block_keeps_its_quantity(self) -> None:
        # 书1 p94：左块以没有用量的名称收尾（「白 糖 三分 八 角」），右块是它的用量
        items = self._items([[("白 糖 三分 八 角", 157, 399), ("三只", 486, 521)]])
        self.assertEqual(items, ["白糖 三分", "八角 三只"])


class UnpairedResidueTests(unittest.TestCase):
    """配不上「名称+用量」的残余文本不得被静默丢弃（全书 76 处，103 道菜受影响）。

    旧实现只在**整段一个 pair 都配不上**时才整段兜底，于是「前半配上、后半配不上」
    的行会把尾巴直接扔掉：书1 p79 条子肉 的调料行「湿淀粉 一钱半　菜籽油 平两」
    （「平」是 OCR 把「半」读错，页图 12 倍放大已核）只剩下「湿淀粉 一钱半」，
    「菜籽油 平两」整条只活在 raw_excerpt 里。

    受影响的主体是**用量不是数词**的条目——原书大量写「少许」「适量」「微量」
    「两小片」，它们全被丢了。这里不为了配对成功而猜用量：「平两」照「平两」保留。
    """

    def _items(self, line: str) -> list[str]:
        entries, _group = _split_ingredient_line(line, "ingredient")
        return [item for _group_name, item in entries]

    def test_ocr_garbled_quantity_tail_is_kept(self) -> None:
        # 书1 p79 条子肉：「平两」不是数词起头 → 配不上，但不许丢，也不许猜成「半两」
        self.assertEqual(
            self._items("调料：湿淀粉 一钱半 菜籽油 平两"),
            ["调料：湿淀粉 一钱半", "菜籽油 平两"],
        )

    def test_vague_quantities_are_kept(self) -> None:
        # 「少许」「适量」「微量」在原书里到处是，一律不是数词起头
        self.assertEqual(self._items("食盐 二钱 酱油 少许"), ["食盐 二钱", "酱油 少许"])
        self.assertEqual(self._items("白糖 四两 桃红食色素 微量"), ["白糖 四两", "桃红食色素 微量"])
        self.assertEqual(
            self._items("猪棒子骨 八斤 食盐 味精 适量"),
            ["猪棒子骨 八斤", "食盐 味精 适量"],
        )

    def test_residue_keeps_its_field_spacing(self) -> None:
        # 残余按原文切片再合并对齐空格：「香 精 微量」→「香精 微量」，
        # 不能像配对成功的名称那样把空格一律删光（会粘成「香精微量」以外的坨）
        self.assertEqual(self._items("冰 糖 半两 香 精 微量"), ["冰糖 半两", "香精 微量"])

    def test_residue_before_the_first_pair_takes_the_group_label(self) -> None:
        # 书1 p161 煨鱿鱼丝：OCR 在名称与用量之间插了个「·」，配对从「一斤…」重启，
        # 「肥瘦生猪肉」原先整块消失。它是本行第一条，组标签要挂在它头上。
        # （这一处杂点现已由 cleaning_rules 的「汉字·数词」规则在上游剥掉，
        #   本例守的是配对器自身在遇到任何未清洗杂点时的下限。）
        self.assertEqual(
            self._items("配料：肥瘦生猪肉·一 斤 鸡大腿 二个"),
            ["配料：肥瘦生猪肉", "一斤鸡大腿 二个"],
        )

    def test_trailing_punctuation_is_not_an_item(self) -> None:
        # 原书原料行末尾常带句号，OCR 也常读出逗号；它们不是条目
        self.assertEqual(self._items("甜面酱 五 钱 白 糖 二 钱。"), ["甜面酱 五钱", "白糖 二钱"])
        self.assertEqual(
            self._items("葱花、姜米、蒜片共一钱，食盐二分"),
            ["葱花、姜米、蒜片共 一钱", "食盐 二分"],
        )

    def test_ocr_placeholder_alone_is_not_an_item(self) -> None:
        # 「▢」是 OCR 用来占位漏字的记号，单独留着只是残渣
        self.assertEqual(self._items("▢淀粉 二钱"), ["淀粉 二钱"])
        # 但「▢」出现在用量位置时，整条仍要保留（不知道分量 ≠ 没有这味料）
        self.assertEqual(self._items("味精 二分 菜籽油 ▢钱"), ["味精 二分", "菜籽油 ▢钱"])

    def test_stray_group_label_alone_is_not_an_item(self) -> None:
        # 书2 p144：OCR 把「配 料：」读散，标签匹配不上，残余只剩个「配 料」
        self.assertEqual(
            self._items("配 料：水蘑菇 一两 火腿片 一 两"),
            ["水蘑菇 一两", "火腿片 一两"],
        )

    def test_step_prose_in_the_ingredient_region_is_not_harvested(self) -> None:
        # 「制法」标题整行没被 OCR 出来时整段做法会留在原料区。分区本身由
        # _implied_steps_start 补救（见 ImpliedStepsBoundaryTests），这里守的是补救不到时
        # 的下限：那些行会产出假条目，残余是半句话，不该再往原料表里灌句子。
        line = "1. 豆腐切五分见方的小块，冬笋去皮洗净，开水焯过；炒勺座大火上，倒入柴油二斤(实耗二两)，油热八成"
        self.assertEqual(self._items(line), ["豆腐切 五分", "倒入柴油 二斤(实耗二两)"])

    def test_whole_segment_fallback_is_unchanged(self) -> None:
        # 一个 pair 都配不上时仍是整段保留，行为不变
        self.assertEqual(self._items("味 精 少许"), ["味精 少许"])


class ImpliedStepsBoundaryTests(unittest.TestCase):
    """「制法」标题整行没被 OCR 出来时，整段做法散文会留在原料区，steps 变成空。

    全库 3 道：书3 p89 糯米稍梅（标题完全没读出）、书3 p23 黄桂油糕（褪成「二、制馅：」）、
    书4 p83 四季豆腐（读成「二、你法：」）。页图已逐条核对。
    """

    book = BookEntry(
        book_id="sxcp-3",
        series=3,
        file_name="陕西菜谱3.pdf",
        file_path="C:/hobby/Shanxi/陕西菜谱3.pdf",
        mineru_json="C:/hobby/Shanxi/example.json",
        status="ready",
        enabled=True,
    )

    def _page(self, blocks: list[dict], local_page: int = 89) -> NormalizedPage:
        return NormalizedPage(
            book_id="sxcp-3",
            book_file="陕西菜谱3.pdf",
            series=3,
            local_page=local_page,
            source_pdf_path=self.book.file_path,
            source_json_path=self.book.mineru_json,
            raw_text="",
            cleaned_text="\n".join(block["text"] for block in blocks),
            text_blocks=blocks,
            title_candidates=[blocks[0]["text"]],
            structure_hints={"page_kind": "recipe"},
            ocr_engine="mineru",
            confidence="high",
            warnings=[],
            review_needed=False,
        )

    def test_bare_step_enumerator_starting_at_one_opens_the_steps_section(self) -> None:
        # 书3 p89/p90 糯米稍梅：p90 页首的「二、制法：」整行没被 OCR 出来。
        blocks = [
            {"block_type": "title", "text": "（八〇）糯米稍梅"},
            {"block_type": "title", "text": "一、原料："},
            {"block_type": "text", "text": "富强粉 三斤 糯米 二斤"},
            {"block_type": "text", "text": "绍酒 一两"},
            {"block_type": "text", "text": "1. 制皮面：先取面粉一斤放盆内，倒入滚水五两，揉成面团。"},
            {"block_type": "text", "text": "2. 制馅：肋条肉切成二分大的小方丁，加水一两上笼蒸约二十分钟。"},
            {"block_type": "text", "text": "3. 成型蒸制：左手托面皮，拨入馅子，旺火蒸约十分钟即熟。"},
        ]
        recipes, _fallbacks, _reviews = segment_book(self.book, [self._page(blocks)])
        self.assertEqual(1, len(recipes))
        recipe = recipes[0]
        self.assertEqual(["富强粉 三斤", "糯米 二斤", "绍酒 一两"], recipe.ingredients)
        self.assertEqual(3, len(recipe.steps))
        self.assertTrue(recipe.steps[0].startswith("1. 制皮面"))
        self.assertTrue(recipe.steps[-1].startswith("3. 成型蒸制"))

    def test_garbled_section_two_head_is_treated_as_the_steps_title(self) -> None:
        # 一=原料、二=制法、三=特点是全书固定的章节编号，所以原料区里的「二、×××：」
        # 只可能是没被认出来的制法标题（书3 p23「二、制馅：」、书4 p83「二、你法：」）。
        blocks = [
            {"block_type": "title", "text": "（十三）黄桂油糕"},
            {"block_type": "title", "text": "一、原料："},
            {"block_type": "text", "text": "面粉 二十斤 菜籽油 五斤(实耗)"},
            {"block_type": "text", "text": "青红丝 一两 黄桂 三两"},
            {"block_type": "text", "text": "二、制馅："},
            {"block_type": "text", "text": "将桃仁、桔饼、青梅切碎，与白糖、青红丝、黄桂混合，"},
            {"block_type": "text", "text": "再加菜籽油一斤、熟面粉半斤，用力揉搓均匀后，放在盆里待用。"},
            {"block_type": "text", "text": "2. 烫面，清水半锅用旺火烧开，将面粉十八斤分次倒入。"},
        ]
        recipes, _fallbacks, _reviews = segment_book(self.book, [self._page(blocks, 23)])
        recipe = recipes[0]
        self.assertEqual(
            ["面粉 二十斤", "菜籽油 五斤(实耗)", "青红丝 一两", "黄桂 三两"], recipe.ingredients
        )
        # 残缺的标题本身不是步骤内容
        self.assertNotIn("二、制馅：", recipe.steps)
        self.assertEqual(3, len(recipe.steps))
        self.assertTrue(recipe.steps[0].startswith("将桃仁"))

    def test_existing_steps_header_disables_the_inference(self) -> None:
        blocks = [
            {"block_type": "title", "text": "（一）猪肉小炒"},
            {"block_type": "title", "text": "一、原料："},
            {"block_type": "text", "text": "猪肉 一斤"},
            {"block_type": "title", "text": "二、制法："},
            {"block_type": "text", "text": "1. 炒熟。"},
        ]
        recipes, _fallbacks, _reviews = segment_book(self.book, [self._page(blocks, 9)])
        self.assertEqual(["猪肉 一斤"], recipes[0].ingredients)
        self.assertEqual(["1. 炒熟。"], recipes[0].steps)

    def test_parenthesised_sub_labels_do_not_open_a_steps_section(self) -> None:
        # 书3 p40/p41 兴平干馍和云云馍 是一菜两式：「（1）干馍：」「（2）云云：」是原料区
        # 里的子项标签，后面跟的是各自的原料表。误判成步骤会把整张原料表划给 steps。
        blocks = [
            {"block_type": "title", "text": "（三二）兴平干馍和云云馍"},
            {"block_type": "title", "text": "一、原料："},
            {"block_type": "title", "text": "（1）干馍："},
            {"block_type": "text", "text": "面粉 一斤 碱面 二钱"},
            {"block_type": "text", "text": "（2）云云："},
            {"block_type": "text", "text": "面粉 一斤 白糖 四两"},
        ]
        recipes, _fallbacks, _reviews = segment_book(self.book, [self._page(blocks, 40)])
        recipe = recipes[0]
        self.assertEqual([], recipe.steps)
        self.assertIn("面粉 一斤", recipe.ingredients)
        self.assertEqual(2, recipe.ingredients.count("面粉 一斤"))
