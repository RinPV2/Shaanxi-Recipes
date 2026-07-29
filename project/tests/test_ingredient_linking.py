"""食材索引与正文链接化：基名分组、最长优先、标签不被破坏、非食材剔除、陈旧页清理。

上一轮实现食材索引时没有留下任何测试，这个文件补的就是那一块。
"""

from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline import site_builder


def make_index(*groups):
    """把 {基名: [(写法, 菜数)]} 写成 build_ingredient_index 的输出形状。"""
    index = []
    for base, variants in groups:
        index.append(
            {
                "base": base,
                "count": max(n for _name, n in variants),
                "variants": [
                    {"name": name, "recipes": [{"slug": f"s{i}"} for i in range(n)]}
                    for name, n in variants
                ],
            }
        )
    return index


class IngredientBasesTests(unittest.TestCase):
    """基名 = 剥掉状态前后缀后仍站得住的最长残词。规则见 site_builder 注释。"""

    def test_state_prefixes_collapse_onto_an_attested_word(self):
        bases = site_builder.ingredient_bases(["水木耳", "水发木耳", "木耳"])
        self.assertEqual(set(bases.values()), {"木耳"})

    def test_unattested_base_needs_two_prefix_only_supporters(self):
        # 原书从不单写「海参」，但 水海参 / 水发海参 都只剥前缀就汇到它 → 基名成立。
        bases = site_builder.ingredient_bases(["水海参", "水发海参"])
        self.assertEqual(set(bases.values()), {"海参"})
        # 只有一个写法支持时不成立，写法自成基名（不敢凭一条就造词）。
        lonely = site_builder.ingredient_bases(["水海参"])
        self.assertEqual(lonely["水海参"], "水海参")

    def test_suffix_stripping_alone_never_invents_a_base(self):
        # 「玉兰片 → 玉兰」是剥后缀，口径 2 不收；玉兰片保持自己的基名。
        bases = site_builder.ingredient_bases(["玉兰片", "玉兰片丝", "水玉兰片"])
        self.assertEqual(set(bases.values()), {"玉兰片"})

    def test_atomic_names_are_never_stripped(self):
        # 熟面（熟面粉）与面（面粉/面条）不是一味东西。
        bases = site_builder.ingredient_bases(["熟面", "面"])
        self.assertEqual(bases["熟面"], "熟面")
        self.assertEqual(bases["面"], "面")

    def test_single_char_base_only_when_the_book_writes_it_alone(self):
        self.assertEqual(site_builder.ingredient_bases(["姜米", "姜"])["姜米"], "姜")
        # 书里没有单写「肉」时，「肉米」不许剥到单字。
        self.assertEqual(site_builder.ingredient_bases(["肉米"])["肉米"], "肉米")

    def test_transitive_closure_reaches_the_shortest_standing_word(self):
        bases = site_builder.ingredient_bases(["熟火腿丝", "熟火腿", "火腿"])
        self.assertEqual(set(bases.values()), {"火腿"})

    def test_result_does_not_depend_on_input_order(self):
        terms = ["水玉兰片", "玉兰片", "水木耳", "木耳", "熟火腿丝", "火腿"]
        forward = site_builder.ingredient_bases(terms)
        backward = site_builder.ingredient_bases(list(reversed(terms)))
        self.assertEqual(forward, backward)


class BuildIngredientIndexTests(unittest.TestCase):
    def _recipes(self):
        return [
            {
                "slug": "a",
                "book_id": "sxcp-1",
                "ingredients": ["主料：猪肉 四两", "配料：水木耳 二钱"],
                "seasonings": ["调料：食盐 五分"],
            },
            {
                "slug": "b",
                "book_id": "sxcp-1",
                "ingredients": ["主料：木耳 一两"],
                "seasonings": ["调料：食盐 三分"],
            },
        ]

    def test_variants_group_under_one_base_and_count_distinct_dishes(self):
        index = site_builder.build_ingredient_index(self._recipes())
        by_base = {item["base"]: item for item in index}
        self.assertEqual(sorted(v["name"] for v in by_base["木耳"]["variants"]),
                         ["木耳", "水木耳"])
        self.assertEqual(by_base["木耳"]["count"], 2)
        self.assertEqual(by_base["食盐"]["count"], 2)

    def test_index_is_sorted_by_dish_count_then_by_name(self):
        index = site_builder.build_ingredient_index(self._recipes())
        counts = [item["count"] for item in index]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_a_dish_counted_once_even_with_two_variants_of_the_same_base(self):
        recipes = [{"slug": "a", "book_id": "sxcp-1",
                    "ingredients": ["主料：水木耳 二钱", "配料：木耳 一钱"], "seasonings": []}]
        index = site_builder.build_ingredient_index(recipes)
        木耳 = next(i for i in index if i["base"] == "木耳")
        self.assertEqual(木耳["count"], 1)
        self.assertEqual(len(木耳["variants"]), 2)


