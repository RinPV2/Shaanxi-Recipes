from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline.correction_applier import apply_correction, split_correct_content
from shanxi_pipeline.models import NormalizedPage


def make_page(blocks: list[dict]) -> NormalizedPage:
    return NormalizedPage(
        book_id="sxcp-2",
        book_file="陕西菜谱2.pdf",
        series=2,
        local_page=74,
        source_pdf_path="a.pdf",
        source_json_path="a.json",
        raw_text="\n".join(block["text"] for block in blocks),
        cleaned_text="",
        text_blocks=[dict(block) for block in blocks],
        title_candidates=[block["text"] for block in blocks if block["block_type"] == "title"],
    )


class SplitCorrectContentTests(unittest.TestCase):
    def test_splits_only_on_spaced_slash(self) -> None:
        self.assertEqual(
            split_correct_content("松鼠鱼… (76) / 红烧鲤鱼… (77)"),
            ["松鼠鱼… (76)", "红烧鲤鱼… (77)"],
        )

    def test_keeps_bare_slash_intact(self) -> None:
        self.assertEqual(split_correct_content("葱段5克/姜末3克"), ["葱段5克/姜末3克"])


class LinePatchTests(unittest.TestCase):
    def test_patches_most_similar_block(self) -> None:
        page = make_page(
            [
                {"block_type": "text", "text": "一、原料：猪肉五两", "bbox": None, "index": 0},
                {"block_type": "text", "text": "一、原料：猪肚五两", "bbox": None, "index": 1},
            ]
        )
        result = apply_correction(page, "一、原料：猪肚五两,冬笋一两")
        self.assertEqual(result["mode"], "line_patch")
        self.assertEqual(result["patched"], 1)
        self.assertEqual(page.text_blocks[1]["text"], "一、原料：猪肚五两,冬笋一两")
        self.assertEqual(page.text_blocks[0]["text"], "一、原料：猪肉五两")
        self.assertTrue(page.structure_hints["correction_applied"])

    def test_corrected_title_line_becomes_title_block(self) -> None:
        page = make_page(
            [
                {"block_type": "text", "text": "（七四） 烧肚当裆", "bbox": None, "index": 0},
                {"block_type": "text", "text": "一、原料：猪肚一个", "bbox": None, "index": 1},
            ]
        )
        result = apply_correction(page, "（七四） 烧肚裆")
        self.assertEqual(result["patched"], 1)
        self.assertEqual(page.text_blocks[0]["block_type"], "title")
        self.assertIn("（七四） 烧肚裆", page.title_candidates)
        self.assertIn("（七四） 烧肚裆", page.raw_text)

    def test_unmatched_line_is_reported(self) -> None:
        page = make_page([{"block_type": "text", "text": "完全无关的文字", "bbox": None, "index": 0}])
        result = apply_correction(page, "（十二）清蒸甲鱼")
        self.assertEqual(result["patched"], 0)
        self.assertEqual(result["unmatched"], ["（十二）清蒸甲鱼"])
        self.assertNotIn("correction_applied", page.structure_hints)

    def test_duplicate_lines_do_not_patch_same_block_twice(self) -> None:
        page = make_page(
            [
                {"block_type": "text", "text": "锅烧全鸡… (90)", "bbox": None, "index": 0},
                {"block_type": "text", "text": "雪花鸡… (90)", "bbox": None, "index": 1},
            ]
        )
        result = apply_correction(page, "雪花鸡… (90) / 锅烧全鸡… (90)")
        self.assertEqual(result["patched"], 2)
        texts = [block["text"] for block in page.text_blocks]
        self.assertIn("雪花鸡… (90)", texts)
        self.assertIn("锅烧全鸡… (90)", texts)


