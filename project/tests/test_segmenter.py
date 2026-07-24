from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline.models import BookEntry, NormalizedPage
from shanxi_pipeline.recipe_segmenter import segment_book


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
