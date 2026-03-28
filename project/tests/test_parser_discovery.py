from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline.mineru_json_parser import discover_page_container, extract_text_blocks


class ParserDiscoveryTests(unittest.TestCase):
    def test_discovers_pdf_info_container(self) -> None:
        payload = {"pdf_info": [{"page_idx": 0, "para_blocks": []}]}
        container = discover_page_container(payload)
        self.assertEqual(container[0]["page_idx"], 0)

    def test_extracts_nested_text_blocks(self) -> None:
        blocks = [
            {"type": "title", "lines": [{"spans": [{"content": "（一）猪肉小炒"}]}]},
            {"type": "image", "blocks": [{"type": "text", "lines": [{"spans": [{"content": "一、原料："}]}]}]},
        ]
        extracted = extract_text_blocks(blocks)
        self.assertEqual(extracted[0]["text"], "（一）猪肉小炒")
        self.assertEqual(extracted[1]["text"], "一、原料：")
