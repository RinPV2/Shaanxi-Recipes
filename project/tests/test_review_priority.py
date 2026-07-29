from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline.review_priority import (
    _classify_page,
    _extract_toc_entries,
    _resolve_toc_local_pages,
)


class ReviewPriorityTests(unittest.TestCase):
    def test_extracts_toc_entries_from_confirmed_content(self) -> None:
        content = (
            "目录 / 猪牛羊肉类 / 猪肉小炒…（1） / 水煮肉片…（1） / "
            "酱爆肉丝…（2） / 烂糊肉丝…（3）"
        )
        rows = _extract_toc_entries(content)
        self.assertEqual(4, len(rows))
        self.assertEqual("猪牛羊肉类", rows[0]["category"])
        self.assertEqual("猪肉小炒", rows[0]["title"])
        self.assertEqual(1, rows[0]["local_page"])
        self.assertEqual("烂糊肉丝", rows[-1]["title"])

    def test_review_control_markers_are_stripped_before_parsing(self) -> None:
        # 【整页】等控制标记是给回灌器的指令前缀,漏剥会写出「【整页】41.红烧肘子」这种菜名,
        # 以及「【整页】水产类」这种分类。
        content = (
            "【整页】目录 / 水产类 / 41.红烧肘子… (40) / "
            "【补行】42.清蒸鲤鱼… (41) / 【替行:43 炸鱼】43.干炸带鱼… (42)"
        )
        rows = _extract_toc_entries(content)
        self.assertEqual(["红烧肘子", "清蒸鲤鱼", "干炸带鱼"], [row["title"] for row in rows])
        self.assertEqual({"水产类"}, {row["category"] for row in rows})

    def test_leading_chinese_numeral_of_dish_name_is_kept(self) -> None:
        # 书2/书4 的目录条目不编号,菜名可以以汉字数字开头;不能当序号剥掉。
        content = "水产类 / 五香鱼… (33) / 三不粘… (103) / 四季豆腐… (74) / 五柳凤尾笋… (80)"
        rows = _extract_toc_entries(content)
        self.assertEqual(
            ["五香鱼", "三不粘", "四季豆腐", "五柳凤尾笋"], [row["title"] for row in rows]
        )

    def test_numbered_entries_still_drop_their_enumerator(self) -> None:
        content = "（五九）三原疙瘩面… (59) / 60.箸头面… (60) / 二、汤汁的配制及保养方法… (61)"
        rows = _extract_toc_entries(content)
        # 「二、」也是编号,剥掉后剩下的附录标题再被合法性校验挡下。
        self.assertEqual(["三原疙瘩面", "箸头面"], [row["title"] for row in rows])

    def test_paired_parentheses_in_title_are_not_stripped(self) -> None:
        content = "（六〇）箸头面（油泼面）… (60) / （七五）西安包子（四种）… (73) / （六一）窝窝面… (61)"
        rows = _extract_toc_entries(content)
        self.assertEqual(
            ["箸头面(油泼面)", "西安包子(四种)", "窝窝面"], [row["title"] for row in rows]
        )

    def test_entries_without_dot_leader_are_parsed(self) -> None:
        # 书4 双栏目录只用空格分隔,强求点线会整页丢条目。
        content = "猪牛羊肉类 / 白封肉 (1) / 香肠 (14) / 腊汁肉 (2) / 猪肉小炒…（1.）"
        rows = _extract_toc_entries(content)
        self.assertEqual(["白封肉", "香肠", "腊汁肉", "猪肉小炒"], [row["title"] for row in rows])

    def test_appendix_entries_are_rejected_as_non_dish(self) -> None:
        content = (
            "禽蛋类 / 盐水鸭… (47) / 附：酱卤菜的特点及制作方法… (96) / "
            "二、汤汁的配制及保养方法… (100) / 冷盘的装拼方法… (103)"
        )
        rejected: list[str] = []
        rows = _extract_toc_entries(content, rejected)
        self.assertEqual(["盐水鸭"], [row["title"] for row in rows])
        self.assertEqual(3, len(rejected))

    def test_category_carries_over_to_the_next_toc_page(self) -> None:
        # 分类标题在原书里只印一次,续页直接接着排菜名;不跨页续传就会整段丢分类。
        state: dict[str, str] = {}
        first = _extract_toc_entries(
            "水产类 / 酱汁鱼… (29) / 熏黄花鱼… (29) / 软酥鱼… (30)",
            category_state=state,
        )
        second = _extract_toc_entries(
            "爆鱼… (34) / 风白鱼… (35) / 脆鳝鱼… (35)",
            category_state=state,
        )
        self.assertEqual({"水产类"}, {row["category"] for row in first})
        self.assertEqual({"水产类"}, {row["category"] for row in second})

    def test_non_toc_page_does_not_pollute_category_context(self) -> None:
        state = {"category": "水产类"}
        self.assertEqual([], _extract_toc_entries("一、原料 / 鲤鱼 一条", category_state=state))
        self.assertEqual({"category": "水产类"}, state)

    def test_resolves_printed_pages_to_local_pages(self) -> None:
        # 目录印的是原书页码,与本地页差 7–13 且册内不固定;照印刷页码查分类会把分类
        # 边界整体放早。这里用「菜名精确匹配正文」定位,匹配不上的按目录顺序插值。
        toc_map = {
            "sxcp-1": {
                1: [{"title": "净炒肉片", "local_page": 1, "category": "猪牛羊肉类"}],
                2: [{"title": "查无此菜", "local_page": 2, "category": "猪牛羊肉类"}],
                3: [{"title": "莲菜炒肉片", "local_page": 3, "category": "猪牛羊肉类"}],
                4: [{"title": "虾子蛋卷", "local_page": 4, "category": "猪牛羊肉类"}],
            }
        }
        recipe_map = {
            ("sxcp-1", 11): [{"title": "净炒肉片", "aliases": []}],
            ("sxcp-1", 13): [{"title": "莲菜炒肉片", "aliases": []}],
            ("sxcp-1", 14): [{"title": "虾子蛋卷（如意卷）", "aliases": []}],
        }
        resolved, stats = _resolve_toc_local_pages(toc_map, recipe_map)
        by_title = {
            entry["title"]: entry
            for entries in resolved["sxcp-1"].values()
            for entry in entries
        }
        self.assertEqual(11, by_title["净炒肉片"]["local_page"])
        self.assertEqual(13, by_title["莲菜炒肉片"]["local_page"])
        # 括号批注只在正文侧 → 宽松键命中,不该退化成插值
        self.assertEqual(14, by_title["虾子蛋卷"]["local_page"])
        self.assertEqual("matched_folded", by_title["虾子蛋卷"]["page_source"])
        # 插值必须落在两侧已定位锚点之间,并保持单调
        self.assertEqual(12, by_title["查无此菜"]["local_page"])
        self.assertEqual("interpolated", by_title["查无此菜"]["page_source"])
        # 印刷页码保留备查
        self.assertEqual([1, 2, 3, 4], [by_title[t]["printed_page"] for t in
                                       ("净炒肉片", "查无此菜", "莲菜炒肉片", "虾子蛋卷")])
        self.assertEqual({"matched": 2, "matched_folded": 1, "interpolated": 1}, stats)

    def test_multi_anchor_page_is_not_forced_into_must_review(self) -> None:
        page = {
            "book_id": "sxcp-2",
            "local_page": 27,
            "confidence": "high",
            "warnings": ["multiple recipe title candidates on one page"],
            "title_candidates": ["（二一）炸玫瑰球", "（二二）干炸丸子"],
            "structure_hints": {"page_kind": "recipe"},
        }
        row = _classify_page(
            page=page,
            recipe_anchors=[{"title": "炸玫瑰球"}, {"title": "干炸丸子"}],
            expected_toc_entries=[],
            confirmation=None,
            title_override=None,
        )
        self.assertEqual("safe_to_skip", row["bucket"])
        self.assertFalse(row["reasons"])
        self.assertTrue(any("multi-anchor page" in note for note in row["notes"]))


