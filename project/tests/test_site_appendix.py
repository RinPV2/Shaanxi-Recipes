"""回退页(page_fallbacks/)上站：发布范围、渲染、注释挂载、陈旧页清理。"""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline import site_builder


FALLBACK_NOTE = """---
title: {book} 第{page}页 页面回退
book_id: {book}
local_pages:
- {page}
status: {status}
review_needed: {review}
raw_excerpt: '不该出现在正文里的摘录'
---

# {book} 第{page}页 页面回退

## 来源
- 书目: 陕西菜谱4.pdf
- 本地页码: {page}

## 页面文本
{text}

## OCR 不确定内容
- 无
"""


def write_fallback(directory: Path, book: str, page: int, text: str,
                   status: str = "continuation", review: str = "false") -> Path:
    path = directory / f"{book}-page-{page:04d}-fallback.md"
    path.write_text(
        FALLBACK_NOTE.format(book=book, page=page, text=text, status=status, review=review),
        encoding="utf-8",
    )
    return path


def make_page(**overrides):
    page = {
        "slug": "sxcp-4-p0113",
        "title": "冷盘的装拼方法（1/4）",
        "article": "冷盘的装拼方法",
        "kind": "附录",
        "book_id": "sxcp-4",
        "local_pages": [113],
        "page": 113,
        "index": 1,
        "total": 4,
        "prev": "",
        "next": "sxcp-4-p0114",
        "review_needed": False,
        "body": ["冷盘的装拼方法", "反之把酱猪肝、云彩卷、缯肘、三鲜酿肚等原料，灵活运用。"],
    }
    page.update(overrides)
    return page


class LoadFallbackTests(unittest.TestCase):
    def _vault(self) -> Path:
        vault = Path(tempfile.mkdtemp()) / "vault"
        (vault / "page_fallbacks").mkdir(parents=True)
        return vault

    def test_missing_directory_is_not_an_error(self):
        self.assertEqual(site_builder.load_page_fallbacks(Path(tempfile.mkdtemp())), [])

    def test_page_text_section_becomes_body_paragraphs(self):
        vault = self._vault()
        write_fallback(vault / "page_fallbacks", "sxcp-4", 113, "第一段\n第二段")
        notes = site_builder.load_page_fallbacks(vault)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["body"], ["第一段", "第二段"])
        self.assertEqual(notes[0]["local_pages"], [113])
        self.assertEqual(notes[0]["note_slug"], "sxcp-4-page-0113-fallback")

    def test_frontmatter_excerpt_and_source_section_stay_out_of_body(self):
        vault = self._vault()
        write_fallback(vault / "page_fallbacks", "sxcp-4", 113, "正文一句")
        body = site_builder.load_page_fallbacks(vault)[0]["body"]
        self.assertEqual(body, ["正文一句"])
        self.assertNotIn("不该出现在正文里的摘录", "".join(body))
        self.assertNotIn("本地页码", "".join(body))


class AppendixPlanTests(unittest.TestCase):
    """发布范围由 APPENDIX_ARTICLES 白名单决定，其余回退页只进 skipped。"""

    def _notes(self):
        return [
            {"note_slug": "a", "book_id": "sxcp-4", "local_pages": [113], "status": "continuation",
             "review_needed": False, "body": ["甲"]},
            {"note_slug": "b", "book_id": "sxcp-4", "local_pages": [114], "status": "continuation",
             "review_needed": False, "body": ["乙"]},
            {"note_slug": "toc", "book_id": "sxcp-1", "local_pages": [5], "status": "toc",
             "review_needed": True, "body": ["目录"]},
        ]

    def test_only_whitelisted_pages_are_published(self):
        published, skipped = site_builder.appendix_plan(self._notes())
        self.assertEqual([p["slug"] for p in published], ["sxcp-4-p0113", "sxcp-4-p0114"])
        self.assertEqual([n["note_slug"] for n in skipped], ["toc"])

    def test_published_pages_get_article_grouping_and_neighbours(self):
        published, _ = site_builder.appendix_plan(self._notes())
        first, second = published
        self.assertEqual(first["article"], "冷盘的装拼方法")
        self.assertEqual(first["kind"], "附录")
        self.assertEqual((first["prev"], first["next"]), ("", "sxcp-4-p0114"))
        self.assertEqual((second["prev"], second["next"]), ("sxcp-4-p0113", ""))
        self.assertEqual(first["total"], 2)

    def test_single_page_article_title_has_no_counter(self):
        notes = [{"note_slug": "c", "book_id": "sxcp-4", "local_pages": [120],
                  "status": "unresolved", "review_needed": False, "body": ["版权"]}]
        published, _ = site_builder.appendix_plan(notes)
        self.assertEqual(published[0]["title"], "版权页")

    def test_missing_note_for_a_whitelisted_page_warns(self):
        with self.assertLogs("shanxi_pipeline.site_builder", level="WARNING") as logs:
            published, _ = site_builder.appendix_plan(self._notes())
        self.assertTrue(any("缺少回退笔记" in line for line in logs.output))
        self.assertEqual(len(published), 2)

    def test_real_vault_whitelist_is_fully_covered(self):
        vault = Path(__file__).resolve().parents[2] / "work" / "vault"
        if not (vault / "page_fallbacks").is_dir():
            self.skipTest("需要真实 vault")
        published, skipped = site_builder.appendix_plan(site_builder.load_page_fallbacks(vault))
        expected = sum(len(a["pages"]) for a in site_builder.APPENDIX_ARTICLES)
        self.assertEqual(len(published), expected)
        self.assertTrue(all(p["body"] for p in published))
        self.assertTrue(skipped)


