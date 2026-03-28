from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline.markdown_writer import fallback_filename, recipe_filename
from shanxi_pipeline.models import PageFallbackNote, RecipeCandidate


class FilenameGenerationTests(unittest.TestCase):
    def test_recipe_filename_is_deterministic(self) -> None:
        recipe = RecipeCandidate(
            title="（一）猪肉小炒",
            aliases=[],
            series=2,
            book_id="sxcp-2",
            book_file="陕西菜谱2.pdf",
            local_pages=[9],
            source_pdf="a.pdf",
            source_json="a.json",
            ingredients=[],
            seasonings=[],
            steps=[],
            tips=[],
            raw_excerpt="",
            related_notes=[],
            ocr_engine="mineru",
            confidence="high",
            status="recipe",
            review_needed=False,
            source_links=[],
        )
        self.assertEqual(recipe_filename(recipe), "sxcp-2-p0009-(一)猪肉小炒.md")

    def test_fallback_filename(self) -> None:
        note = PageFallbackNote(
            title="sxcp-2 第3页 页面回退",
            series=2,
            book_id="sxcp-2",
            book_file="陕西菜谱2.pdf",
            local_pages=[3],
            source_pdf="a.pdf",
            source_json="a.json",
            raw_excerpt="",
            cleaned_text="",
            related_notes=[],
            ocr_engine="mineru",
            confidence="low",
            status="toc",
            review_needed=True,
            source_links=[],
        )
        self.assertEqual(fallback_filename(note), "sxcp-2-page-0003-fallback.md")
