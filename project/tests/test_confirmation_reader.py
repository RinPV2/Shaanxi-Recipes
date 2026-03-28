from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline.confirmation_reader import parse_confirmation_markdown, parse_confirmation_source, summarize_confirmations


class ConfirmationReaderTests(unittest.TestCase):
    def test_parses_confirmed_entry_with_chinese_labels(self) -> None:
        content = """# User Confirmation Queue

## sxcp-2 p.3
- confidence: low
- reasons: page-level fallback requires review
- content_preview: 目录
- notes: 括号改成英文
- 正确内容: 目录 / 猪牛羊肉类
- 确认勾: [x]
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "queue.md"
            path.write_text(content, encoding="utf-8")
            rows = parse_confirmation_markdown(path)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["confirmed"])
        self.assertEqual(rows[0]["correct_content"], "目录 / 猪牛羊肉类")

    def test_summarizes_repeatable_rules(self) -> None:
        rows = [
            {"confirmed": True, "notes": "括号改成英文", "correct_content": "", "book_id": "sxcp-2", "local_page": 3},
            {"confirmed": True, "notes": "去除多余空格", "correct_content": "", "book_id": "sxcp-2", "local_page": 9},
        ]
        summary = summarize_confirmations(rows)
        rule_names = {item["rule_name"] for item in summary["learned_rules"]}
        self.assertIn("normalize_brackets_to_ascii", rule_names)
        self.assertIn("remove_spurious_inner_spaces", rule_names)

    def test_parses_page_review_directory(self) -> None:
        content = """# sxcp-2 p.9

## 校对记录
- notes: 内容正确
- 正确内容:
- 确认勾: [x]
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book_dir = root / "sxcp-2"
            book_dir.mkdir()
            path = book_dir / "p0009.md"
            path.write_text(content, encoding="utf-8")
            rows = parse_confirmation_source(root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["book_id"], "sxcp-2")
        self.assertTrue(rows[0]["confirmed"])
