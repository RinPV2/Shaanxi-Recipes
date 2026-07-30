from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline.models import RecipeCandidate
from shanxi_pipeline.title_policy import (
    MANUAL_ALIASES,
    TOC_ALIAS_PAIRS,
    apply_title_policy,
    attach_manual_aliases,
    attach_toc_aliases,
    core_title,
    to_fullwidth_parens,
)


def make(title: str, book_id: str = "sxcp-1", page: int = 1, aliases=None) -> RecipeCandidate:
    return RecipeCandidate(
        title=title,
        aliases=list(aliases or []),
        series=1,
        book_id=book_id,
        book_file="陕西菜谱1.pdf",
        local_pages=[page],
        source_pdf="",
        source_json="",
        ingredients=[],
        seasonings=[],
        steps=[],
        tips=[],
        raw_excerpt="",
        related_notes=[],
        ocr_engine="",
        confidence="high",
        status="ok",
        review_needed=False,
        source_links=[],
    )


class FullwidthParenTests(unittest.TestCase):
    def test_halfwidth_parens_become_fullwidth(self) -> None:
        self.assertEqual("扒牛（羊）肉条", to_fullwidth_parens("扒牛(羊)肉条"))
        self.assertEqual("菊花干贝（酿菜）", to_fullwidth_parens("菊花干贝(酿菜)"))

    def test_paren_width_change_does_not_create_an_alias(self) -> None:
        # 半角→全角只是排版差异,记成「又作：」只是噪音（笔记文件名与 URL 走 NFKC,
        # 一直是半角,也不会因此改变）。
        recipes = [make("风干小肚(又名香肚)")]
        changes = apply_title_policy(recipes)
        self.assertEqual("风干小肚（又名香肚）", recipes[0].title)
        self.assertEqual([], recipes[0].aliases)
        self.assertEqual(1, len(changes))

    def test_already_fullwidth_title_is_untouched(self) -> None:
        recipes = [make("焖牛（羊）肉")]
        self.assertEqual([], apply_title_policy(recipes))
        self.assertEqual("焖牛（羊）肉", recipes[0].title)
        self.assertEqual([], recipes[0].aliases)

    def test_alias_equal_to_normalized_title_is_dropped(self) -> None:
        # title_override 遗留:标题半角、alias 全角,归一后两者重合。
        recipes = [make("菊花干贝(酿菜)", aliases=["菊花干贝（酿菜）"])]
        apply_title_policy(recipes)
        self.assertEqual("菊花干贝（酿菜）", recipes[0].title)
        self.assertEqual([], recipes[0].aliases)


class QingsuAnnotationTests(unittest.TestCase):
    def test_qingsu_annotation_is_stripped_into_alias(self) -> None:
        recipes = [make("糖醋荸荠（清素）")]
        apply_title_policy(recipes)
        self.assertEqual("糖醋荸荠", recipes[0].title)
        # 「清素」不能凭空丢失:留在 alias 里,站点搜索索引与「又作：」都收 aliases。
        self.assertEqual(["糖醋荸荠（清素）"], recipes[0].aliases)

    def test_other_annotations_are_kept_in_the_title(self) -> None:
        for title in (
            "炒凉粉（粉鱼）",
            "螺旋油饼（原名金钱油饼）",
            "西安包子（四种）",
            "凉面皮（酿皮子）",
            "虾籽蛋卷（如意卷）",
            "菊花干贝（酿菜）",
            "风干小肚（又名香肚）",
        ):
            recipes = [make(title)]
            apply_title_policy(recipes)
            self.assertEqual(title, recipes[0].title)
            self.assertEqual([], recipes[0].aliases)

    def test_paren_group_of_a_variant_name_is_not_an_annotation(self) -> None:
        # 「牛（羊）肉煮馍」的括号是「可换成羊肉」的意思,不是批注,不能剥。
        recipes = [make("牛（羊）肉煮馍")]
        apply_title_policy(recipes)
        self.assertEqual("牛（羊）肉煮馍", recipes[0].title)

    def test_core_title_drops_every_annotation(self) -> None:
        self.assertEqual("炒凉粉", core_title("炒凉粉（粉鱼）"))
        self.assertEqual("炒拨鱼", core_title("炒拨鱼(附，拨鱼方法)"))


