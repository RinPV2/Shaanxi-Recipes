from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline.page_review_builder import render_page_review_markdown


class PageReviewBuilderTests(unittest.TestCase):
    def test_renders_review_markdown_with_confirmation(self) -> None:
        page = {
            "book_id": "sxcp-2",
            "series": 2,
            "local_page": 9,
            "confidence": "high",
            "review_needed": True,
            "source_pdf_path": "a.pdf",
            "source_json_path": "a.json",
            "title_candidates": ["（一）猪肉小炒"],
            "warnings": ["multiple recipe title candidates on one page"],
            "cleaned_text": "猪肉小炒",
            "raw_text": "猪肉小炒",
        }
        markdown = render_page_review_markdown(
            page=page,
            book_file="陕西菜谱2.pdf",
            image_path="image.png",
            recipe_candidates=[{"title": "猪肉小炒"}],
            fallback_candidates=[],
            confirmation={"notes": "内容正确", "correct_content": "", "confirm_mark": "[x]"},
        )
        self.assertIn("# sxcp-2 p.9", markdown)
        self.assertIn("- notes: 内容正确", markdown)
        self.assertIn("- 确认勾: [x]", markdown)