if __name__ == "__main__":
    unittest.main()

class TitleOverrideExtractionTests(unittest.TestCase):
    def test_toc_style_line_is_not_a_title_override(self) -> None:
        from shanxi_pipeline.review_priority import _extract_page_title_override

        self.assertEqual("", _extract_page_title_override("（二八）炸豆奶… (27)"))

    def test_plain_enumerated_title_is_extracted(self) -> None:
        from shanxi_pipeline.review_priority import _extract_page_title_override

        self.assertEqual("烧肚裆", _extract_page_title_override("（七四） 烧肚裆"))


class PlaceholderIngredientTests(unittest.TestCase):
    """「▢」是校对员给认不出的字留的占位符，不清洗、不猜字，只当校对信号往上报。

    落在原料区的占位符最要紧：书2 p102「▢淀粉 二钱」实为湿淀粉，
    书1 p75「菜籽油 ▢钱」、书2 p103「葱段 ▢钱」缺的是用量。
    """

    def _page(self, book_id: str, local_page: int, blocks: list[dict]) -> dict:
        return {
            "book_id": book_id,
            "local_page": local_page,
            "confidence": "high",
            "warnings": [],
            "title_candidates": [],
            "structure_hints": {"page_kind": "recipe"},
            "text_blocks": blocks,
        }

    def test_only_placeholders_inside_the_ingredient_region_are_collected(self) -> None:
        from shanxi_pipeline.review_priority import _placeholder_ingredient_lines

        pages = [
            self._page(
                "sxcp-2",
                102,
                [
                    {"block_type": "title", "text": "（五〇）熬炒子鸡"},
                    {"block_type": "title", "text": "一、原料："},
                    {"block_type": "text", "text": "▢淀粉 二钱"},
                    {"block_type": "title", "text": "二、制法："},
                    {"block_type": "text", "text": "1. 形状▢▢（原书墨迹模糊）。"},
                ],
            )
        ]
        found = _placeholder_ingredient_lines(pages)
        self.assertEqual({("sxcp-2", 102): ["▢淀粉 二钱"]}, found)

    def test_placeholder_page_is_lifted_out_of_safe_to_skip(self) -> None:
        page = {
            "book_id": "sxcp-1",
            "local_page": 75,
            "confidence": "high",
            "warnings": [],
            "title_candidates": ["（六四）棋盘肉"],
            "structure_hints": {"page_kind": "recipe"},
        }
        base = _classify_page(
            page=page,
            recipe_anchors=[{"title": "棋盘肉"}],
            expected_toc_entries=[],
            confirmation={"confirmed": True},
            title_override=None,
        )
        self.assertEqual("safe_to_skip", base["bucket"])

        flagged = _classify_page(
            page=page,
            recipe_anchors=[{"title": "棋盘肉"}],
            expected_toc_entries=[],
            confirmation={"confirmed": True},
            title_override=None,
            placeholder_lines=["味精 二分 菜籽油 ▢钱"],
        )
        self.assertEqual("optional_sample", flagged["bucket"])
        self.assertFalse(flagged["reasons"])
        self.assertTrue(any("placeholder" in note for note in flagged["notes"]))
