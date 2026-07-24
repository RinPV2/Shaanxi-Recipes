from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline.cli import _apply_title_overrides
from shanxi_pipeline.models import RecipeCandidate


def make_recipe(title: str, book_id: str = "sxcp-2", start_page: int = 74) -> RecipeCandidate:
    return RecipeCandidate(
        title=title,
        aliases=[],
        series=2,
        book_id=book_id,
        book_file="陕西菜谱2.pdf",
        local_pages=[start_page, start_page + 1],
        source_pdf="a.pdf",
        source_json="a.json",
        ingredients=[],
        seasonings=[],
        steps=[],
        tips=[],
        raw_excerpt="",
        related_notes=[],
        ocr_engine="",
        confidence="high",
        status="recipe",
        review_needed=False,
        source_links=[],
    )


class TitleOverrideTests(unittest.TestCase):
    def test_applies_override_and_keeps_alias(self) -> None:
        recipe = make_recipe("烧肚当裆")
        log: list[dict] = []
        _apply_title_overrides([recipe], {"sxcp-2": {74: "烧肚裆"}}, log)
        self.assertEqual(recipe.title, "烧肚裆")
        self.assertIn("烧肚当裆", recipe.aliases)
        self.assertEqual(log[0]["mode"], "title_override")

    def test_skips_when_multiple_recipes_start_on_page(self) -> None:
        first = make_recipe("菜一")
        second = make_recipe("菜二")
        log: list[dict] = []
        _apply_title_overrides([first, second], {"sxcp-2": {74: "别的名"}}, log)
        self.assertEqual(first.title, "菜一")
        self.assertEqual(second.title, "菜二")
        self.assertEqual(log, [])

    def test_noop_when_title_already_correct(self) -> None:
        recipe = make_recipe("烧肚裆")
        log: list[dict] = []
        _apply_title_overrides([recipe], {"sxcp-2": {74: "烧肚裆"}}, log)
        self.assertEqual(recipe.aliases, [])
        self.assertEqual(log, [])
