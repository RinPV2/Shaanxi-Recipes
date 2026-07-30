"""成品站脚注注释：挂载、编号、失配显形。"""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline import site_builder


def make_recipe(**overrides):
    recipe = {
        "slug": "sxcp-1-p0078-条子肉",
        "title": "条子肉",
        "book_id": "sxcp-1",
        "local_pages": [78, 79],
        "ingredients": ["主料：五花猪肉 半斤"],
        "seasonings": ["湿淀粉 一钱半"],
        "steps": ["1. 猪肉刮洗干净入汤锅煮六成熟捞出。"],
        "tips": ["色红，汤香。"],
    }
    recipe.update(overrides)
    return recipe


def annotation(**overrides):
    item = {
        "book_id": "sxcp-1",
        "local_page": 79,
        "anchor": "湿淀粉 一钱半",
        "note": "原书此条之后还有「菜籽油 平两」。",
    }
    item.update(overrides)
    return item


class AttachAnnotationTests(unittest.TestCase):
    def test_superscript_follows_anchor(self):
        rows, matched, missed = site_builder.attach_annotations(
            make_recipe(), [annotation()]
        )
        self.assertEqual(len(matched), 1)
        self.assertEqual(missed, [])
        self.assertEqual(
            rows["seasonings"][0],
            '湿淀粉 一钱半<sup class="fn"><a id="fnref-1" href="#fn-1">1</a></sup>',
        )

    def test_anchor_inside_longer_line_keeps_tail(self):
        recipe = make_recipe(steps=["另座炒勺将蜂蜜倒入飞成蜜汁，将丸子放入。"])
        rows, matched, _ = site_builder.attach_annotations(
            recipe, [annotation(anchor="倒入飞成蜜汁")]
        )
        self.assertEqual(len(matched), 1)
        self.assertIn("倒入飞成蜜汁<sup", rows["steps"][0])
        self.assertTrue(rows["steps"][0].endswith("，将丸子放入。"))

    def test_unmatched_anchor_is_reported_not_swallowed(self):
        rows, matched, missed = site_builder.attach_annotations(
            make_recipe(), [annotation(anchor="并不存在的锚文本")]
        )
        self.assertEqual(matched, [])
        self.assertEqual(len(missed), 1)
        self.assertNotIn("<sup", "".join(rows["seasonings"]))

    def test_numbering_follows_reading_order_across_sections(self):
        items = [
            annotation(anchor="色红", note="第三"),
            annotation(anchor="猪肉刮洗", note="第二"),
            annotation(anchor="五花猪肉", note="第一"),
        ]
        rows, matched, missed = site_builder.attach_annotations(make_recipe(), items)
        self.assertEqual(missed, [])
        self.assertEqual([m["note"] for m in matched], ["第一", "第二", "第三"])
        self.assertIn('href="#fn-1"', rows["ingredients"][0])
        self.assertIn('href="#fn-2"', rows["steps"][0])
        self.assertIn('href="#fn-3"', rows["tips"][0])

    def test_two_annotations_in_one_line_number_left_to_right(self):
        recipe = make_recipe(steps=["划成 “▤” 形，背面划成 “⊠” 形。"])
        items = [
            annotation(anchor="“⊠” 形", note="交叉"),
            annotation(anchor="“▤” 形", note="横线"),
        ]
        rows, matched, _ = site_builder.attach_annotations(recipe, items)
        self.assertEqual([m["note"] for m in matched], ["横线", "交叉"])
        self.assertLess(
            rows["steps"][0].index('href="#fn-1"'), rows["steps"][0].index('href="#fn-2"')
        )

    def test_anchor_with_html_special_chars_is_escaped_consistently(self):
        recipe = make_recipe(tips=["用量 <半两> & 适量"])
        rows, matched, _ = site_builder.attach_annotations(
            recipe, [annotation(anchor="<半两> &")]
        )
        self.assertEqual(len(matched), 1)
        self.assertIn("&lt;半两&gt; &amp;<sup", rows["tips"][0])


