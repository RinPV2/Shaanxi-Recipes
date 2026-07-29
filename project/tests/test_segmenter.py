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