class NotFoodExclusionTests(unittest.TestCase):
    """INGREDIENT_NOT_FOOD 里的写法压根不是食材，索引与链接都不许收。"""

    def test_season_word_never_enters_the_index(self):
        recipes = [{"slug": "a", "book_id": "sxcp-3",
                    "ingredients": ["面粉 十斤", "酵面夏季 七两", "春秋季 一斤", "冬季 一斤半"],
                    "seasonings": []}]
        bases = {item["base"] for item in site_builder.build_ingredient_index(recipes)}
        self.assertIn("面粉", bases)
        self.assertFalse(bases & {"冬季", "春秋季", "酵面夏季"})

    def test_glued_two_ingredient_fragment_never_enters_the_index(self):
        recipes = [{"slug": "a", "book_id": "sxcp-4", "ingredients": ["盐少许粉面 四两"],
                    "seasonings": ["菜油适量绍酒 一两"]}]
        self.assertEqual(site_builder.build_ingredient_index(recipes), [])

    def test_excluded_form_is_still_shown_in_the_recipe_body_just_not_linked(self):
        recipes = [{"slug": "a", "book_id": "sxcp-3",
                    "ingredients": ["酵面 七两", "冬季 一斤半"], "seasonings": []}]
        index = site_builder.build_ingredient_index(recipes)
        linker = site_builder.IngredientLinker(index)
        row = linker.linkify("冬季 一斤半")
        self.assertEqual(row, "冬季 一斤半")
        self.assertIn("冬季", row)
        self.assertIn('<a class="ing"', linker.linkify("酵面 七两"))

    def test_every_excluded_form_is_documented_with_a_source_comment(self):
        # 名单必须逐条带出处注释，否则后来人无从核实——注释数不得少于条目数。
        source = Path(site_builder.__file__).read_text(encoding="utf-8")
        block = source.split("INGREDIENT_NOT_FOOD = frozenset(", 1)[1].split("\n)", 1)[0]
        self.assertGreaterEqual(
            len([line for line in block.splitlines() if line.strip().startswith("#")]),
            len(site_builder.INGREDIENT_NOT_FOOD) - 8,  # 同页/同条的可共用一条注释
        )
        self.assertIn("sxcp-", block)

    def test_exclusion_list_only_holds_forms_the_book_actually_has(self):
        # 名单里若留下书中已不存在的写法（校对改过），说明名单该缩；用真实 vault 校验。
        vault = Path(__file__).resolve().parents[2] / "work" / "vault"
        if not (vault / "recipes").is_dir():
            self.skipTest("需要真实 vault")
        recipes = site_builder.load_recipes(vault)
        seen = {t for r in recipes for t in site_builder._recipe_terms(r)}
        self.assertEqual(site_builder.INGREDIENT_NOT_FOOD - seen, frozenset())