class TocAliasTests(unittest.TestCase):
    def test_one_char_apart_toc_title_becomes_alias(self) -> None:
        recipes = [make("海参烀蹄子", page=150)]
        attached = attach_toc_aliases(recipes, {"sxcp-1": [("海参煨蹄子", 150)]})
        self.assertEqual(["海参煨蹄子"], recipes[0].aliases)
        self.assertEqual(1, len(attached))

    def test_annotation_only_difference_becomes_alias(self) -> None:
        recipes = [make("炒凉粉（粉鱼）", page=76)]
        attach_toc_aliases(recipes, {"sxcp-1": [("炒凉粉", 76)]})
        self.assertEqual(["炒凉粉"], recipes[0].aliases)

    def test_exact_match_adds_nothing(self) -> None:
        recipes = [make("红烧肘子")]
        self.assertEqual([], attach_toc_aliases(recipes, {"sxcp-1": [("红烧肘子", 1)]}))
        self.assertEqual([], recipes[0].aliases)

    def test_ambiguous_one_char_match_is_refused(self) -> None:
        # 「滑溜里脊片」「焦溜里脊片」都与「炸溜里脊片」差一个字:认不出是哪一道,一个都不认。
        recipes = [make("滑溜里脊片", page=31), make("焦溜里脊片", page=98)]
        self.assertEqual([], attach_toc_aliases(recipes, {"sxcp-1": [("炸溜里脊片", 55)]}))
        self.assertEqual([], recipes[0].aliases)
        self.assertEqual([], recipes[1].aliases)

    def test_different_name_is_refused(self) -> None:
        # 异名（目录「清汤鱿鱼包袱底」对正文两道菜）不认亲:猜是哪一道就是编数据。
        recipes = [make("胡辣鱿鱼丝", page=164), make("清汤鱿鱼芙蓉底", page=164)]
        self.assertEqual([], attach_toc_aliases(recipes, {"sxcp-1": [("清汤鱿鱼包袱底", 164)]}))

    def test_toc_side_appended_note_is_not_an_alias(self) -> None:
        # 「（附…）」是目录自己的交叉引用,不是别名:甜翠稍梅还是另一道菜。
        recipes = [make("糯米稍梅", book_id="sxcp-3", page=89), make("炒拨鱼", book_id="sxcp-3", page=77)]
        self.assertEqual(
            [],
            attach_toc_aliases(
                recipes,
                {"sxcp-3": [("糯米稍梅（附甜翠稍梅）", 89), ("炒拨鱼（附，拨鱼方法）", 77)]},
            ),
        )
        self.assertEqual([], recipes[0].aliases)
        self.assertEqual([], recipes[1].aliases)

    def test_toc_side_plain_annotation_is_an_alias(self) -> None:
        # 括号批注只在目录一侧、且不是「附…」时仍然认亲。
        recipes = [make("腊汁肉", book_id="sxcp-4", page=10)]
        attach_toc_aliases(recipes, {"sxcp-4": [("腊汁肉（又名樊记肉）", 10)]})
        self.assertEqual(["腊汁肉（又名樊记肉）"], recipes[0].aliases)

    def test_ambiguity_is_broken_by_the_anchor_page(self) -> None:
        # 目录「牛肉脆」同时与「牛肉脯」(p34)、「牛肉松」(p31) 差一个字;
        # 锚点落在 p34,只留同页的那一道。
        recipes = [make("牛肉松", book_id="sxcp-4", page=31), make("牛肉脯", book_id="sxcp-4", page=34)]
        attached = attach_toc_aliases(recipes, {"sxcp-4": [("牛肉脆", 34)]})
        self.assertEqual(1, len(attached))
        self.assertEqual([], recipes[0].aliases)
        self.assertEqual(["牛肉脆"], recipes[1].aliases)

    def test_edge_separator_is_stripped_from_the_title(self) -> None:
        # 书4 p22 的标题被 OCR 读成「·怪味肚丁」,那个间隔号会一路进文件名和站点 URL。
        recipes = [make("·怪味肚丁", book_id="sxcp-4", page=22)]
        apply_title_policy(recipes)
        self.assertEqual("怪味肚丁", recipes[0].title)
        # 名字**中间**的顿号是原书的并列菜名,不能剥
        rows = [make("大饼、家常饼", book_id="sxcp-3", page=59)]
        apply_title_policy(rows)
        self.assertEqual("大饼、家常饼", rows[0].title)

    def test_toc_titles_of_another_book_are_not_used(self) -> None:
        recipes = [make("海参烀蹄子", book_id="sxcp-1", page=150)]
        self.assertEqual([], attach_toc_aliases(recipes, {"sxcp-2": [("海参煨蹄子", 150)]}))

    def test_halfwidth_toc_paren_matches_fullwidth_title(self) -> None:
        # 目录半角、正文全角:归一后是同一个名字,不该再挂一条 alias。
        recipes = [make("牛（羊）肉煮馍", book_id="sxcp-3", page=12)]
        self.assertEqual([], attach_toc_aliases(recipes, {"sxcp-3": [("牛(羊)肉煮馍", 12)]}))
        self.assertEqual([], recipes[0].aliases)