class RenderAppendixTests(unittest.TestCase):
    def test_body_renders_as_paragraphs_with_page_scan(self):
        html = site_builder.render_appendix_page(make_page(), "https://example.invalid")
        self.assertIn("<p>冷盘的装拼方法</p>", html)
        self.assertIn('src="../assets/pages/sxcp-4/p0113.webp"', html)
        self.assertIn("原书 第四册 第 113 页", html)
        self.assertIn("<h1>冷盘的装拼方法（1/4）</h1>", html)

    def test_pager_links_stay_inside_the_article(self):
        html = site_builder.render_appendix_page(make_page(), "")
        self.assertIn('<a href="sxcp-4-p0114.html">下一页 →</a>', html)
        self.assertNotIn("上一页", html)
        self.assertIn('<a href="index.html">', html)

    def test_report_button_points_at_the_appendix_url(self):
        html = site_builder.render_appendix_page(make_page(), "https://example.invalid")
        self.assertIn("example.invalid/appendix/sxcp-4-p0113.html", html.replace("%3A//", "://"))
        self.assertIn("%E9%99%84%E5%BD%95%E9%A1%B5", html)  # 「附录页」而不是「菜谱」

    def test_low_confidence_page_carries_the_warning(self):
        html = site_builder.render_appendix_page(make_page(review_needed=True), "")
        self.assertIn('class="warn"', html)

    def test_empty_body_falls_back_to_the_scan(self):
        html = site_builder.render_appendix_page(make_page(body=[]), "")
        self.assertIn("请直接看右侧页图", html)
        self.assertIn("p0113.webp", html)

    def test_html_in_body_is_escaped(self):
        html = site_builder.render_appendix_page(make_page(body=["<script>x</script>"]), "")
        self.assertNotIn("<script>x", html)
        self.assertIn("&lt;script&gt;x", html)

    def test_no_external_hosts_referenced(self):
        html = site_builder.render_appendix_page(make_page(), "")
        html += site_builder.render_appendix_index([make_page()], [])
        for url in ("//cdn", "fonts.googleapis", "unpkg", "jsdelivr"):
            self.assertNotIn(url, html)


class AppendixIndexTests(unittest.TestCase):
    def test_articles_are_grouped_with_per_page_links(self):
        pages = [make_page(), make_page(slug="sxcp-4-p0114", page=114, local_pages=[114])]
        html = site_builder.render_appendix_index(pages, [])
        self.assertIn("<h2>冷盘的装拼方法</h2>", html)
        self.assertIn('<a href="sxcp-4-p0113.html">第 113 页</a>', html)
        self.assertIn('<a href="sxcp-4-p0114.html">第 114 页</a>', html)

    def test_skipped_pages_only_get_a_scan_link(self):
        skipped = [{"note_slug": "t", "book_id": "sxcp-1", "local_pages": [5], "status": "toc",
                    "review_needed": True, "body": ["目录"]}]
        html = site_builder.render_appendix_index([make_page()], skipped)
        self.assertIn("目录页", html)
        self.assertIn('href="../assets/pages/sxcp-1/p0005.webp"', html)
        self.assertNotIn("sxcp-1-p0005.html", html)


class HomeEntryTests(unittest.TestCase):
    def test_home_page_links_to_the_appendix_index(self):
        html = site_builder.render_index_page([], ["肉菜"], [make_page()])
        self.assertIn('href="appendix/index.html"', html)
        self.assertIn("冷盘的装拼方法", html)

    def test_home_page_without_appendix_has_no_promo(self):
        html = site_builder.render_index_page([], ["肉菜"], [])
        self.assertNotIn('class="promo"', html)

    def test_topbar_link_is_depth_aware(self):
        # 只锁「深度前缀正确」，不锁 nav 内的排列次序——加「食材索引」入口后
        # 它排在附录之前，原先的 '<nav><a href=…' 前缀断言会误报。
        recipe_html = site_builder.render_appendix_page(make_page(), "")
        self.assertIn('<nav>', recipe_html)
        self.assertIn('href="../appendix/index.html"', recipe_html)
        home_html = site_builder.render_index_page([], [], [])
        self.assertIn('<nav>', home_html)
        self.assertIn('href="appendix/index.html"', home_html)