class FullPageTests(unittest.TestCase):
    def test_full_page_rebuild_marks_titles(self) -> None:
        page = make_page([{"block_type": "text", "text": "乱码", "bbox": None, "index": 0}])
        result = apply_correction(page, "【整页】禽蛋类 / （八九）滑炒鸡丝 / 一、原料：鸡脯肉四两")
        self.assertEqual(result["mode"], "full_page")
        self.assertEqual(result["patched"], 3)
        self.assertEqual(page.text_blocks[0]["block_type"], "title")  # 禽蛋类
        self.assertEqual(page.text_blocks[1]["block_type"], "title")  # 枚举号菜名
        self.assertEqual(page.text_blocks[2]["block_type"], "text")
        self.assertEqual(page.title_candidates, ["禽蛋类", "（八九）滑炒鸡丝"])


class BlockReplacementTests(unittest.TestCase):
    def test_normalize_applies_replacements_to_blocks(self) -> None:
        from shanxi_pipeline.page_normalizer import normalize_page

        page = make_page(
            [
                {"block_type": "text", "text": "用60^{\\circ}热水", "bbox": None, "index": 0},
                {"block_type": "text", "text": "放入滚水锅里氽一下", "bbox": None, "index": 1},
            ]
        )
        rules = {
            "text_replacements": [
                {"pattern": r"\^\{\\circ\}", "replacement": "°"},
                {"pattern": "氽", "replacement": "汆"},
            ],
            "section_aliases": {"ingredients": [], "seasonings": [], "steps": [], "tips": []},
            "ignored_title_exact": [],
            "generic_title_keywords": [],
        }
        thresholds = {"sparse_text_chars": 1, "medium_text_chars": 2, "high_text_chars": 3}
        normalize_page(page, rules, thresholds)
        self.assertEqual(page.text_blocks[0]["text"], "用60°热水")
        self.assertEqual(page.text_blocks[1]["text"], "放入滚水锅里汆一下")


class TocEntryGuardTests(unittest.TestCase):
    def test_toc_entry_with_page_ref_is_not_title(self) -> None:
        page = make_page([{"block_type": "text", "text": "乱", "bbox": None, "index": 0}])
        apply_correction(page, "【整页】水产类 / （二八）炸豆奶… (27) / 41.红烧肘子… (40)")
        types = [b["block_type"] for b in page.text_blocks]
        self.assertEqual(types, ["title", "text", "text"])

    def test_line_patch_does_not_promote_toc_entry(self) -> None:
        page = make_page([{"block_type": "text", "text": "（二八）炸豆好… (27)", "bbox": None, "index": 0}])
        apply_correction(page, "（二八）炸豆奶… (27)")
        self.assertEqual(page.text_blocks[0]["block_type"], "text")


class InsertLineTests(unittest.TestCase):
    def test_insert_line_prepends_block(self) -> None:
        page = make_page([{"block_type": "text", "text": "二、制法：", "bbox": None, "index": 0}])
        result = apply_correction(page, "【补行】水淀粉 一两 辣椒油 一两")
        self.assertEqual(result["patched"], 1)
        self.assertEqual(page.text_blocks[0]["text"], "水淀粉 一两 辣椒油 一两")
        self.assertEqual(page.text_blocks[0]["block_type"], "text")
        self.assertEqual(page.text_blocks[1]["text"], "二、制法：")
        self.assertIn("水淀粉 一两 辣椒油 一两", page.raw_text)


class AnchoredInsertTests(unittest.TestCase):
    def test_insert_before_anchor_block(self) -> None:
        page = make_page(
            [
                {"block_type": "text", "text": "鳝鱼煮馍的收尾文字", "bbox": None, "index": 0},
                {"block_type": "text", "text": "一、原料：猪肋条肉 十斤（约三十份）", "bbox": None, "index": 1},
            ]
        )
        result = apply_correction(page, "【补行前:一、原料：猪肋条肉 十斤（约三十份）】（二）红肉煮馍")
        self.assertEqual(result["patched"], 1)
        self.assertEqual(page.text_blocks[1]["text"], "（二）红肉煮馍")
        self.assertEqual(page.text_blocks[1]["block_type"], "title")
        self.assertEqual(page.text_blocks[2]["text"], "一、原料：猪肋条肉 十斤（约三十份）")