class CandidateSelectionTests(unittest.TestCase):
    def test_matches_any_page_of_a_multi_page_recipe(self):
        picked = site_builder.annotations_for_recipe(
            [annotation(local_page=79)], make_recipe(), set()
        )
        self.assertEqual(len(picked), 1)

    def test_other_book_or_page_is_not_a_candidate(self):
        items = [annotation(local_page=200), annotation(book_id="sxcp-2")]
        self.assertEqual(
            site_builder.annotations_for_recipe(items, make_recipe(), set()), []
        )

    def test_slug_pins_the_annotation_to_one_note(self):
        item = annotation(slug="sxcp-1-p0079-虾米肉", local_page=79)
        self.assertEqual(site_builder.annotations_for_recipe([item], make_recipe(), set()), [])
        other = make_recipe(slug="sxcp-1-p0079-虾米肉", local_pages=[79, 80])
        self.assertEqual(len(site_builder.annotations_for_recipe([item], other, set())), 1)

    def test_claimed_annotation_is_not_offered_twice(self):
        item = annotation()
        self.assertEqual(
            site_builder.annotations_for_recipe([item], make_recipe(), {id(item)}), []
        )


class RenderTests(unittest.TestCase):
    def test_footnote_block_carries_backlinks(self):
        html = site_builder.render_footnotes([annotation(note="甲"), annotation(note="乙")])
        self.assertIn("<summary>注释（2）</summary>", html)
        self.assertIn('<li id="fn-1">甲 <a class="fn-back" href="#fnref-1"', html)
        self.assertIn('<li id="fn-2">乙 <a class="fn-back" href="#fnref-2"', html)

    def test_no_annotations_renders_nothing(self):
        self.assertEqual(site_builder.render_footnotes([]), "")

    def test_recipe_page_has_superscript_before_footnote_section(self):
        html = site_builder.render_recipe_page(
            make_recipe(), "肉菜", "https://example.invalid", [annotation()]
        )
        self.assertIn('湿淀粉 一钱半<sup class="fn">', html)
        self.assertLess(html.index('<sup class="fn">'), html.index('<details class="notes"'))
        # 注释区在正文之后、纠错按钮之前，属于页底区域
        self.assertLess(html.index('<details class="notes"'), html.index('class="report"'))

    def test_recipe_page_without_annotations_is_plain(self):
        html = site_builder.render_recipe_page(
            make_recipe(), "肉菜", "https://example.invalid"
        )
        self.assertNotIn("<sup", html)
        self.assertNotIn('class="notes"', html)


class LoadAnnotationsTests(unittest.TestCase):
    def _write(self, text: str) -> Path:
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "annotations.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(site_builder.load_annotations(Path("no-such-file.yaml")), [])

    def test_pending_entries_are_not_loaded(self):
        path = self._write(
            "annotations:\n"
            "  - book_id: sxcp-1\n    local_page: 79\n    anchor: 甲\n    note: 乙\n"
            "pending:\n"
            "  - book_id: sxcp-4\n    local_page: 113\n    anchor: 缯肘\n    note: 丙\n"
        )
        loaded = site_builder.load_annotations(path)
        self.assertEqual([i["anchor"] for i in loaded], ["甲"])

    def test_incomplete_entry_is_dropped(self):
        path = self._write(
            "annotations:\n"
            "  - book_id: sxcp-1\n    local_page: 79\n    anchor: 甲\n"
            "  - book_id: sxcp-1\n    local_page: 79\n    anchor: 乙\n    note: 丙\n"
        )
        self.assertEqual([i["anchor"] for i in site_builder.load_annotations(path)], ["乙"])

    def test_broken_yaml_does_not_break_the_build(self):
        path = self._write("annotations: [unclosed\n")
        self.assertEqual(site_builder.load_annotations(path), [])

    def test_real_config_file_parses(self):
        path = Path(__file__).resolve().parents[1] / "config" / "annotations.yaml"
        loaded = site_builder.load_annotations(path)
        self.assertGreaterEqual(len(loaded), 3)
        for item in loaded:
            self.assertTrue(item["anchor"].strip())
            self.assertTrue(item["note"].strip())

    def test_glyph_decision_notes_are_present(self):
        """2026-07-30 的两个字形决策必须**有注可查**，否则读者无从判断与推翻。

        「爦」多数字体渲染不出（会显示成方框），「臊子」则是把原书一贯的「稍子」
        归到了现代汉语写法——两条都属于「不注读者会误解」，故列进回归测试。
        """
        path = Path(__file__).resolve().parents[1] / "config" / "annotations.yaml"
        loaded = site_builder.load_annotations(path)
        lan = [item for item in loaded if "爦" in item["anchor"]]
        self.assertTrue(lan, "干爦 的注释不见了")
        for item in lan:
            self.assertIn("lǎn", item["note"])
            self.assertIn("方框", item["note"])
        sao = [item for item in loaded if item.get("slug") == "sxcp-3-p0072-岐山面"]
        self.assertTrue(sao, "臊子 用字归一的注释不见了")
        self.assertIn("稍子", sao[0]["note"])