class BuildSiteAppendixTests(unittest.TestCase):
    def _fake_root(self, annotations_yaml: str = "annotations: []\n") -> Path:
        root = Path(tempfile.mkdtemp())
        fallbacks = root / "work" / "vault" / "page_fallbacks"
        fallbacks.mkdir(parents=True)
        (root / "work" / "vault" / "recipes").mkdir(parents=True)
        (root / "project" / "config").mkdir(parents=True)
        write_fallback(
            fallbacks, "sxcp-4", 113,
            "冷盘的装拼方法\n反之把酱猪肝、云彩卷、缯肘、三鲜酿肚等原料，灵活运用。",
        )
        write_fallback(fallbacks, "sxcp-4", 114, "糖醋排骨和鲜嫩黄瓜排在一起。")
        write_fallback(fallbacks, "sxcp-1", 5, "目录", status="toc", review="true")
        (root / "project" / "config" / "annotations.yaml").write_text(
            annotations_yaml, encoding="utf-8"
        )
        return root

    def test_only_whitelisted_fallbacks_become_html(self):
        root = self._fake_root()
        stats = site_builder.build_site(root)
        names = sorted(p.name for p in (root / "appendix").glob("*.html"))
        self.assertEqual(
            names, ["index.html", "sxcp-4-p0113.html", "sxcp-4-p0114.html"]
        )
        self.assertEqual(stats["appendix_pages"], 2)
        self.assertEqual(stats["fallbacks_skipped"], 1)
        # 未发布的页不许在 appendix/ 里留下文件
        self.assertFalse((root / "appendix" / "sxcp-1-p0005.html").exists())

    def test_annotation_attaches_to_an_appendix_page(self):
        root = self._fake_root(
            "annotations:\n"
            "  - book_id: sxcp-4\n    local_page: 113\n"
            "    anchor: 缯肘\n    note: 「缯肘」不是错字，是真实的菜名。\n"
        )
        stats = site_builder.build_site(root)
        self.assertEqual(stats["annotations_rendered"], 1)
        self.assertEqual(stats["annotations_unmatched"], 0)
        html = (root / "appendix" / "sxcp-4-p0113.html").read_text(encoding="utf-8")
        self.assertIn('缯肘<sup class="fn">', html)
        self.assertIn("是真实的菜名", html)

    def test_annotation_can_be_pinned_to_an_appendix_slug(self):
        root = self._fake_root(
            "annotations:\n"
            "  - book_id: sxcp-4\n    local_page: 113\n    slug: sxcp-4-p0113\n"
            "    anchor: 缯肘\n    note: 挂到这一页。\n"
        )
        stats = site_builder.build_site(root)
        self.assertEqual(stats["annotations_unmatched"], 0)

    def test_annotation_missing_on_an_appendix_page_is_reported(self):
        root = self._fake_root(
            "annotations:\n"
            "  - book_id: sxcp-4\n    local_page: 113\n"
            "    anchor: 页上没有这几个字\n    note: 落空的。\n"
        )
        with self.assertLogs("shanxi_pipeline.site_builder", level="WARNING") as logs:
            stats = site_builder.build_site(root)
        self.assertEqual(stats["annotations_unmatched"], 1)
        self.assertTrue(any("未命中" in line for line in logs.output))

    def test_stale_appendix_html_is_pruned(self):
        root = self._fake_root()
        site_builder.build_site(root)
        stale = root / "appendix" / "sxcp-4-p0999.html"
        stale.write_text("旧页", encoding="utf-8")
        stats = site_builder.build_site(root)
        self.assertEqual(stats["appendix_pruned"], 1)
        self.assertFalse(stale.exists())
        self.assertTrue((root / "appendix" / "index.html").exists())

    def test_appendix_index_is_never_pruned(self):
        root = self._fake_root()
        site_builder.build_site(root)
        stats = site_builder.build_site(root)
        self.assertEqual(stats["appendix_pruned"], 0)

    def test_recipes_directory_is_untouched_by_the_appendix(self):
        root = self._fake_root()
        stats = site_builder.build_site(root)
        self.assertEqual(stats["recipes"], 0)
        self.assertEqual(list((root / "recipes").glob("*.html")), [])


if __name__ == "__main__":
    unittest.main()