class LinkifyTests(unittest.TestCase):
    def _linker(self):
        return site_builder.IngredientLinker(
            make_index(
                ("木耳", [("水木耳", 79), ("木耳", 2)]),
                ("食盐", [("食盐", 313)]),
                ("姜", [("姜米", 111)]),
            )
        )

    def test_longest_form_wins_so_a_prefix_is_not_split_off(self):
        html = self._linker().linkify("配料：水木耳 二钱")
        self.assertIn(">水木耳</a>", html)
        self.assertEqual(html.count("<a "), 1)
        # 「木耳」不许抢先切开「水木耳」——切开了链接就指到错的写法锚点上。
        self.assertNotIn("水<a", html)

    def test_link_target_carries_base_page_and_variant_anchor(self):
        html = self._linker().linkify("水木耳 二钱", depth=1)
        self.assertIn('href="../ingredients/木耳.html#v-水木耳"', html)
        self.assertIn('title="水木耳·79 道菜"', html)

    def test_depth_zero_link_has_no_parent_prefix(self):
        html = self._linker().linkify("食盐 五分", depth=0)
        self.assertIn('href="ingredients/食盐.html', html)
        self.assertNotIn("../", html)

    def test_existing_footnote_sup_is_not_broken(self):
        row = '食盐<sup class="fn"><a href="#fn-1" id="fnref-1">1</a></sup> 五分'
        html = self._linker().linkify(row)
        self.assertIn('<sup class="fn">', html)
        self.assertIn('href="#fn-1"', html)
        self.assertIn('id="fnref-1"', html)
        self.assertIn(">食盐</a>", html)
        # 脚注锚点里那个「1」不会被当成正文文本再包一层
        self.assertEqual(html.count('id="fnref-1"'), 1)

    def test_text_inside_an_existing_anchor_is_left_alone(self):
        row = '<a href="x.html">水木耳的故事</a> 与 食盐'
        html = self._linker().linkify(row)
        self.assertIn('<a href="x.html">水木耳的故事</a>', html)  # 不套嵌套锚点
        self.assertIn(">食盐</a>", html)
        self.assertEqual(html.count('class="ing"'), 1)

    def test_annotated_ingredient_gets_both_the_link_and_the_footnote(self):
        rows = {"ingredients": ['水木耳<sup class="fn"><a href="#fn-1">1</a></sup> 二钱']}
        out = self._linker().linkify_rows(rows)
        self.assertIn('class="ing"', out["ingredients"][0])
        self.assertIn('class="fn"', out["ingredients"][0])

    def test_escaped_html_is_matched_and_never_unescaped(self):
        linker = site_builder.IngredientLinker(make_index(("A&B菜", [("A&B菜", 1)])))
        html = linker.linkify("A&amp;B菜 一两")
        self.assertIn("&amp;", html)
        self.assertNotIn("A&B菜 ", html)  # 转义不许被还原
        self.assertIn('title="A&amp;B菜·1 道菜"', html)

    def test_angle_brackets_in_the_row_are_not_treated_as_ingredient_text(self):
        html = self._linker().linkify("&lt;食盐&gt; 五分")
        self.assertIn("&lt;", html)
        self.assertIn(">食盐</a>", html)

    def test_empty_index_is_a_no_op(self):
        linker = site_builder.IngredientLinker([])
        self.assertEqual(linker.linkify("水木耳 二钱"), "水木耳 二钱")

    def test_repeated_occurrences_all_get_linked(self):
        html = self._linker().linkify("食盐 五分，另加食盐 一钱")
        self.assertEqual(html.count('class="ing"'), 2)


class RenderIngredientPagesTests(unittest.TestCase):
    def _item(self):
        return make_index(("木耳", [("水木耳", 2), ("木耳", 1)]))[0]

    def test_page_groups_by_written_form_with_anchors(self):
        html = site_builder.render_ingredient_page(self._item())
        self.assertIn('id="v-水木耳"', html)
        self.assertIn('id="v-木耳"', html)
        self.assertIn("../index.html", html)

    def test_index_lists_every_base(self):
        html = site_builder.render_ingredient_index(make_index(
            ("木耳", [("水木耳", 2)]), ("食盐", [("食盐", 5)])
        ))
        self.assertIn('href="木耳.html"', html)
        self.assertIn('href="食盐.html"', html)

    def test_base_name_is_escaped_in_page_and_index(self):
        item = make_index(("<b>菜", [("<b>菜", 1)]))[0]
        page = site_builder.render_ingredient_page(item)
        idx = site_builder.render_ingredient_index([item])
        for html in (page, idx):
            self.assertNotIn("<b>菜", html)
            self.assertIn("&lt;b&gt;菜", html)

    def test_no_external_hosts_referenced(self):
        html = site_builder.render_ingredient_page(self._item())
        html += site_builder.render_ingredient_index([self._item()])
        for url in ("//cdn", "fonts.googleapis", "unpkg", "jsdelivr", "http://", "https://"):
            self.assertNotIn(url, html.replace(site_builder.REPO_URL, ""))


RECIPE_NOTE = """---
title: {title}
aliases: []
book_id: sxcp-1
local_pages:
- {page}
ingredients:
{ingredients}
seasonings: []
steps:
- 1. 下锅炒熟。
tips: []
status: recipe
review_needed: false
---

# {title}
"""