class NamedTocAliasTests(unittest.TestCase):
    """页图核定的显式认亲名单（TOC_ALIAS_PAIRS）。

    这四条的成因已回页图查明：**原书目录与正文本身不一致**，两边都不是 OCR 错。
    自动判据（单字之差 / 括号批注之差）故意收得紧，认不出「多字之差」，所以显式点名。
    键含册号与本地页 → 页码不对就不认，等于自带一道守卫。
    """

    def test_the_four_page_verified_pairs(self) -> None:
        cases = [
            ("sxcp-2", 46, "锅烧拆骨肉", "锅烧折骨"),
            ("sxcp-2", 52, "红烧肉米金皮", "烧肉米金皮"),
            ("sxcp-2", 54, "清汤捶鸡片", "清汤捶里脊片"),
            ("sxcp-3", 14, "羊（牛）肉小炒煮馍", "牛（羊）肉小炒煮馍"),
        ]
        for book_id, page, title, toc_title in cases:
            with self.subTest(title=title):
                recipes = [make(title, book_id=book_id, page=page)]
                attached = attach_toc_aliases(recipes, {book_id: [(toc_title, page)]})
                self.assertEqual([toc_title], recipes[0].aliases)
                self.assertEqual(
                    [{"book_id": book_id, "title": title, "alias": toc_title}], attached
                )

    def test_halfwidth_toc_paren_still_matches_the_named_pair(self) -> None:
        # 目录锚点里的半角括号先归一为全角再查表（键一律写全角）
        recipes = [make("羊（牛）肉小炒煮馍", book_id="sxcp-3", page=14)]
        attach_toc_aliases(recipes, {"sxcp-3": [("牛(羊)肉小炒煮馍", 14)]})
        self.assertEqual(["牛（羊）肉小炒煮馍"], recipes[0].aliases)

    def test_named_pair_is_page_scoped(self) -> None:
        # 目录锚点落在别的页 → 不认（防目录页码错位时张冠李戴）
        recipes = [make("锅烧拆骨肉", book_id="sxcp-2", page=46)]
        self.assertEqual([], attach_toc_aliases(recipes, {"sxcp-2": [("锅烧折骨", 99)]}))
        self.assertEqual([], recipes[0].aliases)

    def test_named_pair_does_not_leak_onto_another_dish(self) -> None:
        # 同页另有一道菜时，只挂到点名的那一道上
        recipes = [
            make("砂锅豆腐", book_id="sxcp-2", page=54),
            make("清汤捶鸡片", book_id="sxcp-2", page=54),
        ]
        attach_toc_aliases(recipes, {"sxcp-2": [("清汤捶里脊片", 54)]})
        self.assertEqual([], recipes[0].aliases)
        self.assertEqual(["清汤捶里脊片"], recipes[1].aliases)

    def test_named_pair_is_skipped_when_the_dish_is_absent(self) -> None:
        # 正文菜名不在库里（改名/漏切）→ 一个都不认，不猜
        recipes = [make("锅烧折骨肉", book_id="sxcp-2", page=46)]
        self.assertEqual([], attach_toc_aliases(recipes, {"sxcp-2": [("锅烧折骨", 46)]}))

    def test_table_stays_the_four_verified_entries(self) -> None:
        self.assertEqual(
            {
                ("sxcp-2", 46, "锅烧折骨"): "锅烧拆骨肉",
                ("sxcp-2", 52, "烧肉米金皮"): "红烧肉米金皮",
                ("sxcp-2", 54, "清汤捶里脊片"): "清汤捶鸡片",
                ("sxcp-3", 14, "牛（羊）肉小炒煮馍"): "羊（牛）肉小炒煮馍",
            },
            TOC_ALIAS_PAIRS,
        )


class ManualAliasTests(unittest.TestCase):
    """正文自带的菜名变体（MANUAL_ALIASES）。

    书2 p54 清汤捶鸡片 的同页附注：「清汤捶鸡丝，配料亦改成丝」——原书点明的同菜变体。
    """

    def test_manual_alias_is_attached(self) -> None:
        recipes = [make("清汤捶鸡片", book_id="sxcp-2", page=54)]
        attached = attach_manual_aliases(recipes)
        self.assertEqual(["清汤捶鸡丝"], recipes[0].aliases)
        self.assertEqual(
            [{"book_id": "sxcp-2", "title": "清汤捶鸡片", "alias": "清汤捶鸡丝"}], attached
        )

    def test_manual_alias_is_not_duplicated(self) -> None:
        recipes = [make("清汤捶鸡片", book_id="sxcp-2", page=54, aliases=["清汤捶鸡丝"])]
        self.assertEqual([], attach_manual_aliases(recipes))
        self.assertEqual(["清汤捶鸡丝"], recipes[0].aliases)

    def test_manual_alias_requires_book_page_and_title_to_match(self) -> None:
        for book_id, page, title in (
            ("sxcp-1", 54, "清汤捶鸡片"),
            ("sxcp-2", 55, "清汤捶鸡片"),
            ("sxcp-2", 54, "清汤捶里脊片"),
        ):
            with self.subTest(book_id=book_id, page=page, title=title):
                recipes = [make(title, book_id=book_id, page=page)]
                self.assertEqual([], attach_manual_aliases(recipes))
                self.assertEqual([], recipes[0].aliases)

    def test_table_stays_the_single_verified_entry(self) -> None:
        self.assertEqual({("sxcp-2", 54, "清汤捶鸡片"): ("清汤捶鸡丝",)}, MANUAL_ALIASES)


if __name__ == "__main__":
    unittest.main()
