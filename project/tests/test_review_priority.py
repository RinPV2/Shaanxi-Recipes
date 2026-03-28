from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline.review_priority import _classify_page, _extract_toc_entries


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
