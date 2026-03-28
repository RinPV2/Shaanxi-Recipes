from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fitz

from shanxi_pipeline.pdf_splitter import split_pdf_file


class PdfSplitterTests(unittest.TestCase):
    def test_splits_pdf_by_page_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.pdf"
            doc = fitz.open()
            for _ in range(5):
                doc.new_page()
            doc.save(source)
            doc.close()

            output_root = root / "out"
            segments = split_pdf_file(source, output_root, max_pages=2, max_bytes=10 * 1024 * 1024, stem_prefix="test")
            self.assertEqual(len(segments), 3)
            self.assertEqual(segments[0]["page_count"], 2)
            self.assertEqual(segments[1]["page_count"], 2)
            self.assertEqual(segments[2]["page_count"], 1)
