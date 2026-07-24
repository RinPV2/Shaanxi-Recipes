from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline.page_review_builder import build_page_review_dataset, render_page_review_markdown


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

    def test_rebuild_preserves_existing_in_file_confirmations(self) -> None:
        import json
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work_root = root / "work"
            manifest = root / "book.yaml"
            manifest.write_text(
                "books:\n"
                "- book_id: sxcp-9\n"
                "  series: 9\n"
                "  file_name: test.pdf\n"
                f"  file_path: {(root / 'test.pdf').as_posix()}\n"
                f"  mineru_json: {(root / 'test.json').as_posix()}\n"
                "  status: ready\n"
                "  enabled: true\n",
                encoding="utf-8",
            )
            page_payload = {
                "book_id": "sxcp-9",
                "series": 9,
                "local_page": 1,
                "confidence": "high",
                "review_needed": False,
                "source_pdf_path": "test.pdf",
                "source_json_path": "test.json",
                "title_candidates": [],
                "warnings": [],
                "cleaned_text": "正文",
                "raw_text": "正文",
            }
            normalized_dir = work_root / "normalized_json" / "sxcp-9"
            normalized_dir.mkdir(parents=True)
            (normalized_dir / "page-0001.json").write_text(
                json.dumps(page_payload, ensure_ascii=False), encoding="utf-8"
            )
            review_md = work_root / "page_review_md" / "sxcp-9" / "p0001.md"
            review_md.parent.mkdir(parents=True)
            review_md.write_text(
                "# sxcp-9 p.1\n\n## 校对记录\n- notes: 错字:虫其实是鱼\n- 正确内容: 松鼠鱼… (76)\n- 确认勾: [x]\n",
                encoding="utf-8",
            )
            context = SimpleNamespace(work_root=work_root, book_manifest=manifest)

            build_page_review_dataset(context)

            rebuilt = review_md.read_text(encoding="utf-8")
            self.assertIn("- notes: 错字:虫其实是鱼", rebuilt)
            self.assertIn("- 正确内容: 松鼠鱼… (76)", rebuilt)
            self.assertIn("- 确认勾: [x]", rebuilt)