class BuildSiteAccountingTests(unittest.TestCase):
    """在一个最小假仓库上跑 build_site，验证 stats 与失配计数。"""

    def _fake_root(self, annotations_yaml: str) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "work" / "vault" / "recipes").mkdir(parents=True)
        (root / "project" / "config").mkdir(parents=True)
        (root / "work" / "vault" / "recipes" / "sxcp-1-p0078-条子肉.md").write_text(
            "---\n"
            "title: 条子肉\n"
            "book_id: sxcp-1\n"
            "local_pages:\n- 78\n- 79\n"
            "seasonings:\n- 湿淀粉 一钱半\n"
            "steps:\n- 1. 猪肉刮洗干净。\n"
            "---\n\n# 条子肉\n",
            encoding="utf-8",
        )
        (root / "project" / "config" / "annotations.yaml").write_text(
            annotations_yaml, encoding="utf-8"
        )
        return root

    def test_matched_annotation_counts_and_renders(self):
        root = self._fake_root(
            "annotations:\n"
            "  - book_id: sxcp-1\n    local_page: 79\n"
            "    anchor: 湿淀粉 一钱半\n    note: 原书此后还有菜籽油 平两。\n"
        )
        stats = site_builder.build_site(root)
        self.assertEqual(stats["annotations"], 1)
        self.assertEqual(stats["annotations_rendered"], 1)
        self.assertEqual(stats["annotations_unmatched"], 0)
        html = (root / "recipes" / "sxcp-1-p0078-条子肉.html").read_text(encoding="utf-8")
        self.assertIn('<sup class="fn">', html)
        self.assertIn('<details class="notes"', html)

    def test_unmatched_annotation_shows_up_in_stats(self):
        root = self._fake_root(
            "annotations:\n"
            "  - book_id: sxcp-1\n    local_page: 79\n"
            "    anchor: 湿淀粉 一钱半\n    note: 命中的。\n"
            "  - book_id: sxcp-1\n    local_page: 79\n"
            "    anchor: 书上没有这句话\n    note: 落空的。\n"
            "  - book_id: sxcp-3\n    local_page: 9\n"
            "    anchor: 别册的页码\n    note: 也落空。\n"
        )
        with self.assertLogs("shanxi_pipeline.site_builder", level="WARNING") as logs:
            stats = site_builder.build_site(root)
        self.assertEqual(stats["annotations"], 3)
        self.assertEqual(stats["annotations_rendered"], 1)
        self.assertEqual(stats["annotations_unmatched"], 2)
        self.assertEqual(sum("未命中" in line for line in logs.output), 2)

    def test_page_html_count_equals_vault_note_count(self):
        root = self._fake_root("annotations: []\n")
        stats = site_builder.build_site(root)
        notes = list((root / "work" / "vault" / "recipes").glob("*.md"))
        pages = list((root / "recipes").glob("*.html"))
        self.assertEqual(len(pages), len(notes))
        self.assertEqual(stats["recipes"], len(notes))


if __name__ == "__main__":
    unittest.main()