class BuildSiteIngredientTests(unittest.TestCase):
    def _root(self, notes):
        root = Path(tempfile.mkdtemp())
        recipes = root / "work" / "vault" / "recipes"
        recipes.mkdir(parents=True)
        (root / "project" / "config").mkdir(parents=True)
        (root / "project" / "config" / "annotations.yaml").write_text(
            "annotations: []\n", encoding="utf-8"
        )
        for slug, title, page, ingredients in notes:
            (recipes / f"{slug}.md").write_text(
                RECIPE_NOTE.format(
                    title=title,
                    page=page,
                    ingredients="\n".join(f"- {row}" for row in ingredients),
                ),
                encoding="utf-8",
            )
        return root

    def _default_root(self):
        return self._root([
            ("sxcp-1-p0011-净炒肉片", "净炒肉片", 11, ["主料：水木耳 二钱", "配料：食盐 五分"]),
            ("sxcp-1-p0012-大炒肉片", "大炒肉片", 12, ["主料：木耳 一两"]),
        ])

    def test_one_html_per_base_plus_index(self):
        root = self._root([
            ("sxcp-1-p0011-净炒肉片", "净炒肉片", 11, ["主料：水木耳 二钱", "配料：食盐 五分"]),
            ("sxcp-1-p0012-大炒肉片", "大炒肉片", 12, ["主料：木耳 一两"]),
        ])
        stats = site_builder.build_site(root)
        names = sorted(p.name for p in (root / "ingredients").glob("*.html"))
        self.assertEqual(names, ["index.html", "木耳.html", "食盐.html"])
        self.assertEqual(stats["ingredient_pages"], 2)
        self.assertEqual(stats["ingredient_variants"], 3)

    def test_recipe_page_links_its_ingredients(self):
        root = self._default_root()
        site_builder.build_site(root)
        html = (root / "recipes" / "sxcp-1-p0011-净炒肉片.html").read_text(encoding="utf-8")
        self.assertIn('href="../ingredients/木耳.html#v-水木耳"', html)
        self.assertIn("水木耳", html)

    def test_excluded_form_gets_no_page_but_stays_in_the_recipe_text(self):
        root = self._root([
            ("sxcp-3-p0041-乾州锅盔", "乾州锅盔", 41, ["酵面 七两", "冬季 一斤半"]),
        ])
        stats = site_builder.build_site(root)
        self.assertFalse((root / "ingredients" / "冬季.html").exists())
        self.assertTrue((root / "ingredients" / "酵面.html").exists())
        self.assertEqual(stats["ingredient_pages"], 1)
        html = (root / "recipes" / "sxcp-3-p0041-乾州锅盔.html").read_text(encoding="utf-8")
        self.assertIn("冬季", html)  # 原料文字不能丢
        self.assertNotIn("ingredients/冬季.html", html)  # 只是不再是链接

    def test_stale_ingredient_html_is_pruned(self):
        root = self._default_root()
        site_builder.build_site(root)
        stale = root / "ingredients" / "早先的基名.html"
        stale.write_text("旧页", encoding="utf-8")
        stats = site_builder.build_site(root)
        self.assertEqual(stats["ingredients_pruned"], 1)
        self.assertFalse(stale.exists())
        self.assertTrue((root / "ingredients" / "木耳.html").exists())

    def test_ingredient_index_is_never_pruned(self):
        root = self._default_root()
        site_builder.build_site(root)
        stats = site_builder.build_site(root)
        self.assertEqual(stats["ingredients_pruned"], 0)
        self.assertTrue((root / "ingredients" / "index.html").exists())

    def test_home_page_promotes_the_ingredient_index(self):
        root = self._default_root()
        site_builder.build_site(root)
        html = (root / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="ingredients/index.html"', html)

    def test_no_nested_anchors_anywhere_in_the_output(self):
        root = self._default_root()
        site_builder.build_site(root)
        for path in (root / "recipes").glob("*.html"):
            html = path.read_text(encoding="utf-8")
            depth = 0
            for tag in re.finditer(r"<a[\s>]|</a\s*>", html, re.IGNORECASE):
                depth += 1 if tag.group(0).lower().startswith("<a") else -1
                self.assertIn(depth, (0, 1), f"{path.name} 出现嵌套锚点")
            self.assertEqual(depth, 0)


if __name__ == "__main__":
    unittest.main()
